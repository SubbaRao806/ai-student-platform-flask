import requests
import json

class AdzunaAPI:
    def __init__(self, app_id, app_key, country='us', host='api-adzuna-com.p.rapidapi.com'):
        self.app_id = app_id
        self.app_key = app_key
        self.country = country
        self.host = host
        self.base_url = "https://api-adzuna-com.p.rapidapi.com/v2"
        self.headers = {
            'X-RapidAPI-Key': app_key,
            'X-RapidAPI-Host': host
        }
    
    def search_opportunities(self, skills, location, page=0, results_per_page=20):
        query = ', '.join(skills) if isinstance(skills, list) else skills
        params = {
            'app_id': self.app_id,
            'app_key': self.app_key,
            'what': query,
            'where': location,
            'content-type': 'blend',
            'page': page,
            'results_per_page': results_per_page,
            'country': self.country
        }
        try:
            response = requests.get(f"{self.base_url}/search/results", 
                                     headers=self.headers, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return data.get('results', [])
            return []
        except requests.exceptions.RequestException:
            return []
    
    def search_by_location_and_type(self, location, job_type='all', skills=None):
        params = {
            'app_id': self.app_id,
            'app_key': self.app_key,
            'where': location,
            'content-type': 'blend',
            'category': job_type if job_type != 'all' else None
        }
        if skills:
            params['what'] = ', '.join(skills) if isinstance(skills, list) else skills
        try:
            response = requests.get(f"{self.base_url}/search/results",
                                     headers=self.headers, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return data.get('results', [])
            return []
        except requests.exceptions.RequestException:
            return []
    
    def get_opportunity_detail(self, source_id, source='adzuna'):
        params = {
            'app_id': self.app_id,
            'app_key': self.app_key
        }
        try:
            response = requests.get(f"{self.base_url}/jobs/{source_id}",
                                     headers=self.headers, params=params, timeout=10)
            if response.status_code == 200:
                return response.json()
            return None
        except requests.exceptions.RequestException:
            return None
