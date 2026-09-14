-- Database schema for AI Student Support Platform
-- Kept consistent with full_schema.sql and app/app.py queries.
-- Fresh install: mysql -u root -p < schema.sql
-- Existing DB: mysql -u root -p student_platform < full_schema.sql (runs migration block at bottom)

CREATE DATABASE IF NOT EXISTS student_platform;
USE student_platform;

-- Users for Authentication
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Student Profiles (email + phone_number required by app/app.py profile UPDATE)
CREATE TABLE IF NOT EXISTS student_profiles (
    user_id INT PRIMARY KEY,
    full_name VARCHAR(100),
    email VARCHAR(255) NULL,
    phone_number VARCHAR(50) NULL,
    dob DATE,
    bio TEXT,
    photo_url VARCHAR(255),
    resume_text LONGTEXT,
    address VARCHAR(255),
    linkedin_url VARCHAR(255),
    github_url VARCHAR(255),
    summary TEXT,
    selected_template VARCHAR(50) DEFAULT 'template1',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Education (matches app/app.py: degree_type, branch, start_year, end_year, location, score_type, score_value)
CREATE TABLE IF NOT EXISTS education (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT,
    degree_type VARCHAR(100),
    institution VARCHAR(255),
    branch VARCHAR(100),
    start_year INT,
    end_year INT,
    location VARCHAR(255),
    score_type VARCHAR(50),
    score_value VARCHAR(50),
    FOREIGN KEY (student_id) REFERENCES student_profiles(user_id) ON DELETE CASCADE
);

-- Internships (preserved)
CREATE TABLE IF NOT EXISTS internships (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT,
    company VARCHAR(255),
    role VARCHAR(255),
    duration VARCHAR(100),
    FOREIGN KEY (student_id) REFERENCES student_profiles(user_id) ON DELETE CASCADE
);

-- Work Experience (required by app/app.py profile POST + resume builder)
CREATE TABLE IF NOT EXISTS work_experience (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    job_title VARCHAR(255),
    company_name VARCHAR(255),
    location VARCHAR(255),
    start_date DATE NULL,
    end_date DATE NULL,
    description TEXT,
    INDEX idx_workexp_student (student_id),
    FOREIGN KEY (student_id) REFERENCES student_profiles(user_id) ON DELETE CASCADE
);

-- Projects (required by app/app.py + load_student_recommendation_data())
CREATE TABLE IF NOT EXISTS projects (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    title VARCHAR(255),
    technologies TEXT,
    link VARCHAR(500) NULL,
    description TEXT,
    INDEX idx_projects_student (student_id),
    FOREIGN KEY (student_id) REFERENCES student_profiles(user_id) ON DELETE CASCADE
);

-- Certifications (required by app/app.py profile POST + resume builder)
CREATE TABLE IF NOT EXISTS certifications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    title VARCHAR(255) NOT NULL,
    INDEX idx_certs_student (student_id),
    FOREIGN KEY (student_id) REFERENCES student_profiles(user_id) ON DELETE CASCADE
);

-- Achievements (required by app/app.py profile POST + resume builder)
CREATE TABLE IF NOT EXISTS achievements (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    title VARCHAR(255) NOT NULL,
    INDEX idx_achieve_student (student_id),
    FOREIGN KEY (student_id) REFERENCES student_profiles(user_id) ON DELETE CASCADE
);

-- Languages (required by app/app.py profile POST + resume builder)
CREATE TABLE IF NOT EXISTS languages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    language_name VARCHAR(100) NOT NULL,
    INDEX idx_lang_student (student_id),
    FOREIGN KEY (student_id) REFERENCES student_profiles(user_id) ON DELETE CASCADE
);

-- Skills: direct per-student skills (student_id, skill_type) + legacy catalog rows (student_id IS NULL) for student_skills mapping
CREATE TABLE IF NOT EXISTS skills (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NULL,
    skill_name VARCHAR(100) NOT NULL,
    skill_type VARCHAR(20) NULL,
    INDEX idx_skills_student (student_id),
    FOREIGN KEY (student_id) REFERENCES student_profiles(user_id) ON DELETE CASCADE
);

-- Mapping Skills to Students (preserved)
CREATE TABLE IF NOT EXISTS student_skills (
    student_id INT,
    skill_id INT,
    proficiency_level INT, -- 1 to 5
    PRIMARY KEY (student_id, skill_id),
    FOREIGN KEY (student_id) REFERENCES student_profiles(user_id) ON DELETE CASCADE,
    FOREIGN KEY (skill_id) REFERENCES skills(id)
);

-- Opportunities (canonical cache of normalized external listings, preserved from full_schema.sql)
CREATE TABLE IF NOT EXISTS opportunities (
    id INT AUTO_INCREMENT PRIMARY KEY,
    external_id VARCHAR(100) NULL,
    title VARCHAR(255) NOT NULL,
    company VARCHAR(255) NULL,
    location VARCHAR(255) NULL,
    type ENUM('job', 'internship', 'scholarship') NOT NULL,
    description TEXT,
    required_skills_json JSON,
    application_url VARCHAR(255),
    source VARCHAR(50) NULL,
    salary_stipend VARCHAR(100) NULL,
    deadline DATE,
    start_date DATE NULL,
    last_fetched_at TIMESTAMP NULL DEFAULT NULL,
    UNIQUE KEY uq_source_external (source, external_id),
    INDEX idx_deadline (deadline),
    INDEX idx_opp_type (type),
    INDEX idx_source (source)
);

-- Fetched Opportunities (API cache, preserved)
CREATE TABLE IF NOT EXISTS fetched_opportunities (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(255),
    company VARCHAR(255),
    location VARCHAR(255),
    description TEXT,
    opp_type VARCHAR(50),
    required_skills_json JSON,
    eligibility TEXT,
    important_dates JSON,
    salary_stipend VARCHAR(100),
    application_url VARCHAR(255),
    source VARCHAR(50),
    source_id VARCHAR(100),
    match_percent INT DEFAULT 0,
    ats_score INT DEFAULT 0,
    searched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    student_id INT,
    FOREIGN KEY (student_id) REFERENCES student_profiles(user_id) ON DELETE CASCADE
);

-- ATS Profiles (cached analysis, preserved)
CREATE TABLE IF NOT EXISTS ats_profiles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT,
    resume_text LONGTEXT,
    total_skills INT DEFAULT 0,
    matched_skills INT DEFAULT 0,
    ats_score INT DEFAULT 0,
    last_analyzed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES student_profiles(user_id) ON DELETE CASCADE
);

-- Personalized Improvement Paths (preserved)
CREATE TABLE IF NOT EXISTS improvement_paths (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT,
    opportunity_id INT,
    missing_skills TEXT,
    recommended_actions TEXT,
    target_score INT DEFAULT 0,
    current_score INT DEFAULT 0,
    estimated_time VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES student_profiles(user_id) ON DELETE CASCADE,
    FOREIGN KEY (opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE
);

-- Student Profile Updates (tracking profile changes, preserved)
CREATE TABLE IF NOT EXISTS profile_updates (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    changes TEXT,
    FOREIGN KEY (student_id) REFERENCES student_profiles(user_id) ON DELETE CASCADE
);

-- Saved Opportunities (student bookmarks, preserved)
CREATE TABLE IF NOT EXISTS saved_opportunities (
    user_id INT NOT NULL,
    opportunity_id INT NOT NULL,
    saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, opportunity_id),
    INDEX idx_saved_user (user_id),
    FOREIGN KEY (user_id) REFERENCES student_profiles(user_id) ON DELETE CASCADE,
    FOREIGN KEY (opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE
);
