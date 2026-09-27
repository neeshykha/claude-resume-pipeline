"""Live + offline checks for the Gem ATS adapter (pipeline/ats_gem.py), per
docs/ats_contract.md section 8, items 1-4.

Written to fail before ats_gem.py and its wiring existed (2026-09-18): item 1
below imports ats_gem directly, which is a plain ImportError pre-adapter.

Network-dependent pieces (1, 3) hit the real jobs.gem.com API -- there is no
sandbox for it -- and are expected to keep passing as long as Retool and
Function Health keep their boards open under these slugs. Items 2 and 4 are
fully offline (2's "empty board" case is synthetic parsing, not a network
call, because no genuinely-empty live Gem board was found during this build;
see item 2's comment).

Run: .venv/bin/python pipeline/test_gem.py
"""
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ats_gem          # noqa: E402
import harvest_ats       # noqa: E402
import poll_ats           # noqa: E402

fails = 0
total = 0


def check(ok, label, detail=""):
    global fails, total
    total += 1
    if not ok:
        fails += 1
    print(f"[{'ok ' if ok else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))


# ─────────────────────────────────────────────────────────────────────────
# 1. LIVE INTEGRATION: resolve a real board, find a named real requisition,
#    parse its title, location, and apply URL.
# ─────────────────────────────────────────────────────────────────────────
print("=" * 78)
print("1. Live integration: jobs.gem.com/retool")
print("=" * 78)

jobs = ats_gem.fetch_gem("retool")
check(isinstance(jobs, list) and jobs and "_error" not in jobs[0],
      "fetch_gem('retool') returns a non-empty board",
      detail=str(jobs[:1]) if (not jobs or "_error" in (jobs[0] if jobs else {})) else f"{len(jobs)} postings")

named = next((j for j in jobs if j.get("title") == "Software Engineer"), None) if jobs and "_error" not in jobs[0] else None
check(named is not None, "board carries a real 'Software Engineer' requisition")

if named:
    loc = poll_ats.parse_location(named, "gem")
    url = poll_ats.build_apply_url(named, "gem", "retool")
    print(f"      title    = {named.get('title')!r}")
    print(f"      location = {loc!r}")
    print(f"      apply    = {url!r}")
    # This posting's job.locationType is HYBRID on the live board (verified
    # 2026-09-18), so the "Hybrid" prefix _apply_workplace_label adds is
    # correct behavior, not a bug -- the expectation here is the observed
    # live value, not a guess.
    check(loc == "Hybrid San Francisco", "parsed location matches the board's San Francisco office (+ Hybrid prefix)", detail=loc)
    check(url == f"https://jobs.gem.com/retool/{named.get('extId')}",
          "apply URL is https://jobs.gem.com/retool/<extId>", detail=url)

# ─────────────────────────────────────────────────────────────────────────
# 2. NO-BOARD CLASSIFICATION, CASES form.
# ─────────────────────────────────────────────────────────────────────────
print()
print("=" * 78)
print("2. No-board classification (harvest_ats.probe('gem', slug))")
print("=" * 78)

# (slug_or_None, expected "None"/"list"/"empty", why)
LIVE_CASES = [
    ("retool", "list", "real board with open postings -> a non-empty list"),
    ("thisboarddoesnotexist12345xyz", "none", "nonexistent slug -> jobBoardExternal null -> None, never []"),
    ("retool.ai", "none", "dotted bogus slug -> also null; confirms dots are safe to send (not a hostname/path segment)"),
]
for slug, want, why in LIVE_CASES:
    result = harvest_ats.probe("gem", slug, None)
    if want == "none":
        ok = result is None
    else:
        ok = isinstance(result, list) and len(result) > 0
    check(ok, f"probe('gem', {slug!r}) -> {want}", why)

# Real-empty-board case: no genuinely empty live Gem board was found while
# building this adapter (all three known boards -- Retool, Function Health,
# Transluce -- carry open postings). The distinction the contract cares
# about (jobBoardExternal populated + jobPostings: [] must read as [], not
# None) is still exercised, offline, at the point where it actually lives:
# ats_gem.parse_board_response. This is a synthetic response in exactly the
# shape the live API returns for a resolved board (confirmed against the
# real jobBoardExternal payload captured in this build's session), just
# with jobPostings emptied out by hand.
SYNTHETIC_EMPTY_BOARD = [{
    "data": {
        "oatsExternalJobPostings": {"jobPostings": []},
        "jobBoardExternal": {"id": "RXh0ZXJuYWxKb2JCb2FyZDo5OTk5OQ==",
                              "teamDisplayName": "Synthetic Co", "pageTitle": "Synthetic Co Careers"},
    }
}]
board_exists, postings = ats_gem.parse_board_response(SYNTHETIC_EMPTY_BOARD)
check(board_exists is True and postings == [],
      "parse_board_response: resolved board + zero jobs -> (True, []), never (False, ...)",
      "SmartRecruiters-class trap: this must NOT collapse to the same answer as a bogus slug")

SYNTHETIC_BOGUS = [{"data": {"oatsExternalJobPostings": {"jobPostings": []}, "jobBoardExternal": None}}]
board_exists2, postings2 = ats_gem.parse_board_response(SYNTHETIC_BOGUS)
check(board_exists2 is False, "parse_board_response: bogus slug -> board_exists False")

# ─────────────────────────────────────────────────────────────────────────
# 3. PAGINATION PAST PAGE 1 -- Gem is single-response ("n/a" row); prove it
#    on the largest live Gem board found (function-health, 33 postings),
#    count vs what the rendered board page shows.
# ─────────────────────────────────────────────────────────────────────────
print()
print("=" * 78)
print("3. Pagination proof: jobs.gem.com/function-health (largest known Gem board)")
print("=" * 78)

fh_jobs = ats_gem.fetch_gem("function-health")
fh_ok = isinstance(fh_jobs, list) and fh_jobs and "_error" not in fh_jobs[0]
check(fh_ok, "fetch_gem('function-health') succeeds", detail="" if fh_ok else str(fh_jobs[:1]))
if fh_ok:
    n = len(fh_jobs)
    print(f"      API returned {n} postings in ONE response (no offset/limit/page "
          f"param exists in the query the live page itself sends)")
    print("      Rendered board page (jobs.gem.com/function-health) header read "
          "'Open positions (33)' and hand-counting the 33 listed titles under "
          "each department matched exactly -- captured live 2026-09-18.")
    # WHY THIS NO LONGER PINS 33 (changed 2026-09-26, horizon M7). The board is
    # live, so an exact count fails the day one posting opens or closes: on
    # 2026-09-26 it had grown to 34 and this read as a regression. The page
    # can't be re-counted automatically -- it's client-rendered, and a plain GET
    # carries no "Open positions (N)" -- so the 09-18 hand count stays as the
    # one-time completeness proof above. What CAN be checked every run is what
    # a silent truncation would break: a single response well past any common
    # page size (20/25), with no posting repeated.
    ext_ids = [p.get("extId") for p in fh_jobs]
    check(n > 25, "one response carries more than any common page size (20/25)", detail=str(n))
    check(len(set(ext_ids)) == n and None not in ext_ids,
          "every posting has a distinct extId (no repeated page)", detail=f"{len(set(ext_ids))}/{n}")
    print("      Conclusion: Gem is the contract's 'one response holds the whole "
          "board' (n/a) pagination class, same as Greenhouse -- no MAX_POSTINGS cap exists.")

# ─────────────────────────────────────────────────────────────────────────
# 4. BUDGET UNDER A SIMULATED HANG (stdlib only: a socket server that accepts
#    and never answers).
# ─────────────────────────────────────────────────────────────────────────
print()
print("=" * 78)
print("4. Budget under a simulated hang")
print("=" * 78)


def _hang_forever(sock, stop_event):
    sock.settimeout(0.5)
    while not stop_event.is_set():
        try:
            conn, _ = sock.accept()
        except socket.timeout:
            continue
        # Accept the connection and never write a response. Don't close it
        # either -- closing would let the client read EOF and return fast,
        # which is not the hang this is testing.
        while not stop_event.is_set():
            time.sleep(0.1)
        try:
            conn.close()
        except OSError:
            pass


server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server_sock.bind(("127.0.0.1", 0))
server_sock.listen(5)
port = server_sock.getsockname()[1]
stop_event = threading.Event()
thread = threading.Thread(target=_hang_forever, args=(server_sock, stop_event), daemon=True)
thread.start()

original_url = ats_gem.GRAPHQL_URL
ats_gem.GRAPHQL_URL = f"http://127.0.0.1:{port}/api/public/graphql/batch"
try:
    budget_seconds = 3
    budget = harvest_ats.Budget(budget_seconds)
    t0 = time.monotonic()
    result = harvest_ats.probe("gem", "anyslug", budget)
    elapsed = time.monotonic() - t0
    # Budget.tripped is a side effect of calling .expired(), not of time
    # passing -- probe()/_post() only called it once, BEFORE the hung
    # request, when it was still False. assess() calls .expired() again
    # before every subsequent probe in its loop, which is what actually
    # notices a budget that ran out mid-request and emits the per-company
    # {'timed_out': True, ...} dict. Reproduce that one extra check here.
    now_expired = budget.expired()
    print(f"      budget={budget_seconds}s  elapsed={elapsed:.2f}s  result={result!r}  "
          f"expired()-after-hang={now_expired}  budget.tripped={budget.tripped}")
    check(elapsed <= budget_seconds + 1.5,
          f"probe() against a hung socket returns within budget+~1.5s",
          detail=f"elapsed={elapsed:.2f}s")
    check(result is None,
          "probe() returns a clean None (no board could be confirmed), not an exception",
          detail=repr(result))
    check(now_expired is True and budget.tripped is True,
          "the NEXT budget.expired() check (what assess()'s loop does before its next "
          "probe) sees the budget used up and sets tripped=True -- the exact signal "
          "assess() reads to emit the per-company {'timed_out': True, ...} dict one layer "
          "up (not re-driven here: assess() walks every cheap ATS x every slug_variant, "
          "which a single fake endpoint can't stand in for; this proves the mechanism "
          "that feeds it)")
finally:
    ats_gem.GRAPHQL_URL = original_url
    stop_event.set()
    thread.join(timeout=2)
    server_sock.close()

# ─────────────────────────────────────────────────────────────────────────
print()
print("=" * 78)
print(f"{total - fails}/{total} passed")
sys.exit(1 if fails else 0)
