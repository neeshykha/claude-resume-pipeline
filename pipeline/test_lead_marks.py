#!/usr/bin/env python3
"""Tests for lead_marks.py and linkedin_followup.py --requested (D41, 2026-10-15).
Fixtures are made up and live in a temp dir; nothing here reads the real files or
touches the network (the LinkedIn fetch is replaced).

    .venv/bin/python pipeline/test_lead_marks.py
"""
import contextlib
import datetime
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lead_marks as lm  # noqa: E402
import linkedin_followup as lf  # noqa: E402

TODAY = datetime.date(2026, 10, 16)


def fresh():
    d = tempfile.mkdtemp(prefix="leads_test_")
    lm.PATH = os.path.join(d, "jobs", "lead_marks.json")
    lf.JOBS = os.path.join(d, "jobs")
    lf.SEEN = os.path.join(lf.JOBS, "linkedin_followup_seen.json")
    lf.DELAY = 0
    return d


def entry(action, marked, **kw):
    e = {"action": action, "marked": marked, "recorded": marked, "company": "Brevik",
         "title": "Head of Support", "list": "unreachable", "loc": "atlanta"}
    e.update(kw)
    return e


def test_pending_requests_oldest_first_and_capped():
    fresh()
    lm.save({"3000003": entry("tailor", "2026-10-14"), "3000001": entry("tailor", "2026-10-12"),
             "3000002": entry("pass", "2026-10-11"), "3000004": entry("tailor", "2026-10-13", fetched="2026-10-14"),
             "3000005": entry("tailor", "2026-10-13")})
    got, waiting = lm.pending_requests(2)
    assert [g["job_id"] for g in got] == ["3000001", "3000005"], got
    assert waiting == 3, "passes and requests already read don't wait"


def test_stamp_only_touches_unread_requests():
    fresh()
    lm.save({"3000001": entry("tailor", "2026-10-12"), "3000002": entry("pass", "2026-10-12"),
             "3000003": entry("tailor", "2026-10-12", fetched="2026-10-13", fetch_status="ok")})
    n = lm.stamp({"3000001": "closed", "3000002": "ok", "3000003": "thin", "9999999": "ok"}, TODAY)
    got = lm.load()
    assert n == 1, n
    assert got["3000001"]["fetched"] == "2026-10-16" and got["3000001"]["fetch_status"] == "closed"
    assert "fetched" not in got["3000002"] and got["3000003"]["fetch_status"] == "ok"


def test_record_keeps_only_known_lists_and_bad_file_raises():
    fresh()
    p, t, n = lm.record({"3000001": {"a": "tailor", "d": "2026-10-12", "l": "somewhere", "c": " Brevik "}}, TODAY)
    got = lm.load()["3000001"]
    assert (t, n) == (1, 0) and "list" not in got and got["company"] == "Brevik", got
    with open(lm.PATH, "w", encoding="utf-8") as f:
        f.write('{"leads": []}')
    try:
        lm.load()
        raise AssertionError("a file without a leads object must raise, so nothing overwrites it")
    except ValueError:
        pass
    assert lm.recorded_ids() == set(), "the page's reader never raises"


def run_requested(fake):
    lf.fetch = fake
    buf = io.StringIO()
    saved = sys.argv
    sys.argv = ["linkedin_followup.py", "--requested", "--date", TODAY.isoformat()]
    try:
        with contextlib.redirect_stdout(buf):
            rc = lf.main()
    finally:
        sys.argv = saved
    return rc, buf.getvalue()


BODY = "Lead our support operations team. " * 30


def test_requested_reads_writes_and_stamps():
    fresh()
    lm.save({"3000001": entry("tailor", "2026-10-12"), "3000002": entry("tailor", "2026-10-12", title="Ops Lead"),
             "3000003": entry("tailor", "2026-10-13", title="Gone"), "3000004": entry("tailor", "2026-10-14"),
             "3000005": entry("pass", "2026-10-11")})
    reads = {"3000001": {"body": BODY, "title": "Head of Support", "company": "Brevik"},
             "3000002": {"error": "HTTP 404"},
             "3000003": {"body": BODY, "closed": True}}
    rc, out = run_requested(lambda session, jid: reads[jid])
    assert rc == 0, out
    assert "3 selected of 4 waiting" in out, out
    cache = os.path.join(lf.JOBS, "jd_cache", f"{TODAY.isoformat()}_requested")
    with open(os.path.join(cache, "manifest.json"), encoding="utf-8") as f:
        man = json.load(f)
    assert man["counts"]["fetched"] == 1 and len(man["batches"]) == 1, man["counts"]
    with open(man["batches"][0][0], encoding="utf-8") as f:
        text = f.read()
    assert "Aneesh asked for this one" in text and "linkedin.com/jobs/view/3000001/" in text
    got = lm.load()
    assert got["3000001"]["fetch_status"] == "ok"
    assert got["3000002"]["fetch_status"] == "error: HTTP 404"
    assert got["3000003"]["fetch_status"] == "closed"
    assert "fetched" not in got["3000004"], "past the cap of 3, it waits for the next run"
    with open(lf.SEEN, encoding="utf-8") as f:
        assert set(json.load(f)) == {"3000001", "3000002", "3000003"}


def test_requested_stops_at_a_429_and_leaves_the_rest_waiting():
    fresh()
    lm.save({"3000001": entry("tailor", "2026-10-12"), "3000002": entry("tailor", "2026-10-13")})
    reads = {"3000001": {"body": BODY}, "3000002": {"error": "429", "throttled": True}}
    rc, out = run_requested(lambda session, jid: reads[jid])
    got = lm.load()
    assert got["3000001"]["fetch_status"] == "ok" and "fetched" not in got["3000002"], got
    assert "stay waiting for the next run" in out, out


def test_transient_errors_keep_the_request_until_the_third_try():
    fresh()
    lm.save({"3000001": entry("tailor", "2026-10-12"), "3000002": entry("tailor", "2026-10-12")})
    reads = {"3000001": {"error": "ReadTimeout: timed out"}, "3000002": {"error": "HTTP 503"}}
    for n in (1, 2):
        rc, out = run_requested(lambda session, jid: reads[jid])
        got = lm.load()
        assert "fetched" not in got["3000001"] and got["3000001"]["tries"] == n, got
        assert "2 request(s) hit a timeout or server error and stay waiting" in out, out
    rc, out = run_requested(lambda session, jid: reads[jid])
    got = lm.load()
    assert got["3000002"]["fetch_status"] == "error: HTTP 503 (3 tries)", got
    assert "gave up after 3 tries" in out, out
    with open(lf.SEEN, encoding="utf-8") as f:
        assert json.load(f) == {}, "a failed read never marks the id seen"
    assert lf.transient("ConnectionError: reset") and lf.transient("HTTP 502")
    assert not lf.transient("HTTP 404") and not lf.transient("no description block (posting closed)")


def test_requested_with_nothing_waiting_is_quiet():
    fresh()
    rc, out = run_requested(lambda session, jid: (_ for _ in ()).throw(AssertionError("no fetch")))
    assert rc == 0 and "0 selected of 0 waiting" in out, out
    assert not os.path.exists(os.path.join(lf.JOBS, "jd_cache")), "nothing to read, nothing written"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
