#!/usr/bin/env python3
"""
ATS Board Poller — runs as a standalone Python script BEFORE Claude's pipeline.

Polls all watchlist companies' ATS endpoints (Greenhouse, Ashby, Lever),
filters by target titles, deduplicates against seen_jobs.json, applies
company cap and basic filters, and outputs a small JSON file that Claude
reads instead of fetching/processing raw API data in-context.

Usage:
    python pipeline/poll_ats.py [--date 2026-05-01]

Output:
    pipeline/jobs/ats_hits_YYYY-MM-DD.json  — matched + borderline jobs
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from urllib.parse import urljoin
import requests

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
WATCHLIST_PATH = os.path.join(SCRIPT_DIR, "watchlist_companies.json")
SEEN_JOBS_PATH = os.path.join(SCRIPT_DIR, "jobs", "seen_jobs.json")
JOBS_DIR = os.path.join(SCRIPT_DIR, "jobs")

# ── ATS Endpoints ────────────────────────────────────────────────────────────
ATS_ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "greenhouse_eu": "https://boards-api.eu.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true",
    # SmartRecruiters public postings API. slug = case-sensitive company identifier
    # (e.g. "BoschGroup", not "bosch"). Added 2026-06-30 to widen which small
    # companies are enrollable beyond Greenhouse/Ashby/Lever/Workday.
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100",
}

REQUEST_TIMEOUT = 30  # seconds
DEDUP_WINDOW_DAYS = 30
COMPANY_CAP = 3  # max pending applications (applied=true, outcome=null) per company before suppression
COMPANY_CAP_OVERRIDE_SCORE = 110  # bypass cap if estimated score exceeds this
MAX_PER_COMPANY_PER_RUN = 2  # diversity cap: max roles per company in the surfaced shortlist (prevents one company sweeping the run)
MIN_SALARY = 100_000

# ── Extended title filter ────────────────────────────────────────────────────
# Core titles from watchlist + additional titles Claude has historically matched.
# Kept broad on purpose — better to include borderline matches for Claude review
# than to miss good roles.
TITLE_KEYWORDS_EXACT = [
    "customer success manager",
    "technical account manager",
    "support account manager",
    "technical support manager",
    "technical operations manager",
    "support operations manager",
    "solutions engineer",
    "sales engineer",
    "customer engineer",
    "implementation consultant",
    "implementation manager",
    "professional services manager",
    "deployment strategist",
    "deployment manager",
    "ai engagement manager",
    "ai adoption",
    "ai enablement manager",
    "ai implementation manager",
    "ai operations manager",
    "ai optimization",
    "ai specialist",
    "ai solutions",
    "automation specialist",
    "customer enablement manager",
    "technical enablement manager",
    "product manager",
    "product csm",
    "technical csm",
    "forward deployed engineer",
    "solutions consultant",
    "customer solutions engineer",
    "digital customer experience",
    "customer experience lead",
    "technical program manager",
    # added 2026-06-30 — core role types at the sub-500 companies enrolled this run
    # (CodeRabbit/Replit/Baseten field eng; Parloa/Replicant/Ema engagement mgr; Replit/Mintlify support eng).
    # "field engineer" also substring-matches "field engineering" (incl. "Manager, Field Engineering").
    "field engineer",
    "engagement manager",
    "support engineer",
]

# Broader keyword fragments for borderline matching.
# If a title matches 2+ of these, it's flagged as borderline for Claude review.
TITLE_FRAGMENTS = [
    "customer success", "account manager", "technical account",
    "solutions", "implementation", "enablement", "deployment",
    "customer engineer", "support manager", "operations manager",
    "product manager", "forward deployed", "ai ", "csm",
    "customer experience", "professional services", "onboarding",
    "tam ", "se ", "adoption", "optimization", "automation", "specialist",
]

# Location filter — only keep US-relevant roles
LOCATION_INCLUDE = [
    "remote", "united states", "us", "usa", "u.s.",
    "atlanta", "georgia", "new york", "nyc", "new jersey",
    "boston", "chicago", "san francisco", "los angeles",
    "austin", "denver", "seattle", "portland", "dallas",
    "miami", "charlotte", "raleigh", "nashville",
    "north america", "americas", "anywhere",
]
LOCATION_EXCLUDE = [
    "emea", "apac", "latam", "anz", "india", "japan",
    "singapore", "australia", "europe", "germany", "france",
    "united kingdom", "uk", "london", "berlin", "paris",
    "canada", "toronto", "vancouver", "brazil", "mexico",
    "israel", "tel aviv", "china", "korea", "spain",
    "italy", "netherlands", "ireland", "dublin",
    "mandarin", "cantonese",  # language-specific roles
]

# Titles to always exclude (too senior, wrong function)
TITLE_EXCLUDE = [
    "vice president", "vp ", "vp,", "head of", "director",
    "staff engineer", "principal engineer", "senior staff",
    "chief ", "c-suite",
    # Language-specific roles (Aneesh speaks English/German/Hindi only)
    "mandarin", "cantonese", "spanish speaking", "french speaking",
    "portuguese speaking", "japanese speaking", "korean speaking",
    "thai speaking", "arabic speaking",
]

# Industry exclusions
EXCLUDED_TERMS = ["crypto", "web3", "blockchain", "defi", "nft"]


def slugify(text: str) -> str:
    """Convert text to dedup-key slug: lowercase, kebab-case (matching seen_jobs.json format)."""
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9\s-]', '', text)  # keep letters, digits, spaces, hyphens
    text = re.sub(r'[\s]+', '-', text)          # spaces → hyphens
    text = re.sub(r'-+', '-', text)             # collapse multiple hyphens
    return text.strip('-')


def make_dedup_key(ats_slug: str, title: str) -> str:
    """Create dedup key: ats_slug::title_slug.
    Uses the ATS slug directly (not the company name) to match existing seen_jobs.json format.
    """
    return f"{ats_slug.lower()}::{slugify(title)}"


def title_matches_exact(title: str) -> bool:
    """Check if title matches any of the exact target titles."""
    t = title.lower()
    for target in TITLE_KEYWORDS_EXACT:
        if target in t:
            return True
    return False


def title_matches_borderline(title: str) -> int:
    """Count how many title fragments match. ≥2 = borderline candidate."""
    t = title.lower()
    return sum(1 for frag in TITLE_FRAGMENTS if frag in t)


def title_excluded(title: str) -> bool:
    """Check if title should be excluded (too senior, wrong function)."""
    t = title.lower()
    return any(excl in t for excl in TITLE_EXCLUDE)


def location_relevant(location: str, title: str) -> bool:
    """Check if the job location is US-relevant. Also checks title for region indicators."""
    loc = location.lower()
    t = title.lower()
    combined = loc + " " + t

    # Explicit exclusion wins (e.g., "Customer Success Manager, EMEA")
    if any(excl in combined for excl in LOCATION_EXCLUDE):
        return False

    # If location contains any included term, it's relevant
    if any(incl in loc for incl in LOCATION_INCLUDE):
        return True

    # If location is vague/empty but title doesn't have region markers, keep it
    # (Claude can filter further)
    if not loc or loc in ("unknown", ""):
        return True

    # Default: exclude non-matching locations
    return False


def description_excluded(text: str) -> bool:
    """Check if description contains excluded industry terms."""
    t = text.lower()
    return any(term in t for term in EXCLUDED_TERMS)


def extract_salary_min(compensation) -> int | None:
    """Try to extract minimum salary from various ATS compensation formats."""
    if not compensation:
        return None
    if isinstance(compensation, dict):
        # Ashby format
        for key in ("min", "minimum", "minValue", "floor"):
            if key in compensation:
                try:
                    return int(compensation[key])
                except (ValueError, TypeError):
                    pass
        # Try nested
        for key in ("salary", "compensation", "range"):
            if key in compensation and isinstance(compensation[key], dict):
                return extract_salary_min(compensation[key])
    if isinstance(compensation, str):
        # Try to extract number from string like "$120,000" or "120000"
        nums = re.findall(r'[\$]?\s*([\d,]+)', compensation)
        if nums:
            try:
                return int(nums[0].replace(',', ''))
            except ValueError:
                pass
    return None


def parse_location(job_data: dict, ats: str) -> str:
    """Extract location string from ATS job data."""
    if ats in ("greenhouse", "greenhouse_eu"):
        loc = job_data.get("location", {})
        if isinstance(loc, dict):
            return loc.get("name", "Unknown")
        return str(loc) if loc else "Unknown"
    elif ats == "ashby":
        loc = job_data.get("location", "")
        if isinstance(loc, list):
            return ", ".join(loc) if loc else "Unknown"
        return str(loc) if loc else "Unknown"
    elif ats == "lever":
        cats = job_data.get("categories", {})
        return cats.get("location", "Unknown") if isinstance(cats, dict) else "Unknown"
    elif ats == "workday":
        return job_data.get("_workday_location") or "Unknown"
    elif ats == "smartrecruiters":
        loc = job_data.get("location", {}) or {}
        full = loc.get("fullLocation") or ", ".join(
            p for p in [loc.get("city"), (loc.get("country") or "").upper()] if p)
        if loc.get("remote"):
            full = f"Remote {full}".strip()
        return full or "Unknown"
    return "Unknown"


def build_apply_url(job_data: dict, ats: str, slug: str) -> str:
    """Build the apply URL for a job."""
    if ats in ("greenhouse", "greenhouse_eu"):
        jid = job_data.get("id", "")
        return f"https://job-boards.greenhouse.io/{slug}/jobs/{jid}"
    elif ats == "ashby":
        jid = job_data.get("id", "")
        return f"https://jobs.ashbyhq.com/{slug}/{jid}"
    elif ats == "lever":
        return job_data.get("hostedUrl", job_data.get("applyUrl", ""))
    elif ats == "workday":
        return job_data.get("_apply_url", "")
    elif ats == "smartrecruiters":
        jid = job_data.get("id", "")
        return f"https://jobs.smartrecruiters.com/{slug}/{jid}"
    return ""


def fetch_greenhouse(slug: str, eu: bool = False) -> list[dict]:
    """Fetch jobs from Greenhouse API."""
    endpoint = ATS_ENDPOINTS["greenhouse_eu" if eu else "greenhouse"]
    url = endpoint.format(slug=slug)
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data.get("jobs", [])
    except Exception as e:
        return [{"_error": f"{type(e).__name__}: {e}"}]


def fetch_ashby(slug: str) -> list[dict]:
    """Fetch jobs from Ashby API."""
    url = ATS_ENDPOINTS["ashby"].format(slug=slug)
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, stream=True)
        # Guard against huge responses (OpenAI)
        content_length = resp.headers.get("content-length")
        if content_length and int(content_length) > 5_000_000:
            return [{"_error": f"Response too large: {content_length} bytes"}]
        resp.raise_for_status()
        data = resp.json()
        return data.get("jobs", [])
    except Exception as e:
        return [{"_error": f"{type(e).__name__}: {e}"}]


def fetch_lever(slug: str) -> list[dict]:
    """Fetch jobs from Lever API."""
    url = ATS_ENDPOINTS["lever"].format(slug=slug)
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        return [{"_error": f"{type(e).__name__}: {e}"}]


def fetch_smartrecruiters(slug: str) -> list[dict]:
    """Fetch jobs from the SmartRecruiters public postings API.

    Returns the `content` array, normalizing each posting's title into a "title"
    key (SmartRecruiters uses "name") so the shared title-extraction path in
    poll_all works unchanged. Single page (limit=100) — enrolled SR companies are
    small; companies with >100 postings would need pagination (not needed yet).
    """
    url = ATS_ENDPOINTS["smartrecruiters"].format(slug=slug)
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"Accept": "application/json"})
        resp.raise_for_status()
        data = resp.json()
        postings = data.get("content", []) or []
        for p in postings:
            p["title"] = p.get("name", "")
        return postings
    except Exception as e:
        return [{"_error": f"{type(e).__name__}: {e}"}]


def fetch_workday(company: dict) -> list[dict]:
    """Fetch jobs from a Workday CXS board.

    Workday differs from the GET-based ATSs: the public careers page is
    JS-rendered, but its frontend calls an internal JSON API at
        POST https://{host}/wday/cxs/{tenant}/{site}/jobs
    which returns structured postings. The host (including the wdN datacenter),
    tenant, and site are NOT guessable, so they live on the watchlist entry as
    wd_host / wd_tenant / wd_site (verified once via /tmp/verify_workday.py).
    Paginates 20/page up to MAX_JOBS.

    Salary is NOT in the list response (it lives on each job's detail page), so
    it stays unset here and is treated as neutral in scoring. Claude fetches the
    exact salary and posting date from the JD at tailoring time, which is where
    the salary-floor and freshness gates are actually applied.

    Returns dicts carrying the fields poll_all expects, with the apply URL and
    location pre-stashed under _apply_url / _workday_location so the existing
    build_apply_url / parse_location helpers can read them.
    """
    host = company.get("wd_host")
    tenant = company.get("wd_tenant")
    site = company.get("wd_site")
    if not (host and tenant and site):
        return [{"_error": "Workday entry missing wd_host/wd_tenant/wd_site"}]

    url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (resume-pipeline)",
    }
    PAGE = 20
    MAX_JOBS = 200  # cap pagination; watchlist boards run well under this
    out = []
    offset = 0
    try:
        while offset < MAX_JOBS:
            body = {"appliedFacets": {}, "limit": PAGE, "offset": offset, "searchText": ""}
            resp = requests.post(url, json=body, headers=headers, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            postings = data.get("jobPostings", [])
            if not postings:
                break
            for p in postings:
                ext = p.get("externalPath", "")
                loc = p.get("locationsText", "") or ""
                # Workday shows "N Locations" for multi-site roles instead of a
                # city — we can't tell US vs intl from the list view, so pass
                # these through as Unknown (kept for Claude review) rather than
                # dropping potentially-US roles.
                if re.match(r'^\s*\d+\s+locations?\s*$', loc, re.I):
                    loc = "Unknown"
                out.append({
                    "title": p.get("title", ""),
                    "_apply_url": f"https://{host}/en-US/{site}{ext}",
                    "_workday_location": loc,
                    "_posted": p.get("postedOn", ""),
                    "id": ext,
                })
            total = data.get("total", 0)
            offset += PAGE
            if offset >= total:
                break
            time.sleep(0.2)
    except Exception as e:
        return [{"_error": f"{type(e).__name__}: {e}"}]
    return out


def load_seen_jobs() -> dict:
    """Load existing seen_jobs for dedup."""
    if not os.path.exists(SEEN_JOBS_PATH):
        return {}
    with open(SEEN_JOBS_PATH) as f:
        data = json.load(f)
    return data.get("jobs", {})


def count_unapplied_by_company(seen_jobs: dict) -> dict[str, int]:
    """Count pending APPLICATIONS per company for cap enforcement.

    Cap rule (canonical, per watchlist_companies.json _scoring_config): only
    entries that have been APPLIED to and have no outcome yet count toward the
    cap. Queued/unapplied roles do NOT count — surfacing a role we haven't
    applied to should never be blocked by other roles we also haven't applied
    to. (Function name kept for caller compatibility.)
    """
    counts = {}
    for entry in seen_jobs.values():
        if entry.get("applied", False) and entry.get("outcome") is None:
            company = slugify(entry.get("company", ""))
            counts[company] = counts.get(company, 0) + 1
    return counts


def is_within_dedup_window(seen_entry: dict, today: date) -> bool:
    """Check if a seen job is within the 30-day dedup window."""
    first_seen = seen_entry.get("first_seen_date")
    if not first_seen:
        return False
    try:
        seen_date = date.fromisoformat(first_seen)
        return (today - seen_date).days <= DEDUP_WINDOW_DAYS
    except (ValueError, TypeError):
        return False


def poll_all(run_date: date) -> dict:
    """
    Poll all watchlist companies, filter, dedup, and return results.

    Returns a dict with:
    - matched: list of jobs that pass title filter
    - borderline: list of jobs with partial title matches (for Claude review)
    - errors: list of ATS errors
    - stats: polling statistics
    """
    with open(WATCHLIST_PATH) as f:
        watchlist = json.load(f)

    companies = watchlist["companies"]
    seen_jobs = load_seen_jobs()
    unapplied_counts = count_unapplied_by_company(seen_jobs)

    matched = []
    borderline = []
    errors = []
    reseen = []  # existing jobs re-encountered (for last_seen_date update)
    stats = {
        "companies_polled": 0,
        "total_jobs_scanned": 0,
        "title_matched": 0,
        "title_borderline": 0,
        "dedup_skipped": 0,
        "cap_suppressed": 0,
        "location_filtered": 0,
        "excluded": 0,
        "errors": 0,
    }

    for company in companies:
        name = company["name"]
        ats = company["ats"]
        slug = company["slug"]
        priority = company.get("priority", "medium")

        # Fetch from ATS
        if ats in ("greenhouse", "greenhouse_eu"):
            jobs = fetch_greenhouse(slug, eu=(ats == "greenhouse_eu"))
        elif ats == "ashby":
            jobs = fetch_ashby(slug)
        elif ats == "lever":
            jobs = fetch_lever(slug)
        elif ats == "smartrecruiters":
            jobs = fetch_smartrecruiters(slug)
        elif ats == "workday":
            jobs = fetch_workday(company)
        else:
            errors.append({"company": name, "error": f"Unknown ATS: {ats}"})
            continue

        stats["companies_polled"] += 1

        # Check for API errors
        if jobs and isinstance(jobs[0], dict) and "_error" in jobs[0]:
            errors.append({
                "company": name,
                "ats": ats,
                "slug": slug,
                "error": jobs[0]["_error"],
            })
            stats["errors"] += 1
            continue

        stats["total_jobs_scanned"] += len(jobs)

        # Company cap check
        company_slug = slugify(name)
        unapplied = unapplied_counts.get(company_slug, 0)
        is_capped = unapplied >= COMPANY_CAP

        for job_data in jobs:
            title = job_data.get("title", job_data.get("text", ""))
            if not title:
                continue

            # Title exclusion
            if title_excluded(title):
                stats["excluded"] += 1
                continue

            # Check title match
            is_exact = title_matches_exact(title)
            borderline_count = title_matches_borderline(title)

            if not is_exact and borderline_count < 2:
                continue  # Not relevant at all

            location = parse_location(job_data, ats)

            # Location filter
            if not location_relevant(location, title):
                stats["excluded"] += 1
                continue

            apply_url = build_apply_url(job_data, ats, slug)
            dedup_key = make_dedup_key(slug, title)
            # Also check company-name-based key (handles slug ≠ name, e.g. pindropsecurity vs pindrop)
            name_slug = re.sub(r'[^a-z0-9-]', '', name.lower().replace(' ', ''))
            alt_dedup_key = f"{name_slug}::{slugify(title)}" if name_slug != slug.lower() else None

            # Compensation
            comp = job_data.get("compensation") or job_data.get("salary")
            salary_min = extract_salary_min(comp)

            # Salary filter
            if salary_min and salary_min < MIN_SALARY:
                stats["excluded"] += 1
                continue

            # Industry exclusion
            desc = job_data.get("content", job_data.get("description", ""))
            if isinstance(desc, str) and description_excluded(desc):
                stats["excluded"] += 1
                continue

            # Dedup check (try both slug-based and name-based keys)
            matched_key = None
            if dedup_key in seen_jobs:
                matched_key = dedup_key
            elif alt_dedup_key and alt_dedup_key in seen_jobs:
                matched_key = alt_dedup_key
            if matched_key and is_within_dedup_window(seen_jobs[matched_key], run_date):
                stats["dedup_skipped"] += 1
                reseen.append(matched_key)
                continue

            # Company cap check
            if is_capped:
                stats["cap_suppressed"] += 1
                continue

            # Build result entry
            entry = {
                "dedup_key": dedup_key,
                "company": name,
                "title": title,
                "location": location,
                "apply_url": apply_url,
                "ats": ats,
                "slug": slug,
                "priority": priority,
                "salary_min": salary_min,
                "match_type": "exact" if is_exact else "borderline",
                "borderline_score": borderline_count if not is_exact else None,
            }

            if is_exact:
                matched.append(entry)
                stats["title_matched"] += 1
            else:
                borderline.append(entry)
                stats["title_borderline"] += 1

        # Rate limit: small delay between companies to be polite
        time.sleep(0.3)

    # Pre-score and rank matched jobs
    for job in matched:
        score = 0
        t = job["title"].lower()

        # Title quality (exact target title vs substring)
        top_titles = ["technical account manager", "customer success manager",
                       "solutions engineer", "implementation consultant",
                       "implementation manager", "technical enablement manager",
                       "ai enablement manager", "ai implementation manager",
                       "forward deployed engineer", "deployment strategist"]
        if any(tt in t for tt in top_titles):
            score += 30
        else:
            score += 15

        # Seniority match (senior = ok, principal/staff = excluded already, manager II = ok)
        if "senior" in t or "sr " in t or "sr." in t:
            score += 5
        if "associate" in t or "junior" in t:
            score -= 5

        # Location
        loc = job["location"].lower()
        if "remote" in loc:
            score += 20
        elif "atlanta" in loc:
            score += 20
        elif "new york" in loc or "nyc" in loc:
            score += 12
        elif "boston" in loc:
            score += 5
        else:
            score += 3

        # Priority
        score += {"high": 15, "medium": 8, "low": 3}.get(job["priority"], 5)

        # Salary
        if job.get("salary_min") and job["salary_min"] >= 130_000:
            score += 10
        elif job.get("salary_min") and job["salary_min"] >= MIN_SALARY:
            score += 5

        # AI/voice boost — TITLE ONLY. Previously also matched the company name,
        # which auto-granted +10 to every role at an AI-named company (Cresta,
        # OpenAI, Arize…) regardless of the role's actual relevance. That rewarded
        # company identity over role fit and let one AI company sweep the shortlist.
        for kw in ["ai", "agentic", "voice", "llm", "machine learning"]:
            if kw in t:
                score += 10
                break
        # IoT boost — company-name match retained: Aneesh's IoT background is a
        # genuine domain differentiator and few watchlist companies are IoT-named.
        for kw in ["iot", "hardware", "smart home", "connected"]:
            if kw in t or kw in job.get("company", "").lower():
                score += 8
                break

        job["pre_score"] = score

    # Sort by pre-score, then apply a per-company DIVERSITY CAP before keeping
    # the top 25. Without this, a single company that posts many CS-adjacent
    # roles (and stacks company-level bonuses) fills the entire shortlist. We
    # surface at most MAX_PER_COMPANY_PER_RUN roles per company so Claude's
    # review set stays diverse; additional same-company roles are dropped from
    # the shortlist (still recorded in stats) and can be revisited next run.
    matched.sort(key=lambda j: -j["pre_score"])
    stats["total_matched_before_cap"] = len(matched)

    top_matched = []
    kept_per_company = {}
    diversity_dropped = 0
    for job in matched:
        co = slugify(job.get("company", ""))
        if kept_per_company.get(co, 0) < MAX_PER_COMPANY_PER_RUN:
            if len(top_matched) < 25:
                kept_per_company[co] = kept_per_company.get(co, 0) + 1
                top_matched.append(job)
        else:
            diversity_dropped += 1
    stats["diversity_dropped"] = diversity_dropped

    borderline.sort(key=lambda j: -j.get("borderline_score", 0))

    return {
        "run_date": run_date.isoformat(),
        "matched": top_matched,
        "borderline": borderline[:20],  # Cap borderline at 20 titles for Claude review
        "reseen_keys": reseen,
        "errors": errors,
        "stats": stats,
        "capped_companies": {
            company: count
            for company, count in unapplied_counts.items()
            if count >= COMPANY_CAP
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Poll ATS boards for matching jobs")
    parser.add_argument("--date", type=str, default=None,
                        help="Run date (YYYY-MM-DD). Defaults to today.")
    args = parser.parse_args()

    run_date = date.fromisoformat(args.date) if args.date else date.today()

    print(f"Polling ATS boards for {run_date.isoformat()}...")
    print(f"Watchlist: {WATCHLIST_PATH}")

    results = poll_all(run_date)

    # Write output
    os.makedirs(JOBS_DIR, exist_ok=True)
    output_path = os.path.join(JOBS_DIR, f"ats_hits_{run_date.isoformat()}.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    # Print summary
    s = results["stats"]
    print(f"\n=== ATS Polling Complete ===")
    print(f"Companies polled: {s['companies_polled']}")
    print(f"Total jobs scanned: {s['total_jobs_scanned']}")
    print(f"Title matches (pre-filter): {s['title_matched']}")
    print(f"Top 25 by pre-score → output (from {s.get('total_matched_before_cap', s['title_matched'])})")
    print(f"Borderline (for Claude review): {s['title_borderline']}")
    print(f"Dedup skipped: {s['dedup_skipped']}")
    print(f"Diversity-capped (>{MAX_PER_COMPANY_PER_RUN}/company, dropped from shortlist): {s.get('diversity_dropped', 0)}")
    print(f"Cap suppressed: {s['cap_suppressed']}")
    print(f"Excluded (salary/industry/seniority): {s['excluded']}")
    print(f"ATS errors: {s['errors']}")
    if results["errors"]:
        print(f"\nErrors:")
        for err in results["errors"]:
            print(f"  {err['company']}: {err['error']}")
    if results["capped_companies"]:
        print(f"\nCapped companies:")
        for co, count in results["capped_companies"].items():
            print(f"  {co}: {count} pending applications")
    print(f"\nOutput: {output_path}")


if __name__ == "__main__":
    main()
