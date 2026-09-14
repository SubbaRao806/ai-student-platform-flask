import re
import logging
from datetime import datetime

from skill_gap_analyzer import (
    normalize_skill,
    build_term_map,
    split_technologies,
    SKILL_ALIASES,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scoring weights. Tune these numbers to change ranking behaviour.
# Weights of SKIPPED components (score None) are redistributed proportionally.
# ---------------------------------------------------------------------------
WEIGHTS = {
    'skill_match': 0.50,        # student skills vs required skills
    'project_relevance': 0.25,  # project technologies vs required skills
    'study_year_relevance': 0.10,  # study year vs opportunity type
    'role_relevance': 0.15,     # preferred role/domain vs listing (optional)
}

# Small matching aid used ONLY to detect requirements mentioned in a
# description (e.g. "we need a react developer"). This is not student data.
# Extend freely; matching stays case-insensitive substring-based.
SKILL_VOCABULARY = [
    'python', 'java', 'javascript', 'typescript', 'html', 'css', 'react',
    'angular', 'vue', 'node.js', 'node', 'django', 'flask', 'spring',
    'sql', 'mysql', 'postgresql', 'mongodb', 'excel', 'tableau',
    'power bi', 'data analysis', 'machine learning', 'deep learning',
    'nlp', 'tensorflow', 'pytorch', 'scikit-learn', 'pandas', 'numpy',
    'git', 'docker', 'kubernetes', 'aws', 'azure', 'gcp', 'linux',
    'c++', 'c#', 'php', 'ruby', 'go', 'rust', 'kotlin', 'swift',
    'android', 'ios', 'flutter', 'figma', 'photoshop',
    'communication', 'leadership', 'teamwork', 'project management',
    'problem solving', 'time management', 'adaptability',
]


def _normalize_terms(values):
    """Lowercase/stripped unique terms, preserving a display form map."""
    return build_term_map(values)


def _split_technologies(raw):
    """Split a technologies string on common separators."""
    return split_technologies(raw)


class RecommendationEngine:
    """Transparent, explainable opportunity ranking. No ATS, no improvement paths."""

    WEIGHTS = WEIGHTS

    # -- student profile ----------------------------------------------------
    def build_student_profile(self, skills, projects, education):
        """
        skills: iterable of skill names (dynamic, from DB).
        projects: iterable of dicts with at least 'technologies'.
        education: iterable of dicts with 'start_year' / 'end_year'.
        """
        skill_map = _normalize_terms(skills)
        tech_terms = []
        for p in projects or []:
            if isinstance(p, dict):
                tech_terms.extend(_split_technologies(p.get('technologies')))
        tech_map = _normalize_terms(tech_terms)

        end_years = [e.get('end_year') for e in (education or [])
                     if isinstance(e, dict) and e.get('end_year')]
        years_to_graduation = None
        if end_years:
            try:
                years_to_graduation = int(max(end_years)) - datetime.now().year
            except (TypeError, ValueError):
                years_to_graduation = None

        return {
            'skills': set(skill_map.keys()),
            'skill_display': skill_map,
            'project_techs': set(tech_map.keys()),
            'years_to_graduation': years_to_graduation,
        }

    # -- required skills ----------------------------------------------------
    def resolve_required_skills(self, opportunity, student_skills):
        """
        Explicit required-skills list first; otherwise detect mentions of
        student skills + SKILL_VOCABULARY terms inside the description.
        Never invents: returns only what the listing actually contains.
        """
        explicit = opportunity.get('required_skills_json') or opportunity.get('required_skills') or []
        if isinstance(explicit, str):
            explicit = [explicit]
        found = _normalize_terms(explicit)

        text = ' '.join([
            str(opportunity.get('title') or ''),
            str(opportunity.get('description') or ''),
        ]).lower()
        if text.strip():
            candidates = set(student_skills or []) | set(SKILL_VOCABULARY)
            for term in candidates:
                if term and term in text and term not in found:
                    found[term] = term
        return found  # {normalized: display}

    # -- components ---------------------------------------------------------
    def _skill_match(self, required, student):
        if not required:
            return 0, {'reason': 'no required skills found in listing'}
        matched = set(required) & set(student['skills'])
        score = round(len(matched) / len(required) * 100)
        return score, {'matched': sorted(matched),
                       'total_required': len(required)}

    def _project_relevance(self, required, student):
        if not required:
            return 0, {'reason': 'no required skills found in listing'}
        if not student['project_techs']:
            return 0, {'reason': 'student has no project technologies listed'}
        matched = set(required) & student['project_techs']
        score = round(len(matched) / len(required) * 100)
        return score, {'matched_via_projects': sorted(matched),
                       'total_required': len(required)}

    def _study_year_relevance(self, opportunity, student):
        ytg = student.get('years_to_graduation')
        opp_type = (opportunity.get('opp_type') or opportunity.get('type') or 'job').lower()
        if ytg is None:
            return 50, {'reason': 'no education end year on file (neutral)'}
        if opp_type == 'internship':
            if 0 <= ytg <= 5:
                return 100, {'reason': f'currently studying ({ytg}y to graduation), internships relevant'}
            return 60, {'reason': 'graduated; internships less typical'}
        if ytg <= 1:
            return 100, {'reason': 'final year/graduated; jobs highly relevant'}
        if ytg == 2:
            return 70, {'reason': 'pre-final year; jobs moderately relevant'}
        return 40, {'reason': f'{ytg}y to graduation; jobs less relevant yet'}

    def _role_relevance(self, opportunity, preferred_role):
        if not preferred_role or not str(preferred_role).strip():
            return None, {'reason': 'no preferred role/domain on file (excluded)'}
        role = str(preferred_role).strip().lower()
        haystack = ' '.join([
            str(opportunity.get('title') or ''),
            str(opportunity.get('category') or ''),
            str(opportunity.get('description') or '')[:2000],
        ]).lower()
        if role in haystack:
            return 100, {'reason': f'preferred role "{preferred_role}" appears in listing'}
        return 20, {'reason': f'preferred role "{preferred_role}" not found in listing'}

    # -- scoring ------------------------------------------------------------
    def score(self, opportunity, student, preferred_role=None):
        required = self.resolve_required_skills(opportunity, student['skills'])

        parts = {}
        parts['skill_match'] = self._skill_match(required, student)
        parts['project_relevance'] = self._project_relevance(required, student)
        parts['study_year_relevance'] = self._study_year_relevance(opportunity, student)
        parts['role_relevance'] = self._role_relevance(opportunity, preferred_role)

        available = {k: v for k, v in parts.items() if v[0] is not None}
        total_w = sum(self.WEIGHTS[k] for k in available)
        final = round(sum(v[0] * self.WEIGHTS[k] for k, v in available.items()) / total_w) if total_w else 0

        breakdown = {}
        for key, (comp_score, detail) in parts.items():
            breakdown[key] = {
                'score': comp_score,
                'weight': self.WEIGHTS[key],
                'detail': detail,
            }

        matched = sorted(set(required) & student['skills'])
        missing = sorted(set(required) - student['skills'])
        return {
            'score': final,
            'required_skills': sorted(required.keys()),
            'matched_skills': matched,
            'missing_skills': missing,
            'breakdown': breakdown,
        }

    def rank(self, opportunities, student, preferred_role=None):
        """
        Score every opportunity and return them sorted highest-first.
        Each item is a copy with 'match_percent' and JSON-safe 'match_breakdown'.
        Only call with active (non-expired) opportunities.
        """
        ranked = []
        for opp in opportunities or []:
            result = self.score(opp, student, preferred_role)
            item = dict(opp)
            item['match_percent'] = result['score']
            item['match_breakdown'] = result['breakdown']
            item['matched_skills_list'] = result['matched_skills']
            item['missing_skills_list'] = result['missing_skills']
            ranked.append(item)
        ranked.sort(key=lambda o: o['match_percent'], reverse=True)
        logger.info(f"Ranked {len(ranked)} opportunities")
        return ranked
