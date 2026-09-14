# AI Student Platform – Internship & Job Recommendation System

## 📌 Project Overview

**AI Student Platform** is a Flask-based web application designed to help students discover suitable internships and job opportunities based on their **skills, education, projects, and experience**.

The platform fetches job and internship opportunities from external job data sources and uses a recommendation/ranking system to personalize the opportunities for each student.

The project also includes AI-powered resume parsing and career-related features to help students understand their career opportunities and skill gaps.

---

## 🚀 Features

* 🎓 Student profile management
* 💼 Internship and job opportunity discovery
* 🤖 AI-powered resume parsing
* 🧠 Personalized opportunity ranking
* 🛠️ Skill-based recommendation
* 🎯 Education-based recommendation
* 📂 Project-based recommendation
* 📊 Skill gap analysis
* 📄 Resume/ATS-related functionality
* 🌐 Job opportunity data integration using Adzuna API
* 🗄️ MySQL database integration
* 🔐 Environment variable support for API keys and credentials
* 🌱 Team-friendly project structure

---

## 🛠️ Technologies Used

### Backend

* Python
* Flask

### Database

* MySQL

### AI

* OpenAI API
* AI-based resume processing

### Job Data

* Adzuna API

### Frontend

* HTML
* CSS
* JavaScript

### Development Tools

* Git
* GitHub
* Python Virtual Environment

---

## 📂 Project Structure

```text
ai-student-platform-flask/
│
├── app/
│   ├── app.py
│   ├── ai_service.py
│   ├── opportunity_data_service.py
│   ├── recommendation_engine.py
│   └── ...
│
├── static/
│
├── templates/
│
├── full_schema.sql
├── schema.sql
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## ⚙️ Installation & Setup

### 1. Clone the Repository

```bash
git clone AI Student Support & Opportunity Platform 
```

Move into the project directory:

```bash
cd ai-student-platform-flask
```

---

### 2. Create a Virtual Environment

Create a Python virtual environment:

```bash
python -m venv venv
```

Activate it on Windows:

```bash
venv\Scripts\activate
```

---

### 3. Install Dependencies

Install all required Python packages:

```bash
pip install -r requirements.txt
```

---

## 🗄️ MySQL Database Setup

Make sure **MySQL Server** is installed and running.

Create the project database:

```sql
CREATE DATABASE student_platform;
```

Then import the database schema:

```bash
mysql -u root -p student_platform < full_schema.sql
```

If your MySQL username, password, host, or port is different, update the configuration in your `.env` file.

---

## 🔐 Environment Variables

The project uses environment variables for sensitive information such as API keys and database credentials.

Create a `.env` file in the project root.

You can use `.env.example` as a template.

Example:

```env
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=your_mysql_username
DB_PASSWORD=your_mysql_password
DB_NAME=student_platform

ADZUNA_APP_ID=your_adzuna_app_id
ADZUNA_APP_KEY=your_adzuna_app_key
ADZUNA_COUNTRY=in

OPENAI_API_KEY=your_openai_api_key
```

### ⚠️ Important

**Never upload `.env` to GitHub.**

The `.env` file may contain passwords and API keys.

Only commit:

```text
.env.example
```

---

## ▶️ Running the Application

Start the Flask application:

```bash
python app\app.py
```

The application will normally be available at:

```text
http://127.0.0.1:5000
```

Open the URL in your browser.

---

## 💼 Internship & Job Recommendation System

The platform retrieves a broad set of job and internship opportunities.

The fetched opportunities are then ranked according to the student's profile.

The recommendation system can consider factors such as:

* Student skills
* Education
* Projects
* Experience
* Other profile information

This allows different students to receive different opportunity rankings based on their profiles.

### Broad Job Feed

The application does not restrict the initial job feed to a student's location or skills.

Instead:

```text
Job Data
   ↓
Broad Opportunity Feed
   ↓
Student Profile
   ↓
Skills / Education / Projects
   ↓
Recommendation & Ranking
   ↓
Personalized Opportunities
```

The current Adzuna configuration uses the selected country configured through `ADZUNA_COUNTRY`.

---

## 🤖 AI Resume Parsing

The application supports AI-assisted resume processing.

A resume can be processed to extract relevant information such as:

* Skills
* Education
* Experience
* Projects
* Other career-related information

The extracted information can be used as part of the student's profile and recommendation workflow.

An `OPENAI_API_KEY` is required for AI-powered resume parsing.

---

## 📊 Skill Gap Analysis

The platform can help identify differences between a student's existing skills and the skills expected for career opportunities.

This can help students understand:

* Which skills they already have
* Which skills they may need to improve
* Which skills are relevant to potential opportunities

---

## 👥 Team Development

This project is designed to be developed collaboratively using GitHub.

Each team member can clone the repository and set up their own local environment.

### Basic Team Workflow

```bash
git pull
```

Make your changes, then:

```bash
git add .
git commit -m "Describe your changes"
git push
```

Before starting new work, it is recommended to pull the latest changes:

```bash
git pull
```

### Important

Team members should create their own local `.env` file.

Do not commit API keys, passwords, or other sensitive credentials.

---

## 🧪 Project Verification

Before committing major changes, it is recommended to verify that the application starts correctly and that modified Python files do not contain syntax errors.

Example:

```bash
python -m py_compile app\app.py
```

---

## 🔮 Future Improvements

Possible future improvements include:

* Advanced AI career guidance
* More job/internship data sources
* Improved recommendation algorithms
* Advanced ATS scoring
* Personalized learning roadmaps
* Skill-demand analysis
* More detailed analytics dashboards
* Additional country/job-market support
* Improved resume analysis
* Automated career-path recommendations

---

## 📜 License

This project is currently developed as an educational/internship project.

License information can be added when the project is ready for public distribution.

---

## 👨‍💻 Project Team

**AI Student Platform Team**

A collaborative project focused on helping students discover career opportunities using AI, data, and personalized recommendation techniques.
