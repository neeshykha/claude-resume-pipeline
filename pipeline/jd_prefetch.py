#!/usr/bin/env python3
"""Fetch every shortlist JD up front, cache the text, and batch it for screen workers.

Usage:
    .venv/bin/python pipeline/jd_prefetch.py                    # today's ats_hits
    .venv/bin/python pipeline/jd_prefetch.py --date 2026-09-24
    .venv/bin/python pipeline/jd_prefetch.py --batch-size 8

Reads pipeline/jobs/ats_hits_<date>.json and fetches, with fetch_jd.fetch():
  - every `matched` entry (the shortlist, tier1 guarantees included),
  - every `borderline` entry flagged ai_wildcard (Step 2a-pre already requires
    reading all of them),
  - `near_window` entries whose listing location could plausibly be Atlanta or
    remote US. The rest of near_window stays a one-line FYI, as before.

Writes pipeline/jobs/jd_cache/<date>/NN_<slug>.txt (header + full body) and
pipeline/jobs/jd_cache/<date>/manifest.json, then prints a short summary and
the batch list. Always exits 0 unless the hits file is missing (exit 1).

Why this exists (added 2026-09-24). The run has one context window, so JDs were
read one at a time and only for the 3-4 roles already picked from listing data:
on 2026-09-24, 924 title matches -> 49 shortlisted -> 4 tailored, and most of
the 49 were never read at all. Fetching is deterministic, so it belongs in
Python; READING the text is what the Step 2-JD screen workers do, one batch
each, in their own context windows. The orchestrator then scores from compact
cards instead of raw JDs. Nothing here scores, filters, or decides anything.

Also marks entries whose URL is already in outcomes.csv (with its stage), so a
worker is not spent on a role Aneesh already applied to or was rejected from.
"""
import argparse
import csv
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fetch_jd  # noqa: E402

JOBS = os.path.join(HERE, "jobs")
OUTCOMES = os.path.join(HERE, "outcomes.csv")
MAX_BODY = 20000
WORKERS = 6
PER_ATS = 2   # concurrent requests per ATS, so one host never sees a burst

# Loose on purpose: this only decides whether a near_window role gets READ.
# Step 2b's hard filter still makes the real location call from the JD body.
PLAUSIBLE_LOC = re.compile(
    r"remote|atlanta|alpharetta|georgia|\bga\b|anywhere|"
    r"^\s*(us|usa|u\.s\.|united states( of america)?)\s*$",
    re.I)


def slugify(s, n=40):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:n] or "x"


def outcome_stages():
    stages = {}
    try:
        with open(OUTCOMES, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("url"):
                    stages[r["url"].strip()] = (r.get("stage") or "").strip()
    except OSError:
        pass
    return stages


def candidates(hits):
    out, seen = [], set()

    def add(e, source):
        url = e.get("apply_url") or e.get("url")
        if not url or url in seen:
            return
        seen.add(url)
        out.append({
            "source": source,
            "company": e.get("company"),
            "title": e.get("title"),
            "listing_location": e.get("location"),
            "url": url,
            "ats": e.get("ats"),
            "pre_score": e.get("pre_score"),
            "title_tier": e.get("title_tier"),
            "posted_date": e.get("posted_date"),
            "jd_verification_required": bool(e.get("jd_verification_required")),
            "provenance": e.get("provenance") or [],
        })

    for e in hits.get("matched") or []:
        add(e, "matched")
    for e in hits.get("borderline") or []:
        if e.get("ai_wildcard"):
            add(e, "ai_wildcard")
    for e in hits.get("near_window") or []:
        if PLAUSIBLE_LOC.search(e.get("location") or ""):
            add(e, "near_window")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--batch-size", type=int, default=8)
    args = ap.parse_args()

    hits_path = os.path.join(JOBS, f"ats_hits_{args.date}.json")
    try:
        with open(hits_path, encoding="utf-8") as f:
            hits = json.load(f)
    except OSError as exc:
        print(f"jd_prefetch: FAILED, cannot read {hits_path}: {exc}")
        return 1

    cache = os.path.join(JOBS, "jd_cache", args.date)
    os.makedirs(cache, exist_ok=True)
    cands = candidates(hits)
    stages = outcome_stages()

    locks = {}
    guard = threading.Lock()

    def ats_lock(ats):
        with guard:
            return locks.setdefault(ats or "?", threading.Semaphore(PER_ATS))

    def work(i_c):
        i, c = i_c
        c["idx"] = i
        c["outcomes_stage"] = stages.get(c["url"], "")
        if c["outcomes_stage"] in ("applied", "rejected", "closed"):
            c["status"] = f"skipped: already {c['outcomes_stage']}"
            return c
        with ats_lock(c["ats"]):
            rec = fetch_jd.fetch(c["url"])
        if rec.get("error"):
            c["status"] = "error"
            c["error"] = rec["error"][:300]
            return c
        body = rec.get("body") or ""
        name = f"{i:02d}_{slugify(c['company'], 20)}_{slugify(c['title'], 40)}.txt"
        path = os.path.join(cache, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"COMPANY : {c['company']}\n")
            f.write(f"TITLE   : {rec.get('title') or c['title']}\n")
            f.write(f"URL     : {c['url']}\n")
            f.write(f"ATS     : {rec.get('ats')}\n")
            f.write(f"LOCATION: {rec.get('location')}   remote={rec.get('remote')}\n")
            f.write(f"LISTING LOCATION: {c['listing_location']}\n")
            f.write(f"POSTED  : {rec.get('posted')}\n")
            f.write(f"SALARY  : {rec.get('salary')}\n")
            f.write("-" * 70 + "\n")
            f.write(body[:MAX_BODY])
            if len(body) > MAX_BODY:
                f.write(f"\n[truncated at {MAX_BODY} of {len(body)} chars]\n")
        c.update(status="ok", file=path, chars=len(body),
                 jd_salary=rec.get("salary"), jd_location=rec.get("location"),
                 jd_remote=rec.get("remote"))
        if len(body) < 400:
            c["status"] = "thin"   # title-only page; the orchestrator decides
        return c

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        done = list(pool.map(work, enumerate(cands, 1)))

    readable = [c for c in done if c["status"] in ("ok", "thin")]
    # Highest pre_score first, so batch 1 holds the likeliest picks and a run
    # that has to fall back to reading inline still reads the right ones first.
    readable.sort(key=lambda c: -(c.get("pre_score") or 0))
    batches = [readable[i:i + args.batch_size]
               for i in range(0, len(readable), args.batch_size)]
    for n, b in enumerate(batches, 1):
        for c in b:
            c["batch"] = n

    manifest = {
        "date": args.date,
        "hits_file": hits_path,
        "counts": {
            "candidates": len(done),
            "by_source": {s: sum(1 for c in done if c["source"] == s)
                          for s in ("matched", "ai_wildcard", "near_window")},
            "fetched": sum(1 for c in done if c["status"] == "ok"),
            "thin": sum(1 for c in done if c["status"] == "thin"),
            "errors": sum(1 for c in done if c["status"] == "error"),
            "skipped_known": sum(1 for c in done if c["status"].startswith("skipped")),
            "batches": len(batches),
        },
        "batches": [[c["file"] for c in b] for b in batches],
        "entries": done,
    }
    # One file per batch. Workers were first told to take manifest
    # batches[N-1]; on the 2026-09-24 trial one of ten read the wrong index, so
    # a batch was screened twice and another never. A named file cannot be
    # miscounted.
    for n, b in enumerate(batches, 1):
        with open(os.path.join(cache, f"batch_{n:02d}.json"), "w", encoding="utf-8") as f:
            json.dump([c["file"] for c in b], f, indent=1)
            f.write("\n")
    mpath = os.path.join(cache, "manifest.json")
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
        f.write("\n")

    k = manifest["counts"]
    print(f"jd_prefetch: {k['candidates']} candidates "
          f"({k['by_source']['matched']} matched, {k['by_source']['ai_wildcard']} ai_wildcard, "
          f"{k['by_source']['near_window']} near_window); fetched {k['fetched']}, "
          f"thin {k['thin']}, errors {k['errors']}, already-known {k['skipped_known']}; "
          f"{k['batches']} batches")
    print(f"manifest: {mpath}")
    for c in done:
        if c["status"] == "error":
            print(f"  ERROR  {c['company']}: {c['title']} ({c['ats']}) -- {c['error'][:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
