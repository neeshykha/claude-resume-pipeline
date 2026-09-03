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
  - feeders: poll_remotive.py, poll_80k.py, poll_builtin.py, harvest_hn_hiring.py (discovery
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

# Set by --all-unpollable. Off by default: see load_unpollable_batch for why the
# ungated list was measured at zero yield and retired as a weekly chore.
INCLUDE_ALL_UNPOLLABLE = False
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


def has_role_signal(entry: dict) -> bool:
    """Did anything ever confirm a fit-space ROLE at this company?

    `manual_review_why` is set by Step 1d-2 when a LinkedIn card showed a
    tier1/tier2/tier2c title at that company in Atlanta or remote-US, and it is
    carried onto the rejection by harvest_ats.py. That is the only per-company
    evidence in this file that a real matching role was ever seen, as opposed to
    a name someone once encountered on a job board.
    """
    return bool(entry.get("manual_review_why") or entry.get("manual_review"))


def load_unpollable_batch(cap=UNPOLLABLE_WEEKLY_CAP):
    """Return (batch, remaining_after_batch, total_unsurfaced) of rejected
    entries tagged unpollable=true, NOT yet surfaced, AND carrying confirmed
    role signal. Oldest rejected_date first.

    GATED ON ROLE SIGNAL as of 2026-08-31, after measuring the ungated version.
    This section used to hand Aneesh 20 companies a week sorted only by
    rejection date, and a 30-company dry run of that exact population produced
    **zero enrollable companies**: 23 had no board at all, 3 had boards with no
    fit-titles, and the batch was dominated by AI-policy nonprofits (GovAI, Pax
    Sapiens, CivAI) and mega-enterprises (Microsoft, Wabtec, Epiroc) that do not
    run a supported ATS and never will. It was a standing weekly chore with a
    measured yield of nothing.

    The premise had also expired. This punch list was created 2026-08-14 because
    harvest_ats.py could not resolve non-obvious slugs, so a human searching by
    hand genuinely beat the machine. On 2026-08-31 the three gaps behind that
    (TLD stripping, legal-form suffixes, dotted slugs) were fixed and verified on
    18/20 known cases, so the machine now finds what the hand-search was for.

    What still justifies human attention is a company where a REAL MATCHING ROLE
    was seen and the automated layer structurally cannot reach it. That is what
    `manual_review_why` records, and it is the same principle behind
    `_unpollable_backlog_companies` in the watchlist: curated from confirmed role
    signal rather than from "no board found."

    Ungated entries are not deleted, just not surfaced; `--all-unpollable`
    restores the old behaviour for a one-off sweep.
    """
    try:
        with open(QUEUE_PATH) as f:
            q = json.load(f)
    except FileNotFoundError:
        return [], 0, 0

    unsurfaced = [
        r for r in q.get("rejected", [])
        if r.get("unpollable") and not r.get("weekly_report_surfaced")
        and (INCLUDE_ALL_UNPOLLABLE or has_role_signal(r))
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
    scope = ("ALL unsurfaced entries (--all-unpollable)" if INCLUDE_ALL_UNPOLLABLE
             else "confirmed role signal only")
    print(f"=== Unpollable companies with a role worth chasing ({scope}) ===")
    if not batch:
        if INCLUDE_ALL_UNPOLLABLE:
            print("None pending review. Every unpollable=true entry has already been surfaced.")
        else:
            print("Nothing to review: no unsurfaced unpollable company has a confirmed "
                  "fit-space role on record.")
            print("This is the expected steady state, not an error. Gated 2026-08-31 after a "
                  "30-company dry run")
            print("of the ungated list returned ZERO enrollable companies. Run with "
                  "--all-unpollable for a")
            print("deliberate full sweep.")
        return
    print(f"{total_unsurfaced} awaiting review; showing the oldest {len(batch)}"
          + (f" ({remaining} more carry over to next week)" if remaining else " (batch clears the list)") + ".")
    if not INCLUDE_ALL_UNPOLLABLE:
        print("Every entry below had a tier1/tier2/tier2c title seen in Atlanta or remote-US,")
        print("at a company the poller structurally cannot watch. That is why it is worth your time.")
    print("Per company: find the real ATS slug/Workday tenant by hand, or decide it is not")
    print("worth chasing and let it drop.")
    print()
    for r in batch:
        name = r.get("name", "?")
        date = r.get("rejected_date", "?")
        reason = (r.get("reason") or "").strip()
        why = (r.get("manual_review_why") or "").strip()
        print(f"  - {name} (rejected {date})")
        if why:
            print(f"      ROLE SEEN: {why}")
        print(f"      {reason}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                         help="Mark the printed unpollable batch as weekly_report_surfaced "
                              "so it doesn't repeat next week. Only run this after the "
                              "digest draft has actually been created.")
    parser.add_argument("--all-unpollable", action="store_true",
                        help="Restore the pre-2026-08-31 behaviour and list EVERY unsurfaced "
                             "unpollable entry, not just those with confirmed role signal. "
                             "For a deliberate one-off sweep; a 30-company dry run of this "
                             "population yielded zero enrollable companies, so it is not the "
                             "weekly default.")
    args = parser.parse_args()
    global INCLUDE_ALL_UNPOLLABLE
    INCLUDE_ALL_UNPOLLABLE = args.all_unpollable

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
    feeder_builtin_leads = sum_field(rows, "feeders", "poll_builtin_leads")
    feeder_builtin_ambiguous = sum_field(rows, "feeders", "poll_builtin_ambiguous")
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
    # poll_builtin landed 2026-09-03; runs before then carry no such key and sum to 0,
    # which reads the same as "ran and found nothing". Check the run dates before
    # concluding this feeder is dead.
    print(f"  poll_builtin leads: {feeder_builtin_leads}"
          f"  |  ambiguous (truncated breakdown, not queued): {feeder_builtin_ambiguous}")
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
