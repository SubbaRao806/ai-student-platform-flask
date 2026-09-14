import os
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Common internal job structure. Every provider (Adzuna, Jooble, Jobvetta,
# IndianAPI) converts its own API response into exactly these keys.
# Values may be None when the source does not supply them -- never invented.
# ---------------------------------------------------------------------------
COMMON_FIELDS = (
    'provider',          # e.g. 'Adzuna' | 'Jooble' | 'Jobvetta' | 'IndianAPI'
    'provider_job_id',   # unique ID within that provider (string)
    'title',
    'company',
    'location',
    'description',       # full text or snippet, as supplied
    'employment_type',   # 'job' | 'internship' | provider label | None
    'salary',            # display string | None
    'skills',            # list of requirement strings (may be empty)
    'posted_date',       # ISO 'YYYY-MM-DD' | None
    'updated_date',      # ISO 'YYYY-MM-DD' | None
    'apply_url',         # legitimate application link | None
    'source_url',        # original listing page | None
    'extra',             # dict for provider-specific leftovers
)


def blank_common(provider):
    """Empty common-format record with safe defaults."""
    return {
        'provider': provider,
        'provider_job_id': None,
        'title': None,
        'company': None,
        'location': None,
        'description': None,
        'employment_type': None,
        'salary': None,
        'skills': [],
        'posted_date': None,
        'updated_date': None,
        'apply_url': None,
        'source_url': None,
        'extra': {},
    }


def to_iso_date(value):
    """Best-effort date normalisation. Returns 'YYYY-MM-DD' or None."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    try:
        from datetime import date as _date
        if isinstance(value, _date):
            return value.isoformat()
    except Exception:
        pass
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value)).date().isoformat()
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()[:10]
        try:
            return datetime.strptime(text, '%Y-%m-%d').date().isoformat()
        except ValueError:
            return None
    return None


class BaseJobProvider:
    """Independent provider contract. Subclass per source; never share state."""

    name = 'base'
    env_key_names = ()

    def __init__(self):
        self.credentials_present = all(os.environ.get(k) for k in self.env_key_names)
        if self.env_key_names and not self.credentials_present:
            logger.info(f"Provider '{self.name}' not configured "
                        f"(missing {list(self.env_key_names)}). It will stay idle.")

    def is_configured(self):
        return bool(self.credentials_present)

    def search(self, skills, location, limit=20):
        """Return a list of common-format dicts. Implemented per provider."""
        raise NotImplementedError(f"Provider '{self.name}' search is not implemented yet.")

    def validate(self, item):
        """Force any dict into the common shape (defaults for missing keys)."""
        base = blank_common(self.name)
        if not isinstance(item, dict):
            return base
        for key in COMMON_FIELDS:
            if key in item and item[key] is not None:
                base[key] = item[key]
        if not isinstance(base['skills'], list):
            base['skills'] = []
        if not isinstance(base['extra'], dict):
            base['extra'] = {}
        return base


def to_legacy_opportunity(common):
    """Common format -> existing repository upsert shape (repo untouched)."""
    return {
        'source': common.get('provider'),
        'source_id': common.get('provider_job_id'),
        'title': common.get('title'),
        'company': common.get('company'),
        'location': common.get('location'),
        'opp_type': common.get('employment_type'),
        'description': common.get('description'),
        'required_skills': list(common.get('skills') or []),
        'salary_stipend': common.get('salary'),
        'deadline': None,
        'start_date': None,
        'application_url': common.get('apply_url'),
    }


class AdzunaProviderAdapter(BaseJobProvider):
    """Read-only adapter over the EXISTING Adzuna integration (untouched)."""

    name = 'Adzuna'
    env_key_names = ('ADZUNA_APP_ID', 'ADZUNA_APP_KEY')

    def search(self, skills, location, limit=20):
        from opportunity_data_service import OpportunityDataService
        service = OpportunityDataService()
        raw = service.search(skills=skills, location=location,
                             results_per_page=limit)
        return [self.validate(self.to_common(o)) for o in raw]

    def to_common(self, adz):
        """Existing Adzuna normalized dict -> common format. No re-fetching logic."""
        posted = to_iso_date(adz.get('created'))
        return {
            'provider': 'Adzuna',
            'provider_job_id': str(adz.get('source_id') or adz.get('id') or ''),
            'title': adz.get('title'),
            'company': adz.get('company'),
            'location': adz.get('location'),
            'description': adz.get('full_description') or adz.get('description'),
            'employment_type': adz.get('opp_type'),
            'salary': adz.get('salary_stipend'),
            'skills': list(adz.get('required_skills') or []),
            'posted_date': posted,
            'updated_date': None,
            'apply_url': adz.get('application_url'),
            'source_url': adz.get('redirect_url'),
            'extra': {'category': adz.get('category'), 'relevance': adz.get('relevance')},
        }

    @staticmethod
    def to_legacy(common):
        """Common format -> existing repository upsert shape (repo untouched)."""
        return to_legacy_opportunity(common)


class JoobleProvider(BaseJobProvider):
    """India Jooble REST API (https://in.jooble.org/api/about). POST JSON API."""

    name = 'Jooble'
    env_key_names = ('JOOBLE_API_KEY',)

    def __init__(self):
        super().__init__()
        self.host = os.environ.get('JOOBLE_API_HOST', 'in.jooble.org')
        try:
            self.cache_ttl = int(os.environ.get('JOOBLE_CACHE_TTL', '900'))
        except ValueError:
            self.cache_ttl = 900
        self._cache = {}

    def _cache_get(self, key):
        entry = self._cache.get(key)
        if not entry:
            return None
        import time as _time
        if _time.time() - entry[0] > self.cache_ttl:
            self._cache.pop(key, None)
            return None
        logger.info(f"DEBUG Jooble cache hit for query={key[0]!r} location={key[1]!r}")
        return entry[1]

    def _cache_set(self, key, value):
        import time as _time
        self._cache[key] = (_time.time(), value)

    def _request(self, keywords, location, page=1):
        import requests as _requests
        url = f"https://{self.host}/api/{os.environ.get('JOOBLE_API_KEY', '')}"
        body = {'keywords': keywords, 'location': location or '', 'page': str(page)}
        logger.info(f"DEBUG Jooble request started: host={self.host} keywords={keywords!r} (key masked)")
        try:
            response = _requests.post(url, json=body, timeout=15)
            logger.info(f"DEBUG Jooble status code: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"Jooble API returned status {response.status_code}: {response.text[:200]}")
                return None
            payload = response.json()
            jobs = payload.get('jobs', []) if isinstance(payload, dict) else []
            logger.info(f"DEBUG Jooble jobs received: {len(jobs)}, totalCount: {payload.get('totalCount') if isinstance(payload, dict) else 'n/a'}")
            return jobs
        except ValueError:
            logger.error("Jooble API returned non-JSON response.")
            return None
        except Exception as exc:
            logger.error(f"Jooble API request error: {type(exc).__name__}")
            return None

    def to_common(self, job):
        if not isinstance(job, dict):
            return self.validate({})
        raw_type = str(job.get('type') or '')
        lowered = f"{job.get('title') or ''} {raw_type}".lower()
        employment_type = 'internship' if 'intern' in lowered else (raw_type or None)
        return self.validate({
            'provider': 'Jooble',
            'provider_job_id': str(job.get('id') or ''),
            'title': job.get('title'),
            'company': job.get('company'),
            'location': job.get('location'),
            'description': job.get('snippet'),
            'employment_type': employment_type,
            'salary': job.get('salary') or None,
            'skills': [],
            'posted_date': None,
            'updated_date': to_iso_date(job.get('updated')),
            'apply_url': job.get('link'),
            'source_url': job.get('source'),
            'extra': {'jooble_type': raw_type or None},
        })

    def search(self, skills, location, limit=20):
        if not self.is_configured():
            logger.error("Cannot search Jooble: JOOBLE_API_KEY not configured.")
            return []
        keywords = ', '.join(skills) if isinstance(skills, list) and skills else (skills or '')
        cache_key = (keywords, location or '', limit)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        jobs = self._request(keywords, location)
        if not jobs:
            return []
        common = [self.to_common(j) for j in jobs[:limit]]
        logger.info(f"DEBUG Jooble normalized: {len(common)} opportunities")
        self._cache_set(cache_key, common)
        return common


class JobvettaProvider(BaseJobProvider):
    """Jobvetta REST API (https://www.jobvetta.com/api). Bearer auth, India jobs."""

    name = 'Jobvetta'
    env_key_names = ('JOBVETTA_API_KEY',)

    def __init__(self):
        super().__init__()
        self.base_url = os.environ.get('JOBVETTA_BASE_URL', 'https://api.jobvetta.com/v1')
        try:
            self.days = min(max(int(os.environ.get('JOBVETTA_DAYS', '30')), 1), 365)
        except ValueError:
            self.days = 30
        try:
            self.detail_limit = max(int(os.environ.get('JOBVETTA_DETAIL_LIMIT', '5')), 0)
        except ValueError:
            self.detail_limit = 5
        try:
            self.cache_ttl = int(os.environ.get('JOBVETTA_CACHE_TTL', '900'))
        except ValueError:
            self.cache_ttl = 900
        self._cache = {}
        self.last_status = None

    def _headers(self):
        return {'Authorization': f"Bearer {os.environ.get('JOBVETTA_API_KEY', '')}"}

    def _cache_get(self, key):
        entry = self._cache.get(key)
        if not entry:
            return None
        import time as _time
        if _time.time() - entry[0] > self.cache_ttl:
            self._cache.pop(key, None)
            return None
        logger.info(f"DEBUG Jobvetta cache hit for query={key[0]!r} location={key[1]!r}")
        return entry[1]

    def _cache_set(self, key, value):
        import time as _time
        self._cache[key] = (_time.time(), value)

    def _get(self, path, params=None):
        import requests as _requests
        url = f"{self.base_url}{path}"
        self.last_status = None
        try:
            response = _requests.get(url, headers=self._headers(), params=params or {}, timeout=15)
            self.last_status = response.status_code
            logger.info(f"DEBUG Jobvetta {path} status code: {response.status_code} (key masked)")
            if response.status_code == 401:
                logger.error("Jobvetta API authentication failed. Check JOBVETTA_API_KEY.")
                return None
            if response.status_code == 404:
                logger.error(f"Jobvetta resource not found: {path}")
                return None
            if response.status_code == 429:
                retry = response.headers.get('Retry-After', 'unknown')
                logger.error(f"Jobvetta daily limit reached (50/day). Retry-After: {retry}")
                return None
            if response.status_code != 200:
                logger.error(f"Jobvetta API returned status {response.status_code}: {response.text[:200]}")
                return None
            return response.json()
        except ValueError:
            logger.error("Jobvetta API returned non-JSON response.")
            return None
        except Exception as exc:
            logger.error(f"Jobvetta API request error: {type(exc).__name__}")
            return None

    def _format_salary(self, job):
        lo, hi, cur = job.get('salary_min'), job.get('salary_max'), job.get('salary_currency')
        if lo is None and hi is None:
            raw = job.get('salary')
            return str(raw) if raw else None
        parts = []
        if lo is not None:
            parts.append(str(lo))
        if hi is not None:
            parts.append(str(hi))
        text = ' - '.join(parts)
        return f"{text} {cur}".strip() if cur else text

    def to_common(self, job, detail=None):
        if not isinstance(job, dict):
            return self.validate({})
        full = detail if isinstance(detail, dict) else {}
        title = full.get('title') or job.get('title')
        raw_type = str(full.get('employment_type') or job.get('employment_type') or '')
        employment_type = 'internship' if 'intern' in f"{title or ''} {raw_type}".lower() else (raw_type or None)
        description = full.get('description')
        if not description:
            quals = full.get('minimum_qualifications') or []
            resps = full.get('responsibilities') or []
            joined = ' '.join([str(q) for q in quals + resps]).strip()
            description = joined or None
        skills = full.get('skills_required') or []
        if isinstance(skills, str):
            skills = [skills]
        return self.validate({
            'provider': 'Jobvetta',
            'provider_job_id': str(full.get('job_id') or job.get('job_id') or ''),
            'title': title,
            'company': full.get('company') or job.get('company'),
            'location': full.get('location') or job.get('location'),
            'description': description,
            'employment_type': employment_type,
            'salary': self._format_salary(full if full else job),
            'skills': [str(s) for s in skills],
            'posted_date': to_iso_date(full.get('created_at')),
            'updated_date': to_iso_date(full.get('last_seen_date')),
            'apply_url': full.get('url') or job.get('url'),
            'source_url': full.get('url') or job.get('url'),
            'extra': {
                'work_model': full.get('work_model') or job.get('work_model'),
                'experience_level': full.get('experience_level'),
                'minimum_qualifications': full.get('minimum_qualifications') or [],
            },
        })

    def search(self, skills, location, limit=20):
        if not self.is_configured():
            logger.error("Cannot search Jobvetta: JOBVETTA_API_KEY not configured.")
            return []
        query = ', '.join(skills) if isinstance(skills, list) and skills else (skills or '')
        # API caps search at 10 per call; details are extra calls against the 50/day quota.
        page_limit = min(max(int(limit or 10), 1), 10)
        cache_key = (query, location or '', page_limit)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        logger.info(f"DEBUG Jobvetta request started: q={query!r} location={location!r} (key masked)")
        payload = self._get('/jobs', params={'q': query, 'location': location or '',
                                             'days': self.days, 'limit': page_limit})
        if not payload:
            return []
        jobs = payload.get('jobs', []) if isinstance(payload, dict) else []
        logger.info(f"DEBUG Jobvetta jobs received: {len(jobs)}, total: {payload.get('total') if isinstance(payload, dict) else 'n/a'}")
        common = []
        for job in jobs:
            if not isinstance(job, dict):
                continue
            detail = None
            if job.get('job_id') and len(common) < self.detail_limit:
                detail = self._get(f"/jobs/{job.get('job_id')}")
                if detail is None and self.last_status == 404:
                    logger.info(f"DEBUG Jobvetta skipping inactive job {job.get('job_id')}")
                    continue
            common.append(self.to_common(job, detail))
        logger.info(f"DEBUG Jobvetta normalized: {len(common)} opportunities")
        self._cache_set(cache_key, common)
        return common


class IndianApiProvider(BaseJobProvider):
    """IndianAPI Jobs API (https://indianapi.in/documentation/jobs-api). X-Api-Key header."""

    name = 'IndianAPI'
    env_key_names = ('INDIANAPI_KEY',)

    def __init__(self):
        super().__init__()
        self.base_url = os.environ.get('INDIANAPI_BASE_URL', 'https://jobs.indianapi.in')
        try:
            self.cache_ttl = int(os.environ.get('INDIANAPI_CACHE_TTL', '900'))
        except ValueError:
            self.cache_ttl = 900
        self._cache = {}

    def _headers(self):
        return {'X-Api-Key': os.environ.get('INDIANAPI_KEY', '')}

    def _cache_get(self, key):
        entry = self._cache.get(key)
        if not entry:
            return None
        import time as _time
        if _time.time() - entry[0] > self.cache_ttl:
            self._cache.pop(key, None)
            return None
        logger.info(f"DEBUG IndianAPI cache hit for query={key[0]!r} location={key[1]!r}")
        return entry[1]

    def _cache_set(self, key, value):
        import time as _time
        self._cache[key] = (_time.time(), value)

    def to_common(self, job):
        if not isinstance(job, dict):
            return self.validate({})
        title = job.get('title') or job.get('job_title')
        raw_type = str(job.get('job_type') or '')
        employment_type = 'internship' if 'intern' in f"{title or ''} {raw_type}".lower() else (raw_type or None)
        return self.validate({
            'provider': 'IndianAPI',
            'provider_job_id': str(job.get('id') or ''),
            'title': title,
            'company': job.get('company'),
            'location': job.get('location'),
            'description': job.get('job_description'),
            'employment_type': employment_type,
            'salary': None,
            'skills': [],
            'posted_date': to_iso_date(job.get('posted_date')),
            'updated_date': None,
            'apply_url': job.get('apply_link'),
            'source_url': None,
            'extra': {
                'job_title': job.get('job_title'),
                'experience': job.get('experience'),
                'education_and_skills': job.get('education_and_skills'),
                'role_and_responsibility': job.get('role_and_responsibility'),
                'about_company': job.get('about_company'),
            },
        })

    def search(self, skills, location, limit=20):
        if not self.is_configured():
            logger.error("Cannot search IndianAPI: INDIANAPI_KEY not configured.")
            return []
        keywords = ', '.join(skills) if isinstance(skills, list) and skills else (skills or '')
        cache_key = (keywords, location or '', limit)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        import requests as _requests
        # Docs specify limit as a string parameter.
        params = {'limit': str(limit or 10)}
        if keywords:
            params['title'] = keywords
        if location:
            params['location'] = location
        logger.info(f"DEBUG IndianAPI request started: {self.base_url}/jobs keywords={keywords!r} (key masked)")
        try:
            response = _requests.get(f"{self.base_url}/jobs", headers=self._headers(),
                                     params=params, timeout=15)
            logger.info(f"DEBUG IndianAPI status code: {response.status_code} (key masked)")
            if response.status_code == 401:
                logger.error("IndianAPI authentication failed. Check INDIANAPI_KEY.")
                return []
            if response.status_code == 422:
                logger.error(f"IndianAPI validation error: {response.text[:200]}")
                return []
            if response.status_code != 200:
                logger.error(f"IndianAPI returned status {response.status_code}: {response.text[:200]}")
                return []
            payload = response.json()
            jobs = payload if isinstance(payload, list) else payload.get('jobs', [])
            logger.info(f"DEBUG IndianAPI jobs received: {len(jobs) if isinstance(jobs, list) else 0}")
        except ValueError:
            logger.error("IndianAPI returned non-JSON response.")
            return []
        except Exception as exc:
            logger.error(f"IndianAPI request error: {type(exc).__name__}")
            return []
        if not isinstance(jobs, list):
            return []
        common = [self.to_common(j) for j in jobs[:limit]]
        logger.info(f"DEBUG IndianAPI normalized: {len(common)} opportunities")
        self._cache_set(cache_key, common)
        return common


PROVIDERS = {
    'Adzuna': AdzunaProviderAdapter,
    'Jooble': JoobleProvider,
    'Jobvetta': JobvettaProvider,
    'IndianAPI': IndianApiProvider,
}


def get_provider(name):
    """Return an independent provider instance by name."""
    cls = PROVIDERS.get(name)
    if cls is None:
        raise ValueError(f"Unknown provider: {name}")
    return cls()


def list_providers():
    return sorted(PROVIDERS.keys())
