"""
Pipeline Orchestrator
====================

This is the main entry point for the daily job pipeline.
It is designed to be invoked by a Claude Code scheduled task.

The orchestrator coordinates:
1. Scraping — collect jobs from all sources via WebSearch
2. Scoring — rank jobs against master resume
3. Tailoring — generate custom resume + cover letter for top picks
4. Delivery — email digest via Gmail

IMPORTANT: This orchestrator is meant to be run BY Claude Code (not as a
standalone Python script), because it relies on Claude's tools (WebSearch,
WebFetch, Gmail MCP) for scraping and delivery. The scheduled task prompt
calls Claude, which then executes this pipeline step by step.
"""

# This file serves as documentation and helper utilities for the
# Claude Code scheduled task. The actual orchestration happens in the
# scheduled task prompt, which uses Claude's tools directly.

import os
import json
from datetime import datetime, date
from pipeline import config
from pipeline.models import Job, save_jobs, load_jobs
from pipeline.scorer import rank_jobs, score_job
from pipeline.scrapers.google_jobs import GoogleJobsScraper
from pipeline.scrapers.wellfound import WellfoundScraper
from pipeline.scrapers.yc_jobs import YCJobsScraper
from pipeline.scrapers.otta import OttaScraper
from pipeline.scrapers.builtin import BuiltInScraper
from pipeline.scrapers.hypepotamus import HypepotamusScraper


ALL_SCRAPERS = [
    GoogleJobsScraper(),
    WellfoundScraper(),
    YCJobsScraper(),
    OttaScraper(),
    BuiltInScraper(),
    HypepotamusScraper(),
]


def get_all_search_queries() -> list[dict]:
    """
    Collect all search queries from all scrapers.
    Returns a list of dicts with 'query', 'source', 'title_filter', 'location_filter'.
    The Claude Code scheduled task uses these to call WebSearch for each.
    """
    all_queries = []
    for scraper in ALL_SCRAPERS:
        all_queries.extend(scraper.get_search_queries_for_web())
    return all_queries


def get_priority_queries(max_queries: int = 20) -> list[dict]:
    """
    Return a reduced set of high-priority queries to stay within rate limits.
    Prioritizes: Google (broadest), Wellfound, YC, then others.
    Deduplicates similar queries.
    """
    all_q = get_all_search_queries()

    # Prioritize by source
    source_priority = {
        "google_jobs": 0,
        "wellfound": 1,
        "yc_jobs": 2,
        "builtin": 3,
        "otta": 4,
        "hypepotamus": 5,
    }
    all_q.sort(key=lambda q: source_priority.get(q["source"], 99))

    # Deduplicate by normalized query text
    seen = set()
    unique = []
    for q in all_q:
        normalized = q["query"].lower().strip()
        if normalized not in seen:
            seen.add(normalized)
            unique.append(q)

    return unique[:max_queries]


def get_todays_job_file() -> str:
    """Path to today's scraped jobs JSON."""
    os.makedirs(config.JOBS_OUTPUT_DIR, exist_ok=True)
    return os.path.join(config.JOBS_OUTPUT_DIR, f"jobs_{date.today().isoformat()}.json")


def get_todays_log_file() -> str:
    """Path to today's pipeline log."""
    os.makedirs(config.LOG_DIR, exist_ok=True)
    return os.path.join(config.LOG_DIR, f"run_{date.today().isoformat()}.json")


def save_run_log(jobs_found: int, jobs_scored: int, jobs_tailored: int, top_jobs: list[Job]):
    """Save a log of today's pipeline run."""
    log = {
        "date": date.today().isoformat(),
        "timestamp": datetime.now().isoformat(),
        "jobs_found": jobs_found,
        "jobs_scored": jobs_scored,
        "jobs_tailored": jobs_tailored,
        "top_jobs": [
            {
                "title": j.title,
                "company": j.company,
                "score": j.fit_score,
                "url": j.url,
            }
            for j in top_jobs
        ],
    }
    path = get_todays_log_file()
    with open(path, "w") as f:
        json.dump(log, f, indent=2)
    return path


def check_already_seen(job: Job) -> bool:
    """
    Check if we've already surfaced this job in a previous run.
    Prevents showing the same job on consecutive days.
    """
    seen_file = os.path.join(config.JOBS_OUTPUT_DIR, "seen_urls.json")
    if not os.path.exists(seen_file):
        return False
    with open(seen_file) as f:
        seen = json.load(f)
    return job.url.rstrip("/").lower() in seen


def mark_as_seen(jobs: list[Job]):
    """Add jobs to the seen list."""
    seen_file = os.path.join(config.JOBS_OUTPUT_DIR, "seen_urls.json")
    seen = []
    if os.path.exists(seen_file):
        with open(seen_file) as f:
            seen = json.load(f)
    for job in jobs:
        url = job.url.rstrip("/").lower()
        if url not in seen:
            seen.append(url)
    # Keep last 500 to prevent unbounded growth
    seen = seen[-500:]
    os.makedirs(os.path.dirname(seen_file), exist_ok=True)
    with open(seen_file, "w") as f:
        json.dump(seen, f, indent=2)


def format_digest_email(top_jobs: list[Job]) -> dict:
    """
    Format the email digest content.
    Returns dict with 'subject' and 'body' (HTML).
    """
    today = date.today().strftime("%B %d, %Y")
    subject = f"Daily Job Matches — {today} ({len(top_jobs)} jobs)"

    rows = ""
    for i, job in enumerate(top_jobs, 1):
        salary_str = ""
        if job.salary_min:
            salary_str = f"${job.salary_min:,}"
            if job.salary_max:
                salary_str += f" – ${job.salary_max:,}"
        else:
            salary_str = "Not listed"

        reasons_html = "<br>".join(f"• {r}" for r in job.score_reasons)

        rows += f"""
        <tr style="border-bottom: 1px solid #eee;">
            <td style="padding: 12px;">
                <strong style="font-size: 16px;">{i}. {job.title}</strong><br>
                <span style="color: #0e7c6b; font-weight: bold;">{job.company}</span><br>
                <span style="color: #666;">{job.location} | {salary_str}</span><br>
                <span style="color: #666; font-size: 12px;">Source: {job.source}</span>
            </td>
            <td style="padding: 12px; vertical-align: top;">
                <span style="background: #0e7c6b; color: white; padding: 2px 8px; border-radius: 4px; font-weight: bold;">
                    {job.fit_score:.0%} match
                </span><br><br>
                <span style="font-size: 12px; color: #444;">{reasons_html}</span>
            </td>
            <td style="padding: 12px; vertical-align: top;">
                <a href="{job.url}" style="background: #0e7c6b; color: white; padding: 8px 16px; border-radius: 4px; text-decoration: none; display: inline-block;">
                    Apply →
                </a><br><br>
                <span style="font-size: 12px; color: #888;">
                    Resume: {'✅ Ready' if job.resume_path else '⏳ Pending'}<br>
                    Cover Letter: {'✅ Ready' if job.cover_letter_path else '⏳ Pending'}
                </span>
            </td>
        </tr>
        """

    body = f"""
    <html>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 800px; margin: 0 auto; padding: 20px;">
        <h1 style="color: #0e7c6b; border-bottom: 2px solid #0e7c6b; padding-bottom: 10px;">
            Daily Job Matches — {today}
        </h1>
        <p style="color: #444;">
            Found <strong>{len(top_jobs)}</strong> jobs matching your criteria.
            Tailored resumes and cover letters are attached.
        </p>
        <table style="width: 100%; border-collapse: collapse;">
            <thead>
                <tr style="background: #f5f5f5;">
                    <th style="padding: 8px; text-align: left;">Position</th>
                    <th style="padding: 8px; text-align: left;">Fit Score</th>
                    <th style="padding: 8px; text-align: left;">Action</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
        <hr style="margin-top: 30px; border-color: #eee;">
        <p style="color: #888; font-size: 12px;">
            Generated by your job pipeline. Resumes tailored from master_resume.md.
            All claims backed by actual experience — nothing fabricated.
        </p>
    </body>
    </html>
    """

    return {"subject": subject, "body": body}
