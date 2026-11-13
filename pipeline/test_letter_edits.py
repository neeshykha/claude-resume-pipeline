#!/usr/bin/env python3
"""Tests for letter_edits.py. Every letter, company, and person here is made up, the fixtures
live in a temp dir, and the renderer is a stand-in: nothing reads the real tracker, the real
Shelf, or a real letter, and nothing needs reportlab.

    .venv/bin/python pipeline/test_letter_edits.py
"""
import contextlib
import csv
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_dashboard as bd  # noqa: E402
import check_voice  # noqa: E402
import letter_edits as le  # noqa: E402
import shelf_inbox as si  # noqa: E402

HEADER = ["applied_date", "company", "title", "url", "fit_score", "jd_coverage_pct", "stage",
          "outcome", "notes", "source_channel", "surfaced_date", "unmet_hard_reqs",
          "vendor_tool_named_in_jd", "hard_req_cap_trigger", "furthest_stage", "ic_scope",
          "his_verdict"]
TODAY = "2026-11-12"
STAMP = "20261112T070000"   # a pinned --today pins the clock at 7:00, and a version folder is named for it
URL = "https://example.com/jobs/1"
STEM = bd.PDF_PREFIX + "Acme_OpsLead"
HEAD = "November 9, 2026\n\nHiring Team\nAcme"
TAIL = "Best,\nJane Doe"
PARAS = [
    "A customer of ours once waited nine days for a replacement part, and nobody had told her why. "
    "I called her, found the order stuck in a queue that no one owned, and stayed on it until the part "
    "shipped. She sent a note to my manager afterward, which I still have.",
    "That kind of follow-through is why the work suits me. I'm applying for the Operations Lead role at "
    "Acme because the job is the warehouse floor and the people on it, and that's where I do my best "
    "work. I'd like the job, and I'd like to earn it the slow way.",
    "At my last job I rebuilt the intake form, cut the handoffs from five to two, and wrote the guide "
    "the team still uses. The numbers moved, and more to the point the questions stopped coming. "
    "I'd bring that same patience to Acme's floor.",
    "I've never run a warehouse system. During my first month I'd spend each morning with the floor "
    "leads, learning the scanner flow from them. Until that day I'll keep reading the vendor's "
    "public manual, one chapter a night, so the vocabulary isn't new when I arrive.",
]


def row(**kw):
    base = dict.fromkeys(HEADER, "")
    base.update(source_channel="pipeline", fit_score="90", stage="surfaced", surfaced_date="2026-11-09",
                company="Acme", title="Operations Lead", url=URL,
                notes=f"Full tier. tailored/apply_now/{STEM}.pdf + _cover.pdf")
    base.update(kw)
    return [base[h] for h in HEADER]


def write_letter(tailored, stem=STEM, paras=PARAS, md_paras=None, extra=None, pdf="apply_now"):
    """A package's letter files: .md, JSON, and a stand-in PDF in apply_now/, tailored/, both, or neither."""
    md = "\n\n".join([HEAD] + list(md_paras or paras) + [TAIL]) + "\n"
    with open(os.path.join(tailored, stem + "_cover.md"), "w", encoding="utf-8") as f:
        f.write(md)
    data = {"date": "November 9, 2026", "recipient": "Hiring Team<br/>Acme", "paragraphs": list(paras)}
    data.update(extra or {})
    with open(os.path.join(tailored, stem + "_cover_data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    for where in ("apply_now", "tailored"):
        if pdf in (where, "both"):
            folder = os.path.join(tailored, "apply_now") if where == "apply_now" else tailored
            with open(os.path.join(folder, stem + "_cover.pdf"), "w", encoding="utf-8") as f:
                f.write(f"OLD PDF in {where}")


def fixture(rows=None, edits=None, marks=None, letter=True, **letter_kw):
    """Temp tracker, temp tailored/, and an inbox file shaped like the Shelf's storage."""
    d = tempfile.mkdtemp(prefix="letter_test_")
    le.OUTCOMES = si.OUTCOMES = check_voice.OUTCOMES = os.path.join(d, "outcomes.csv")
    le.JOBS_DIR = si.JOBS_DIR = os.path.join(d, "jobs")
    le.TAILORED = os.path.join(d, "tailored")
    si.SEEN_JOBS = os.path.join(si.JOBS_DIR, "seen_jobs.json")
    os.makedirs(os.path.join(le.TAILORED, "apply_now"))
    os.makedirs(le.JOBS_DIR)
    with open(le.OUTCOMES, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows if rows is not None else [row()])
    if letter:
        write_letter(le.TAILORED, **letter_kw)
    inbox = os.path.join(d, "storage.json")
    set_inbox(inbox, edits or {}, marks or {})
    return d, inbox


def set_inbox(inbox, edits, marks=None):
    with open(inbox, "w", encoding="utf-8") as f:
        json.dump({"jobdash.ticks.v1": "{}", si.INBOX_KEY: json.dumps(marks or {}),
                   le.LETTERS_KEY: json.dumps(edits)}, f)


def sha_on_disk(stem=STEM):
    letter, why = bd.read_letter(le.TAILORED, stem)
    assert letter, why
    return letter["sha"]


def edit(paras, base=None, saved="2026-11-12T23:10:00.000Z"):
    return {"text": "\n\n".join(paras), "base_sha": sha_on_disk() if base is None else base, "saved_at": saved}


def changed(i=2, new="I'd bring that same patience to the floor at Acme, and to the people on it."):
    """PARAS with the last sentence of paragraph i swapped for `new`."""
    paras = list(PARAS)
    cut = bd.sentence_spans(paras[i])[-1][0]
    paras[i] = paras[i][:cut] + new
    return paras


RENDERED = []


def fake_render(json_path, pdf_path):
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    RENDERED.append(pdf_path)
    with open(pdf_path, "w", encoding="utf-8") as f:
        f.write("NEW PDF " + bd.letter_sha([bd.letter_plain(p) for p in data["paragraphs"]]))


def run(inbox, *flags, render=fake_render):
    real = le.render_cover
    le.render_cover = render
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = le.main(["--inbox", inbox, "--today", TODAY] + list(flags))
    finally:
        le.render_cover = real
    return rc, buf.getvalue()


def tree(root):
    """{relative path: bytes} for every file under root."""
    out = {}
    for folder, _, names in os.walk(root):
        for n in names:
            p = os.path.join(folder, n)
            with open(p, "rb") as f:
                out[os.path.relpath(p, root)] = f.read()
    return out


def log_lines():
    path = os.path.join(le.JOBS_DIR, le.LOG_NAME)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def results():
    with open(os.path.join(le.JOBS_DIR, le.RESULTS_NAME), encoding="utf-8") as f:
        return json.load(f)["rows"]


def refused(rows=None, edits=None, marks=None, expect="", **kw):
    """Apply against a fixture that must refuse: no letter file may change, and the reason is logged."""
    d, inbox = fixture(rows=rows, marks=marks, **kw)
    if edits is None:
        edits = {URL: edit(changed())}
    set_inbox(inbox, edits, marks)
    before = tree(le.TAILORED)
    rc, out = run(inbox, "--apply")
    assert rc == 0 and "applied 0, refused 1" in out, out
    assert expect in out, out
    assert tree(le.TAILORED) == before, "a refused edit changes no letter file and leaves no version folder"
    last = log_lines()[-1]
    assert last["status"] == "refused" and expect in last["reason"], last
    assert "text" in last, "the refused text is kept in the log, so his words outlive the page"
    assert results()[URL]["last"]["status"] == "refused"
    return out


def test_an_applied_edit_gives_matching_files_keeps_the_old_version_and_logs():
    d, inbox = fixture(pdf="apply_now")
    old = tree(le.TAILORED)
    new = changed()
    set_inbox(inbox, {URL: edit(new)})
    rc, out = run(inbox, "--apply")
    assert rc == 0 and "letter_edits: applied 1, refused 0" in out, out
    assert "applied: Acme: Operations Lead" in out and "check_voice.py, for information only" in out, out

    letter, why = bd.read_letter(le.TAILORED, STEM)
    assert letter and letter["paras"] == new, why
    with open(os.path.join(le.TAILORED, STEM + "_cover.md"), encoding="utf-8") as f:
        md = f.read()
    with open(os.path.join(le.TAILORED, STEM + "_cover_data.json"), encoding="utf-8") as f:
        data = json.load(f)
    assert md == "\n\n".join([HEAD] + new + [TAIL]) + "\n", "date, recipient, and sign-off carried over as written"
    assert data["paragraphs"] == new, "the .md and the JSON hold the same paragraphs word for word"
    assert data["date"] == "November 9, 2026" and data["recipient"] == "Hiring Team<br/>Acme"
    assert list(data) == ["date", "recipient", "paragraphs"]
    with open(os.path.join(le.TAILORED, "apply_now", STEM + "_cover.pdf"), encoding="utf-8") as f:
        assert f.read() == "NEW PDF " + bd.letter_sha(new), "the PDF was rendered from the new JSON"

    vdir = os.path.join(le.TAILORED, le.VERSIONS_DIR, STEM, STAMP)
    kept = tree(vdir)
    assert set(kept) == {STEM + "_cover.md", STEM + "_cover_data.json", STEM + "_cover.pdf"}, set(kept)
    assert kept[STEM + "_cover.md"] == old[STEM + "_cover.md"]
    assert kept[STEM + "_cover_data.json"] == old[STEM + "_cover_data.json"]
    assert kept[STEM + "_cover.pdf"] == b"OLD PDF in apply_now"
    assert os.listdir(os.path.join(le.TAILORED, le.VERSIONS_DIR, STEM)) == [STAMP], "no staging left behind"

    (entry,) = log_lines()
    assert entry["status"] == "applied" and entry["url"] == URL and entry["stem"] == STEM
    assert entry["new_sha"] == bd.letter_sha(new) and entry["base_sha"] == bd.letter_sha(PARAS)
    assert entry["version"].endswith(os.path.join(le.VERSIONS_DIR, STEM, STAMP))
    assert entry["first_sentence_changed"] is False and entry["promise_changed"] is False
    assert "text" not in entry, "an applied edit's text is the file itself"
    res = results()[URL]
    assert res["applied"]["new_sha"] == bd.letter_sha(new) and res["applied"]["saved_at"] == "2026-11-12T23:10:00.000Z"
    assert res["last"]["status"] == "applied" and res["last"]["at"] == TODAY


def test_a_second_run_is_idempotent():
    d, inbox = fixture()
    set_inbox(inbox, {URL: edit(changed())})
    run(inbox, "--apply")
    after_first, jobs_first = tree(le.TAILORED), tree(le.JOBS_DIR)
    rc, out = run(inbox, "--apply")
    assert rc == 0 and "applied 0, refused 0, 1 unchanged since an earlier run" in out, out
    assert tree(le.TAILORED) == after_first, "no rewrite and no second version folder"
    assert tree(le.JOBS_DIR) == jobs_first, "and nothing new in the log or the results file"
    # The same text arriving as a fresh save (he saved it again) is already on disk: said once, then quiet.
    set_inbox(inbox, {URL: edit(changed(), base="stale", saved="2026-11-13T01:00:00.000Z")})
    rc, out = run(inbox, "--apply")
    assert "1 already applied" in out and "already applied: Acme: Operations Lead" in out, out
    assert tree(le.TAILORED) == after_first
    assert log_lines()[-1]["status"] == "already" and results()[URL]["applied"]["saved_at"] == "2026-11-12T23:10:00.000Z"


def test_a_second_edit_keeps_a_second_version():
    d, inbox = fixture()
    first = changed()
    set_inbox(inbox, {URL: edit(first)})
    run(inbox, "--apply")
    second = list(first)
    second[1] = second[1].replace("the slow way", "the patient way")
    set_inbox(inbox, {URL: edit(second, saved="2026-11-12T23:40:00.000Z")})   # made on the letter as it now stands
    rc, out = run(inbox, "--apply")
    assert "applied 1" in out and bd.read_letter(le.TAILORED, STEM)[0]["paras"] == second, out
    versions = os.path.join(le.TAILORED, le.VERSIONS_DIR, STEM)
    assert sorted(os.listdir(versions)) == [STAMP, STAMP + "-2"], "the same second never overwrites a kept version"
    with open(os.path.join(versions, STAMP, STEM + "_cover_data.json"), encoding="utf-8") as f:
        assert json.load(f)["paragraphs"] == PARAS
    with open(os.path.join(versions, STAMP + "-2", STEM + "_cover_data.json"), encoding="utf-8") as f:
        assert json.load(f)["paragraphs"] == first
    with open(os.path.join(versions, STAMP + "-2", STEM + "_cover.pdf"), encoding="utf-8") as f:
        assert f.read() == "NEW PDF " + bd.letter_sha(first), "each kept version has the PDF that went with it"


def test_report_mode_writes_nothing():
    d, inbox = fixture()
    set_inbox(inbox, {URL: edit(changed()), "https://example.com/gone": edit(changed())})
    before = tree(d)
    rc, out = run(inbox)
    assert rc == 0 and "would apply 1, would refuse 1 (report only; --apply applies them)" in out, out
    assert "would apply: Acme: Operations Lead" in out and "would refuse: " in out
    assert tree(d) == before, "report mode leaves no version folder, no log, and no results file"
    assert all(not p.startswith(d) for p in RENDERED), "and renders nothing"


def test_refuses_when_the_row_is_missing_or_shared():
    refused(rows=[row(url="https://example.com/other")], expect="No tracker row has this posting link.")
    refused(rows=[row(), row(company="Twin")], expect="Two tracker rows share this posting link")
    d, inbox = fixture()
    set_inbox(inbox, {"acme|operationslead": edit(changed())})
    rc, out = run(inbox, "--apply")
    assert "refused 1" in out and "No tracker row has this posting link." in out, "a row with no link can't be matched"


def test_refuses_any_stage_but_surfaced_and_says_when_it_may_have_gone_out():
    for stage in ("applied", "rejected", "closed", "expired", "interview"):
        assert stage in le.ASSUME_SENT_FOR_SAFETY
        out = refused(rows=[row(stage=stage)], expect=f"The tracker row is {stage}, so this letter may have gone out")
        assert "record of what was sent" in out
    refused(rows=[row(stage="tailored")], expect="The tracker row is tailored, not surfaced.")
    refused(rows=[row(stage="")], expect="The tracker row is blank, not surfaced.")


def test_refuses_a_row_with_any_verdict():
    refused(rows=[row(his_verdict="sent_as_is")], expect="carries your verdict sent_as_is")
    refused(rows=[row(his_verdict="skip_fit")], expect="carries your verdict skip_fit")


def test_refuses_when_another_row_sent_the_same_package():
    twin = "https://example.com/jobs/repost"
    refused(rows=[row(), row(url=twin, stage="applied")],
            expect="Another tracker row names this same package and is applied, so this letter may have gone out from there.")
    refused(rows=[row(), row(url=twin, stage="expired")], expect="names this same package and is expired")
    refused(rows=[row(), row(url=twin, his_verdict="sent_edited")], expect="names this same package and is sent_edited")
    # Two unsent rows sharing one package is only a duplicate: the edit lands, once, for both.
    d, inbox = fixture(rows=[row(), row(url=twin)])
    set_inbox(inbox, {URL: edit(changed())})
    rc, out = run(inbox, "--apply")
    assert "applied 1, refused 0" in out, out


def test_refuses_while_a_sent_mark_waits_on_the_page():
    sent = {"a": "sent", "u": URL + "/", "d": TODAY, "c": "Acme", "t": "Operations Lead"}
    refused(marks={URL: sent}, expect="A Sent mark for this row is waiting on the page")
    refused(marks={"some other key": sent}, expect="A Sent mark for this row is waiting")   # by the mark's own URL too
    # A Skip or a snooze is not a send, and a Sent mark on another row is that row's business.
    d, inbox = fixture()
    set_inbox(inbox, {URL: edit(changed())}, {URL: {"a": "later", "u": URL}, "https://example.com/x": dict(sent, u="https://example.com/x")})
    rc, out = run(inbox, "--apply")
    assert "applied 1, refused 0" in out, out


def test_refuses_when_a_letter_file_is_missing_or_the_notes_name_no_package():
    d, inbox = fixture()
    base = sha_on_disk()
    for gone in ("_cover.md", "_cover_data.json"):
        d, inbox = fixture()
        os.remove(os.path.join(le.TAILORED, STEM + gone))
        set_inbox(inbox, {URL: edit(changed(), base=base)})
        before = tree(le.TAILORED)
        rc, out = run(inbox, "--apply")
        assert "refused 1" in out and f"The package has no {gone}, and a letter is both files." in out, out
        assert tree(le.TAILORED) == before
    for notes in ("Full tier, no file named.", f"{STEM}.pdf, sibling of {bd.PDF_PREFIX}Acme_Other.pdf"):
        d, inbox = fixture(rows=[row(notes=notes)])
        set_inbox(inbox, {URL: edit(changed(), base=base)})
        before = tree(le.TAILORED)
        rc, out = run(inbox, "--apply")
        assert "refused 1" in out and "notes don't name one package" in out, out
        assert tree(le.TAILORED) == before


def test_refuses_when_the_letter_changed_on_disk_or_its_files_disagree():
    refused(edits={URL: {"text": "\n\n".join(changed()), "base_sha": "0123456789abcdef", "saved_at": "x"}},
            expect="isn't the one this edit was made on")
    d, inbox = fixture()
    base = sha_on_disk()
    drifted = list(PARAS)
    drifted[1] = drifted[1].replace("the slow way", "the long way")
    write_letter(le.TAILORED, md_paras=drifted)       # the .md says one thing, the JSON another
    set_inbox(inbox, {URL: edit(changed(), base=base)})
    before = tree(le.TAILORED)
    rc, out = run(inbox, "--apply")
    assert "refused 1" in out and "The letter on disk can't be used" in out and "don't hold the same paragraphs" in out, out
    assert tree(le.TAILORED) == before


def test_refuses_text_that_is_not_a_letter():
    d, inbox = fixture()
    base = sha_on_disk()
    long_para = " ".join(["word"] * 80)
    cases = [(["One paragraph only. " + long_para + " " + long_para], "The edit is 1 paragraph; a letter has at least 2."),
             ([PARAS[0], PARAS[1], "* * *", PARAS[2], PARAS[3]], "One paragraph of the edit has no words in it."),
             ([PARAS[0], PARAS[1]], "words; a letter is 150 to 600."),
             ([long_para] * 8, "The edit is 640 words; a letter is 150 to 600."),
             (changed(new="The floor answers in <5 minutes and >90% of the time."), "can't carry as plain text"),
             (changed(new="I'd bring that same **patience**."), "can't carry as plain text")]
    for paras, expect in cases:
        refused(edits={URL: edit(paras, base=base)}, expect=expect)
    for junk in ({"text": 7, "base_sha": base}, {"text": "\n\n".join(changed())}, {"text": "", "base_sha": ""}):
        d, inbox = fixture()
        set_inbox(inbox, {URL: junk})
        before = tree(le.TAILORED)
        rc, out = run(inbox, "--apply")
        assert "refused 1" in out and "The saved edit is malformed" in out, out
        assert tree(le.TAILORED) == before
    # An empty text box is zero paragraphs, not a wiped letter.
    refused(edits={URL: {"text": "  \n\n \n", "base_sha": base, "saved_at": "x"}}, expect="The edit is 0 paragraphs")


def test_the_same_refusal_is_logged_once_and_a_new_one_again():
    d, inbox = fixture(rows=[row(stage="applied")])
    set_inbox(inbox, {URL: edit(changed())})
    run(inbox, "--apply")
    rc, out = run(inbox, "--apply")
    assert "applied 0, refused 0, 1 unchanged since an earlier run" in out, out
    assert len(log_lines()) == 1
    set_inbox(inbox, {URL: edit(changed(), saved="2026-11-13T02:00:00.000Z")})   # he saved it again
    rc, out = run(inbox, "--apply")
    assert "refused 1" in out and len(log_lines()) == 2, out


def test_a_failed_render_leaves_the_package_as_it_was():
    d, inbox = fixture()
    set_inbox(inbox, {URL: edit(changed())})
    before = tree(le.TAILORED)

    def boom(json_path, pdf_path):
        raise RuntimeError("no contact details in this worktree")
    rc, out = run(inbox, "--apply", render=boom)
    assert rc == 0 and "applied 0, refused 0, 1 FAILED" in out and "The PDF couldn't be rendered" in out, out
    assert tree(le.TAILORED) == before, "no new text without its PDF, and no empty version folder"
    assert log_lines()[-1]["status"] == "failed" and results()[URL]["last"]["status"] == "failed"
    rc, out = run(inbox, "--apply", "--strict", render=lambda j, p: None)   # a renderer that writes nothing
    assert rc == 1 and "the renderer left no PDF" in out and tree(le.TAILORED) == before, out
    rc, out = run(inbox, "--apply")                                          # and the next run gets it done
    assert "applied 1" in out and bd.read_letter(le.TAILORED, STEM)[0]["paras"] == changed(), out


def test_a_failure_after_the_files_moved_puts_the_kept_version_back():
    d, inbox = fixture(pdf="none")
    set_inbox(inbox, {URL: edit(changed())})
    before = tree(le.TAILORED)
    real, calls = bd.read_letter, []

    def flaky(tailored, stem):
        calls.append(stem)
        return real(tailored, stem) if len(calls) == 1 else (None, "simulated fault on the read-back")
    bd.read_letter = flaky
    try:
        rc, out = run(inbox, "--apply")
    finally:
        bd.read_letter = real
    assert rc == 0 and "1 FAILED" in out and "The earlier version was put back" in out, out
    after = tree(le.TAILORED)
    versions = {k: v for k, v in after.items() if k.startswith(le.VERSIONS_DIR)}
    assert {k: v for k, v in after.items() if k not in versions} == before, "the letter is as it was, and no stray PDF"
    assert set(versions) == {os.path.join(le.VERSIONS_DIR, STEM, STAMP, STEM + s) for s in ("_cover.md", "_cover_data.json")}, \
        "the kept copy is never removed once a file has moved"
    assert bd.read_letter(le.TAILORED, STEM)[0]["paras"] == PARAS and log_lines()[-1]["status"] == "failed"


def test_the_pdf_is_replaced_where_it_lives():
    d, inbox = fixture(pdf="tailored")          # rotate_apply_folder.py moved it back
    set_inbox(inbox, {URL: edit(changed())})
    run(inbox, "--apply")
    assert not os.path.exists(os.path.join(le.TAILORED, "apply_now", STEM + "_cover.pdf"))
    with open(os.path.join(le.TAILORED, STEM + "_cover.pdf"), encoding="utf-8") as f:
        assert f.read().startswith("NEW PDF")
    d, inbox = fixture(pdf="both")
    set_inbox(inbox, {URL: edit(changed())})
    run(inbox, "--apply")
    for folder in (os.path.join(le.TAILORED, "apply_now"), le.TAILORED):
        with open(os.path.join(folder, STEM + "_cover.pdf"), encoding="utf-8") as f:
            assert f.read().startswith("NEW PDF"), "a stale second copy would be the one rotation keeps"
    kept = tree(os.path.join(le.TAILORED, le.VERSIONS_DIR, STEM, STAMP))
    assert kept[STEM + "_cover.pdf"] == b"OLD PDF in apply_now"
    assert kept[os.path.join("copy_in_tailored", STEM + "_cover.pdf")] == b"OLD PDF in tailored"
    d, inbox = fixture(pdf="none")
    set_inbox(inbox, {URL: edit(changed())})
    run(inbox, "--apply")
    assert os.path.exists(os.path.join(le.TAILORED, "apply_now", STEM + "_cover.pdf")), "none yet: the documented place"


def test_untouched_paragraphs_keep_each_files_own_spelling():
    raw_json = list(PARAS)
    raw_json[0] = raw_json[0].replace("nine days", "<b>nine days</b>")
    raw_json[2] = raw_json[2].replace("the handoffs", "the hand-offs &amp; the waiting")
    raw_md = list(PARAS)
    raw_md[0] = raw_md[0].replace("nine days", "**nine days**")
    raw_md[2] = raw_md[2].replace("the handoffs", "the hand-offs & the waiting")
    d, inbox = fixture(paras=raw_json, md_paras=raw_md, extra={"closing": "Warmly,", "name": "Jane Doe"})
    on_disk = bd.read_letter(le.TAILORED, STEM)[0]["paras"]
    new = list(on_disk)
    new[3] = new[3].replace("one chapter a night", "one chapter a night & two on weekends")
    set_inbox(inbox, {URL: edit(new)})
    rc, out = run(inbox, "--apply")
    assert "applied 1" in out, out
    with open(os.path.join(le.TAILORED, STEM + "_cover.md"), encoding="utf-8") as f:
        md = f.read()
    with open(os.path.join(le.TAILORED, STEM + "_cover_data.json"), encoding="utf-8") as f:
        data = json.load(f)
    assert "**nine days**" in md and "<b>nine days</b>" in data["paragraphs"][0], "bold survives on a paragraph he left alone"
    assert data["paragraphs"][2] == raw_json[2]
    assert "a night & two on weekends" in md and "a night &amp; two on weekends" in data["paragraphs"][3], \
        "his text is plain in the .md and escaped for the renderer in the JSON"
    assert (data["closing"], data["name"]) == ("Warmly,", "Jane Doe"), "every other JSON key is carried over"
    assert bd.read_letter(le.TAILORED, STEM)[0]["paras"] == new


def test_the_voice_check_is_recorded_and_never_blocks():
    stiff = list(PARAS)
    stiff[1] = ("That kind of follow-through is why the work suits me. I am applying for the Operations Lead role "
                "at Acme because it is floor work. I would like the job, and I do not mind that it is not easy. "
                "I have not been handed anything, and I will not ask to be. I am patient, and that is most of it. "
                "I did not get here quickly, and I cannot pretend I did.")
    d, inbox = fixture()
    set_inbox(inbox, {URL: edit(stiff)})
    rc, out = run(inbox, "--apply")
    assert "applied 1" in out and "CONTRACTIONS" in out, out
    entry = log_lines()[-1]
    assert entry["status"] == "applied" and entry["voice_clean"] is False and "CONTRACTIONS" in entry["voice"]
    assert bd.read_letter(le.TAILORED, STEM)[0]["paras"] == stiff, "his words went in exactly as he wrote them"
    real = le.voice_report
    le.voice_report = lambda md_path: 1 / 0
    try:
        d, inbox = fixture()
        set_inbox(inbox, {URL: edit(changed())})
        rc, out = run(inbox, "--apply")
    finally:
        le.voice_report = real
    assert "applied 1" in out and "check_voice.py could not run" in out, out


def test_it_says_when_the_opener_or_the_promise_changed_and_touches_nothing_else():
    d, inbox = fixture()
    openers = os.path.join(le.TAILORED, "_cover_openers.md")
    with open(openers, "w", encoding="utf-8") as f:
        f.write('- [2026-11-09] Acme: "A customer of ours once waited nine days."\n')
    new = list(PARAS)
    new[0] = "A customer of ours once waited eleven days for a part." + new[0][new[0].index(" I called her"):]
    assert "During my first month" in new[3]
    new[3] = new[3].replace("During my first month", "During my first two weeks")
    set_inbox(inbox, {URL: edit(new)})
    rc, out = run(inbox, "--apply")
    assert "note: the first sentence changed; tailored/_cover_openers.md still has the old opener" in out, out
    assert "note: the promise sentence changed" in out and "brief file" in out, out
    with open(openers, encoding="utf-8") as f:
        assert "nine days" in f.read(), "the opener log is never touched"
    entry = log_lines()[-1]
    assert entry["first_sentence_changed"] is True and entry["promise_changed"] is True
    d, inbox = fixture()
    set_inbox(inbox, {URL: edit(changed())})
    rc, out = run(inbox, "--apply")
    assert "note:" not in out, out


def test_one_bad_edit_does_not_block_the_rest_and_results_follow_the_queue():
    other = "https://example.com/jobs/2"
    stem2 = bd.PDF_PREFIX + "Bolt_SupportMgr"
    d, inbox = fixture(rows=[row(), row(company="Bolt", title="Support Manager", url=other,
                                        notes=f"tailored/apply_now/{stem2}.pdf + _cover.pdf")])
    write_letter(le.TAILORED, stem=stem2)
    set_inbox(inbox, {URL: edit(changed()), other: edit([PARAS[0]]), "junk": {"text": None}})
    rc, out = run(inbox, "--apply")
    assert rc == 0 and "applied 1, refused 2" in out, out
    assert bd.read_letter(le.TAILORED, STEM)[0]["paras"] == changed()
    assert bd.read_letter(le.TAILORED, stem2)[0]["paras"] == PARAS
    assert set(results()) == {URL, other, "junk"}
    # The page cleared its edits and the first row was sent: its result leaves with it.
    with open(le.OUTCOMES, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows([row(stage="applied"), row(company="Bolt", title="Support Manager", url=other,
                                               notes=f"tailored/apply_now/{stem2}.pdf + _cover.pdf")])
    set_inbox(inbox, {other: edit(changed(), base=bd.letter_sha(PARAS), saved="2026-11-13T02:00:00.000Z")})
    run(inbox, "--apply")
    assert set(results()) == {other}, results()
    assert os.path.exists(os.path.join(le.JOBS_DIR, le.RESULTS_NAME + ".bak")), "one copy aside before the rewrite"


def test_no_edits_and_failures_exit_zero_and_strict_exits_one():
    d, inbox = fixture()
    rc, out = run(inbox, "--apply")
    assert rc == 0 and out.strip() == "letter_edits: no letter edits saved (none on the page)", out
    assert os.listdir(le.JOBS_DIR) == []
    set_inbox(inbox, {URL: edit(changed())})
    os.remove(le.OUTCOMES)
    before = tree(le.TAILORED)
    rc, out = run(inbox, "--apply")
    assert rc == 0 and out.startswith("letter_edits: FAILED FileNotFoundError"), out
    assert run(inbox, "--apply", "--strict")[0] == 1
    assert tree(le.TAILORED) == before
    with open(inbox, "w", encoding="utf-8") as f:
        f.write("{not json")
    rc, out = run(inbox, "--apply")
    assert rc == 0 and "letter_edits: FAILED" in out, out
    # The Sent marks can't be read: it can't know which letters went out, so it applies nothing.
    d, inbox = fixture()
    with open(inbox, "w", encoding="utf-8") as f:
        json.dump({si.INBOX_KEY: "[1, 2]", le.LETTERS_KEY: json.dumps({URL: edit(changed())})}, f)
    before = tree(le.TAILORED)
    rc, out = run(inbox, "--apply")
    assert "letter_edits: FAILED" in out and tree(le.TAILORED) == before, out
    # A results file that won't parse is never overwritten.
    d, inbox = fixture()
    set_inbox(inbox, {URL: edit(changed())})
    with open(os.path.join(le.JOBS_DIR, le.RESULTS_NAME), "w", encoding="utf-8") as f:
        f.write("{broken")
    rc, out = run(inbox, "--apply")
    assert "letter_edits: FAILED" in out, out
    with open(os.path.join(le.JOBS_DIR, le.RESULTS_NAME), encoding="utf-8") as f:
        assert f.read() == "{broken"


def test_contracts_with_the_page_and_the_generator():
    assert le.RESULTS_NAME == bd.LETTER_RESULTS and le.LIMITS is bd.LETTER_LIMITS
    assert "EKEY='%s'" % le.LETTERS_KEY in bd.PAGE, "the page and letter_edits.py must share the storage key"
    assert "{text:text,base_sha:L.sha,saved_at:new Date().toISOString()}" in bd.PAGE, "the shape plan_one() reads"
    d, inbox = fixture()
    letter = bd.read_letter(le.TAILORED, STEM)[0]
    md, js = le.compose(letter, letter["paras"])
    with open(os.path.join(le.TAILORED, STEM + "_cover.md"), encoding="utf-8") as f:
        assert f.read() == md, "composing an unchanged letter reproduces its .md"
    with open(os.path.join(le.TAILORED, STEM + "_cover_data.json"), encoding="utf-8") as f:
        assert json.load(f) == json.loads(js)


def test_the_real_renderer_is_called_the_documented_way():
    import subprocess
    seen = {}
    real = subprocess.run

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        with open(cmd[-1], "w", encoding="utf-8") as f:
            f.write("pdf")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    d = tempfile.mkdtemp(prefix="letter_test_")
    subprocess.run = fake_run
    try:
        le.render_cover(os.path.join(d, "x.json"), os.path.join(d, "x.pdf"))
        subprocess.run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "Traceback\nRuntimeError: no contact")
        try:
            le.render_cover(os.path.join(d, "y.json"), os.path.join(d, "y.pdf"))
            raise AssertionError("a failed render must raise")
        except RuntimeError as e:
            assert "no contact" in str(e)
    finally:
        subprocess.run = real
    assert seen["cmd"][1:] == [os.path.join(le.SCRIPT_DIR, "render_pdf.py"), "cover",
                               os.path.join(d, "x.json"), os.path.join(d, "x.pdf")], seen


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
