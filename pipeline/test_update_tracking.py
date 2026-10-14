#!/usr/bin/env python3
"""Tests for update_tracking.py: the append path, what the dedup leaves out, and
the retailor reopen. Fixtures are built in a temp dir with made-up companies;
nothing here reads the real tracker.

    .venv/bin/python pipeline/test_update_tracking.py

The reopen exists so the scripts that find a row by its URL keep working, so
several tests hand the rewritten tracker to those scripts and read the result.
"""
import contextlib
import csv
import io
import json
import os
import sys
import tempfile
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import age_report  # noqa: E402
import audit_scores  # noqa: E402
import build_dashboard  # noqa: E402
import check_voice  # noqa: E402
import fit_check  # noqa: E402
import mark_applied  # noqa: E402
import mark_outcome  # noqa: E402
import mark_verdict  # noqa: E402
import pipeline_quality  # noqa: E402
import rotate_apply_folder  # noqa: E402
import shelf_inbox  # noqa: E402
import update_tracking as ut  # noqa: E402

HEADER = list(ut.OUTCOMES_HEADER)
TODAY = "2026-10-13"
URL = "https://example.com/jobs/acme-tam"
OLD_STEM = "Jane_Doe_Acme_TAM"
STEM = "Jane_Doe_Acme_TAM_2"
OLD_NOTES = f"Full tailoring. First package. tailored/{OLD_STEM}.pdf + _cover.pdf"
NOTES = f"Full tier, resume + cover letter. tailored/apply_now/{STEM}.pdf + _cover.pdf"
# age_report.py, rotate_apply_folder.py, and the dashboard read the wall clock,
# so the tests that call them date their fixtures from it.
NOW = date.today()
LONG_AGO = (NOW - timedelta(days=90)).isoformat()


def row(**kw):
    base = dict.fromkeys(HEADER, "")
    base.update(company="Acme Robotics", title="Technical Account Manager", url=URL,
                fit_score="88", jd_coverage_pct="93", stage="expired", source_channel="pipeline",
                applied_date="2026-07-17", surfaced_date="2026-07-17", notes=OLD_NOTES)
    base.update(kw)
    return [base[h] for h in HEADER]


def job(**kw):
    base = dict(dedup_key="acme::technical-account-manager", company="Acme Robotics",
                title="Technical Account Manager", url=URL, score=101, jd_coverage_pct=80,
                unmet_hard_reqs=2, vendor_tool_named_in_jd="", hard_req_cap_trigger="none",
                ic_scope="ic", notes=NOTES)
    base.update(kw)
    return base


def retailor(**kw):
    return job(**{"retailor": STEM, **kw})


SEEN = {"acme::technical-account-manager": {
    "company": "Acme Robotics", "title": "Technical Account Manager", "url": URL,
    "first_seen_date": "2026-07-17", "last_seen_date": "2026-08-10", "score": 88,
    "applied": False, "outcome": None}}


def fixture(rows, seen=SEEN, header=HEADER):
    d = tempfile.mkdtemp(prefix="track_test_")
    jobs = os.path.join(d, "jobs")
    os.makedirs(jobs)
    ut.OUTCOMES = os.path.join(d, "outcomes.csv")
    ut.SEEN_JOBS = os.path.join(jobs, "seen_jobs.json")
    ut.SEEN_URLS = os.path.join(jobs, "seen_urls.json")
    ut.REOPENED_ROWS = os.path.join(jobs, "reopened_rows.jsonl")
    if rows is not None:
        with open(ut.OUTCOMES, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
    with open(ut.SEEN_JOBS, "w", encoding="utf-8") as f:
        json.dump({"jobs": json.loads(json.dumps(seen))}, f)
    return d


def run(d, jobs, run_date=TODAY):
    path = os.path.join(d, "track.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"run_date": run_date, "jobs": jobs}, f)
    buf, argv = io.StringIO(), sys.argv
    sys.argv = ["update_tracking.py", path]
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = ut.main()
    finally:
        sys.argv = argv
    return rc, buf.getvalue()


def tracker():
    with open(ut.OUTCOMES, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def raw():
    with open(ut.OUTCOMES, "rb") as f:
        return f.read()


def archive():
    if not os.path.exists(ut.REOPENED_ROWS):
        return []
    with open(ut.REOPENED_ROWS, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def seen_jobs():
    with open(ut.SEEN_JOBS, encoding="utf-8") as f:
        return json.load(f)["jobs"]


def untouched(before):
    return raw() == before and archive() == [] and not os.path.exists(ut.OUTCOMES + ut.REOPEN_BACKUP)


def call(module, *argv):
    """Run another tracker script's main() against this fixture's tracker."""
    module.OUTCOMES = ut.OUTCOMES
    if hasattr(module, "SEEN_JOBS"):
        module.SEEN_JOBS = ut.SEEN_JOBS
    buf, old = io.StringIO(), sys.argv
    sys.argv = [module.__name__ + ".py", *argv]
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = module.main()
    finally:
        sys.argv = old
    return rc, buf.getvalue()


def verdict(*argv):
    with contextlib.redirect_stdout(io.StringIO()):
        return mark_verdict.main(list(argv), path=ut.OUTCOMES)


# ---------------------------------------------------------------- append path

def test_a_new_job_appends_one_row_and_a_second_run_changes_nothing():
    d = fixture([row(company="Other Co", url="https://example.com/other")], seen={})
    j = job(notes=f"Full tier. tailored/apply_now/{OLD_STEM}.pdf + _cover.pdf")
    rc, out = run(d, [j])
    assert rc == 0 and "outcomes.csv: +1 rows" in out and "NO ROW WRITTEN" not in out, out
    rows = tracker()
    assert len(rows) == 2
    r = rows[1]
    assert (r["stage"], r["surfaced_date"], r["applied_date"]) == ("surfaced", TODAY, TODAY)
    assert (r["fit_score"], r["unmet_hard_reqs"], r["hard_req_cap_trigger"], r["ic_scope"]) == \
        ("101", "2", "none", "ic")
    assert r["his_verdict"] == "" and r["furthest_stage"] == "" and r["source_channel"] == "pipeline"
    before = raw()
    rc, out = run(d, [j])
    assert rc == 0 and raw() == before, out
    assert "1 already recorded today" in out and "NO ROW WRITTEN" not in out, out
    # a verdict appended to the row's notes since: still this job's own row
    assert verdict("Acme Robotics", "skip_time", "--url", URL, "--note", "busy week") == 0
    rc, out = run(d, [j])
    assert "1 already recorded today" in out and "NO ROW WRITTEN" not in out, out


def test_a_built_row_is_as_wide_as_the_header():
    assert len(ut.build_row(job(), TODAY)) == len(ut.OUTCOMES_HEADER)


def test_no_tracker_yet_creates_one_with_the_header():
    d = fixture(None, seen={})
    rc, _ = run(d, [job()])
    assert rc == 0
    with open(ut.OUTCOMES, newline="", encoding="utf-8") as f:
        got = list(csv.reader(f))
    assert got[0] == HEADER and len(got) == 2


def test_a_job_the_dedup_leaves_out_is_printed_and_nothing_is_written():
    d = fixture([row()])
    before = raw()
    rc, out = run(d, [job()])   # the 2026-10-13 case as it used to go: no key, no row
    assert rc == 0 and untouched(before)
    assert "outcomes.csv: +0 rows" in out and "NO ROW WRITTEN" in out, out
    assert "Acme Robotics — Technical Account Manager: its URL already has a row " \
           "(stage=expired, surfaced 2026-07-17)" in out, out
    assert '"retailor"' in out


def test_a_seen_key_with_a_new_url_is_printed_too():
    d = fixture([row()])
    before = raw()
    rc, out = run(d, [job(url="https://example.com/jobs/acme-tam-new-req")])
    assert rc == 0 and untouched(before)
    assert "its dedup key was seen before and its URL has no row" in out, out


def test_a_second_package_the_same_day_is_not_mistaken_for_a_rerun():
    # A row surfaced today for this URL, then another package for it with the key
    # forgotten. Step 6 notes open with the same tier boilerplate, so "starts with"
    # is not enough; calling it recorded would hide the loss this file exists to stop.
    boiler = "Full tier, resume + cover letter."
    d = fixture([row(stage="surfaced", surfaced_date=TODAY, applied_date=TODAY,
                     notes=f"{boiler} tailored/apply_now/{OLD_STEM}.pdf")])
    for notes in (boiler, NOTES):
        rc, out = run(d, [job(notes=notes)])
        assert "NO ROW WRITTEN" in out and "already recorded today" not in out, (notes, out)
    # with no notes at all on either side, the role itself has to match
    d = fixture([row(stage="surfaced", surfaced_date=TODAY, applied_date=TODAY, notes="")])
    rc, out = run(d, [job(notes="")])
    assert "1 already recorded today" in out, out
    rc, out = run(d, [job(notes="", title="Senior Technical Account Manager")])
    assert "NO ROW WRITTEN" in out, out


def test_null_or_numeric_notes_never_stop_the_file():
    # A row added by this run sits in memory with the job's raw values. A later job in
    # the same file reads it; that must not crash after seen_jobs.json is already written.
    d = fixture([row()], seen={})
    rc, out = run(d, [job(dedup_key="a::one", url="https://example.com/one", notes=None),
                      job(dedup_key="a::two", url="https://example.com/one", notes=None),
                      job(dedup_key="a::three", url="https://example.com/three", notes=7),
                      retailor(),
                      retailor(url="https://example.com/four", notes=7)])
    assert rc == 1 and "outcomes.csv: +2 rows" in out and "1 reopened" in out, out
    assert f"must name {STEM}.pdf" in out, out
    rows = tracker()
    assert [r["notes"] for r in rows[1:]] == ["", "7"] and rows[0]["stage"] == "surfaced"


def test_a_rerun_is_recognised_when_the_notes_ended_in_whitespace():
    d = fixture([], seen={})
    j = job(notes=f"Full tier. tailored/apply_now/{OLD_STEM}.pdf \n")
    run(d, [j])
    assert verdict("Acme Robotics", "skip_time", "--url", URL, "--note", "busy week") == 0
    rc, out = run(d, [j])
    assert "1 already recorded today" in out and "NO ROW WRITTEN" not in out, out


def test_two_jobs_sharing_a_url_in_one_file_make_one_row():
    d = fixture([], seen={})
    rc, out = run(d, [job(), job(dedup_key="acme::tam-alias")])
    assert rc == 0 and len(tracker()) == 1, out


# -------------------------------------------------------------------- reopen

def test_retailor_reopens_an_expired_row_in_place():
    target = row(his_verdict="skip_fit", source_channel="referral")
    d = fixture([row(company="Before Co", url="https://example.com/before", notes='He said "no", twice'),
                 target,
                 row(title="Support Operations Manager", url="https://example.com/jobs/acme-som",
                     stage="surfaced", surfaced_date="2026-10-09", applied_date="2026-10-09"),
                 row(company="Short Co", url="https://example.com/short")[:-3],     # a drifted row
                 row(company="After Co", url="https://example.com/after", stage="applied")])
    with open(ut.OUTCOMES, "a", newline="", encoding="utf-8") as f:
        f.write("\r\n")                                                            # and a blank line
    before = raw()
    rc, out = run(d, [retailor()])
    assert rc == 0, out
    assert "1 reopened for a new package" in out and f"[was expired] -> {STEM}" in out, out
    assert "his earlier verdict, skip_fit, is cleared" in out and f"earlier package {OLD_STEM}:" in out, out
    assert "NO ROW WRITTEN" not in out and "REFUSED" not in out
    rows = tracker()
    assert [r["url"] for r in rows].count(URL) == 1, "the URL stays on one row"
    r = rows[1]
    assert (r["stage"], r["surfaced_date"], r["applied_date"]) == ("surfaced", TODAY, TODAY)
    assert (r["fit_score"], r["jd_coverage_pct"], r["unmet_hard_reqs"], r["hard_req_cap_trigger"],
            r["ic_scope"]) == ("101", "80", "2", "none", "ic")
    assert r["his_verdict"] == "" and r["outcome"] == "" and r["furthest_stage"] == ""
    assert r["source_channel"] == "referral", "the job named no channel, so the row keeps its own"
    assert r["notes"] == (f"{NOTES}; reopened {TODAY}: this row was expired, last surfaced 2026-07-17, "
                          f"his verdict then skip_fit, package {OLD_STEM}; it now carries a new package, "
                          f"and the row as it stood is in jobs/reopened_rows.jsonl")
    assert f"{OLD_STEM}.pdf" not in r["notes"], "the old PDF name would bind the old files to this row"
    # every other line, byte for byte (the drifted row and the blank line included)
    old_lines, new_lines = before.split(b"\r\n"), raw().split(b"\r\n")
    assert len(old_lines) == len(new_lines), "a reopen never adds or drops a line"
    assert [i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b] == [2]
    with open(ut.OUTCOMES + ut.REOPEN_BACKUP, "rb") as f:
        assert f.read() == before
    # the row as it stood, whole
    kept = archive()
    assert len(kept) == 1 and kept[0]["reopened_on"] == TODAY and kept[0]["new_package"] == STEM
    assert kept[0]["row"] == dict(zip(HEADER, target))
    # seen_jobs: the poller's dedup date is not ours to move
    s = seen_jobs()["acme::technical-account-manager"]
    assert (s["first_seen_date"], s["last_seen_date"]) == ("2026-07-17", TODAY)


def test_a_second_run_of_a_retailor_changes_nothing_and_archives_once():
    d = fixture([row()])
    run(d, [retailor()])
    after = raw()
    rc, out = run(d, [retailor()])
    assert rc == 0 and raw() == after and len(archive()) == 1, out
    assert "1 already recorded today" in out and "reopened" not in out, out
    # ...and the day after, the same file is a request to restart the clock: refused
    rc, out = run(d, [retailor()], run_date="2026-10-14")
    assert rc == 1 and raw() == after and len(archive()) == 1 and "does not restart the clock" in out, out


def test_a_backfilled_pre_epoch_date_gap_is_not_a_send():
    # backfill_surfaced_date.py set old rows' surfaced_date from seen_jobs, so a
    # pre-epoch row can show two dates without ever having been promoted.
    d = fixture([row(surfaced_date="2026-05-06", applied_date="2026-07-13")])
    rc, out = run(d, [retailor()])
    assert rc == 0 and "1 reopened" in out, out


def test_a_same_day_send_is_caught_by_what_the_promotion_left_in_seen_jobs():
    # Sent the day it was surfaced, closed later: the two dates are equal, the verdict is
    # blank, and only seen_jobs.json still says a confirmation promoted it.
    sent = dict(stage="closed", outcome="closed", surfaced_date="2026-09-08", applied_date="2026-09-08")
    flagged = {k: dict(v, applied=True) for k, v in SEEN.items()}
    d = fixture([row(**sent)], seen=flagged)
    before = raw()
    rc, out = run(d, [retailor(never_sent=True)])
    assert rc == 1 and untouched(before) and "seen_jobs.json has this URL as applied" in out, out
    # the same row without the flag is his word against nothing, and his word stands
    d = fixture([row(**sent)])
    rc, out = run(d, [retailor(never_sent=True)])
    assert rc == 0 and "[was closed]" in out, out
    # a pre-epoch flag is a self-report from before confirmations existed: not a refusal
    d = fixture([row()], seen=flagged)
    rc, out = run(d, [retailor()])
    assert rc == 0 and "1 reopened" in out, out


def test_an_archive_line_cut_short_by_a_crash_is_not_glued_to_the_next():
    d = fixture([row()])
    with open(ut.REOPENED_ROWS, "w", encoding="utf-8") as f:
        f.write('{"reopened_on": "2026-10-01", "row": {"comp')
    rc, out = run(d, [retailor()])
    assert rc == 0, out
    with open(ut.REOPENED_ROWS, encoding="utf-8") as f:
        lines = f.read().split("\n")
    assert len(lines) == 3 and lines[2] == "" and json.loads(lines[1])["new_package"] == STEM, lines


def test_a_changed_title_at_the_same_url_is_recorded_as_posted_now():
    d = fixture([row(title="Manager, Technical Support")])
    rc, out = run(d, [retailor(dedup_key="acme::senior-manager-technical-support",
                               title="Senior Manager, Technical Support", source_channel="user_surfaced")])
    assert rc == 0 and 'the row\'s title was "Manager, Technical Support"' in out, out
    r = tracker()[0]
    assert r["title"] == "Senior Manager, Technical Support" and r["source_channel"] == "user_surfaced"
    assert "acme::senior-manager-technical-support" in seen_jobs()


def test_retailor_for_a_new_requisition_under_a_seen_key_appends():
    d = fixture([row(stage="applied")])
    before = raw()
    rc, out = run(d, [retailor(url="https://example.com/jobs/acme-tam-req-2")])
    assert rc == 0 and "outcomes.csv: +1 rows" in out and "reopened" not in out, out
    assert raw().startswith(before) and len(tracker()) == 2 and archive() == []
    assert tracker()[1]["stage"] == "surfaced" and tracker()[0]["stage"] == "applied"


def test_closed_is_reopened_only_when_he_says_it_was_never_sent():
    d = fixture([row(stage="closed", outcome="closed")])
    before = raw()
    rc, out = run(d, [retailor()])
    assert rc == 1 and untouched(before) and "never_sent" in out, out
    rc, out = run(d, [retailor(never_sent="yes")])   # only a real true counts
    assert rc == 1 and untouched(before)
    rc, out = run(d, [retailor(never_sent=True)])
    assert rc == 0 and "[was closed]" in out, out
    r = tracker()[0]
    assert (r["stage"], r["outcome"]) == ("surfaced", "")
    assert archive()[0]["row"]["outcome"] == "closed"


PROMOTED = dict(surfaced_date="2026-08-14", applied_date="2026-08-15")   # what mark_applied.py leaves
REFUSALS = [
    ("applied", dict(stage="applied"), {}, "looks sent (stage=applied)"),
    ("rejected", dict(stage="rejected", outcome="rejected"), {}, "looks sent (stage=rejected)"),
    ("interview", dict(stage="interview"), {}, "looks sent (stage=interview)"),
    ("sent verdict", dict(his_verdict="sent_as_is"), {}, "looks sent (his_verdict=sent_as_is)"),
    ("furthest stage", dict(furthest_stage="applied"), {}, "looks sent (furthest_stage=applied)"),
    ("an outcome", dict(outcome="pending"), {}, "looks sent (outcome=pending)"),
    ("shelf note", dict(notes="x; verdict: marked sent on the Shelf 2026-08-01, no confirmation email yet"),
     {}, "its notes say he marked it sent"),
    ("promoted, then expired", dict(PROMOTED), {}, "applied_date 2026-08-15 moved off surfaced_date 2026-08-14"),
    ("promoted, then closed", dict(PROMOTED, stage="closed", outcome="closed"), dict(never_sent=True),
     "applied_date 2026-08-15 moved off surfaced_date 2026-08-14"),
    ("closed with a sent verdict", dict(stage="closed", his_verdict="sent_edited"), dict(never_sent=True),
     "looks sent (his_verdict=sent_edited)"),
    ("still open", dict(stage="surfaced", surfaced_date="2026-09-20", applied_date="2026-09-20"), {},
     "its row is still open (surfaced 2026-09-20)"),
    ("still open, skipped", dict(stage="surfaced", his_verdict="skip_materials"), {}, "its row is still open"),
    ("legacy stage", dict(stage="tailored"), {}, "stage=tailored is not one a retailor reopens"),
    ("blank stage", dict(stage=""), {}, "stage=blank is not one a retailor reopens"),
    ("another company at the url", dict(company="Borealis Labs"), {}, "belongs to Borealis Labs"),
    ("true, not a stem", {}, dict(retailor=True), "must be the new package's stem"),
    ("a path, not a stem", {}, dict(retailor=f"tailored/{STEM}.pdf"), "must be the new package's stem"),
    ("notes without the pdf", {}, dict(notes="Full tier, resume + cover letter."), f"must name {STEM}.pdf"),
    ("notes name the old pdf only", {}, dict(notes=f"tailored/{OLD_STEM}.pdf"), f"must name {STEM}.pdf"),
    ("no url", {}, dict(url=""), "needs the posting URL"),
    ("same package again", dict(notes=f"tailored/{STEM}.pdf + _cover.pdf"), {}, "does not restart the clock"),
]


def test_refusals_write_nothing_and_exit_one():
    for name, row_kw, job_kw, expect in REFUSALS:
        d = fixture([row(**row_kw)])
        before = raw()
        rc, out = run(d, [retailor(**job_kw)])
        assert rc == 1, (name, out)
        assert "RETAILOR REFUSED (nothing written for these): 1" in out and expect in out, (name, out)
        assert untouched(before), name


def test_two_rows_sharing_the_url_are_left_for_a_person():
    d = fixture([row(), row(stage="applied")])
    before = raw()
    rc, out = run(d, [retailor()])
    assert rc == 1 and untouched(before) and "2 rows share its URL" in out, out


def test_a_stem_another_row_names_is_refused():
    for other in (f"tailored/{STEM}.pdf", f"tailored/apply_now/{STEM}_cover.pdf", f"{STEM}_ATS.pdf"):
        d = fixture([row(), row(company="Borealis Labs", url="https://example.com/b", notes=other)])
        before = raw()
        rc, out = run(d, [retailor()])
        assert rc == 1 and untouched(before), out
        assert f"{STEM}.pdf is already named by another row (Borealis Labs — " in out, out


def test_a_drifted_tracker_or_row_is_never_rewritten():
    d = fixture([row()[:-1]], header=HEADER[:-1])          # a schema one column behind
    before = raw()
    rc, out = run(d, [retailor()])
    assert rc == 1 and untouched(before) and "repair_outcomes.py" in out, out
    d = fixture([row()[:-2]])                              # one short row under the current header
    before = raw()
    rc, out = run(d, [retailor()])
    assert rc == 1 and untouched(before) and "drifted columns" in out, out


def test_one_refusal_does_not_block_the_rest_of_the_file():
    d = fixture([row(), row(company="Sent Co", title="Ops Lead", url="https://example.com/sent", stage="applied")],
                seen=dict(SEEN, **{"sent::ops-lead": {"url": "https://example.com/sent"}}))
    rc, out = run(d, [
        job(dedup_key="newco::csm", company="New Co", title="CSM", url="https://example.com/new",
            notes="tailored/apply_now/Jane_Doe_NewCo_CSM.pdf"),
        retailor(),
        job(dedup_key="sent::ops-lead", company="Sent Co", title="Ops Lead", url="https://example.com/sent",
            retailor="Jane_Doe_SentCo_OpsLead_2", notes="tailored/apply_now/Jane_Doe_SentCo_OpsLead_2.pdf")])
    assert rc == 1, out
    assert "outcomes.csv: +1 rows" in out and "1 reopened" in out and "REFUSED (nothing written for these): 1" in out
    rows = tracker()
    assert [(r["company"], r["stage"]) for r in rows] == \
        [("Acme Robotics", "surfaced"), ("Sent Co", "applied"), ("New Co", "surfaced")]


# ------------------------------------- the scripts that find a row by its URL

def reopened_tracker(extra=(), run_date=TODAY, **row_kw):
    d = fixture([row(**row_kw), *extra])
    rc, out = run(d, [retailor()], run_date=run_date)
    assert rc == 0, out
    return d


def test_a_confirmation_promotes_the_reopened_row_and_only_it():
    sibling = row(title="Technical Account Manager, EMEA", url="https://example.com/jobs/acme-tam-emea",
                  stage="surfaced", surfaced_date="2026-10-09", applied_date="2026-10-09")
    d = reopened_tracker([sibling])
    conf = os.path.join(d, "conf.json")
    with open(conf, "w", encoding="utf-8") as f:
        json.dump({"confirmations": [{"url": URL + "/", "company": "Acme Robotics",
                                      "title": "Technical Account Manager",
                                      "applied_date": "2026-10-14"}]}, f)
    rc, out = call(mark_applied, conf)
    assert "1 promoted to stage=applied" in out and "NOT SURFACED AND NOT SENT" not in out, out
    rows = tracker()
    assert (rows[0]["stage"], rows[0]["applied_date"], rows[0]["surfaced_date"]) == \
        ("applied", "2026-10-14", TODAY)
    assert rows[1]["stage"] == "surfaced"
    assert seen_jobs()["acme::technical-account-manager"]["applied"] is True
    # ...and Step 6 run again that day finds its own row, promoted or not
    before = raw()
    rc, out = run(d, [retailor()])
    assert rc == 0 and raw() == before and "1 already recorded today" in out, out
    # ...and the same confirmation arriving again is the quiet "already recorded"
    rc, out = call(mark_applied, conf)
    assert "ALREADY RECORDED" in out and "0 promoted" in out, out
    # ...and a sent row is now out of a retailor's reach
    before = raw()
    rc, out = run(d, [job(retailor="Jane_Doe_Acme_TAM_3",
                          notes="tailored/apply_now/Jane_Doe_Acme_TAM_3.pdf")], run_date="2026-10-20")
    assert rc == 1 and raw() == before and "looks sent (stage=applied)" in out, out


def test_a_reopened_row_sent_the_same_day_and_later_closed_is_not_reopened_again():
    d = reopened_tracker()
    conf, closed = os.path.join(d, "conf.json"), os.path.join(d, "closed.json")
    with open(conf, "w", encoding="utf-8") as f:
        json.dump({"confirmations": [{"url": URL, "company": "Acme Robotics", "applied_date": TODAY}]}, f)
    with open(closed, "w", encoding="utf-8") as f:
        json.dump({"outcomes": [{"company": "Acme Robotics", "url": URL, "outcome": "closed"}]}, f)
    call(mark_applied, conf)
    call(mark_outcome, closed)
    r = tracker()[0]
    assert (r["stage"], r["applied_date"], r["surfaced_date"], r["his_verdict"]) == ("closed", TODAY, TODAY, "")
    before = raw()
    rc, out = run(d, [job(retailor="Jane_Doe_Acme_TAM_3", never_sent=True,
                          notes="tailored/apply_now/Jane_Doe_Acme_TAM_3.pdf")], run_date="2026-12-01")
    assert rc == 1 and raw() == before and "seen_jobs.json has this URL as applied" in out, out


def test_before_the_reopen_that_confirmation_had_nowhere_to_land():
    d = fixture([row()])
    conf = os.path.join(d, "conf.json")
    with open(conf, "w", encoding="utf-8") as f:
        json.dump({"confirmations": [{"url": URL, "company": "Acme Robotics",
                                      "applied_date": "2026-10-14"}]}, f)
    rc, out = call(mark_applied, conf)
    assert "URL MATCHES A ROW THAT IS NOT SURFACED AND NOT SENT" in out and "0 promoted" in out, out


def test_shelf_marks_land_on_the_reopened_row():
    for mark, want_stage, want_verdict in (({"a": "sent"}, "applied", "sent_as_is"),
                                           ({"a": "skip", "r": "fit"}, "surfaced", "skip_fit")):
        d = reopened_tracker()
        inbox = os.path.join(d, "storage.json")
        with open(inbox, "w", encoding="utf-8") as f:
            json.dump({shelf_inbox.INBOX_KEY: json.dumps({URL: dict(
                mark, d=TODAY, ts=1, u=URL, c="Acme Robotics", t="Technical Account Manager")})}, f)
        shelf_inbox.OUTCOMES, shelf_inbox.SEEN_JOBS = ut.OUTCOMES, ut.SEEN_JOBS
        shelf_inbox.JOBS_DIR = os.path.join(d, "jobs")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = shelf_inbox.main(["--inbox", inbox, "--today", TODAY, "--apply", "--strict"])
        assert rc == 0 and "0 not matched" in buf.getvalue() and "PROBLEMS" not in buf.getvalue(), buf.getvalue()
        r = tracker()[0]
        assert (r["stage"], r["his_verdict"]) == (want_stage, want_verdict), (mark, r)


def test_a_verdict_and_an_outcome_by_url_find_one_row():
    d = reopened_tracker()
    assert verdict("Acme Robotics", "skip_time", "--url", URL) == 0
    assert tracker()[0]["his_verdict"] == "skip_time"
    out_file = os.path.join(d, "out.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({"outcomes": [{"company": "Acme Robotics", "url": URL, "outcome": "closed"}]}, f)
    rc, out = call(mark_outcome, out_file)
    assert "updated 1 existing rows" in out and "AMBIGUOUS" not in out, out
    assert tracker()[0]["stage"] == "closed"


def test_the_reopened_row_gets_a_fresh_45_days_and_a_hand_flip_would_not():
    old = dict(surfaced_date=LONG_AGO, applied_date=LONG_AGO)
    reopened_tracker([row(company="Hand Flipped Co", url="https://example.com/flipped", stage="surfaced", **old)],
                     run_date=NOW.isoformat(), **old)
    call(age_report, "--apply")
    got = {r["company"]: r["stage"] for r in tracker()}
    assert got == {"Acme Robotics": "surfaced", "Hand Flipped Co": "expired"}, got


def test_the_package_scripts_find_the_row_by_the_new_pdf():
    d = reopened_tracker(run_date=NOW.isoformat())
    rows = tracker()
    for name in (f"{STEM}.pdf", f"{STEM}_cover.pdf", f"{STEM}_ATS.pdf"):
        found = rotate_apply_folder.find_row(rows, name)
        assert found is rows[0], name
        assert rotate_apply_folder.decide(found, os.path.join(d, name), NOW) == (False, "surfaced 0d ago")
    assert rotate_apply_folder.find_row(rows, f"{OLD_STEM}.pdf") is None
    assert len(fit_check.rows_naming(rows, STEM)) == 1 and fit_check.rows_naming(rows, OLD_STEM) == []
    check_voice.OUTCOMES = ut.OUTCOMES
    assert check_voice.stage_of(f"tailored/{STEM}_cover.md") == "surfaced"
    assert check_voice.stage_of(f"tailored/{OLD_STEM}_cover.md") is None   # reads as ASK, never editable


def test_the_dashboard_queues_the_reopened_row_with_its_new_pdfs():
    d = reopened_tracker(run_date=NOW.isoformat())
    apply_now = os.path.join(d, "tailored", "apply_now")
    os.makedirs(apply_now)
    for name in (f"{OLD_STEM}.pdf", f"{OLD_STEM}_cover.pdf"):
        open(os.path.join(d, "tailored", name), "w").close()
    for name in (f"{STEM}.pdf", f"{STEM}_cover.pdf"):
        open(os.path.join(apply_now, name), "w").close()
    bd = build_dashboard
    bd.OUTCOMES, bd.REPO, bd.TAILORED, bd.APPLY_NOW = ut.OUTCOMES, d, os.path.join(d, "tailored"), apply_now
    bd.JOBS_DIR, bd.PDF_PREFIX = os.path.join(d, "jobs"), "Jane_Doe_"
    queue, quiet, counts = bd.read_outcomes(NOW, {})
    assert len(queue) == 1 and not quiet and counts["skipped"] == 0, (queue, counts)
    q = queue[0]
    assert q["key"] == URL and q["surfaced"] == NOW.isoformat() and q["score"] == 101
    assert q["resume"].endswith(f"apply_now/{STEM}.pdf") and q["cover"].endswith(f"apply_now/{STEM}_cover.pdf")
    # the cleared list still drops the URL: it has a row
    with open(os.path.join(bd.JOBS_DIR, f"screened_{NOW.isoformat()}.json"), "w", encoding="utf-8") as f:
        json.dump({"roles": [{"company": "Acme Robotics", "title": "TAM", "url": URL, "score": 90}]}, f)
    assert bd.read_screened(NOW)[0] == []


def test_the_quality_report_counts_a_reopened_posting_once():
    reopened_tracker([row(company="Borealis Labs", url="https://example.com/b", stage="applied",
                          surfaced_date="2026-10-01", applied_date="2026-10-02")])
    text = pipeline_quality.report(pipeline_quality.load(ut.OUTCOMES, pipeline_quality.EPOCH))
    assert "Tailored: 2 | sent: 1/2 (50%) | still open: 1 | expired unsent: 0" in text, text
    assert "1 of these rows was reopened for a new package" in text, text


def test_the_stamp_is_not_scoring_evidence():
    reopened_tracker(his_verdict="skip_fit")
    stamp = tracker()[0]["notes"][len(NOTES):]
    assert stamp.startswith("; reopened ") and "skip_fit" in stamp and OLD_STEM in stamp
    assert audit_scores.parse_tier(stamp) is None
    assert not audit_scores.user_directed(stamp) and not audit_scores.documented_override(stamp)
    assert audit_scores.rubric_drift(stamp, "2026-07-01", "surfaced") == (False, 0, False)
    assert audit_scores.location_component(stamp)[1] == "not parseable from notes"
    assert audit_scores.salary_component(stamp)[1] == "not parseable from notes"
    assert not audit_scores.CAP_FIRES.search(stamp) and not audit_scores.CAP_DECLINED.search(stamp)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
