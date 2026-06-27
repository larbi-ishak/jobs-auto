"""
Adzuna scraper — multi-country job search via Adzuna API.
Supports: Germany (de), Canada (ca), France (fr), Ireland (via gb with location filter).
"""

import logging
import time
from typing import Any

import httpx

from scrapers.base import BaseScraper
from config import (
    ADZUNA_APP_ID,
    ADZUNA_APP_KEY,
    ADZUNA_BASE_URL,
    ADZUNA_COUNTRIES,
    ROLE_KEYWORDS,
)

logger = logging.getLogger(__name__)

# Maximum retries for transient connection errors
MAX_RETRIES = 4
RETRY_BACKOFF_BASE = 3  # seconds (3, 9, 27, 81)


class AdzunaScraper(BaseScraper):
    """Scrape Adzuna API for multiple countries."""

    name = "adzuna"

    # Countries that use 'gb' but should be filtered for Ireland locations
    IRELAND_LOCATION_KEYWORDS = ["ireland", "dublin", "cork", "galway", "limerick", "waterford"]

    def __init__(self, countries: dict[str, str] | None = None) -> None:
        """
        Args:
            countries: mapping of country name → Adzuna country code.
                       Defaults to ADZUNA_COUNTRIES from config.
        """
        super().__init__()
        self.countries = countries or ADZUNA_COUNTRIES

    async def fetch_jobs(self) -> list[dict[str, Any]]:
        """
        Search each role keyword in each country.
        Returns deduplicated (by URL) list of matching jobs.
        """
        all_jobs: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for country_name, country_code in self.countries.items():
            logger.info("[adzuna] Scraping country: %s (%s)", country_name, country_code)

            for keyword in ROLE_KEYWORDS:
                try:
                    jobs = await self._search(country_name, country_code, keyword)
                    for job in jobs:
                        job_url = job.get("url", "")
                        if job_url and job_url not in seen_urls:
                            seen_urls.add(job_url)
                            all_jobs.append(job)
                except Exception as exc:
                    logger.warning(
                        "[adzuna] Failed for %s / '%s': %s",
                        country_name, keyword, exc,
                    )

                await self.rate_limit()

        return all_jobs

    async def _search(
        self, country_name: str, country_code: str, keyword: str
    ) -> list[dict[str, Any]]:
        """Search Adzuna for a single keyword in a single country, with retry logic."""
        url = (
            f"{ADZUNA_BASE_URL}/{country_code}/search/1"
            f"?app_id={ADZUNA_APP_ID}"
            f"&app_key={ADZUNA_APP_KEY}"
            f"&what={keyword}"
            f"&results_per_page=50"
            f"&content-type=application/json"
        )

        # Add location filter for Ireland (searching within gb)
        if country_name == "Ireland":
            url += "&where=ireland&distance=50"

        data = await self._request_with_retry(url)

        results = data.get("results", [])
        mapped = []

        for result in results:
            job = self._map_job(result, country_name)
            if job:
                # For Ireland via gb: only keep jobs located in Ireland
                if country_name == "Ireland":
                    location_text = f"{job.get('location', '')} {result.get('title', '')}".lower()
                    if not any(kw in location_text for kw in self.IRELAND_LOCATION_KEYWORDS):
                        continue
                mapped.append(job)

        logger.debug(
            "[adzuna] %s / '%s' → %d results",
            country_name, keyword, len(mapped),
        )
        return mapped

    async def _request_with_retry(self, url: str) -> dict:
        """
        Make an HTTP GET request with exponential backoff retry
        for transient connection errors (WinError 10054, SSL timeouts, etc.).
        """
        for attempt in range(MAX_RETRIES):
            try:
                logger.debug("[adzuna] GET %s (attempt %d/%d)", url, attempt + 1, MAX_RETRIES)
                # Always create a fresh client to avoid stale connection pools
                self.client.close()
                self.client = httpx.Client(
                    timeout=httpx.Timeout(10.0, connect=15.0),
                    follow_redirects=True,
                    limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
                )
                response = self.client.get(url)
                response.raise_for_status()
                return response.json()
            except (httpx.ConnectError, httpx.ReadError, httpx.WriteError,
                    httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout,
                    httpx.PoolTimeout, ConnectionError, OSError) as exc:
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                    logger.warning(
                        "[adzuna] Connection error (attempt %d/%d): %s — retrying in %ds",
                        attempt + 1, MAX_RETRIES, exc, wait,
                    )
                    time.sleep(wait)
                else:
                    raise
            except httpx.HTTPStatusError as exc:
                # Don't retry 404s — they're permanent
                if exc.response.status_code == 404:
                    logger.warning("[adzuna] 404 for URL — country may not be supported: %s", url)
                    raise
                # Retry other HTTP errors (429, 5xx)
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                    logger.warning(
                        "[adzuna] HTTP %d (attempt %d/%d) — retrying in %ds",
                        exc.response.status_code, attempt + 1, MAX_RETRIES, wait,
                    )
                    time.sleep(wait)
                else:
                    raise
        return {}  # Should never reach here

    def _map_job(self, data: dict, country_name: str) -> dict[str, Any] | None:
        """Map an Adzuna result to our canonical format."""
        title = data.get("title", "")
        description = data.get("description", "")
        url = data.get("redirect_url", "")

        if not url or not title:
            return None

        # Keyword filtering — must match at least one role keyword
        text_to_search = f"{title} {description}".lower()
        if not any(kw.lower() in text_to_search for kw in ROLE_KEYWORDS):
            return None

        # Company
        company_data = data.get("company", {})
        company = company_data.get("display_name", "") if isinstance(company_data, dict) else str(company_data)

        # Location
        location_data = data.get("location", {})
        if isinstance(location_data, dict):
            area = location_data.get("area", [])
            location = ", ".join(area) if area else location_data.get("display_name", country_name)
        else:
            location = str(location_data) or country_name

        # Salary
        salary_min = data.get("salary_min")
        salary_max = data.get("salary_max")
        salary_is_predicted = data.get("salary_is_predicted", False)

        if salary_min and salary_max:
            currency = self._currency_for_country(country_name)
            salary = f"{currency}{salary_min:,.0f} – {currency}{salary_max:,.0f}"
            if salary_is_predicted:
                salary += " (est.)"
        elif salary_min:
            currency = self._currency_for_country(country_name)
            salary = f"{currency}{salary_min:,.0f}+"
        else:
            salary = "not specified"

        # Contract type
        contract_type = data.get("contract_time", "")
        created = data.get("created", "")

        return {
            "title": title,
            "company": company,
            "location": location,
            "url": url,
            "description": description,
            "salary": salary,
            "source": "adzuna",
            "country": country_name,
            "contract_type": contract_type,
            "created": created,
        }

    @staticmethod
    def _currency_for_country(country_name: str) -> str:
        """Return currency symbol for a country."""
        currencies = {
            "Germany": "€",
            "France": "€",
            "Ireland": "€",
            "Canada": "CAD",
        }
        return currencies.get(country_name, "€")

    def normalize_job(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Already normalized in _map_job."""
        return {
            "title": raw.get("title", ""),
            "company": raw.get("company", ""),
            "location": raw.get("location", ""),
            "url": raw.get("url", ""),
            "description": raw.get("description", ""),
            "salary": raw.get("salary", "not specified"),
            "source": raw.get("source", self.name),
            "country": raw.get("country", ""),
        }
