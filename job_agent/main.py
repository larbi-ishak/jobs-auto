"""
Job Agent — Main entry point with APScheduler.

Usage:
    python main.py          # Start scheduled runs every 6 hours
    python main.py --now    # Force an immediate run, then start scheduler
"""

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

# Ensure job_agent directory is on sys.path for imports
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import SCHEDULE_INTERVAL_HOURS, ROLE_KEYWORDS, VISA_KEYWORDS, SALARY_THRESHOLDS, MAX_JOBS_TO_SCORE_PER_RUN
from storage import init_db, insert_job, update_score, job_exists, get_stats
from scorer import load_candidate_profile, score_job
from notifier import send_digest

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(PROJECT_ROOT / "job_agent.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("job_agent")


# ── Visa / salary analysis ───────────────────────────────────────────────────

def _detect_visa_priority(job: dict) -> bool:
    """Check if job description mentions visa sponsorship / relocation."""
    text = f"{job.get('title', '')} {job.get('description', '')}".lower()
    return any(kw.lower() in text for kw in VISA_KEYWORDS)


def _check_salary_threshold(job: dict) -> str:
    """
    Check if salary is below the visa minimum for the country.
    Returns: 'low_priority', 'above_threshold', or 'not_specified'
    """
    salary = job.get("salary", "not specified")
    country = job.get("country", "")

    if salary == "not specified" or not salary:
        return "not_specified"

    threshold = SALARY_THRESHOLDS.get(country)
    if threshold is None:
        return "not_specified"

    numeric = _extract_salary_number(salary)
    if numeric is None:
        return "not_specified"

    if numeric < threshold:
        return "low_priority"
    return "above_threshold"


def _extract_salary_number(salary_str: str) -> Optional[float]:
    """Extract a numeric salary value from a formatted string."""
    import re
    cleaned = salary_str.replace("€", "").replace("CAD", "").replace("(est.)", "").strip()
    numbers = re.findall(r"[\d]+(?:[.,]\d{3})*(?![.,]\d)", cleaned)
    if not numbers:
        return None
    first = numbers[0].replace(",", "").replace(".", "")
    try:
        return float(first)
    except ValueError:
        return None


# ── Pipeline ──────────────────────────────────────────────────────────────────

async def run_scrapers() -> list[dict]:
    """Run all scrapers and return combined job listings."""
    all_jobs: list[dict] = []

    # --- arbeitnow (Germany) ---
    try:
        from scrapers.arbeitnow import ArbeitnowScraper
        scraper = ArbeitnowScraper()
        jobs = await scraper.run()
        all_jobs.extend(jobs)
        logger.info("Arbeitnow: %d jobs", len(jobs))
    except Exception as exc:
        logger.exception("Arbeitnow scraper crashed: %s", exc)

    # --- Adzuna (DE, CA, FR, IE) ---
    try:
        from scrapers.adzuna import AdzunaScraper
        scraper = AdzunaScraper()
        jobs = await scraper.run()
        all_jobs.extend(jobs)
        logger.info("Adzuna: %d jobs", len(jobs))
    except Exception as exc:
        logger.exception("Adzuna scraper crashed: %s", exc)

    return all_jobs


def filter_and_enrich(jobs: list[dict]) -> list[dict]:
    """
    Apply filtering rules and enrich jobs with metadata:
    - Visa priority flag
    - Salary threshold check
    """
    enriched = []
    for job in jobs:
        job["visa_priority"] = _detect_visa_priority(job)
        salary_status = _check_salary_threshold(job)
        job["salary_status"] = salary_status
        if salary_status == "low_priority":
            job["salary"] = f"{job.get('salary', '')} ⚠️ below visa min"
        enriched.append(job)
    return enriched


def store_jobs(jobs: list[dict]) -> list[dict]:
    """Store new jobs in SQLite (dedup by URL). Returns only newly inserted jobs."""
    new_jobs = []
    for job in jobs:
        url = job.get("url", "")
        if not url or job_exists(url):
            continue
        inserted = insert_job(
            url=url,
            title=job.get("title", ""),
            company=job.get("company", ""),
            location=job.get("location", ""),
            country=job.get("country", ""),
            salary=job.get("salary", "not specified"),
            source=job.get("source", "unknown"),
        )
        if inserted:
            new_jobs.append(job)
    logger.info("Stored %d new job(s) (deduped from %d)", len(new_jobs), len(jobs))
    return new_jobs


def score_and_update(jobs: list[dict]) -> None:
    """Score each new job with LLM and update the database."""
    if not jobs:
        return

    # Limit to avoid very long scoring runs
    if len(jobs) > MAX_JOBS_TO_SCORE_PER_RUN:
        logger.info(
            "Limiting scoring to %d/%d jobs (remaining will be scored next run)",
            MAX_JOBS_TO_SCORE_PER_RUN, len(jobs),
        )
        jobs = jobs[:MAX_JOBS_TO_SCORE_PER_RUN]

    logger.info("Scoring %d job(s)…", len(jobs))
    for i, job in enumerate(jobs):
        url = job.get("url", "")
        title = job.get("title", "")
        try:
            result = score_job(job)
            score = result["score"]
            reason = result["reason"]
            visa_likely = result["visa_likely"]
            if job.get("visa_priority"):
                visa_likely = True
            update_score(url, score, visa_likely, reason)
            logger.debug("Scored '%s' → %d/10", title, score)
        except Exception as exc:
            logger.warning("Failed to score '%s': %s", title, exc)
            update_score(url, 0, False, "scoring failed")
        if i < len(jobs) - 1:
            time.sleep(0.5)
    logger.info("Scoring complete")


async def run_pipeline() -> None:
    """Execute the full pipeline: scrape → filter → store → score → notify."""
    logger.info("=" * 60)
    logger.info("Pipeline run started")
    logger.info("=" * 60)

    # 1. Scrape all sources
    logger.info("Step 1/5: Scraping job sources…")
    raw_jobs = await run_scrapers()
    logger.info("Total raw jobs fetched: %d", len(raw_jobs))

    # 2. Filter and enrich
    logger.info("Step 2/5: Filtering and enriching…")
    enriched_jobs = filter_and_enrich(raw_jobs)
    logger.info("Jobs after filtering: %d", len(enriched_jobs))

    # 3. Store (dedup)
    logger.info("Step 3/5: Storing new jobs…")
    new_jobs = store_jobs(enriched_jobs)

    # 4. Score new jobs with LLM
    logger.info("Step 4/5: Scoring new jobs with LLM…")
    score_and_update(new_jobs)

    # 5. Send Telegram digest
    logger.info("Step 5/5: Sending Telegram digest…")
    notified = await send_digest()
    logger.info("Notified %d job(s)", notified)

    # Log stats
    stats = get_stats()
    logger.info(
        "Pipeline complete — DB stats: %d total, %d unnotified, %d scored",
        stats["total"], stats["unnotified"], stats["scored"],
    )


def scheduled_run() -> None:
    """Wrapper for the scheduler (runs async pipeline in a new event loop)."""
    asyncio.run(run_pipeline())


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Job Agent — automated job hunting")
    parser.add_argument(
        "--now", action="store_true",
        help="Run pipeline immediately, then start scheduler",
    )
    args = parser.parse_args()

    # Initialise
    logger.info("Job Agent starting up…")
    init_db()
    load_candidate_profile()

    if args.now:
        logger.info("--now flag: running pipeline immediately")
        scheduled_run()

    # Set up scheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        scheduled_run,
        "interval",
        hours=SCHEDULE_INTERVAL_HOURS,
        id="job_pipeline",
        name="Job scraping pipeline",
        misfire_grace_time=300,
    )
    scheduler.start()
    logger.info(
        "Scheduler started — pipeline runs every %d hour(s)",
        SCHEDULE_INTERVAL_HOURS,
    )

    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down…")
        scheduler.shutdown(wait=False)
        logger.info("Job Agent stopped")


if __name__ == "__main__":
    main()
