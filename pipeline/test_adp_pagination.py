#!/usr/bin/env python3
"""Live pagination proof for the ADP adapter (ats_contract.md section 8 item 3).

Run as: .venv/bin/python pipeline/test_adp_pagination.py

Caliber Car Wash's own live WorkforceNow board (cid
2fe51c8e-72c9-4ef8-b866-3bb618f66134) is the proof board: its
meta.totalNumber was 58 as of 2026-09-18, well over ADP_PAGE_SIZE (20), and
the API's page size is server-CLAMPED at 20 regardless of the requested
$top (verified: $top=100 still returned exactly 20 rows). So a single-page
read of this board is structurally incomplete, and any correct multi-page
walk must read strictly more than one page's worth to reach the reported
total.

This calls poll_ats.fetch_adp() -- the real poller entry point, not a
reimplementation -- and checks:
  1. more than ADP_PAGE_SIZE distinct postings were read
  2. the count read equals the API's own reported total (meta.totalNumber
     from the first page), up to ADP_MAX_POSTINGS
  3. no duplicate itemIDs survived (the de-dup step actually worked, despite
     the observed skip-boundary overlap noted in fetch_adp's docstring)

Caliber's board is a live, changing set of real postings, so exact equality
with a number recorded in a comment would go stale. This re-reads the API's
own totalNumber on every run instead of hardcoding 58, so the assertion
stays valid as the board turns over.
"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import requests
import ats_adp
import poll_ats

CALIBER_CID = "2fe51c8e-72c9-4ef8-b866-3bb618f66134"


def main():
    # Ground truth: ask the API itself what its total is, independent of our
    # own pagination loop, so this isn't just checking our loop against itself.
    url = ats_adp.requisitions_url(CALIBER_CID, skip=0, top=ats_adp.ADP_PAGE_SIZE)
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (resume-pipeline-test)"},
                         timeout=30)
    resp.raise_for_status()
    page0, reported_total = ats_adp.extract_page(resp.json())

    print(f"Page size served by the API (requested top={ats_adp.ADP_PAGE_SIZE}): "
          f"{len(page0)} rows")
    print(f"API-reported meta.totalNumber: {reported_total}")

    fails = 0
    if reported_total is None:
        print("[FAIL] first page carried no meta.totalNumber -- can't prove anything")
        sys.exit(1)
    if reported_total <= ats_adp.ADP_PAGE_SIZE:
        print(f"[FAIL] board only has {reported_total} postings, <= one page "
              f"({ats_adp.ADP_PAGE_SIZE}) -- this board can't prove multi-page "
              f"pagination. Pick a bigger board.")
        sys.exit(1)
    print(f"[ok ] board total ({reported_total}) exceeds one page "
          f"({ats_adp.ADP_PAGE_SIZE}) -- a real multi-page walk is required")

    # Now the real thing: the poller's own fetch_adp, unmodified.
    company = {"name": "Caliber Car Wash", "ats": "adp", "slug": CALIBER_CID}
    jobs = poll_ats.fetch_adp(company)

    if jobs and isinstance(jobs[0], dict) and "_error" in jobs[0]:
        print(f"[FAIL] fetch_adp errored: {jobs[0]['_error']}")
        sys.exit(1)

    print(f"poll_ats.fetch_adp() read {len(jobs)} postings")

    expected = min(reported_total, poll_ats.ADP_MAX_POSTINGS)
    if len(jobs) == expected:
        print(f"[ok ] count read ({len(jobs)}) == expected "
              f"(min(reported total {reported_total}, cap {poll_ats.ADP_MAX_POSTINGS}) "
              f"= {expected})")
    else:
        print(f"[FAIL] count read ({len(jobs)}) != expected ({expected})")
        fails += 1

    if len(jobs) > ats_adp.ADP_PAGE_SIZE:
        print(f"[ok ] count read ({len(jobs)}) exceeds one page "
              f"({ats_adp.ADP_PAGE_SIZE}) -- pagination actually ran past page 1")
    else:
        print(f"[FAIL] count read ({len(jobs)}) did not exceed one page")
        fails += 1

    ids = [j.get("itemID") for j in jobs]
    if len(ids) == len(set(ids)):
        print(f"[ok ] no duplicate itemIDs across {len(jobs)} postings "
              f"(de-dup across the observed skip-boundary overlap held)")
    else:
        dupes = len(ids) - len(set(ids))
        print(f"[FAIL] {dupes} duplicate itemID(s) survived de-dup")
        fails += 1

    print(f"\n{'PASS' if not fails else 'FAIL'}: {3 - fails}/3 checks passed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
