"""
Hypepotamus scraper — Atlanta-focused tech/startup jobs.
"""
from pipeline.scrapers.base import BaseScraper
from pipeline.models import Job
from pipeline import config


class HypepotamusScraper(BaseScraper):
    name = "hypepotamus"

    BASE_URL = "https://hypepotamus.com/jobs/"

    def get_search_urls(self) -> list[str]:
        """Hypepotamus jobs page — smaller board, single URL usually suffices."""
        return [self.BASE_URL]

    def get_search_queries_for_web(self) -> list[dict]:
        """Return structured queries for WebSearch."""
        queries = []
        for title in config.TARGET_TITLES:
            queries.append({
                "query": f"site:hypepotamus.com jobs {title} Atlanta",
                "source": self.name,
                "title_filter": title,
                "location_filter": "Atlanta, GA",
            })
        # Also a general query for their jobs page
        queries.append({
            "query": "hypepotamus.com/jobs account manager product manager Atlanta",
            "source": self.name,
            "title_filter": "general",
            "location_filter": "Atlanta, GA",
        })
        return queries

    def scrape(self) -> list[Job]:
        return self.get_search_urls()  # type: ignore
