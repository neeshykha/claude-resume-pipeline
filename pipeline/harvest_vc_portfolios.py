"""Harvest Atlanta-area VC / accelerator portfolio company NAMES into the
enrollment queue.

    .venv/bin/python pipeline/harvest_vc_portfolios.py            # dry run
    .venv/bin/python pipeline/harvest_vc_portfolios.py --apply    # write to pending
    .venv/bin/python pipeline/harvest_vc_portfolios.py --source "BIP Ventures"

WHY THIS EXISTS (added 2026-08-25)
----------------------------------
Atlanta coverage is the pipeline's biggest structural gap: only ~19 of 319
watchlist companies are Atlanta-HQ, and the poller is company-first, so Atlanta
coverage is capped at (enrolled Atlanta companies) x (their open fit roles).
Nothing in the system can ask "what is open in Atlanta right now."

Two other pathways were investigated and rejected first, both recorded here so
they are not re-attempted:

  * Atlanta-local job SITES (Built In Atlanta, Hypepotamus, Atlanta Tech
    Village) have no public JSON API. Built In's /jobs/atlanta.json returns the
    SPA shell; Hypepotamus and ATV expose no WP JSON job endpoints; ATV's member
    directory 404s outright. Verified 2026-08-23 and 2026-08-25.
  * PEO-hosted boards (Insperity/Avature, TriNet) are enumerable but ANONYMOUS.
    The Insperity req that surfaced Engagifii never names Engagifii anywhere in
    41KB of HTML. Without an employer you cannot score company bonuses, check
    the company cap, dedupe, or do diligence -- 60 of Engagifii's 118 points
    came from knowing who it was. Rejected 2026-08-25.

VC and accelerator portfolios are the right shape because they output COMPANY
NAMES, which is the one input the existing machinery already consumes: a name
goes to enrollment_candidates.json -> pending, and harvest_ats.py turns it into
either a resolved board polled daily forever or a reasoned rejection. Zero new
downstream infrastructure. Portfolios also converge (they change a few times a
year), so this belongs on a MONTHLY cadence, not daily.

Proof the aim is right: BIP Ventures' portfolio contains Crescerance (parent of
Engagifii, the 118-scoring Atlanta role that arrived by recruiter because no
automated channel could see it), plus Cloverly, FinQuery, and GoFan/PlayOn --
all already on the watchlist.

EXPECTED YIELD, so nobody over-reads a thin run: of ~105 BIP names, maybe 30-40
are Atlanta, roughly half of those run a supported ATS, and roughly half of
those have a fit-title open at any moment. Five to ten enrollments on a first
run and a trickle after. Companies too small to run any ATS (Engagifii's case)
land in `rejected` as unpollable, which is still strictly better than invisible:
weekly_channel_report.py surfaces those as a manual punch list.
"""
import argparse
import html as html_mod
import json
import os
import re
import sys

import requests

from check_company import hit, load_known

HERE = os.path.dirname(os.path.abspath(__file__))
ENROLLMENT = os.path.join(HERE, "enrollment_candidates.json")

TIMEOUT = 30
UA = {"User-Agent": "Mozilla/5.0 (resume-pipeline)"}

# Cap per run, same spirit as the LinkedIn harvest's 15/run cap: keeps cost flat
# no matter how large a portfolio turns out to be. Anything over the cap is
# reported and picked up next month.
MAX_NEW_PER_RUN = 40

# Labels that are page furniture, team members, or filter values rather than
# portfolio companies. Matched case-insensitively against the whole name.
NOISE = {
    "team lead", "logo", "image", "read more", "learn more", "view all", "next",
    "previous", "close", "menu", "search", "home", "about", "contact", "news",
    "events", "apply", "programs", "team", "sector", "stage", "forms",
    "subscribe", "meet our", "everything you need", "our", "explore",
    "resources", "stay connected", "portfolio", "companies", "all",
    "seed", "series a", "series b", "growth", "scale", "venture",
}


def clean_name(raw: str) -> str:
    """Normalize a scraped label into a company name harvest_ats.py can resolve.

    Portfolio grids annotate names inline -- "FinQuery (Formerly LeaseQuery)",
    "GoFan (Acq. by PlayOn!)", "Gigantik (Formerly GigLabs)" are all real
    examples from BIP. The parenthetical breaks slug generation, so strip it;
    the former name is interesting to a human but useless to a slug prober.
    """
    n = html_mod.unescape(raw or "").strip()
    n = re.sub(r"\s*\((?:formerly|acq\.?(?:uired)? by|now|fka|dba)[^)]*\)", "", n, flags=re.I)
    n = re.sub(r"\s+", " ", n).strip(" \t\r\n-|,;:")
    return n


def looks_like_person(name: str) -> bool:
    """Heuristic filter for team-member names leaking out of a sibling grid.

    Deliberately conservative: only two-word all-alphabetic names where neither
    word carries a company-ish token. "Case Status" and "Copper Banking" are
    real BIP companies and must survive this.
    """
    parts = name.split()
    if len(parts) != 2 or not all(p.isalpha() for p in parts):
        return False
    corp = {"health", "labs", "bank", "banking", "data", "cloud", "care", "tech",
            "systems", "status", "learning", "robotics", "energy", "media",
            "logistics", "security", "software", "digital", "medical", "capital"}
    return not any(p.lower() in corp for p in parts)


def _fetch(url: str) -> str:
    r = requests.get(url, headers=UA, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    return r.text


# --------------------------------------------------------------------------
# Per-source extractors. Each takes page HTML and returns raw candidate labels.
# Scraping is inherently per-site and fragile; every extractor is wrapped so one
# broken layout degrades that source only, never the run.
# --------------------------------------------------------------------------

def extract_bip(body: str) -> list[str]:
    """BIP Ventures / Panoramic (Atlanta, B2B software since 2007).

    Webflow. The page holds THREE w-dyn-list collections: two are filter
    dropdowns (sector, stage) and one is the company grid. Scoping to the grid
    matters -- an unscoped split also picks up the team collection, which is how
    an early pass produced "Ben Carraway" and "Mark Buffington" as companies.
    """
    anchor = body.find("portfolio_list_grid--wrapper")
    if anchor == -1:
        return []
    grid = body[anchor:]
    out = []
    for block in re.split(r"w-dyn-item", grid)[1:]:
        chunk = block[:1500]
        for pat in (r'alt="([^"]{2,60})"',
                    r">([A-Z][A-Za-z0-9&.\'\-\+ ]{2,50})</h\d>",
                    r"<div[^>]*>\s*([A-Z][A-Za-z0-9&.\'\-\+ ]{2,50})\s*</div>"):
            m = re.search(pat, chunk)
            if m:
                out.append(m.group(1))
                break
    return out


def extract_venture_atlanta(body: str) -> list[str]:
    """Venture Atlanta -- companies that have presented at the conference.

    Curated list of Southeast startups actively raising, which correlates with
    hiring. Names sit in heading tags.
    """
    return re.findall(r"<h[2-5][^>]*>\s*([A-Z][A-Za-z0-9&.,\'\-\+ ]{2,50})\s*</h[2-5]>", body)


def extract_atdc_announcement(body: str) -> list[str]:
    """ATDC (Georgia Tech's incubator) graduating-class announcements.

    The live members directory at /startup-companies-atdc-active-members/ is a
    WordPress admin-ajax grid: only part of its 141 companies is in the initial
    HTML ("Cloverly" is present, "Slip Robotics" is not). Reverse-engineering
    that endpoint is fragile, so this reads the annual class announcements
    instead -- static prose pages that name each cohort. It degrades gracefully:
    a reformatted year loses that year, not the source.
    """
    names = []
    names += re.findall(r"<strong>\s*([A-Z][A-Za-z0-9&.,\'\-\+ ]{2,50})\s*</strong>", body)
    names += re.findall(r"<li[^>]*>\s*<b>\s*([A-Z][A-Za-z0-9&.,\'\-\+ ]{2,50})\s*</b>", body)
    names += re.findall(r"<h[3-5][^>]*>\s*([A-Z][A-Za-z0-9&.,\'\-\+ ]{2,50})\s*</h[3-5]>", body)
    return names


SOURCES = [
    {
        "name": "BIP Ventures",
        "url": "https://www.bipventures.vc/portfolio",
        "extract": extract_bip,
        "why": "BIP Ventures portfolio (Atlanta B2B software VC, investing since 2007)",
    },
    {
        "name": "Venture Atlanta",
        "url": "https://www.ventureatlanta.org/companies/",
        "extract": extract_venture_atlanta,
        "why": "Venture Atlanta presenting companies (Southeast startups actively raising)",
    },
]

# ---------------------------------------------------------------------------
# DISABLED, with the dead ends recorded so they are not re-attempted blind.
#
# ATDC (Georgia Tech's incubator, 141 active members) is the densest Atlanta
# list that exists and is still the most valuable target here, but nothing
# reachable actually serves it:
#   * /startup-companies-atdc-active-members/ is a WordPress admin-ajax grid.
#     Only part of the list is in the initial 405KB ("Cloverly" present, "Slip
#     Robotics" and "Strados Labs" absent).
#   * The graduating-class announcement pages return 200 and 224KB, but the
#     article body is not in the served HTML -- stripping tags yields only site
#     navigation. extract_atdc_announcement below returns 0 against it, which is
#     why this source is disabled rather than shipped broken.
#   * resumes.ei2.info, ATDC's own job board, IS server-rendered and trivially
#     scrapable, and is useless: two live jobs, and its category list
#     (development, design, marketing, QA, R&D) has no support, CS, or
#     operations category at all.
# NEXT THING TO TRY: the site nav exposes "Portfolio Companies > Alumni", which
# may be a static list where Active Members is not. Untested as of 2026-08-25.
#
# Atlanta Tech Village (300+ members) is a harder dead end: /community,
# /community/graduates, and /community/sponsors all 404 despite being indexed.
# ---------------------------------------------------------------------------
DISABLED_SOURCES = [
    {
        "name": "ATDC Class of 2022",
        "url": "https://atdc.org/the-advanced-technology-development-center-announces-atdc-class-of-2022-graduates/",
        "extract": extract_atdc_announcement,
        "why": "ATDC graduating class (Georgia Tech incubator, Atlanta)",
    },
]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="write new names to enrollment_candidates.json -> pending")
    ap.add_argument("--source", action="append",
                    help="run only this source (repeatable, exact name)")
    args = ap.parse_args()

    known = load_known()
    with open(ENROLLMENT) as f:
        enrollment = json.load(f)
    pending_names = [e.get("name", "") for e in enrollment.get("pending", [])]

    selected = [s for s in SOURCES if not args.source or s["name"] in args.source]
    if not selected:
        print("no source matched --source"); sys.exit(2)

    new: list[tuple[str, str]] = []
    seen_this_run: set[str] = set()

    for src in selected:
        try:
            body = _fetch(src["url"])
            raw = src["extract"](body)
        except Exception as e:
            print(f"  [!!] {src['name']:<22} {type(e).__name__}: {str(e)[:60]}")
            continue

        cleaned, dropped_noise, dropped_person, already = [], 0, 0, 0
        for r in raw:
            n = clean_name(r)
            if not n or n.lower() in NOISE or len(n) < 3:
                dropped_noise += 1
                continue
            if looks_like_person(n):
                dropped_person += 1
                continue
            key = "".join(c for c in n.lower() if c.isalnum())
            if key in seen_this_run:
                continue
            seen_this_run.add(key)
            if any(hit(n, k) for k in known) or any(hit(n, p) for p in pending_names):
                already += 1
                continue
            cleaned.append(n)

        print(f"  [ok] {src['name']:<22} {len(raw):>3} raw -> {len(cleaned):>3} new "
              f"({already} already known, {dropped_noise} noise, {dropped_person} person-like)")
        for n in cleaned:
            new.append((n, src["why"]))

    print()
    if not new:
        print("no new companies found.")
        return

    capped = new[:MAX_NEW_PER_RUN]
    print(f"NEW COMPANIES: {len(new)}" +
          (f" (capping at {MAX_NEW_PER_RUN}, {len(new) - len(capped)} carry to next run)"
           if len(new) > MAX_NEW_PER_RUN else ""))
    for i in range(0, len(capped), 5):
        print("   " + " | ".join(n for n, _ in capped[i:i + 5]))

    if not args.apply:
        print()
        print("dry run; re-run with --apply to append these to pending")
        return

    from datetime import date
    today = date.today().isoformat()
    for n, why in capped:
        enrollment["pending"].append({
            "name": n,
            "ats": None,
            "slug": None,
            "source": "VC/accelerator portfolio harvest",
            "first_seen": today,
            "why": why,
            "needs_ats_resolution": True,
        })
    tmp = ENROLLMENT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(enrollment, f, indent=2)
        f.write("\n")
    os.replace(tmp, ENROLLMENT)
    print()
    print(f"appended {len(capped)} to pending (now {len(enrollment['pending'])}). "
          f"Run harvest_ats.py --from-pending next.")


if __name__ == "__main__":
    main()
