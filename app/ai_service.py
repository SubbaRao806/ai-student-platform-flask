import os
from openai import OpenAI


def _get_client():
    """Create OpenAI client from env. Never hard-code keys."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in environment variables.")
    return OpenAI(api_key=api_key)


def parse_resume(resume_text):
    """Parse resume text. Returns JSON string with skills, experience_years, summary."""
    if not resume_text or not str(resume_text).strip():
        raise ValueError("resume_text is empty.")
    prompt = f"""
    Analyze the following resume and extract the skills and experience:
    {resume_text}
    Return the result in JSON format with keys: 'skills' (list), 'experience_years' (int), 'summary' (str).
    """

    client = _get_client()
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content
