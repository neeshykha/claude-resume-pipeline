#!/usr/bin/env python3
"""ATS directory-harvest layer: company name -> slug -> live board -> fit-space -> enroll.

Usage:
    .venv/bin/python pipeline/harvest_ats.py --from-pending
    .venv/bin/python pipeline/harvest_ats.py --names "Outreach" "Rippling" "Deel"
    .venv/bin/python pipeline/harvest_ats.py --from-pending --apply
    .venv/bin/python pipeline/harvest_ats.py --prune            # dead-board audit

WHY THIS EXISTS
---------------
CLAUDE.md carried a standing decision from 2026-07-02: a third WitnessAI-class
miss (real company, pollable board, invisible to discovery) triggers building an
ATS directory-harvest layer. That trigger has since fired many times over --
Nexus Cognitive, Docusign, Netflix, and a 2026-07-31 audit that found 35 of 47
well-known scaleups untracked.

The gap was NOT a shortage of company names: Step 1d-2 (LinkedIn), HN hiring,
80,000 Hours, and the board dorks all feed names into `enrollment_candidates.json
-> pending`. The bottleneck was that turning a NAME into a verified slug required
Claude to run a WebSearch per company, which is why Step 1d is capped at 4 per
run and why the queue silently stalled for 26 days.

This script does that resolution deterministically and in bulk: it generates
slug candidates from the company name, probes each supported ATS directly, and
scores the resulting board against the SAME TitleMatcher the poller uses -- so a
company is judged by real tier1/tier2 fit-titles, not by keyword guessing. A full
pass over a dozen names costs seconds and zero WebSearches.

DELIBERATELY NOT A CRAWLER. It never enumerates or brute-forces slug space; it
only tries a handful of deterministic variants of a name someone already
surfaced, with a polite delay between requests.
"""
import argparse
import json
import os
import re
import sys
import time

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST = os.path.join(SCRIPT_DIR, "watchlist_companies.json")
QUEUE = os.path.join(SCRIPT_DIR, "enrollment_candidates.json")

TIMEOUT = 20
DELAY = 0.35          # politeness pause between HTTP calls
UA = {"User-Agent": "Mozilla/5.0 (resume-pipeline-harvest)"}

# Location strings that count as US-reachable. Mirrors the intent of the
# poller's location handling: we only want fit-titles Aneesh could actually take.
US_HINTS = (
    "united states", "usa", "u.s.", "remote", "anywhere", "north america",
    "california", "new york", "texas", "washington", "massachusetts", "illinois",
    "colorado", "georgia", "florida", "utah", "oregon", "arizona", "virginia",
    "boston", "chicago", "atlanta", "denver", "austin", "seattle", "nyc",
    "san francisco", "los angeles", "san diego", "miami", "philadelphia",
)

# Tiers that count as real fit-space for auto-enrollment. tier3/tier4/supplemental
# are deliberately excluded: a company whose only "match" is a weak stretch title
# is not worth a permanent daily poll slot.
STRONG_TIERS = ("tier1_true_match", "tier2_strong_overlap", "tier2c_tooling_systems")


def slug_variants(name: str):
    """Deterministic slug candidates from a company name, most-likely first.

    Handles the real-world cases hit by hand on 2026-07-29..31: Gong's board is
    'gongio', Navan's is still the legacy 'tripactions', Anduril's is
    'andurilindustries', Ironclad's is 'ironcladhq'. Suffix/legal-form stripping
    covers the first class; the rest need a manual slug and are reported as
    unresolved rather than guessed at further.
    """
    n = name.strip().lower()
    n = re.sub(r"[''`]", "", n)
    base = re.sub(r"[^a-z0-9]+", "", n)
    words = re.sub(r"[^a-z0-9 ]+", " ", n).split()
    nospace = "".join(words)
    hyphen = "-".join(words)
    stripped = re.sub(r"(inc|llc|ltd|corp|co|company|labs|technologies|technology)$", "", base)
    cands = [base, nospace, hyphen, stripped, base + "io", base + "hq",
             base + "inc", base + "industries", base + "ai",
             # Rippling-hosted boards commonly append one of these to the bare
             # name rather than using it plain (seen live 2026-08-12:
             # routeware-careers, gaiias-open-positions, nerdio-careers,
             # alongside bare rippling/supper/tixr/kion) -- harmless no-ops
             # against every other ATS, which just 404 on them.
             hyphen + "-careers", hyphen + "-open-positions", hyphen + "-jobs"]
    out, seen = [], set()
    for c in cands:
        if c and len(c) > 1 and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _get(url):
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        return r if r.status_code == 200 else None
    except Exception:
        return None
    finally:
        time.sleep(DELAY)


def probe(ats: str, slug: str):
    """Return [(title, location)] if the board resolves, else None."""
    if ats == "greenhouse":
        r = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
        if not r:
            return None
        return [(j.get("title", ""), (j.get("location") or {}).get("name", ""))
                for j in r.json().get("jobs", [])]
    if ats == "ashby":
        r = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
        if not r:
            return None
        return [(j.get("title", ""), j.get("location", ""))
                for j in r.json().get("jobs", [])]
    if ats == "lever":
        r = _get(f"https://api.lever.co/v0/postings/{slug}?mode=json")
        if not r:
            return None
        return [(j.get("text", ""), (j.get("categories") or {}).get("location", ""))
                for j in r.json()]
    if ats == "workable":
        r = _get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true")
        if not r:
            return None
        return [(j.get("title", ""), j.get("location", "") or j.get("city", ""))
                for j in r.json().get("jobs", [])]
    if ats == "pinpoint":
        r = _get(f"https://{slug}.pinpointhq.com/postings.json")
        if not r:
            return None
        out = []
        for j in r.json().get("data", []):
            loc = j.get("location") or {}
            parts = [p.strip() for p in [loc.get("city"), loc.get("province")] if p and p.strip()]
            label = ", ".join(parts) if parts else (loc.get("name") or "")
            out.append((j.get("title", ""), label))
        return out
    if ats == "rippling":
        # First page only (20 postings) -- enough to judge fit-space; the real
        # daily poll (fetch_rippling in poll_ats.py) paginates fully once a
        # company is actually enrolled.
        r = _get(f"https://ats.rippling.com/{slug}/jobs")
        if not r:
            return None
        m = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            r.text, re.DOTALL)
        if not m:
            return None
        try:
            next_data = json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            return None
        queries = (next_data.get("props", {}).get("pageProps", {})
                   .get("dehydratedState", {}).get("queries", []))
        job_query = next(
            (qy for qy in queries
             if isinstance(qy.get("queryKey"), list) and "job-posts" in qy["queryKey"]),
            None)
        if not job_query:
            return None
        items = job_query.get("state", {}).get("data", {}).get("items", []) or []
        out = []
        for j in items:
            locs = j.get("locations") or []
            names = [l.get("name") for l in locs if l.get("name")]
            out.append((j.get("name", ""), ", ".join(names)))
        return out
    return None


def us_reachable(loc: str) -> bool:
    return any(h in (loc or "").lower() for h in US_HINTS)


def load_known():
    wl = json.load(open(WATCHLIST, encoding="utf-8"))
    q = json.load(open(QUEUE, encoding="utf-8"))
    names = {c["name"].lower() for c in wl["companies"]}
    pairs = {(c.get("ats"), (c.get("slug") or "").lower())
             for c in wl["companies"] if c.get("ats") and c.get("slug")}
    # Deliberately excludes "pending": --from-pending sources its targets from
    # that same bucket, so including it here made every pending entry match its
    # own name and get skipped as "already known" -- --from-pending was a silent
    # no-op until this fix (found 2026-08-01, targets always skipped in the same run
    # that built them).
    for bucket in ("enrolled", "rejected"):
        for e in q.get(bucket, []):
            if e.get("name"):
                names.add(str(e["name"]).lower())
    return wl, q, names, pairs


def assess(name, matcher, hard_excluded, known_pairs):
    """Resolve a company to (ats, slug, strong_hits, total_jobs) or a reason."""
    for slug in slug_variants(name):
        for ats in ("greenhouse", "ashby", "lever", "workable", "pinpoint", "rippling"):
            if (ats, slug) in known_pairs:
                continue
            jobs = probe(ats, slug)
            if jobs is None:
                continue
            if not jobs:
                # Board resolves but is empty. Keep looking under other slugs
                # before concluding anything; an empty board is weak evidence
                # that we found the right company at all.
                continue
            strong = []
            for title, loc in jobs:
                if hard_excluded(title):
                    continue
                m = matcher.match_exact(title)
                if m and m[0] in STRONG_TIERS and us_reachable(loc):
                    strong.append((title, loc, m[0]))
            return {"ats": ats, "slug": slug, "total": len(jobs), "strong": strong}
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", nargs="*", default=[])
    ap.add_argument("--from-pending", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--prune", action="store_true")
    args = ap.parse_args()

    sys.path.insert(0, SCRIPT_DIR)
    import poll_ats as P

    wl, q, known_names, known_pairs = load_known()
    P._init_config(wl)
    matcher = P.TitleMatcher(wl)

    if args.prune:
        return prune(wl, matcher, P.title_hard_excluded)

    targets = list(args.names)
    if args.from_pending:
        targets += [e["name"] for e in q.get("pending", []) if e.get("name")]
    if not targets:
        print("nothing to do: pass --names or --from-pending")
        return 0

    enrollable, no_board, no_fit, skipped = [], [], [], []
    for name in targets:
        if name.lower() in known_names and not args.names:
            skipped.append(name)
            continue
        res = assess(name, matcher, P.title_hard_excluded, known_pairs)
        if res is None:
            no_board.append(name)
            print(f"  [--] {name:24s} no board resolved from name variants")
            continue
        if not res["strong"]:
            no_fit.append((name, res))
            print(f"  [..] {name:24s} {res['ats']}/{res['slug']:20s} "
                  f"{res['total']:>4} jobs, 0 US fit-titles")
            continue
        enrollable.append((name, res))
        print(f"  [OK] {name:24s} {res['ats']}/{res['slug']:20s} "
              f"{res['total']:>4} jobs, {len(res['strong'])} US fit-titles")
        for t, l, tier in res["strong"][:3]:
            print(f"         [{tier[:5]}] {t[:46]:46s} | {str(l)[:24]}")

    print(f"\nenrollable={len(enrollable)} no_fit={len(no_fit)} "
          f"no_board={len(no_board)} already_known_skipped={len(skipped)}")

    if not args.apply:
        print("dry run; re-run with --apply to enroll")
        return 0

    today = __import__("datetime").date.today().isoformat()
    for name, res in enrollable:
        wl["companies"].append({
            "name": name, "ats": res["ats"], "slug": res["slug"],
            "priority": "low",
            "enrolled_date": today,
            "enrolled_via": "harvest_ats.py automated slug resolution",
            "reason": (f"Auto-enrolled by the ATS harvest layer. Board verified live "
                       f"({res['total']} jobs) with {len(res['strong'])} US-reachable "
                       f"tier1/tier2/tier2c fit-titles at harvest time, e.g. "
                       f"{res['strong'][0][0][:60]!r}. Enrolled at LOW priority by "
                       f"design: auto-enrollment should not outrank hand-vetted "
                       f"companies. Prune via --prune if the board goes dead or "
                       f"fit-space-empty."),
        })
        q.setdefault("enrolled", []).append(
            {"name": name, "ats": res["ats"], "slug": res["slug"],
             "enrolled_date": today, "via": "harvest_ats.py"})
    for name, res in no_fit:
        q.setdefault("rejected", []).append(
            {"name": name, "ats": res["ats"], "slug": res["slug"],
             "rejected_date": today,
             "reason": (f"Board resolves and is live ({res['total']} jobs) but ZERO "
                        f"US-reachable tier1/tier2/tier2c titles at harvest time. "
                        f"Rejected on fit-space, not pollability -- recheck if the "
                        f"company resurfaces."),
             "recheck_if_resurfaced": True})
    for name in no_board:
        q.setdefault("rejected", []).append(
            {"name": name, "ats": None, "slug": None, "rejected_date": today,
             "reason": ("No board resolved from deterministic name-variant slugs across "
                        "Greenhouse/Ashby/Lever/Workable. May still be pollable under a "
                        "non-obvious slug or on Workday: worth one manual "
                        "site:myworkdayjobs.com search if the company matters."),
             "recheck_if_resurfaced": True})

    handled = {n.lower() for n, _ in enrollable} | {n.lower() for n, _ in no_fit} | {n.lower() for n in no_board}
    q["pending"] = [e for e in q.get("pending", [])
                    if str(e.get("name", "")).lower() not in handled]

    for path, data in ((WATCHLIST, wl), (QUEUE, q)):
        tmp = path + ".tmp"
        json.dump(data, open(tmp, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    print(f"\nenrolled {len(enrollable)}, rejected {len(no_fit) + len(no_board)}; "
          f"watchlist now {len(wl['companies'])}")
    return 0


def prune(wl, matcher, hard_excluded):
    """Dead-board audit: report enrolled companies whose board 404s or is empty."""
    dead, empty, ok = [], [], 0
    for c in wl["companies"]:
        ats, slug = c.get("ats"), c.get("slug")
        if ats not in ("greenhouse", "ashby", "lever", "workable") or not slug:
            continue  # Workday and custom hosts are out of scope for this audit
        jobs = probe(ats, slug)
        if jobs is None:
            dead.append(c["name"])
        elif not jobs:
            empty.append(c["name"])
        else:
            ok += 1
    print(f"live={ok} dead(404)={len(dead)} empty={len(empty)}")
    if dead:
        print("DEAD:", ", ".join(dead))
    if empty:
        print("EMPTY:", ", ".join(empty))
    print("\nReport only; no changes written. Set board_status by hand after review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
