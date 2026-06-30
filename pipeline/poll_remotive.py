#!/usr/bin/env python3
"""
Daily discovery feeder: Remotive remote-jobs API → enrollment queue.

Remotive (https://remotive.com/api/remote-jobs) is a free, structured JSON feed
that skews remote + startup — useful long-tail coverage the big-company watchlist
misses. UNLIKE the HN harvester, Remotive does NOT expose the underlying ATS link
(it hosts the JD itself and links back to remotive.com), so this feeder produces
NAME-ONLY leads flagged `needs_ats_resolution`: "Company X is hiring <role>, US/
remote." The enrollment step (daily_task_prompt.md Step 1b) resolves the ATS via a
quick `site:greenhouse.io OR ashby OR lever <company>` search before enrolling.

RemoteOK was evaluated 2026-06-30 and dropped: its feed returned low-quality,
mostly non-US junk (e.g. "Sharetea Edmonton", "Macquarie Group Testing") and, like
Remotive, no ATS link — not worth the noise.

This is a DISCOVERY FEEDER, not a job source. Idempotent (dedupes by company name).

Usage:
    .venv/bin/python pipeline/poll_remotive.py
    .venv/bin/python pipeline/poll_remotive.py --dry-run
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

REMOTIVE_API = "https://remotive.com/api/remote-jobs"
TIMEOUT = 30
HEADERS = {"User-Agent": "Mozilla/5.0 (resume-pipeline-remotive)"}

# Remotive search is a broad keyword match over title+description, so we re-filter
# on the TITLE against these precise phrases. Each is also a search seed.
TITLE_PHRASES = [
    "customer success", "technical account", "solutions engineer", "solutions consultant",
    "implementation manager", "implementation consultant", "professional services",
    "customer experience", "support operations", "forward deployed", "engagement manager",
    "customer operations", "technical support manager", "deployment strategist",
]
SEARCH_SEEDS = ["customer success", "technical account manager", "implementation",
                "solutions engineer", "professional services", "forward deployed"]

# candidate_required_location values that count as US-reachable.
US_OK = ["usa", "us", "u.s.", "united states", "north america", "americas",
         "anywhere", "worldwide"]
# ...but drop if it's pinned to a clearly non-US country only.
FOREIGN_ONLY = ["india", "brazil", "philippines", "europe only", "emea only", "uk only",
                "germany", "canada only", "latam only", "apac"]


def norm_name(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def title_matches(title):
    low = (title or "").lower()
    return next((p for p in TITLE_PHRASES if p in low), None)


def location_ok(loc):
    low = (loc or "").lower()
    if any(f in low for f in FOREIGN_ONLY):
        return False
    return any(u in low for u in US_OK)


def load_known_names():
    """Normalized names already on the watchlist or in any queue bucket."""
    names = set()
    with open(WATCHLIST_PATH) as f:
        wl = json.load(f)
    for c in wl.get("companies", []):
        names.add(norm_name(c.get("name")))
    with open(QUEUE_PATH) as f:
        q = json.load(f)
    for bucket in ("pending", "enrolled", "rejected"):
        for e in q.get(bucket, []):
            names.add(norm_name(e.get("name")))
    return names, q


def fetch(seed):
    r = requests.get(REMOTIVE_API, headers=HEADERS, timeout=TIMEOUT, params={"search": seed})
    r.raise_for_status()
    return r.json().get("jobs", []) or []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    known, queue = load_known_names()
    seen_this_run = set()
    new_leads = []

    for seed in SEARCH_SEEDS:
        try:
            jobs = fetch(seed)
        except Exception as e:
            print(f"  seed '{seed}': fetch failed ({e})")
            continue
        for j in jobs:
            title = j.get("title", "")
            phrase = title_matches(title)
            if not phrase:
                continue
            if not location_ok(j.get("candidate_required_location", "")):
                continue
            company = (j.get("company_name") or "").strip()
            nk = norm_name(company)
            if not nk or nk in known or nk in seen_this_run:
                continue
            seen_this_run.add(nk)
            new_leads.append({
                "name": company,
                "ats": None,
                "slug": None,
                "needs_ats_resolution": True,
                "source": "Remotive API",
                "first_seen": date.today().isoformat(),
                "why": f"Remotive — '{title.strip()}' | {j.get('candidate_required_location', '')}".strip(),
            })

    print(f"New name-only leads (need ATS resolution at enrollment): {len(new_leads)}")
    for c in new_leads:
        print(f"  + {c['name']:32s} | {c['why'][:70]}")

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
