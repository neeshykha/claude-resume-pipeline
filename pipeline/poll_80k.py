#!/usr/bin/env python3
"""
Daily discovery feeder: 80,000 Hours job board (Algolia API) → enrollment queue.

The 80K Hours board (jobs.80000hours.org) lists ~850 jobs at EA / AI-safety /
public-good orgs. Its search frontend embeds a PUBLIC Algolia search key, so the
whole board is directly queryable — no browser, no JS rendering, no WebSearch
snippets (which surfaced ~5 org pages vs 84+ live listings; confirmed undercount
2026-07-06, access upgraded 2026-07-13). Same Algolia pattern as
harvest_hn_hiring.py.

Hits are RICHER than Remotive's: they carry salary, location tags, posted_at,
and `url_external` (the real apply link). When that link points at a supported
ATS (Greenhouse/Ashby/Lever) we extract (ats, slug) directly — the lead is
immediately verifiable at enrollment. Otherwise it's a name-only lead flagged
`needs_ats_resolution`, with the apply URL preserved in `why`.

This is a DISCOVERY FEEDER, not a job source: it surfaces COMPANIES for the
enrollment queue. The watchlist poller scans an enrolled company's full roster
daily. Idempotent (dedupes by company name AND (ats, slug) against the
watchlist + all queue buckets).

Caveats encoded below: the board skews research/engineering titles, some roles
are volunteer/unpaid or hourly-admin, and UK/EU-only orgs are common — we filter
to US-reachable, target-role-shaped, non-junior titles.

Usage:
    .venv/bin/python pipeline/poll_80k.py
    .venv/bin/python pipeline/poll_80k.py --dry-run
"""
import argparse
import json
import os
import re
from datetime import date

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_PATH = os.path.join(SCRIPT_DIR, "watchlist_companies.json")
QUEUE_PATH = os.path.join(SCRIPT_DIR, "enrollment_candidates.json")

ALGOLIA_ENDPOINT = "https://W6KM1UDIB3-dsn.algolia.net/1/indexes/jobs_prod/query"
ALGOLIA_HEADERS = {
    "x-algolia-application-id": "W6KM1UDIB3",
    # Public search-only key embedded in the jobs.80000hours.org frontend.
    "x-algolia-api-key": "d1d7f2c8696e7b36837d5ed337c4a319",
    "Content-Type": "application/json",
}
TIMEOUT = 30
HITS_PER_SEED = 50

SEARCH_SEEDS = [
    "operations manager",
    "operations lead",
    "business operations",
    "program manager",
    "customer success",
    "technical account manager",
    "implementation",
    "support operations",
]

# Title must contain one of these to count as fit-space.
TITLE_PHRASES = [
    "operations", "customer success", "technical account", "implementation",
    "program manager", "support", "deployment", "engagement manager",
    "professional services", "solutions",
]

# ...but not these (research/eng/legal/junior-admin roles dominate this board).
TITLE_EXCLUDE = [
    "research", "scientist", "engineer", "engineering", "counsel", "attorney",
    "intern", "fellow", "phd", "professor", "assistant", "coordinator",
    "associate", "chair", "trustee", "chief ", "ceo", "cto", "cfo",
]

GLOBAL_OK = ["global", "worldwide", "anywhere"]


def norm_name(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def title_ok(title):
    low = (title or "").lower()
    if any(x in low for x in TITLE_EXCLUDE):
        return False
    return any(p in low for p in TITLE_PHRASES)


def location_ok(tags_country, tags_city):
    """US-reachable: USA-tagged, globally remote, or untagged-but-remote.

    'Remote' alone is NOT enough when a non-US country tag is present
    (e.g. tags ['Remote'] + country ['UK'] is a UK-remote role)."""
    countries = [t.lower() for t in (tags_country or [])]
    cities = [t.lower() for t in (tags_city or [])]
    if any("usa" in c for c in countries):
        return True
    if any(g in t for t in countries + cities for g in GLOBAL_OK):
        return True
    return not countries and any("remote" in c for c in cities)


# ATS link → (ats, slug). Mirrors harvest_hn_hiring.py's patterns.
ATS_PATTERNS = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9][a-z0-9_-]+)", re.I)),
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/([a-z0-9][a-z0-9_-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([a-z0-9][a-z0-9_%-]+)", re.I)),
    ("lever", re.compile(r"jobs\.lever\.co/([a-z0-9][a-z0-9_-]+)", re.I)),
]
SLUG_BLOCKLIST = {"jobs", "job", "embed", "boards", "careers"}


def extract_ats(url):
    for ats, pat in ATS_PATTERNS:
        m = pat.search(url or "")
        if m and m.group(1).lower() not in SLUG_BLOCKLIST:
            return ats, m.group(1)
    return None, None


def load_known():
    """Normalized company names + (ats, slug) pairs already tracked anywhere."""
    names, pairs = set(), set()
    with open(WATCHLIST_PATH) as f:
        wl = json.load(f)
    for c in wl.get("companies", []):
        names.add(norm_name(c.get("name")))
        if c.get("ats") and c.get("slug"):
            pairs.add((c["ats"], c["slug"].lower()))
    with open(QUEUE_PATH) as f:
        q = json.load(f)
    for bucket in ("pending", "enrolled", "rejected"):
        for e in q.get(bucket, []):
            names.add(norm_name(e.get("name")))
            if e.get("ats") and e.get("slug"):
                pairs.add((e["ats"], e["slug"].lower()))
    return names, pairs, q


def fetch(seed):
    body = {
        "query": seed,
        "hitsPerPage": HITS_PER_SEED,
        "attributesToRetrieve": [
            "title", "company_name", "tags_city", "tags_country",
            "salary", "url_external", "company_url", "posted_at",
        ],
    }
    r = requests.post(ALGOLIA_ENDPOINT, headers=ALGOLIA_HEADERS,
                      json=body, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json().get("hits", []) or []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    known_names, known_pairs, queue = load_known()
    seen_this_run = set()
    new_leads = []

    for seed in SEARCH_SEEDS:
        try:
            hits = fetch(seed)
        except Exception as e:
            print(f"  seed '{seed}': fetch failed ({e})")
            continue
        for h in hits:
            title = h.get("title", "")
            if not title_ok(title):
                continue
            if not location_ok(h.get("tags_country"), h.get("tags_city")):
                continue
            company = (h.get("company_name") or "").strip()
            nk = norm_name(company)
            if not nk or nk in known_names or nk in seen_this_run:
                continue
            ats, slug = extract_ats(h.get("url_external"))
            if ats and (ats, slug.lower()) in known_pairs:
                continue
            seen_this_run.add(nk)
            loc = ", ".join(h.get("tags_city") or h.get("tags_country") or [])
            salary = h.get("salary") or "salary unlisted"
            lead = {
                "name": company,
                "ats": ats,
                "slug": slug,
                "source": "80K Hours Algolia API",
                "first_seen": date.today().isoformat(),
                "why": f"80K Hours — '{title.strip()}' | {loc} | {salary} | {(h.get('url_external') or '')[:120]}",
            }
            if not ats:
                lead["needs_ats_resolution"] = True
            new_leads.append(lead)

    resolved = sum(1 for c in new_leads if c.get("ats"))
    print(f"New leads: {len(new_leads)} ({resolved} with ATS pre-resolved, "
          f"{len(new_leads) - resolved} name-only)")
    for c in new_leads:
        tag = f"{c['ats']}/{c['slug']}" if c.get("ats") else "needs ATS resolution"
        print(f"  + {c['name']:32s} [{tag}] | {c['why'][:80]}")

    if args.dry_run:
        print("\n--dry-run: queue not modified.")
        return
    if not new_leads:
        print("\nNothing new to append.")
        return

    queue.setdefault("pending", []).extend(new_leads)
    with open(QUEUE_PATH, "w") as f:
        json.dump(queue, f, indent=2)
        f.write("\n")
    print(f"\nAppended {len(new_leads)} leads to enrollment_candidates.json → pending.")


if __name__ == "__main__":
    main()
