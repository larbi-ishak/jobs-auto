"""
Arbeitnow scraper — Germany jobs with visa sponsorship filter.
Uses the free public API: GET https://www.arbeitnow.com/api/job-board-api?visa=true
"""

import logging
from typing import Any

import httpx

from scrapers.base import BaseScraper
from config import ARBEITNOW_BASE_URL, ROLE_KEYWORDS

logger = logging.getLogger(__name__)


class ArbeitnowScraper(BaseScraper):
    """Scrape arbeitnow.com for Germany jobs with visa sponsorship."""

    name = "arbeitnow"

    def __init__(self) -> None:
        super().__init__()
        self.base_url = ARBEITNOW_BASE_URL

    async def fetch_jobs(self) -> list[dict[str, Any]]:
        """
        Fetch jobs from arbeitnow API. Paginates through available pages.
        Only returns jobs that match at least one role keyword.
        """
        all_jobs: list[dict[str, Any]] = []
        page = 1

        while True:
            url = f"{self.base_url}?visa=true&page={page}"
            logger.debug("[arbeitnow] Fetching page %d: %s", page, url)

            try:
                resp = await self._fetch_page(url)
            except Exception as exc:
                logger.warning("[arbeitnow] Failed to fetch page %d: %s", page, exc)
                break

            data = resp.get("data", [])
            if not data:
                break

            for job_data in data:
                normalized = self._map_job(job_data)
                if normalized:
                    all_jobs.append(normalized)

            # Check if there are more pages
            meta = resp.get("meta", {})
            last_page = meta.get("last_page", 1)
            if page >= last_page:
                break

            page += 1
            await self.rate_limit()

        return all_jobs

    async def _fetch_page(self, url: str) -> dict:
        """Fetch a single page from the API."""
        response = self.client.get(url)
        response.raise_for_status()
        return response.json()

    def _map_job(self, data: dict) -> dict[str, Any] | None:
        """Map an arbeitnow job object to our canonical format."""
        title = data.get("title", "")
        description = data.get("description", "")
        slug = data.get("slug", "")
        url = data.get("url", "") or f"https://www.arbeitnow.com/jobs/{slug}"

        if not url or not title:
            return None

        # Keyword filtering — must match at least one role keyword
        text_to_search = f"{title} {description}".lower()
        if not any(kw.lower() in text_to_search for kw in ROLE_KEYWORDS):
            return None

        # Salary — arbeitnow may provide salary_range
        salary_raw = data.get("salary_range")
        if salary_raw and isinstance(salary_raw, dict):
            min_sal = salary_raw.get("min")
            max_sal = salary_raw.get("max")
            currency = salary_raw.get("currency", "€")
            if min_sal and max_sal:
                salary = f"{currency}{min_sal:,.0f} – {currency}{max_sal:,.0f}"
            elif min_sal:
                salary = f"{currency}{min_sal:,.0f}+"
            else:
                salary = "not specified"
        elif salary_raw and isinstance(salary_raw, str):
            salary = salary_raw
        else:
            salary = "not specified"

        # Location
        location_parts = []
        if data.get("city"):
            location_parts.append(data["city"])
        if data.get("state"):
            location_parts.append(data["state"])
        location = ", ".join(location_parts) if location_parts else data.get("location", "Germany")

        # Company
        company = data.get("company_name", "") or data.get("company", "")

        # Tags (for visa detection)
        tags = data.get("tags", [])

        return {
            "title": title,
            "company": company,
            "location": location,
            "url": url,
            "description": description,
            "salary": salary,
            "source": "arbeitnow",
            "country": "Germany",
            "tags": tags,
        }

    def normalize_job(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Already normalized in _map_job, just ensure required keys."""
        return {
            "title": raw.get("title", ""),
            "company": raw.get("company", ""),
            "location": raw.get("location", ""),
            "url": raw.get("url", ""),
            "description": raw.get("description", ""),
            "salary": raw.get("salary", "not specified"),
            "source": raw.get("source", self.name),
            "country": raw.get("country", "Germany"),
        }
