#!/usr/bin/env python3
"""Tests for log_interview.py. Everything runs against a temp log with made-up companies.

    .venv/bin/python pipeline/test_log_interview.py
"""
import json
import os
import sys
import tempfile
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log_interview as li  # noqa: E402


def run(rounds):
    d = tempfile.mkdtemp(prefix="li_test_")
    path = os.path.join(d, "in.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"rounds": rounds}, f)
    assert li.main([path]) == 0
    with open(li.LOG, encoding="utf-8") as f:
        return json.load(f)["rounds"]


def fresh_log():
    li.LOG = os.path.join(tempfile.mkdtemp(prefix="li_log_"), "jobs", "interviews.json")


def test_numbers_by_date_and_never_numbers_an_assessment():
    fresh_log()
    got = run([{"company": "Acme", "date": "2026-09-10", "kind": "interview"},
               {"company": "Acme", "date": "2026-09-01", "kind": "screen"},
               {"company": "Acme", "date": "2026-09-05", "kind": "assessment", "round": 4}])
    assert [(r["date"], r["kind"], r["round"]) for r in got] == [
        ("2026-09-01", "screen", 1), ("2026-09-05", "assessment", None), ("2026-09-10", "interview", 2)], got
    # An earlier round logged afterwards moves the auto-numbered ones along; a given number stays.
    run([{"company": "Dune", "date": "2026-09-10", "kind": "interview"},
         {"company": "Dune", "date": "2026-09-12", "kind": "onsite", "round": 5}])
    got = run([{"company": "Dune", "date": "2026-09-02", "kind": "screen"}])
    assert [(r["date"], r["round"]) for r in got if r["company"] == "Dune"] == [
        ("2026-09-02", 1), ("2026-09-10", 2), ("2026-09-12", 5)], got


def test_a_rerun_updates_in_place_instead_of_adding_a_copy():
    fresh_log()
    run([{"company": "Bolt", "date": "2026-09-02", "kind": "screen", "label": "R1"}])
    got = run([{"company": "bolt", "date": "2026-09-02", "kind": "screen", "label": "R1 recruiter screen"},
               {"company": "Bolt", "date": "2026-09-02", "kind": "screen", "label": "R1 recruiter screen"}])
    assert len(got) == 1 and got[0]["label"] == "R1 recruiter screen" and got[0]["round"] == 1, got
    assert os.path.exists(li.LOG + ".bak"), "the previous log is kept beside it"


def test_refuses_bad_input_and_future_rounds():
    fresh_log()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    got = run([{"company": "Cove", "date": tomorrow, "kind": "screen"},
               {"company": "Cove", "date": "2026-13-01", "kind": "screen"},
               {"company": "Cove", "date": "2026-09-03", "kind": "lunch"},
               {"company": "", "date": "2026-09-03", "kind": "screen"},
               {"company": "Cove", "date": "2026-09-03", "kind": "screen", "round": True},
               "not a round",
               {"company": "Cove", "date": "2026-09-03", "kind": "onsite", "round": 3}])
    assert [(r["company"], r["kind"], r["round"]) for r in got] == [("Cove", "onsite", 3)], got


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
