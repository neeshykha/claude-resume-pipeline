#!/usr/bin/env python3
"""Tests for rotate_apply_folder.py's matching and eviction rules. Made-up names only.

    .venv/bin/python pipeline/test_rotate_apply_folder.py
"""
import datetime
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rotate_apply_folder as rot  # noqa: E402

TODAY = datetime.date(2026, 10, 12)
NOTES = "Full tier. tailored/apply_now/Aneesh_Khan_Acme_OpsLead.pdf + _cover.pdf"


def row(**kw):
    base = {"company": "Acme", "title": "Ops Lead", "stage": "surfaced", "notes": NOTES,
            "surfaced_date": "2026-10-10", "applied_date": "", "his_verdict": "", "fit_score": "101"}
    base.update(kw)
    return base


def test_cover_and_ats_variants_map_to_the_resume_the_row_names():
    assert rot.resume_basename("Aneesh_Khan_Acme_OpsLead.pdf") == "Aneesh_Khan_Acme_OpsLead.pdf"
    assert rot.resume_basename("Aneesh_Khan_Acme_OpsLead_cover.pdf") == "Aneesh_Khan_Acme_OpsLead.pdf"
    assert rot.resume_basename("Aneesh_Khan_Acme_OpsLead_ATS.pdf") == "Aneesh_Khan_Acme_OpsLead.pdf"
    rows = [row()]
    for name in ("Aneesh_Khan_Acme_OpsLead.pdf", "Aneesh_Khan_Acme_OpsLead_cover.pdf",
                 "Aneesh_Khan_Acme_OpsLead_ATS.pdf"):
        assert rot.find_row(rows, name) is rows[0], name
    assert rot.find_row(rows, "Aneesh_Khan_Other_Role_ATS.pdf") is None


def test_a_role_whose_name_ends_in_ats_is_only_stripped_once():
    # "..._CoverLetterOps_cover.pdf" style names: one suffix comes off, never two.
    assert rot.resume_basename("Aneesh_Khan_Acme_Lead_ATS_cover.pdf") == "Aneesh_Khan_Acme_Lead_ATS.pdf"


def test_skip_verdict_evicts_without_a_digest_line():
    path = os.path.join(tempfile.mkdtemp(prefix="rot_test_"), "x.pdf")
    open(path, "w").close()
    evict, why = rot.decide(row(his_verdict="skip_fit"), path, TODAY)
    assert evict and why == "his_verdict=skip_fit"
    assert "still surfaced" not in why, "a skip is his decision, so it never becomes an unsent nag"
    assert rot.decide(row(his_verdict="sent_as_is"), path, TODAY) == (False, "surfaced 2d ago")
    assert rot.decide(row(), path, TODAY) == (False, "surfaced 2d ago")
    assert rot.decide(row(surfaced_date="2026-10-01"), path, TODAY)[0] is True
    assert rot.decide(row(stage="applied", his_verdict="skip_fit"), path, TODAY) == (True, "stage=applied")
    assert rot.decide(None, path, TODAY)[0] is False, "an unmatched PDF is still kept"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
