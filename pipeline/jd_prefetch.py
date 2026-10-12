#!/usr/bin/env python3
"""Fetch every shortlist JD up front, cache the text, and batch it for screen workers.

Usage:
    .venv/bin/python pipeline/jd_prefetch.py                    # today's ats_hits
    .venv/bin/python pipeline/jd_prefetch.py --date 2026-09-24
    .venv/bin/python pipeline/jd_prefetch.py --batch-size 8
    .venv/bin/python pipeline/jd_prefetch.py --no-reuse         # every JD to a worker

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

Card reuse (added 2026-10-12). Most of a day's shortlist is yesterday's
shortlist: across the 2026-09-24..10-09 cache dirs, 784 times a URL was fetched
on two runs in a row, and 762 of those files came back byte for byte the same.
A worker reading the same text writes the same card, so after fetching, each JD
is checked against the cards earlier runs left in jd_cache/<YYYY-MM-DD>/. Same
URL, same text, card readable, and a worker read it recently enough (see
max_age_days: REUSE_MAX_AGE_DAYS plus a few days fixed per URL, so postings
first read on the same run don't all come due together): the card is copied
into today's cards_batch_cached.json
(`file` pointed at today's txt, `reused_from` = the day a worker read it) and
the JD is left out of the batches. It stays in manifest entries, so
jd_screen_table.py joins it like any other card. Nothing is stored between
runs; the earlier cache dirs are the only state. `reused_from` is carried
forward unchanged on every later reuse, so a posting gets a fresh read once the
original is too old however many days it has been reused. --no-reuse sends
everything to a worker; use it once after jd_screen_worker.md or the card
schema changes, because an old card is only as good as the brief it was
written under. Reuse can only take work away: any bad or missing old dir, card
file, or card is skipped, and any failure in the reuse pass reads everything.
"""
import argparse
import csv
import glob
import hashlib
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
RULE = "-" * 70   # divides the header from the JD body in a cached txt

REUSE_LOOKBACK_DAYS = 21   # how far back to look for an earlier card
REUSE_MAX_AGE_DAYS = 14    # a worker's read stands at least this long, then it is redone
# ...plus 0 to this many days, fixed per URL. Replaying 2026-09-24..10-09 with a flat
# 14 days, everything first read on 09-24 came due on the same run and that day's
# reuse fell from about 75 cards to 54. Spreading the due dates flattens that.
REUSE_JITTER_DAYS = 6
# jd_screen_table.py globs cards_batch_*.json, so this name needs no change there.
REUSED_CARDS = "cards_batch_cached.json"
DAY_DIR = re.compile(r"\d{4}-\d{2}-\d{2}")   # main-run dirs only, not <date>_linkedin
# Header lines left out of the reuse hash. POSTED moves when an ATS re-stamps a
# posting whose text did not change, and no card field holds it; URL is the
# index key already. The other header lines (title, location, salary) are facts
# a worker quotes, so a change in one of them is a reason to read again. The
# header carries no fetch date, rank, pre_score, or source: the rank is only in
# the file NAME, which is why the hash is of the content and never the path.
HASH_SKIP = {"URL", "POSTED"}

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


def norm_url(u):
    return (u or "").strip().rstrip("/").lower()


def max_age_days(url):
    """How long a worker's read of this URL stands. Stable for a URL, spread across URLs."""
    spread = int(hashlib.sha256(norm_url(url).encode("utf-8")).hexdigest(), 16) % (REUSE_JITTER_DAYS + 1)
    return REUSE_MAX_AGE_DAYS + spread


def parse_day(s):
    try:
        return date.fromisoformat(s) if isinstance(s, str) and DAY_DIR.fullmatch(s) else None
    except ValueError:
        return None


def text_hash(path):
    """Hash of a cached JD as a worker reads it, or None if it cannot be read.

    Covers the body and every header line a card draws on; leaves out HASH_SKIP
    and collapses whitespace, so a re-stamped or re-wrapped posting still
    matches. A file with no header (not written by this script) hashes whole.
    """
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except (OSError, ValueError):
        return None
    head, sep, body = text.partition("\n" + RULE + "\n")
    if sep:
        kept = [ln for ln in head.splitlines()
                if ln.split(":", 1)[0].strip() not in HASH_SKIP]
        text = "\n".join(kept) + "\n" + body
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


def reuse_index(cache_root, today, lookback=REUSE_LOOKBACK_DAYS):
    """{normalized url: (text hash, card, day a worker read it)} from earlier runs.

    Walks the main-run dirs dated within `lookback` days before `today`, oldest
    first, so the newest card for a URL wins. The read day is the dir's date
    for a card a worker wrote there and `reused_from` for one this script
    copied in. Never raises: anything unreadable or misshapen is skipped.
    """
    index = {}
    run_day = parse_day(today)
    try:
        names = sorted(os.listdir(cache_root))
    except OSError:
        return index
    for name in names:
        day = parse_day(name)
        if not run_day or not day or not 0 < (run_day - day).days <= lookback:
            continue
        d = os.path.join(cache_root, name)
        for p in sorted(glob.glob(os.path.join(d, "cards_batch_*.json"))):
            try:
                with open(p, encoding="utf-8") as f:
                    cards = json.load(f)
            except (OSError, ValueError):
                continue
            for card in cards if isinstance(cards, list) else []:
                if not isinstance(card, dict) or not isinstance(card.get("file"), str):
                    continue
                url = norm_url(card.get("url") if isinstance(card.get("url"), str) else "")
                # A bad reused_from drops the card rather than falling back to
                # the dir's date, which would restart the clock.
                read_day = parse_day(card["reused_from"]) if "reused_from" in card else day
                # The txt is looked up beside the card, by name: the card's own
                # path is whatever the worker copied and may be from elsewhere.
                h = text_hash(os.path.join(d, os.path.basename(card["file"])))
                if url and read_day and h:
                    index[url] = (h, card, read_day)
    return index


def carded_today(cache):
    """Normalized URLs a WORKER carded in this run date's dir (the reused file excluded)."""
    urls = set()
    for p in glob.glob(os.path.join(cache, "cards_batch_*.json")):
        if os.path.basename(p) == REUSED_CARDS:
            continue
        try:
            with open(p, encoding="utf-8") as f:
                cards = json.load(f)
        except (OSError, ValueError):
            continue
        for card in cards if isinstance(cards, list) else []:
            if isinstance(card, dict) and isinstance(card.get("url"), str):
                urls.add(norm_url(card["url"]))
    return urls


def reuse_card(index, url, path, today):
    """A copy of the earlier card for this JD, pointed at today's txt, or None."""
    hit = index.get(norm_url(url))
    run_day = parse_day(today)
    if not hit or not run_day:
        return None
    h, card, read_day = hit
    if card.get("read_ok") is not True:
        return None
    if not 0 < (run_day - read_day).days <= max_age_days(url):
        return None
    if h != text_hash(path):
        return None
    out = dict(card)
    out["file"] = path
    out["reused_from"] = read_day.isoformat()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--no-reuse", action="store_true",
                    help="send every JD to a worker, even one with a reusable earlier card")
    args = ap.parse_args(argv)

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
            f.write(RULE + "\n")
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

    # Card reuse: see the module docstring. Whatever goes wrong in here, the
    # answer is to read everything, which is what the run did before.
    reused, reuse_note = [], ""
    if not args.no_reuse:
        try:
            index = reuse_index(os.path.join(JOBS, "jd_cache"), args.date)
            fresh = carded_today(cache)
            for c in readable:
                if norm_url(c["url"]) in fresh:
                    # A worker already read this posting on THIS date (a second run the
                    # same day, typically after --no-reuse). Its card is newer than
                    # anything the index holds, so the JD goes back to a worker rather
                    # than having an older read copied over it.
                    continue
                card = reuse_card(index, c["url"], c["file"], args.date)
                if card:
                    reused.append((c, card))
        except Exception as exc:                      # noqa: BLE001
            reused, reuse_note = [], f"{type(exc).__name__}: {exc}"
    # Written on every run, empty included. A second run on the same date
    # (--no-reuse after a normal one, say) must not leave the first run's
    # copies behind: the table reads this file after the workers' files, so a
    # stale copy would override a fresh card for the same JD.
    try:
        with open(os.path.join(cache, REUSED_CARDS), "w", encoding="utf-8") as f:
            json.dump([card for _, card in reused], f, indent=1)
            f.write("\n")
    except (OSError, TypeError, ValueError) as exc:
        reused, reuse_note = [], f"{type(exc).__name__}: {exc}"
    for c, card in reused:
        c["reused_from"] = card["reused_from"]
    to_read = [c for c in readable if "reused_from" not in c]

    # Highest pre_score first, so batch 1 holds the likeliest picks and a run
    # that has to fall back to reading inline still reads the right ones first.
    to_read.sort(key=lambda c: -(c.get("pre_score") or 0))
    batches = [to_read[i:i + args.batch_size]
               for i in range(0, len(to_read), args.batch_size)]
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
            "reused": len(reused),
            "to_read": len(to_read),
        },
        "batches": [[c["file"] for c in b] for b in batches],
        "entries": done,
    }
    # One file per batch. Workers were first told to take manifest
    # batches[N-1]; on the 2026-09-24 trial one of ten read the wrong index, so
    # a batch was screened twice and another never. A named file cannot be
    # miscounted.
    # An earlier run on this date may have written more batch files than this one
    # will (with reuse, a second run usually has fewer). jd_screen_table.py globs
    # them to decide what to RE-DISPATCH, so leftovers would send workers after
    # batches that no longer exist. Only this script's own batch files are removed;
    # the workers' cards_batch_*.json are never touched.
    for old in glob.glob(os.path.join(cache, "batch_[0-9]*.json")):
        try:
            os.remove(old)
        except OSError:
            pass
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
          f"{k['batches']} batches; reused {k['reused']}, to read {k['to_read']}"
          + (" (--no-reuse)" if args.no_reuse else ""))
    print(f"manifest: {mpath}")
    if reuse_note:
        print(f"  REUSE OFF  every JD goes to a worker -- {reuse_note[:200]}")
    for c in done:
        if c["status"] == "error":
            print(f"  ERROR  {c['company']}: {c['title']} ({c['ats']}) -- {c['error'][:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
