import json

class ImprovementPathGenerator:
    def generate(self, missing_skills, student_profile, education, experience):
        if not missing_skills:
            return {
                "missing_skills": [],
                "actions": [],
                "estimated_time": "0 weeks",
                "target_score": 100,
                "current_score": 100
            }
        
        actions = []
        skill_resources = {
            'Python': {'action': 'Complete Python Certification Course', 'resource': 'https://coursera.org/python', 'time': '2 weeks'},
            'JavaScript': {'action': 'Learn JavaScript Fundamentals', 'resource': 'https://freecodecamp.org/javascript', 'time': '2 weeks'},
            'SQL': {'action': 'Get SQL Database Certification', 'resource': 'https://sqlzoo.net', 'time': '1 week'},
            'Data Analysis': {'action': 'Complete Data Analysis Specialization', 'resource': 'https://edx.org/data-analysis', 'time': '3 weeks'},
            'Machine Learning': {'action': 'Take ML Course', 'resource': 'https://coursera.org/ml', 'time': '4 weeks'},
            'Communication': {'action': 'Public Speaking Workshop', 'resource': 'https://udemy.com/communication', 'time': '1 week'},
            'Leadership': {'action': 'Leadership Training Program', 'resource': 'https://coursera.org/leadership', 'time': '2 weeks'},
            'Project Management': {'action': 'PMP Certification Prep', 'resource': 'https://pmi.org/pmp', 'time': '3 weeks'},
            'HTML': {'action': 'Learn HTML5', 'resource': 'https://w3schools.com/html', 'time': '1 week'},
            'CSS': {'action': 'Master CSS3', 'resource': 'https://w3schools.com/css', 'time': '1 week'},
            'React': {'action': 'React.js Crash Course', 'resource': 'https://reactjs.org', 'time': '2 weeks'},
            'Node.js': {'action': 'Learn Node.js', 'resource': 'https://nodejs.org', 'time': '2 weeks'},
            'Java': {'action': 'Java Programming Course', 'resource': 'https://coursera.org/java', 'time': '3 weeks'},
            'Excel': {'action': 'Excel Advanced Functions', 'resource': 'https://excel-easy.com', 'time': '1 week'},
        }
        
        for skill in missing_skills:
            resource = skill_resources.get(skill, {'action': f'Complete course for {skill}', 'resource': 'https://www.udemy.com', 'time': '2 weeks'})
            actions.append({
                "skill": skill,
                "action": resource['action'],
                "resource": resource['resource'],
                "time": resource['time']
            })
        
        total_time = sum(int(a['time'].split()[0]) for a in actions if a['time'].split()[0].isdigit())
        current_score = 100 - (len(missing_skills) * 10)
        
        return {
            "missing_skills": list(missing_skills),
            "actions": actions,
            "estimated_time": f"{total_time} weeks",
            "target_score": 100,
            "current_score": max(current_score, 0)
        }