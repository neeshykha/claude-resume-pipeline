"""
BuiltIn scraper.
BuiltIn has regional sites (builtin.com, builtinnyc.com, etc.)
"""
from pipeline.scrapers.base import BaseScraper
from pipeline.models import Job
from pipeline import config


class BuiltInScraper(BaseScraper):
    name = "builtin"

    # BuiltIn regional domains
    REGIONAL_SITES = {
        "Atlanta, GA": "builtinga.com",
        "New York, NY": "builtinnyc.com",
        "New Jersey": "builtinnyc.com",  # NJ jobs often listed under NYC
        "Remote": "builtin.com",
    }

    def get_search_urls(self) -> list[str]:
        """Build BuiltIn search URLs."""
        urls = []
        for title in config.TARGET_TITLES:
            query = self.url_encode(title)
            for location, domain in self.REGIONAL_SITES.items():
                url = f"https://{domain}/jobs?search={query}"
                urls.append(url)
        return list(set(urls))

    def get_search_queries_for_web(self) -> list[dict]:
        """Return structured queries for WebSearch."""
        queries = []
        for title in config.TARGET_TITLES:
            for location, domain in self.REGIONAL_SITES.items():
                queries.append({
                    "query": f"site:{domain} {title}",
                    "source": self.name,
                    "title_filter": title,
                    "location_filter": location,
                })
        return queries

    def scrape(self) -> list[Job]:
        return self.get_search_urls()  # type: ignore
