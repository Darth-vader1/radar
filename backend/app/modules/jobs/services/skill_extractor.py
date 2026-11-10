import re
from typing import List, Set

from app.models.job import ExperienceLevel, JobCategory, RemoteStatus

# Recognized technology skills taxonomy
TECH_SKILLS = [
    # Languages
    "Python", "JavaScript", "TypeScript", "Go", "Golang", "Rust", "Java", "C++",
    "C#", "PHP", "Ruby", "Swift", "Kotlin", "Scala", "Dart", "SQL", "Bash",
    # Frontend
    "React", "Next.js", "Vue.js", "Angular", "Tailwind CSS", "HTML5", "CSS3",
    "Redux", "GraphQL", "Svelte", "Webpack",
    # Backend & Frameworks
    "FastAPI", "Django", "Flask", "Node.js", "Express", "NestJS", "Spring Boot",
    "Ruby on Rails", "Laravel", "ASP.NET", "gRPC",
    # Cloud, DevOps & Infra
    "AWS", "GCP", "Google Cloud", "Azure", "Docker", "Kubernetes", "Terraform",
    "Ansible", "CI/CD", "GitHub Actions", "GitLab CI", "Linux", "Prometheus", "Grafana",
    # Databases & Caching
    "PostgreSQL", "MySQL", "MongoDB", "Redis", "Elasticsearch", "Cassandra",
    "DynamoDB", "Snowflake", "BigQuery", "Kafka", "RabbitMQ",
    # AI & Data Science
    "Machine Learning", "Deep Learning", "PyTorch", "TensorFlow", "Pandas",
    "NumPy", "Scikit-Learn", "NLP", "Computer Vision", "LLM", "RAG",
    # Security & QA
    "Penetration Testing", "SOC 2", "OWASP", "Playwright", "Cypress", "Selenium", "Jest"
]

SKILL_PATTERNS = [(skill, re.compile(rf"\b{re.escape(skill)}\b", re.IGNORECASE)) for skill in TECH_SKILLS]


def extract_skills_from_text(text: str) -> List[str]:
    """Extracts known tech skills from job title, description, and requirements."""
    if not text:
        return []

    found: Set[str] = set()
    for skill_name, pattern in SKILL_PATTERNS:
        if pattern.search(text):
            found.add(skill_name)

    return sorted(list(found))


def classify_category(title: str, description: str = "") -> str:
    """Classifies a job into standard technology categories based on title and keywords."""
    combined = f"{title} {description[:500]}".lower()

    if any(k in combined for k in ("frontend", "front-end", "react", "vue", "angular", "ui engineer")):
        return JobCategory.FRONTEND.value
    if any(k in combined for k in ("backend", "back-end", "python engineer", "golang engineer", "java engineer", "django", "fastapi")):
        return JobCategory.BACKEND.value
    if any(k in combined for k in ("devops", "site reliability", "sre", "infrastructure engineer", "platform engineer", "kubernetes", "terraform")):
        return JobCategory.DEVOPS.value
    if any(k in combined for k in ("cloud engineer", "cloud architect", "aws architect", "azure architect")):
        return JobCategory.CLOUD.value
    if any(k in combined for k in ("ai/ml", "ai engineer", "machine learning", "ml engineer", "artificial intelligence", "deep learning", "nlp", "computer vision", "llm")):
        return JobCategory.AI_ML.value
    if any(k in combined for k in ("data scientist", "data analyst", "data engineer", "bi engineer", "analytics engineer")):
        return JobCategory.DATA_SCIENCE.value
    if any(k in combined for k in ("security", "cybersecurity", "infosec", "penetration tester", "soc analyst")):
        return JobCategory.CYBERSECURITY.value
    if any(k in combined for k in ("product design", "ui/ux", "ux designer", "ui designer")):
        return JobCategory.PRODUCT_DESIGN.value
    if any(k in combined for k in ("product manager", "technical product", "product owner")):
        return JobCategory.PRODUCT_MANAGEMENT.value
    if any(k in combined for k in ("software engineer", "developer", "full stack", "fullstack", "mobile engineer", "ios", "android")):
        return JobCategory.SOFTWARE_ENGINEERING.value

    return JobCategory.OTHER_TECH.value


def extract_experience_level(title: str, text: str = "") -> str:
    """Extracts seniority level from title and requirements."""
    t_lower = title.lower()

    if any(k in t_lower for k in ("intern", "internship", "graduate trainee", "apprentice")):
        return ExperienceLevel.INTERN.value
    if any(k in t_lower for k in ("junior", "entry level", "associate", "graduate")):
        return ExperienceLevel.ENTRY.value
    if any(k in t_lower for k in ("lead", "manager", "director", "head of", "vp")):
        return ExperienceLevel.LEAD_MANAGER.value
    if any(k in t_lower for k in ("staff", "principal", "distinguished", "architect")):
        return ExperienceLevel.STAFF_PRINCIPAL.value
    if any(k in t_lower for k in ("senior", "sr.", "sr ", "experienced")):
        return ExperienceLevel.SENIOR.value

    # Check years of experience in requirements text
    years_match = re.search(r"(\d+)\+?\s*years?(?:\s+of)?\s+experience", text, re.IGNORECASE)
    if years_match:
        years = int(years_match.group(1))
        if years >= 7:
            return ExperienceLevel.STAFF_PRINCIPAL.value
        elif years >= 5:
            return ExperienceLevel.SENIOR.value
        elif years >= 2:
            return ExperienceLevel.MID.value
        elif years <= 1:
            return ExperienceLevel.ENTRY.value

    return ExperienceLevel.MID.value


def extract_remote_status(location_str: str, text: str = "") -> str:
    """Extracts remote eligibility from location and text."""
    combined = f"{location_str} {text[:400]}".lower()

    if "remote" in combined or "anywhere" in combined or "work from home" in combined:
        if "hybrid" in combined:
            return RemoteStatus.HYBRID.value
        return RemoteStatus.REMOTE.value
    elif "hybrid" in combined:
        return RemoteStatus.HYBRID.value
    elif any(k in combined for k in ("onsite", "on-site", "office")):
        return RemoteStatus.ONSITE.value

    return RemoteStatus.UNSPECIFIED.value
