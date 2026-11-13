#!/usr/bin/env python3
"""Tests for the furthest_stage handling in mark_outcome.py.

    .venv/bin/python pipeline/test_mark_outcome_furthest.py

Added 2026-11-12. CLAUDE.md ("Tracking files") says furthest_stage is set
alongside every mark_outcome.py run that records an interview, assessment, or
offer, and the script had no code for it. So the column was filled by hand or
not at all, and a role that reached an interview and was then rejected read
only `rejected`: the loss DECISIONS.md D7 added the column to stop.

What is pinned here:
  - an outcome of assessment, interview, onsite, or offer moves the row's
    furthest_stage to that stage;
  - an item can name the stage itself, so a rejection that followed an
    interview is recorded as outcome rejected, furthest_stage interview;
  - the column only moves right, is never cleared, and a rejection, closure,
    or pending on its own never sets it;
  - a value outside repair_outcomes.FURTHEST_STAGES is refused, and nothing is
    written for that item;
  - everything else about the script is as it was: a row the run did not
    match is byte-identical, the header and the 17 columns do not change, and
    a run with no stage in it prints what it always printed.

Every company below is made up. Each case builds its own tracker in a temp
dir and points mark_outcome.OUTCOMES at it for the length of one call; the
real outcomes.csv is never opened.
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
import mark_outcome as M  # noqa: E402
import repair_outcomes as R  # noqa: E402

HEADER = list(R.CANONICAL)
FS = HEADER.index("furthest_stage")

ACME = "https://example.com/jobs/acme-tam"
BOREALIS = "https://example.com/jobs/borealis-som"
BYSTANDER = "https://example.com/jobs/zzq-bystander"
# The cells csv.writer has to quote: commas, quotes, a line break inside a
# field, padding, and a non-ASCII character. A row the run does not match must
# come back with every one of them as it was.
AWKWARD_NOTES = ('Full tier, resume + cover. He said "send it", then waited;\n'
                 "second line of the note, with an accent (café) and a trailing space ")

TEMP_DIRS = []


def row(**kw):
    base = dict.fromkeys(HEADER, "")
    base.update(applied_date="2026-10-01", surfaced_date="2026-10-01", stage="applied",
                fit_score="90", jd_coverage_pct="93", source_channel="pipeline")
    base.update(kw)
    return [base[h] for h in HEADER]


def acme(**kw):
    return row(**{**dict(company="Acme Robotics", title="Technical Account Manager", url=ACME), **kw})


def borealis(**kw):
    return row(**{**dict(company="Borealis Labs", title="Support Operations Manager", url=BOREALIS), **kw})


def bystander(**kw):
    return row(**{**dict(company="Zzq Bystander Co", title='Manager, "Tier 2" Support',
                         url=BYSTANDER, notes=AWKWARD_NOTES, furthest_stage="interview",
                         stage="rejected", outcome="rejected", his_verdict="sent_as_is"), **kw})


class Tracker:
    """One temp outcomes.csv, and mark_outcome.main() run against it."""

    def __init__(self, rows, header=HEADER):
        self.dir = tempfile.mkdtemp(prefix="mark_outcome_furthest_test_")
        TEMP_DIRS.append(self.dir)
        self.path = os.path.join(self.dir, "outcomes.csv")
        self.runs = 0
        with open(self.path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)

    def mark(self, *items):
        """Write the items as one outcomes file and run the script on it."""
        self.runs += 1
        path = os.path.join(self.dir, f"outcomes_{self.runs}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"outcomes": list(items)}, f)
        return self.rerun(path)

    def rerun(self, path):
        saved = (M.OUTCOMES, sys.argv)
        M.OUTCOMES, sys.argv = self.path, ["mark_outcome.py", path]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = M.main()
        finally:
            M.OUTCOMES, sys.argv = saved
        return rc, buf.getvalue()

    def raw(self):
        with open(self.path, "rb") as f:
            return f.read()

    def records(self):
        """The file's records as bytes, header first. csv.writer ends a record
        with CRLF and the fixture's one in-field line break is a bare LF."""
        return self.raw().split(b"\r\n")

    def rows(self):
        with open(self.path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def cells(self):
        with open(self.path, newline="", encoding="utf-8") as f:
            return list(csv.reader(f))

    def got(self, company):
        """(stage, outcome, furthest_stage) of the one row for a company."""
        hits = [r for r in self.rows() if r["company"] == company]
        if len(hits) != 1:
            return f"{len(hits)} rows for {company}"
        return hits[0]["stage"], hits[0]["outcome"], hits[0]["furthest_stage"]


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


@case
def an_interview_outcome_sets_it():
    """The gap this file exists for: the interview is recorded and the column follows."""
    t = Tracker([acme(), bystander()])
    rc, out = t.mark({"company": "Acme Robotics", "url": ACME, "outcome": "interview",
                      "outcome_date": "2026-10-20", "notes": "R1 recruiter screen"})
    ok = (rc == 0 and t.got("Acme Robotics") == ("interview", "interview", "interview")
          and "furthest_stage moved right on 1 rows" in out
          and "Acme Robotics / Technical Account Manager: (not recorded) -> interview" in out)
    return ok, (rc, t.got("Acme Robotics"), out)


@case
def a_later_rejection_keeps_it():
    """Outcome and stage go to rejected; the interview stays on the row."""
    t = Tracker([acme()])
    t.mark({"company": "Acme Robotics", "outcome": "interview"})
    rc, out = t.mark({"company": "Acme Robotics", "outcome": "rejected",
                      "outcome_date": "2026-10-29", "notes": "form rejection"})
    ok = (rc == 0 and t.got("Acme Robotics") == ("rejected", "rejected", "interview")
          and "furthest_stage" not in out)
    return ok, (rc, t.got("Acme Robotics"), out)


@case
def assessment_then_interview_moves_right():
    t = Tracker([acme()])
    t.mark({"url": ACME, "outcome": "assessment"})
    first = t.got("Acme Robotics")
    rc, out = t.mark({"url": ACME, "outcome": "interview"})
    second = t.got("Acme Robotics")
    ok = (first[2] == "assessment" and second[2] == "interview"
          and "Acme Robotics / Technical Account Manager: assessment -> interview" in out)
    return ok, (first, second, out)


@case
def interview_then_assessment_does_not_move_left():
    """The outcome column takes the later value, as it always has; the furthest point does not."""
    t = Tracker([acme()])
    t.mark({"url": ACME, "outcome": "interview"})
    rc, out = t.mark({"url": ACME, "outcome": "assessment"})
    stage, outcome, furthest = t.got("Acme Robotics")
    ok = rc == 0 and (outcome, furthest) == ("assessment", "interview") and "furthest_stage" not in out
    return ok, (rc, (stage, outcome, furthest), out)


@case
def each_stage_outcome_sets_its_own_stage_and_only_those_do():
    """assessment, interview, onsite, offer: read off the shared list, not retyped here."""
    stages = R.FURTHEST_STAGES[R.FURTHEST_STAGES.index("applied") + 1:]
    got = {}
    for o in stages + ["rejected", "closed", "pending", "applied", ""]:
        t = Tracker([acme()])
        t.mark({"url": ACME, "outcome": o})
        got[o] = t.got("Acme Robotics")[2]
    want = {o: o for o in stages}
    want.update({"rejected": "", "closed": "", "pending": "", "applied": "", "": ""})
    return got == want and len(stages) == 4, got


@case
def a_rejection_or_closure_alone_never_sets_it():
    """Empty means not recorded. A rejection that names no stage says nothing about one."""
    t = Tracker([acme(), borealis(), row(company="Cobalt Works", title="Escalation Manager")])
    rc, out = t.mark({"company": "Acme Robotics", "outcome": "rejected", "stage": "rejected"},
                     {"company": "Borealis Labs", "outcome": "closed", "notes": "role filled"},
                     {"company": "Cobalt Works", "outcome": "pending"})
    got = [t.got(c) for c in ("Acme Robotics", "Borealis Labs", "Cobalt Works")]
    ok = (rc == 0 and got == [("rejected", "rejected", ""), ("closed", "closed", ""),
                               ("applied", "pending", "")]
          and "furthest_stage" not in out)
    return ok, (rc, got, out)


@case
def an_explicit_furthest_stage_on_a_rejection_is_honored():
    """The rejection that followed an interview the tracker never saw."""
    t = Tracker([acme(), bystander()])
    rc, out = t.mark({"company": "Acme Robotics", "title": "Technical Account Manager",
                      "outcome": "rejected", "outcome_date": "2026-10-29",
                      "furthest_stage": "interview",
                      "notes": "rejected after the recruiter screen"})
    notes = t.rows()[0]["notes"]
    ok = (rc == 0 and t.got("Acme Robotics") == ("rejected", "rejected", "interview")
          and notes == "outcome 2026-10-29; rejected after the recruiter screen"
          and "(not recorded) -> interview" in out)
    return ok, (rc, t.got("Acme Robotics"), notes, out)


@case
def an_explicit_value_is_read_without_its_case_or_padding():
    t = Tracker([acme()])
    rc, _ = t.mark({"url": ACME, "outcome": "rejected", "furthest_stage": " Onsite "})
    return rc == 0 and t.got("Acme Robotics")[2] == "onsite", (rc, t.got("Acme Robotics"))


@case
def an_explicit_value_only_moves_right_and_never_clears():
    """Lower, equal, empty, and null all leave a row at onsite where it is."""
    got = {}
    for label, item in (("lower", {"furthest_stage": "interview"}),
                        ("equal", {"furthest_stage": "onsite"}),
                        ("empty", {"furthest_stage": ""}),
                        ("null", {"furthest_stage": None}),
                        ("absent", {}),
                        ("lower outcome", {"outcome": "assessment"})):
        t = Tracker([acme(furthest_stage="onsite", stage="onsite", outcome="onsite")])
        rc, out = t.mark({"url": ACME, "outcome": "rejected", **item})
        got[label] = (rc, t.got("Acme Robotics")[2], "furthest_stage" in out)
    return all(v == (0, "onsite", False) for v in got.values()), got


@case
def the_further_of_the_outcome_and_the_explicit_value_wins():
    t = Tracker([acme(), borealis()])
    rc, out = t.mark({"url": ACME, "outcome": "interview", "furthest_stage": "assessment"},
                     {"url": BOREALIS, "outcome": "assessment", "furthest_stage": "onsite"})
    got = (t.got("Acme Robotics")[2], t.got("Borealis Labs")[2])
    return rc == 0 and got == ("interview", "onsite"), (rc, got, out)


@case
def applied_is_a_stage_an_item_can_name_but_not_one_it_can_fall_back_to():
    """`applied` is in the vocabulary, so naming it fills an empty cell and no more."""
    t = Tracker([acme(), borealis(furthest_stage="interview")])
    rc, _ = t.mark({"url": ACME, "outcome": "rejected", "furthest_stage": "applied"},
                   {"url": BOREALIS, "outcome": "rejected", "furthest_stage": "applied"})
    got = (t.got("Acme Robotics")[2], t.got("Borealis Labs")[2])
    return rc == 0 and got == ("applied", "interview"), (rc, got)


@case
def an_unknown_value_is_refused_and_nothing_is_written_for_that_item():
    """`screen` is a round kind in interviews.json, not a furthest_stage. The item
    beside it in the same file is still recorded, and the script exits 1."""
    t = Tracker([acme(), borealis(), bystander()])
    before = t.records()
    rc, out = t.mark({"company": "Acme Robotics", "url": ACME, "outcome": "rejected",
                      "outcome_date": "2026-10-29", "notes": "must not land",
                      "source_channel": "referral", "furthest_stage": "screen"},
                     {"company": "Borealis Labs", "outcome": "interview"})
    after = t.records()
    ok = (rc == 1
          and after[1] == before[1] and after[3:] == before[3:]
          and t.got("Acme Robotics") == ("applied", "", "")
          and t.got("Borealis Labs") == ("interview", "interview", "interview")
          and "REFUSED, nothing written for these (1):" in out
          and "Acme Robotics / (no title given): furthest_stage 'screen' is not one of: "
              "applied, assessment, interview, onsite, offer" in out
          and "updated 1 existing rows" in out)
    return ok, (rc, t.got("Acme Robotics"), t.got("Borealis Labs"), out)


@case
def a_file_of_refused_items_leaves_the_tracker_and_its_backup_alone():
    """Nothing to write means no write: same bytes, no .bak, and no appended row
    even when the item asks for one."""
    t = Tracker([acme(), bystander()])
    before = t.raw()
    rc, out = t.mark({"url": ACME, "outcome": "interview", "furthest_stage": "phone screen"},
                     {"url": ACME, "outcome": "rejected", "furthest_stage": 3},
                     {"url": ACME, "outcome": "rejected", "furthest_stage": ["interview"]},
                     {"company": "Novel Co", "title": "Support Lead", "outcome": "rejected",
                      "furthest_stage": "final", "append_if_missing": True})
    ok = (rc == 1 and t.raw() == before and not os.path.exists(t.path + ".bak")
          and "REFUSED, nothing written for these (4):" in out
          and "updated 0 existing rows" in out and "appended 0 new rows" in out)
    return ok, (rc, t.raw() == before, out)


@case
def a_row_untouched_by_the_run_is_byte_identical():
    """Rows the run did not match come back byte for byte, awkward cells and all;
    the matched row differs in the cells the item named and nowhere else."""
    rows = [bystander(), acme(notes="Full tier. tailored/Jane_Doe_Acme_TAM.pdf + _cover.pdf"),
            borealis(furthest_stage="assessment", notes="plain"),
            bystander(company="Zzq Second Bystander", url=BYSTANDER + "-2", furthest_stage="")]
    t = Tracker(rows)
    before, cells_before = t.records(), t.cells()
    rc, out = t.mark({"url": ACME, "outcome": "interview", "notes": "R1 recruiter screen"})
    after, cells_after = t.records(), t.cells()
    changed = {HEADER[i] for i, (a, b) in enumerate(zip(cells_before[2], cells_after[2])) if a != b}
    ok = (rc == 0 and len(after) == len(before) == 6        # header, 4 rows, the trailing CRLF
          and [i for i in range(len(before)) if after[i] != before[i]] == [2]
          and changed == {"stage", "outcome", "notes", "furthest_stage"}
          and cells_after[1][HEADER.index("notes")] == AWKWARD_NOTES
          and cells_after[4][FS] == "" and cells_after[3][FS] == "assessment")
    return ok, (rc, sorted(changed), [i for i in range(len(before)) if after[i] != before[i]])


@case
def the_header_and_column_count_are_unchanged():
    """Seventeen columns in the canonical order, before and after an update and an append."""
    t = Tracker([acme(), bystander()])
    header_before = t.records()[0]
    rc, _ = t.mark({"url": ACME, "outcome": "interview"},
                   {"company": "Novel Co", "title": "Support Lead", "outcome": "rejected",
                    "furthest_stage": "interview", "append_if_missing": True})
    cells = t.cells()
    ok = (rc == 0 and t.records()[0] == header_before
          and header_before == ",".join(R.CANONICAL).encode()
          and cells[0] == R.CANONICAL and len(cells[0]) == 17 and FS == 14
          and len(cells) == 4 and all(len(r) == 17 for r in cells))
    return ok, (rc, [len(r) for r in cells], cells[0])


@case
def an_appended_row_carries_it():
    """append_if_missing rows get the same treatment as matched ones."""
    t = Tracker([acme()])
    rc, out = t.mark({"company": "Novel Co", "title": "Support Lead", "outcome": "rejected",
                      "furthest_stage": "interview", "append_if_missing": True},
                     {"company": "Other Novel Co", "title": "TAM", "outcome": "interview",
                      "append_if_missing": True},
                     {"company": "Third Novel Co", "title": "CSM", "outcome": "rejected",
                      "append_if_missing": True})
    got = [t.got(c) for c in ("Novel Co", "Other Novel Co", "Third Novel Co")]
    ok = (rc == 0 and got == [("rejected", "rejected", "interview"),
                              ("interview", "interview", "interview"),
                              ("rejected", "rejected", "")]
          and "appended 3 new rows" in out and "furthest_stage moved right on 2 rows" in out)
    return ok, (rc, got, out)


@case
def running_the_same_file_twice_changes_nothing_the_second_time():
    t = Tracker([acme(), bystander()])
    t.mark({"url": ACME, "outcome": "interview", "outcome_date": "2026-10-20", "notes": "R1"})
    once = t.raw()
    rc, out = t.rerun(os.path.join(t.dir, "outcomes_1.json"))
    return rc == 0 and t.raw() == once and "furthest_stage" not in out, (rc, out)


@case
def a_run_with_no_stage_in_it_prints_what_it_always_printed():
    """The whole of stdout, so a new line cannot slip into the ordinary case."""
    t = Tracker([acme(), borealis(), borealis(url=BOREALIS + "-2")])
    rc, out = t.mark({"company": "Acme Robotics", "outcome": "rejected"},
                     {"company": "Borealis Labs", "outcome": "rejected"},
                     {"company": "Nowhere Co", "title": "Lead", "outcome": "closed"})
    want = ("updated 1 existing rows\n"
            "  Acme Robotics / Technical Account Manager -> rejected\n"
            "appended 0 new rows\n"
            "AMBIGUOUS, skipped (1):\n"
            "  Borealis Labs / (no title given) matched 2 rows\n"
            "NO MATCH and append_if_missing not set (1):\n"
            "  Nowhere Co / Lead\n")
    return rc == 0 and out == want, (rc, out)


@case
def an_ambiguous_or_unmatched_item_moves_nothing():
    """A stage is written to the one row an item matched, or to no row."""
    t = Tracker([borealis(), borealis(url=BOREALIS + "-2")])
    before = t.raw()
    rc, out = t.mark({"company": "Borealis Labs", "outcome": "interview"},
                     {"company": "Nowhere Co", "outcome": "offer"})
    return rc == 0 and t.raw() == before and "furthest_stage" not in out, (rc, out)


@case
def a_tracker_with_no_furthest_stage_column_still_records_the_outcome():
    """A file on the 14-column schema worked before this change and still does;
    the stage is reported as not recorded, and no column is invented."""
    old = list(R.LEGACY_V3)
    t = Tracker([acme()[:len(old)]], header=old)
    rc, out = t.mark({"url": ACME, "outcome": "interview"})
    cells = t.cells()
    ok = (rc == 0 and cells[0] == old and len(cells[1]) == len(old) == 14
          and (cells[1][old.index("stage")], cells[1][old.index("outcome")]) == ("interview", "interview")
          and "FURTHEST_STAGE NOT RECORDED (1):" in out and "wanted interview" in out
          and "repair_outcomes.py --apply" in out)
    return ok, (rc, cells[0], out)


@case
def a_cell_holding_a_value_outside_the_vocabulary_is_left_alone():
    """It cannot be ranked, so nothing proves the new stage is a move right."""
    t = Tracker([acme(furthest_stage="screen")])
    rc, out = t.mark({"url": ACME, "outcome": "interview"})
    ok = (rc == 0 and t.got("Acme Robotics") == ("interview", "interview", "screen")
          and "FURTHEST_STAGE NOT RECORDED (1):" in out and "'screen'" in out)
    return ok, (rc, t.got("Acme Robotics"), out)


@case
def the_stage_list_is_the_one_in_repair_outcomes():
    """One list, imported. The rank and the outcome stages are derived from it."""
    ok = (M.FURTHEST_STAGES is R.FURTHEST_STAGES
          and list(M.STAGE_RANK) == R.FURTHEST_STAGES
          and [M.STAGE_RANK[s] for s in R.FURTHEST_STAGES] == list(range(len(R.FURTHEST_STAGES)))
          and M.OUTCOME_STAGES == [s for s in R.FURTHEST_STAGES if s not in ("", "applied")])
    return ok, (M.OUTCOME_STAGES, M.STAGE_RANK)


def main():
    passed = 0
    try:
        for fn in CASES:
            try:
                ok, detail = fn()
            except Exception as e:      # a case that raises is a failed case, not a dead run
                ok, detail = False, f"raised {type(e).__name__}: {e}"
            print(f"  [{'ok ' if ok else 'FAIL'}] {fn.__name__}" + (f"   {detail}" if not ok else ""))
            passed += bool(ok)
    finally:
        for d in TEMP_DIRS:
            shutil.rmtree(d, ignore_errors=True)
    print(f"  {passed}/{len(CASES)} passed")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
