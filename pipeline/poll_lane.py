#!/usr/bin/env python3
"""Lane-only poll: every title match at the lane employers, for Step 3.6.

Usage:
    .venv/bin/python pipeline/poll_lane.py                    # today, lane "industrial"
    .venv/bin/python pipeline/poll_lane.py --date 2026-10-12
    .venv/bin/python pipeline/poll_lane.py --lane industrial

Runs the real poll_ats.poll_all() once per watchlist entry marked
`"lane": "<lane>"`, each time against a temporary copy of the watchlist whose
`companies` list is that one entry with the marker dropped, and writes
pipeline/jobs/lane_hits_<date>.json: a `counts` block, one line per board, then
one flat `candidates` list, Georgia first, then remote, then everywhere else.

Why this exists (added 2026-10-10). The main poll ranks every title match on
the watchlist into one shortlist of about 40. Lane entries are low-priority
enterprise companies, and in that pool they lost both ways: of ten lane matches
in metro Atlanta or remote, one cleared the day's cutoff, while about four
roles in other states did and would have held shortlist slots. So poll_all()
skips marked entries and this is the only reader of their boards. Polled on
their own, nothing competes with them. The gates, the matcher, the dedup, and
the pre_score are the main poll's; only the ranking pool is different, and the
two list caps that ration the main poll's output are lifted so nothing is cut.

It writes that one file and nothing else. poll_all() only reads (the watchlist
and seen_jobs.json), and poll_ats.main(), which writes ats_hits_<date>.json,
is never called. The live watchlist is read, never written.

Each board gets BOARD_DEADLINE_S of wall clock. The adapters' request timeouts
bound the gap between bytes, not the whole read, and on the first dry run one
board's feed dripped for 27 minutes before failing. A board that runs out of
time, or errors, is named in `boards` and `errors` and costs only its own
candidates.

Exits 0 with a one-line summary, including when no entry carries the lane
marker (a zero-candidate file is still written, so a reader can tell an empty
lane from a skipped step). An invalid watchlist exits 2 from poll_all(), as it
does for the main poll.
"""
import argparse
import json
import os
import signal
import sys
import tempfile
import time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import poll_ats  # noqa: E402

JOBS = os.path.join(HERE, "jobs")
DEFAULT_LANE = "industrial"
UNCAPPED = 10 ** 6
# Healthy reads of the first three lane boards took 11 to 52 seconds.
BOARD_DEADLINE_S = 150
PLACES = ("georgia", "remote", "elsewhere")   # poll_ats._fyi_place() order
SOURCES = (("matched", "tier_match"), ("near_window", "tier_match"),
           ("borderline", "borderline"), ("function_mismatch", "function_mismatch"),
           ("ai_engineer_stretch", "ai_engineer_stretch"))


class BoardDeadline(BaseException):
    """Raised by the alarm. A BaseException so the adapters' `except Exception`
    blocks cannot swallow it and carry on reading."""


def _on_alarm(signum, frame):
    raise BoardDeadline()


def lane_companies(watchlist, lane):
    return [c for c in watchlist.get("companies", []) if c.get("lane") == lane]


def poll_board(run_date, watchlist, company):
    """(poll_all() result, None) for one company, or (None, reason)."""
    saved = (poll_ats.WATCHLIST_PATH, poll_ats.NEAR_WINDOW_SIZE, poll_ats.BORDERLINE_SIZE)
    old_handler = signal.signal(signal.SIGALRM, _on_alarm)
    fd, tmp = tempfile.mkstemp(prefix="lane_watchlist_", suffix=".json")
    try:
        # poll_all() skips entries that carry the lane marker, so this copy
        # drops it. ASCII-escaped, so poll_all()'s plain open() reads it under
        # any locale.
        unmarked = {k: v for k, v in company.items() if k != "lane"}
        with os.fdopen(fd, "w") as f:
            json.dump(dict(watchlist, companies=[unmarked]), f)
        poll_ats.WATCHLIST_PATH = tmp
        # The 2-per-company cap leaves almost every match in near_window, so
        # its 40-line cap is the one that would cut real matches here.
        poll_ats.NEAR_WINDOW_SIZE = poll_ats.BORDERLINE_SIZE = UNCAPPED
        signal.setitimer(signal.ITIMER_REAL, BOARD_DEADLINE_S)
        try:
            res = poll_ats.poll_all(run_date)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
    except BoardDeadline:
        return None, f"no complete read inside {BOARD_DEADLINE_S} s"
    finally:
        signal.signal(signal.SIGALRM, old_handler)
        poll_ats.WATCHLIST_PATH, poll_ats.NEAR_WINDOW_SIZE, poll_ats.BORDERLINE_SIZE = saved
        os.unlink(tmp)
    if res["errors"]:
        return None, str(res["errors"][0].get("error"))
    return res, None


def flatten(res, run_date):
    """One entry per posting. `matched` and `near_window` are one population
    here (only the 2-per-company cap separates them when a company competes
    with no one else), so both come out as source "tier_match"."""
    out, seen = [], set()
    for key, source in SOURCES:
        for e in res.get(key) or []:
            url = e.get("apply_url") or e.get("url")
            if url and url in seen:
                continue
            seen.add(url)
            posted = e.get("posted_date")
            age = e.get("posting_age_days")
            if not posted and age is not None:   # function_mismatch entries carry the age only
                posted = (run_date - timedelta(days=age)).isoformat()
            out.append({
                "company": e.get("company"),
                "title": e.get("title"),
                "location": e.get("location"),
                "place": PLACES[poll_ats._fyi_place(e.get("location"))],
                "source": source,
                "pre_score": e.get("pre_score"),
                "title_tier": e.get("title_tier"),
                "posted_date": posted,
                "url": url,
            })
    return out


def run(run_date, lane=DEFAULT_LANE, jobs_dir=None, watchlist_path=None):
    """Poll each lane board, write lane_hits_<date>.json, return (path, payload)."""
    with open(watchlist_path or poll_ats.WATCHLIST_PATH, encoding="utf-8") as f:
        watchlist = json.load(f)
    boards, cands = [], []
    for company in lane_companies(watchlist, lane):
        started = time.monotonic()
        res, error = poll_board(run_date, watchlist, company)
        got = flatten(res, run_date) if res else []
        boards.append({
            "company": company["name"],
            "postings_scanned": res["stats"]["total_jobs_scanned"] if res else 0,
            "candidates": len(got),
            "seconds": round(time.monotonic() - started),
            "error": error,
        })
        cands.extend(got)
    cands.sort(key=lambda c: (PLACES.index(c["place"]), -(c["pre_score"] or 0),
                              c["company"] or "", c["title"] or ""))
    counts = {"candidates": len(cands)}
    for place in PLACES:
        counts[place] = sum(1 for c in cands if c["place"] == place)
    for source in ("tier_match", "borderline", "function_mismatch", "ai_engineer_stretch"):
        counts[source] = sum(1 for c in cands if c["source"] == source)
    payload = {
        "run_date": run_date.isoformat(),
        "lane": lane,
        "counts": counts,
        "boards": boards,
        "errors": [{"company": b["company"], "error": b["error"]} for b in boards if b["error"]],
        "candidates": cands,
    }
    jobs_dir = jobs_dir or JOBS
    os.makedirs(jobs_dir, exist_ok=True)
    path = os.path.join(jobs_dir, f"lane_hits_{run_date.isoformat()}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False)
        f.write("\n")
    return path, payload


def main():
    ap = argparse.ArgumentParser(description="Poll only the watchlist entries marked for a lane")
    ap.add_argument("--date", default=None, help="Run date (YYYY-MM-DD). Defaults to today.")
    ap.add_argument("--lane", default=DEFAULT_LANE)
    args = ap.parse_args()
    run_date = date.fromisoformat(args.date) if args.date else date.today()

    path, p = run(run_date, args.lane)
    k = p["counts"]
    print(f"poll_lane: {len(p['boards'])} boards, "
          f"{sum(b['postings_scanned'] for b in p['boards'])} postings, "
          f"{len(p['errors'])} errors, {sum(b['seconds'] for b in p['boards'])} s; "
          f"{k['candidates']} candidates "
          f"({k['tier_match']} tier_match, {k['borderline']} borderline, "
          f"{k['function_mismatch']} function_mismatch, "
          f"{k['ai_engineer_stretch']} ai_engineer_stretch); "
          f"{k['georgia']} georgia, {k['remote']} remote, {k['elsewhere']} elsewhere")
    if not p["boards"]:
        print(f"  no watchlist entry is marked lane={args.lane!r}")
    for err in p["errors"]:
        print(f"  ERROR  {err['company']}: {err['error'][:160]}")
    print(f"output: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
