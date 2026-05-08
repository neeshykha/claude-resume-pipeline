"""
Google Jobs scraper via SerpAPI (if key available) or direct Google search scraping.
Falls back to structured Google search URLs for manual/web-fetch parsing.
"""
import json
import os
import re
from pipeline.scrapers.base import BaseScraper
from pipeline.models import Job
from pipeline import config


class GoogleJobsScraper(BaseScraper):
    name = "google_jobs"

    def __init__(self, web_fetch_fn=None):
        """
        web_fetch_fn: async callable that fetches a URL and returns text content.
        In the Claude Code context, this will be wired to the WebFetch MCP tool.
        """
        self.web_fetch = web_fetch_fn

    def build_search_urls(self) -> list[str]:
        """Build Google Jobs search URLs for each title+location combo."""
        urls = []
        for query in self.build_search_queries():
            title = self.url_encode(query["title"])
            location = self.url_encode(query["location"])
            # Google Jobs search URL — returns job listings
            url = (
                f"https://www.google.com/search?q={title}+jobs+{location}"
                f"&ibp=htl;jobs&chips=date_posted:today"
            )
            urls.append(url)
        return urls

    def build_serpapi_urls(self) -> list[str]:
        """Build SerpAPI Google Jobs URLs if API key is available."""
        api_key = os.environ.get("SERPAPI_KEY")
        if not api_key:
            return []
        urls = []
        for query in self.build_search_queries():
            title = self.url_encode(query["title"])
            location = self.url_encode(query["location"])
            url = (
                f"https://serpapi.com/search.json?engine=google_jobs"
                f"&q={title}&location={location}"
                f"&chips=date_posted:today"
                f"&api_key={api_key}"
            )
            urls.append(url)
        return urls

    def parse_serpapi_response(self, text: str) -> list[Job]:
        """Parse SerpAPI JSON response into Job objects."""
        jobs = []
        try:
            data = json.loads(text)
            for item in data.get("jobs_results", []):
                salary_min = None
                salary_max = None
                if "detected_extensions" in item:
                    ext = item["detected_extensions"]
                    salary_min = ext.get("salary_min")
                    salary_max = ext.get("salary_max")

                jobs.append(Job(
                    title=item.get("title", ""),
                    company=item.get("company_name", ""),
                    location=item.get("location", ""),
                    url=item.get("apply_link", item.get("link", "")),
                    source=self.name,
                    description=item.get("description", ""),
                    salary_min=salary_min,
                    salary_max=salary_max,
                    date_posted=item.get("detected_extensions", {}).get("posted_at"),
                ))
        except (json.JSONDecodeError, KeyError):
            pass
        return jobs

    def scrape(self) -> list[Job]:
        """
        Returns search URLs and parsing instructions.
        Actual fetching is done by the orchestrator via WebFetch.
        """
        # Return the URLs to be fetched by the orchestrator
        serpapi_urls = self.build_serpapi_urls()
        if serpapi_urls:
            return serpapi_urls  # type: ignore — orchestrator handles this
        return self.build_search_urls()  # type: ignore

    def get_search_queries_for_web(self) -> list[dict]:
        """Return structured queries the orchestrator can use with WebSearch."""
        queries = []
        for q in self.build_search_queries():
            queries.append({
                "query": f"{q['title']} jobs {q['location']} posted today",
                "source": self.name,
                "title_filter": q["title"],
                "location_filter": q["location"],
            })
        return queries
