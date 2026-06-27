"""
Configuration module — loads environment variables and defines constants.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Adzuna API ────────────────────────────────────────────────────────────────
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")
ADZUNA_BASE_URL = "https://api.adzuna.com/v1/api/jobs"

# ── arbeitnow API ─────────────────────────────────────────────────────────────
ARBEITNOW_BASE_URL = "https://www.arbeitnow.com/api/job-board-api"

# ── Huawei MaaS (OpenAI-compatible) ──────────────────────────────────────────
HUAWEI_MAAS_BASE_URL = os.getenv("HUAWEI_MAAS_BASE_URL", "")
HUAWEI_MAAS_API_KEY = os.getenv("HUAWEI_MAAS_API_KEY", "")
HUAWEI_MAAS_MODEL = os.getenv("HUAWEI_MAAS_MODEL", "glm-4")

# ── LLM Scoring ──────────────────────────────────────────────────────────────
LLM_TIMEOUT_SECONDS = 60
LLM_MAX_RETRIES = 2
MAX_JOBS_TO_SCORE_PER_RUN = 50  # Limit to avoid very long scoring runs

# ── Job Role Keywords ────────────────────────────────────────────────────────
ROLE_KEYWORDS = [
    "cloud presales",
    "solutions engineer",
    "cloud architect",
    "technical account manager",
    "presales engineer",
    "cloud engineer",
    "devops engineer",
    "pre-sales",
]

# ── Visa / Relocation Keywords ───────────────────────────────────────────────
VISA_KEYWORDS = [
    "visa sponsorship",
    "visa support",
    "relocation",
    "work permit",
    "relocation assistance",
    "visa required",
    "sponsorship available",
]

# ── English Language Keywords ────────────────────────────────────────────────
ENGLISH_KEYWORDS = [
    "english",
    "englisch",
    "anglais",
    "working language: english",
    "business english",
    "fluent in english",
]

# ── Salary Thresholds (visa minimum by country) ──────────────────────────────
SALARY_THRESHOLDS = {
    "Germany": 45000,   # €45,000 — Blue Card minimum for IT shortage occupations
    "France": 43000,    # €43,000
    "Canada": 55000,    # CAD 55,000
    "Ireland": 32000,   # €32,000
}

# Currency labels per country (for display)
SALARY_CURRENCY = {
    "Germany": "€",
    "France": "€",
    "Canada": "CAD",
    "Ireland": "€",
}

# ── Country → Adzuna country code ────────────────────────────────────────────
ADZUNA_COUNTRIES = {
    "Germany": "de",
    "Canada": "ca",
    "France": "fr",
    "Ireland": "gb",  # Adzuna uses 'gb' for UK+Ireland; we filter by location
}

# ── Scraper Rate Limiting ────────────────────────────────────────────────────
RATE_LIMIT_MIN_SECONDS = 2.0
RATE_LIMIT_MAX_SECONDS = 4.0

# ── Scheduling ───────────────────────────────────────────────────────────────
SCHEDULE_INTERVAL_HOURS = 6

# ── Notification Limits ──────────────────────────────────────────────────────
MAX_JOBS_PER_DIGEST = 15
MIN_SCORE_FOR_NOTIFICATION = 6

# ── Database ─────────────────────────────────────────────────────────────────
DB_PATH = Path(__file__).resolve().parent / "jobs.db"

# ── Candidate Profile ────────────────────────────────────────────────────────
CANDIDATE_PROFILE_PATH = Path(__file__).resolve().parent / "candidate_profile.md"
