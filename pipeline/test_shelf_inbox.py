#!/usr/bin/env python3
"""Tests for shelf_inbox.py. Fixtures are built in a temp dir with made-up
companies; nothing here reads the real tracker or the real Shelf.

    .venv/bin/python pipeline/test_shelf_inbox.py
"""
import contextlib
import csv
import datetime
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shelf_inbox as si  # noqa: E402

HEADER = ["applied_date", "company", "title", "url", "fit_score", "jd_coverage_pct", "stage",
          "outcome", "notes", "source_channel", "surfaced_date", "unmet_hard_reqs",
          "vendor_tool_named_in_jd", "hard_req_cap_trigger", "furthest_stage", "ic_scope",
          "his_verdict"]
TODAY = "2026-10-12"


def row(**kw):
    base = dict.fromkeys(HEADER, "")
    base.update(source_channel="pipeline", fit_score="90", stage="surfaced",
                surfaced_date="2026-10-09", applied_date="2026-10-09")
    base.update(kw)
    return [base[h] for h in HEADER]


def fixture(rows, marks, seen=None):
    """Temp tracker + an inbox file shaped like the Shelf's storage (values are strings)."""
    d = tempfile.mkdtemp(prefix="inbox_test_")
    si.OUTCOMES = os.path.join(d, "outcomes.csv")
    si.JOBS_DIR = os.path.join(d, "jobs")
    si.SEEN_JOBS = os.path.join(si.JOBS_DIR, "seen_jobs.json")
    os.makedirs(si.JOBS_DIR)
    with open(si.OUTCOMES, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)
    if seen is not None:
        with open(si.SEEN_JOBS, "w", encoding="utf-8") as f:
            json.dump({"jobs": seen}, f)
    inbox = os.path.join(d, "storage.json")
    with open(inbox, "w", encoding="utf-8") as f:
        json.dump({"jobdash.ticks.v1": "{}", si.INBOX_KEY: json.dumps(marks)}, f)
    return d, inbox


def run(inbox, *flags):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = si.main(["--inbox", inbox, "--today", TODAY] + list(flags))
    return rc, buf.getvalue()


def tracker():
    with open(si.OUTCOMES, newline="", encoding="utf-8") as f:
        return {r["company"]: r for r in csv.DictReader(f)}


def BACKUP():
    return si.OUTCOMES + si.BACKUP_SUFFIX + "-mon"


def mark(action, url, **kw):
    m = {"a": action, "u": url, "d": "2026-10-11", "c": "page company", "t": "page title"}
    m.update(kw)
    return m


def test_sent_promotes_and_records_verdict_with_provenance():
    url = "https://example.com/jobs/1"
    d, inbox = fixture([row(company="Acme", title="Ops Lead", url=url + "/")],
                       {url: mark("sent", url)},
                       seen={"k1": {"url": url, "applied": False}})
    rc, out = run(inbox, "--apply")
    r = tracker()["Acme"]
    assert rc == 0 and "recorded 1 sent, 1 verdicts" in out, out
    assert r["stage"] == "applied" and r["applied_date"] == "2026-10-11", r
    assert r["his_verdict"] == "sent_as_is"
    assert "marked sent on the Shelf 2026-10-11, no confirmation email yet" in r["notes"], r["notes"]
    with open(si.SEEN_JOBS, encoding="utf-8") as f:
        assert json.load(f)["jobs"]["k1"]["applied"] is True
    assert os.path.exists(BACKUP()), "2026-10-12 is a Monday"
    assert os.path.exists(os.path.join(si.JOBS_DIR, f"shelf_inbox_{TODAY}.json"))


def test_sent_edited_and_skip_reasons():
    rows = [row(company="A", url="https://example.com/a"), row(company="B", url="https://example.com/b"),
            row(company="C", url="https://example.com/c"), row(company="D", url="https://example.com/d")]
    marks = {"https://example.com/a": mark("sent", "https://example.com/a", e=True),
             "https://example.com/b": mark("skip", "https://example.com/b", r="fit"),
             "https://example.com/c": mark("skip", "https://example.com/c", r="materials"),
             "https://example.com/d": mark("skip", "https://example.com/d", r="something new")}
    d, inbox = fixture(rows, marks)
    rc, out = run(inbox, "--apply")
    t = tracker()
    assert t["A"]["his_verdict"] == "sent_edited" and t["A"]["stage"] == "applied"
    assert t["B"]["his_verdict"] == "skip_fit" and t["B"]["stage"] == "surfaced", "a skip never changes the stage"
    assert "skipped on the Shelf 2026-10-11" in t["B"]["notes"]
    assert t["C"]["his_verdict"] == "skip_materials"
    assert t["D"]["his_verdict"] == "skip_other", "an unknown reason falls back, it is not dropped"
    assert "recorded 1 sent, 4 verdicts (3 skips)" in out, out


def test_later_is_page_only_and_report_mode_writes_nothing():
    url = "https://example.com/a"
    d, inbox = fixture([row(company="A", url=url), row(company="B", url="https://example.com/b")],
                       {url: mark("later", url), "https://example.com/b": mark("skip", "https://example.com/b", r="time")})
    before = open(si.OUTCOMES, "rb").read()
    rc, out = run(inbox)
    assert rc == 0 and "would record 0 sent, 1 skipped" in out and "1 snoozed" in out, out
    assert open(si.OUTCOMES, "rb").read() == before
    assert not os.path.exists(BACKUP())
    assert os.listdir(si.JOBS_DIR) == [], "report mode leaves no files"


def test_idempotent_second_run_changes_nothing():
    url = "https://example.com/a"
    d, inbox = fixture([row(company="A", url=url), row(company="B", url="https://example.com/b")],
                       {url: mark("sent", url), "https://example.com/b": mark("skip", "https://example.com/b", r="fit")})
    run(inbox, "--apply")
    after_first = open(si.OUTCOMES, "rb").read()
    rc, out = run(inbox, "--apply")
    assert "nothing new to record; 2 already recorded" in out, out
    assert open(si.OUTCOMES, "rb").read() == after_first


def test_unmatched_and_ambiguous_write_nothing():
    dup = "https://example.com/dup"
    d, inbox = fixture([row(company="A", url=dup), row(company="B", url=dup)],
                       {dup: mark("sent", dup), "https://example.com/gone": mark("skip", "https://example.com/gone", r="fit"),
                        "nokey": {"a": "sent", "c": "No Url", "t": "x"}})
    before = open(si.OUTCOMES, "rb").read()
    rc, out = run(inbox, "--apply")
    assert rc == 0 and "nothing new to record" in out and "3 not matched" in out, out
    assert "ambiguous: A: " not in out and "ambiguous: page company" in out, out
    assert open(si.OUTCOMES, "rb").read() == before


def test_stale_skip_and_sent_after_email_confirmation():
    rows = [row(company="Applied", url="https://example.com/a", stage="applied"),
            row(company="Expired", url="https://example.com/x", stage="expired"),
            row(company="Emailed", url="https://example.com/e", stage="applied", notes="confirmed by email")]
    marks = {"https://example.com/a": mark("skip", "https://example.com/a", r="fit"),
             "https://example.com/x": mark("sent", "https://example.com/x"),
             "https://example.com/e": mark("sent", "https://example.com/e")}
    d, inbox = fixture(rows, marks)
    rc, out = run(inbox, "--apply")
    t = tracker()
    assert t["Applied"]["his_verdict"] == "", "a skip on an applied row is stale, not recorded"
    assert t["Expired"]["stage"] == "expired" and t["Expired"]["his_verdict"] == ""
    assert t["Emailed"]["his_verdict"] == "sent_as_is"
    assert "no confirmation email yet" not in t["Emailed"]["notes"], "email-confirmed rows keep clean provenance"
    assert "2 stale" in out and "recorded 0 sent, 1 verdicts" in out, out


def test_future_dated_mark_is_clamped_and_bad_date_defaults():
    rows = [row(company="A", url="https://example.com/a"), row(company="B", url="https://example.com/b")]
    marks = {"https://example.com/a": mark("sent", "https://example.com/a", d="2027-01-01"),
             "https://example.com/b": mark("sent", "https://example.com/b", d="not a date")}
    d, inbox = fixture(rows, marks)
    run(inbox, "--apply")
    t = tracker()
    assert t["A"]["applied_date"] == TODAY and t["B"]["applied_date"] == TODAY


def test_drifted_rows_pass_through_untouched():
    url = "https://example.com/a"
    d, inbox = fixture([row(company="A", url=url)], {url: mark("skip", url, r="time")})
    with open(si.OUTCOMES, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["2026-09-01", "Short", "Title", url])
    run(inbox, "--apply")
    with open(si.OUTCOMES, newline="", encoding="utf-8") as f:
        raw = list(csv.reader(f))
    assert raw[-1] == ["2026-09-01", "Short", "Title", url], "a drifted row is neither matched nor rewritten"
    assert raw[1][HEADER.index("his_verdict")] == "skip_time"


def test_reads_the_shelf_library_and_storage_shape():
    d = tempfile.mkdtemp(prefix="shelf_test_")
    si.SHELF_DIR = d
    os.makedirs(os.path.join(d, "Data"))
    lib = {"categories": [], "documents": [
        {"id": "AAA", "originalName": "something_else.html"},
        {"id": "BBB", "originalName": si.PAGE_FILE, "trackedSource": "/x/Downloads/" + si.PAGE_FILE}]}
    with open(os.path.join(d, "library.json"), "w", encoding="utf-8") as f:
        json.dump(lib, f)
    assert si.load_marks() == ({}, "the page has no stored data yet")
    with open(os.path.join(d, "Data", "BBB.json"), "w", encoding="utf-8") as f:
        json.dump({"jobdash.ticks.v1": "{\"x\":\"2026-09-20\"}"}, f)
    assert si.load_marks() == ({}, "no marks on the page")
    with open(os.path.join(d, "Data", "BBB.json"), "w", encoding="utf-8") as f:
        json.dump({si.INBOX_KEY: json.dumps({"https://example.com/a": {"a": "later"}, "junk": 7})}, f)
    marks, why = si.load_marks()
    assert list(marks) == ["https://example.com/a"] and why == ""
    lib["documents"].append({"id": "CCC", "originalName": si.PAGE_FILE})
    with open(os.path.join(d, "library.json"), "w", encoding="utf-8") as f:
        json.dump(lib, f)
    assert si.find_storage_file()[0].endswith("BBB.json"), "the tracked copy wins over a stray duplicate"
    lib["documents"][1].pop("trackedSource")
    with open(os.path.join(d, "library.json"), "w", encoding="utf-8") as f:
        json.dump(lib, f)
    assert si.find_storage_file()[0] is None, "two equal copies: refuse to pick"
    si.SHELF_DIR = os.path.join(d, "nope")
    assert si.load_marks()[1] == "no Shelf library on this machine"


def test_a_crash_between_the_two_writes_is_finished_by_the_next_drain():
    import mark_applied
    url = "https://example.com/a"
    d, inbox = fixture([row(company="A", url=url), row(company="B", url="https://example.com/b")],
                       {url: mark("sent", url), "https://example.com/b": mark("skip", "https://example.com/b", r="time")})
    real = mark_applied.main

    def boom():
        raise RuntimeError("simulated crash in the promotion step")
    mark_applied.main = boom
    try:
        rc, out = run(inbox, "--apply")
    finally:
        mark_applied.main = real
    t = tracker()
    assert rc == 0 and "1 PROBLEMS" in out, out
    assert t["A"]["stage"] == "surfaced" and t["A"]["his_verdict"] == "sent_as_is", "verdict lands before the promotion"
    assert "no confirmation email yet" in t["A"]["notes"]
    assert t["B"]["his_verdict"] == "skip_time", "the other mark still got recorded"
    rc, out = run(inbox, "--apply")
    t = tracker()
    assert t["A"]["stage"] == "applied" and "recorded 1 sent, 0 verdicts" in out, out
    rc, out = run(inbox, "--apply")
    assert "nothing new to record; 2 already recorded" in out, out


def confirm(conf):
    """Run mark_applied.py the way Step 0.5 does, against the fixture tracker."""
    import mark_applied
    path = os.path.join(si.JOBS_DIR, "confirmations_test.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"confirmations": conf}, f)
    mark_applied.OUTCOMES, mark_applied.SEEN_JOBS = si.OUTCOMES, si.SEEN_JOBS
    buf, argv = io.StringIO(), sys.argv
    sys.argv = ["mark_applied.py", path]
    try:
        with contextlib.redirect_stdout(buf):
            mark_applied.main()
    finally:
        sys.argv = argv
    return buf.getvalue()


def test_a_later_confirmation_email_never_lands_on_a_sibling_row():
    # The defect the 2026-10-12 review reproduced: a row marked Sent on the Shelf is already
    # `applied` when its confirmation email arrives, so the URL misses the surfaced rows and
    # the company fallback used to promote a DIFFERENT open role there (titles match as
    # substrings). The URL names the requisition; the search has to stop at it.
    x = "https://example.com/jobs/csm"
    d, inbox = fixture([row(company="Co", title="Customer Success Manager", url=x),
                        row(company="Co", title="Senior Customer Success Manager", url="https://example.com/jobs/sr"),
                        row(company="Solo", title="Ops Lead", url="https://example.com/jobs/solo"),
                        row(company="Solo", title="Other Role", url="https://example.com/jobs/other")],
                       {x: mark("sent", x)})
    run(inbox, "--apply")
    out = confirm([{"url": x, "company": "Co", "title": "Customer Success Manager", "applied_date": "2026-10-12"}])
    t = {r["title"]: r for r in csv.DictReader(open(si.OUTCOMES, newline="", encoding="utf-8"))}
    assert t["Senior Customer Success Manager"]["stage"] == "surfaced", "the sibling must stay unsent"
    assert "ALREADY RECORDED" in out and "0 promoted" in out, out
    # No title in the email at all: the old code promoted the only surfaced row at the company.
    out = confirm([{"url": x + "/", "company": "Co", "applied_date": "2026-10-12"}])
    t = {r["title"]: r for r in csv.DictReader(open(si.OUTCOMES, newline="", encoding="utf-8"))}
    assert t["Senior Customer Success Manager"]["stage"] == "surfaced" and "0 promoted" in out, out
    # A URL the tracker has never seen still falls back to the company match, as before.
    out = confirm([{"url": "https://example.com/unknown", "company": "Solo", "title": "Ops Lead", "applied_date": "2026-10-12"}])
    assert "1 promoted" in out, out


def test_a_url_on_a_retired_row_is_reported_not_promoted_and_not_passed_on():
    x = "https://example.com/jobs/old"
    d, inbox = fixture([row(company="Co", title="Old Role", url=x, stage="expired"),
                        row(company="Co", title="Old Role Two", url="https://example.com/jobs/new")], {})
    out = confirm([{"url": x, "company": "Co", "title": "Old Role", "applied_date": "2026-10-12"}])
    t = tracker_by_title()
    assert t["Old Role"]["stage"] == "expired" and t["Old Role Two"]["stage"] == "surfaced", out
    assert "NOT SURFACED AND NOT SENT" in out and "0 promoted" in out, out


def tracker_by_title():
    with open(si.OUTCOMES, newline="", encoding="utf-8") as f:
        return {r["title"]: r for r in csv.DictReader(f)}


def test_a_mark_older_than_its_rows_package_is_stale_not_applied():
    # update_tracking.py's retailor reopens a retired row for a new package and restarts
    # its surfaced_date. A click made on the old package is still stored under the URL.
    a, b, c = "https://example.com/a", "https://example.com/b", "https://example.com/c"
    d, inbox = fixture([row(company="A", url=a, surfaced_date=TODAY, applied_date=TODAY),
                        row(company="B", url=b, surfaced_date=TODAY, applied_date=TODAY),
                        row(company="C", url=c, surfaced_date=TODAY, applied_date=TODAY)],
                       {a: mark("skip", a, r="fit"), b: mark("sent", b), c: mark("sent", c, d=TODAY)})
    before = {k: (v["stage"], v["his_verdict"], v["notes"]) for k, v in tracker().items()}
    rc, out = run(inbox, "--apply")
    t = tracker()
    assert (t["A"]["stage"], t["A"]["his_verdict"], t["A"]["notes"]) == before["A"], out
    assert (t["B"]["stage"], t["B"]["his_verdict"], t["B"]["notes"]) == before["B"], out
    assert (t["C"]["stage"], t["C"]["his_verdict"]) == ("applied", "sent_as_is"), "a same-day mark still lands"
    assert "2 stale" in out and "before this row's package was surfaced 2026-10-12" in out, out


def test_one_malformed_mark_does_not_block_the_rest():
    good = "https://example.com/good"
    d, inbox = fixture([row(company="Good", url=good)],
                       {good: mark("skip", good, r="fit"),
                        "https://example.com/bad1": {"a": "sent", "u": 12345, "c": ["x"], "t": None},
                        "https://example.com/bad2": {"a": ["sent"]},
                        "bad3": {"a": "skip", "u": {"nested": 1}, "r": 9}})
    rc, out = run(inbox, "--apply")
    assert rc == 0 and "FAILED" not in out, out
    assert tracker()["Good"]["his_verdict"] == "skip_fit"
    assert "recorded 0 sent, 1 verdicts" in out and "3 not matched" in out, out


def test_sent_replaces_an_earlier_skip_and_skip_replaces_an_unfinished_sent():
    a, b, c = "https://example.com/a", "https://example.com/b", "https://example.com/c"
    d, inbox = fixture([row(company="A", url=a, his_verdict="skip_fit"),
                        row(company="B", url=b, his_verdict="sent_as_is"),
                        row(company="C", url=c, stage="applied", his_verdict="skip_time")],
                       {a: mark("sent", a), b: mark("skip", b, r="time"), c: mark("sent", c, e=True)})
    rc, out = run(inbox, "--apply")
    t = tracker()
    assert t["A"]["stage"] == "applied" and t["A"]["his_verdict"] == "sent_as_is", "no 'applied, verdict skip' rows"
    assert "no confirmation email yet" in t["A"]["notes"]
    assert t["B"]["stage"] == "surfaced" and t["B"]["his_verdict"] == "skip_time", "the newer mark is the answer"
    assert t["C"]["his_verdict"] == "sent_edited" and "no confirmation email yet" not in t["C"]["notes"]
    rc, out = run(inbox, "--apply")
    assert "nothing new to record; 3 already recorded" in out, out


def test_the_days_first_backup_survives_a_second_drain():
    a, b = "https://example.com/a", "https://example.com/b"
    d, inbox = fixture([row(company="A", url=a), row(company="B", url=b)], {a: mark("skip", a, r="fit")})
    original = open(si.OUTCOMES, "rb").read()
    run(inbox, "--apply")
    # The drain asks whether the backup was written "today", and today here is TODAY,
    # not the wall clock: date the file to match, or this passes on one day a year.
    noon = datetime.datetime.fromisoformat(TODAY + "T12:00:00").timestamp()
    os.utime(BACKUP(), (noon, noon))
    with open(inbox, "w", encoding="utf-8") as f:
        json.dump({si.INBOX_KEY: json.dumps({a: mark("skip", a, r="fit"), b: mark("sent", b)})}, f)
    run(inbox, "--apply")
    assert tracker()["B"]["stage"] == "applied"
    assert open(BACKUP(), "rb").read() == original, "the backup still holds the state before today's marks"
    old = os.path.getmtime(BACKUP()) - 8 * 86400
    os.utime(BACKUP(), (old, old))
    with open(inbox, "w", encoding="utf-8") as f:
        json.dump({si.INBOX_KEY: json.dumps({b: mark("sent", b, e=True)})}, f)
    with open(si.OUTCOMES, newline="", encoding="utf-8") as f:
        rows_now = list(csv.reader(f))
    rows_now[2][HEADER.index("his_verdict")] = ""
    with open(si.OUTCOMES, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows_now)
    before_third = open(si.OUTCOMES, "rb").read()
    run(inbox, "--apply")
    assert open(BACKUP(), "rb").read() == before_third, "last week's same-weekday backup is replaced"


def test_bulk_clear_is_always_skip_other_and_says_so():
    a, b = "https://example.com/a", "https://example.com/b"
    d, inbox = fixture([row(company="A", url=a), row(company="B", url=b)],
                       {a: mark("skip", a, r="other", bulk=True),
                        b: mark("skip", b, r="fit", bulk=True)})    # a tampered reason can't ride along
    rc, out = run(inbox, "--apply")
    t = tracker()
    assert t["A"]["his_verdict"] == "skip_other" and t["B"]["his_verdict"] == "skip_other", out
    assert t["A"]["notes"].endswith("cleared in bulk") and t["A"]["stage"] == "surfaced"
    assert "recorded 0 sent, 2 verdicts (2 skips)" in out, out


def test_failure_exits_zero_and_strict_exits_one():
    url = "https://example.com/a"
    d, inbox = fixture([row(company="A", url=url)], {url: mark("sent", url)})
    os.remove(si.OUTCOMES)
    rc, out = run(inbox, "--apply")
    assert rc == 0 and out.startswith("shelf_inbox: FAILED"), out
    rc, out = run(inbox, "--apply", "--strict")
    assert rc == 1
    with open(inbox, "w", encoding="utf-8") as f:
        f.write("{not json")
    rc, out = run(inbox, "--apply")
    assert rc == 0 and "FAILED" in out


# --- The weekly leads (D41, 2026-10-15) ---------------------------------------------------

def lead_fixture(lead_marks_on_page, queue_marks=None):
    """Same temp layout, plus a leads inbox and a lead_marks.json path inside the temp dir."""
    import lead_marks
    d, inbox = fixture([row(company="A", url="https://example.com/a")], queue_marks or {})
    with open(inbox, encoding="utf-8") as f:
        store = json.load(f)
    store[si.LEADS_KEY] = json.dumps(lead_marks_on_page)
    with open(inbox, "w", encoding="utf-8") as f:
        json.dump(store, f)
    lead_marks.PATH = os.path.join(si.JOBS_DIR, "lead_marks.json")
    return inbox, lead_marks


def lead(action, **kw):
    m = {"a": action, "d": "2026-10-11", "ts": 1, "u": "https://www.linkedin.com/jobs/view/3000001/",
         "c": "Brevik", "t": "Head of Support", "l": "unreachable", "tier": "tier1", "loc": "atlanta"}
    m.update(kw)
    return m


def test_leads_are_recorded_beside_queue_marks():
    url = "https://example.com/a"
    inbox, lm = lead_fixture({"3000001": lead("tailor"), "3000002": lead("pass", l="never_picked"),
                              "not-an-id": lead("tailor"), "3000003": lead("maybe")},
                             {url: mark("skip", url, r="fit")})
    rc, out = run(inbox, "--apply")
    assert rc == 0, out
    assert "recorded 0 sent, 1 verdicts (1 skips)" in out, out
    assert "leads: recorded 1 to tailor, 1 passed, 2 not recorded" in out, out
    assert "not a LinkedIn job id" in out and "unknown action" in out, out
    got = lm.load()
    assert set(got) == {"3000001", "3000002"}, got
    assert got["3000001"]["action"] == "tailor" and got["3000001"]["marked"] == "2026-10-11"
    assert got["3000001"]["recorded"] == TODAY and got["3000001"]["list"] == "unreachable"
    assert got["3000002"]["list"] == "never_picked"


def test_leads_report_only_without_apply_and_first_answer_wins():
    inbox, lm = lead_fixture({"3000001": lead("tailor")})
    rc, out = run(inbox)
    assert "leads: would record 1 to tailor, 0 passed" in out, out
    assert not os.path.exists(lm.PATH), "a report-only run writes nothing"
    run(inbox, "--apply")
    # A stale mark from before the drain says something else. The recorded answer stands.
    inbox2, _ = lead_fixture({"3000001": lead("pass")})
    lm.PATH = os.path.join(os.path.dirname(lm.PATH), "lead_marks.json")
    lm.save({"3000001": {"action": "tailor", "recorded": "2026-10-12"}})
    rc, out = run(inbox2, "--apply")
    assert "leads: nothing new, 1 already recorded" in out, out
    assert lm.load()["3000001"]["action"] == "tailor"


def test_a_lead_failure_never_stops_queue_marks():
    url = "https://example.com/a"
    inbox, lm = lead_fixture({"3000001": lead("tailor")}, {url: mark("skip", url, r="time")})
    with open(lm.PATH, "w", encoding="utf-8") as f:
        f.write("{broken")
    rc, out = run(inbox, "--apply")
    assert rc == 0 and "recorded 0 sent, 1 verdicts" in out and "leads: FAILED" in out, out
    assert tracker()["A"]["his_verdict"] == "skip_time"
    rc, out = run(inbox, "--apply", "--strict")
    assert rc == 1, "strict mode surfaces the lead failure"
    with open(lm.PATH, encoding="utf-8") as f:
        assert f.read() == "{broken", "a malformed record is never overwritten"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
