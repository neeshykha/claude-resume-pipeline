#!/usr/bin/env python3
"""Live + CASES tests for the ADP (WorkforceNow) adapter.

Run as: .venv/bin/python pipeline/test_adp.py

Two parts, per ats_contract.md section 8 items 1-2:

  PART 1 -- LIVE INTEGRATION (item 1). Resolves a REAL WorkforceNow board
  (Caliber Car Wash, cid=2fe51c8e-72c9-4ef8-b866-3bb618f66134, one of the five
  ADP backlog companies from the 2026-09-11 provider sweep), finds a named
  real requisition on it ("Site Manager", Cross Roads TX, requisition ID
  2436), and asserts poll_ats.fetch_adp() parses its title, location, and
  apply URL correctly. Written to fail before poll_ats.fetch_adp existed --
  the first run of this file (2026-09-18, before any adapter code landed in
  poll_ats.py) failed with AttributeError: module 'poll_ats' has no attribute
  'fetch_adp'. That failing run is recorded in the build report, not here,
  since this file's job is to pass once the adapter exists.

  Caliber's board changes daily (live job postings), so this only asserts
  that the ONE requisition ID 2436 is present with the expected fields --
  not that it's the top of the list or that the board's total count is any
  particular number. If Caliber ever closes req 2436, this test needs a new
  target; that's a feature, not a bug, of testing against a real board.

  PART 2 -- NO-BOARD CLASSIFICATION (item 2), CASES form, in
  harvest_ats.probe_adp(). Real cid -> a list; bogus cid -> None (live,
  since ADP's 404 behavior on an unknown cid is exactly the fact under test
  and there's no safe way to fake it without losing coverage of the real
  behavior). The "real but empty" answer ([] on an honest zero-result JSON)
  is covered with a synthetic, safe-for-a-public-repo fixture via dependency
  injection -- no real company was ever observed with zero requisitions
  during this build, so this exercises the CODE PATH rather than a live
  company.
"""
import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import poll_ats           # noqa: E402
import harvest_ats         # noqa: E402
import ats_adp             # noqa: E402

CALIBER_CID = "2fe51c8e-72c9-4ef8-b866-3bb618f66134"
CALIBER_REQ_ID = "2436"          # clientRequisitionID
CALIBER_TITLE = "Site Manager"
CALIBER_LOCATION_CONTAINS = "Cross Roads, TX"
CALIBER_APPLY_URL_CONTAINS = "jobId=638063"

fails = 0
total = 0


def check(name, cond, detail=""):
    global fails, total
    total += 1
    if cond:
        print(f"[ok ] {name}")
    else:
        print(f"[FAIL] {name}  {detail}")
        fails += 1


# ---------------------------------------------------------------------------
# PART 1: live integration against one real requisition
# ---------------------------------------------------------------------------
print("=== PART 1: live integration (poll_ats.fetch_adp, Caliber Car Wash) ===")
company = {"name": "Caliber Car Wash", "ats": "adp", "slug": CALIBER_CID}
jobs = poll_ats.fetch_adp(company)

check("fetch_adp returned a non-empty list, no _error sentinel",
      bool(jobs) and not (isinstance(jobs[0], dict) and "_error" in jobs[0]),
      detail=str(jobs[:1]) if jobs else "empty result")

target = None
if jobs and not (isinstance(jobs[0], dict) and "_error" in jobs[0]):
    target = next((j for j in jobs if j.get("_adp_req_id") == CALIBER_REQ_ID), None)

check(f"requisition {CALIBER_REQ_ID} ('{CALIBER_TITLE}') is present on the board",
      target is not None,
      detail=f"present req ids: {[j.get('_adp_req_id') for j in (jobs or [])][:10]}")

if target:
    check("title == 'Site Manager'",
          target.get("title") == CALIBER_TITLE,
          detail=f"got {target.get('title')!r}")

    loc = poll_ats.parse_location(target, "adp")
    check(f"parse_location contains {CALIBER_LOCATION_CONTAINS!r}",
          CALIBER_LOCATION_CONTAINS in loc,
          detail=f"got {loc!r}")

    apply_url = poll_ats.build_apply_url(target, "adp", CALIBER_CID)
    check(f"build_apply_url contains {CALIBER_APPLY_URL_CONTAINS!r}",
          CALIBER_APPLY_URL_CONTAINS in apply_url,
          detail=f"got {apply_url!r}")
    check("build_apply_url is on workforcenow.adp.com",
          apply_url.startswith(f"https://{ats_adp.ADP_WFN_HOST}/"),
          detail=f"got {apply_url!r}")

    posted = poll_ats.extract_posted_date(target, "adp")
    check("extract_posted_date returns a date (or None -- never raises)",
          posted is None or hasattr(posted, "isoformat"))
else:
    print("  (skipping title/location/apply-url checks: requisition not found)")


# ---------------------------------------------------------------------------
# PART 2: no-board classification (harvest_ats.probe_adp), CASES form
# ---------------------------------------------------------------------------
print("\n=== PART 2: no-board classification (harvest_ats.probe_adp) ===")

# Real cid -> a list of (title, location) tuples, non-empty, live network.
result = harvest_ats.probe_adp(CALIBER_CID)
check("probe_adp(real cid) -> a non-empty list",
      isinstance(result, list) and len(result) > 0,
      detail=f"got {type(result)} len={len(result) if isinstance(result, list) else 'n/a'}")
if isinstance(result, list) and result:
    check("probe_adp(real cid) list entries are (title, location) tuples",
          all(isinstance(t, tuple) and len(t) == 2 for t in result[:5]),
          detail=str(result[:2]))
    check(f"'{CALIBER_TITLE}' appears among probed titles",
          any(t == CALIBER_TITLE for t, _loc in result),
          detail=str([t for t, _l in result][:10]))

# Bogus/nonexistent cid -> None. Live: ADP answers HTTP 404 for an unknown
# cid (verified 2026-09-18 with cid=00000000-0000-0000-0000-000000000000),
# which is the fact this case is actually testing -- faking it would test
# nothing about the real API.
BOGUS_CID = "00000000-0000-0000-0000-000000000000"
result_bogus = harvest_ats.probe_adp(BOGUS_CID)
check("probe_adp(bogus cid) -> None",
      result_bogus is None,
      detail=f"got {result_bogus!r}")


# Real board, zero requisitions -> []. No live company observed during this
# build has an empty board, so this is exercised with a synthetic fixture via
# dependency injection: probe_adp accepts a `get` callable (see its
# docstring), and this fake returns a well-formed, safe-for-a-public-repo
# job-requisitions response with meta.totalNumber=0.
class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _fake_get_empty_board(url, timeout=None):
    return _FakeResponse(200, {"jobRequisitions": [], "meta": {"totalNumber": 0}})


result_empty = harvest_ats.probe_adp("11111111-1111-1111-1111-111111111111",
                                      get=_fake_get_empty_board)
check("probe_adp(real-but-empty board, faked) -> []",
      result_empty == [],
      detail=f"got {result_empty!r}")


# Malformed / non-JSON 200 response -> None, never a crash.
def _fake_get_garbage(url, timeout=None):
    class _R:
        status_code = 200

        def json(self):
            raise ValueError("not json")
    return _R()


result_garbage = harvest_ats.probe_adp("22222222-2222-2222-2222-222222222222",
                                        get=_fake_get_garbage)
check("probe_adp(malformed JSON body) -> None, no exception",
      result_garbage is None,
      detail=f"got {result_garbage!r}")


print(f"\n{total - fails}/{total} passed")
sys.exit(1 if fails else 0)
