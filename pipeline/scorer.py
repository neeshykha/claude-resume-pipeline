"""
Job scoring and ranking engine.
Scores each job against the master resume to find the best daily matches.

This module provides keyword-based pre-scoring. The orchestrator may also
invoke Claude for semantic scoring of the top candidates.
"""
import re
from pipeline.models import Job
from pipeline import config


# Keywords extracted from master resume — grouped by category
RESUME_KEYWORDS = {
    "platforms": [
        "salesforce", "service cloud", "jira", "zendesk", "intercom",
        "omni-channel", "flows", "dashboards",
    ],
    "cloud_infra": [
        "aws", "iot core", "docker", "linux", "debian", "openwrt",
        "networking", "server",
    ],
    "ai_automation": [
        "claude", "ai", "automation", "maven agi", "google ai studio",
        "prompt engineering", "machine learning", "ai enablement",
        "ai implementation", "ai adoption", "ai-driven", "self-service",
        "deflection", "change management", "ai tools",
    ],
    "leadership": [
        "team lead", "manager", "distributed team", "hiring", "training",
        "coaching", "mentoring", "scaling", "bpo",
    ],
    "processes": [
        "cross-functional", "stakeholder", "vendor", "migration",
        "platform migration", "onboarding", "documentation", "sop",
        "knowledge base", "knowledge articles",
    ],
    "cx_skills": [
        "customer success", "customer experience", "account management",
        "technical account", "support operations", "escalation",
        "customer effort score", "ces", "nps", "csat",
    ],
    "product": [
        "product manager", "product management", "roadmap", "requirements",
        "user feedback", "firmware", "qa testing", "release",
    ],
    "iot_hardware": [
        "iot", "smart home", "hardware", "connected devices", "mesh",
        "wifi", "networking", "firmware", "sensor",
    ],
}

# Flatten for quick lookup
ALL_RESUME_KEYWORDS = set()
for group in RESUME_KEYWORDS.values():
    ALL_RESUME_KEYWORDS.update(group)


def score_title_match(job: Job) -> float:
    """Score based on how well the job title matches target titles."""
    title_lower = job.title.lower()
    scores = {
        "technical account manager": 1.0,
        "support account manager": 0.95,
        "technical support manager": 0.90,
        "support operations manager": 0.90,
        "technical operations manager": 0.88,
        "ai enablement manager": 0.90,
        "ai implementation manager": 0.90,
        "ai self-service manager": 0.90,
        "ai operations manager": 0.88,
        "head of ai operations": 0.88,
        "customer success manager": 0.85,
        "support enablement manager": 0.88,
        "technical enablement manager": 0.87,
        "customer enablement manager": 0.85,
        "revenue enablement manager": 0.82,
        "gtm enablement manager": 0.80,
        "technical program manager": 0.80,
        "product manager": 0.80,
        "associate product manager": 0.75,
    }
    best = 0.0
    for target, score in scores.items():
        if target in title_lower:
            best = max(best, score)
        # Partial match — at least 2 words overlap
        target_words = set(target.split())
        title_words = set(title_lower.split())
        overlap = len(target_words & title_words)
        if overlap >= 2:
            best = max(best, score * (overlap / len(target_words)))
    return best


def score_keyword_match(job: Job) -> tuple[float, list[str]]:
    """Score based on keyword overlap between JD and resume keywords."""
    text = (job.description + " " + job.title).lower()
    matched = []
    for keyword in ALL_RESUME_KEYWORDS:
        if keyword in text:
            matched.append(keyword)
    if not ALL_RESUME_KEYWORDS:
        return 0.0, matched
    return len(matched) / len(ALL_RESUME_KEYWORDS), matched


def score_location(job: Job) -> float:
    """Score based on location preference."""
    loc = job.location.lower()
    if "remote" in loc:
        return 1.0
    if "atlanta" in loc:
        return 1.0
    if "new york" in loc or "nyc" in loc or "new jersey" in loc or "nj" in loc:
        return 0.9
    # Unknown but might be acceptable
    return 0.3


def score_salary(job: Job) -> float:
    """Score based on salary if available."""
    if job.salary_min is not None:
        if job.salary_min >= config.MIN_SALARY:
            return 1.0
        elif job.salary_min >= config.MIN_SALARY * 0.9:
            return 0.7  # close enough to consider
        else:
            return 0.1  # below threshold
    # No salary listed — neutral
    return 0.5


def score_industry_boost(job: Job) -> float:
    """Bonus score for boosted industries (IoT/hardware +15%, AI/ML +20%)."""
    text = (job.description + " " + job.title + " " + job.company).lower()
    # AI/ML gets the larger boost — check first
    for term in config.AI_BOOSTED_INDUSTRIES:
        if term in text:
            return 0.20  # 20% bonus for AI/ML companies
    for term in config.BOOSTED_INDUSTRIES:
        if term in text:
            return 0.15  # 15% bonus for IoT/hardware
    return 0.0


# Signals that suggest a company is a startup or small company
_STARTUP_SIGNALS = [
    "series a", "series b", "series c", "seed", "startup",
    "wellfound", "workatastartup", "early-stage", "early stage",
    "small team", "founding team",
]

# Well-known enterprise/large companies — Atlanta roles get only the base +10%
_ENTERPRISE_COMPANIES = [
    "workday", "salesforce", "google", "microsoft", "amazon", "ibm",
    "oracle", "sap", "servicenow", "atlassian", "okta", "crowdstrike",
    "pagerduty", "zendesk", "box", "delta", "coca-cola", "home depot",
    "ups", "ncr", "equifax", "intercontinental exchange", "ice",
]


def score_atlanta_boost(job: Job) -> float:
    """
    Extra boost for Atlanta-based roles on top of location score.
    Startups/small companies: +20%. Enterprise/large: +10%. Uncertain: +15%.
    """
    loc = job.location.lower()
    if "atlanta" not in loc and "georgia" not in loc:
        return 0.0

    text = (job.description + " " + job.source).lower()
    company_lower = job.company.lower()

    # Known enterprise company → base boost
    for name in _ENTERPRISE_COMPANIES:
        if name in company_lower:
            return config.ATLANTA_ENTERPRISE_BOOST

    # Startup signals in description or source → full boost
    for signal in _STARTUP_SIGNALS:
        if signal in text or signal in company_lower:
            return config.ATLANTA_STARTUP_BOOST

    # Default: split the difference
    return 0.15


def score_job(job: Job) -> Job:
    """Calculate composite fit score for a job."""
    title_score = score_title_match(job)
    keyword_score, matched_keywords = score_keyword_match(job)
    location_score = score_location(job)
    salary_score = score_salary(job)
    industry_bonus = score_industry_boost(job)
    atlanta_bonus = score_atlanta_boost(job)

    # Weighted composite
    composite = (
        title_score * 0.30
        + keyword_score * 0.30
        + location_score * 0.20
        + salary_score * 0.10
        + 0.10  # base score for being a new posting
        + industry_bonus
        + atlanta_bonus
    )

    reasons = []
    if title_score >= 0.8:
        reasons.append(f"Strong title match ({title_score:.0%})")
    if matched_keywords:
        reasons.append(f"Keyword overlap: {', '.join(matched_keywords[:8])}")
    if location_score >= 0.9:
        reasons.append(f"Location match: {job.location}")
    if salary_score == 1.0 and job.salary_min:
        reasons.append(f"Salary meets threshold: ${job.salary_min:,}+")
    if industry_bonus == 0.20:
        reasons.append("AI/ML platform boost (+20%)")
    elif industry_bonus == 0.15:
        reasons.append("IoT/Hardware industry boost (+15%)")
    if atlanta_bonus == config.ATLANTA_STARTUP_BOOST:
        reasons.append("Atlanta startup boost (+20%)")
    elif atlanta_bonus == config.ATLANTA_ENTERPRISE_BOOST:
        reasons.append("Atlanta enterprise boost (+10%)")
    elif atlanta_bonus == 0.15:
        reasons.append("Atlanta company boost (+15%)")

    job.fit_score = round(composite, 3)
    job.score_reasons = reasons
    return job


def rank_jobs(jobs: list[Job], top_n: int = None) -> list[Job]:
    """Score and rank all jobs, return top N."""
    if top_n is None:
        top_n = config.DAILY_TARGET
    scored = [score_job(job) for job in jobs]
    scored.sort(key=lambda j: j.fit_score, reverse=True)
    return scored[:top_n]
