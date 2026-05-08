"""
Otta scraper.
Uses Otta's public job search at https://otta.com/jobs
"""
from pipeline.scrapers.base import BaseScraper
from pipeline.models import Job
from pipeline import config


class OttaScraper(BaseScraper):
    name = "otta"

    def get_search_urls(self) -> list[str]:
        """Build Otta search URLs."""
        urls = []
        for title in config.TARGET_TITLES:
            query = self.url_encode(title)
            url = f"https://otta.com/jobs?query={query}"
            urls.append(url)
        return list(set(urls))

    def get_search_queries_for_web(self) -> list[dict]:
        """Return structured queries for WebSearch."""
        queries = []
        for title in config.TARGET_TITLES:
            for location in config.LOCATIONS:
                queries.append({
                    "query": f"site:otta.com {title} {location}",
                    "source": self.name,
                    "title_filter": title,
                    "location_filter": location,
                })
        return queries

    def scrape(self) -> list[Job]:
        return self.get_search_urls()  # type: ignore
