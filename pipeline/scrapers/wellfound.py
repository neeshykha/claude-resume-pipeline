"""
Wellfound (AngelList) scraper.
Uses Wellfound's public job search pages.
"""
from pipeline.scrapers.base import BaseScraper
from pipeline.models import Job
from pipeline import config


class WellfoundScraper(BaseScraper):
    name = "wellfound"

    # Wellfound role type slugs that map to our target titles
    ROLE_SLUGS = {
        "Technical Account Manager": "technical-account-manager",
        "Support Account Manager": "account-manager",
        "Customer Success Manager": "customer-success-manager",
        "Product Manager": "product-manager",
        "Associate Product Manager": "product-manager",
        "Technical Support Manager": "technical-support",
        "Technical Program Manager": "program-manager",
    }

    LOCATION_SLUGS = {
        "Remote": "remote",
        "Atlanta, GA": "atlanta",
        "New York, NY": "new-york",
        "New Jersey": "new-jersey",
    }

    def get_search_urls(self) -> list[str]:
        """Build Wellfound search URLs."""
        urls = []
        for title, role_slug in self.ROLE_SLUGS.items():
            for loc_name, loc_slug in self.LOCATION_SLUGS.items():
                url = f"https://wellfound.com/jobs?role={role_slug}&location={loc_slug}"
                urls.append(url)
        return list(set(urls))  # dedupe

    def get_search_queries_for_web(self) -> list[dict]:
        """Return structured queries for WebSearch."""
        queries = []
        for title in config.TARGET_TITLES:
            for location in config.LOCATIONS:
                queries.append({
                    "query": f"site:wellfound.com {title} {location}",
                    "source": self.name,
                    "title_filter": title,
                    "location_filter": location,
                })
        return queries

    def scrape(self) -> list[Job]:
        return self.get_search_urls()  # type: ignore
