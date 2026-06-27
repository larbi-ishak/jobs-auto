"""
Scraper registry — centralized registry for all available scrapers.
Makes it easy to add new scrapers without modifying main.py.
"""

import logging
from typing import Any

from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# ── Registry ──────────────────────────────────────────────────────────────────

_registry: dict[str, type[BaseScraper]] = {}


def register(name: str, scraper_class: type[BaseScraper]) -> None:
    """Register a scraper class under a given name."""
    _registry[name] = scraper_class
    logger.debug("Registered scraper: %s", name)


def get_scraper(name: str) -> BaseScraper | None:
    """Instantiate and return a scraper by name, or None if not found."""
    cls = _registry.get(name)
    if cls is None:
        logger.warning("Scraper '%s' not found in registry", name)
        return None
    return cls()


def get_all_scrapers() -> list[BaseScraper]:
    """Instantiate and return all registered scrapers."""
    return [cls() for cls in _registry.values()]


def list_scrapers() -> list[str]:
    """Return names of all registered scrapers."""
    return list(_registry.keys())


# ── Auto-register built-in scrapers ──────────────────────────────────────────

def _auto_register() -> None:
    """Register all built-in scrapers."""
    try:
        from scrapers.arbeitnow import ArbeitnowScraper
        register("arbeitnow", ArbeitnowScraper)
    except ImportError:
        logger.debug("Arbeitnow scraper not available")

    try:
        from scrapers.adzuna import AdzunaScraper
        register("adzuna", AdzunaScraper)
    except ImportError:
        logger.debug("Adzuna scraper not available")


_auto_register()
