import os
import json
import logging
import mysql.connector
from datetime import datetime, date

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_CONFIG = {
    'host': os.environ.get('DB_HOST', '127.0.0.1'),
    'port': int(os.environ.get('DB_PORT', '3306')),
    'user': os.environ.get('DB_USER', 'root'),
    'password': os.environ.get('DB_PASSWORD', 'root'),
    'database': os.environ.get('DB_NAME', 'student_platform')
}

VALID_TYPES = ('job', 'internship', 'scholarship')


def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)


def parse_deadline_to_date(value):
    """Convert API deadline value to a date object or None. Never invents a date."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value)).date()
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        for fmt in ('%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%SZ',
                    '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%d %H:%M:%S'):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return None
    return None


def _coerce_type(opp_type):
    if opp_type in VALID_TYPES:
        return opp_type
    return 'job'


class OpportunityRepository:
    """Persistence layer for normalized opportunities. No API keys stored here."""

    def upsert_opportunity(self, opp):
        """
        Insert a normalized opportunity or update it if (source, external_id)
        already exists. Returns the row id, or None if skipped.
        """
        if not opp or not isinstance(opp, dict):
            return None
        external_id = str(opp.get('source_id') or opp.get('external_id') or '').strip() or None
        source = opp.get('source')
        if not external_id or not source:
            logger.info(f"Skipping cache for opportunity without identity: {opp.get('title', 'N/A')}")
            return None

        skills = opp.get('required_skills') or opp.get('required_skills_json') or []
        if isinstance(skills, str):
            try:
                skills = json.loads(skills)
            except (json.JSONDecodeError, TypeError):
                skills = []
        skills_json = json.dumps(list(skills))

        row = {
            'external_id': external_id,
            'title': opp.get('title') or 'Untitled',
            'company': opp.get('company'),
            'location': opp.get('location'),
            'type': _coerce_type(opp.get('opp_type')),
            'description': opp.get('description') or opp.get('full_description'),
            'required_skills_json': skills_json,
            'application_url': opp.get('application_url'),
            'source': source,
            'salary_stipend': opp.get('salary_stipend'),
            'deadline': parse_deadline_to_date(opp.get('deadline')),
            'start_date': parse_deadline_to_date(opp.get('start_date')),
        }

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO opportunities
                    (external_id, title, company, location, type, description,
                     required_skills_json, application_url, source, salary_stipend,
                     deadline, start_date, last_fetched_at)
                VALUES
                    (%(external_id)s, %(title)s, %(company)s, %(location)s, %(type)s,
                     %(description)s, %(required_skills_json)s, %(application_url)s,
                     %(source)s, %(salary_stipend)s, %(deadline)s, %(start_date)s, NOW())
                ON DUPLICATE KEY UPDATE
                    title = VALUES(title),
                    company = VALUES(company),
                    location = VALUES(location),
                    type = VALUES(type),
                    description = VALUES(description),
                    required_skills_json = VALUES(required_skills_json),
                    application_url = VALUES(application_url),
                    salary_stipend = VALUES(salary_stipend),
                    deadline = VALUES(deadline),
                    start_date = VALUES(start_date),
                    last_fetched_at = NOW()
            """, row)
            conn.commit()
            row_id = cursor.lastrowid
            if row_id == 0:
                cursor.execute(
                    "SELECT id FROM opportunities WHERE source = %s AND external_id = %s",
                    (source, external_id)
                )
                found = cursor.fetchone()
                row_id = found[0] if found else None
            return row_id
        finally:
            cursor.close()
            conn.close()

    def upsert_many(self, opportunities):
        """Bulk upsert. Returns counts dict. Never creates duplicates."""
        stats = {'inserted_or_updated': 0, 'skipped': 0}
        for opp in opportunities or []:
            result = self.upsert_opportunity(opp)
            if result is None:
                stats['skipped'] += 1
            else:
                stats['inserted_or_updated'] += 1
        logger.info(f"Upsert complete: {stats}")
        return stats

    def _row_to_dict(self, row):
        skills = row.get('required_skills_json')
        if isinstance(skills, str):
            try:
                skills = json.loads(skills)
            except (json.JSONDecodeError, TypeError):
                skills = []
        return {
            'id': row.get('id'),
            'external_id': row.get('external_id'),
            'title': row.get('title'),
            'company': row.get('company'),
            'location': row.get('location'),
            'opp_type': row.get('type'),
            'description': row.get('description'),
            'required_skills_json': list(skills or []),
            'application_url': row.get('application_url'),
            'source': row.get('source'),
            'salary_stipend': row.get('salary_stipend'),
            'deadline': row.get('deadline').isoformat() if isinstance(row.get('deadline'), date) else row.get('deadline'),
            'start_date': row.get('start_date').isoformat() if isinstance(row.get('start_date'), date) else row.get('start_date'),
            'last_fetched_at': row.get('last_fetched_at'),
        }

    def get_active_opportunities(self, opp_type=None, limit=50):
        """
        Return active recommendations only.
        Expired rows stay in the table but are excluded via
        WHERE (deadline IS NULL OR deadline >= CURDATE()).
        """
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            query = """
                SELECT id, external_id, title, company, location, type,
                       description, required_skills_json, application_url,
                       source, salary_stipend, deadline, start_date, last_fetched_at
                FROM opportunities
                WHERE (deadline IS NULL OR deadline >= CURDATE())
            """
            params = []
            if opp_type in VALID_TYPES:
                query += " AND type = %s"
                params.append(opp_type)
            query += " ORDER BY (deadline IS NULL), deadline ASC LIMIT %s"
            params.append(int(limit))
            cursor.execute(query, params)
            return [self._row_to_dict(r) for r in cursor.fetchall()]
        finally:
            cursor.close()
            conn.close()

    def get_by_id(self, opp_id):
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT id, external_id, title, company, location, type,
                       description, required_skills_json, application_url,
                       source, salary_stipend, deadline, start_date, last_fetched_at
                FROM opportunities WHERE id = %s
            """, (opp_id,))
            row = cursor.fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            cursor.close()
            conn.close()

    def count_all(self):
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM opportunities")
            return cursor.fetchone()[0]
        finally:
            cursor.close()
            conn.close()

    def count_active(self):
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM opportunities WHERE (deadline IS NULL OR deadline >= CURDATE())")
            return cursor.fetchone()[0]
        finally:
            cursor.close()
            conn.close()
