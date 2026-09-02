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


# Corporate boilerplate that shouldn't block a match: "Blueprint" should hit
# "Blueprint Technologies", "Coca-Cola" should hit "The Coca-Cola Company".
_STOP_TOKENS = {"inc", "llc", "corp", "corporation", "company", "co", "the",
                "ltd", "group", "technologies", "labs", "software"}


def _tokens(s: str) -> frozenset:
    toks = {t for t in "".join(c if c.isalnum() else " " for c in (s or "").lower()).split()}
    core = toks - _STOP_TOKENS
    return frozenset(core or toks)


def hit(query: str, candidate: str) -> bool:
    """Whole-token match, either direction, plus joined-string equality (slugs).

    REWRITTEN 2026-09-01. The original was bidirectional SUBSTRING containment
    on alnum-collapsed strings, which produced four false "already known" hits
    in three days -- 'Ada' inside 'r-ADA-i' (Rad AI, 2026-08-31), 'Vanta'
    inside 'Hitachi VANTAra', 'EY' inside 'harv-EY', 'Meta' inside 'na-META-g'
    (all 2026-09-01). A false already-known is the one failure mode this tool
    exists to prevent inverted: it silently discards a genuinely new company.
    Every one was caught only because a human read the output.

    Token-subset keeps the intended hits (Blueprint / Blueprint Technologies,
    Coca-Cola / The Coca-Cola Company, Hawk-Eye / Hawk-Eye Innovations) while
    killing intra-word collisions. Joined equality keeps exact slug matches
    ('radai' vs 'radai'). Deliberately lost: partial-slug containment like
    'clutch' vs slug 'withclutch' -- the display NAME still matches in every
    such case on the current watchlist, checked before shipping.
    """
    q, c = norm(query), norm(candidate)
    if not (q and c):
        return False
    if q == c:
        return True
    qt, ct = _tokens(query), _tokens(candidate)
    return bool(qt and ct) and (qt <= ct or ct <= qt)


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


def lookup(query: str, watchlist: dict, enrollment: dict) -> list[tuple[str, dict]]:
    """Every known entry `query` hits, as (where, entry) pairs, in the order the CLI
    reports them: "watchlist", then the manual-coverage blocks ("blind_spot_companies",
    "unpollable_backlog_companies"), then "pending" / "enrolled" / "rejected".

    Extracted 2026-09-02 so harvest_linkedin.py can grade a card's company with the
    exact surface this CLI reports on -- including WHICH surface, since a blind-spot hit
    needs different handling from a pending one (Step 1d-2 item 3b). An empty list is
    the CLI's UNKNOWN.
    """
    out = []
    for c in watchlist.get("companies", []):
        if hit(query, c.get("name", "")) or hit(query, c.get("slug", "")):
            out.append(("watchlist", c))
    # These blocks were NOT searched before 2026-08-25, so this tool returned
    # UNKNOWN for Home Depot, Delta, Equifax, and Cox Automotive -- all of
    # which ARE covered by the blind-spot rotation. Since a result of UNKNOWN
    # is what sends a company to `pending`, the omission caused real wasted
    # cycles: Microsoft was queued, failed ATS resolution, and was rejected
    # 2026-07-29 with the note "Already covered by _blind_spot_companies
    # rotation. Enrolling would duplicate that coverage."
    for block in MANUAL_BLOCKS:
        for c in watchlist.get(block, {}).get("companies", []):
            if hit(query, c.get("name", "")):
                out.append((block.strip("_"), c))
    for bucket in ("pending", "enrolled", "rejected"):
        for e in enrollment.get(bucket, []):
            if hit(query, e.get("name", "")) or hit(query, e.get("slug") or ""):
                out.append((bucket, e))
    return out


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

        for where, c in lookup(query, watchlist, enrollment):
            found = True
            if where == "watchlist":
                print(f"  WATCHLIST: {c['name']} ({c.get('ats')}/{c.get('slug')})"
                      f"{'  [' + c['headcount_band'] + ']' if c.get('headcount_band') else ''}")
                if c.get("board_status"):
                    print(f"    board_status: {c['board_status']}")
                if c.get("reason"):
                    print(f"    reason: {c['reason'][:200]}")
            elif where in ("pending", "enrolled", "rejected"):
                date_field = (c.get("rejected_date") or c.get("enrolled_date")
                              or c.get("first_seen") or "?")
                print(f"  ENROLLMENT/{where.upper()}: {c['name']} ({date_field})")
                detail = c.get("reason") or c.get("notes") or c.get("why") or ""
                if detail:
                    print(f"    {detail[:250]}")
            else:
                print(f"  {where.upper()}: {c['name']}"
                      f" (last_checked {c.get('last_checked', '?')})")
                if c.get("why"):
                    print(f"    {c['why'][:200]}")

        if not found:
            all_known = False
            print("  UNKNOWN — not on the watchlist or in any enrollment bucket;"
                  " safe to treat as a new discovery.")
        print()

    sys.exit(0 if all_known else 1)


if __name__ == "__main__":
    main()
