#!/usr/bin/env python3
"""Tests for age_report.py's "high score, never sent" callout. Made-up rows only.

    .venv/bin/python pipeline/test_age_report.py
"""
import contextlib
import csv
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import age_report as ar  # noqa: E402

BASE = ["applied_date", "company", "title", "url", "fit_score", "jd_coverage_pct", "stage",
        "outcome", "notes", "source_channel", "surfaced_date"]


def report(header, rows, *flags):
    d = tempfile.mkdtemp(prefix="age_test_")
    ar.OUTCOMES = os.path.join(d, "outcomes.csv")
    with open(ar.OUTCOMES, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            base = dict.fromkeys(header, "")
            base.update(stage="surfaced", surfaced_date="2020-01-01", fit_score="110")
            base.update(r)
            w.writerow([base[h] for h in header])
    buf, argv = io.StringIO(), sys.argv
    sys.argv = ["age_report.py", *flags]
    try:
        with contextlib.redirect_stdout(buf):
            ar.main()
    finally:
        sys.argv = argv
    return buf.getvalue()


def stages():
    with open(ar.OUTCOMES, newline="", encoding="utf-8") as f:
        return {r["company"]: r["stage"] for r in csv.DictReader(f)}


def test_a_skipped_row_is_not_called_out_as_unsent_but_still_retires():
    header = BASE + ["his_verdict"]
    rows = [{"company": "Unsent Co"}, {"company": "Skipped Co", "his_verdict": "skip_fit"},
            {"company": "Sent Verdict Co", "his_verdict": "sent_as_is"}]
    out = report(header, rows)
    callout = out.split("score >=100")[1].split("older than")[1] if "score >=100" in out else ""
    assert "Unsent Co" in out and "Sent Verdict Co" in out, out
    assert "Skipped Co" not in out, "he decided to pass; it isn't unsent work to nag about"
    assert "(2 roles" in out, out
    assert "still stage=surfaced: 3" in out, "all three are still counted as stale"
    report(header, rows, "--apply")
    assert set(stages().values()) == {"expired"}, "a skipped row retires on the same schedule"


def test_a_tracker_without_the_verdict_column_reports_everything():
    out = report(BASE, [{"company": "Old Schema Co"}])
    assert "Old Schema Co" in out and "(1 roles" in out, out


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
