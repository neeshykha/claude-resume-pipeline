"""Check whether a company is already known to the pipeline before treating a
discovery hit as "unfamiliar."

Usage:
    .venv/bin/python pipeline/check_company.py <name-or-slug> [more names...]

Searches (case-insensitive substring, both directions) across:
  - watchlist_companies.json -> companies[].name / .slug
  - enrollment_candidates.json -> pending / enrolled / rejected

Prints one status block per query. Exit code 0 if every query matched
something, 1 if any query is genuinely unknown (safe to append to pending).

Why this exists: discovery dorks keep re-surfacing companies the pipeline
already tracks (Nash, Metronome, Lightrun, Cognite all reappeared on
2026-07-19), and the cross-check was a manual eyeball of two JSON files —
which is exactly how Nash nearly got double-enrolled that day.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WATCHLIST = os.path.join(HERE, "watchlist_companies.json")
ENROLLMENT = os.path.join(HERE, "enrollment_candidates.json")


def norm(s: str) -> str:
    return "".join(c for c in (s or "").lower() if c.isalnum())


def hit(query: str, candidate: str) -> bool:
    q, c = norm(query), norm(candidate)
    return bool(q and c) and (q in c or c in q)


# Manual-coverage blocks in watchlist_companies.json. These hold companies the
# poller structurally CANNOT reach but which ARE actively covered by a rotation,
# so a hit here means "already handled", not "new discovery".
MANUAL_BLOCKS = ("_blind_spot_companies", "_unpollable_backlog_companies")


def load_known() -> list[str]:
    """Every company name/slug the pipeline already knows, as a flat list.

    Importable so other harvesters dedupe against exactly the same surface this
    CLI reports on -- see harvest_vc_portfolios.py.
    """
    with open(WATCHLIST) as f:
        watchlist = json.load(f)
    with open(ENROLLMENT) as f:
        enrollment = json.load(f)

    out = []
    for c in watchlist.get("companies", []):
        out += [c.get("name", ""), c.get("slug", "") or ""]
    for block in MANUAL_BLOCKS:
        for c in watchlist.get(block, {}).get("companies", []):
            out.append(c.get("name", ""))
    for bucket in ("pending", "enrolled", "rejected"):
        for e in enrollment.get(bucket, []):
            out += [e.get("name", ""), e.get("slug") or ""]
    return [n for n in out if n]


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)

    with open(WATCHLIST) as f:
        watchlist = json.load(f)
    with open(ENROLLMENT) as f:
        enrollment = json.load(f)

    all_known = True
    for query in sys.argv[1:]:
        print(f"=== {query} ===")
        found = False

        for c in watchlist.get("companies", []):
            if hit(query, c.get("name", "")) or hit(query, c.get("slug", "")):
                found = True
                print(f"  WATCHLIST: {c['name']} ({c.get('ats')}/{c.get('slug')})"
                      f"{'  [' + c['headcount_band'] + ']' if c.get('headcount_band') else ''}")
                if c.get("board_status"):
                    print(f"    board_status: {c['board_status']}")
                if c.get("reason"):
                    print(f"    reason: {c['reason'][:200]}")

        # Fixed 2026-08-25: these blocks were NOT searched, so this tool returned
        # UNKNOWN for Home Depot, Delta, Equifax, and Cox Automotive -- all of
        # which ARE covered by the blind-spot rotation. Since a result of UNKNOWN
        # is what sends a company to `pending`, the omission caused real wasted
        # cycles: Microsoft was queued, failed ATS resolution, and was rejected
        # 2026-07-29 with the note "Already covered by _blind_spot_companies
        # rotation. Enrolling would duplicate that coverage."
        for block in MANUAL_BLOCKS:
            for c in watchlist.get(block, {}).get("companies", []):
                if hit(query, c.get("name", "")):
                    found = True
                    print(f"  {block.strip('_').upper()}: {c['name']}"
                          f" (last_checked {c.get('last_checked', '?')})")
                    if c.get("why"):
                        print(f"    {c['why'][:200]}")

        for bucket in ("pending", "enrolled", "rejected"):
            for e in enrollment.get(bucket, []):
                if hit(query, e.get("name", "")) or hit(query, e.get("slug") or ""):
                    found = True
                    date_field = (e.get("rejected_date") or e.get("enrolled_date")
                                  or e.get("first_seen") or "?")
                    print(f"  ENROLLMENT/{bucket.upper()}: {e['name']} ({date_field})")
                    detail = e.get("reason") or e.get("notes") or e.get("why") or ""
                    if detail:
                        print(f"    {detail[:250]}")

        if not found:
            all_known = False
            print("  UNKNOWN — not on the watchlist or in any enrollment bucket;"
                  " safe to treat as a new discovery.")
        print()

    sys.exit(0 if all_known else 1)


if __name__ == "__main__":
    main()
