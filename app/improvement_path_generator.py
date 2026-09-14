import re
import logging
from math import ceil

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Pedagogical mapping only: which already-known skills make a missing skill
# easier to practice. This NEVER adds requirements; requirements come solely
# from the opportunity. Extend freely.
RELATED_SKILLS = {
    'rest api': ['flask', 'django', 'node.js', 'node', 'python', 'javascript', 'java'],
    'graphql': ['rest api', 'javascript', 'node.js'],
    'docker': ['linux', 'git', 'python'],
    'kubernetes': ['docker', 'linux'],
    'react': ['javascript', 'html', 'css'],
    'angular': ['typescript', 'javascript', 'html'],
    'vue': ['javascript', 'html', 'css'],
    'node.js': ['javascript'],
    'django': ['python', 'sql'],
    'flask': ['python'],
    'spring': ['java', 'sql'],
    'machine learning': ['python', 'sql', 'data analysis'],
    'deep learning': ['machine learning', 'python'],
    'nlp': ['python', 'machine learning'],
    'tensorflow': ['python', 'machine learning'],
    'pytorch': ['python', 'machine learning'],
    'pandas': ['python', 'sql'],
    'sql': ['excel', 'python'],
    'power bi': ['excel', 'sql', 'data analysis'],
    'tableau': ['excel', 'sql', 'data analysis'],
    'aws': ['linux', 'python'],
    'git': ['github'],
}


class BasePathProvider:
    """Interface for step generation. Implement this with an AI model later."""

    def steps_for(self, skill, display, context):
        raise NotImplementedError


class RuleBasedPathProvider(BasePathProvider):
    """Transparent, data-grounded steps. No invented requirements or URLs."""

    def _find_anchor(self, skill_key, student_skills, description):
        lowered = (description or '').lower()
        for s in sorted(student_skills):
            if s != skill_key and s in lowered and skill_key in lowered:
                return s
        for candidate in RELATED_SKILLS.get(skill_key, []):
            if candidate in student_skills:
                return candidate
        return None

    def _find_project(self, skill_key, required_keys, projects):
        best, best_overlap = None, 0
        for p in projects or []:
            if not isinstance(p, dict):
                continue
            techs = set(t.strip().lower() for t in str(p.get('technologies') or '').replace(';', ',').replace('|', ',').split(',') if t.strip())
            overlap = len((techs | {skill_key}) & set(required_keys))
            if p.get('title') and overlap > best_overlap:
                best, best_overlap = p.get('title'), overlap
        return best

    def _find_integration_target(self, skill_key, required):
        for key in sorted(required.keys()):
            if key != skill_key:
                return required[key]
        return None

    def _pace(self, years_to_graduation):
        if years_to_graduation is not None and years_to_graduation <= 1:
            return {'learn': '3-4 days', 'practice': '2-3 days', 'build': '1 week', 'per_skill_weeks': 2}
        return {'learn': '1 week', 'practice': '1 week', 'build': '1-2 weeks', 'per_skill_weeks': 3}

    def steps_for(self, skill, display, context):
        student_skills = context['student_skills']
        required = context['required']
        projects = context['projects']
        opportunity = context['opportunity']
        pace = self._pace(context.get('years_to_graduation'))
        title = opportunity.get('title') or 'this role'
        company = opportunity.get('company') or 'the employer'
        github_url = context.get('github_url')

        anchor = self._find_anchor(skill, student_skills, opportunity.get('description'))
        project = self._find_project(skill, list(required.keys()), projects)
        target = self._find_integration_target(skill, required)

        steps = [{
            'skill': display,
            'action': f"Learn {display} fundamentals, focusing on how it is used in {title} roles at {company}",
            'resource': f"Search: '{display} fundamentals tutorial'",
            'time': pace['learn'],
        }]
        if anchor:
            anchor_display = context['skill_display'].get(anchor, anchor)
            steps.append({
                'skill': display,
                'action': f"Practice {display} with {anchor_display}: redo a small {anchor_display} task using {display}",
                'resource': f"Search: '{display} with {anchor_display} example'",
                'time': pace['practice'],
            })
        if project:
            steps.append({
                'skill': display,
                'action': f"Extend your project '{project}': add {display} to it and document the change",
                'resource': 'Your existing project repository and README',
                'time': pace['build'],
            })
        else:
            steps.append({
                'skill': display,
                'action': f"Build a small {display} mini-project related to {title} work",
                'resource': f"Search: '{display} mini project ideas'",
                'time': pace['build'],
            })
        if target:
            steps.append({
                'skill': display,
                'action': f"Connect it to {target} end-to-end so the piece works like in a real {title} task",
                'resource': f"Search: '{display} {target} integration example'",
                'time': pace['practice'],
            })
        steps.append({
            'skill': display,
            'action': 'Push the code to GitHub with a README (what you built, how to run it)' + (
                ' on your GitHub profile' if github_url else ''),
            'resource': "Search: 'how to write a good README'",
            'time': pace['practice'],
        })
        steps.append({
            'skill': display,
            'action': f"Add '{display}' to your resume Skills section and the project under Projects",
            'resource': 'Your resume (update it once the project is done)',
            'time': pace['practice'],
        })
        return steps


class ImprovementPathGenerator:
    """
    Personalized improvement paths from Skill Gap missing skills.
    Swap `provider` with an AI-backed BasePathProvider later; callers stay same.
    """

    def __init__(self, provider=None):
        self.provider = provider or RuleBasedPathProvider()

    def prioritize(self, missing_displays, required_map, opportunity):
        """Most-mentioned / title-mentioned skills first. Deterministic."""
        text = ' '.join([
            str(opportunity.get('title') or ''),
            str(opportunity.get('description') or ''),
        ]).lower()
        title = str(opportunity.get('title') or '').lower()
        scored = []
        for display in missing_displays:
            key = next((k for k, v in required_map.items() if v == display), display.lower())
            importance = min(text.count(key), 10)
            if key and key in title:
                importance += 10
            scored.append((importance, display))
        scored.sort(key=lambda t: (-t[0], t[1]))
        return [display for _, display in scored]

    def generate(self, gap, student, opportunity, current_score=0, max_skills=None):
        """
        gap: {'matched': [...], 'missing': [...]} (displays) + required map.
        student: {'skills': set(keys), 'skill_display': {}, 'project_techs': set,
                  'years_to_graduation': int|None, 'projects': [...], 'github_url': str|None}.
        opportunity: dict with title/company/opp_type/description.
        Returns the detail-template contract, or None when nothing is missing.
        """
        missing = list(gap.get('missing') or [])
        if not missing:
            return None
        required = gap.get('required_map') or {}
        ordered = self.prioritize(missing, required, opportunity)
        if max_skills:
            ordered = ordered[:max_skills]

        key_of = {v: k for k, v in required.items()}
        context = {
            'student_skills': set(student.get('skills') or []),
            'skill_display': student.get('skill_display') or {},
            'required': required,
            'projects': student.get('projects') or [],
            'opportunity': opportunity,
            'years_to_graduation': student.get('years_to_graduation'),
            'github_url': student.get('github_url'),
        }
        actions = []
        for display in ordered:
            key = key_of.get(display, display.lower())
            actions.extend(self.provider.steps_for(key, display, context))

        ytg = student.get('years_to_graduation')
        per_skill = 2 if (ytg is not None and ytg <= 1) else 3
        result = {
            'current_score': int(current_score),
            'target_score': 100,
            'estimated_time': f"~{per_skill * len(ordered)} weeks for {len(ordered)} skill(s)",
            'actions': actions,
            'ordered_skills': ordered,
        }
        logger.info(f"Improvement path: {len(ordered)} skills, {len(actions)} actions")
        return result
