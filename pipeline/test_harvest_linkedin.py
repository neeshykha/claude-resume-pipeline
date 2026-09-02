"""Self-check for harvest_linkedin.py: card parsing plus grading against the LIVE config.

    .venv/bin/python pipeline/test_harvest_linkedin.py

The fixture is a synthetic body in the exact shape LinkedIn sends (verified 2026-09-02
against 14 real bodies from both job senders), carrying the cards the 2026-09-02 retro
named as the expected findings. It contains no real addresses or tracking tokens, so it
is safe to keep in the public repo.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import harvest_linkedin as HL  # noqa: E402

TRK = "?trackingId=abc&refId=def&lipi=urn%3Ali%3Apage%3Aemail_email_job_alert_digest_01"
RULE = "---------------------------------------------------------"

BODY = f"""Your job alert for support operations manager in Atlanta

New jobs match your preferences.

Director of Customer Support
Cloudbeds
Atlanta, GA
View job: https://www.linkedin.com/comm/jobs/view/4461000001/{TRK}

{RULE}

Technical Account Manager (US Remote)
Upwind Security
United States

3 connections
View job: https://www.linkedin.com/comm/jobs/view/4461000002/{TRK}

{RULE}

Technical Account Manager
Vultr
United States

This company is actively hiring
View job: https://www.linkedin.com/comm/jobs/view/4461000003/{TRK}

{RULE}

Operations Enablement Lead
Swooped
United States
View job: https://www.linkedin.com/comm/jobs/view/4461000004/{TRK}

{RULE}

Support Delivery Manager
RemoteHunter
United States
View job: https://www.linkedin.com/comm/jobs/view/4461000005/{TRK}

{RULE}

Data Center Operations Manager
Google
Atlanta, GA

1 school alum
View job: https://www.linkedin.com/comm/jobs/view/4461000006/{TRK}

{RULE}

Customer Success Manager
Example Labs
Toronto, Ontario, Canada
View job: https://www.linkedin.com/comm/jobs/view/4461000007/{TRK}

{RULE}

GTM Systems Manager
Example Labs
Remote - United States
View job: https://www.linkedin.com/comm/jobs/view/4461000008/{TRK}

{RULE}

Deployment Strategist
Example Labs
Indianapolis, IN

This company is actively hiring
View job: https://www.linkedin.com/comm/jobs/view/4461000009/{TRK}

{RULE}

Mission Control Supervisor
Example Labs
Atlanta Metropolitan Area
Apply with resume & profile
View job: https://www.linkedin.com/comm/jobs/view/4461000010/{TRK}

{RULE}

See all jobs on LinkedIn: https://www.linkedin.com/comm/jobs/search-results/?x=y
"""

EXPECT = {
    # job_id: (title_tier, location_verdict, manual_review)
    "4461000001": ("tier1", "atlanta", True),      # Cloudbeds -- the retro's headline find
    "4461000002": ("tier2", "remote", True),       # Upwind Security TAM (US Remote)
    "4461000003": ("tier2", "us-national", True),  # Vultr TAM, bare United States
    "4461000006": ("none", "atlanta", False),      # Google, no tier; blind-spot company
    "4461000007": ("tier3", "non-us", False),      # Canada -> no review flag
    "4461000008": ("demoted", "remote", False),    # GTM Systems demotion must show
    "4461000009": ("tier2", "other", False),       # "india" must not fire inside Indianapolis
    "4461000010": ("none", "atlanta", False),      # "Apply with resume & profile" with no blank line
}
DROPPED = {"Swooped", "RemoteHunter"}


def main() -> int:
    fails = 0
    cards = HL.parse_cards(BODY)
    ids = [c["job_id"] for c in cards]
    if len(cards) != 10:
        print(f"FAIL parse: expected 10 cards, got {len(cards)}: {ids}")
        fails += 1
    for c in cards:
        if c["job_id"] == "4461000010" and (c["company"] != "Example Labs"
                                             or c["location"] != "Atlanta Metropolitan Area"):
            print(f"FAIL parse: apply-hint line shifted the card: {c}")
            fails += 1
    for c in cards:
        if c["job_id"] == "4461000002" and (c["company"] != "Upwind Security"
                                             or c["extra"] != "3 connections"):
            print(f"FAIL parse: extra-line card mis-split: {c}")
            fails += 1
        if c["job_id"] == "4461000001" and c["location"] != "Atlanta, GA":
            print(f"FAIL parse: first card location: {c}")
            fails += 1
    if HL.alert_search(BODY) != "support operations manager in Atlanta":
        print(f"FAIL header: {HL.alert_search(BODY)!r}")
        fails += 1

    with open(os.path.join(HERE, "watchlist_companies.json"), encoding="utf-8") as f:
        wl = json.load(f)
    with open(os.path.join(HERE, "enrollment_candidates.json"), encoding="utf-8") as f:
        enrollment = json.load(f)
    grader = HL.Grader(wl, enrollment)

    records = [{"id": "m1", "thread_id": "t1", "sender": HL.JOB_SENDERS[0],
                "subject": "Director of Customer Support at Cloudbeds",
                "date": "2026-09-02T06:19:21Z", "body": BODY, "source": "fixture"}]
    import datetime as dt
    res = HL.harvest(records, grader, dt.date(2026, 9, 2),
                     {"query": "q", "window_used": "2d", "input_mode": "fixture"})
    c = res["counters"]
    by_id = {g["job_id"]: g for g in res["cards"]}

    for jid, (tier, verdict, review) in EXPECT.items():
        g = by_id.get(jid)
        if g is None:
            print(f"FAIL {jid}: card missing from graded output")
            fails += 1
            continue
        got = (g["title_tier"], g["location_verdict"], g["manual_review"])
        if got != (tier, verdict, review):
            print(f"FAIL {jid} {g['company']}: {g['title']!r} -> {got}, want {(tier, verdict, review)}")
            fails += 1
    if set(c["aggregators_dropped"]) != DROPPED:
        print(f"FAIL aggregators: {c['aggregators_dropped']} want {sorted(DROPPED)}")
        fails += 1
    if any(g["company"] in DROPPED for g in res["cards"]):
        print("FAIL aggregator card reached the graded list")
        fails += 1
    if not by_id["4461000006"]["blind_spot"]:
        print("FAIL Google should resolve to _blind_spot_companies")
        fails += 1
    if c["job_alert_threads_seen"] != 1 or c["bodies_read"] != 1:
        print(f"FAIL counters: {c}")
        fails += 1
    first = res["digest_lines"][0] if res["digest_lines"] else ""
    if not first.startswith("[tier1 | Atlanta] Cloudbeds: Director of Customer Support | 4461000001"):
        print(f"FAIL digest ordering/format: {first!r}")
        fails += 1
    # Example Labs is unknown to every surface and must queue with the review flag off
    # (its best card is the demoted GTM one; the other is Canada).
    pend = {e["name"]: e for e in res["pending_entries"]}
    if "Example Labs" not in pend or pend["Example Labs"].get("manual_review"):
        print(f"FAIL pending: {pend}")
        fails += 1

    print(f"{len(EXPECT)} graded expectations, {len(res['cards'])} cards, "
          f"{'ALL PASS' if not fails else str(fails) + ' FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
