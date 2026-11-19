#!/usr/bin/env python3
"""Tests for the sender check on receipts and outcomes (sender_check.py).

    .venv/bin/python pipeline/test_sender_check.py

Added 2026-11-19 (DECISIONS.md D60). The fleet red team of 2026-11-17 mailed
the confirmation alias a "thank you for applying" from a look-alike domain, and
Step 0.5 promoted that row in 4 of 6 runs. What is pinned here:
  - the senders that may move a row: an ATS domain from job_mail_terms.json,
    an exact address listed there, LinkedIn's application sender, Indeed, and
    the row's own job-URL domain;
  - the ones that may not: a look-alike of the company, a display name that
    claims to be him, no address at all;
  - mark_applied.py and mark_outcome.py move nothing for an untrusted sender and
    say so, still move rows for a trusted one, and leave items without a sender
    (his dashboard marks, hand-recorded outcomes) exactly as before.

Every company and address below is made up. Each case builds its own tracker
in a temp dir and points the script at it; the real outcomes.csv is never
opened.
"""
import contextlib
import csv
import io
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sender_check as S  # noqa: E402
import mark_applied as A  # noqa: E402
import mark_outcome as O  # noqa: E402
import repair_outcomes as R  # noqa: E402

HEADER = list(R.CANONICAL)
ATS_ROW = "https://job-boards.greenhouse.io/acmewidgets/jobs/1001"
SITE_ROW = "https://careers.borealis.example/jobs/2002"
UK_ROW = "https://jobs.caldera.co.uk/roles/3003"
FAILURES = []
TEMP_DIRS = []


def expect(name, got, want):
    if got != want:
        FAILURES.append(f"{name}: got {got!r}, want {want!r}")


def trusted(sender, row_url=""):
    return S.check(sender, row_url)[0]


def test_unit():
    expect("ATS domain", trusted("Acme Recruiting <no-reply@greenhouse-mail.io>"), True)
    expect("ATS subdomain", trusted("no-reply@us.greenhouse-mail.io"), True)
    expect("ATS domain, bare address", trusted("notifications@hire.lever.co"), True)
    expect("listed exact address", trusted("Google <noreply+jobs@google.com>"), True)
    expect("unlisted address on that domain", trusted("someone@google.com"), False)
    expect("LinkedIn application sender", trusted("LinkedIn <jobs-noreply@linkedin.com>"), True)
    expect("other LinkedIn sender, no LinkedIn row", trusted("messages-noreply@linkedin.com"), False)
    expect("Indeed Apply", trusted("Indeed Apply <indeedapply@indeed.com>"), True)
    expect("row's own domain", trusted("Borealis Talent <talent@borealis.example>", SITE_ROW), True)
    expect("row's own domain, subdomain sender", trusted("no-reply@mail.borealis.example", SITE_ROW), True)
    expect("look-alike of the row's domain", trusted("no-reply@borealis-hiring.example", SITE_ROW), False)
    expect("look-alike with an ATS row", trusted("no-reply@acmewidgets-hiring.example", ATS_ROW), False)
    expect("company domain, ATS-hosted row", trusted("careers@acmewidgets.example", ATS_ROW), False)
    expect("a name claiming to be the owner", trusted("Job Seeker <owner@home-mail.example>"), False)
    expect("two-label suffix row", trusted("talent@caldera.co.uk", UK_ROW), True)
    expect("two-label suffix stranger", trusted("talent@other.co.uk", UK_ROW), False)
    expect("no address", trusted("Acme Talent"), False)
    expect("empty sender", trusted(""), False)
    expect("missing sender", trusted(None), False)
    expect("address hidden in the name", trusted('"no-reply@greenhouse-mail.io" <x@lookalike.example>'), False)


def row(**kw):
    base = dict.fromkeys(HEADER, "")
    base.update(surfaced_date="2026-11-10", fit_score="90", jd_coverage_pct="90",
                source_channel="pipeline", stage="surfaced")
    base.update(kw)
    return [base[h] for h in HEADER]


ROWS = [
    row(company="Acme Widgets", title="Support Operations Manager", url=ATS_ROW),
    row(company="Borealis", title="Head of Support", url=SITE_ROW),
    row(company="Cobalt Grove", title="Technical Support Manager",
        url="https://jobs.ashbyhq.com/cobaltgrove/4004"),
]


def tracker():
    d = tempfile.mkdtemp(prefix="sendercheck-")
    TEMP_DIRS.append(d)
    p = os.path.join(d, "outcomes.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(ROWS)
    return d, p


def run(module, items_key, items, d):
    inp = os.path.join(d, "in.json")
    json.dump({items_key: items}, open(inp, "w", encoding="utf-8"))
    saved = (module.OUTCOMES, getattr(module, "SEEN_JOBS", None), sys.argv)
    module.OUTCOMES = os.path.join(d, "outcomes.csv")
    if hasattr(module, "SEEN_JOBS"):
        module.SEEN_JOBS = os.path.join(d, "seen_jobs.json")
    sys.argv = [module.__name__ + ".py", inp]
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            rc = module.main()
    finally:
        module.OUTCOMES, seen, sys.argv = saved
        if seen is not None:
            module.SEEN_JOBS = seen
    return rc, out.getvalue()


def read_rows(p):
    with open(p, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {r["company"]: r for r in rows}


def test_mark_applied():
    d, p = tracker()
    rc, out = run(A, "confirmations", [
        {"url": ATS_ROW, "company": "Acme Widgets", "title": "Support Operations Manager",
         "applied_date": "2026-11-17", "sender": "Acme Widgets Talent <no-reply@acmewidgets-hiring.example>"},
        {"company": "Borealis", "title": "Head of Support", "applied_date": "2026-11-17",
         "sender": "Borealis Talent <talent@borealis.example>"},
        {"url": "https://jobs.ashbyhq.com/cobaltgrove/4004", "company": "Cobalt Grove",
         "applied_date": "2026-11-16"},
    ], d)
    rows = read_rows(p)
    expect("applied: look-alike receipt not promoted", rows["Acme Widgets"]["stage"], "surfaced")
    expect("applied: look-alike listed", "UNTRUSTED SENDER" in out and "acmewidgets-hiring.example" in out, True)
    expect("applied: own-domain receipt promoted", rows["Borealis"]["stage"], "applied")
    expect("applied: no-sender (dashboard) item promoted", rows["Cobalt Grove"]["stage"], "applied")
    expect("applied: exit code", rc, 0)

    d, p = tracker()
    rc, out = run(A, "confirmations", [
        {"url": ATS_ROW, "company": "Acme Widgets", "applied_date": "2026-11-17",
         "sender": "no-reply@us.greenhouse-mail.io"}], d)
    expect("applied: ATS receipt promoted", read_rows(p)["Acme Widgets"]["stage"], "applied")
    expect("applied: nothing untrusted printed", "UNTRUSTED SENDER" in out, False)

    d, p = tracker()
    before = open(p, encoding="utf-8").read()
    rc, out = run(A, "confirmations", [
        {"url": ATS_ROW, "company": "Acme Widgets", "applied_date": "2026-11-17", "sender": ""}], d)
    expect("applied: empty sender moves nothing", open(p, encoding="utf-8").read(), before)


def test_mark_outcome():
    d, p = tracker()
    before = open(p, encoding="utf-8").read()
    rc, out = run(O, "outcomes", [
        {"company": "Acme Widgets", "title": "Support Operations Manager", "url": ATS_ROW,
         "outcome": "offer", "outcome_date": "2026-11-16",
         "sender": "Partner Network <status@acmewidgets-careers.example>"},
        {"company": "Driftwood Labs", "title": "Support Lead", "url": "https://driftwood-careers.example/1",
         "outcome": "offer", "append_if_missing": True,
         "sender": "Driftwood <hr@driftwood-careers.example>"},
    ], d)
    expect("outcome: look-alike offer writes nothing", open(p, encoding="utf-8").read(), before)
    expect("outcome: both listed", out.count("acmewidgets-careers.example") + out.count("driftwood-careers.example"), 2)
    expect("outcome: exit code", rc, 0)

    d, p = tracker()
    rc, out = run(O, "outcomes", [
        {"company": "Cobalt Grove", "title": "Technical Support Manager", "outcome": "rejected",
         "sender": "Cobalt Grove <no-reply@ashbyhq.com>"},
        {"company": "Borealis", "title": "Head of Support", "outcome": "interview"},
    ], d)
    rows = read_rows(p)
    expect("outcome: ATS rejection recorded", rows["Cobalt Grove"]["outcome"], "rejected")
    expect("outcome: hand-recorded (no sender) still recorded", rows["Borealis"]["outcome"], "interview")
    expect("outcome: nothing untrusted printed", "UNTRUSTED SENDER" in out, False)


def main():
    try:
        test_unit()
        test_mark_applied()
        test_mark_outcome()
    finally:
        for d in TEMP_DIRS:
            shutil.rmtree(d, ignore_errors=True)
    if FAILURES:
        print(f"FAIL ({len(FAILURES)}):")
        for f in FAILURES:
            print("  " + f)
        return 1
    print("ok: sender check, mark_applied, and mark_outcome cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
