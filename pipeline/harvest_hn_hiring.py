#!/usr/bin/env python3
"""
Harvest the monthly Hacker News "Ask HN: Who is hiring?" thread for off-watchlist
companies and append them to the enrollment queue.

Why this exists: HN's monthly hiring thread is ~500 companies/month, free and
structured via the Algolia API, and startup-dense — exactly the sub-500 segment
the big-company watchlist and Google dorks miss. Each top-level comment is one
company, usually with a direct ATS apply link (Greenhouse/Ashby/Lever/SmartRecruiters/
Workable). We extract (ats, slug) straight from those links — the slug IS the
enrollable key, so no fragile company-name parsing is needed.

This is a DISCOVERY FEEDER, not a job source: it only appends new companies to
`enrollment_candidates.json → pending`. The next pipeline run verifies each board
and enrolls or rejects it (daily_task_prompt.md Step 1b). Cadence: monthly (the
thread posts on the 1st), but safe to run any time — it's idempotent.

Usage:
    .venv/bin/python pipeline/harvest_hn_hiring.py            # auto-find latest thread
    .venv/bin/python pipeline/harvest_hn_hiring.py --item 48357725
    .venv/bin/python pipeline/harvest_hn_hiring.py --dry-run  # show finds, don't write
"""
import argparse
import html
import json
import os
import re
from datetime import date

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_PATH = os.path.join(SCRIPT_DIR, "watchlist_companies.json")
QUEUE_PATH = os.path.join(SCRIPT_DIR, "enrollment_candidates.json")

ALGOLIA_SEARCH = "https://hn.algolia.com/api/v1/search_by_date"
ALGOLIA_ITEM = "https://hn.algolia.com/api/v1/items/{item_id}"
TIMEOUT = 30
HEADERS = {"User-Agent": "Mozilla/5.0 (resume-pipeline-hn-harvest)"}

# Target-title signal. Discovery, not final filtering — but precise enough that a
# pure-SWE hiring post doesn't slip through on an incidental word. Two tiers:
# (1) specific multi-word phrases, safe as substrings; (2) abbreviations that need
# word boundaries (bare "tam" was matching inside "team", "csm" inside other words).
TITLE_SIGNALS = [
    "customer success", "technical account", "solutions engineer", "solutions consultant",
    "implementation consultant", "implementation manager", "professional services",
    "deployment strategist", "deployment manager", "forward deployed", "customer experience",
    "engagement manager", "support operations", "support engineer", "customer engineer",
    "field engineer", "technical support", "customer operations", "customer support",
    "technical program manager", "post-sales", "sales engineer", "onboarding manager",
    "enablement manager", "customer success manager", "customer support manager",
]
ABBREV_SIGNALS = [
    (re.compile(r"\btam\b", re.I), "tam"),
    (re.compile(r"\bcsm\b", re.I), "csm"),
]

# Clearly non-US-only signals — skip a comment if it's location-tagged ONLY to these
# and has no remote/US hint. (Conservative: only drop on an explicit foreign-only tag.)
US_REMOTE_HINTS = ["remote", "united states", "usa", "u.s.", " us ", "us-", "anywhere",
                   "north america", "americas", "worldwide", "global"]
FOREIGN_ONLY_HINTS = ["onsite only", "on-site only", "no remote"]

# ATS link → (ats_provider, slug). Order matters; first match wins per provider.
ATS_PATTERNS = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9][a-z0-9_-]+)", re.I)),
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/([a-z0-9][a-z0-9_-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([a-z0-9][a-z0-9_%-]+)", re.I)),
    ("lever", re.compile(r"jobs\.lever\.co/([a-z0-9][a-z0-9_-]+)", re.I)),
    ("smartrecruiters", re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([a-z0-9][a-z0-9_-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/([a-z0-9][a-z0-9_-]+)", re.I)),
    ("workable", re.compile(r"https?://([a-z0-9][a-z0-9_-]+)\.workable\.com", re.I)),
]
# Workday needs tenant+datacenter+site (site isn't in the link) — flag for manual verify.
WORKDAY_PATTERN = re.compile(r"([a-z0-9][a-z0-9_-]+)\.(wd\d+)\.myworkdayjobs\.com", re.I)

# Greenhouse/ashby reserved path segments that are NOT company slugs.
SLUG_BLOCKLIST = {"embed", "v1", "boards", "job_board", "jobs", "api"}


def latest_hiring_thread():
    """Return (item_id, title) of the most recent 'Ask HN: Who is hiring?' thread."""
    r = requests.get(ALGOLIA_SEARCH, headers=HEADERS, timeout=TIMEOUT,
                     params={"tags": "story,author_whoishiring", "hitsPerPage": 10})
    r.raise_for_status()
    for hit in r.json().get("hits", []):
        title = hit.get("title", "")
        if re.match(r"Ask HN:\s*Who is hiring\?", title, re.I):
            return hit["objectID"], title
    raise SystemExit("Could not find a 'Who is hiring?' thread via Algolia.")


def fetch_comments(item_id):
    """Return list of top-level comment texts for the thread."""
    r = requests.get(ALGOLIA_ITEM.format(item_id=item_id), headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    children = r.json().get("children", []) or []
    out = []
    for c in children:
        if c and c.get("text"):
            out.append(c["text"])
    return out


def clean_text(raw):
    """HN comment HTML → plain text."""
    txt = re.sub(r"<[^>]+>", " ", raw)
    txt = html.unescape(txt)
    return re.sub(r"\s+", " ", txt).strip()


def extract_candidates(text):
    """Return list of (ats, slug) found in a comment's ATS links."""
    found = []
    for ats, pat in ATS_PATTERNS:
        for m in pat.finditer(text):
            slug = m.group(1)
            if slug.lower() in SLUG_BLOCKLIST:
                continue
            found.append((ats, slug))
    for m in WORKDAY_PATTERN.finditer(text):
        found.append(("workday", m.group(1)))  # site unknown — enrollment step runs verify_workday
    return found


def has_target_title(text):
    low = text.lower()
    hit = next((s for s in TITLE_SIGNALS if s in low), None)
    if hit:
        return hit
    for pat, label in ABBREV_SIGNALS:
        if pat.search(text):
            return label
    return None


def is_us_or_remote(text):
    low = text.lower()
    if any(h in low for h in FOREIGN_ONLY_HINTS):
        return False
    return any(h in low for h in US_REMOTE_HINTS) or True  # default-include; scoring filters location later


def load_known():
    """All (ats, slug) already on the watchlist or already in the queue (any bucket)."""
    known = set()
    with open(WATCHLIST_PATH) as f:
        wl = json.load(f)
    for c in wl.get("companies", []):
        if c.get("ats") and c.get("slug"):
            known.add((c["ats"], c["slug"].lower()))
    with open(QUEUE_PATH) as f:
        q = json.load(f)
    for bucket in ("pending", "enrolled", "rejected"):
        for e in q.get(bucket, []):
            if e.get("ats") and e.get("slug"):
                known.add((e["ats"], e["slug"].lower()))
    return known, q


def short_why(text, title_hit):
    """A compact reason string: the title signal + a trimmed snippet."""
    snippet = text[:160].strip()
    return f"HN hiring thread — matched '{title_hit}'. Snippet: {snippet}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--item", help="HN story objectID to harvest (default: latest auto-found)")
    ap.add_argument("--dry-run", action="store_true", help="print finds, do not write the queue")
    args = ap.parse_args()

    if args.item:
        item_id, title = args.item, f"(item {args.item})"
    else:
        item_id, title = latest_hiring_thread()
    print(f"Harvesting: {title}  (item {item_id})")

    comments = fetch_comments(item_id)
    print(f"Top-level comments: {len(comments)}")

    known, queue = load_known()
    seen_this_run = set()
    new_candidates = []
    for raw in comments:
        text = clean_text(raw)
        title_hit = has_target_title(text)
        if not title_hit:
            continue
        if not is_us_or_remote(text):
            continue
        for ats, slug in extract_candidates(text):
            key = (ats, slug.lower())
            if key in known or key in seen_this_run:
                continue
            seen_this_run.add(key)
            new_candidates.append({
                "name": slug.replace("-", " ").replace("_", " ").title(),
                "ats": ats,
                "slug": slug,
                "source": f"HN Who is hiring ({title})",
                "first_seen": date.today().isoformat(),
                "why": short_why(text, title_hit),
            })

    print(f"\nNew enrollable companies found (not already known): {len(new_candidates)}")
    for c in new_candidates:
        print(f"  + {c['ats']:15s} {c['slug']:24s} ({c['name']})")

    if args.dry_run:
        print("\n--dry-run: queue not modified.")
        return
    if not new_candidates:
        print("\nNothing new to append.")
        return

    queue.setdefault("pending", []).extend(new_candidates)
    with open(QUEUE_PATH, "w") as f:
        json.dump(queue, f, indent=2)
        f.write("\n")
    print(f"\nAppended {len(new_candidates)} candidates to enrollment_candidates.json → pending.")


if __name__ == "__main__":
    main()
