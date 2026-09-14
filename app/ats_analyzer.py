import re
import logging
from collections import Counter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Factor weights. Tune here; skipped factors redistribute proportionally.
ATS_WEIGHTS = {
    'skill_coverage': 0.35,       # required skills mentioned in the resume
    'keyword_coverage': 0.25,     # frequent description keywords in the resume
    'project_relevance': 0.15,    # required skills evidenced in project tech/descriptions
    'role_relevance': 0.10,       # title terms present in the resume
    'education_relevance': 0.15,  # education section + degree detail in the resume
}

STOPWORDS = {
    'the', 'and', 'for', 'with', 'you', 'your', 'our', 'are', 'will',
    'have', 'has', 'had', 'this', 'that', 'from', 'they', 'them',
    'job', 'role', 'work', 'working', 'team', 'join', 'looking',
    'candidate', 'ideal', 'strong', 'good', 'great', 'help', 'including',
    'include', 'required', 'requirements', 'preferred', 'plus', 'ability',
    'experience', 'experienced', 'year', 'years', 'new', 'now', 'day',
    'time', 'apply', 'about', 'into', 'over', 'under', 'such', 'each',
    'other', 'than', 'then', 'also', 'well', 'who', 'what', 'when',
    'where', 'which', 'while', 'within', 'without', 'per', 'via',
    'using', 'use', 'used', 'based', 'related', 'opportunity', 'company',
    'intern', 'internship', 'developer', 'development', 'position',
}

EDUCATION_MARKERS = {'education', 'degree', 'university', 'college', 'institute',
                     'school', 'cgpa', 'gpa', 'graduated', 'graduation', 'academic'}
DEGREE_WORDS = {'bachelor', 'master', 'b.tech', 'm.tech', 'mba', 'phd', 'bca',
                'mca', 'b.sc', 'm.sc', 'b.e', 'm.e', 'associate', 'diploma'}

DISCLAIMER = ('Estimated compatibility only, computed from your saved resume. '
              'This is not the employer\'s actual ATS score.')


def _tokens(text):
    return re.findall(r'[a-z][a-z0-9+#.\-]*', (text or '').lower())


def extract_keywords(title, description, top_n=30):
    """Most frequent non-stopword tokens from the listing. Grounded in the text."""
    words = [t for t in _tokens(f"{title or ''} {description or ''}")
             if len(t) >= 3 and t not in STOPWORDS and not t.replace('.', '').isdigit()]
    ranked = Counter(words).most_common(top_n)
    ranked.sort(key=lambda kv: (-kv[1], kv[0]))
    return [w for w, _ in ranked]


class ATSCompatibilityAnalyzer:
    """Estimated ATS compatibility. Read-only: never modifies the saved resume."""

    def analyze(self, resume_texts, student, opportunity, required_map):
        resume_blob = ' '.join(str(t or '') for t in (resume_texts or []))
        resume_lower = resume_blob.lower()
        source = 'saved resume' if any(resume_texts or []) else 'none'
        required = required_map or {}

        project_blob = ' '.join(
            f"{p.get('technologies') or ''} {p.get('description') or ''}"
            for p in (student.get('projects') or []) if isinstance(p, dict)
        ).lower()

        factors = {}

        covered = [k for k in required if k and k in resume_lower]
        skill_score = round(len(covered) / len(required) * 100) if required else 0
        factors['skill_coverage'] = {
            'score': skill_score, 'weight': ATS_WEIGHTS['skill_coverage'],
            'detail': {'covered': len(covered), 'total_required': len(required)}}

        keywords = extract_keywords(opportunity.get('title'), opportunity.get('description'))
        hits = [k for k in keywords if k in resume_lower]
        kw_score = round(len(hits) / len(keywords) * 100) if keywords else None
        factors['keyword_coverage'] = {
            'score': kw_score, 'weight': ATS_WEIGHTS['keyword_coverage'],
            'detail': {'matched_keywords': hits[:10], 'total_keywords': len(keywords)}}

        in_projects = [k for k in required if k and k in project_blob]
        proj_score = round(len(in_projects) / len(required) * 100) if required else 0
        factors['project_relevance'] = {
            'score': proj_score, 'weight': ATS_WEIGHTS['project_relevance'],
            'detail': {'evidenced_in_projects': len(in_projects), 'total_required': len(required)}}

        title_words = [t for t in _tokens(opportunity.get('title'))
                       if len(t) >= 3 and t not in STOPWORDS]
        if title_words:
            present = [t for t in title_words if t in resume_lower]
            role_score = round(len(present) / len(title_words) * 100)
        else:
            role_score, present = None, []
        factors['role_relevance'] = {
            'score': role_score, 'weight': ATS_WEIGHTS['role_relevance'],
            'detail': {'title_terms_found': present, 'title_terms': title_words}}

        if any(d in resume_lower for d in DEGREE_WORDS):
            edu_score = 100
        elif any(m in resume_lower for m in EDUCATION_MARKERS):
            edu_score = 60
        else:
            edu_score = 30
        factors['education_relevance'] = {
            'score': edu_score, 'weight': ATS_WEIGHTS['education_relevance'],
            'detail': {}}

        available = {k: v for k, v in factors.items() if v['score'] is not None}
        total_w = sum(v['weight'] for v in available.values())
        score = round(sum(v['score'] * v['weight'] for v in available.values()) / total_w) if total_w else 0

        suggestions = self._suggest(required, covered, keywords, hits,
                                    in_projects, title_words, present, edu_score)
        result = {'score': score, 'estimated': True, 'disclaimer': DISCLAIMER,
                  'factors': factors, 'suggestions': suggestions,
                  'resume_source': source}
        logger.info(f"Estimated ATS compatibility: {score}/100")
        return result

    def _suggest(self, required, covered, keywords, hits, in_projects,
                 title_words, present, edu_score):
        suggestions = []
        missing_req = [required[k] for k in required if k not in set(covered)]
        for display in missing_req[:3]:
            suggestions.append(f"Add relevant {display} project experience")
        absent_kw = [k for k in keywords if k not in set(hits)][:4]
        if absent_kw:
            suggestions.append(f"Include relevant technical keywords: {', '.join(absent_kw)}")
        missing_proj = [required[k] for k in required if k not in set(in_projects)][:3]
        if missing_proj and len(in_projects) < len(required):
            suggestions.append(f"Improve project descriptions to mention: {', '.join(missing_proj)}")
        absent_role = [t for t in title_words if t not in set(present)][:3]
        if absent_role:
            suggestions.append(f"Mention {'/'.join(absent_role)} role experience in your summary")
        if edu_score < 100:
            suggestions.append("Add an Education section with degree details")
        return suggestions[:6]

    def quick_score(self, resume_texts, student, opportunity, required_map):
        """Lightweight integer score for list views."""
        return int(self.analyze(resume_texts, student, opportunity, required_map)['score'])
