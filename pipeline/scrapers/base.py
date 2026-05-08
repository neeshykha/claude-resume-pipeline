"""
Base scraper class and utilities.
"""
import urllib.parse
from abc import ABC, abstractmethod
from pipeline.models import Job
from pipeline import config


class BaseScraper(ABC):
    """Base class for all job scrapers."""

    name: str = "base"

    def build_search_queries(self) -> list[dict]:
        """Build search query combinations from config."""
        queries = []
        for title in config.TARGET_TITLES:
            for location in config.LOCATIONS:
                queries.append({"title": title, "location": location})
        return queries

    @abstractmethod
    def scrape(self) -> list[Job]:
        """Scrape jobs from this source. Returns deduplicated list."""
        ...

    def deduplicate(self, jobs: list[Job]) -> list[Job]:
        """Remove duplicate jobs by URL."""
        seen = set()
        unique = []
        for job in jobs:
            key = job.url.rstrip("/").lower()
            if key not in seen:
                seen.add(key)
                unique.append(job)
        return unique

    def filter_excluded_industries(self, jobs: list[Job]) -> list[Job]:
        """Remove jobs from excluded industries based on description keywords."""
        filtered = []
        for job in jobs:
            text = (job.description + " " + job.title + " " + job.company).lower()
            if not any(exc in text for exc in config.EXCLUDED_INDUSTRIES):
                filtered.append(job)
        return filtered

    def url_encode(self, text: str) -> str:
        return urllib.parse.quote_plus(text)
