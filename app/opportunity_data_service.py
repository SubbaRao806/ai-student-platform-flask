import os
import re
import requests
import logging
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Adzuna job-search API countries (https://developer.adzuna.com/).
SUPPORTED_ADZUNA_COUNTRIES = {
    'at', 'au', 'be', 'br', 'ca', 'ch', 'de', 'es', 'fr', 'gb',
    'in', 'it', 'mx', 'nl', 'nz', 'pl', 'ru', 'sg', 'us', 'za',
}

_STREET_HINTS = {
    'line', 'street', 'st', 'road', 'rd', 'colony', 'nagar', 'lane',
    'floor', 'door', 'plot', 'house', 'flat', 'apartment', 'area',
    'phase', 'sector', 'block', 'agraharam', 'village', 'mandal',
    'district', 'colony,',
}

_COUNTRY_TOKENS = {'india', 'usa', 'united states', 'united states of america', 'us', 'in'}

_INDIA_HINTS = (
    'india', 'guntur', 'vijayawada', 'hyderabad', 'chennai', 'bengaluru',
    'bangalore', 'delhi', 'mumbai', 'kolkata', 'pune', 'ahmedabad',
    'andhra', 'telangana', 'tamil nadu', 'karnataka', 'kerala',
    'maharashtra', 'gujarat', 'rajasthan', 'punjab', 'uttar pradesh',
    'madhya pradesh', 'west bengal', 'bihar', 'odisha', 'assam',
)

# Temporary broad-search fan-out: one combined `what` misses when Adzuna
# requires all terms. Keep small to respect the free-tier rate limit.
ADZUNA_MAX_SKILL_SUBQUERIES = 4
ADZUNA_GENERIC_FALLBACK_WHAT = 'software developer'

# Broad/global feed: Adzuna has no single "all jobs in the world" endpoint.
# Every job-search request is scoped to one country path
# (https://api.adzuna.com/v1/api/jobs/{country}/search/{page}).
# The broadest valid query is therefore: configured country, NO `what`,
# NO `where`, paginated. Personalization happens AFTER fetching, in
# recommendation_engine.py. Keep page count small (free tier: 25/min, 250/day).
def _broad_max_pages():
    try:
        return max(1, min(int(os.environ.get('ADZUNA_BROAD_MAX_PAGES', '3')), 10))
    except ValueError:
        return 3


def get_default_location():
    """Sensible country-level fallback driven by ADZUNA_COUNTRY (no street address)."""
    country = (os.environ.get('ADZUNA_COUNTRY', 'us') or 'us').strip().lower()
    return 'India' if country == 'in' else 'USA'


def clean_city(raw_location, fallback=None):
    """Reduce a free-form profile address to a city-level `where` value.

    Example: "A.T.Agraharam,4th line,Venkata Krishna Colony,Guntur" -> "Guntur".
    Never returns a street address; returns `fallback` (or country default) when invalid.
    """
    if fallback is None:
        fallback = get_default_location()
    if not raw_location or not str(raw_location).strip():
        return fallback
    text = str(raw_location).strip()
    lowered_whole = text.lower()
    if lowered_whole in ('usa', 'us', 'united states', 'india', 'in'):
        return 'India' if lowered_whole in ('india', 'in') else 'USA'
    # Drop pincodes/zipcodes so they don't become the "city".
    text = re.sub(r'\b\d{6}\b|\b\d{5}(?:-\d{4})?\b', '', text)
    parts = [p.strip(' ,;') for p in text.split(',')]
    parts = [p for p in (p.strip() for p in parts) if p]
    if not parts:
        return fallback
    if len(parts) == 1:
        single = re.sub(r'\s+', ' ', parts[0]).strip()
        return single[:60] if len(single) >= 2 else fallback
    # Prefer the rightmost non-country, non-street token (the city).
    for token in reversed(parts):
        low = token.lower()
        if low in _COUNTRY_TOKENS:
            continue
        if any(ch.isdigit() for ch in token):
            continue
        words = set(re.findall(r'[a-z]+', low))
        if words & _STREET_HINTS and len(token.split()) > 1:
            continue
        cleaned = re.sub(r'\s+', ' ', token).strip()
        if len(cleaned) >= 2:
            return cleaned[:60]
    # Fallback: rightmost token stripped, or country default.
    last = re.sub(r'\s+', ' ', parts[-1]).strip()
    return last[:60] if len(last) >= 2 else fallback


def infer_country(raw_location, default=None):
    """Pick an Adzuna country code without hard-coding per-user values.

    Uses India hints in the address; otherwise the ADZUNA_COUNTRY env default.
    """
    default_code = (default or os.environ.get('ADZUNA_COUNTRY', 'us') or 'us').strip().lower()
    if default_code not in SUPPORTED_ADZUNA_COUNTRIES:
        logger.warning(f"Unsupported ADZUNA_COUNTRY={default_code!r}; falling back to 'us'.")
        default_code = 'us'
    text = (str(raw_location) if raw_location else '').lower()
    if text and any(h in text for h in _INDIA_HINTS):
        return 'in'
    return default_code


def normalize_skills(skills):
    """Deduplicated non-empty skill list preserving order. Empty -> [] (broad search)."""
    if not skills:
        return []
    if isinstance(skills, str):
        skills = [s for s in re.split(r'[,;]+', skills)]
    seen, out = set(), []
    for s in skills or []:
        name = str(s or '').strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


class OpportunityDataService:
    def __init__(self, app_id=None, app_key=None, country=None, host=None):
        self.app_id = app_id or os.environ.get('ADZUNA_APP_ID')
        self.app_key = app_key or os.environ.get('ADZUNA_APP_KEY')
        env_country = (os.environ.get('ADZUNA_COUNTRY', country or 'us') or 'us').strip().lower()
        if env_country not in SUPPORTED_ADZUNA_COUNTRIES:
            logger.warning(f"Unsupported ADZUNA_COUNTRY={env_country!r}; falling back to 'us'.")
            env_country = 'us'
        self.country = env_country
        self.host = host or os.environ.get('ADZUNA_RAPIDAPI_HOST', 'api-adzuna-com.p.rapidapi.com')
        # Official Adzuna endpoint (verified live: unknown path 404s, bad keys 401 here).
        self.base_url = "https://api.adzuna.com/v1/api/jobs"

        if not self.app_id or not self.app_key:
            logger.error("ADZUNA_APP_ID and ADZUNA_APP_KEY must be set in environment variables")

        self.headers = {}

    def _build_params(self, skills=None, location=None, page=0, results_per_page=20, job_type=None):
        # Official API takes country and 1-based page in the URL path.
        params = {
            'app_id': self.app_id,
            'app_key': self.app_key,
            'results_per_page': results_per_page,
        }
        clean_skills = normalize_skills(skills)
        if clean_skills:
            params['what'] = ', '.join(clean_skills)
        city = clean_city(location) if location else None
        if city:
            params['where'] = city
        if job_type and job_type != 'all':
            params['category'] = job_type
        return params

    def _make_request(self, params, country=None, page=1):
        effective_country = (country or self.country or 'us').strip().lower()
        try:
            page_num = max(int(page or 1), 1)
        except (TypeError, ValueError):
            page_num = 1
        safe_params = {k: ('***' if 'key' in k.lower() or k in ('app_id', 'app_key') else v)
                       for k, v in params.items()}
        url = f"{self.base_url}/{effective_country}/search/{page_num}"
        logger.info(f"DEBUG Adzuna request: country={effective_country} url={url} params={safe_params}")
        try:
            response = requests.get(
                url,
                headers=self.headers,
                params=params,
                timeout=15
            )
            logger.info(f"DEBUG Adzuna status code: {response.status_code}")
            if response.status_code == 200:
                payload = response.json()
                results = payload.get('results', []) if isinstance(payload, dict) else []
                logger.info(f"DEBUG Adzuna results received: {len(results)}, total count field: {payload.get('count') if isinstance(payload, dict) else 'n/a'}")
                return payload
            elif response.status_code == 401:
                logger.error("Adzuna API authentication failed. Check your ADZUNA_APP_ID and ADZUNA_APP_KEY.")
                return None
            elif response.status_code == 429:
                logger.error("Adzuna API rate limit exceeded.")
                return None
            else:
                logger.error(f"Adzuna API returned status code {response.status_code}: {response.text[:200]}")
                return None
        except requests.exceptions.Timeout:
            logger.error("Adzuna API request timed out.")
            return None
        except requests.exceptions.ConnectionError:
            logger.error("Failed to connect to Adzuna API. Check network connection.")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Adzuna API request error: {str(e)}")
            return None

    def _safe_get(self, data, *keys, default=None):
        """Safely navigate nested dictionaries."""
        for key in keys:
            if isinstance(data, dict) and key in data:
                data = data[key]
            else:
                return default
        return data

    def _extract_skills(self, description):
        """Extract skills from description. Returns list of strings."""
        if not description:
            return []
        try:
            data = json.loads(description) if isinstance(description, str) and description.startswith('[') else None
            if isinstance(data, list):
                return [str(s) for s in data]
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    def _extract_salary(self, item):
        """Extract salary info from Adzuna item."""
        salary_min = self._safe_get(item, 'salary_min', default=None)
        salary_max = self._safe_get(item, 'salary_max', default=None)
        salary_string = self._safe_get(item, 'salary_string', default=None)

        if salary_string:
            return salary_string
        if salary_min is not None and salary_max is not None:
            try:
                return f"${int(salary_min):,} - ${int(salary_max):,}"
            except (TypeError, ValueError):
                pass
        if salary_min is not None:
            try:
                return f"${int(salary_min):,}+"
            except (TypeError, ValueError):
                pass
        return None

    def _extract_dates(self, item):
        """Extract important dates from Adzuna item."""
        dates = {}
        created = self._safe_get(item, 'created', default=None)
        if created:
            try:
                dt = datetime.fromtimestamp(created) if isinstance(created, (int, float)) else datetime.strptime(str(created), '%Y-%m-%d')
                dates['posted'] = dt.strftime('%Y-%m-%d')
            except (ValueError, TypeError):
                dates['posted'] = str(created)

        if self._safe_get(item, 'expires', default=None):
            expires = self._safe_get(item, 'expires', default=None)
            try:
                dt = datetime.fromtimestamp(expires) if isinstance(expires, (int, float)) else datetime.strptime(str(expires), '%Y-%m-%d')
                dates['deadline'] = dt.strftime('%Y-%m-%d')
            except (ValueError, TypeError):
                dates['deadline'] = str(expires)

        return dates if dates else None

    def _extract_location(self, item):
        """Extract location information from Adzuna item."""
        location = self._safe_get(item, 'location', default=None)
        if location and isinstance(location, dict):
            display_name = self._safe_get(location, 'display_name', default=None)
            if display_name:
                return display_name
        return self._safe_get(item, 'location')

    def _extract_company(self, item):
        """Extract company information from Adzuna item."""
        company = self._safe_get(item, 'company', default=None)
        if company and isinstance(company, dict):
            return self._safe_get(company, 'display_name', default=None)
        return self._safe_get(item, 'company')

    def _extract_application_url(self, item):
        """Extract the application URL from Adzuna item. None when absent (never '#' or a guess)."""
        redirect_url = self._safe_get(item, 'redirect_url', default=None)
        if redirect_url:
            return redirect_url
        urls = self._safe_get(item, 'urls', default=None)
        if urls and isinstance(urls, dict):
            return self._safe_get(urls, 'apply', default=None)
        return self._safe_get(item, 'application_url')

    def _categorize_type(self, item):
        """Determine if the opportunity is a job or internship."""
        category = self._safe_get(item, 'category', default=None)
        if category:
            cat_lower = category.lower() if isinstance(category, str) else ''
            if 'intern' in cat_lower or 'placement' in cat_lower or 'trainee' in cat_lower:
                return 'internship'
        what = self._safe_get(item, 'what', default=None)
        if what and isinstance(what, str) and ('intern' in what.lower() or 'placement' in what.lower()):
            return 'internship'
        title = self._safe_get(item, 'title', default=None)
        if title and isinstance(title, str) and ('intern' in title.lower() or 'placement' in title.lower() or 'trainee' in title.lower()):
            return 'internship'
        return 'job'

    def _normalize_opportunity(self, item):
        """Convert a raw Adzuna API result into our common opportunity format."""
        if not item or not isinstance(item, dict):
            return None

        return {
            'id': self._safe_get(item, 'id', default=''),
            'title': self._safe_get(item, 'title', default='N/A'),
            'company': self._extract_company(item),
            'location': self._extract_location(item),
            'description': self._safe_get(item, 'description', default=''),
            'opp_type': self._categorize_type(item),
            'required_skills': self._extract_skills(self._safe_get(item, 'skills', default=None)) or [],
            'salary_stipend': self._extract_salary(item),
            'start_date': self._safe_get(item, 'start_time', default=None) or self._safe_get(item, 'start_date', default=None),
            'deadline': self._safe_get(item, 'deadline', default=None) or self._safe_get(item, 'expires', default=None),
            'application_url': self._extract_application_url(item),
            'source': 'Adzuna',
            'source_id': self._safe_get(item, 'id', default=''),
            'category': self._safe_get(item, 'category', default=None),
            'created': self._safe_get(item, 'created', default=None),
            'redirect_url': self._safe_get(item, 'redirect_url', default=None),
            'content_type': self._safe_get(item, 'content-type', default=None),
            'relevance': self._safe_get(item, 'relevance_score', default=None) or self._safe_get(item, 'relevance', default=None),
        }

    def _parse_deadline(self, deadline_value):
        """
        Parse deadline from various formats into a timezone-aware datetime.
        Supports: Unix timestamp, ISO string 'YYYY-MM-DD', ISO string 'YYYY-MM-DDTHH:MM:SSZ', datetime object.
        Returns timezone-aware datetime or None if parsing fails.
        """
        if not deadline_value:
            return None

        if isinstance(deadline_value, datetime):
            if deadline_value.tzinfo is None:
                return deadline_value.replace(tzinfo=timezone.utc)
            return deadline_value

        if isinstance(deadline_value, (int, float)):
            try:
                return datetime.fromtimestamp(float(deadline_value), tz=timezone.utc)
            except (OSError, OverflowError, ValueError):
                return None

        if isinstance(deadline_value, str):
            deadline_str = deadline_value.strip()
            formats = [
                '%Y-%m-%d',
                '%Y-%m-%dT%H:%M:%S',
                '%Y-%m-%dT%H:%M:%SZ',
                '%Y-%m-%dT%H:%M:%S%z',
                '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%d %H:%M:%S UTC',
            ]
            for fmt in formats:
                try:
                    parsed = datetime.strptime(deadline_str, fmt)
                    if parsed.tzinfo is None:
                        return parsed.replace(tzinfo=timezone.utc)
                    return parsed
                except ValueError:
                    continue
            logger.warning(f"Could not parse deadline string: {deadline_str}")
            return None

        return None

    def _is_expired(self, deadline_value, tz_name='UTC'):
        """
        Check if an opportunity deadline has already passed.

        Args:
            deadline_value: Raw deadline value from Adzuna (any format)
            tz_name: Timezone string (e.g., 'US/Eastern', 'UTC')

        Returns:
            True if deadline is past (expired), False if active or no deadline.
        """
        if not deadline_value:
            return False

        deadline_dt = self._parse_deadline(deadline_value)
        if deadline_dt is None:
            return False

        target_tz = ZoneInfo(tz_name)
        deadline_in_tz = deadline_dt.astimezone(target_tz)
        now_in_tz = datetime.now(tz=target_tz)

        is_expired = deadline_in_tz < now_in_tz
        if is_expired:
            logger.info(f"Opportunity expired: deadline {deadline_in_tz.isoformat()} < now {now_in_tz.isoformat()}")
        return is_expired

    def filter_active(self, opportunities, tz_name='UTC'):
        """
        Filter a list of opportunities, removing expired ones.

        Args:
            opportunities: List of normalized opportunity dicts
            tz_name: Timezone string (e.g., 'US/Eastern', 'UTC')

        Returns:
            List of active (non-expired) opportunities.
            Opportunities without deadlines are kept.
        """
        active = []
        for opp in opportunities:
            deadline = opp.get('deadline')
            if self._is_expired(deadline, tz_name=tz_name):
                logger.info(f"Filtering out expired opportunity: {opp.get('title', 'N/A')} (deadline: {deadline})")
                continue
            active.append(opp)

        logger.info(f"Filtered {len(opportunities)} opportunities to {len(active)} active ones")
        return active

    def fetch_broad_feed(self, results_per_page=20, max_pages=None, country=None, job_type='all', tz_name='UTC'):
        """Fetch a broad job pool WITHOUT user skills (`what`) or location (`where`).

        Flow: broad Adzuna country feed -> DB/cache (caller upserts) ->
        recommendation_engine ranks for the current user. User skills,
        education, and projects are used ONLY for ranking, never for fetching.

        Limitation: Adzuna scopes every search to one country path
        (../jobs/{country}/search/{page}); there is no single request that
        returns "every job in the world". This fetches the broadest valid
        query (configured country, no filters) across `max_pages` pages and
        deduplicates before returning.
        """
        if not self.app_id or not self.app_key:
            logger.error("Cannot fetch broad feed: ADZUNA_APP_ID and ADZUNA_APP_KEY not configured.")
            return []
        effective_country = (country or self.country or 'us').strip().lower()
        if effective_country not in SUPPORTED_ADZUNA_COUNTRIES:
            logger.warning(f"Unsupported country={effective_country!r}; falling back to 'us'.")
            effective_country = 'us'
        pages = max_pages if max_pages is not None else _broad_max_pages()
        try:
            pages = max(1, min(int(pages), 10))
        except (TypeError, ValueError):
            pages = 3
        logger.info(
            "DEBUG Adzuna broad feed start: country=%s pages=%d results_per_page=%s (no what, no where)",
            effective_country, pages, results_per_page,
        )
        merged_raw = []
        for page_num in range(1, pages + 1):
            params = {
                'app_id': self.app_id,
                'app_key': self.app_key,
                'results_per_page': results_per_page,
            }
            if job_type and job_type != 'all':
                params['category'] = job_type
            data = self._make_request(params, country=effective_country, page=page_num)
            if data is None:
                logger.info(
                    "DEBUG Adzuna broad feed page failed: country=%s page=%d",
                    effective_country, page_num,
                )
                continue
            results = data.get('results', [])
            total = data.get('count', 'n/a') if isinstance(data, dict) else 'n/a'
            logger.info(
                "DEBUG Adzuna broad feed page: country=%s page=%d count=%s returned=%d",
                effective_country, page_num, total, len(results),
            )
            merged_raw.extend(results or [])
            if not results:
                break
        if not merged_raw:
            logger.info(f"DEBUG Adzuna broad feed empty: country={effective_country} pages={pages}")
            return []
        normalized = []
        for item in merged_raw:
            opp = self._normalize_opportunity(item)
            if opp:
                normalized.append(opp)
        logger.info(f"DEBUG parsed opportunities: {len(normalized)} of {len(merged_raw)} raw results (pre-dedupe)")
        deduped = {}
        for opp in normalized:
            key = str(opp.get('source_id') or opp.get('id') or '')
            if not key:
                key = f"{opp.get('title')}|{opp.get('company')}|{opp.get('location')}"
            if key not in deduped:
                deduped[key] = opp
        normalized = list(deduped.values())
        logger.info(
            "DEBUG Adzuna broad feed merged: %d raw -> %d deduped (country=%s)",
            len(merged_raw), len(normalized), effective_country,
        )
        before = len(normalized)
        active = self.filter_active(normalized, tz_name=tz_name)
        logger.info(f"DEBUG rejected by deadline filtering: {before - len(active)}, active: {len(active)}")
        logger.info(f"Fetched {len(normalized)} normalized opportunities from Adzuna broad feed, {len(active)} active")
        return active

    def search(self, skills, location, page=0, results_per_page=20, job_type='all', tz_name='UTC', country=None):
        """
        Search for opportunities from Adzuna API.

        NOTE: legacy filtered search (per-skill fan-out using `what`/`where`).
        The app's main routes now use fetch_broad_feed() instead: fetch a
        broad pool first, then rank with recommendation_engine.py.
        Callers, caching, and ranking are unchanged.

        Args:
            skills: List of skill strings or a single comma-separated string.
                Empty -> broad search (no `what`), never zeroed by caller.
            location: Free-form profile address; reduced to city-level internally.
            page: Page number for pagination
            results_per_page: Number of results per page
            job_type: 'all', 'job', or 'internship' to filter
            tz_name: Timezone for deadline comparison (e.g., 'US/Eastern', 'UTC')
            country: Optional override; otherwise inferred from location + ADZUNA_COUNTRY.

        Returns:
            List of normalized active opportunity dicts. Empty list on failure.
            Expired opportunities are automatically excluded.
        """
        if not self.app_id or not self.app_key:
            logger.error("Cannot search: ADZUNA_APP_ID and ADZUNA_APP_KEY not configured.")
            return []

        clean_skills = normalize_skills(skills)
        city = clean_city(location)
        effective_country = infer_country(location, default=country or self.country)
        what_query = ', '.join(clean_skills) if clean_skills else '(broad search: no what)'
        logger.info(
            "DEBUG Adzuna search input: country=%s cleaned_city=%r skills=%s what=%s raw_location=%r",
            effective_country, city, clean_skills, what_query, location,
        )

        # Build fan-out plan: per-skill, generic role, broad fallback.
        sub_queries = []
        if clean_skills:
            for skill in clean_skills[:ADZUNA_MAX_SKILL_SUBQUERIES]:
                sub_queries.append([skill])
            if ADZUNA_GENERIC_FALLBACK_WHAT.lower() not in {s.lower() for s in clean_skills}:
                sub_queries.append([ADZUNA_GENERIC_FALLBACK_WHAT])
            sub_queries.append(None)  # broad `where`-only fallback
        else:
            sub_queries.append(None)

        merged_raw = []
        for what in sub_queries:
            label = ', '.join(what) if what else '(broad: no what)'
            params = self._build_params(
                skills=what,
                location=city,
                page=page,
                results_per_page=results_per_page,
                job_type=job_type
            )
            data = self._make_request(params, country=effective_country)
            if data is None:
                logger.info(
                    "DEBUG Adzuna sub-query failed: country=%s where=%r what=%s",
                    effective_country, city, label,
                )
                continue
            results = data.get('results', [])
            total = data.get('count', 'n/a') if isinstance(data, dict) else 'n/a'
            logger.info(
                "DEBUG Adzuna sub-query: country=%s where=%r what=%s count=%s returned=%d",
                effective_country, city, label, total, len(results),
            )
            merged_raw.extend(results or [])

        if not merged_raw:
            logger.info(f"No results found for skills={clean_skills}, cleaned_city={city}, country={effective_country}")
            return []

        normalized = []
        for item in merged_raw:
            opp = self._normalize_opportunity(item)
            if opp:
                normalized.append(opp)
        logger.info(f"DEBUG parsed opportunities: {len(normalized)} of {len(merged_raw)} raw results (pre-dedupe)")

        # Merge + deduplicate before ranking (same Adzuna id can hit several sub-queries).
        deduped = {}
        for opp in normalized:
            key = str(opp.get('source_id') or opp.get('id') or '')
            if not key:
                key = f"{opp.get('title')}|{opp.get('company')}|{opp.get('location')}"
            if key not in deduped:
                deduped[key] = opp
        normalized = list(deduped.values())
        logger.info(
            "DEBUG Adzuna merged: %d raw -> %d deduped (country=%s where=%r)",
            len(merged_raw), len(normalized), effective_country, city,
        )

        before = len(normalized)
        active = self.filter_active(normalized, tz_name=tz_name)
        logger.info(f"DEBUG rejected by deadline filtering: {before - len(active)}, active: {len(active)}")

        logger.info(f"Fetched {len(normalized)} normalized opportunities from Adzuna, {len(active)} active")
        return active

    def search_by_location(self, location, page=0, results_per_page=20, job_type='all'):
        """
        Search for opportunities by location without specific skills.

        Args:
            location: Location string
            page: Page number
            results_per_page: Number of results per page
            job_type: Filter by type

        Returns:
            List of normalized opportunity dicts. Empty list on failure.
        """
        return self.search(skills=None, location=location, page=page, results_per_page=results_per_page, job_type=job_type)

    def get_opportunity_detail(self, source_id):
        """
        Get detailed information for a specific opportunity.

        Args:
            source_id: The opportunity ID from Adzuna

        Returns:
            Normalized opportunity dict or None on failure.
        """
        if not self.app_id or not self.app_key:
            logger.error("Cannot fetch detail: ADZUNA_APP_ID and ADZUNA_APP_KEY not configured.")
            return None

        params = {
            'app_id': self.app_id,
            'app_key': self.app_key
        }

        try:
            response = requests.get(
                f"{self.base_url}/jobs/{source_id}",
                headers=self.headers,
                params=params,
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                result = data.get('results', [data])
                if result:
                    return self._normalize_opportunity(result[0])
                return None
            else:
                logger.error(f"Adzuna detail API returned status code {response.status_code}")
                return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Adzuna detail API request error: {str(e)}")
            return None

    def health_check(self):
        """
        Check if the Adzuna API connection works.

        Returns:
            True if connection is healthy, False otherwise.
        """
        if not self.app_id or not self.app_key:
            return False

        params = self._build_params(skills=['python'], location='us', results_per_page=1)
        data = self._make_request(params)
        return data is not None and isinstance(data, dict)

    def get_last_fetched_count(self, skills, location):
        """
        Get the count of results without fetching all data.

        Returns:
            Integer count of results or 0 on failure.
        """
        params = self._build_params(
            skills=skills,
            location=location,
            page=0,
            results_per_page=1,
            job_type='all'
        )
        data = self._make_request(params)
        if data and isinstance(data, dict):
            return data.get('count', 0)
        return 0
