"""
LLM-based job scoring via Huawei MaaS (OpenAI-compatible API).
"""

import json
import logging
from typing import Any

from openai import OpenAI

from config import (
    HUAWEI_MAAS_BASE_URL,
    HUAWEI_MAAS_API_KEY,
    HUAWEI_MAAS_MODEL,
    LLM_TIMEOUT_SECONDS,
    LLM_MAX_RETRIES,
    CANDIDATE_PROFILE_PATH,
)

logger = logging.getLogger(__name__)

# ── Candidate profile (loaded once at module import) ──────────────────────────
_candidate_profile: str = ""


def load_candidate_profile() -> str:
    """Load the candidate profile from Markdown file."""
    global _candidate_profile
    try:
        _candidate_profile = CANDIDATE_PROFILE_PATH.read_text(encoding="utf-8").strip()
        logger.info("Candidate profile loaded from %s (%d chars)", CANDIDATE_PROFILE_PATH, len(_candidate_profile))
    except FileNotFoundError:
        logger.warning("Candidate profile not found at %s — using fallback", CANDIDATE_PROFILE_PATH)
        _candidate_profile = _fallback_profile()
    except Exception as exc:
        logger.warning("Failed to read candidate profile: %s — using fallback", exc)
        _candidate_profile = _fallback_profile()
    return _candidate_profile


def _fallback_profile() -> str:
    """Fallback profile if the file is missing."""
    return (
        "## Experience\n"
        "3 years as Cloud Presales Engineer at Huawei\n\n"
        "## Technical Skills\n"
        "HCS private cloud, GaussDB, Kubernetes, solution architecture, "
        "client presentations, RFP responses\n\n"
        "## Languages\n"
        "French, English, Arabic\n\n"
        "## Target Roles\n"
        "Presales, Solutions Engineering, Cloud Architecture, Technical Account Management\n\n"
        "## Preferences\n"
        "Visa sponsorship required: yes (non-EU, non-Canadian citizen)\n"
    )


def get_candidate_profile() -> str:
    """Return the loaded candidate profile string."""
    return _candidate_profile


# ── OpenAI client (Huawei MaaS) ──────────────────────────────────────────────

_client: OpenAI | None = None


def _normalize_base_url(url: str) -> str:
    """
    Normalize the base URL for the OpenAI SDK.
    The SDK automatically appends /chat/completions, so if the user
    included it in the base URL we strip it to avoid doubling the path.
    Correct format per Huawei MaaS docs: https://<host>/openai/v1
    """
    if url.endswith("/chat/completions"):
        url = url[: -len("/chat/completions")]
        logger.info(
            "Stripped '/chat/completions' from base URL — SDK appends it automatically"
        )
    return url


def _get_client() -> OpenAI:
    """Get or create the OpenAI client pointed at Huawei MaaS."""
    global _client
    if _client is None:
        base_url = _normalize_base_url(HUAWEI_MAAS_BASE_URL)
        logger.info("LLM base URL: %s", base_url)
        _client = OpenAI(
            base_url=base_url,
            api_key=HUAWEI_MAAS_API_KEY,
            timeout=LLM_TIMEOUT_SECONDS,
            max_retries=LLM_MAX_RETRIES,
        )
    return _client


def build_scoring_prompt(title: str, company: str, location: str, description: str) -> str:
    """Build the LLM scoring prompt for a single job (concise for faster LLM response)."""
    profile = get_candidate_profile()
    # Truncate profile to first 800 chars and description to 300 for speed
    profile_short = profile[:800] if len(profile) > 800 else profile
    truncated_desc = (description or "")[:300]

    return (
        f"Score this job for the candidate below. Respond ONLY with JSON: "
        f'{{"score":1-10,"reason":"one sentence","visa_likely":true/false}}\n\n'
        f"Candidate:\n{profile_short}\n\n"
        f"Job: {title} at {company}, {location}\n"
        f"Desc: {truncated_desc}"
    )


def score_job(job: dict[str, Any]) -> dict[str, Any]:
    """
    Score a single job using the LLM.

    Returns dict with keys: score, reason, visa_likely
    On any failure, returns score=0, reason="scoring failed", visa_likely=False
    """
    title = job.get("title", "")
    company = job.get("company", "")
    location = job.get("location", "")
    description = job.get("description", "")

    prompt = build_scoring_prompt(title, company, location, description)

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=HUAWEI_MAAS_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a job relevance scoring assistant. Always respond with valid JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=200,
        )

        raw_text = response.choices[0].message.content.strip()

        # Strip markdown code fences if present
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            raw_text = "\n".join(lines).strip()

        result = json.loads(raw_text)

        score = int(result.get("score", 0))
        score = max(1, min(10, score))  # Clamp to 1-10

        reason = str(result.get("reason", ""))[:200]
        visa_likely = bool(result.get("visa_likely", False))

        logger.debug("Scored '%s' → %d/10 (visa=%s)", title, score, visa_likely)
        return {"score": score, "reason": reason, "visa_likely": visa_likely}

    except json.JSONDecodeError as exc:
        logger.warning("LLM returned invalid JSON for '%s': %s", title, exc)
        return {"score": 0, "reason": "scoring failed (invalid JSON)", "visa_likely": False}
    except Exception as exc:
        logger.warning("LLM scoring failed for '%s': %s", title, exc)
        return {"score": 0, "reason": "scoring failed", "visa_likely": False}


def score_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Score a list of jobs. Updates each job dict in-place with
    score, reason, and visa_likely.
    """
    if not jobs:
        return jobs

    logger.info("Scoring %d job(s) with LLM…", len(jobs))

    for i, job in enumerate(jobs):
        result = score_job(job)
        job["score"] = result["score"]
        job["reason"] = result["reason"]
        job["visa_likely"] = result["visa_likely"]

        # Small delay between LLM calls to avoid rate limits
        if i < len(jobs) - 1:
            import time
            time.sleep(0.5)

    scored = sum(1 for j in jobs if j.get("score", 0) > 0)
    logger.info("Scored %d/%d jobs successfully", scored, len(jobs))
    return jobs
