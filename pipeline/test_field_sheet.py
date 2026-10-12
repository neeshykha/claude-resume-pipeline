#!/usr/bin/env python3
"""Tests for field_sheet.py. Fixtures are built in a temp dir with a made-up person
and made-up employers; nothing here reads the real profile or any tailored resume.

    .venv/bin/python pipeline/test_field_sheet.py
"""
import atexit
import contextlib
import copy
import io
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import field_sheet as fs  # noqa: E402

STEM = "Jane_Doe_Acme_SupportOps"
NEEDS = fs.NEEDS

PROFILE = {
    "legal_name": {"first": "Jane", "last": "Doe", "preferred": "Jane"},
    "contact": {"email": "jane.doe@example.com", "phone": "555-0100", "phone_type": "Mobile",
                "phone_country_code": "United States of America (+1)",
                "address_line_1": NEEDS, "address_line_2": "", "city": "Springfield",
                "state": "Ohio", "postal_code": NEEDS, "country": "United States of America",
                "linkedin": "https://www.linkedin.com/in/jane-doe-example/",
                "github": "https://github.com/jane-doe-example"},
    "employment": [
        {"title": "Support Operations Manager", "company": "Acme Co", "location": "Springfield, OH",
         "start": "03/2020", "end": "PRESENT", "current": True},
        {"title": "Support Lead", "company": "Bolt Works (North)", "location": "Shelbyville, OH",
         "start": NEEDS + "/2017", "end": "11/2019", "current": False},
        {"title": "Support Lead", "company": "Bolt Works (South)", "location": "Capital City, OH",
         "start": "6/2015", "end": NEEDS + "/2017", "current": False},
        {"title": "Support Agent", "company": "Cask Labs", "location": "Ogdenville, OH",
         "start": "01/2013", "end": "05/2015", "current": False},
    ],
    "education": [{"school": "Example State University", "degree": "Bachelor's Degree",
                   "field": "Economics", "start_year": NEEDS, "end_year": "2012", "gpa": ""}],
    fs.SCREENING_KEY: [
        "Legally authorized to work in the US?", "Will you require sponsorship now or in future?",
        "Desired salary / compensation expectations", "Earliest start date",
        "Any free-text 'why this company' box"],
}

RESUME = {
    "summary": "Support operations leader.",
    "experience": [
        {"title": "Support Operations Manager",
         "company": "<b>Acme Co</b> &nbsp;|&nbsp; March 2020 &ndash; Present",
         "bullets": ["Cut backlog 40% with <b>workflow automation</b>.",
                     "Led a team of 8 across R&amp;D and support."]},
        {"title": "Support Lead", "company": "Bolt Works (North)  |  2017 – 2019",
         "bullets": ["Ran escalations for the northern region."]},
        {"title": "Support Lead", "company": "Bolt Works (South)  |  2015 - 2017",
         "bullets": ["Opened the southern support desk."]},
        {"title": "Support Lead / Support Agent",
         "company": "Cask Labs (Startup)  |  2013 – 2015 (Acquired by Bolt Works in 2016)",
         "bullets": ["First support hire."]},
        {"title": "Lab Assistant", "company": "Dune Lab  |  February 2012 – June 2013",
         "bullets": ["Kept the lab's servers patched."]},
    ],
    "education": {"degree": "Bachelor of Arts in Economics",
                  "school": "Example State University  |  2012"},
    "skills": ["<b>Platforms &amp; Tools:</b> Helpdesk administration, SQL",
               "<b>Methods:</b> Vendor selection, BPO management"],
}


def fixture(resume=RESUME, profile=PROFILE, pdfs=()):
    d = tempfile.mkdtemp(prefix="field_sheet_test_")
    atexit.register(shutil.rmtree, d, ignore_errors=True)
    os.makedirs(os.path.join(d, "tailored", "apply_now"))
    os.makedirs(os.path.join(d, "pipeline"))
    if resume is not None:
        with open(os.path.join(d, "tailored", f"{STEM}_data.json"), "w", encoding="utf-8") as f:
            json.dump(resume, f)
    if profile is not None:
        with open(os.path.join(d, "pipeline", "application_profile.json"), "w", encoding="utf-8") as f:
            json.dump(profile, f)
    for rel in pdfs:
        open(os.path.join(d, "tailored", rel), "w").close()
    return d


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = fs.main(argv)
    return code, out.getvalue()


def build(resume=RESUME, profile=PROFILE, pdfs=()):
    """(sheet JSON, markdown text, the stdout line) from one strict run into a fresh --out."""
    d = fixture(resume, profile, pdfs)
    out = os.path.join(d, "out")
    code, line = run([STEM, "--repo", d, "--out", out, "--strict"])
    assert code == 0, line
    with open(os.path.join(out, f"{STEM}_fields.json"), encoding="utf-8") as f:
        data = json.load(f)
    with open(os.path.join(out, f"{STEM}_fields.md"), encoding="utf-8") as f:
        return data, f.read(), line


def changed(base, **edits):
    """A deep copy of a fixture with 'a.b.c' paths replaced; an int segment indexes a list."""
    new = copy.deepcopy(base)
    for path, value in edits.items():
        node, keys = new, [int(k) if k.isdigit() else k for k in path.split("__")]
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value
    return new


def sec(data, title):
    hits = [s for s in data["sections"] if s["title"] == title]
    assert len(hits) == 1, (title, [s["title"] for s in data["sections"]])
    return {f["label"]: f for f in hits[0]["fields"]}


def read_md(text):
    """[(label, value, flagged)] parsed back out of the sheet by CommonMark's own rules
    for code spans and fences, so a value that broke the markup comes back different."""
    out, lines, i = [], text.split("\n"), 0
    while i < len(lines):
        m = re.match(r"- (`>>>` )?\*\*((?:\\.|[^\\*])+)\*\*(.*)$", lines[i])
        i += 1
        if not m:
            continue
        label = re.sub(r"\\(.)", r"\1", m.group(2))
        label, rest, value = label[:-1] if label.endswith(":") else label, m.group(3), ""
        if rest:
            assert rest.startswith(" `"), rest
            n = len(rest) - 1 - len(rest[1:].lstrip("`"))
            body = rest[1 + n:]
            close = re.search(r"(?<!`)`{%d}(?!`)" % n, body)  # first run of exactly n closes the span
            assert close and close.end() == len(body), f"code span leaks: {lines[i - 1]!r}"
            value = body[:close.start()]
            if value.startswith(" ") and value.endswith(" ") and value.strip():
                value = value[1:-1]
        elif i + 1 < len(lines) and lines[i] == "" and re.fullmatch(r"`{3,}", lines[i + 1]):
            n, i, body = len(lines[i + 1]), i + 2, []
            while not re.fullmatch(r"`{%d,}\s*" % n, lines[i]):  # closing fence: at least as long
                body.append(lines[i])
                i += 1
            value = "\n".join(body)
        out.append((label, value, bool(m.group(1))))
    return out


def flat(data):
    return [(f["label"], f["value"], f["needs_you"]) for s in data["sections"] for f in s["fields"]]


def test_months_come_from_the_profile():
    data, _, _ = build()
    one = sec(data, "Work experience 1 of 5")
    assert one["Company"]["value"] == "Acme Co", "renderer markup and entities are stripped before matching"
    assert one["Location"]["value"] == "Springfield, OH"
    assert one["From"] == {"label": "From", "value": "03/2020", "needs_you": False}
    assert one[fs.CURRENT]["value"] == "Yes" and "To" not in one
    assert list(one) == ["Job Title", "Company", "Location", fs.CURRENT, "From", "Role Description"]
    assert sec(data, "Work experience 2 of 5")["To"] == {"label": "To", "value": "11/2019", "needs_you": False}
    three = sec(data, "Work experience 3 of 5")
    assert three["From"]["value"] == "06/2015" and not three["From"]["needs_you"], "6/2015 is zero-padded"
    assert three["Company"]["value"] == "Bolt Works (South)" and three["Location"]["value"] == "Capital City, OH"


def test_year_without_a_month_stays_MM_and_needs_you():
    data, _, _ = build()
    assert sec(data, "Work experience 2 of 5")["From"] == {"label": "From", "value": "MM/2017", "needs_you": True}
    assert sec(data, "Work experience 3 of 5")["To"] == {"label": "To", "value": "MM/2017", "needs_you": True}


def test_role_missing_from_profile_gets_MM_and_needs_you():
    data, _, _ = build()
    five = sec(data, "Work experience 5 of 5")
    assert five["Job Title"]["value"] == "Lab Assistant" and five["Company"]["value"] == "Dune Lab"
    assert five["From"] == {"label": "From", "value": "MM/2012", "needs_you": True}, \
        "the resume's own 'February' is not read as a month"
    assert five["To"] == {"label": "To", "value": "MM/2013", "needs_you": True}
    assert five["Location"] == {"label": "Location", "value": "", "needs_you": True}
    assert five["Role Description"]["value"] == "Kept the lab's servers patched."
    # No date range on the resume and no profile entry: nothing is known, so nothing is printed.
    data, _, _ = build(resume=changed(RESUME, experience__4__company="Dune Lab"))
    five = sec(data, "Work experience 5 of 5")
    assert five["From"]["value"] == five["To"]["value"] == "MM/YYYY"
    assert five["From"]["needs_you"] and five["To"]["needs_you"]


def test_annotated_company_and_split_title_find_the_profile_entry():
    four = sec(build()[0], "Work experience 4 of 5")
    assert four["Company"]["value"] == "Cask Labs" and four["Job Title"]["value"] == "Support Agent"
    assert four["From"]["value"] == "01/2013" and four["To"]["value"] == "05/2015"
    assert not four["From"]["needs_you"], "the year inside '(Acquired ... in 2016)' is not a third date"


def test_two_different_parentheticals_never_cross_match():
    data, _, _ = build(resume=changed(RESUME, experience__1__company="Bolt Works (East)  |  2017 – 2019"))
    two = sec(data, "Work experience 2 of 5")
    assert two["Company"]["value"] == "Bolt Works (East)"
    assert two["Location"]["needs_you"] and two["From"]["value"] == "MM/2017" and two["To"]["value"] == "MM/2019"
    # Same company, a title the profile doesn't list for it: also no match.
    data, _, _ = build(resume=changed(RESUME, experience__0__title="Head of Support"))
    one = sec(data, "Work experience 1 of 5")
    assert one["Job Title"]["value"] == "Head of Support" and one["From"]["value"] == "MM/2020"
    assert one[fs.CURRENT]["value"] == "Yes", "'Present' is the resume's own statement"


def test_two_profile_entries_for_one_role_is_a_miss_not_a_pick():
    twice = copy.deepcopy(PROFILE)
    twice["employment"].append(dict(twice["employment"][0], start="09/2021"))
    one = sec(build(profile=twice)[0], "Work experience 1 of 5")
    assert one["From"] == {"label": "From", "value": "MM/2020", "needs_you": True}


def test_year_disagreement_is_flagged_not_settled():
    data, _, _ = build(resume=changed(RESUME, experience__1__company="Bolt Works (North)  |  2018 – 2019",
                                      experience__0__company="Acme Co  |  2020 – 2024"))
    two = sec(data, "Work experience 2 of 5")
    assert "From" not in two and two["From (profile and resume disagree)"]["value"] == "MM/YYYY"
    assert two["From (profile and resume disagree)"]["needs_you"]
    assert two["To"]["value"] == "11/2019", "the end date still agrees, so it stands"
    one = sec(data, "Work experience 1 of 5")
    assert fs.CURRENT not in one, "the profile says current, the resume gives an end year"
    assert one["To (profile and resume disagree)"] == {
        "label": "To (profile and resume disagree)", "value": "MM/YYYY", "needs_you": True}
    edu = sec(build(resume=changed(RESUME, education__school="Example State University | 2011"))[0], "Education")
    assert edu["To (profile and resume disagree)"]["value"] == ""


def test_needs_values_come_out_empty_and_flagged():
    data, md, _ = build()
    info = sec(data, "My information")
    for label in ("Address Line 1", "Postal Code"):
        assert info[label] == {"label": label, "value": "", "needs_you": True}
    assert info["First Name"] == {"label": "First Name", "value": "Jane", "needs_you": False}
    assert "Address Line 2" not in info, "an optional field left blank in the profile stays off the sheet"
    edu = sec(data, "Education")
    assert edu["From"] == {"label": "From", "value": "", "needs_you": True}
    assert edu["To"]["value"] == "2012" and edu["Degree"]["value"] == "Bachelor's Degree"
    assert edu["Field of Study"]["value"] == "Economics" and "Overall Result / GPA" not in edu
    assert NEEDS not in json.dumps(data) and NEEDS not in md, "the sentinel never reaches an output"
    assert "- `>>>` **Address Line 1:**" in md.split("\n")
    # Absent altogether behaves the same as never supplied.
    bare = copy.deepcopy(PROFILE)
    del bare["contact"]["email"], bare["legal_name"], bare["education"], bare["employment"]
    data, _, _ = build(profile=bare)
    info = sec(data, "My information")
    assert info["Email"]["needs_you"] and info["Last Name"]["needs_you"] and info["Email"]["value"] == ""
    assert sec(data, "Education")["Field of Study"]["needs_you"]
    assert sec(data, "Education")["School"]["value"] == "Example State University"
    assert sec(data, "Work experience 1 of 5")["From"]["value"] == "MM/2020"


def test_personal_sections_are_flagged():
    full = changed(PROFILE, contact__address_line_1="12 Example Street", contact__postal_code="00000")
    data, _, _ = build(profile=full)
    assert [s["title"] for s in data["sections"] if s["personal"]] == ["My information", "Websites"]
    assert [s["title"] for s in data["sections"] if not s["personal"]] == [
        "Start", "Work experience 1 of 5", "Work experience 2 of 5", "Work experience 3 of 5",
        "Work experience 4 of 5", "Work experience 5 of 5", "Education", "Skills", "Only you"]
    public = json.dumps([s for s in data["sections"] if not s["personal"]])
    for private in ("12 Example Street", "00000", "555-0100", "jane.doe@example.com", "linkedin.com", "github.com"):
        assert private not in public, private
        assert private in json.dumps(data)


def test_screening_and_eeo_are_listed_and_never_answered():
    loaded = dict(PROFILE, work_authorization="ZZ-ANSWER", salary_expectation="ZZ-ANSWER",
                  eeo={"gender": "ZZ-ANSWER", "veteran": "ZZ-ANSWER"})
    data, md, _ = build(profile=loaded)
    only = sec(data, "Only you")
    assert all(f["value"] == "" and f["needs_you"] for f in only.values())
    assert "ZZ-ANSWER" not in json.dumps(data) and "ZZ-ANSWER" not in md
    labels = list(only)
    for subject in ("authoriz", "sponsor", "salary", "start date", "why", "schedule"):
        assert sum(bool(re.search(subject, l, re.I)) for l in labels) == 1, (subject, labels)
    assert labels[:5] == PROFILE[fs.SCREENING_KEY], "the profile's wording, in its order"
    assert labels[-4:] == ["Gender (self-identification)", "Race / ethnicity (self-identification)",
                           "Veteran status (self-identification)", "Disability (self-identification)"]
    assert data["sections"][-1]["title"] == "Only you"
    # A profile with no list at all still gets every default.
    none = {k: v for k, v in PROFILE.items() if k != fs.SCREENING_KEY}
    labels = list(sec(build(profile=none)[0], "Only you"))
    assert len(labels) == len(fs.SCREENING) + len(fs.SELF_ID)
    for subject in ("authoriz", "sponsor", "salary", "start date", "why"):
        assert any(re.search(subject, l, re.I) for l in labels), subject


def test_description_is_the_tailored_bullets_one_per_line():
    data, md, _ = build()
    want = "Cut backlog 40% with workflow automation.\nLed a team of 8 across R&D and support."
    assert sec(data, "Work experience 1 of 5")["Role Description"]["value"] == want
    assert "```\n" + want + "\n```" in md


def test_skills_from_list_and_dict_shapes():
    skills = sec(build()[0], "Skills")
    assert skills["Platforms & Tools"]["value"] == "Helpdesk administration, SQL"
    assert list(skills) == ["Platforms & Tools", "Methods"], "the resume's order"
    as_dict = changed(RESUME, skills={"Platforms &amp; Tools": "Helpdesk administration, SQL",
                                      "Methods": ["Vendor selection", "BPO management"]})
    skills = sec(build(resume=as_dict)[0], "Skills")
    assert skills["Platforms & Tools"]["value"] == "Helpdesk administration, SQL"
    assert skills["Methods"]["value"] == "Vendor selection, BPO management"
    assert "Skills" not in [s["title"] for s in build(resume=changed(RESUME, skills=[]))[0]["sections"]]


def test_start_names_the_rendered_pdf():
    start = sec(build(pdfs=[f"apply_now/{STEM}.pdf", f"apply_now/{STEM}_ATS.pdf", f"{STEM}_cover.pdf"])[0], "Start")
    assert start["Resume to upload"]["value"] == f"tailored/apply_now/{STEM}_ATS.pdf"
    assert start["Cover letter, if the form takes a second file"]["value"] == f"tailored/{STEM}_cover.pdf"
    start = sec(build(pdfs=[f"{STEM}.pdf"])[0], "Start")
    assert start["Resume to upload"]["value"] == f"tailored/{STEM}.pdf" and len(start) == 1
    start = sec(build()[0], "Start")
    assert list(start.values()) == [
        {"label": "Resume to upload (no rendered PDF found)", "value": "", "needs_you": True}]


def test_missing_inputs_fail_quietly_and_write_nothing():
    for resume, profile, word in ((None, PROFILE, "_data.json"), (RESUME, None, "application_profile.json")):
        d = fixture(resume, profile)
        out = os.path.join(d, "out")
        code, line = run([STEM, "--repo", d, "--out", out])
        assert code == 0 and line.startswith("field_sheet: FAILED ") and word in line, line
        assert line.count("\n") == 1 and "Traceback" not in line
        assert not os.path.exists(out)
        assert run([STEM, "--repo", d, "--out", out, "--strict"])[0] == 1
    d = fixture()
    with open(os.path.join(d, "tailored", f"{STEM}_data.json"), "w") as f:
        f.write("{not json")
    code, line = run([STEM, "--repo", d, "--out", os.path.join(d, "out")])
    assert code == 0 and "not valid JSON" in line
    assert run([STEM, "--repo", fixture(resume={"summary": "x", "experience": []}), "--strict"])[0] == 1
    for argv in ([], ["--repo", d], [STEM, "--out"], [STEM, "extra"], [STEM, "--nope"]):
        code, line = run(argv)
        assert code == 0 and line.startswith("field_sheet: FAILED "), (argv, line)
        assert run(argv + ["--strict"])[0] == 1


def test_json_is_valid_and_only_the_two_outputs_are_written():
    d = fixture()
    out = os.path.join(d, "out")
    code, line = run([STEM, "--repo", d, "--out", out, "--strict"])
    assert code == 0
    assert sorted(os.listdir(out)) == [f"{STEM}_fields.json", f"{STEM}_fields.md"], "no temp file left behind"
    with open(os.path.join(out, f"{STEM}_fields.json"), encoding="utf-8") as f:
        data = json.load(f)
    assert set(data) == {"stem", "generated", "sections"} and data["stem"] == STEM
    assert isinstance(datetime.fromisoformat(data["generated"]), datetime)
    for s in data["sections"]:
        assert set(s) == {"title", "personal", "fields"} and isinstance(s["personal"], bool) and s["fields"]
        for f in s["fields"]:
            assert set(f) == {"label", "value", "needs_you"}
            assert isinstance(f["label"], str) and isinstance(f["value"], str) and isinstance(f["needs_you"], bool)
            assert f["value"] or f["needs_you"], "an empty value is always flagged"
    fields = flat(data)
    assert line == (f"field_sheet: {STEM} -> {len(data['sections'])} sections, {len(fields)} fields, "
                    f"{sum(f[2] for f in fields)} need you\n")
    assert set(os.listdir(os.path.join(d, "tailored"))) == {"apply_now", f"{STEM}_data.json"}, \
        "--out means nothing lands beside the inputs"


def test_default_output_is_tailored_under_the_repo():
    d = fixture()
    assert run([f"tailored/{STEM}_data.json", "--repo", d, "--strict"])[0] == 0, "a data-file path works as a stem"
    assert set(os.listdir(os.path.join(d, "tailored"))) == {
        "apply_now", f"{STEM}_data.json", f"{STEM}_fields.json", f"{STEM}_fields.md"}


def test_markdown_carries_exactly_the_json_fields():
    data, md, _ = build()
    assert read_md(md) == flat(data)
    titles = re.findall(r"^## \d+\. (.+)$", md, re.M)
    assert titles == [s["title"] for s in data["sections"]], "the form's order, same in both files"
    assert "- 3. Work experience 1 of 5" not in md and "- 4. Work experience 2 of 5: From `MM/2017`" in md


def test_backtick_and_pipe_do_not_break_the_markdown():
    nasty = ["a `tick` b", "`starts and ends`", "pipe | in | value", "``` fence", "**bold** _it_ [x](y)",
             "trailing \\", "<b>kept</b> & &amp; <i>gone</i>"]
    resume = changed(RESUME, experience__0__bullets=["Used `grep | sort` daily.", "```", "Wrote ````four```` ticks."],
                     skills=["<b>Shell `sh` | *nix [x]:</b> grep `-r`, a | b", "<b>Long:</b> " + "x`y | " * 40])
    profile = changed(PROFILE, contact__city=nasty[0], contact__state=nasty[1], contact__country=nasty[2],
                      contact__address_line_1=nasty[3], contact__postal_code=nasty[4],
                      contact__phone_type=nasty[5], legal_name__first=nasty[6],
                      **{fs.SCREENING_KEY: ["Why `us` | *them*?", "Start date_now [y/n]"]})
    data, md, _ = build(resume=resume, profile=profile)
    info = sec(data, "My information")
    assert [info[k]["value"] for k in ("City", "State", "Country", "Address Line 1", "Postal Code",
                                       "Phone Device Type", "First Name")] == nasty, "profile text is never rewritten"
    assert read_md(md) == flat(data), "every value reads back out of the markdown unchanged"
    assert not any(l.startswith("|") or re.fullmatch(r"[\s|:-]+", l) and "|" in l for l in md.split("\n")), \
        "no table for a pipe to split"
    desc = sec(data, "Work experience 1 of 5")["Role Description"]["value"]
    assert desc.split("\n") == ["Used `grep | sort` daily.", "```", "Wrote ````four```` ticks."]
    assert "\n`````\n" + desc + "\n`````\n" in md, "the fence outgrows the longest run inside it"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
