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

The per-channel `enrolled` counters inside `channel_stats` are SAME-RUN counts,
and they systematically undercount. Measured 2026-09-07 over the 39 backfilled
entries carrying both dates: 72% of enrollments lag discovery by at least a day
(median 1d, max 11d) and only 28% resolve in the run that found them. Step 1d
appends to `pending` and `harvest_ats.py` drains it in the same pass, so same-run
enrollment is common -- it is the majority case that is NOT.

That alone does not explain a zero. The other half is attribution: the
`channel_stats` block is written by hand at Step 7, and until 2026-09-07 nothing
recorded WHICH channel fed a given enrollment. LinkedIn could self-report,
because Step 1d-2 knows the names it just appended; WebSearch could not, because
its dorks feed the same undifferentiated queue. That is how this report spent
weeks saying "0 enrollments off 19 WebSearch source-runs" about a channel that
was in fact converting -- 2 enrolled against 2 rejected in the 09-01..09-07
window alone, once the provenance existed to see it.

The "Enrollment attribution" section (added 2026-09-07) is the honest answer.
It reads `enrollment_candidates.json` directly and counts entries whose
`enrolled_date` falls in the window, grouped by the `source` string carried over
from `pending`. Because enrollment and discovery are different events, this
section deliberately does NOT divide by the window's discovery counts: the
companies enrolled this week were mostly found last week. It reports the lag
instead, so the two numbers can be read against each other honestly.

`source` has only been carried onto `enrolled`/`rejected` since 2026-09-07;
everything filed before then is counted as "unattributed" rather than guessed
at, and that bucket shrinks on its own as the backlog turns over.

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

Also prints a "LinkedIn alerts: what was in them and where it went" section
(added 2026-09-10, from Aneesh: "I'm seeing a lot of cool stuff that isn't seeming
to make the cut. That job leads pull, I kind of want that validated."). The four
`linkedin_harvest` counters above it are self-reported VOLUME and cannot answer
that; they say how much came in, never what happened to it. This section joins the
daily `linkedin_cards_<date>.json` files against outcomes.csv and gives every
strong role a disposition, which is auditable.

Measured on the first run (window 2026-09-04..09-10, 568 cards, 304 unique roles,
60 strong): 12% became a tailored application, 8% were at a company that produced
other work, 13% were at pollable companies and still never scored in, and **47%
were at companies the poller structurally cannot reach**. His instinct was right,
and the leak is reachability rather than grading -- the harvester found these
roles and correctly graded them tier1/tier2; there was simply no board to watch.

Note the deliberate overlap with the unpollable punch list below: that one is
company-level and drains a standing backlog, this one is role-level and windowed.
A company can honestly appear in both.

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

WATCHLIST_PATH = "pipeline/watchlist_companies.json"

# The first date on which every outcome entry SHOULD carry a source. The
# carry-through landed 2026-09-07, so runs that had already fired that day wrote
# source-less entries under the old code; dating the boundary to the day after
# keeps those out of the "something is wrong" bucket. Entries filed before it
# are unattributable by construction, not by a bug, and the report says so
# instead of lumping them in with genuinely source-less ones.
PROVENANCE_SINCE = "2026-09-08"

# Source strings are freeform prose written by seven different producers, so
# classification is by substring against a small vocabulary rather than by exact
# match. Order matters: the explicit script labels below are unambiguous and are
# tested before the configured WebSearch source names, which are broader.
LINKEDIN_SOURCE_MARKERS = ("linkedin",)

# Fixed labels emitted by the feeder scripts: poll_remotive.py ("Remotive API"),
# poll_80k.py ("80K Hours Algolia API"), harvest_hn_hiring.py, poll_builtin.py
# ("BuiltIn directory"), harvest_vc_portfolios.py.
#
# Two of these collide with retired WebSearch dorks of the same subject and the
# distinction is real, not pedantic: "80,000 Hours Job Board" and "BuiltIn
# Remote" were dorks BEFORE poll_80k.py and poll_builtin.py replaced them, so
# those strings belong to the websearch channel and "80K Hours Algolia API" /
# "BuiltIn directory" belong to feeders. Matching on "80k hours" and "algolia"
# rather than on "80,000 hours", and on "builtin directory" rather than on
# "builtin", is what keeps the two apart.
FEEDER_SOURCE_MARKERS = (
    "remotive", "80k hours", "algolia", "hn who is hiring",
    "builtin directory", "portfolio harvest", "vc/accelerator",
)

WEBSEARCH_SOURCE_MARKERS = ("websearch", "dork", "board sweep")

CHANNEL_LABELS = {
    "websearch": "WebSearch discovery",
    "linkedin_harvest": "LinkedIn harvest",
    "feeders": "Discovery feeders",
    "other": "Other / hand-added",
}
CHANNEL_ORDER = ("websearch", "linkedin_harvest", "feeders", "other")

# Set by --all-unpollable. Off by default: see load_unpollable_batch for why the
# ungated list was measured at zero yield and retired as a weekly chore.
INCLUDE_ALL_UNPOLLABLE = False
QUEUE_PATH = "pipeline/enrollment_candidates.json"

# --- LinkedIn card funnel (added 2026-09-10, Aneesh's ask) -------------------
#
# The four `linkedin_harvest` counters in channel_stats are self-reported volume:
# threads seen, companies extracted, same-run enrollments. They cannot answer the
# question he actually asked, which is "the alerts are full of roles that look
# good and none of them become picks -- is this channel working?"
#
# harvest_linkedin.py already writes every graded card to
# pipeline/jobs/linkedin_cards_<date>.json. Joining those against outcomes.csv
# turns the channel from a volume counter into a funnel with a disposition for
# each strong role, which is auditable.
#
# Measured over 2026-09-02..09-09 (6 card files, 743 cards, 335 unique roles, 70
# strong): 15% of strong roles became a tailored application, 34% were at
# companies the poller structurally cannot reach, and 30% were at companies not
# yet enrolled when the alert arrived. His instinct was right, and the leak is
# almost entirely reachability rather than grading.
LINKEDIN_CARDS_GLOB = "pipeline/jobs/linkedin_cards_*.json"

# A card is STRONG if the title hit a real scoring tier AND the location clears
# the Atlanta / remote-US gate. tier3 is deliberately excluded: it is a stretch
# title that only earns tailoring above 88, so a tier3 card going nowhere is the
# rubric working rather than a leak.
STRONG_CARD_TIERS = {"tier1", "tier2", "tier2c", "tier2d"}

# How many unreachable strong roles to name per report before collapsing to a
# count. Same reasoning as UNPOLLABLE_WEEKLY_CAP: a punch list nobody reads is
# worse than a short one somebody acts on.
LINKEDIN_PUNCHLIST_CAP = 20

CARD_BUCKETS = (
    ("tailored", "Became a tailored application"),
    ("company_worked", "Different role at that company was tailored"),
    ("pollable_not_picked", "Company IS pollable, this role never scored in"),
    ("queued", "Company queued, not pollable yet when the alert landed"),
    ("unknown", "Company new or unclassified"),
    ("unpollable", "Company REJECTED, no ATS board exists"),
    ("blind_spot", "Named blind-spot employer, structurally unpollable"),
)
UNREACHABLE_BUCKETS = ("unpollable", "blind_spot")


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
            # `tailored_count` is a TOP-LEVEL key of run_*.json, not part of the
            # channel_stats block (daily_task_prompt.md Step 6 item 7 says so
            # explicitly). sum_field only walks inside channel_stats, so the
            # report summed a path that never existed and printed
            # "Tailored applications this window: 0" every single week since the
            # schema landed. Caught 2026-09-10. Copy it inside under a private
            # key rather than changing load_window's return signature.
            cs = dict(cs)
            cs["_tailored_count"] = d.get("tailored_count", 0)
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


def websearch_source_heads(path=WATCHLIST_PATH):
    """Configured WebSearch source names, trimmed to the part before " (".

    Read from config rather than hardcoded so a newly added dork classifies
    correctly without touching this file. The trim is what makes matching work
    across renames: the source string on a queue entry is whatever the run wrote
    that day -- "Atlanta Board Sweep (repaired dorks, first working run)" -- and
    the configured name has since become "Atlanta Board Sweep (Greenhouse)".
    The shared head, "atlanta board sweep", survives both.

    Returns () if the watchlist is unreadable. That degrades classification to
    the keyword markers rather than crashing a report whose other half works.
    """
    try:
        with open(path) as f:
            wl = json.load(f)
    except Exception:
        return ()
    heads = []
    for s in wl.get("_websearch_sources", {}).get("sources", []):
        name = (s.get("name") or "").split(" (")[0].strip().lower()
        if name:
            heads.append(name)
    return tuple(heads)


def classify_source(source, heads=()):
    """Map a freeform `source` string onto one of CHANNEL_ORDER.

    Returns None for a missing/empty source -- the caller separates "we do not
    know" from "we know it was none of the channels", because conflating those
    is what made the old numbers unreadable in the first place.
    """
    if not source:
        return None
    s = source.lower()
    if any(m in s for m in LINKEDIN_SOURCE_MARKERS):
        return "linkedin_harvest"
    if any(m in s for m in FEEDER_SOURCE_MARKERS):
        return "feeders"
    if any(h in s for h in heads):
        return "websearch"
    if any(m in s for m in WEBSEARCH_SOURCE_MARKERS):
        return "websearch"
    return "other"


def load_attribution(cutoff, today):
    """Group in-window enrolled/rejected queue entries by discovery channel.

    Returns (channels, unattributed, legacy, total_enrolled), where `channels`
    maps a channel key to {"enrolled": [...], "rejected": [...], "lags": [...]}.
    `unattributed` counts in-window enrollments with no `source` that were filed
    on or after PROVENANCE_SINCE (a real gap worth noticing -- typically a
    hand-enrolled company or a `harvest_ats.py --names` run against a name that
    was never queued); `legacy` counts those filed before it (expected, drains
    on its own).
    """
    try:
        with open(QUEUE_PATH) as f:
            q = json.load(f)
    except FileNotFoundError:
        return {}, 0, 0, 0

    heads = websearch_source_heads()
    channels = {k: {"enrolled": [], "rejected": [], "lags": []} for k in CHANNEL_ORDER}
    unattributed = legacy = 0
    total_enrolled = 0

    def in_window(value):
        try:
            d = datetime.strptime(value, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return False
        return cutoff <= d <= today

    for e in q.get("enrolled", []):
        if not in_window(e.get("enrolled_date")):
            continue
        total_enrolled += 1
        channel = classify_source(e.get("source"), heads)
        if channel is None:
            if (e.get("enrolled_date") or "") < PROVENANCE_SINCE:
                legacy += 1
            else:
                unattributed += 1
            continue
        channels[channel]["enrolled"].append(e)
        lag = enrollment_lag(e)
        if lag is not None:
            channels[channel]["lags"].append(lag)

    for e in q.get("rejected", []):
        if not in_window(e.get("rejected_date")):
            continue
        channel = classify_source(e.get("source"), heads)
        if channel is not None:
            channels[channel]["rejected"].append(e)

    return channels, unattributed, legacy, total_enrolled


def enrollment_lag(entry):
    """Days from first sighting to enrollment, or None if either date is absent.

    This is the number that explains the whole section: it is why a channel's
    same-run `enrolled` counter reads zero, and it is how far back you have to
    look to find the discovery runs that produced this week's enrollments.
    """
    try:
        seen = datetime.strptime(entry["first_seen"], "%Y-%m-%d").date()
        got = datetime.strptime(entry["enrolled_date"], "%Y-%m-%d").date()
    except (KeyError, TypeError, ValueError):
        return None
    return (got - seen).days


def print_attribution_section(channels, unattributed, legacy, total_enrolled,
                              cutoff, today):
    print()
    print("=== Enrollment attribution (which channel found what enrolled this window) ===")
    print(f"Counts enrollment_candidates.json entries with enrolled_date in {cutoff}..{today},")
    print("grouped by the source carried over from `pending`. These are NOT the same-run")
    print("`enrolled` counters above, and must not be divided by this window's discovery")
    print("counts: 72% of enrollments lag discovery by a day or more (median 1d, max 11d),")
    print("so most of what enrolled this week was found before it.")
    print()

    if not total_enrolled:
        print("  No companies were enrolled in this window at all.")
        return

    attributed = sum(len(v["enrolled"]) for v in channels.values())
    for key in CHANNEL_ORDER:
        data = channels[key]
        n_enrolled = len(data["enrolled"])
        n_rejected = len(data["rejected"])
        if not n_enrolled and not n_rejected:
            continue
        resolved = n_enrolled + n_rejected
        rate = f"{100.0 * n_enrolled / resolved:.0f}%" if resolved else "n/a"
        print(f"  {CHANNEL_LABELS[key]}: {n_enrolled} enrolled, {n_rejected} rejected "
              f"({rate} of {resolved} resolved this window)")
        lags = sorted(data["lags"])
        if lags:
            median = lags[len(lags) // 2]
            print(f"      discovery-to-enrollment lag: median {median}d, "
                  f"range {lags[0]}-{lags[-1]}d (n={len(lags)})")
        for e in data["enrolled"][:5]:
            lag = enrollment_lag(e)
            when = f", found {lag}d earlier" if lag is not None else ""
            print(f"      + {e.get('name', '?')}{when} — {e.get('source', '?')[:70]}")
        if n_enrolled > 5:
            print(f"      + ...and {n_enrolled - 5} more")

    print()
    print(f"  Attributed: {attributed} of {total_enrolled} enrollments this window.")
    if legacy:
        print(f"  Unattributable (enrolled before {PROVENANCE_SINCE}, when `source` started")
        print(f"    being carried onto outcome buckets): {legacy}. Expected; drains on its own.")
    if unattributed:
        print(f"  No source despite being enrolled on/after {PROVENANCE_SINCE}: {unattributed}.")
        print("    Usually hand-enrolled, or `harvest_ats.py --names` on a name that was never")
        print("    queued. Worth a look only if this grows.")


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


def _norm(s):
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def _status_text(card):
    """company_status is a list on some cards and a string on others."""
    raw = card.get("company_status") or ""
    return (",".join(raw) if isinstance(raw, list) else str(raw)).lower()


def load_linkedin_cards(cutoff, today):
    """Every graded card in the window, deduped by LinkedIn job id.

    LinkedIn re-sends the same role across days and across saved searches, so the
    raw card count overstates reach by roughly 2x. Dedupe by job id and keep the
    first sighting; `seen_times` records the recurrence so a role that alerted six
    days running is visibly different from one that appeared once.
    """
    unique, raw_total, files = {}, 0, 0
    for path in sorted(glob.glob(LINKEDIN_CARDS_GLOB)):
        try:
            with open(path) as fh:
                doc = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        run_date = doc.get("run_date") or ""
        if not (cutoff.isoformat() <= run_date <= today.isoformat()):
            continue
        files += 1
        for card in doc.get("cards", []):
            raw_total += 1
            key = card.get("job_id") or (_norm(card.get("company")) + _norm(card.get("title")))
            if key in unique:
                unique[key]["seen_times"] += 1
            else:
                card = dict(card)
                card["seen_times"] = 1
                unique[key] = card
    return list(unique.values()), raw_total, files


def classify_card(card, tailored_pairs, tailored_companies):
    company, title = _norm(card.get("company")), _norm(card.get("title"))
    status = _status_text(card)
    if (company, title) in tailored_pairs:
        return "tailored"
    if company in tailored_companies:
        return "company_worked"
    if card.get("blind_spot"):
        return "blind_spot"
    if "reject" in status:
        return "unpollable"
    if "watchlist" in status or "enrolled" in status:
        return "pollable_not_picked"
    if "pending" in status:
        return "queued"
    return "unknown"


def load_tailored_index(path="pipeline/outcomes.csv"):
    """Company/title pairs that ever reached outcomes.csv, at any stage."""
    import csv
    pairs, companies = set(), set()
    try:
        with open(path, newline="") as fh:
            for row in csv.DictReader(fh):
                c, t = _norm(row.get("company")), _norm(row.get("title"))
                if c:
                    companies.add(c)
                    pairs.add((c, t))
    except OSError:
        pass
    return pairs, companies


def print_linkedin_cards_section(cards, raw_total, files, cutoff, today):
    print()
    print("=== LinkedIn alerts: what was in them and where it went ===")
    if not files:
        print("No linkedin_cards_*.json files in this window. Either Step 1d-2 did not run,")
        print("or it ran before harvest_linkedin.py started writing card files (2026-09-02).")
        return

    pairs, companies = load_tailored_index()
    strong = [c for c in cards
              if c.get("title_tier") in STRONG_CARD_TIERS
              and (c.get("location_points") or 0) > 0
              and not c.get("hard_excluded")]

    print(f"{raw_total} cards across {files} day(s), {len(cards)} unique roles after deduping")
    print(f"by LinkedIn job id. LinkedIn re-sends the same role across days and saved searches,")
    print(f"so the raw count roughly doubles the real reach; the unique number is the honest one.")
    print()
    print(f"STRONG roles (tier1/tier2/tier2c/tier2d AND Atlanta or remote-US): {len(strong)}")
    print("tier3 is excluded on purpose: it is a stretch title that only earns tailoring above")
    print("88, so a tier3 card going nowhere is the rubric working rather than a leak.")
    if not strong:
        print("\nNo strong roles in the window. Nothing to validate.")
        return

    buckets = {}
    for card in strong:
        buckets.setdefault(classify_card(card, pairs, companies), []).append(card)

    print()
    print("Where the strong ones went:")
    for key, label in CARD_BUCKETS:
        hits = buckets.get(key, [])
        if not hits:
            continue
        print(f"  {label:<52} {len(hits):>3}  ({round(100 * len(hits) / len(strong))}%)")

    unreachable = [c for k in UNREACHABLE_BUCKETS for c in buckets.get(k, [])]
    if unreachable:
        pct = round(100 * len(unreachable) / len(strong))
        print()
        print(f"--- {len(unreachable)} of {len(strong)} strong roles ({pct}%) were at companies the "
              f"poller cannot reach ---")
        print("These are the ones you are noticing. The grading found them; the pipeline had no")
        print("board to watch, so they were never scored and never competed for a slot. Each needs")
        print("a hand decision: chase the company's own careers page, or let it drop.")
        print("Some names also appear in the unpollable punch list further down. That list is")
        print("company-level and drains a standing backlog; this one is role-level and only covers")
        print("this window, so the overlap is expected rather than a duplicate.")
        print()
        shown = sorted(unreachable, key=lambda c: (c.get("title_tier") or "", c.get("company") or ""))
        for card in shown[:LINKEDIN_PUNCHLIST_CAP]:
            recur = f" x{card['seen_times']}" if card.get("seen_times", 1) > 1 else ""
            print(f"  [{card.get('title_tier','?'):<6} | {card.get('location_verdict','?'):<11}] "
                  f"{(card.get('company') or '?')[:26]:<26} {(card.get('title') or '?')[:44]}{recur}")
            print(f"      {card.get('url') or 'no link captured'}")
        if len(shown) > LINKEDIN_PUNCHLIST_CAP:
            print(f"  ... and {len(shown) - LINKEDIN_PUNCHLIST_CAP} more, held back to keep this readable.")

    missed = buckets.get("pollable_not_picked", [])
    if missed:
        print()
        print(f"--- {len(missed)} strong roles at companies the poller DOES watch, "
              f"never picked ---")
        print("A different problem, and a more interesting one: the board was scanned and the role")
        print("still lost. Usually location scoring or the shortlist rank cutoff. Worth a look if")
        print("any of these read better to you than what did surface that week.")
        print()
        for card in sorted(missed, key=lambda c: c.get("company") or ""):
            recur = f" x{card['seen_times']}" if card.get("seen_times", 1) > 1 else ""
            print(f"  [{card.get('title_tier','?'):<6} | {card.get('location_verdict','?'):<11}] "
                  f"{(card.get('company') or '?')[:26]:<26} {(card.get('title') or '?')[:44]}{recur}")
            print(f"      {card.get('url') or 'no link captured'}")

    queued = len(buckets.get("queued", [])) + len(buckets.get("unknown", []))
    if queued:
        print()
        print(f"{queued} more were at companies not yet enrolled when the alert arrived. Those are a")
        print("timing cost rather than a structural one: the company gets enrolled within a day or")
        print("two and the poller watches it from then on, but that specific requisition may be gone.")


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
        # Attribution reads the enrollment queue, not the run files, so it still
        # has something to say on a week where every run file is missing its
        # channel_stats block.
        print_attribution_section(*load_attribution(cutoff, today), cutoff, today)
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
    # Matched exact-lowercase "degraded" until 2026-09-10, but the runs write prose
    # ("DEGRADED (self-reported; queue untouched)"), so a permanently degraded feeder
    # reported as healthy on 0 of N days. Match by case-insensitive prefix instead.
    remotive_degraded_days = sum(
        1 for _, cs in rows
        if str(cs.get("feeders", {}).get("poll_remotive_status") or "").strip().lower().startswith("degraded")
    )

    tailored_total = sum_field(rows, "_tailored_count")

    print()
    print(f"ATS poll (execution layer, runs every day):")
    print(f"  companies polled (latest-day snapshot varies; summed across {len(rows)} days): {ats_polled}")
    print(f"  jobs scanned: {ats_scanned}  |  title matches: {ats_matched}  |  shortlisted: {ats_shortlisted}")
    print()
    print(f"WebSearch discovery ({ws_sources} source-runs across {len(rows)} days):")
    print(f"  new companies found: {ws_new}  |  enrolled ON THE SAME RUN: {ws_enrolled}")
    print(f"  (same-run enrollment is near-impossible by design — see Enrollment attribution below)")
    print()
    print(f"LinkedIn harvest ({li_threads} threads, {li_companies} companies extracted):")
    print(f"  enrolled ON THE SAME RUN: {li_enrolled}  |  blind-spot real hits "
          f"(unpollable but real): {li_blind_spot}")
    print(f"  (volume only -- see 'LinkedIn alerts: what was in them and where it went' below")
    print(f"   for the per-role disposition, which is the part that says whether this works)")
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

    print_attribution_section(*load_attribution(cutoff, today), cutoff, today)

    print_linkedin_cards_section(*load_linkedin_cards(cutoff, today), cutoff, today)

    batch, remaining, total_unsurfaced = load_unpollable_batch()
    print_unpollable_section(batch, remaining, total_unsurfaced)
    if args.apply:
        mark_surfaced(batch)


if __name__ == "__main__":
    main()
