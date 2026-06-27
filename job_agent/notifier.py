"""
Telegram notification module — sends job digest messages.
"""

import logging
from typing import Any

import httpx

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    MAX_JOBS_PER_DIGEST,
    MIN_SCORE_FOR_NOTIFICATION,
    SALARY_CURRENCY,
)
from storage import get_unnotified_jobs, mark_notified

logger = logging.getLogger(__name__)

# ── Country flag emojis ───────────────────────────────────────────────────────
COUNTRY_FLAGS = {
    "Germany": "🇩🇪",
    "Canada": "🇨🇦",
    "France": "🇫🇷",
    "Ireland": "🇮🇪",
}


def _format_job(job: dict[str, Any]) -> str:
    """Format a single job for the Telegram digest."""
    country = job.get("country", "Unknown")
    flag = COUNTRY_FLAGS.get(country, "🌍")
    score = job.get("score", 0)
    title = job.get("title", "Unknown Title")
    company = job.get("company", "Unknown Company")
    location = job.get("location", "Unknown Location")
    salary = job.get("salary", "not specified")
    visa_likely = job.get("visa_likely", False)
    reason = job.get("reason", "")
    url = job.get("url", "")

    visa_icon = "✅" if visa_likely else "❓"
    salary_display = salary if salary != "not specified" else "Not specified"

    lines = [
        f"{flag} {country.upper()} | Score: {score}/10",
        "",
        f"💼 {title} — {company}",
        f"📍 {location}",
        f"💰 {salary_display}",
        f"🛂 Visa: Likely {visa_icon}",
    ]

    if reason:
        lines.append(f"📝 {reason}")

    lines.append(f"🔗 {url}")

    return "\n".join(lines)


def _group_by_country(jobs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group jobs by country."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for job in jobs:
        country = job.get("country", "Other")
        groups.setdefault(country, []).append(job)
    return groups


async def send_telegram_message(text: str) -> bool:
    """Send a message via the Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials not configured — skipping notification")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    # Telegram message limit is 4096 chars
    if len(text) > 4096:
        text = text[:4090] + "\n…"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            resp.raise_for_status()
            logger.debug("Telegram message sent (status=%d)", resp.status_code)
            return True
    except Exception as exc:
        logger.error("Failed to send Telegram message: %s", exc)
        return False


async def send_digest() -> int:
    """
    Send a digest of unnotified, high-scoring jobs via Telegram.
    Returns the number of jobs sent.
    """
    jobs = get_unnotified_jobs(min_score=MIN_SCORE_FOR_NOTIFICATION)

    if not jobs:
        logger.info("No new jobs to notify about")
        return 0

    # Limit to MAX_JOBS_PER_DIGEST
    to_send = jobs[:MAX_JOBS_PER_DIGEST]
    remaining = len(jobs) - MAX_JOBS_PER_DIGEST

    # Group by country
    grouped = _group_by_country(to_send)

    # Build digest message
    digest_parts: list[str] = []
    digest_parts.append("📋 <b>Job Digest — New Opportunities</b>\n")

    for country, country_jobs in grouped.items():
        flag = COUNTRY_FLAGS.get(country, "🌍")
        digest_parts.append(f"\n{'─' * 30}")
        digest_parts.append(f"{flag} <b>{country.upper()}</b> ({len(country_jobs)} jobs)\n")

        for job in country_jobs:
            digest_parts.append(_format_job(job))
            digest_parts.append("")  # blank line between jobs

    if remaining > 0:
        digest_parts.append(
            f"\n📦 {remaining} more jobs available, next digest in 6h"
        )

    digest_text = "\n".join(digest_parts)

    # Split into chunks if message is too long (Telegram limit: 4096 chars)
    chunks = _split_message(digest_text, max_len=4096)

    sent_count = 0
    for chunk in chunks:
        success = await send_telegram_message(chunk)
        if success:
            sent_count += 1

    # Mark sent jobs as notified
    sent_urls = [job["url"] for job in to_send]
    mark_notified(sent_urls)

    logger.info(
        "Digest sent: %d jobs in %d message(s), %d remaining",
        len(to_send), sent_count, remaining,
    )
    return len(to_send)


def _split_message(text: str, max_len: int = 4096) -> list[str]:
    """Split a long message into chunks that fit within Telegram's character limit."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break

        # Find a natural break point (double newline) near the limit
        split_at = text.rfind("\n\n", 0, max_len)
        if split_at == -1:
            split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks
