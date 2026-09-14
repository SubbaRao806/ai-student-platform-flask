import re
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Canonical equivalences, applied AFTER lowercasing/stripping.
# Keep this list small and explicit. Easy to modify later.
SKILL_ALIASES = {
    'nodejs': 'node.js',
    'restapi': 'rest api',
    'restapis': 'rest api',
    'powerbi': 'power bi',
    'machinelearning': 'machine learning',
    'deeplearning': 'deep learning',
    'scikitlearn': 'scikit-learn',
    'scikit learn': 'scikit-learn',
    'postgres': 'postgresql',
    'mongo': 'mongodb',
    'js': 'javascript',
    'py': 'python',
    'reactjs': 'react',
    'react.js': 'react',
    'vuejs': 'vue',
    'angularjs': 'angular',
    'c plus plus': 'c++',
    'c sharp': 'c#',
    'dot net': '.net',
}


def normalize_skill(name):
    """Canonical key for a skill name: case/whitespace/punctuation-insensitive."""
    if not name:
        return ''
    key = str(name).strip().lower()
    key = re.sub(r'\s+', ' ', key)
    key = key.strip('.,;:!?()[]{}"\'')
    nospace = key.replace(' ', '').replace('-', '').replace('.', '')
    if nospace in SKILL_ALIASES:
        return SKILL_ALIASES[nospace]
    if key in SKILL_ALIASES:
        return SKILL_ALIASES[key]
    return key


def build_term_map(values):
    """{normalized: display} preserving first-seen display form."""
    terms = {}
    for v in values or []:
        if not v:
            continue
        key = normalize_skill(v)
        if key and key not in terms:
            terms[key] = str(v).strip()
    return terms


def split_technologies(raw):
    """Split a technologies string. Never reads project titles."""
    if not raw:
        return []
    return [p.strip() for p in re.split(r'[,;|/]+', str(raw)) if p.strip()]


class SkillGapAnalyzer:
    """
    Compares STUDENT SKILLS + PROJECT TECHNOLOGIES + RESUME INFORMATION
    against an opportunity's REQUIRED SKILLS.
    Returns exactly: matched skills and missing skills.
    No performance improvement logic lives here.
    """

    def build_student_skill_map(self, skills, projects):
        """
        skills: iterable of skill names from the student profile (dynamic).
        projects: iterable of dicts; only the 'technologies' field is used.
        Returns {normalized: {'display': str, 'sources': [...]}}.
        """
        skill_map = {}
        for name in skills or []:
            if not name:
                continue
            key = normalize_skill(name)
            if not key:
                continue
            entry = skill_map.setdefault(key, {'display': str(name).strip(), 'sources': []})
            if 'profile skills' not in entry['sources']:
                entry['sources'].append('profile skills')

        for p in projects or []:
            if not isinstance(p, dict):
                continue
            for tech in split_technologies(p.get('technologies')):
                key = normalize_skill(tech)
                if not key:
                    continue
                entry = skill_map.setdefault(key, {'display': tech, 'sources': []})
                if 'project technologies' not in entry['sources']:
                    entry['sources'].append('project technologies')
        return skill_map

    def analyze(self, required_skills, student_skill_map, resume_texts=None):
        """
        required_skills: iterable of required skill names (opportunity side).
        student_skill_map: from build_student_skill_map().
        resume_texts: iterable of resume/summary/bio strings. A required
            skill mentioned here counts as evidenced ('resume'), nothing
            is assumed beyond literal mention.
        Returns {'matched': [...], 'missing': [...], 'evidence': {...}}.
        Display names follow the opportunity's required-skill wording.
        """
        required = build_term_map(required_skills)
        resume_blob = ' '.join(str(t or '') for t in (resume_texts or [])).lower()

        matched, missing, evidence = [], [], {}
        for norm, display in required.items():
            entry = (student_skill_map or {}).get(norm)
            if entry:
                matched.append(display)
                evidence[display] = list(entry['sources'])
            elif norm and norm in resume_blob:
                matched.append(display)
                evidence[display] = ['resume']
            else:
                missing.append(display)
        result = {'matched': sorted(matched), 'missing': sorted(missing), 'evidence': evidence}
        logger.info(f"Skill gap: {len(matched)} matched, {len(missing)} missing")
        return result
