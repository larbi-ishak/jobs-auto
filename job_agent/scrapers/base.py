"""
Base scraper class — provides httpx client, rate limiting, and error wrapping.
"""

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from typing import Any

import httpx

from config import RATE_LIMIT_MIN_SECONDS, RATE_LIMIT_MAX_SECONDS

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Abstract base class for all job scrapers."""

    name: str = "base"

    def __init__(self) -> None:
        self.client = httpx.Client(timeout=30.0, follow_redirects=True)

    async def rate_limit(self) -> None:
        """Sleep for a random interval between API calls."""
        delay = random.uniform(RATE_LIMIT_MIN_SECONDS, RATE_LIMIT_MAX_SECONDS)
        await asyncio.sleep(delay)

    @abstractmethod
    async def fetch_jobs(self) -> list[dict[str, Any]]:
        """
        Fetch raw job listings from the source API.
        Must return a list of dicts with at minimum:
            title, company, location, url, description, source, country
        """
        ...

    def normalize_job(self, raw: dict[str, Any]) -> dict[str, Any]:
        """
        Normalize a raw job dict into the canonical format.
        Subclasses should override if special mapping is needed.
        """
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

    async def run(self) -> list[dict[str, Any]]:
        """
        Public entry point: fetch + normalize, wrapped in try/except.
        Never crashes — returns empty list on failure.
        """
        try:
            logger.info("[%s] Starting scrape…", self.name)
            raw_jobs = await self.fetch_jobs()
            normalized = [self.normalize_job(j) for j in raw_jobs]
            logger.info("[%s] Fetched %d jobs", self.name, len(normalized))
            return normalized
        except Exception as exc:
            logger.exception("[%s] Scraper failed: %s", self.name, exc)
            return []
        finally:
            self.client.close()
