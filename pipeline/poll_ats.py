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

# ── Config plumbing ──────────────────────────────────────────────────────────
# Single source of truth is watchlist_companies.json. Endpoints, the salary
# floor, the company cap, the small-company bonus, and EVERY title list are
# read from it at startup by _init_config() — this module defines no copy of
# anything the JSON defines (that divergence caused the 2026-06/07 miss class;
# see pipeline/audit_recurring_fixes_2026-07.md §3). Constants below are
# poller-only mechanics with no JSON counterpart.

REQUEST_TIMEOUT = 30  # seconds
DEDUP_WINDOW_DAYS = 30
MAX_PER_COMPANY_PER_RUN = 2  # diversity cap: max roles per company in the surfaced shortlist (prevents one company sweeping the run)
SHORTLIST_SIZE = 25

# Populated from watchlist_companies.json by _init_config():
ATS_ENDPOINTS = {}       # ← _endpoints (workday excluded; fetch_workday builds its URL from wd_* fields)
MIN_SALARY = None        # ← _scoring_config.salary_floor_usd
MAX_POSTING_AGE_DAYS = 21  # hard filter (CLAUDE.md Step 2b) — all ATSes; Workday dates are approximate, see extract_posted_date
COMPANY_CAP = None       # ← _scoring_config.company_cap_max_applied_pending
SMALL_COMPANY_BONUS = {}  # ← _scoring_config.small_company_bonus
MATCHER = None           # ← TitleMatcher built from _title_scoring_tiers + _poller_config


def _init_config(watchlist: dict):
    """Load all shared knobs from the parsed watchlist JSON into module globals."""
    global MIN_SALARY, COMPANY_CAP, MATCHER
    ATS_ENDPOINTS.clear()
    ATS_ENDPOINTS.update({k: v for k, v in watchlist["_endpoints"].items()
                          if not v.startswith("POST")})
    sc = watchlist["_scoring_config"]
    MIN_SALARY = sc["salary_floor_usd"]
    COMPANY_CAP = sc["company_cap_max_applied_pending"]
    SMALL_COMPANY_BONUS.clear()
    SMALL_COMPANY_BONUS.update(sc["small_company_bonus"])
    MATCHER = TitleMatcher(watchlist)


# Balanced shortlist quotas (added 2026-07-01). The small-company/novelty bonuses
# flipped the shortlist from all-incumbent to all-sub-500 in one run; per Aneesh,
# neither extreme is right. Reserve slots for both pools; the remainder is open
# competition by pre_score. "Small" = headcount_band ≤500; unknown band counts
# as large until the backfill housekeeping fills it in.
MIN_SMALL_SLOTS = 10
MIN_LARGE_SLOTS = 10
SMALL_BANDS = {"1-50", "51-200", "201-500"}
BORDERLINE_SIZE = 20
MIN_AI_WILDCARD_SLOTS = 10  # reserved quota; see borderline-list build below

# ── Title matching (config-driven, stemmed-token-subset) ────────────────────
# History: this used to be two hand-maintained substring lists that only grew
# when a human noticed a miss — at least 6 silent misses in June–July 2026
# alone, including pure word-form gaps ("Manager, Technical Account Management"
# vs "Technical Account Manager"). Now the exact gate is derived at runtime
# from _title_scoring_tiers + _poller_config in watchlist_companies.json, and
# matching is stem-normalized so word order and word form don't matter. Adding
# a title to a tier in the JSON automatically teaches the poller.

_STOPWORDS = {"of", "and", "the", "for", "in", "a", "an", "to"}

# Abbreviations folded to the stem their spelled-out form produces.
_TOKEN_ALIASES = {
    "ops": "operat",     # "Support Ops Manager" == "Support Operations Manager"
    "mgr": "manag",
    "mgmt": "manag",
    "tech": "technical",
    "eng": "engin",
}

# Suffixes stripped longest-first, repeatedly, with a minimum stem of 4 chars.
# Deliberately tiny (not a full Porter stemmer): just enough that the word
# forms that actually appear in job titles collapse together —
# manager/management/managing → manag, engineer/engineering → engin,
# operations/operation → operat, strategist/strategy → strateg,
# deployed/deployment → deploy, consultant/consulting → consult.
_SUFFIXES = ("ments", "ment", "ings", "ing", "ions", "ion", "ists", "ist",
             "ants", "ant", "ers", "er", "ors", "or", "ies", "ed", "es", "s", "y")


def _stem(tok: str) -> str:
    while len(tok) > 4:
        for suf in _SUFFIXES:
            if tok.endswith(suf) and len(tok) - len(suf) >= 4:
                if suf in ("s", "es") and tok.endswith("ss"):
                    continue  # "success" must not become "succes"
                tok = tok[:-len(suf)]
                break
        else:
            break
    if len(tok) > 4 and tok.endswith("e"):
        tok = tok[:-1]  # manage/manag, engine/engin collapse
    return tok


def tokenize(text: str) -> list[str]:
    """Title → list of normalized word stems (lowercased, punctuation-split,
    stopwords dropped, aliases folded, suffix-stemmed)."""
    out = []
    for raw in re.split(r"[^a-z0-9]+", text.lower()):
        if not raw or raw in _STOPWORDS:
            continue
        out.append(_TOKEN_ALIASES.get(raw) or _stem(raw))
    return out


def _tokens_near(cfg_tokens: frozenset, job_tokens: list, slack: int = 2) -> bool:
    """True if all cfg_tokens appear in job_tokens within a window of
    len(cfg_tokens) + slack positions (any order).

    Pure set-subset matching scatter-matched across long titles: "Senior
    Technical Product Manager, Content Platforms (AI Content Operations)"
    collected {technical, operations, manager} from opposite ends of the title
    and hit tier-1 "Technical Operations Manager". The window keeps legitimate
    reorderings ("Manager, Technical Account Management") while rejecting
    matches whose words are only coincidentally co-present.
    """
    if not cfg_tokens <= set(job_tokens):
        return False
    limit = len(cfg_tokens) + slack
    need = len(cfg_tokens)
    counts = {}
    have = 0
    left = 0
    for right, tok in enumerate(job_tokens):
        if tok in cfg_tokens:
            counts[tok] = counts.get(tok, 0) + 1
            if counts[tok] == 1:
                have += 1
        while have == need:
            if right - left + 1 <= limit:
                return True
            lt = job_tokens[left]
            if lt in cfg_tokens:
                counts[lt] -= 1
                if counts[lt] == 0:
                    have -= 1
            left += 1
    return False


class TitleMatcher:
    """Config-driven title matcher.

    A job title matches a config title when the job title contains ALL of the
    config title's stemmed tokens, in any order and any word form, within a
    small positional window (see _tokens_near). So "Manager, Technical Account
    Management", "Technical Account Manager II", and "Senior Technical Account
    Manager, East" all match the tier-2 title "Technical Account Manager" with
    no per-variant list entries.

    Sources (all in watchlist_companies.json — never hardcode a title here):
    - _title_scoring_tiers tier1..tier4 titles + tier2b explicit_titles
    - _poller_config.supplemental_exact_titles (poller-only, no scoring tier)
    - _poller_config.borderline_fragments (partial-match review list)
    - _poller_config.jd_verification_required_titles (risky-title tagging)
    """

    def __init__(self, watchlist: dict):
        tiers = watchlist["_title_scoring_tiers"]
        pc = watchlist["_poller_config"]

        self.exact = []  # (frozenset tokens, tier_name, prescore)
        for tier_name in ("tier1_true_match", "tier2_strong_overlap",
                          "tier3_reasonable_stretch", "tier4_weak_stretch"):
            spec = tiers[tier_name]
            for t in spec["titles"]:
                self._add_exact(t, tier_name, spec["title_match_score"])
        wc = tiers["tier2b_ai_wildcard"]
        self.ai_wildcard_score = wc["title_match_score"]
        for t in wc.get("explicit_titles", []):
            self._add_exact(t, "tier2b_ai_wildcard", wc["title_match_score"])
        supp = pc["supplemental_exact_titles"]
        for t in supp["titles"]:
            self._add_exact(t, "supplemental", supp["title_match_prescore"])
        # Highest-scoring tier wins when several config titles match.
        self.exact.sort(key=lambda e: -e[2])

        self.tier1_tokens = [frozenset(tokenize(t))
                             for t in tiers["tier1_true_match"]["titles"]]
        frag = pc["borderline_fragments"]
        self.fragments = [frozenset(tokenize(f)) for f in frag["fragments"]]
        self.min_fragments = frag["min_fragments"]
        self.risky_tokens = [frozenset(tokenize(t))
                             for t in pc["jd_verification_required_titles"]["titles"]]
        self.wc_signal = [w.lower() for w in wc["signal_words"]]
        self.wc_exclude = [w.lower() for w in wc["exclude_if_contains"]]
        fm = pc.get("function_mismatch_titles", {})
        self.mismatch = [frozenset(tokenize(t)) for t in fm.get("titles", [])]
        self.mismatch_protected = set(fm.get("protected_tiers", []))

    def _add_exact(self, title: str, tier_name: str, score):
        toks = frozenset(tokenize(title))
        if toks:
            self.exact.append((toks, tier_name, score))

    def match_exact(self, title: str):
        """Return (tier_name, prescore) for the best-scoring matching config
        title, or None."""
        toks = tokenize(title)
        for cfg_toks, tier_name, score in self.exact:
            if _tokens_near(cfg_toks, toks):
                return tier_name, score
        return None

    def is_tier1(self, title: str) -> bool:
        toks = tokenize(title)
        return any(_tokens_near(t1, toks) for t1 in self.tier1_tokens)

    def fragment_count(self, title: str) -> int:
        toks = tokenize(title)
        return sum(1 for f in self.fragments if _tokens_near(f, toks))

    def needs_jd_verification(self, title: str) -> bool:
        toks = tokenize(title)
        return any(_tokens_near(r, toks) for r in self.risky_tokens)

    def is_function_mismatch(self, title: str, tier_name) -> bool:
        """True when the title matches a _poller_config.function_mismatch_titles
        pattern AND its best tier match isn't protected. Protected tiers
        (tier1/tier2/tier4 by config) exist because token-subset matching would
        otherwise demote real targets that merely contain a mismatch pattern:
        'Product Engagement Manager, User Operations' (tier1) contains
        'Product…Manager', 'Support Engineering Manager' (tier1) contains
        'Engineering Manager'. Demoted titles go to the output's
        function_mismatch section (digest FYI), not the shortlist."""
        if not self.mismatch or tier_name in self.mismatch_protected:
            return False
        toks = tokenize(title)
        return any(_tokens_near(m, toks) for m in self.mismatch)

    def matches_ai_wildcard(self, title: str) -> bool:
        """Mirror _title_scoring_tiers.tier2b_ai_wildcard: a word-bounded 'AI'
        plus one signal word flags a novel AI-prefixed title for Claude review,
        without needing to clear the generic borderline threshold. Coding/IC
        titles (AI Engineer, AI Architect) are excluded so this doesn't
        re-create the FDE problem under a new name."""
        t = title.lower()
        if not re.search(r'\bai\b', t):
            return False
        if any(ex in t for ex in self.wc_exclude):
            return False
        return any(sig in t for sig in self.wc_signal)

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
    "emea", "apac", "latam", "anz", "india", "bangalore", "japan",
    "singapore", "australia", "europe", "germany", "france",
    "united kingdom", "uk", "london", "berlin", "paris",
    "canada", "toronto", "vancouver", "brazil", "mexico",
    "israel", "tel aviv", "china", "korea", "spain",
    "italy", "netherlands", "ireland", "dublin",
    "mandarin", "cantonese",  # language-specific roles
]

# Narrower than LOCATION_INCLUDE on purpose: used only to rescue dual-region
# postings (e.g. "LATAM & USA", "EMEA / US") from the exclusion check below.
# Excludes the generic "remote"/"us"/"north america"/"americas"/"anywhere"
# catch-alls, which also appear in region-locked postings like "Remote
# (Europe only)" and would wrongly un-exclude those if included here.
US_SPECIFIC_INCLUDE = [
    "united states", "usa", "u.s.",
    "atlanta", "georgia", "new york", "nyc", "new jersey",
    "boston", "chicago", "san francisco", "los angeles",
    "austin", "denver", "seattle", "portland", "dallas",
    "miami", "charlotte", "raleigh", "nashville",
]

# Titles to always exclude (too senior, wrong function).
# NOTE: an exact TIER-1 title match overrides this list (see poll_all) — tier1
# deliberately contains "Head of Support" and "Director of Support Operations",
# which the bare "head of"/"director" entries here would otherwise silently
# kill. Generic Head-of/Director titles that aren't tier-1 stay excluded.
TITLE_EXCLUDE = [
    "vice president", "vp ", "vp,", "head of", "director",
    "staff engineer", "principal engineer", "senior staff",
    "staff product", "staff software", "principal product",
    "chief ", "c-suite",
    # token-subset matching would otherwise let "Product Marketing Manager"
    # match the supplemental "Product Manager" title
    "product marketing",
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


def title_excluded(title: str) -> bool:
    """Check if title should be excluded (too senior, wrong function)."""
    t = title.lower()
    return any(excl in t for excl in TITLE_EXCLUDE)


def location_relevant(location: str, title: str) -> bool:
    """Check if the job location is US-relevant. Also checks title for region indicators."""
    loc = location.lower()
    t = title.lower()
    combined = loc + " " + t

    # Explicit exclusion wins (e.g., "Customer Success Manager, EMEA") --
    # UNLESS the same string also unambiguously names a US option (e.g.
    # "LATAM & USA", "EMEA / US Remote"). A co-listed excluded region
    # shouldn't silently kill a role the company explicitly opened to US
    # candidates too.
    if any(excl in combined for excl in LOCATION_EXCLUDE):
        if any(us_term in combined for us_term in US_SPECIFIC_INCLUDE):
            return True
        # Word-boundary check for bare "US" (e.g. "EMEA / US Remote") -- not
        # a plain substring test, since that would false-positive inside
        # "aUStralia", "belarUS", etc.
        if re.search(r'\bus\b', combined):
            return True
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


def extract_posted_date(job_data: dict, ats: str) -> date | None:
    """Extract the posting's first-published date, normalized to a date object.

    Every supported ATS now yields a date (Workday's is approximate, parsed
    from its relative "Posted N Days Ago" string). Returns None only when the
    field is missing or unparseable — callers must treat None as
    neutral/unknown, never as stale, per the same "no data → don't filter"
    rule used for salary.
    """
    try:
        if ats in ("greenhouse", "greenhouse_eu"):
            raw = job_data.get("first_published") or job_data.get("updated_at")
            if raw:
                return datetime.fromisoformat(raw).date()
        elif ats == "ashby":
            raw = job_data.get("publishedAt")
            if raw:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        elif ats == "lever":
            raw = job_data.get("createdAt")
            if raw:
                return datetime.fromtimestamp(int(raw) / 1000).date()
        elif ats == "smartrecruiters":
            raw = job_data.get("releasedDate")
            if raw:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        elif ats == "workday":
            # Workday's CXS list response has no ISO date, only a relative
            # "postedOn" string ("Posted Today" / "Posted Yesterday" /
            # "Posted 19 Days Ago" / "Posted 30+ Days Ago"), stashed by
            # fetch_workday as _posted. Approximate to a date; "30+" parses
            # as 31, which correctly trips the 21-day staleness filter.
            # (Added 2026-07-19: Workday hosts the enterprise segment where
            # stale postings are common — Cengage's Sr Manager Customer
            # Support was 19 days old and only discoverable via JD fetch.)
            raw = (job_data.get("_posted") or "").lower()
            if "today" in raw:
                return date.today()
            if "yesterday" in raw:
                return date.today() - timedelta(days=1)
            m = re.search(r"(\d+)(\+?)\s*days?\s+ago", raw)
            if m:
                days = int(m.group(1)) + (1 if m.group(2) else 0)
                return date.today() - timedelta(days=days)
    except (ValueError, TypeError, OSError):
        return None
    return None


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
    it stays unset here and is treated as neutral in scoring; Claude fetches the
    exact salary from the JD at tailoring time. The posting date IS available as
    a relative string ("Posted 19 Days Ago"), stashed as _posted and parsed by
    extract_posted_date into an approximate date for the freshness filter.

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


def company_surface_stats(seen_jobs: dict, today: date) -> tuple[set, dict]:
    """Return (companies_ever_surfaced, recent_surface_counts).

    Used for shortlist diversity: companies the pipeline has never surfaced get
    a novelty bonus, and companies surfaced repeatedly in the last 14 days get a
    repetition penalty. This directly counters the observed failure mode where
    the top 5 employers accounted for ~40% of all surfaced roles.
    """
    ever = set()
    recent = {}
    for entry in seen_jobs.values():
        co = slugify(entry.get("company", ""))
        ever.add(co)
        first_seen = entry.get("first_seen_date")
        try:
            if first_seen and (today - date.fromisoformat(first_seen)).days <= 14:
                recent[co] = recent.get(co, 0) + 1
        except (ValueError, TypeError):
            pass
    return ever, recent


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

    # Refuse to poll against a malformed watchlist (hand-edit protection —
    # trailing commas already parse-fail above; this catches schema breakage).
    from validate_config import validate_watchlist
    config_errors, config_warnings = validate_watchlist(watchlist)
    for w in config_warnings:
        print(f"CONFIG WARN: {w}")
    if config_errors:
        for e in config_errors:
            print(f"CONFIG ERROR: {e}", file=sys.stderr)
        sys.exit(2)

    # All endpoints, thresholds, and title lists come from the JSON.
    _init_config(watchlist)

    companies = watchlist["companies"]
    # Passion-domain keywords (config-driven; see _scoring_config → passion_domains).
    # Poller applies a small pre_score lift and tags the entry; Claude applies the
    # real +10 bonus semantically at full scoring.
    passion_cfg = watchlist.get("_scoring_config", {}).get("passion_domains", {})
    passion_keywords = {
        domain: [kw.lower() for kw in spec.get("poller_keywords", [])]
        for domain, spec in passion_cfg.get("domains", {}).items()
    }
    seen_jobs = load_seen_jobs()
    unapplied_counts = count_unapplied_by_company(seen_jobs)
    ever_surfaced, recent_surfaced = company_surface_stats(seen_jobs, run_date)

    matched = []
    borderline = []
    function_mismatch = []  # demoted title classes (PM/TPM/SalesEng...): digest FYI, never shortlisted
    errors = []
    reseen = []  # existing jobs re-encountered (for last_seen_date update)
    stats = {
        "companies_polled": 0,
        "total_jobs_scanned": 0,
        "title_matched": 0,
        "title_borderline": 0,
        "title_ai_wildcard": 0,
        "jd_verification_flagged": 0,
        "function_mismatch": 0,
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

            # Check title match
            exact_match = MATCHER.match_exact(title)

            # Title exclusion — but an exact TIER-1 match overrides it: tier1
            # includes "Head of Support" / "Director of Support Operations",
            # which the generic "head of"/"director" exclusions would kill.
            # Non-tier1 senior titles (VP of CS, Director of CSM...) stay out.
            if title_excluded(title) and not (exact_match and MATCHER.is_tier1(title)):
                stats["excluded"] += 1
                continue

            is_exact = exact_match is not None
            borderline_count = MATCHER.fragment_count(title)
            is_ai_wildcard = not is_exact and MATCHER.matches_ai_wildcard(title)

            if not is_exact and borderline_count < MATCHER.min_fragments and not is_ai_wildcard:
                continue  # Not relevant at all

            location = parse_location(job_data, ats)

            # Location filter
            if not location_relevant(location, title):
                stats["excluded"] += 1
                continue

            apply_url = build_apply_url(job_data, ats, slug)

            # Freshness hard filter (CLAUDE.md Step 2b: exclude postings >21
            # days old). Only enforced when a date could be extracted; a
            # missing/unparseable date stays neutral, same as the
            # "no salary listed" rule. Found 2026-07-13: 6 of a
            # day's top-25 pre-scored matches (Harvey, PermitFlow, Smile
            # Digital Health, Vanta, Replicant, Chainguard) were 27-84 days
            # old and had been silently wasting full tailoring effort across
            # multiple runs because nothing checked absolute posting age.
            posted_date = extract_posted_date(job_data, ats)
            posting_age_days = (run_date - posted_date).days if posted_date else None
            if posting_age_days is not None and posting_age_days > MAX_POSTING_AGE_DAYS:
                stats["excluded"] += 1
                continue

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
            new_req_of_applied = False
            if matched_key:
                seen_entry = seen_jobs[matched_key]
                seen_url = (seen_entry.get("url") or "").rstrip("/").lower()
                new_url = (apply_url or "").rstrip("/").lower()
                same_url = bool(seen_url and new_url and seen_url == new_url)
                # An already-applied posting must never resurface as "new" just
                # because it's been open long enough to outlive the 30-day
                # dedup window (observed 2026-07-06: Assembled's Enterprise
                # Deployment Strategist, applied 2026-05-07, resurfaced as a
                # fresh match on 2026-07-06 because first_seen_date was 61 days
                # old). Same URL + applied = permanent skip regardless of age.
                if seen_entry.get("applied") and same_url:
                    stats["dedup_skipped"] += 1
                    reseen.append(matched_key)
                    continue
                if is_within_dedup_window(seen_entry, run_date):
                    # Title-based keys collide when a company reposts the same
                    # title under a NEW requisition (observed: Ping Identity
                    # Senior TAM). If the stored entry was applied but this
                    # posting has a different URL, it's a new req — surface it
                    # flagged instead of silently skipping. Unapplied
                    # same-title reposts stay skipped (noise within the window).
                    if seen_entry.get("applied") and not same_url:
                        new_req_of_applied = True
                    else:
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
                "posted_date": posted_date.isoformat() if posted_date else None,
                "posting_age_days": posting_age_days,
                "match_type": "exact" if is_exact else "borderline",
                "borderline_score": borderline_count if not is_exact else None,
                "headcount_band": company.get("headcount_band"),
                # Which config tier the title matched (tier1_true_match ...
                # supplemental) and its pre-score — Claude uses this at full
                # scoring instead of re-deriving the tier by hand.
                "title_tier": exact_match[0] if is_exact else None,
                "title_prescore": exact_match[1] if is_exact else None,
            }
            if new_req_of_applied:
                entry["new_req_of_applied_title"] = True
            if is_ai_wildcard:
                # Flags entries that only qualified via tier2b_ai_wildcard so
                # Claude scores them at +18 (not by guessing a tier) and the
                # digest can call out "novel AI title, needs a look."
                entry["ai_wildcard"] = True
            if MATCHER.needs_jd_verification(title):
                # Known-risky title (per _poller_config): read the full JD
                # before tailoring, and don't let it consume a diversity-cap
                # slot ahead of a clean same-company title (see shortlist build).
                entry["jd_verification_required"] = True
                stats["jd_verification_flagged"] += 1

            # Function-mismatch demotion (config: _poller_config.
            # function_mismatch_titles). These title classes (Product Manager,
            # TPM, Sales Engineer, Engineering Manager...) matched the gate for
            # months but were manually skipped as "poor function fit" in every
            # run — on 2026-07-19 they held ~13 of 25 shortlist slots including
            # the top two pre-scores. They stay visible as digest FYI lines but
            # never consume a shortlist or borderline slot. Tier1/tier2/tier4
            # best-matches are protected (see is_function_mismatch docstring).
            if MATCHER.is_function_mismatch(title, entry["title_tier"]):
                function_mismatch.append({
                    "company": name,
                    "title": title,
                    "location": location,
                    "apply_url": apply_url,
                    "title_tier": entry["title_tier"],
                    "posting_age_days": posting_age_days,
                })
                stats["function_mismatch"] += 1
                continue

            if is_exact:
                matched.append(entry)
                stats["title_matched"] += 1
            else:
                borderline.append(entry)
                stats["title_borderline"] += 1
                if is_ai_wildcard:
                    stats["title_ai_wildcard"] += 1

        # Rate limit: small delay between companies to be polite
        time.sleep(0.3)

    def pre_score_job(job: dict, default_title_prescore: int = 15) -> int:
        """Shared pre-score formula. Used for exact `matched` titles (where
        title_prescore comes from _title_scoring_tiers) AND for ai_wildcard
        borderline entries (title_prescore is deliberately None for those —
        see the entry-building comment above — so they fall back to the
        tier2b_ai_wildcard score the caller passes in). Extracted 2026-07-10
        after Arcadia's "AI Operations Lead" (ai_wildcard borderline, real
        full-score ~112) sat unscored in the borderline list, ranked only by
        a low-fidelity fragment-count borderline_score, and got skipped in a
        busy run — see pipeline/audit_recurring_fixes_2026-07.md."""
        score = 0
        t = job["title"].lower()

        # Title quality — the matched tier's score straight from
        # _title_scoring_tiers / _poller_config (tier1 30, tier2 22, tier2b 18,
        # tier3 15, supplemental 15, tier4 8). This replaces a hardcoded
        # "top titles" list that had drifted from the tier config (it treated
        # tier-3 CSM titles as top-tier and, until 2026-07-09, gave Forward
        # Deployed Engineer a +30 premium despite a near-100% JD miss rate —
        # FDE now inherits tier4's +8 automatically).
        score += job.get("title_prescore") or default_title_prescore

        # Seniority match (senior = ok, principal/staff = excluded already, manager II = ok)
        if "senior" in t or "sr " in t or "sr." in t:
            score += 5
        if "associate" in t or "junior" in t:
            score -= 5

        # Location
        loc = job["location"].lower()
        # Dual-region postings (e.g. "LATAM & USA") already cleared
        # location_relevant()'s gate above by explicitly naming a US option
        # alongside an excluded region -- but without this check they'd still
        # fall to the lowest bucket below since they don't contain the literal
        # word "remote". Treat them the same as a remote US role.
        us_named = (any(t in loc for t in US_SPECIFIC_INCLUDE)
                    or re.search(r'\bus\b', loc))
        if "remote" in loc or us_named:
            score += 20
        elif "atlanta" in loc:
            score += 20
        elif "new york" in loc or "nyc" in loc:
            score += 12
        elif "boston" in loc:
            score += 5
        else:
            score += 3

        # Priority — softened 2026-07-01 (was high 15 / medium 8). The priority
        # field describes the COMPANY, not the role, and at +15 it entrenched
        # watchlist incumbents at the top of every shortlist.
        score += {"high": 10, "medium": 6, "low": 3}.get(job["priority"], 5)

        # Small-company bonus (read from _scoring_config → small_company_bonus,
        # not mirrored). Previously only applied in Claude's full scoring —
        # which meant sub-500 companies often never REACHED full scoring
        # because pre_score decides the top-25 shortlist. Absent band = 0,
        # never guess.
        score += SMALL_COMPANY_BONUS.get(job.get("headcount_band") or "", 0)

        # Passion-domain lift (+5, tag for Claude's semantic +10 at full scoring).
        # Matched against title + company name only; description isn't kept on
        # the entry, and false positives are cheap here (Claude re-judges).
        passion_text = t + " " + job.get("company", "").lower()
        for domain, kws in passion_keywords.items():
            if any(kw in passion_text for kw in kws):
                score += 5
                job["passion_domain"] = domain
                break

        # Novelty / repetition (see company_surface_stats). Companies never
        # surfaced before get a lift; companies surfaced repeatedly in the last
        # 14 days get pushed down so the shortlist rotates.
        co_slug = slugify(job.get("company", ""))
        if co_slug not in ever_surfaced:
            score += 6
        score -= min(recent_surfaced.get(co_slug, 0) * 3, 9)

        # Salary
        if job.get("salary_min") and job["salary_min"] >= 130_000:
            score += 10
        elif job.get("salary_min") and job["salary_min"] >= MIN_SALARY:
            score += 5

        # AI/voice boost — TITLE ONLY. Previously also matched the company name,
        # which auto-granted +10 to every role at an AI-named company (Cresta,
        # OpenAI, Arize…) regardless of the role's actual relevance. That rewarded
        # company identity over role fit and let one AI company sweep the shortlist.
        # "ai" is word-boundary matched (2026-07-09 fix) — a bare substring check
        # would false-positive on any title containing "domain," "maintain,"
        # "captain," etc.
        if re.search(r'\bai\b', t) or any(kw in t for kw in ["agentic", "voice", "llm", "machine learning"]):
            score += 10
        # IoT boost — company-name match retained: Aneesh's IoT background is a
        # genuine domain differentiator and few watchlist companies are IoT-named.
        for kw in ["iot", "hardware", "smart home", "connected"]:
            if kw in t or kw in job.get("company", "").lower():
                score += 8
                break

        return score

    # Pre-score and rank matched jobs
    for job in matched:
        job["pre_score"] = pre_score_job(job)

    # Pre-score ai_wildcard borderline entries too (title_prescore is None for
    # these by design — they never hit an exact tier — so fall back to
    # tier2b_ai_wildcard's title_match_score). Without this they only carry a
    # fragment-count borderline_score and can't be triaged by real fit; see
    # the pre_score_job docstring for the miss this fixes.
    tier2b_score = MATCHER.ai_wildcard_score
    for job in borderline:
        if job.get("ai_wildcard"):
            job["pre_score"] = pre_score_job(job, default_title_prescore=tier2b_score)

    # Sort by pre-score, then apply a per-company DIVERSITY CAP before keeping
    # the top 25. Without this, a single company that posts many CS-adjacent
    # roles (and stacks company-level bonuses) fills the entire shortlist. We
    # surface at most MAX_PER_COMPANY_PER_RUN roles per company so Claude's
    # review set stays diverse; additional same-company roles are dropped from
    # the shortlist (still recorded in stats) and can be revisited next run.
    matched.sort(key=lambda j: -j["pre_score"])
    stats["total_matched_before_cap"] = len(matched)

    # Within each company, demote jd_verification_required titles below that
    # company's clean titles before the diversity cap picks its ≤2 keepers.
    # Without this, a risky high-pre-score title (FDE is the prototype) crowds
    # a safer, genuinely better-fitting title at the same company out of the
    # shortlist entirely — Confido's Implementation Manager was invisible on
    # 2026-07-09 because CSM + FDE took both slots and FDE failed the JD read.
    # Implementation: jobs keep their global slots; only same-company jobs
    # swap among the positions they already occupy, so overall ranking is
    # otherwise untouched. Risky roles still surface when slots remain.
    slots_by_company = {}
    for idx, j in enumerate(matched):
        slots_by_company.setdefault(slugify(j.get("company", "")), []).append(idx)
    for slots in slots_by_company.values():
        if len(slots) < 2:
            continue
        reordered = sorted((matched[i] for i in slots),
                           key=lambda j: (bool(j.get("jd_verification_required")),
                                          -j["pre_score"]))
        for i, job in zip(slots, reordered):
            matched[i] = job

    # Build the shortlist with per-company diversity cap AND small/large balance.
    kept_per_company = {}
    diversity_dropped = 0

    def try_take(job, shortlist, taken_keys):
        nonlocal diversity_dropped
        co = slugify(job.get("company", ""))
        if kept_per_company.get(co, 0) >= MAX_PER_COMPANY_PER_RUN:
            diversity_dropped += 1
            taken_keys.add(id(job))  # cap won't free up; don't retry or re-count
            return False
        kept_per_company[co] = kept_per_company.get(co, 0) + 1
        shortlist.append(job)
        taken_keys.add(id(job))
        return True

    small_pool = [j for j in matched if (j.get("headcount_band") or "") in SMALL_BANDS]
    large_pool = [j for j in matched if (j.get("headcount_band") or "") not in SMALL_BANDS]

    top_matched = []
    taken = set()
    # Phase 1: fill each pool's reserved slots (score order within pool)
    for pool, quota in ((small_pool, MIN_SMALL_SLOTS), (large_pool, MIN_LARGE_SLOTS)):
        count = 0
        for job in pool:
            if count >= quota or len(top_matched) >= SHORTLIST_SIZE:
                break
            if try_take(job, top_matched, taken):
                count += 1
    # Phase 2: open competition for the remaining slots
    for job in matched:
        if len(top_matched) >= SHORTLIST_SIZE:
            break
        if id(job) in taken:
            continue
        try_take(job, top_matched, taken)

    top_matched.sort(key=lambda j: -j["pre_score"])
    stats["diversity_dropped"] = diversity_dropped
    stats["shortlist_small"] = sum(
        1 for j in top_matched if (j.get("headcount_band") or "") in SMALL_BANDS)
    stats["shortlist_large_or_unknown"] = len(top_matched) - stats["shortlist_small"]

    # Cap borderline at BORDERLINE_SIZE, but reserve slots for ai_wildcard hits
    # first. A plain score-sort-then-slice buries them: ai_wildcard entries
    # often carry a low borderline_score (that's exactly why they didn't clear
    # the generic 2-fragment threshold on their own), so on a busy AI-title day
    # they'd lose every tiebreak against ordinary fragment matches and never
    # reach the output Claude reads — silently defeating the wildcard match in
    # MATCHER.matches_ai_wildcard(). Mirrors the small/large reserved-quota
    # pattern used for the matched shortlist above.
    #
    # Sort the ai_wildcard pool by the real pre_score computed above, not
    # borderline_score (fragment-match count, 1-3 typically — a near-random
    # ranking of actual fit). Fixed 2026-07-10 after Arcadia's "AI Operations
    # Lead" — full score ~112, i.e. would have led the WHOLE shortlist — sat
    # ranked by fragment count alongside noise and was never flagged for
    # priority review. other_pool (non-wildcard borderline) still has no real
    # pre_score computed, so it keeps the old borderline_score sort.
    ai_wildcard_pool = sorted(
        (j for j in borderline if j.get("ai_wildcard")),
        key=lambda j: -j.get("pre_score", j.get("borderline_score", 0)),
    )
    other_pool = sorted(
        (j for j in borderline if not j.get("ai_wildcard")),
        key=lambda j: -j.get("borderline_score", 0),
    )
    reserved = ai_wildcard_pool[:MIN_AI_WILDCARD_SLOTS]
    leftover = ai_wildcard_pool[MIN_AI_WILDCARD_SLOTS:] + other_pool
    leftover.sort(key=lambda j: -j.get("pre_score", j.get("borderline_score", 0)))
    borderline_capped = reserved + leftover[:BORDERLINE_SIZE - len(reserved)]

    # Function-mismatch FYI list: dedup-suppressed against seen_jobs' 30-day
    # window is NOT applied here (these are never tracked), so just cap the
    # list to keep the output file readable on PM-heavy days.
    function_mismatch.sort(key=lambda j: (j["company"], j["title"]))

    return {
        "run_date": run_date.isoformat(),
        "matched": top_matched,
        "borderline": borderline_capped,
        "function_mismatch": function_mismatch[:40],
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
    print(f"Borderline (for Claude review): {s['title_borderline']} (of which {s['title_ai_wildcard']} via AI-wildcard)")
    print(f"Dedup skipped: {s['dedup_skipped']}")
    print(f"Diversity-capped (>{MAX_PER_COMPANY_PER_RUN}/company, dropped from shortlist): {s.get('diversity_dropped', 0)}")
    print(f"Flagged jd_verification_required (risky title, read JD first): {s.get('jd_verification_flagged', 0)}")
    print(f"Function-mismatch demoted (PM/TPM/SalesEng..., digest FYI only): {s.get('function_mismatch', 0)}")
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
    ai_wildcard_hits = sorted(
        (j for j in results["borderline"] if j.get("ai_wildcard")),
        key=lambda j: -j.get("pre_score", 0),
    )
    if ai_wildcard_hits:
        print(f"\nTop AI-wildcard borderline hits (now pre-scored — review before finalizing the shortlist, don't just skim):")
        for j in ai_wildcard_hits[:5]:
            print(f"  [{j['pre_score']}] {j['company']}: {j['title']}")
    print(f"\nOutput: {output_path}")


if __name__ == "__main__":
    main()
