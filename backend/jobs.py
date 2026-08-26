import urllib.request
import json
import xml.etree.ElementTree as ET
import re
import time
from backend import db

# Cache jobs in memory to avoid constant fetching (since remote APIs rate limit)
_jobs_cache = {
    "timestamp": 0,
    "data": []
}
CACHE_DURATION_SECS = 1800 # 30 minutes

def clean_html(raw_html: str) -> str:
    """Removes HTML tags from a text string."""
    clean_re = re.compile('<.*?>')
    return re.sub(clean_re, '', raw_html)

def fetch_remoteok_jobs() -> list[dict]:
    """Fetches programming jobs from RemoteOK API."""
    jobs = []
    try:
        url = "https://remoteok.com/api"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"}
        )
        with urllib.request.urlopen(req, timeout=8) as response:
            data = json.loads(response.read().decode())
            # RemoteOK returns standard legal notice as first element
            for item in data[1:]:
                if "position" in item:
                    # Clean tags and descriptions
                    tags = item.get("tags", [])
                    desc = clean_html(item.get("description", ""))
                    jobs.append({
                        "id": f"remoteok_{item.get('id', hash(item.get('position')))}",
                        "title": item.get("position"),
                        "company": item.get("company"),
                        "location": item.get("location") or "Remote",
                        "tags": [t.lower() for t in tags],
                        "description": desc,
                        "url": item.get("url"),
                        "source": "RemoteOK"
                    })
    except Exception as e:
        print(f"Error fetching jobs from RemoteOK: {e}")
    return jobs

def fetch_weworkremotely_jobs() -> list[dict]:
    """Fetches jobs from WeWorkRemotely RSS feed."""
    jobs = []
    try:
        url = "https://weworkremotely.com/categories/remote-programming-jobs.rss"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=8) as response:
            xml_data = response.read()
            root = ET.fromstring(xml_data)
            for item in root.findall(".//item"):
                title_text = item.find("title").text if item.find("title") is not None else ""
                # Title on WWR RSS is usually "Company: Position"
                company = "Remote Company"
                position = title_text
                if ":" in title_text:
                    parts = title_text.split(":", 1)
                    company = parts[0].strip()
                    position = parts[1].strip()
                
                link = item.find("link").text if item.find("link") is not None else ""
                desc = item.find("description").text if item.find("description") is not None else ""
                desc = clean_html(desc)
                
                # WWR doesn't provide tags in RSS, but we can extract keywords from title
                tags = [w.lower() for w in position.split() if len(w) > 3]
                
                jobs.append({
                    "id": f"wwr_{hash(link)}",
                    "title": position,
                    "company": company,
                    "location": "Remote",
                    "tags": tags,
                    "description": desc,
                    "url": link,
                    "source": "WeWorkRemotely"
                })
    except Exception as e:
        print(f"Error fetching jobs from WeWorkRemotely: {e}")
    return jobs

def get_live_jobs() -> list[dict]:
    """Gets job listings, using in-memory cache if fresh."""
    global _jobs_cache
    now = time.time()
    if now - _jobs_cache["timestamp"] < CACHE_DURATION_SECS and _jobs_cache["data"]:
        return _jobs_cache["data"]
        
    # Fetch from both sources
    rok_jobs = fetch_remoteok_jobs()
    wwr_jobs = fetch_weworkremotely_jobs()
    
    # Merge and cache
    all_jobs = rok_jobs + wwr_jobs
    if all_jobs:
        _jobs_cache["data"] = all_jobs
        _jobs_cache["timestamp"] = now
    return all_jobs

def calculate_job_matches(student_skills: list[dict], target_role: str = None) -> list[dict]:
    """Calculates matching scores for live job listings based on student skills and target role."""
    jobs = get_live_jobs()
    if not jobs:
        # Fallback dummy job openings if network failed or no jobs loaded
        jobs = [
            {
                "id": "mock_1",
                "title": "Junior Frontend Developer",
                "company": "TechVibe Solutions",
                "location": "Remote (USA/Canada)",
                "tags": ["react", "javascript", "html", "css", "git"],
                "description": "We are looking for a junior React/Frontend developer to join our growing engineering team. Knowledge of CSS grid, React hooks, and Git is preferred.",
                "url": "https://example.com/jobs/1",
                "source": "System Matcher"
            },
            {
                "id": "mock_2",
                "title": "Software Engineer Intern (Python)",
                "company": "ByteCraft AI",
                "location": "Remote (Global)",
                "tags": ["python", "sql", "fastapi", "docker"],
                "description": "Looking for a Python software developer intern. You will work on writing FastAPI backend routes, integrating SQL databases, and setting up Docker environments.",
                "url": "https://example.com/jobs/2",
                "source": "System Matcher"
            },
            {
                "id": "mock_3",
                "title": "Data Analyst (SQL / Python)",
                "company": "MetricFlow Corp",
                "location": "Bengaluru, India (Hybrid)",
                "tags": ["python", "sql", "pandas", "data science"],
                "description": "Join our data operations team! Requirements include strong SQL query building, data modeling, and python script generation for cleaning data sets.",
                "url": "https://example.com/jobs/3",
                "source": "System Matcher"
            },
            {
                "id": "mock_4",
                "title": "Full Stack Developer (Node.js & React)",
                "company": "OmniStack Systems",
                "location": "Remote (India)",
                "tags": ["javascript", "react", "node.js", "mongodb", "git"],
                "description": "Full stack engineering opening. We build apps using Node.js, Express, React, and MongoDB. Familiarity with typescript and git workflows is required.",
                "url": "https://example.com/jobs/4",
                "source": "System Matcher"
            }
        ]
        
    student_skill_names = {s["skill_name"].lower(): s["level"] for s in student_skills}
    matched_jobs = []
    
    for job in jobs:
        score = 50.0  # base match score
        matched_skills = []
        missing_skills = []
        
        # 1. Evaluate Skill Tag Overlaps
        job_words_and_tags = set(job["tags"])
        
        # Also extract words from title and description
        text_corpus = (job["title"] + " " + job["description"]).lower()
        
        for s_name, level in student_skill_names.items():
            # Check if skill name is in tags, title, or description
            pattern = rf"\b{re.escape(s_name)}\b"
            if s_name in job_words_and_tags or re.search(pattern, text_corpus):
                matched_skills.append(s_name.title())
                # Add score based on student skill level (higher level -> better score boost)
                score += (level / 100.0) * 10
            else:
                # Skill is missing in student profile, but is it a job requirement?
                # Check if this skill name occurs in the job description or title
                # If so, it's a gap!
                if s_name in ["react", "python", "javascript", "sql", "java", "git", "typescript", "docker", "aws"]:
                    # check if the job specifies it
                    if re.search(rf"\b{re.escape(s_name)}\b", text_corpus):
                        missing_skills.append(s_name.title())
                        
        # 2. Evaluate Target Role Match
        if target_role:
            target_words = set(target_role.lower().split())
            title_words = set(job["title"].lower().split())
            overlap_words = target_words.intersection(title_words)
            if overlap_words:
                score += len(overlap_words) * 12
                
        # Cap score between 40% and 98%
        score = min(max(score, 40.0), 98.0)
        
        matched_jobs.append({
            "id": job["id"],
            "title": job["title"],
            "company": job["company"],
            "location": job["location"],
            "tags": job["tags"][:5], # limit tags
            "url": job["url"],
            "source": job["source"],
            "match_score": round(score),
            "matched_skills": matched_skills,
            "missing_skills": missing_skills
        })
        
    # Sort matched jobs by match score descending
    matched_jobs.sort(key=lambda x: x["match_score"], reverse=True)
    return matched_jobs

def get_skill_gaps_and_recommendations(target_role: str, student_skills: list[dict]) -> dict:
    """Compares student skills to standard target role requirements to identify gaps & recommend learning paths."""
    # Standard role requirements database
    role_requirements = {
        "frontend developer": {
            "required": ["HTML/CSS", "JavaScript", "React", "Git", "TypeScript"],
            "recommendations": [
                {"topic": "React Hooks & State Management", "resource": "Official React Documentation (react.dev)"},
                {"topic": "TypeScript Basics", "resource": "TypeScript Handbook"},
                {"topic": "Responsive CSS & Flexbox/Grid", "resource": "MDN Web Docs / CSS Grid Guide"},
                {"topic": "Git Version Control", "resource": "GitHub Learning Lab"}
            ]
        },
        "backend developer": {
            "required": ["Python", "SQL", "Git", "Docker", "FastAPI", "PostgreSQL"],
            "recommendations": [
                {"topic": "Relational Databases & SQL", "resource": "SQL Zoo / Mode Analytics SQL"},
                {"topic": "FastAPI Web Framework", "resource": "FastAPI Tutorial User Guide"},
                {"topic": "Docker Containerization", "resource": "Docker Curriculum (docker-curriculum.com)"},
                {"topic": "Backend System Design", "resource": "Grokking the System Design Interview"}
            ]
        },
        "data scientist": {
            "required": ["Python", "SQL", "Machine Learning", "Pandas", "Math/Statistics"],
            "recommendations": [
                {"topic": "Data Analysis with Pandas", "resource": "Kaggle Pandas Course"},
                {"topic": "Intro to Machine Learning", "resource": "Machine Learning by Andrew Ng (Coursera)"},
                {"topic": "Statistical Analysis", "resource": "OpenIntro Statistics"},
                {"topic": "SQL for Data Analysis", "resource": "DataCamp SQL Fundamentals"}
            ]
        },
        "full stack developer": {
            "required": ["JavaScript", "React", "Node.js", "SQL", "MongoDB", "Git"],
            "recommendations": [
                {"topic": "Full-Stack Development (MERN/PERN)", "resource": "Full Stack Open (University of Helsinki)"},
                {"topic": "RESTful API Design with Node & Express", "resource": "MDN Express Tutorial"},
                {"topic": "NoSQL Databases (MongoDB)", "resource": "MongoDB University"},
                {"topic": "CI/CD & Deployment", "resource": "GitHub Actions documentation"}
            ]
        }
    }
    
    normalized_role = (target_role or "").strip().lower()
    # Default fallback requirements if role not in predefined list
    requirements = role_requirements.get(normalized_role, {
        "required": ["Python", "SQL", "Git", "Communication"],
        "recommendations": [
            {"topic": "Programming Fundamentals", "resource": "Learn Python the Hard Way"},
            {"topic": "Data Modeling", "resource": "W3Schools SQL Tutorial"},
            {"topic": "Software Engineering Best Practices", "resource": "Clean Code by Robert C. Martin"}
        ]
    })
    
    student_skill_set = {s["skill_name"].lower() for s in student_skills}
    
    skills_acquired = []
    skills_gap = []
    
    for r_skill in requirements["required"]:
        if r_skill.lower() in student_skill_set:
            skills_acquired.append(r_skill)
        else:
            skills_gap.append(r_skill)
            
    # Filter learning recommendations to focus on skills gap
    learning_recommendations = []
    for rec in requirements["recommendations"]:
        # If any word in the topic matches a gap skill, prioritize it
        rec_words = rec["topic"].lower()
        is_gap_rel = False
        for gap in skills_gap:
            if gap.lower() in rec_words:
                is_gap_rel = True
                break
        
        # Include if it is relevant to a gap or we have few recommendations
        if is_gap_rel or len(learning_recommendations) < 3:
            learning_recommendations.append(rec)
            
    return {
        "target_role": target_role or "General Software Engineer",
        "skills_acquired": skills_acquired,
        "skills_gap": skills_gap,
        "recommendations": learning_recommendations
    }
