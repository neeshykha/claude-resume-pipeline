"""
Weekly channel-effectiveness rollup for the daily job pipeline.

Aggregates the `channel_stats` block (added 2026-08-10) from the trailing 7 days
of pipeline/jobs/run_*.json and prints a human-readable summary comparing the
four discovery/execution channels:
  - ats_poll: poll_ats.py against the full watchlist (execution layer -- runs
    every day, benefits from every company any channel has ever enrolled)
  - websearch: the 14 active _websearch_sources dorks (discovery layer)
  - linkedin_harvest: Step 1d-2 forwarded LinkedIn job-alert emails (discovery
    layer, plus the blind-spot auto-trigger for named unpollable companies)
  - feeders: poll_remotive.py, poll_80k.py, harvest_hn_hiring.py (discovery
    layer, lower daily cadence)

Only aggregates days that actually have a channel_stats block -- older run
files predate the schema and are skipped, not guessed at. The report says
explicitly how many of the trailing 7 days had data.

Also prints an "unpollable companies" section (added 2026-08-14, from Aneesh
asking for a weekly punch list): pipeline/enrollment_candidates.json -> rejected
entries tagged unpollable=true (a genuine "no ATS board was ever found" gap, not
a fit/geo/category rejection) that haven't been surfaced in a prior weekly report.
These are a standing backlog, not a trailing-7-day window -- unpollable=true
entries accumulate whenever the automated layer hits a wall, and Aneesh reviews a
capped batch by hand once a week (workarounds: a non-obvious ATS slug, a Workday
tenant name, or deciding it's not worth chasing). Capped at UNPOLLABLE_WEEKLY_CAP
per report, oldest rejected_date first, so a backlog drains gradually instead of
dumping 100+ companies into one email.

Usage:
    .venv/bin/python pipeline/weekly_channel_report.py           # preview only
    .venv/bin/python pipeline/weekly_channel_report.py --apply   # preview + mark
                                                                  # the printed
                                                                  # unpollable batch
                                                                  # weekly_report_surfaced
                                                                  # so it doesn't repeat

Prints the report to stdout. The channel-stats half never touches state. The
unpollable-companies half only writes to enrollment_candidates.json when --apply
is passed -- the calling routine (daily_task_prompt.md) runs it plain first to
build the draft, then re-runs with --apply once the draft is actually created, so
a preview that never gets sent doesn't silently consume the batch. The "is a
report due this run" gate (via pipeline/jobs/weekly_channel_report_state.json)
and Gmail draft creation stay owned by the calling routine either way.
"""
import argparse
import glob
import json
from datetime import datetime, timedelta

UNPOLLABLE_WEEKLY_CAP = 20
QUEUE_PATH = "pipeline/enrollment_candidates.json"


def load_window(days=7):
    cutoff = datetime.now().date() - timedelta(days=days - 1)
    found = []
    missing_dates = []
    for path in sorted(glob.glob("pipeline/jobs/run_*.json")):
        date_str = path.replace("pipeline/jobs/run_", "").replace(".json", "")
        try:
            run_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if run_date < cutoff:
            continue
        try:
            d = json.load(open(path))
        except Exception:
            continue
        cs = d.get("channel_stats")
        if cs:
            found.append((run_date, cs))
        else:
            missing_dates.append(run_date)
    found.sort(key=lambda x: x[0])
    return found, missing_dates, cutoff


def sum_field(rows, *path):
    total = 0
    for _, cs in rows:
        node = cs
        for key in path:
            node = node.get(key, {}) if isinstance(node, dict) else {}
        if isinstance(node, (int, float)):
            total += node
    return total


def load_unpollable_batch(cap=UNPOLLABLE_WEEKLY_CAP):
    """Return (batch, remaining_after_batch, total_unsurfaced) of rejected
    entries tagged unpollable=true that haven't been surfaced in a prior
    weekly report yet. Oldest rejected_date first."""
    try:
        with open(QUEUE_PATH) as f:
            q = json.load(f)
    except FileNotFoundError:
        return [], 0, 0

    unsurfaced = [
        r for r in q.get("rejected", [])
        if r.get("unpollable") and not r.get("weekly_report_surfaced")
    ]
    unsurfaced.sort(key=lambda r: r.get("rejected_date") or "")
    batch = unsurfaced[:cap]
    remaining = len(unsurfaced) - len(batch)
    return batch, remaining, len(unsurfaced)


def mark_surfaced(batch):
    """Write weekly_report_surfaced=true + date onto exactly the entries in
    `batch` (matched by name + rejected_date, since names alone could collide
    across re-discovery). Only called with --apply."""
    if not batch:
        return
    with open(QUEUE_PATH) as f:
        q = json.load(f)

    keys = {(r.get("name"), r.get("rejected_date")) for r in batch}
    today = datetime.now().date().isoformat()
    touched = 0
    for r in q.get("rejected", []):
        if (r.get("name"), r.get("rejected_date")) in keys and not r.get("weekly_report_surfaced"):
            r["weekly_report_surfaced"] = True
            r["weekly_report_surfaced_date"] = today
            touched += 1

    tmp = QUEUE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(q, f, indent=2)
        f.write("\n")
    import os
    os.replace(tmp, QUEUE_PATH)
    print(f"\nMarked {touched} unpollable entries as weekly_report_surfaced.")


def print_unpollable_section(batch, remaining, total_unsurfaced):
    print()
    print("=== Unpollable companies (no ATS board ever found) ===")
    if not batch:
        print("None pending review. Every unpollable=true entry has already been surfaced.")
        return
    print(f"{total_unsurfaced} total awaiting review; showing the oldest {len(batch)}"
          + (f" ({remaining} more carry over to next week)" if remaining else " (backlog clear after this batch)") + ".")
    print("Workaround options per company: find the real ATS slug/Workday tenant by hand,")
    print("or decide it's not worth chasing and let it drop.")
    print()
    for r in batch:
        name = r.get("name", "?")
        date = r.get("rejected_date", "?")
        reason = (r.get("reason") or "").strip()
        print(f"  - {name} (rejected {date})")
        print(f"      {reason}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                         help="Mark the printed unpollable batch as weekly_report_surfaced "
                              "so it doesn't repeat next week. Only run this after the "
                              "digest draft has actually been created.")
    args = parser.parse_args()

    rows, missing, cutoff = load_window()
    today = datetime.now().date()

    print(f"=== Weekly Channel Report: {cutoff} to {today} ===")
    print(f"Days with channel_stats data: {len(rows)} of 7")
    if missing:
        print(f"Days in window without data: {', '.join(str(d) for d in missing)}")
    if not rows:
        print("No channel_stats data in the trailing window. Nothing to report yet.")
        batch, remaining, total_unsurfaced = load_unpollable_batch()
        print_unpollable_section(batch, remaining, total_unsurfaced)
        if args.apply:
            mark_surfaced(batch)
        return

    ats_polled = sum_field(rows, "ats_poll", "companies_polled")
    ats_scanned = sum_field(rows, "ats_poll", "jobs_scanned")
    ats_matched = sum_field(rows, "ats_poll", "title_matched")
    ats_shortlisted = sum_field(rows, "ats_poll", "shortlisted")

    ws_sources = sum_field(rows, "websearch", "sources_run")
    ws_new = sum_field(rows, "websearch", "new_companies_found")
    ws_enrolled = sum_field(rows, "websearch", "enrolled")

    li_threads = sum_field(rows, "linkedin_harvest", "threads_found")
    li_companies = sum_field(rows, "linkedin_harvest", "companies_extracted")
    li_enrolled = sum_field(rows, "linkedin_harvest", "enrolled")
    li_blind_spot = sum_field(rows, "linkedin_harvest", "blind_spot_real_hits")

    feeder_remotive_leads = sum_field(rows, "feeders", "poll_remotive_leads")
    feeder_80k_leads = sum_field(rows, "feeders", "poll_80k_leads")
    feeder_hn_leads = sum_field(rows, "feeders", "harvest_hn_hiring_leads")
    remotive_degraded_days = sum(
        1 for _, cs in rows if cs.get("feeders", {}).get("poll_remotive_status") == "degraded"
    )

    tailored_total = sum_field(rows, "tailored_count")

    print()
    print(f"ATS poll (execution layer, runs every day):")
    print(f"  companies polled (latest-day snapshot varies; summed across {len(rows)} days): {ats_polled}")
    print(f"  jobs scanned: {ats_scanned}  |  title matches: {ats_matched}  |  shortlisted: {ats_shortlisted}")
    print()
    print(f"WebSearch discovery ({ws_sources} source-runs across {len(rows)} days):")
    print(f"  new companies found: {ws_new}  |  enrolled: {ws_enrolled}")
    print()
    print(f"LinkedIn harvest ({li_threads} threads, {li_companies} companies extracted):")
    print(f"  enrolled: {li_enrolled}  |  blind-spot real hits (unpollable but real): {li_blind_spot}")
    print()
    print(f"Discovery feeders:")
    print(f"  poll_remotive: DEGRADED on {remotive_degraded_days} of {len(rows)} tracked days, 0 leads possible while degraded")
    print(f"  poll_80k leads: {feeder_80k_leads}  |  harvest_hn_hiring leads: {feeder_hn_leads}")
    print()
    print(f"Tailored applications this window: {tailored_total}")
    print(f"  (all tailoring executes off the ATS-poll shortlist by design -- discovery channels")
    print(f"   feed the watchlist that ATS-poll scans, they don't produce same-day applications directly)")

    batch, remaining, total_unsurfaced = load_unpollable_batch()
    print_unpollable_section(batch, remaining, total_unsurfaced)
    if args.apply:
        mark_surfaced(batch)


if __name__ == "__main__":
    main()
