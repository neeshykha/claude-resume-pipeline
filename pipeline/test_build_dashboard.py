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
          "vendor_tool_named_in_jd", "hard_req_cap_trigger", "furthest_stage", "ic_scope",
          "his_verdict"]
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
    bd.JOBS_DIR = os.path.join(d, "jobs")
    os.makedirs(bd.JOBS_DIR)
    return d


def screened_file(day, roles):
    with open(os.path.join(bd.JOBS_DIR, f"screened_{day}.json"), "w", encoding="utf-8") as f:
        json.dump({"run_date": day, "roles": roles}, f)


def test_screened_window_dedupe_and_known_urls():
    fixture([row(company="Tailored", stage="surfaced", surfaced_date="2026-09-18",
                 url="https://example.com/tailored")])
    screened_file("2026-09-19", [
        {"company": "Acme", "title": "Ops Lead", "url": "https://example.com/a", "score": 91},
        {"company": "Tailored", "title": "Now in outcomes", "url": "https://example.com/tailored", "score": 99}])
    screened_file("2026-09-16", [
        {"company": "Acme", "title": "Ops Lead", "url": "https://example.com/a", "score": 88},
        {"company": "Bolt", "title": "Support Mgr", "url": "https://example.com/b", "score": 80}])
    screened_file("2026-09-01", [
        {"company": "Old", "title": "Too old", "url": "https://example.com/old", "score": 95}])
    data = build()
    got = {s["url"]: s for s in data["screened"]}
    assert set(got) == {"https://example.com/a", "https://example.com/b"}, got
    assert got["https://example.com/a"]["score"] == 91          # newest file wins
    assert got["https://example.com/a"]["first"] == "2026-09-16"  # earliest clear kept
    assert data["counts"]["screened_days"] == 2


def test_screened_dismissed_urls_stay_hidden_and_junk_hides_nothing():
    fixture([])
    roles = [{"company": "Acme", "title": "Ops Lead", "url": "https://example.com/a", "score": 91},
             {"company": "Bolt", "title": "Support Mgr", "url": "https://example.com/b", "score": 80},
             {"company": "Cove", "title": "TAM", "url": "https://example.com/c", "score": 79}]
    screened_file("2026-09-19", roles)
    screened_file("2026-09-18", roles)                     # re-listed on a second day
    path = os.path.join(bd.JOBS_DIR, bd.SCREENED_DISMISSED)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"dismissed": [{"url": "https://example.com/a ", "company": "Acme"},
                                 "https://example.com/c", {"company": "no url"}, 7]}, f)
    data = build()
    assert [s["url"] for s in data["screened"]] == ["https://example.com/b"], data["screened"]
    assert data["counts"]["screened_days"] == 2
    for junk in ("not json", '["https://example.com/b"]', '{"dismissed": "https://example.com/b"}'):
        with open(path, "w", encoding="utf-8") as f:
            f.write(junk)
        assert len(build()["screened"]) == 3, junk


def test_screened_absent_is_distinguishable_from_empty():
    fixture([])
    assert build()["counts"]["screened_days"] == 0
    screened_file("2026-09-19", [])
    data = build()
    assert data["screened"] == [] and data["counts"]["screened_days"] == 1


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


def test_ats_variant_is_part_of_the_package_not_a_second_resume():
    fixture([row(company="Smith & Sons", stage="surfaced", surfaced_date="2026-09-10"),
             row(company="Lone Variant", stage="surfaced", surfaced_date="2026-09-10")],
            pdfs=["apply_now/Aneesh_Khan_SmithSons_AIAdoption.pdf",
                  "apply_now/Aneesh_Khan_SmithSons_AIAdoption_ATS.pdf",
                  "apply_now/Aneesh_Khan_SmithSons_AIAdoption_cover.pdf",
                  "apply_now/Aneesh_Khan_LoneVariant_TAM_ATS.pdf"])
    q = {i["company"]: i for i in build()["queue"]}
    s = q["Smith & Sons"]
    assert "note" not in s, "the ATS variant must not read as '2 PDFs match'"
    assert s["resume"].endswith("AIAdoption.pdf") and s["ats"].endswith("AIAdoption_ATS.pdf")
    assert s["cover"].endswith("_cover.pdf")
    assert q["Lone Variant"]["resume"] == "" and q["Lone Variant"]["ats"].endswith("_TAM_ATS.pdf")


def test_notes_naming_the_package_beat_the_company_slug():
    fixture([row(company="Dotted.io", stage="surfaced", surfaced_date="2026-09-10",
                 notes="Full tier. tailored/apply_now/Aneesh_Khan_Dotted_OpsLead.pdf + _cover.pdf"),
             row(company="Two Named", stage="surfaced", surfaced_date="2026-09-10",
                 notes="Aneesh_Khan_TwoNamed_A.pdf, sibling of Aneesh_Khan_TwoNamed_B.pdf")],
            pdfs=["apply_now/Aneesh_Khan_Dotted_OpsLead.pdf", "apply_now/Aneesh_Khan_Dotted_OpsLead_cover.pdf",
                  "apply_now/Aneesh_Khan_Dotted_OpsLead_ATS.pdf", "Aneesh_Khan_Dotted_OpsLead.pdf",
                  "Aneesh_Khan_TwoNamed_A.pdf", "Aneesh_Khan_TwoNamed_B.pdf"])
    q = {i["company"]: i for i in build()["queue"]}
    d = q["Dotted.io"]
    assert d["resume"].endswith("apply_now/Aneesh_Khan_Dotted_OpsLead.pdf"), d
    assert d["cover"].endswith("_cover.pdf") and d["ats"].endswith("_ATS.pdf") and d["in_apply_now"]
    assert "2 PDFs match" in q["Two Named"]["note"], "notes naming two packages settle nothing"


def test_skip_verdict_leaves_the_queue_and_rows_carry_a_mark_key():
    fixture([row(company="Keep", stage="surfaced", surfaced_date="2026-09-18", url="https://Example.com/Jobs/1/"),
             row(company="Sent Verdict", stage="surfaced", surfaced_date="2026-09-18",
                 url="https://example.com/2", his_verdict="sent_as_is"),
             row(company="Skipped", stage="surfaced", surfaced_date="2026-09-18",
                 url="https://example.com/3", his_verdict="skip_fit"),
             row(company="No Url Co", title="Some Role", stage="surfaced", surfaced_date="2026-09-18", url="")])
    d = build()
    q = {i["company"]: i for i in d["queue"]}
    assert set(q) == {"Keep", "Sent Verdict", "No Url Co"}, set(q)
    assert d["counts"]["skipped"] == 1
    assert q["Keep"]["key"] == "https://example.com/jobs/1", "same normalization shelf_inbox.py matches on"
    assert q["No Url Co"]["key"] == "nourlco|somerole"


def test_mark_key_and_inbox_contract_with_shelf_inbox():
    import shelf_inbox
    fixture([row(company="A", stage="surfaced", surfaced_date="2026-09-18")])
    html = bd.render(build())
    assert "IKEY='%s'" % shelf_inbox.INBOX_KEY in html, "page and shelf_inbox.py must share the storage key"
    for reason in shelf_inbox.SKIP_VERDICTS:
        assert reason + ":'" in html, f"skip reason {reason} missing from the page"
    assert "function canMark(q){return /^https?:\\/\\//.test(q.key)&&keyN[q.key]===1}" in html, \
        "rows shelf_inbox.py could never match (no link, or a shared link) must not take marks"
    assert bd.norm_url(" https://X.example/a/ ") == shelf_inbox.norm_url(" https://X.example/a/ ")
    assert 'data-act="bulk"' in html and "bulk:true" in html and 'data-act="unbulk"' in html, \
        "the one-click clear and its undo; shelf_inbox.py reads the `bulk` flag"


def brief_file(day, payload):
    with open(os.path.join(bd.JOBS_DIR, f"brief_{day}.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f)


def test_brief_newest_wins_is_capped_and_survives_junk():
    fixture([row(company="A", stage="surfaced", surfaced_date="2026-09-18", url="https://example.com/a")])
    assert build()["brief"] is None
    brief_file("2026-09-10", {"note": "too old to show"})
    assert build()["brief"] is None, "a brief older than the window is ignored"
    brief_file("2026-09-17", {"note": "older"})
    brief_file("2026-09-18", {
        "note": "x" * 2000, "alerts": ["one", 7, ""],
        "picks": [{"url": "https://Example.com/a/", "read": "why", "commitment": "a promise",
                   "check": ["phrase", None], "changes": ["c1", "c2"]},
                  {"read": "no url, dropped"}, "junk"],
        "sections": [{"title": "Near-misses", "note": "n", "lines": ["plain string",
                      {"text": "with link", "url": "https://example.com/x", "label": "board"}, {"url": "no text"}]},
                     {"lines": ["untitled section, dropped"]}, 5]})
    b = build()["brief"]
    assert b["run_date"] == "2026-09-18" and len(b["note"]) == 900
    assert b["alerts"] == ["one"]
    assert list(b["picks"]) == ["https://example.com/a"], "picks are keyed like queue rows"
    assert b["picks"]["https://example.com/a"]["check"] == ["phrase"]
    assert len(b["sections"]) == 1 and [l["text"] for l in b["sections"][0]["lines"]] == ["plain string", "with link"]
    brief_file("2026-09-19", ["not", "an", "object"])
    assert build()["brief"]["run_date"] == "2026-09-18", "an unreadable newer brief falls back, it doesn't blank the page"
    json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>',
                         bd.render(build()), re.S).group(1))


def test_field_sheet_embeds_only_sections_marked_non_personal():
    d = fixture([row(company="Smith & Sons", stage="surfaced", surfaced_date="2026-09-10"),
                 row(company="No Sheet", stage="surfaced", surfaced_date="2026-09-10")],
                pdfs=["apply_now/Aneesh_Khan_SmithSons_AIAdoption.pdf",
                      "apply_now/Aneesh_Khan_SmithSons_AIAdoption_ATS.pdf",
                      "apply_now/Aneesh_Khan_NoSheet_TAM.pdf"])
    with open(os.path.join(d, "tailored", "Aneesh_Khan_SmithSons_AIAdoption_fields.json"), "w", encoding="utf-8") as f:
        json.dump({"stem": "x", "sections": [
            {"title": "My information", "personal": True, "fields": [{"label": "Phone", "value": "555-0100"}]},
            {"title": "Unflagged", "fields": [{"label": "Street", "value": "1 Private Way"}]},
            {"title": "Work experience 1", "personal": False, "fields": [
                {"label": "Job title", "value": "Ops Lead"}, {"label": "From", "value": "MM/2020", "needs_you": True},
                {"value": "no label, dropped"}]},
            {"title": "Only you", "personal": False, "fields": [
                {"label": "Legally authorized to work in the US? (a profile question)", "value": "", "needs_you": True}]}]}, f)
    q = {i["company"]: i for i in build()["queue"]}
    f = q["Smith & Sons"]["fields"]
    assert [s["title"] for s in f] == ["Work experience 1"], "personal and unflagged sections never reach the page"
    assert [x["label"] for x in f[0]["fields"]] == ["Job title", "From"] and f[0]["fields"][1]["needs_you"] is True
    assert "fields" not in q["No Sheet"]
    html = bd.render(build())
    assert "555-0100" not in html and "1 Private Way" not in html
    assert "a profile question" not in html, "a section with nothing to paste stays in the .md sheet"


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


def leads_file(day, payload):
    with open(os.path.join(bd.JOBS_DIR, f"weekly_leads_{day}.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f)


def lead_row(jid, lst="unreachable", **kw):
    x = {"id": jid, "list": lst, "company": "Brevik", "title": "Head of Support",
         "url": f"https://www.linkedin.com/jobs/view/{jid}/", "tier": "tier1", "loc": "atlanta",
         "seen": 2, "first": "2026-09-15", "note": "no board"}
    x.update(kw)
    return x


def test_weekly_leads_window_answered_and_junk():
    fixture([row(company="A", stage="surfaced", surfaced_date="2026-09-18", url="https://example.com/a")])
    assert build()["leads"] is None
    leads_file("2026-09-05", {"leads": [lead_row("4000001")]})
    assert build()["leads"] is None, "older than LEADS_DAYS is not this week's report"
    leads_file("2026-09-17", {
        "window": {"start": "2026-09-11", "end": "2026-09-17"},
        "flags": ["Remotive was degraded", 7],
        "health": [{"title": "Channels", "lines": ["one", 2]}, {"lines": ["no title"]},
                   {"title": "Pipeline quality", "lines": ["a  b"], "pre": True}],
        "leads": [lead_row("4000001"), lead_row("4000002", lst="never_picked"), lead_row("4000003", lst="no_board"),
                  lead_row("4000001"),                       # duplicate id
                  lead_row("abc"), lead_row("4000004", lst="elsewhere"), "junk",
                  lead_row("4000005", seen=10 ** 6, title="<b>x</b>")]})
    with open(os.path.join(bd.JOBS_DIR, "lead_marks.json"), "w", encoding="utf-8") as f:
        json.dump({"leads": {"4000002": {"action": "pass"},
                             "9000000": {"action": "tailor"}}}, f)  # waiting, from another week
    L = build()["leads"]
    assert [x["id"] for x in L["rows"]] == ["4000001", "4000003", "4000005"], L["rows"]
    assert L["handled"] == 1 and L["waiting"] == 1, L
    assert L["start"] == "2026-09-11" and L["flags"] == ["Remotive was degraded"]
    assert [h["title"] for h in L["health"]] == ["Channels", "Pipeline quality"] and L["health"][1]["pre"]
    assert L["health"][0]["lines"] == ["one"]
    assert L["rows"][2]["seen"] == 1, "an absurd count is reset, not trusted"
    with open(os.path.join(bd.JOBS_DIR, "lead_marks.json"), "w", encoding="utf-8") as f:
        f.write("{broken")
    assert len(build()["leads"]["rows"]) == 4, "a malformed lead_marks.json hides nothing"
    html = bd.render(build())
    assert "<b>x</b>" not in html, "embedded data is escaped for the script block"


def test_leads_key_contract_with_shelf_inbox_and_lead_marks():
    import lead_marks
    import shelf_inbox
    fixture([row(company="A", stage="surfaced", surfaced_date="2026-09-18")])
    leads_file("2026-09-18", {"leads": [lead_row("4000001")]})
    html = bd.render(build())
    assert "LKEY='%s'" % shelf_inbox.LEADS_KEY in html, "page and shelf_inbox.py must share the leads key"
    assert "l:x.list,tier:x.tier,loc:x.loc" in html and "c:x.company,t:x.title" in html, \
        "lead_marks.record reads c, t, u, l, tier, loc"
    assert set(bd.LEAD_LISTS) == set(lead_marks.LISTS)
    assert bd.LEAD_ID_RE.pattern == lead_marks.JOB_ID_RE.pattern
    assert 'data-lact="tailor"' in html and 'data-lact="pass"' in html and 'data-lact="undo"' in html
    with open(os.path.join(bd.JOBS_DIR, "lead_marks.json"), "w", encoding="utf-8") as f:
        json.dump({"leads": {"4000009": {"action": "pass"}}}, f)
    data = build()
    assert data["lead_answered"] == ["4000009"], "the page prunes a lead mark only once a run recorded it"
    assert "done[k]||n==null||n>D.lead_mark_days" in bd.render(data)


def interviews_file(rounds):
    with open(os.path.join(bd.JOBS_DIR, bd.INTERVIEWS), "w", encoding="utf-8") as f:
        json.dump({"rounds": rounds}, f)


def test_progress_counts_sends_from_the_epoch_and_closed_rows_only_with_evidence():
    fixture([row(company="A", stage="applied", applied_date="2026-09-01", surfaced_date="2026-08-30"),
             row(company="B", stage="rejected", applied_date="2026-09-01", surfaced_date="2026-09-01"),
             row(company="C", stage="surfaced", applied_date="2026-09-02", surfaced_date="2026-09-02"),
             row(company="D", stage="applied", applied_date="", surfaced_date="2026-09-03"),
             row(company="Old", stage="applied", applied_date="2026-07-01", surfaced_date="2026-07-01"),
             row(company="Kept", stage="closed", applied_date="2026-09-04", surfaced_date="2026-09-04", his_verdict="sent_as_is"),
             row(company="Never", stage="closed", applied_date="2026-09-04", surfaced_date="2026-09-04"),
             row(company="ByUrl", stage="closed", applied_date="2026-09-05", surfaced_date="2026-09-05",
                 url="https://example.com/byurl"),
             row(company="ByName", stage="closed", applied_date="2026-09-05", surfaced_date="2026-09-05", title="Ops Lead"),
             row(company="WrongTitle", stage="closed", applied_date="2026-09-05", surfaced_date="2026-09-05", title="Ops Lead")])
    with open(os.path.join(bd.JOBS_DIR, "confirmations_2026-09-06.json"), "w", encoding="utf-8") as f:
        json.dump({"confirmations": [{"url": "https://example.com/byurl/", "company": "ByUrl"},
                                     {"company": "ByName"}, {"company": "WrongTitle", "title": "Engineer"}]}, f)
    with open(os.path.join(bd.JOBS_DIR, "confirmations_junk.json"), "w", encoding="utf-8") as f:
        f.write("{not json")
    p = build()["progress"]
    assert "error" not in p, p
    sent = sorted(c for v in p["days"].values() for c in v)
    assert sent == ["A", "B", "ByName", "ByUrl", "D", "Kept"], sent
    assert p["days"]["2026-09-03"] == ["D"] and p["inexact"] == 1  # dated by surfacing, and says so
    assert p["pre_epoch"] == 1 and p["funnel"]["sent"] == 6


def test_progress_rounds_attach_to_the_right_send_and_fill_the_funnel():
    fixture([row(company="Acme", stage="rejected", applied_date="2026-08-01", surfaced_date="2026-08-01",
                 url="https://example.com/acme-old"),
             row(company="Acme", stage="applied", applied_date="2026-09-10", surfaced_date="2026-09-10",
                 url="https://example.com/acme-new"),
             row(company="Bolt", stage="applied", applied_date="2026-08-02", surfaced_date="2026-08-02"),
             row(company="Cove", stage="applied", applied_date="2026-09-15", surfaced_date="2026-09-15"),
             row(company="Dune", stage="interview", applied_date="2026-08-20", surfaced_date="2026-08-20"),
             row(company="Echo", stage="applied", applied_date="2026-08-21", surfaced_date="2026-08-21")])
    interviews_file([
        # No URL: the company's latest send on or before the round, so the OLD Acme posting.
        {"company": "acme", "date": "2026-08-15", "kind": "screen"},
        {"company": "Acme", "date": "2026-08-25", "kind": "interview"},
        {"company": "Echo", "date": "2026-08-30", "kind": "assessment"},
        {"company": "Elsewhere", "date": "2026-09-01", "kind": "screen", "round": 1},
        {"company": "Bad", "date": "someday", "kind": "screen"},
        {"company": "Bad", "date": "2026-09-01", "kind": "coffee"}])
    p = build()["progress"]
    assert [(r["company"], r["round"]) for r in p["rounds"]] == [
        ("acme", 1), ("Acme", 2), ("Echo", None), ("Elsewhere", 1)], p["rounds"]
    assert "2 unreadable entries" in p["rounds_note"]
    f = p["funnel"]
    # Acme-old: two rounds, then rejected, so it counts as interviewed and reached a later round.
    # Dune: the tracker says interview with no logged round. Bolt: quiet 48 days. Cove: 4 days.
    assert (f["sent"], f["screen"], f["later"], f["interviewed"]) == (6, 2, 1, 2), f
    assert (f["ghosted"], f["waiting"], f["assessment"], f["rejected"]) == (1, 2, 1, 0), f
    wk = {w["week"]: w for w in p["weeks"]}
    assert wk["2026-07-27"]["screen"] == 1 and wk["2026-09-07"]["waiting"] == 1


def test_progress_without_a_log_and_a_failure_that_spares_the_page():
    fixture([row(company="A", stage="applied", applied_date="2026-09-01", surfaced_date="2026-09-01")])
    p = build()["progress"]
    assert p["rounds"] == [] and "No interview log" in p["rounds_note"]
    with open(os.path.join(bd.JOBS_DIR, bd.INTERVIEWS), "w", encoding="utf-8") as f:
        f.write("[1, 2")
    assert "could not be read" in build()["progress"]["rounds_note"]
    real = bd.read_progress
    bd.read_progress = lambda today: 1 / 0
    try:
        d = build()
    finally:
        bd.read_progress = real
    assert d["progress"]["error"].startswith("ZeroDivisionError") and d["quiet"], "the rest of the page still builds"


def test_page_script_parses_as_javascript():
    # The other tests never execute the page. On 2026-10-12 a one-character slip in the
    # embedded script left every list blank and all of them still passed.
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        print("    (skipped: node is not installed, so the page script was not syntax-checked)")
        return
    d = fixture([row(company="A", stage="surfaced", surfaced_date="2026-09-18", url="https://example.com/a")])
    html = bd.render(build())
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert len(scripts) == 1, "expected exactly one executable script block"
    path = os.path.join(d, "page_script.js")
    with open(path, "w", encoding="utf-8") as f:
        f.write(scripts[0])
    r = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert r.returncode == 0, "the page's script does not parse:\n" + r.stderr[:600]


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
