"""
Y Combinator Work at a Startup scraper.
Uses the public job board at https://www.workatastartup.com/jobs
"""
from pipeline.scrapers.base import BaseScraper
from pipeline.models import Job
from pipeline import config


class YCJobsScraper(BaseScraper):
    name = "yc_jobs"

    # YC Work at a Startup uses query params for filtering
    BASE_URL = "https://www.workatastartup.com/jobs"

    ROLE_MAP = {
        "Technical Account Manager": "technical-account-manager",
        "Support Account Manager": "account-manager",
        "Customer Success Manager": "customer-success",
        "Product Manager": "product",
        "Associate Product Manager": "product",
        "Technical Support Manager": "support",
        "Technical Program Manager": "program-manager",
    }

    def get_search_urls(self) -> list[str]:
        """Build YC job search URLs."""
        urls = []
        for title in config.TARGET_TITLES:
            query = self.url_encode(title)
            url = f"{self.BASE_URL}?query={query}&remote=true"
            urls.append(url)
        return list(set(urls))

    def get_search_queries_for_web(self) -> list[dict]:
        """Return structured queries for WebSearch."""
        queries = []
        for title in config.TARGET_TITLES:
            queries.append({
                "query": f"site:workatastartup.com {title}",
                "source": self.name,
                "title_filter": title,
                "location_filter": "Remote",
            })
        return queries

    def scrape(self) -> list[Job]:
        return self.get_search_urls()  # type: ignore
