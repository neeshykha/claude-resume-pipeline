#!/usr/bin/env python3
"""Picks which _websearch_sources to run today, and records which ones actually ran.

Usage:
    .venv/bin/python pipeline/websearch_rotation.py                    # what's due today
    .venv/bin/python pipeline/websearch_rotation.py --all              # every active source
    .venv/bin/python pipeline/websearch_rotation.py -n 10              # override the slot count
    .venv/bin/python pipeline/websearch_rotation.py --mark "BuiltIn Atlanta" "Lever Boards - Target Roles"

Why this exists (added 2026-08-23). Step 1c used to say "run every active daily source,"
which is 16 WebSearch calls whose results all land in the run's context. On heavy days that
competes directly with JD retrieval and tailoring, and the way it lost was by being skipped:
2026-08-21 skipped Step 1c outright, and 2026-08-23 ran 4 of 16. A skipped step is invisible;
a rotation is not.

The measured tradeoff, over the 11 runs that carry `channel_stats` (2026-08-10 onward):
WebSearch discovery produced 46 new companies and 13 enrollments across 121 source-runs, so
roughly 9 source-runs per company actually enrolled. The LinkedIn harvest produced 21
enrollments from one Gmail call per run. WebSearch discovery works, but the marginal source
is expensive, so spreading the sweep over several days costs far less than it looks.

The reason a multi-day gap is cheap here specifically: **these sources discover COMPANIES,
not today's jobs.** An unfamiliar company on an Ashby dork today is still there in three days,
and once enrolled the poller scans its entire roster daily, forever. That is the same argument
`daily_task_prompt.md` Step 1d-2 already makes for harvesting companies rather than roles from
LinkedIn; it just never got applied to the dorks. Contrast the ATS poll, where a fresh req
genuinely decays and daily really does mean daily.

Rotation applies ONLY to `frequency: "daily"` sources. Monthly sources keep their own
month-based gating and never consume a rotation slot; this script reports their due state
separately so they cannot be forgotten.

`--mark` takes the sources you ACTUALLY ran, not the ones this script proposed. If the run
gets through 4 of 6, mark 4. Marking a source you skipped pushes it to the back of the
queue and is the one way this mechanism can silently lose coverage.
"""
import argparse
import datetime
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST = os.path.join(SCRIPT_DIR, "watchlist_companies.json")
DEFAULT_ROTATION = 6


def load():
    with open(WATCHLIST, encoding="utf-8") as f:
        return json.load(f)


def save(data):
    tmp = WATCHLIST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, WATCHLIST)


def sort_key(src):
    """Oldest first, nulls first, name as a stable tie-break.

    A missing or malformed `last_run` sorts to the very front rather than being
    dropped: an unparseable date must mean 'run it', never 'skip it silently'.
    """
    lr = src.get("last_run")
    if not isinstance(lr, str) or not lr.strip():
        return ("", src.get("name", ""))
    return (lr.strip(), src.get("name", ""))


def month_of(s):
    return s[:7] if isinstance(s, str) and len(s) >= 7 else ""


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--all", action="store_true",
                    help="print every active source, ignoring the rotation")
    ap.add_argument("-n", "--slots", type=int, default=None,
                    help="override rotation_per_run for this call")
    ap.add_argument("--mark", nargs="+", metavar="NAME",
                    help="record today's date on the sources that actually ran")
    ap.add_argument("--today", default=None,
                    help="override today's date (YYYY-MM-DD), for testing")
    args = ap.parse_args()

    today = args.today or datetime.date.today().isoformat()
    data = load()
    block = data["_websearch_sources"]
    sources = block.get("sources", [])
    by_name = {s.get("name"): s for s in sources}

    if args.mark:
        unknown = [n for n in args.mark if n not in by_name]
        if unknown:
            print("unknown source name(s): " + ", ".join(repr(n) for n in unknown),
                  file=sys.stderr)
            print("\nvalid names:", file=sys.stderr)
            for s in sources:
                print(f"  {s.get('name')}", file=sys.stderr)
            return 2
        for n in args.mark:
            by_name[n]["last_run"] = today
        save(data)
        print(f"marked {len(args.mark)} source(s) as run on {today}:")
        for n in args.mark:
            print(f"  {n}")
        return 0

    active = [s for s in sources if s.get("status") == "active"]
    daily = [s for s in active if s.get("frequency") == "daily"]
    monthly = [s for s in active if s.get("frequency") == "monthly"]
    other = [s for s in active if s.get("frequency") not in ("daily", "monthly")]

    slots = args.slots if args.slots is not None else block.get(
        "rotation_per_run", DEFAULT_ROTATION)
    ordered = sorted(daily, key=sort_key)
    selected = ordered if args.all else ordered[:slots]

    print(f"today: {today}")
    print(f"active daily sources: {len(daily)}   "
          f"{'ALL (rotation bypassed)' if args.all else f'rotation_per_run: {slots}'}")
    print()
    print("=== RUN THESE ===")
    for s in selected:
        lr = s.get("last_run") or "never"
        print(f"\n[{s.get('name')}]  last_run: {lr}")
        print(f"  {s.get('query')}")

    if not args.all:
        deferred = ordered[slots:]
        print()
        print(f"=== DEFERRED ({len(deferred)}) ===")
        for s in deferred:
            print(f"  {s.get('name'):<45} last_run: {s.get('last_run') or 'never'}")

        stale = [s for s in ordered
                 if isinstance(s.get('last_run'), str)
                 and (datetime.date.fromisoformat(today)
                      - datetime.date.fromisoformat(s['last_run'])).days > 7]

        # A freshly seeded config has every source at null, so a never-run alarm
        # would fire on all of them and mean nothing. Suppress it until the first
        # full cycle has had time to complete: ceil(sources/slots) runs, plus a day
        # of slack. After that a null genuinely is a source falling through.
        never = [s for s in ordered if not s.get("last_run")]
        seeded = block.get("rotation_seeded")
        if never and isinstance(seeded, str) and slots > 0:
            cycle_days = -(-len(ordered) // slots) + 1
            if (datetime.date.fromisoformat(today)
                    - datetime.date.fromisoformat(seeded)).days <= cycle_days:
                never = []

        if stale or never:
            print()
            print("STALENESS ALARM: a rotation is only honest if nothing rots at the back "
                  "of it.")
            for s in never:
                print(f"  never run: {s.get('name')}")
            for s in stale:
                age = (datetime.date.fromisoformat(today)
                       - datetime.date.fromisoformat(s['last_run'])).days
                print(f"  {age}d since last run: {s.get('name')}")
            print("  Carry this into the digest housekeeping section.")

    if monthly:
        print()
        print("=== MONTHLY (not part of the rotation, own gating) ===")
        for s in monthly:
            due = month_of(s.get("last_run")) != month_of(today)
            print(f"  [{'DUE' if due else 'done this month'}] {s.get('name'):<45} "
                  f"last_run: {s.get('last_run') or 'never'}")

    if other:
        print()
        print("=== UNKNOWN FREQUENCY (treated as daily-eligible, fix the config) ===")
        for s in other:
            print(f"  {s.get('name')}: frequency={s.get('frequency')!r}")

    print()
    print("After running them, record ONLY the ones that actually ran:")
    names = " ".join(f'"{s.get("name")}"' for s in selected)
    print(f"  .venv/bin/python pipeline/websearch_rotation.py --mark {names}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
