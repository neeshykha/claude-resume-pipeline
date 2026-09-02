#!/usr/bin/env python3
"""Compute the correct `newer_than:` window for Step 1d-2's LinkedIn harvest.

Usage:
    .venv/bin/python pipeline/linkedin_window.py

Why this exists (added 2026-08-31). Step 1d-2 harvests LinkedIn job-alert email,
and its window has to cover every day since the pipeline last ran. The scheduled
task is `0 3 * * 1-5` -- weekdays only -- so a `1d` window on a **Monday** reaches
back only to Sunday 03:00 and silently drops Friday, Saturday, and Sunday: roughly
48 alert threads a week, on the pipeline's highest-yield discovery channel per call.

That was found and documented on 2026-08-28 as a prose instruction: "use
`newer_than:4d` on Mondays, and widen similarly after any skipped or failed run
(check the most recent `run_*.json` date)." The instruction is correct. The problem
is that it asks a model, mid-run, to notice the weekday, find the last run file,
and do arithmetic -- and Step 1d-2's own documented failure mode is being skipped
while self-reporting success (2026-07-30: the step did not execute at all; the run
record contained zero mentions of LinkedIn). A prose rule guarding against silent
omission is itself silently omissible.

Nothing here needs judgment, so this removes it: the window is a function of the
gap since the last completed run.

    window = (today - last_run_date) + 1 day of overlap

Overlap is deliberate and close to free. Widening cannot double-count: every
extracted company goes through check_company.py before it can become a lead, and
the hard cap of 15 new companies per run bounds the downstream work regardless.

Capped at MAX_WINDOW_DAYS. An unbounded window after a long outage would pull
hundreds of threads into the run's context, which is its own failure. If the gap
exceeds the cap the script says so explicitly rather than quietly truncating --
the run should report that some alert history was not reachable.
"""
import datetime as dt
import glob
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.path.join(SCRIPT_DIR, "jobs")

MAX_WINDOW_DAYS = 7
NO_HISTORY_WINDOW_DAYS = 4   # a Monday-sized default when no prior run is on disk
RUN_RE = re.compile(r"run_(\d{4}-\d{2}-\d{2})\.json$")


def prior_run_dates(today: dt.date) -> list[dt.date]:
    """Every run_<date>.json on disk strictly before `today`, newest first."""
    out = []
    for path in glob.glob(os.path.join(JOBS_DIR, "run_*.json")):
        m = RUN_RE.search(os.path.basename(path))
        if not m:
            continue
        try:
            d = dt.date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if d < today:
            out.append(d)
    return sorted(out, reverse=True)


def compute_window(today: dt.date) -> dict:
    """The window as data: {window, last, gap, note}. harvest_linkedin.py imports this
    so the script and the printed instruction can never disagree about the window."""
    prior = prior_run_dates(today)

    if not prior:
        window = NO_HISTORY_WINDOW_DAYS
        last = None
        gap = None
        note = (f"no prior run_*.json on disk, so the gap is unknown; defaulting to "
                f"{window}d (a Monday-sized window). Verify this is a first run and "
                f"not a jobs/ directory problem.")
    else:
        last = prior[0]
        gap = (today - last).days
        window = gap + 1
        if window > MAX_WINDOW_DAYS:
            note = (f"gap is {gap} days, so the ideal window ({gap + 1}d) exceeds the "
                    f"{MAX_WINDOW_DAYS}d cap. Using {MAX_WINDOW_DAYS}d. ALERT HISTORY "
                    f"OLDER THAN {MAX_WINDOW_DAYS} DAYS IS NOT REACHABLE THIS RUN -- say "
                    f"so in the digest rather than letting it pass as full coverage.")
            window = MAX_WINDOW_DAYS
        elif today.weekday() == 0 and gap >= 3:
            note = ("Monday after a weekend gap, which is the case this check was built "
                    "for: a 1d window here would drop Friday through Sunday.")
        else:
            note = "normal weekday gap."
    return {"window": window, "last": last, "gap": gap, "note": note}


def main() -> int:
    today = dt.date.today()
    w = compute_window(today)
    window, last, gap, note = w["window"], w["last"], w["gap"], w["note"]

    print(f"today          : {today.isoformat()} ({today.strftime('%A')})")
    print(f"last run       : {last.isoformat() + ' (' + last.strftime('%A') + ')' if last else 'none found'}")
    print(f"gap (days)     : {gap if gap is not None else 'unknown'}")
    print()
    print(f"USE THIS WINDOW: newer_than:{window}d")
    print()
    print(f"Step 0.5 query : deliveredto:{{{{CONFIRM_ALIAS}}}} -from:linkedin.com newer_than:3d")
    print(f"Step 1d-2 query: deliveredto:{{{{CONFIRM_ALIAS}}}} from:linkedin.com newer_than:{window}d")
    print()
    print(f"note           : {note}")
    print()
    print("Log the window you actually used in run_[date].json -> "
          "step_1d_2_linkedin_harvest.window_used, alongside jobs_noreply_threads_seen "
          "and digest_bodies_opened.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
