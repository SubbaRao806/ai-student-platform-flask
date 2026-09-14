from dotenv import load_dotenv
load_dotenv()
import sys
import os
import logging
sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
from ai_service import parse_resume
from opportunity_data_service import OpportunityDataService
from opportunity_repository import OpportunityRepository
from recommendation_engine import RecommendationEngine
from skill_gap_analyzer import SkillGapAnalyzer
from improvement_path_generator import ImprovementPathGenerator
from ats_analyzer import ATSCompatibilityAnalyzer
from urllib.parse import urlparse


def is_valid_application_url(url):
    """Only http(s) URLs with a host are treated as real application links."""
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    if not url or url == '#':
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ('http', 'https') and bool(parsed.netloc)


def analyze_opportunity_gap(user_id, db_opp):
    """Dynamic skill gap for one opportunity: skills + project tech + resume vs required."""
    data = load_student_recommendation_data(user_id)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT resume_text, summary, bio FROM student_profiles WHERE user_id = %s", (user_id,))
    profile = cursor.fetchone() or {}
    cursor.close()
    conn.close()

    engine = RecommendationEngine()
    analyzer = SkillGapAnalyzer()

    student = engine.build_student_profile(
        skills=data['skills'], projects=data['projects'], education=data['education'])
    required = engine.resolve_required_skills(db_opp, student['skills'])
    skill_map = analyzer.build_student_skill_map(
        skills=data['skills'], projects=data['projects'])
    gap = analyzer.analyze(
        required_skills=list(required.values()),
        student_skill_map=skill_map,
        resume_texts=[profile.get('resume_text'), profile.get('summary'), profile.get('bio')])
    gap['required_map'] = required
    gap['resume_texts'] = [profile.get('resume_text'), profile.get('summary'), profile.get('bio')]
    gap['resume_source'] = 'saved resume' if profile.get('resume_text') else 'profile summary'
    gap['student'] = student
    return gap


def fetch_user_search_skills(cursor, user_id):
    """Skills for Adzuna `what`: direct profile skills + mapped catalog skills, deduped.

    Dashboard routes previously read only the student_skills mapping, so users
    with only direct `skills(student_id)` rows searched with skills=[].
    Empty result -> [] so the service performs a broad search (no `what`).
    """
    cursor.execute("SELECT skill_name FROM skills WHERE student_id = %s", (user_id,))
    direct_skills = [row['skill_name'] for row in cursor.fetchall()]

    cursor.execute("""
        SELECT s.skill_name
        FROM skills s
        JOIN student_skills ss ON s.id = ss.skill_id
        WHERE ss.student_id = %s
    """, (user_id,))
    mapped_skills = [row['skill_name'] for row in cursor.fetchall()]

    seen, merged = set(), []
    for name in direct_skills + mapped_skills:
        if name and str(name).strip() and str(name).strip().lower() not in seen:
            seen.add(str(name).strip().lower())
            merged.append(str(name).strip())
    return merged


def load_student_recommendation_data(user_id):
    """Dynamic student data for recommendations: skills, projects, education."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    skills = fetch_user_search_skills(cursor, user_id)

    cursor.execute("SELECT title, technologies, description FROM projects WHERE student_id = %s", (user_id,))
    projects = cursor.fetchall()

    cursor.execute("SELECT degree_type, branch, start_year, end_year FROM education WHERE student_id = %s", (user_id,))
    education = cursor.fetchall()

    cursor.close()
    conn.close()

    return {'skills': skills, 'projects': projects, 'education': education}

app = Flask(__name__, template_folder='../templates', static_folder='../static')
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev_secret_key_change_in_production')

DB_CONFIG = {
    'host': os.environ.get('DB_HOST', '127.0.0.1'),
    'port': int(os.environ.get('DB_PORT', '3306')),
    'user': os.environ.get('DB_USER', 'root'),
    'password': os.environ.get('DB_PASSWORD', 'root'),
    'database': os.environ.get('DB_NAME', 'student_platform')
}

def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = generate_password_hash(request.form['password'])
        
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # Insert user
            cursor.execute("INSERT INTO users (email, password_hash) VALUES (%s, %s)", (email, password))
            user_id = cursor.lastrowid
            # Initialize student profile
            cursor.execute("INSERT INTO student_profiles (user_id) VALUES (%s)", (user_id,))
            conn.commit()
            flash('Registration successful!')
            return redirect(url_for('login'))
        except mysql.connector.Error as err:
            flash(f'Database error: {err}')
        finally:
            cursor.close()
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password.')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        # Clear existing data
        cursor.execute("DELETE FROM education WHERE student_id=%s", (session['user_id'],))
        cursor.execute("DELETE FROM work_experience WHERE student_id=%s", (session['user_id'],))
        cursor.execute("DELETE FROM projects WHERE student_id=%s", (session['user_id'],))
        cursor.execute("DELETE FROM skills WHERE student_id=%s", (session['user_id'],))
        cursor.execute("DELETE FROM achievements WHERE student_id=%s", (session['user_id'],))
        cursor.execute("DELETE FROM languages WHERE student_id=%s", (session['user_id'],))
        cursor.execute("DELETE FROM certifications WHERE student_id=%s", (session['user_id'],))

        # Save Basic Profile
        cursor.execute("""
            UPDATE student_profiles 
            SET full_name=%s, email=%s, phone_number=%s, dob=%s, address=%s, 
                linkedin_url=%s, github_url=%s, summary=%s, bio=%s 
            WHERE user_id=%s
        """, (request.form.get('full_name', ''), request.form.get('email', ''), request.form.get('phone_number', ''),
              request.form.get('dob', None), request.form.get('address', ''), request.form.get('linkedin_url', ''), 
              request.form.get('github_url', ''), request.form.get('summary', ''), request.form.get('bio', ''), session['user_id']))

        # Save Certifications
        for c in request.form.getlist('certifications[]'):
            cursor.execute("INSERT INTO certifications (student_id, title) VALUES (%s, %s)", (session['user_id'], c))
        
        # Save Education
        degrees = request.form.getlist('degree_type[]')
        for i in range(len(degrees)):
            cursor.execute("""
                INSERT INTO education (student_id, degree_type, branch, start_year, end_year, location, score_type, score_value)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (session['user_id'], degrees[i], request.form.getlist('branch[]')[i], 
                  request.form.getlist('start_year[]')[i], request.form.getlist('end_year[]')[i], 
                  request.form.getlist('location[]')[i], request.form.getlist('score_type[]')[i], 
                  request.form.getlist('score_value[]')[i]))
        
        # Save Experience
        job_titles = request.form.getlist('job_title[]')
        for i in range(len(job_titles)):
            cursor.execute("""
                INSERT INTO work_experience (student_id, job_title, company_name, location, start_date, end_date, description)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (session['user_id'], job_titles[i], request.form.getlist('company_name[]')[i], 
                  request.form.getlist('exp_location[]')[i], request.form.getlist('start_date[]')[i] or None, 
                  request.form.getlist('end_date[]')[i] or None, request.form.getlist('description[]')[i]))
        
        # Save Projects
        project_titles = request.form.getlist('project_title[]')
        for i in range(len(project_titles)):
            cursor.execute("""
                INSERT INTO projects (student_id, title, technologies, link, description)
                VALUES (%s, %s, %s, %s, %s)
            """, (session['user_id'], project_titles[i], request.form.getlist('technologies[]')[i], 
                  request.form.getlist('project_link[]')[i], request.form.getlist('project_description[]')[i]))
        
        # Save Skills
        for s in request.form.getlist('technical_skills[]'):
            cursor.execute("INSERT INTO skills (student_id, skill_name, skill_type) VALUES (%s, %s, 'Technical')", (session['user_id'], s))
        for s in request.form.getlist('soft_skills[]'):
            cursor.execute("INSERT INTO skills (student_id, skill_name, skill_type) VALUES (%s, %s, 'Soft')", (session['user_id'], s))
        for s in request.form.getlist('learning_skills[]'):
            cursor.execute("INSERT INTO skills (student_id, skill_name, skill_type) VALUES (%s, %s, 'Learning')", (session['user_id'], s))
        
        # Save Achievements
        for a in request.form.getlist('achievements[]'):
            cursor.execute("INSERT INTO achievements (student_id, title) VALUES (%s, %s)", (session['user_id'], a))
            
        # Save Languages
        for l in request.form.getlist('languages[]'):
            cursor.execute("INSERT INTO languages (student_id, language_name) VALUES (%s, %s)", (session['user_id'], l))
        
        conn.commit()
        flash('Profile updated successfully!')
        
    cursor.execute("SELECT * FROM student_profiles WHERE user_id = %s", (session['user_id'],))
    profile = cursor.fetchone()
    
    # Fetch all skills to display them back in the form
    cursor.execute("SELECT * FROM skills WHERE student_id = %s", (session['user_id'],))
    profile['skills'] = cursor.fetchall()

    cursor.close()
    conn.close()
    return render_template('profile.html', profile=profile)

@app.route('/parse-resume', methods=['POST'])
def parse_resume_route():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    resume_text = request.form['resume_text']
    try:
        parsed_data = parse_resume(resume_text)
        return jsonify({"status": "success", "data": parsed_data})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/add-opportunity', methods=['GET', 'POST'])
def add_opportunity():
    if request.method == 'POST':
        title = request.form['title']
        opp_type = request.form['type']
        description = request.form['description']
        app_url = request.form['application_url']
        skills = json.dumps(request.form['skills'].split(','))
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO opportunities (title, type, description, required_skills_json, application_url) VALUES (%s, %s, %s, %s, %s)",
                       (title, opp_type, description, skills, app_url))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Opportunity added successfully!')
        return redirect(url_for('find_opportunities'))
    return render_template('add_opportunity.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM student_profiles WHERE user_id = %s", (session['user_id'],))
    profile = cursor.fetchone()

    cursor.execute("SELECT opportunity_id FROM saved_opportunities WHERE user_id = %s", (session['user_id'],))
    saved_ids = {row['opportunity_id'] for row in cursor.fetchall()}

    cursor.close()
    conn.close()

    # Broad feed: fetch WITHOUT user skills/location; rank below with
    # load_student_recommendation_data() + RecommendationEngine.
    logger.info("DEBUG dashboard: fetching broad Adzuna feed (no what, no where)")
    tz_name = os.environ.get('TZ', 'UTC')
    service = OpportunityDataService()
    repo = OpportunityRepository()
    engine = RecommendationEngine()

    api_opportunities = service.fetch_broad_feed(results_per_page=15, tz_name=tz_name)
    repo.upsert_many(api_opportunities)
    active = repo.get_active_opportunities(limit=15)

    student = engine.build_student_profile(**load_student_recommendation_data(session['user_id']))
    ranked = engine.rank(active, student)
    for opp in ranked:
        raw_apply_url = opp.get('application_url')
        opp['apply_url'] = raw_apply_url if is_valid_application_url(raw_apply_url) else None

    opp_filter = request.args.get('filter', 'all')
    if opp_filter in ('job', 'internship'):
        ranked = [o for o in ranked if o.get('opp_type') == opp_filter]
    elif opp_filter == 'saved':
        ranked = [o for o in ranked if o.get('id') in saved_ids]

    return render_template('dashboard.html', profile=profile,
                           opportunities=ranked[:6], opp_filter=opp_filter,
                           saved_ids=saved_ids)


@app.route('/save-opportunity/<int:opp_id>', methods=['POST'])
def save_opportunity(opp_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT IGNORE INTO saved_opportunities (user_id, opportunity_id) VALUES (%s, %s)",
                   (session['user_id'], opp_id))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(request.referrer or url_for('dashboard'))


@app.route('/unsave-opportunity/<int:opp_id>', methods=['POST'])
def unsave_opportunity(opp_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM saved_opportunities WHERE user_id = %s AND opportunity_id = %s",
                   (session['user_id'], opp_id))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(request.referrer or url_for('dashboard'))

import json

@app.route('/find-opportunities')
def find_opportunities():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT full_name, address, summary FROM student_profiles WHERE user_id = %s", (session['user_id'],))
    profile = cursor.fetchone()

    cursor.close()
    conn.close()

    logger.info("DEBUG find-opportunities: fetching broad Adzuna feed (no what, no where)")
    tz_name = os.environ.get('TZ', 'UTC')
    service = OpportunityDataService()
    repo = OpportunityRepository()
    engine = RecommendationEngine()

    api_opportunities = service.fetch_broad_feed(results_per_page=15, tz_name=tz_name)
    repo.upsert_many(api_opportunities)
    active = repo.get_active_opportunities(limit=15)

    student_data = load_student_recommendation_data(session['user_id'])
    student = engine.build_student_profile(**student_data)
    opportunities = engine.rank(active, student)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT resume_text, summary, bio FROM student_profiles WHERE user_id = %s", (session['user_id'],))
    resume_row = cursor.fetchone() or {}
    cursor.close()
    conn.close()
    resume_texts = [resume_row.get('resume_text'), resume_row.get('summary'), resume_row.get('bio')]
    student['projects'] = student_data['projects']
    ats_analyzer = ATSCompatibilityAnalyzer()
    for opp in opportunities:
        required = engine.resolve_required_skills(opp, student['skills'])
        opp['ats_score'] = ats_analyzer.quick_score(resume_texts, student, opp, required)
        raw_apply_url = opp.get('application_url')
        opp['apply_url'] = raw_apply_url if is_valid_application_url(raw_apply_url) else None

    return render_template('opportunities.html', opportunities=opportunities, profile=profile)

@app.route('/opportunity/<int:opp_id>')
def opportunity_detail(opp_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    repo = OpportunityRepository()
    db_opp = repo.get_by_id(opp_id)
    if not db_opp:
        flash('Opportunity not found.')
        return redirect(url_for('find_opportunities'))

    gap = analyze_opportunity_gap(session['user_id'], db_opp)
    matched_skills = gap['matched']
    missing_skills = gap['missing']
    total_req = len(matched_skills) + len(missing_skills) or 1
    match_percent = round(len(matched_skills) / total_req * 100)

    data = load_student_recommendation_data(session['user_id'])
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT github_url FROM student_profiles WHERE user_id = %s", (session['user_id'],))
    profile_row = cursor.fetchone() or {}
    cursor.close()
    conn.close()

    engine = RecommendationEngine()
    student = engine.build_student_profile(
        skills=data['skills'], projects=data['projects'], education=data['education'])
    student['projects'] = data['projects']
    student['github_url'] = profile_row.get('github_url')

    improvement_path = ImprovementPathGenerator().generate(
        gap=gap, student=student, opportunity=db_opp, current_score=match_percent)

    ats = ATSCompatibilityAnalyzer().analyze(
        resume_texts=gap['resume_texts'], student={**gap['student'], 'projects': data['projects']},
        opportunity=db_opp, required_map=gap['required_map'])

    raw_apply_url = db_opp.get('application_url')
    apply_url = raw_apply_url if is_valid_application_url(raw_apply_url) else None

    return render_template('opportunity_detail.html', opp=db_opp,
                           required_skills=sorted(gap['required_map'].values()),
                           matched_skills=matched_skills,
                           missing_skills=missing_skills,
                           match_percent=match_percent,
                           skill_evidence=gap['evidence'],
                           improvement_path=improvement_path,
                           ats_score=ats['score'],
                           ats_suggestions=ats['suggestions'],
                           ats_disclaimer=ats['disclaimer'],
                           apply_url=apply_url)

@app.route('/find-opps-api', methods=['POST'])
def find_opps_api():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    logger.info(f"DEBUG Fetch Latest request received for user_id={session['user_id']}")
    logger.info(f"DEBUG Adzuna creds present: app_id={bool(os.environ.get('ADZUNA_APP_ID'))}, app_key={bool(os.environ.get('ADZUNA_APP_KEY'))}")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT full_name, address, summary FROM student_profiles WHERE user_id = %s", (session['user_id'],))
    profile = cursor.fetchone()

    cursor.close()
    conn.close()

    logger.info("DEBUG find-opps-api: fetching broad Adzuna feed (no what, no where)")
    tz_name = os.environ.get('TZ', 'UTC')
    service = OpportunityDataService()
    repo = OpportunityRepository()
    engine = RecommendationEngine()

    api_opportunities = service.fetch_broad_feed(results_per_page=15, tz_name=tz_name)
    logger.info(f"DEBUG fetched from service: {len(api_opportunities)}")
    stats = repo.upsert_many(api_opportunities)
    logger.info(f"DEBUG saved/updated in database: {stats}")
    active = repo.get_active_opportunities(limit=15)
    logger.info(f"DEBUG active in database: {len(active)}")

    student_data = load_student_recommendation_data(session['user_id'])
    student = engine.build_student_profile(**student_data)
    opportunities = engine.rank(active, student)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT resume_text, summary, bio FROM student_profiles WHERE user_id = %s", (session['user_id'],))
    resume_row = cursor.fetchone() or {}
    cursor.close()
    conn.close()
    resume_texts = [resume_row.get('resume_text'), resume_row.get('summary'), resume_row.get('bio')]
    student['projects'] = student_data['projects']
    ats_analyzer = ATSCompatibilityAnalyzer()
    for opp in opportunities:
        required = engine.resolve_required_skills(opp, student['skills'])
        opp['ats_score'] = ats_analyzer.quick_score(resume_texts, student, opp, required)
        raw_apply_url = opp.get('application_url')
        opp['apply_url'] = raw_apply_url if is_valid_application_url(raw_apply_url) else None

    logger.info(f"DEBUG final response to frontend: {len(opportunities)} opportunities")
    return jsonify({"status": "success", "opportunities": opportunities})


@app.route('/fetch-jooble', methods=['POST'])
def fetch_jooble():
    """Jooble-only fetch endpoint (mirrors /find-opps-api). No UI changes."""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    from job_providers import get_provider, to_legacy_opportunity
    logger.info(f"DEBUG Jooble fetch request received for user_id={session['user_id']}")
    logger.info(f"DEBUG Jooble key present: {bool(os.environ.get('JOOBLE_API_KEY'))}")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT full_name, address FROM student_profiles WHERE user_id = %s", (session['user_id'],))
    profile = cursor.fetchone()
    cursor.execute("""
        SELECT s.skill_name
        FROM skills s
        JOIN student_skills ss ON s.id = ss.skill_id
        WHERE ss.student_id = %s
    """, (session['user_id'],))
    student_skills = [row['skill_name'] for row in cursor.fetchall()]
    cursor.close()
    conn.close()

    location = profile['address'] if profile and profile.get('address') else 'India'
    provider = get_provider('Jooble')
    common = provider.search(skills=student_skills, location=location, limit=20)
    logger.info(f"DEBUG Jooble normalized: {len(common)}")

    repo = OpportunityRepository()
    stats = repo.upsert_many([to_legacy_opportunity(o) for o in common])
    logger.info(f"DEBUG Jooble saved/updated in database: {stats}")

    return jsonify({"status": "success", "provider": "Jooble", "opportunities": common})


@app.route('/fetch-jobvetta', methods=['POST'])
def fetch_jobvetta():
    """Jobvetta-only fetch endpoint (mirrors /fetch-jooble). No UI changes."""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    from job_providers import get_provider, to_legacy_opportunity
    logger.info(f"DEBUG Jobvetta fetch request received for user_id={session['user_id']}")
    logger.info(f"DEBUG Jobvetta key present: {bool(os.environ.get('JOBVETTA_API_KEY'))}")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT full_name, address FROM student_profiles WHERE user_id = %s", (session['user_id'],))
    profile = cursor.fetchone()
    cursor.execute("""
        SELECT s.skill_name
        FROM skills s
        JOIN student_skills ss ON s.id = ss.skill_id
        WHERE ss.student_id = %s
    """, (session['user_id'],))
    student_skills = [row['skill_name'] for row in cursor.fetchall()]
    cursor.close()
    conn.close()

    location = profile['address'] if profile and profile.get('address') else 'India'
    provider = get_provider('Jobvetta')
    common = provider.search(skills=student_skills, location=location, limit=10)
    logger.info(f"DEBUG Jobvetta normalized: {len(common)}")

    repo = OpportunityRepository()
    stats = repo.upsert_many([to_legacy_opportunity(o) for o in common])
    logger.info(f"DEBUG Jobvetta saved/updated in database: {stats}")

    return jsonify({"status": "success", "provider": "Jobvetta", "opportunities": common})


@app.route('/fetch-indianapi', methods=['POST'])
def fetch_indianapi():
    """IndianAPI-only fetch endpoint (mirrors /fetch-jobvetta). No UI changes."""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    from job_providers import get_provider, to_legacy_opportunity
    logger.info(f"DEBUG IndianAPI fetch request received for user_id={session['user_id']}")
    logger.info(f"DEBUG IndianAPI key present: {bool(os.environ.get('INDIANAPI_KEY'))}")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT full_name, address FROM student_profiles WHERE user_id = %s", (session['user_id'],))
    profile = cursor.fetchone()
    cursor.execute("""
        SELECT s.skill_name
        FROM skills s
        JOIN student_skills ss ON s.id = ss.skill_id
        WHERE ss.student_id = %s
    """, (session['user_id'],))
    student_skills = [row['skill_name'] for row in cursor.fetchall()]
    cursor.close()
    conn.close()

    location = profile['address'] if profile and profile.get('address') else 'India'
    provider = get_provider('IndianAPI')
    common = provider.search(skills=student_skills, location=location, limit=10)
    logger.info(f"DEBUG IndianAPI normalized: {len(common)}")

    repo = OpportunityRepository()
    stats = repo.upsert_many([to_legacy_opportunity(o) for o in common])
    logger.info(f"DEBUG IndianAPI saved/updated in database: {stats}")

    return jsonify({"status": "success", "provider": "IndianAPI", "opportunities": common})

@app.route('/resume-select')
def resume_select():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('resume_selection.html')

@app.route('/generate-resume-final', methods=['POST'])
def generate_resume_final():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    template = request.form.get('template', 'template1')
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM student_profiles WHERE user_id = %s", (session['user_id'],))
    profile = cursor.fetchone()
    
    # Fetch all linked data
    cursor.execute("SELECT * FROM education WHERE student_id = %s", (session['user_id'],))
    education = cursor.fetchall()
    cursor.execute("SELECT * FROM work_experience WHERE student_id = %s", (session['user_id'],))
    experience = cursor.fetchall()
    cursor.execute("SELECT * FROM projects WHERE student_id = %s", (session['user_id'],))
    projects = cursor.fetchall()
    cursor.execute("SELECT * FROM skills WHERE student_id = %s", (session['user_id'],))
    skills = cursor.fetchall()
    cursor.execute("SELECT * FROM certifications WHERE student_id = %s", (session['user_id'],))
    certifications = cursor.fetchall()
    cursor.execute("SELECT * FROM achievements WHERE student_id = %s", (session['user_id'],))
    achievements = cursor.fetchall()
    cursor.execute("SELECT * FROM languages WHERE student_id = %s", (session['user_id'],))
    languages = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template(f'templates/{template}.html', 
                           profile=profile, education=education, experience=experience, 
                           projects=projects, skills=skills, certifications=certifications, 
                           achievements=achievements, languages=languages)

@app.route('/save-template', methods=['POST'])
def save_template():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    template = request.form.get('template', 'template1')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE student_profiles SET selected_template=%s WHERE user_id=%s", (template, session['user_id']))
    conn.commit()
    cursor.close()
    conn.close()
    
    flash('Template saved successfully!')
    return redirect(url_for('resume_select'))

@app.route('/apply/<int:opp_id>')
def apply_opportunity(opp_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT application_url FROM opportunities WHERE id = %s", (opp_id,))
    opp = cursor.fetchone()
    
    raw_apply_url = opp.get('application_url') if opp else None
    if is_valid_application_url(raw_apply_url):
        cursor.close()
        conn.close()
        return redirect(raw_apply_url)
    
    cursor.close()
    conn.close()
    flash('Application link unavailable.')
    return redirect(url_for('opportunity_detail', opp_id=opp_id))

@app.route('/skill-gap-analysis/<int:opp_id>')
def skill_gap_analysis(opp_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    repo = OpportunityRepository()
    db_opp = repo.get_by_id(opp_id)
    if not db_opp:
        flash('Opportunity not found.')
        return redirect(url_for('find_opportunities'))

    gap = analyze_opportunity_gap(session['user_id'], db_opp)

    return render_template('skill_gap.html', opp=db_opp,
                           matched_skills=gap['matched'],
                           missing_skills=gap['missing'])

if __name__ == '__main__':
    app.run(debug=True)
