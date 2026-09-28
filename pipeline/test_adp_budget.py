#!/usr/bin/env python3
"""Budget-under-a-simulated-hang proof for the ADP adapter
(ats_contract.md section 8 item 4).

Run as: .venv/bin/python pipeline/test_adp_budget.py

Standard library only: a local `socket` server thread that accepts every
connection and then never sends a byte back -- the plainest possible hang,
no third-party mocking. `harvest_ats.probe_adp()` is pointed at it through
its `get=` injection hook (see probe_adp's docstring: `get` is also budget-
aware, checking `budget.expired()` before each page and passing
`budget.timeout()` -- floored at 1s -- as the request timeout instead of a
fixed constant), with a small `Budget(3)`.

What this proves: the probe returns an ordinary answer (None, here -- the
first page never came back, so nothing was learned about the board) rather
than raising, and does so within budget + ~1s (the timeout floor from
Budget.timeout()'s docstring). It does NOT prove a `{"timed_out": True, ...}`
dict comes back from probe_adp itself -- nothing in this codebase's Budget
mechanics do that at the single-probe layer; that shaped result is
assembled one level up, in harvest_ats.assess(), by checking
`budget.tripped` after every probe has run (see PER_COMPANY_BUDGET's
docstring, section 4 of the contract, and probe_workday/probe_comeet, which
are budget-aware the same way and also just return their normal answer
early). This script additionally asserts `budget.tripped` is True
afterward, which is the actual signal assess() reads to build that dict --
so it demonstrates the real mechanism ADP shares with every other budgeted
probe, not a bespoke one.
"""
import os
import socket
import sys
import threading
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import harvest_ats

BUDGET_SECONDS = 3.0
TIMEOUT_FLOOR = 1.0          # Budget.timeout()'s floor
SLACK = 1.0                  # "budget + ~1s" per the contract wording


def _hang_server(sock, stop_event):
    """Accept every connection, read nothing, write nothing, forever
    (until the test process exits)."""
    while not stop_event.is_set():
        try:
            sock.settimeout(0.5)
            conn, _addr = sock.accept()
        except socket.timeout:
            continue
        except OSError:
            return
        # Deliberately do nothing with conn: no recv, no send, no close.
        # The client's socket sits there until ITS OWN timeout fires.


def _hanging_get(url, timeout):
    """Stand-in for a real HTTP client: opens a TCP connection to the hung
    server and blocks on recv() until `timeout` (seconds) elapses, exactly
    like requests' read-timeout behavior. Returns None on timeout/failure,
    matching `_get`'s "network failure -> None" contract so probe_adp's
    NO_BOARD branch fires the same way it would for a real dead host.
    """
    host, port = _HANG_ADDR
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.settimeout(timeout)
            s.recv(4096)   # blocks until `timeout`; server never sends anything
    except (socket.timeout, OSError):
        pass
    return None


def main():
    global _HANG_ADDR
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    _HANG_ADDR = srv.getsockname()
    stop_event = threading.Event()
    t = threading.Thread(target=_hang_server, args=(srv, stop_event), daemon=True)
    t.start()
    print(f"Local hang server listening on {_HANG_ADDR}, accepts and never answers.")

    budget = harvest_ats.Budget(seconds=BUDGET_SECONDS)
    cid = "33333333-3333-3333-3333-333333333333"  # arbitrary; never reaches ADP

    start = time.monotonic()
    result = None
    raised = None
    try:
        result = harvest_ats.probe_adp(cid, budget=budget, get=_hanging_get)
    except Exception as exc:                       # noqa: BLE001
        raised = exc
    elapsed = time.monotonic() - start

    stop_event.set()
    srv.close()

    # Mirrors assess()'s own pattern (see PER_COMPANY_BUDGET's docstring:
    # "After the loops, budget.tripped is re-checked so a walk cut short on
    # its last slug isn't reported as a clean no-board"): `tripped` is a
    # side effect of CALLING expired(), not something a single probe call
    # sets on its own mid-request. The request itself already spent the
    # whole budget in recv() -- this just asks the same question the real
    # caller asks once the probe returns.
    budget.expired()

    print(f"Budget: {BUDGET_SECONDS}s   Elapsed: {elapsed:.2f}s   "
          f"Result: {result!r}   Raised: {raised!r}")
    print(f"budget.tripped: {budget.tripped}   budget.elapsed(): {budget.elapsed():.2f}s")

    fails = 0

    if raised is not None:
        print(f"[FAIL] probe_adp raised instead of returning a result: {raised!r}")
        fails += 1
    else:
        print("[ok ] probe_adp returned normally, no exception")

    cap = BUDGET_SECONDS + TIMEOUT_FLOOR + SLACK
    if elapsed <= cap:
        print(f"[ok ] elapsed ({elapsed:.2f}s) <= budget + timeout-floor + slack "
              f"({cap:.2f}s)")
    else:
        print(f"[FAIL] elapsed ({elapsed:.2f}s) exceeded budget + timeout-floor + "
              f"slack ({cap:.2f}s) -- the hang was not bounded")
        fails += 1

    if result is None:
        print("[ok ] result is None (no board could be confirmed -- the honest "
              "answer when the only page attempted never came back)")
    else:
        print(f"[FAIL] expected None, got {result!r}")
        fails += 1

    if budget.tripped:
        print("[ok ] budget.tripped is True -- this is exactly the signal "
              "assess() reads, one layer up, to write a {'timed_out': True, ...} "
              "record instead of an ordinary no_board rejection")
    else:
        print("[FAIL] budget.tripped is False -- the probe finished some other "
              "way, not by hitting the cap (re-check BUDGET_SECONDS vs. the "
              "server's accept delay)")
        fails += 1

    print(f"\n{'PASS' if not fails else 'FAIL'}: {4 - fails}/4 checks passed")
    sys.exit(1 if fails else 0)


_HANG_ADDR = None

if __name__ == "__main__":
    main()
