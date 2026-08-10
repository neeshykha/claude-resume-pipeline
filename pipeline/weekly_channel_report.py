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

Usage:
    .venv/bin/python pipeline/weekly_channel_report.py

Prints the report to stdout. Does not touch Gmail or any state marker --
the calling routine (daily_task_prompt.md) owns the "is a report due this
run" gate (via pipeline/jobs/weekly_channel_report_state.json) and the
draft-creation step, so this script stays a pure aggregator.
"""
import glob
import json
from datetime import datetime, timedelta


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


def main():
    rows, missing, cutoff = load_window()
    today = datetime.now().date()

    print(f"=== Weekly Channel Report: {cutoff} to {today} ===")
    print(f"Days with channel_stats data: {len(rows)} of 7")
    if missing:
        print(f"Days in window without data: {', '.join(str(d) for d in missing)}")
    if not rows:
        print("No channel_stats data in the trailing window. Nothing to report yet.")
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


if __name__ == "__main__":
    main()
