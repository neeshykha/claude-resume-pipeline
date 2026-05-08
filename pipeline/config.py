"""
Pipeline configuration — all search parameters and settings.
"""

# Job titles to search for (order = priority)
TARGET_TITLES = [
    "Technical Account Manager",
    "Support Account Manager",
    "Customer Success Manager",
    "Product Manager",
    "Associate Product Manager",
    "Technical Support Manager",
    "Technical Program Manager",
    "AI Enablement Manager",
    "AI Implementation Manager",
    "AI Operations Manager",
    "AI Self-Service Manager",
    "Customer Enablement Manager",
    "Technical Enablement Manager",
    "Support Enablement Manager",
    "Revenue Enablement Manager",
    "GTM Enablement Manager",
]

# Locations (including remote)
LOCATIONS = [
    "Remote",
    "Atlanta, GA",
    "New York, NY",
    "New Jersey",
]

# Salary floor
MIN_SALARY = 100_000

# Company size preferences (employee count ranges)
COMPANY_SIZE = {
    "min": 1,
    "max": 5000,
}

# Industries to exclude
EXCLUDED_INDUSTRIES = [
    "crypto",
    "web3",
    "blockchain",
    "defi",
    "nft",
]

# Industries to boost in scoring (+15%)
BOOSTED_INDUSTRIES = [
    "iot",
    "hardware",
    "smart home",
    "connected devices",
]

# AI/ML companies get a larger boost (+20%)
AI_BOOSTED_INDUSTRIES = [
    "ai", "artificial intelligence", "machine learning", "llm",
    "agentic", "genai", "generative ai", "large language model",
]

# Atlanta location boost values
ATLANTA_STARTUP_BOOST = 0.20   # small company / startup
ATLANTA_ENTERPRISE_BOOST = 0.10  # large / enterprise company

# Watchlist — always surface a role from these companies if one opens
WATCHLIST_COMPANIES = [
    "fullstory",  # Atlanta, digital experience analytics, AI-powered — no CSM/TAM open as of 2026-04-14
]

# Number of jobs to surface per day
DAILY_TARGET = 4

# Sources to scrape
SOURCES = [
    "google_jobs",
    "wellfound",
    "yc_jobs",
    "otta",
    "builtin",
    "hypepotamus",
    "80000hours",
    "hn_whos_hiring",
    "startup_jobs",
    "techstars",
    "indeed",
    "linkedin",
]

# Paths
import os
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER_RESUME = os.path.join(PROJECT_ROOT, "master_resume.md")
TAILORED_DIR = os.path.join(PROJECT_ROOT, "tailored")
PIPELINE_DIR = os.path.join(PROJECT_ROOT, "pipeline")
JOBS_OUTPUT_DIR = os.path.join(PIPELINE_DIR, "jobs")
LOG_DIR = os.path.join(PIPELINE_DIR, "logs")

# Email
DIGEST_RECIPIENT = "your.email@example.com"  # Replace with your email address

# Schedule
SCHEDULE_TIME = "07:00"  # ET
SCHEDULE_TIMEZONE = "America/New_York"
