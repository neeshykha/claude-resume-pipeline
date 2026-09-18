#!/usr/bin/env python3
"""Test bar for the iCIMS adapter, per docs/ats_contract.md section 8.

Usage:
    .venv/bin/python pipeline/test_icims.py

Four sections, matching the contract's four numbered items:

  1. Live integration -- resolve a REAL board (RealPage,
     careers-realpagepms.icims.com), find a named real requisition on it
     (req 14575, "Customer Success Manager II - HOA/Real Estate", verified
     live 2026-09-18), and parse title/location/apply URL. This section is
     WRITTEN TO FAIL before ats_icims.py/poll_ats.fetch_icims exist -- it was
     run against the pre-implementation tree (`git stash` of everything but
     this file) to capture the failing output the build report quotes
     verbatim, then re-run after implementing.
  2. No-board classification in CASES form: a bogus tenant -> None (live), a
     real tenant with jobs -> a list (live), a real tenant whose classic page
     is only a client redirect to a custom front end (GitHub) -> None (live,
     see ats_icims.py's docstring), and a resolved-but-EMPTY board -> []
     (OFFLINE FAKE: no live empty iCIMS board is known to this build, so this
     one case is a controlled fake of a genuine classic page with zero
     `iCIMS_JobCardItem` blocks, monkeypatching harvest_ats._get for one call).
  3. Pagination past page 1, live against Peraton (careers-peraton.icims.com,
     1526 reqs / 31 pages @ 50/page as of 2026-09-18): the count read exceeds
     one page and is capped at ats_icims.ICIMS_MAX_POSTINGS (500) rather than
     the board's full total, proving the cap engages on a board that needs it.
  4. Budget under a simulated hang: a local TCP server (stdlib socket only)
     that accepts a connection and never answers, with the harvest probe's
     iCIMS endpoint template monkeypatched to point at it. Asserts the probe
     returns None (not an exception, not a hang) within budget + ~1s.

Network required for sections 1-3 (live RealPage/Peraton/GitHub) and for
section 2's bogus-tenant case (live 404). Section 2's empty-board case and
section 4 run with no live iCIMS dependency.
"""
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poll_ats
import harvest_ats as H
import ats_icims as ICIMS  # noqa: F401 (kept for parity with other adapters' tests)

LIVE_TENANT = "realpagepms"           # RealPage -- small board, live-integration target
PAGINATION_TENANT = "peraton"         # Peraton -- 1526 reqs / 31 pages, pagination proof
REDIRECT_SKIN_TENANT = "githubinc"    # GitHub -- real tenant, unreadable custom skin
KNOWN_REQ_TITLE_SUBSTR = "Customer Success Manager II"  # req 14575, verified live 2026-09-18

fails = 0
total = 0


def check(ok, label):
    global fails, total
    total += 1
    if not ok:
        fails += 1
    print(f"[{'ok ' if ok else 'FAIL'}] {label}")
    return ok


# ---------------------------------------------------------------------------
# Section 1: live integration
# ---------------------------------------------------------------------------
print("=== Section 1: live integration (RealPage) ===")
jobs = poll_ats.fetch_icims(LIVE_TENANT)
board_ok = bool(jobs) and not (isinstance(jobs[0], dict) and "_error" in jobs[0])
check(board_ok, f"fetch_icims({LIVE_TENANT!r}) returns a non-error job list "
                f"({len(jobs) if board_ok else 0} jobs"
                f"{'' if board_ok else ': ' + str(jobs[0].get('_error')) if jobs else ' (empty)'})")

found = None
if board_ok:
    for j in jobs:
        if KNOWN_REQ_TITLE_SUBSTR.lower() in (j.get("title") or "").lower():
            found = j
            break
check(found is not None, f"named requisition found (title contains {KNOWN_REQ_TITLE_SUBSTR!r})")

if found:
    title = found.get("title", "")
    location = poll_ats.parse_location(found, "icims")
    apply_url = poll_ats.build_apply_url(found, "icims", LIVE_TENANT)
    print(f"      title     = {title!r}")
    print(f"      location  = {location!r}")
    print(f"      apply_url = {apply_url!r}")
    check(bool(title), "title parsed (non-empty)")
    check(location not in (None, "", "Unknown"), "location parsed (not Unknown/empty)")
    check(bool(apply_url) and apply_url.startswith("https://careers-") and "/job" in apply_url,
          "apply URL parsed and well-formed (careers-*.icims.com/.../job)")
else:
    print("      (skipped title/location/apply-url checks -- requisition not found)")


# ---------------------------------------------------------------------------
# Section 2: no-board classification, CASES form
# ---------------------------------------------------------------------------
print("\n=== Section 2: no-board classification (CASES) ===")


def fake_empty_page(url, budget=None):
    """A genuine classic iCIMS page shape with zero postings (no live example known)."""
    class R:
        status_code = 200
        text = ('<div class="container-fluid iCIMS_SearchResultsHeader">'
                '<h2 class="iCIMS_SubHeader iCIMS_SubHeader_Jobs">Search Results\n'
                'Page 1 of 1\n</h2></div>'
                '<ul class="container-fluid iCIMS_JobsTable"></ul>')
    return R()


CASES = [
    ("_bogus_live", "zzqxnotreal-icims-adapter-test-9f3d", None,
     "bogus tenant, live 404 -> probe() returns None"),
    ("_real_live", LIVE_TENANT, "list", "real tenant with jobs, live -> probe() returns a list"),
    ("_redirect_skin_live", REDIRECT_SKIN_TENANT, None,
     "real tenant, live 200 but only a client redirect to a custom front end "
     "(GitHub) -> probe() returns None, not a false empty board"),
]

for kind, slug, expect, why in CASES:
    got = H.probe("icims", slug, None)
    ok = (got is None) if expect is None else (isinstance(got, list) and len(got) > 0)
    shown = "None" if got is None else f"list[{len(got)}]"
    check(ok, f"probe('icims', {slug!r}) -> {expect}  ({why})  got={shown}")

# Offline: resolved-but-empty board -> [].
real_get = H._get
H._get = fake_empty_page
try:
    got_empty = H.probe("icims", "_offline_fake_empty_tenant", None)
finally:
    H._get = real_get
check(got_empty == [], "probe('icims', ...) on a resolved-but-EMPTY page -> [] "
                       "(offline fake -- no live empty iCIMS board known to this build)")


# ---------------------------------------------------------------------------
# Section 3: pagination past page 1, live
# ---------------------------------------------------------------------------
print("\n=== Section 3: pagination past page 1 (Peraton, live) ===")
t0 = time.monotonic()
paged_jobs = poll_ats.fetch_icims(PAGINATION_TENANT)
elapsed_fetch = time.monotonic() - t0
paged_ok = bool(paged_jobs) and not (isinstance(paged_jobs[0], dict) and "_error" in paged_jobs[0])
check(paged_ok, f"fetch_icims({PAGINATION_TENANT!r}) returns a non-error job list "
                f"({len(paged_jobs) if paged_ok else 0} jobs, {elapsed_fetch:.1f}s)")
check(paged_ok and len(paged_jobs) > ICIMS.ICIMS_PAGE_SIZE,
      f"read more than one page's worth ({ICIMS.ICIMS_PAGE_SIZE}/page): "
      f"got {len(paged_jobs) if paged_ok else 0}")
check(paged_ok and len(paged_jobs) == ICIMS.ICIMS_MAX_POSTINGS,
      f"capped at ICIMS_MAX_POSTINGS ({ICIMS.ICIMS_MAX_POSTINGS}): "
      f"got {len(paged_jobs) if paged_ok else 0}")

probe_paged = H.probe("icims", PAGINATION_TENANT, None)
check(isinstance(probe_paged, list) and len(probe_paged) == ICIMS.ICIMS_MAX_POSTINGS,
      f"harvest_ats.probe() reads the SAME cap as the poller: "
      f"got {len(probe_paged) if isinstance(probe_paged, list) else type(probe_paged).__name__}")


# ---------------------------------------------------------------------------
# Section 4: budget under a simulated hang (stdlib only, no live iCIMS needed)
# ---------------------------------------------------------------------------
print("\n=== Section 4: budget under a simulated hang ===")


def start_hanging_server():
    """Accepts one connection and never answers -- standard library only."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    port = srv.getsockname()[1]
    stop = threading.Event()

    def serve():
        srv.settimeout(0.5)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            # Hold the connection open, sending nothing, until the test ends.
            threading.Thread(target=lambda c=conn: (time.sleep(30), c.close()),
                             daemon=True).start()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    return port, srv, stop


port, srv, stop = start_hanging_server()
template = (f"http://127.0.0.1:{port}/jobs/search"
           f"?pr={{page}}&in_iframe=1&searchRelation=keyword_all")
real_endpoint = H._ICIMS_ENDPOINT
H._ICIMS_ENDPOINT = template
BUDGET_SECONDS = 3
budget = H.Budget(BUDGET_SECONDS)
t0 = time.monotonic()
try:
    hang_result = H.probe("icims", "anytenant", budget)
    hang_exc = None
except Exception as e:  # noqa: BLE001
    hang_result = None
    hang_exc = e
finally:
    elapsed = time.monotonic() - t0
    H._ICIMS_ENDPOINT = real_endpoint
    stop.set()
    try:
        srv.close()
    except OSError:
        pass

print(f"      elapsed={elapsed:.2f}s  budget={BUDGET_SECONDS}s  "
     f"result={hang_result!r}  exception={hang_exc!r}")
check(hang_exc is None, "probe() did not raise on a hung socket")
check(hang_result is None, "probe() returned None (no board could be confirmed) rather than hanging")
check(elapsed <= BUDGET_SECONDS + 1.5,
      f"elapsed {elapsed:.2f}s is within budget + ~1s ({BUDGET_SECONDS + 1.5}s)")


print(f"\n{total - fails}/{total} passed")
sys.exit(1 if fails else 0)
