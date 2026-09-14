import json
import re

class ATSScorer:
    def analyze_resume(self, resume_text, required_skills):
        if not resume_text or not required_skills:
            return 0
        resume_lower = resume_text.lower()
        matched = 0
        for skill in required_skills:
            if skill.lower() in resume_lower:
                matched += 1
        return round((matched / len(required_skills)) * 100)
    
    def calculate_compatibility(self, student_profile, education, experience, required_skills):
        score = 0
        total = len(required_skills) if required_skills else 1
        
        # Skill match (40%)
        skill_match = self.analyze_resume(student_profile.get('summary', '') + ' ' + ' '.join(required_skills), required_skills) if required_skills else 0
        score += (skill_match / 100) * 40
        
        # Education match (25%)
        if education:
            degree = education[0].get('degree_type', '').lower() if education else ''
            if 'bachelor' in degree or 'master' in degree or 'phd' in degree or 'btech' in degree or 'mba' in degree:
                score += 25
            else:
                score += 10
        else:
            score += 5
        
        # Experience match (20%)
        if experience:
            score += 20
        else:
            score += 5
        
        # Profile completeness (15%)
        profile_fields = ['full_name', 'email', 'phone_number', 'dob', 'address', 'summary']
        filled = sum(1 for f in profile_fields if student_profile.get(f))
        score += (filled / len(profile_fields)) * 15
        
        return round(score)
    
    def extract_keywords(self, description):
        if not description:
            return []
        keywords = re.findall(r'\b[A-Z][a-z]+\b', description)
        return list(set(keywords))
    
    def calculate_ats_score(self, resume_text, required_skills, education, experience, profile):
        skill_score = self.analyze_resume(resume_text, required_skills) if required_skills else 0
        compat_score = self.calculate_compatibility(profile, education, experience, required_skills)
        final_score = round((skill_score * 0.6) + (compat_score * 0.4))
        return min(final_score, 100)
