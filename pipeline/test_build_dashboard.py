#!/usr/bin/env python3
"""Tests for build_dashboard.py. Fixtures are built in a temp dir with made-up
companies; nothing here reads the real tracking files.

    .venv/bin/python pipeline/test_build_dashboard.py
"""
import csv
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_dashboard as bd  # noqa: E402

HEADER = ["applied_date", "company", "title", "url", "fit_score", "jd_coverage_pct", "stage",
          "outcome", "notes", "source_channel", "surfaced_date", "unmet_hard_reqs",
          "vendor_tool_named_in_jd", "hard_req_cap_trigger", "furthest_stage", "ic_scope"]
TODAY = date(2026, 9, 19)


def row(**kw):
    base = dict.fromkeys(HEADER, "")
    base.update(source_channel="pipeline", url="https://example.com/job", fit_score="90")
    base.update(kw)
    return [base[h] for h in HEADER]


def fixture(rows, watch=None, queue=None, pdfs=()):
    d = tempfile.mkdtemp(prefix="dash_test_")
    with open(os.path.join(d, "outcomes.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)
    with open(os.path.join(d, "watchlist.json"), "w", encoding="utf-8") as f:
        json.dump(watch if watch is not None else {"_scoring_config": {}}, f)
    with open(os.path.join(d, "queue.json"), "w", encoding="utf-8") as f:
        json.dump(queue or {}, f)
    os.makedirs(os.path.join(d, "tailored", "apply_now"))
    for rel in pdfs:
        open(os.path.join(d, "tailored", rel), "w").close()
    bd.OUTCOMES = os.path.join(d, "outcomes.csv")
    bd.WATCHLIST = os.path.join(d, "watchlist.json")
    bd.QUEUE = os.path.join(d, "queue.json")
    bd.REPO = d
    bd.TAILORED = os.path.join(d, "tailored")
    bd.APPLY_NOW = os.path.join(d, "tailored", "apply_now")
    return d


def build():
    return bd.build_data(TODAY, datetime(2026, 9, 19, 7, 0))


def test_queue_dates_and_undated():
    fixture([row(company="Acme", stage="surfaced", surfaced_date="2026-09-19"),
             row(company="Bolt", stage="surfaced", surfaced_date="2026-08-05"),
             row(company="Cask", stage="surfaced", surfaced_date="")])
    q = {i["company"]: i for i in build()["queue"]}
    assert len(q) == 3
    assert q["Cask"]["surfaced"] == "", "undated rows stay on the page with no countdown"
    assert bd.summary(build(), TODAY).startswith("3 queue (1 expiring)"), bd.summary(build(), TODAY)


def test_quiet_blank_and_pending_and_epoch():
    fixture([row(company="A", stage="applied", outcome="", applied_date="2026-08-10", surfaced_date="2026-08-09"),
             row(company="B", stage="applied", outcome="pending", applied_date="2026-08-10", surfaced_date="2026-08-09"),
             row(company="C", stage="applied", outcome="interview", applied_date="2026-08-10", surfaced_date="2026-08-09"),
             row(company="Old", stage="applied", outcome="", applied_date="2026-07-01", surfaced_date="2026-07-01"),
             row(company="NoSend", stage="applied", outcome="", applied_date="", surfaced_date="2026-08-20")])
    d = build()
    names = sorted(i["company"] for i in d["quiet"])
    assert names == ["A", "B", "NoSend"], names
    assert d["counts"]["pre_epoch_quiet"] == 1
    nosend = [i for i in d["quiet"] if i["company"] == "NoSend"][0]
    assert nosend["applied"] == "2026-08-20" and nosend["applied_is_exact"] is False


def test_unknown_stage_and_bad_rows():
    d = fixture([row(company="A", stage="interview"), row(company="B", stage="surfaced", surfaced_date="2026-09-01")])
    with open(os.path.join(d, "outcomes.csv"), "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["2026-09-01", "Short", "Title"])
    c = build()["counts"]
    assert c["in_process"] == 1 and c["unknown_stages"] == ["interview"]
    assert c["bad_rows"] == 1


def test_coverage_is_a_gate_and_text_unmet():
    fixture([row(company="A", stage="surfaced", surfaced_date="2026-09-10", jd_coverage_pct="73",
                 unmet_hard_reqs="some prose instead of a number", hard_req_cap_trigger="none", ic_scope="IC"),
             row(company="B", stage="surfaced", surfaced_date="2026-09-10", jd_coverage_pct="100",
                 unmet_hard_reqs="2", hard_req_cap_trigger="5+ years in X", fit_score="112")])
    q = {i["company"]: i for i in build()["queue"]}
    assert q["A"]["coverage_ok"] is False and "coverage" not in q["A"], "no raw coverage number ships"
    assert q["A"]["unmet"] == -1 and q["A"]["unmet_text"].startswith("some prose")
    assert q["A"]["cap_trigger"] == "" and q["A"]["cap_checked"] is True and q["A"]["ic_scope"] == "ic"
    assert q["B"]["cap_trigger"] == "5+ years in X" and q["B"]["tier"] == "priority"


def test_pdf_matching():
    fixture([row(company="Smith & Sons", stage="surfaced", surfaced_date="2026-09-10"),
             row(company="Multi Co", stage="surfaced", surfaced_date="2026-09-10"),
             row(company="Nothing Inc", stage="surfaced", surfaced_date="2026-09-10")],
            pdfs=["apply_now/Aneesh_Khan_SmithSons_AIAdoption.pdf",
                  "apply_now/Aneesh_Khan_SmithSons_AIAdoption_cover.pdf",
                  "Aneesh_Khan_SmithSons_OldRole.pdf",
                  "Aneesh_Khan_MultiCo_TAM.pdf", "Aneesh_Khan_MultiCo_CSM.pdf"])
    q = {i["company"]: i for i in build()["queue"]}
    assert q["Smith & Sons"]["resume"].endswith("apply_now/Aneesh_Khan_SmithSons_AIAdoption.pdf")
    assert q["Smith & Sons"]["cover"].endswith("_cover.pdf") and q["Smith & Sons"]["in_apply_now"]
    assert "2 PDFs match" in q["Multi Co"]["note"] and "resume" not in q["Multi Co"]
    assert q["Nothing Inc"]["note"] == "no PDF matched"


def test_manual_links_and_live_hits():
    watch = {"_scoring_config": {},
             "_blind_spot_companies": {"description": "x", "companies": [
                 {"name": "Has Url", "why": "w", "query": "q", "careers_url": "https://careers.example.com",
                  "last_checked": "2026-09-14", "last_hit": "2026-09-14: Support Ops Manager, Atlanta"},
                 {"name": "Query Only", "why": "w", "query": 'site:example.com "support"',
                  "last_checked": "2026-09-14", "last_hit": "2026-09-14: no US fit-space hit"}]},
             "_unpollable_backlog_companies": {"companies": [{"name": "Monthly", "query": ""}]}}
    fixture([], watch=watch,
            queue={"rejected": [{"name": "r", "manual_review": True},
                                {"name": "s", "manual_review": True, "manual_review_surfaced": True},
                                {"name": "t", "unpollable": True}]})
    d = build()
    m = {i["name"]: i for i in d["manual"]}
    assert m["Has Url"]["link_kind"] == "careers" and m["Has Url"]["hit_is_live"] is True
    assert m["Query Only"]["link_kind"] == "search" and "google.com/search?q=site%3Aexample.com" in m["Query Only"]["link"]
    assert m["Query Only"]["hit_is_live"] is False
    assert m["Monthly"]["group"] == "Backlog" and m["Monthly"]["stale_days"] == 30 and m["Monthly"]["link"] == ""
    assert d["counts"]["manual_review_unsurfaced"] == 1 and d["counts"]["unpollable_unreported"] == 1


def test_hostile_notes_produce_valid_embedded_json():
    fixture([row(company='Evil </script><script>alert(1)</script>', title='Quote " and <!-- comment',
                 stage="surfaced", surfaced_date="2026-09-10")])
    html = bd.render(build())
    blob = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1)
    assert "</script" not in blob
    assert json.loads(blob)["queue"][0]["company"].startswith("Evil </script>")


def test_failure_exits_zero_and_writes_nothing():
    d = fixture([])
    os.remove(bd.OUTCOMES)
    out = os.path.join(d, "out")
    assert bd.main(["--out", out, "--today", "2026-09-19"]) == 0
    assert not os.path.exists(os.path.join(out, bd.OUT_NAME))
    assert bd.main(["--out", out, "--today", "2026-09-19", "--strict"]) == 1


def test_main_writes_atomically_named_file():
    d = fixture([row(company="A", stage="surfaced", surfaced_date="2026-09-10")])
    out = os.path.join(d, "out")
    assert bd.main(["--out", out, "--today", "2026-09-19", "--strict"]) == 0
    assert os.listdir(out) == [bd.OUT_NAME], "no temp file left behind for the Shelf to import"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
