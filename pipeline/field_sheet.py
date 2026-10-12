#!/usr/bin/env python3
"""Writes the paste sheet for one tailored package: every field a long application
form asks for, in the form's own order, as text to paste instead of retype.

Usage:
    .venv/bin/python pipeline/field_sheet.py <stem>               # into tailored/
    .venv/bin/python pipeline/field_sheet.py <stem> --out DIR     # write only into DIR (first runs, tests)
    .venv/bin/python pipeline/field_sheet.py <stem> --repo PATH   # read another checkout's data
    .venv/bin/python pipeline/field_sheet.py <stem> --strict      # exit 1 on failure (tests only)

Added 2026-10-12.

WHY THIS EXISTS
---------------
Workday, Paylocity, Taleo, and iCIMS make him retype his whole work history after
the resume upload, and packages on those systems go unsent far more often than the
rest. The assisted-apply skill's no-browser fallback is a paste sheet, and until now
that sheet was written by hand, once. This builds it for any package with no model
in the loop: it reads two files, copies values out of them, and costs no tokens.

Reads, under the repo root (this checkout, or --repo):
    tailored/<stem>_data.json            which roles, in what order, and their bullets
    pipeline/application_profile.json    form values: contact block, exact months, locations

Writes, atomically, into tailored/ of that same root or into --out:
    <stem>_fields.md      the sheet, values in backticks so they select cleanly
    <stem>_fields.json    the same fields for the dashboard's copy buttons:
                          {"stem", "generated", "sections": [{"title", "personal",
                           "fields": [{"label", "value", "needs_you"}]}]}

Both outputs hold a home address and a phone number. tailored/ is gitignored for that
reason; keep --out pointed somewhere that is too. `personal: true` marks the sections
a page should leave out (contact block, websites).

WHAT IT WILL NOT DO
-------------------
The skill's hard boundaries, held here by construction rather than by care:

  * It never invents or infers a value. A month comes from the profile or it stays
    the literal `MM`; the resume's own "February 2023" is not read as a month, so
    there is one source for months and it is the one he typed. A year the two files
    disagree on is flagged, never settled.
  * Anything the profile marks NEEDS_ANEESH, or doesn't hold, comes out empty with
    needs_you set. The sentinel itself never reaches an output.
  * Screening questions and EEO / self-identification are listed by name and left
    empty. The script reads a fixed list of profile keys, so an answer sitting
    anywhere else in that file cannot leak into a sheet.

HOW A RESUME ROLE FINDS ITS PROFILE ENTRY
-----------------------------------------
By company AND title, and only when exactly one entry fits; anything else is "not in
the profile", which costs him a month to type, where a wrong match would put a wrong
date on a real application. Renderer markup and entities are stripped first. A
parenthetical on one side only is treated as an annotation ("Name (Startup)" finds
"Name"); two different parentheticals are two different companies. A title written
"Lead / Agent" on the resume finds a profile entry for either half.

When a role matches, the profile's title, company, and location go on the sheet,
since those are the form values and the skill says employment entries come from
there. The description is always the tailored bullets for THIS package, one per
line, so the form agrees with the uploaded PDF.

Always exits 0 and prints one line, so an unattended run can call it without being
able to fail on it; `field_sheet: FAILED ...` means nothing was written.

This file is committed to a public repo. No company names, no sample values.
"""
import html
import json
import os
import re
import sys
import tempfile
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SCRIPT_DIR)
DATA_REL = "tailored/{stem}_data.json"
PROFILE_REL = "pipeline/application_profile.json"
PDF_FOLDERS = ("tailored/apply_now", "tailored")  # rotate_apply_folder.py moves them back out

NEEDS = "NEEDS_ANEESH"   # the profile's "never supplied" sentinel
PRESENT = "PRESENT"
MARK = ">>>"
FENCE_OVER = 100         # a longer value, or any multi-line one, gets a fenced block

START, MY_INFO, WORK, EDUCATION, SKILLS, WEBSITES, ONLY_YOU = (
    "Start", "My information", "Work experience", "Education", "Skills", "Websites", "Only you")
CURRENT = "I currently work here"

# (label, profile block, key, optional). An optional field is left off when blank;
# every other one is always on the sheet, flagged when the profile doesn't hold it.
MY_INFO_FIELDS = (
    ("First Name", "legal_name", "first", False),
    ("Last Name", "legal_name", "last", False),
    ("Address Line 1", "contact", "address_line_1", False),
    ("Address Line 2", "contact", "address_line_2", True),
    ("City", "contact", "city", False),
    ("State", "contact", "state", False),
    ("Postal Code", "contact", "postal_code", False),
    ("Country", "contact", "country", False),
    ("Email", "contact", "email", False),
    ("Phone Device Type", "contact", "phone_type", False),
    ("Country Phone Code", "contact", "phone_country_code", False),
    ("Phone Number", "contact", "phone", False),
)
WEBSITE_FIELDS = (
    ("LinkedIn", "contact", "linkedin", False),
    ("GitHub", "contact", "github", True),
)

# His alone, per the skill. The profile's own list is used when it has one; each
# default below is added only when no question there covers its subject, so the five
# the skill names are on every sheet whatever the profile says.
SCREENING_KEY = "screening_questions_are_aneesh_only"
SCREENING = (
    (r"authoriz", "Are you legally authorized to work in the United States?"),
    (r"sponsor", "Will you now or in the future require sponsorship?"),
    (r"salary|compensation", "Desired salary / compensation expectations"),
    (r"start date", "Earliest start date"),
    (r"schedule|on-site|onsite|hybrid", "Willing to work the stated on-site or hybrid schedule?"),
    (r"\bwhy\b", 'Any free-text "why this company" box'),
)
SELF_ID = ("Gender", "Race / ethnicity", "Veteran status", "Disability")

NOTES = {
    START: "Upload the resume first and let the form parse it. Correcting prefilled entries "
           "from the sections below is faster than typing them from scratch.",
    SKILLS: "One line per category, in this resume's order. Add them one at a time if the "
            "form wants single skills.",
    ONLY_YOU: "Listed so none of them surprises you mid-form. They're blank on purpose and "
              "nothing fills them in for you.",
}
REVIEW = ("Before you submit, check the two things form parsers get wrong most often: "
          "employment dates (months dropped, years shifted) and long role descriptions "
          "(cut off at a character cap, sometimes mid-sentence).")


USAGE = "usage: field_sheet.py <stem> [--out DIR] [--repo PATH] [--strict]"


class Failure(Exception):
    """An expected reason to write nothing: a missing or unusable input."""


def field(label, value="", needs_you=None):
    value = value or ""
    return {"label": label, "value": value,
            "needs_you": (not value) if needs_you is None else needs_you}


def section(title, fields, personal=False):
    return {"title": title, "personal": personal, "fields": fields}


def clean(s):
    """Resume text as a form wants it. The JSON is written for the PDF renderer, so
    it carries <b> tags and entities (&amp;, &ndash;, &nbsp;) that must not be pasted."""
    s = re.sub(r"</?[A-Za-z][^<>]*>", "", str(s or ""))
    return " ".join(html.unescape(s).replace("\xa0", " ").split())


def supplied(v):
    """A profile value as text, or "" when it was never supplied."""
    if v is None or isinstance(v, (dict, list, bool)):
        return ""
    s = str(v).strip()
    return "" if NEEDS in s else s


def norm(s):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", clean(s).casefold()).split())


def split_dated(raw):
    """'Name  |  date range' -> (name, date text). No pipe means no date was given."""
    head, sep, tail = str(raw or "").rpartition("|")
    return (clean(head), clean(tail)) if sep else (clean(tail), "")


def resume_span(text):
    """(start year, end year or PRESENT) as the resume states them, "" for whatever
    it doesn't. Years only: a month name here is deliberately not read."""
    text = re.sub(r"\([^)]*\)", " ", text)  # "(Acquired by ...)" can carry a year of its own
    marks = [m if m.isdigit() else PRESENT for m in
             re.findall(r"\b(?:19|20)\d{2}\b|\b(?:present|current)\b", text, flags=re.I)]
    if not marks or len(marks) > 2 or marks[0] == PRESENT:
        return "", ""
    return marks[0], marks[1] if len(marks) == 2 else ""


def profile_date(raw):
    """(month, year) from a profile date, each "" when the profile doesn't hold it:
    'NEEDS_ANEESH/2021' is ("", "2021"). The year is PRESENT for a current job."""
    s = str(raw or "").strip()
    if s.casefold() in ("present", "current"):
        return "", PRESENT
    m = re.fullmatch(r"(\d{1,2})/(\d{4})", s)
    if m and 1 <= int(m.group(1)) <= 12:
        return f"{int(m.group(1)):02d}", m.group(2)
    m = re.fullmatch(r"(?:[^/]*/)?(\d{4})", s)
    return ("", m.group(1)) if m else ("", "")


def date_field(label, prof, resume_year):
    """One From/To field. The month comes from the profile or stays MM. The year may
    come from either file, and when both state one and they differ, neither is used."""
    month, year = prof
    if year and resume_year and year != resume_year:
        return field(f"{label} (profile and resume disagree)", "MM/YYYY", True)
    year = year or resume_year
    if year == PRESENT:
        return field(CURRENT, "Yes")
    return field(label, f"{month or 'MM'}/{year or 'YYYY'}", not (month and year))


def year_field(label, prof_year, resume_year):
    if prof_year and resume_year and prof_year != resume_year:
        return field(f"{label} (profile and resume disagree)", "", True)
    return field(label, prof_year or resume_year)


def title_keys(s):
    return ({norm(part) for part in clean(s).split("/")} | {norm(s)}) - {""}


def find_employment(title, company, employment):
    """The one profile entry for this resume role, or None. Never a best guess; see
    the module docstring for the rule and for why a miss is the cheap direction."""
    rows = [p for p in employment or [] if isinstance(p, dict)]
    want = title_keys(title)
    full, base, bare = norm(company), norm(company.split("(")[0]), "(" not in company

    def titled(p):
        return bool(want & title_keys(p.get("title")))

    def named(p):
        return clean(p.get("company"))

    exact = [p for p in rows if full and norm(named(p)) == full and titled(p)]
    if exact:
        return exact[0] if len(exact) == 1 else None
    loose = [p for p in rows if base and norm(named(p).split("(")[0]) == base
             and (bare or "(" not in named(p)) and titled(p)]
    return loose[0] if len(loose) == 1 else None


def role_section(n, total, role, employment):
    title = clean(role.get("title"))
    company, when = split_dated(role.get("company"))
    r_start, r_end = resume_span(when)
    p = find_employment(title, company, employment) or {}
    start = profile_date(p.get("start"))
    start = ("", "") if start[1] == PRESENT else start
    end = ("", PRESENT) if p.get("current") is True else profile_date(p.get("end"))
    frm, to = date_field("From", start, r_start), date_field("To", end, r_end)
    bullets = [clean(b) for b in role.get("bullets") or [] if isinstance(b, str)]
    fields = [field("Job Title", supplied(p.get("title")) or title),
              field("Company", supplied(p.get("company")) or company),
              field("Location", supplied(p.get("location")))]
    fields += [to, frm] if to["label"] == CURRENT else [frm, to]  # the form's order: tick, then From
    fields.append(field("Role Description", "\n".join(b for b in bullets if b)))
    return section(f"{WORK} {n} of {total}", fields)


def education_section(n, total, edu, profile_edu):
    school, when = split_dated(edu.get("school"))
    first, last = resume_span(when)
    r_from, r_to = (first, last) if last else ("", first)  # a lone year is the graduation year
    hits = [p for p in profile_edu or [] if isinstance(p, dict)
            and norm(school) and norm(p.get("school")) == norm(school)]
    p = hits[0] if len(hits) == 1 else {}
    fields = [field("School", supplied(p.get("school")) or school),
              field("Degree", supplied(p.get("degree")) or clean(edu.get("degree"))),
              field("Field of Study", supplied(p.get("field"))),
              year_field("From", supplied(p.get("start_year")), r_from),
              year_field("To", supplied(p.get("end_year")), "" if r_to == PRESENT else r_to)]
    gpa = p.get("gpa")
    if supplied(gpa) or NEEDS in str(gpa or ""):  # optional: blank in the profile means leave it off
        fields.append(field("Overall Result / GPA", supplied(gpa)))
    return section(EDUCATION if total == 1 else f"{EDUCATION} {n} of {total}", fields)


def skill_fields(skills):
    """One field per skills line: the renderer's '<b>Category:</b> items', or the
    {category: items} dict a few older files carry."""
    pairs = []
    if isinstance(skills, dict):
        pairs = list(skills.items())
    elif isinstance(skills, list):
        for line in skills:
            m = re.match(r"\s*<b>(.*?)</b>\s*:?\s*(.*)", str(line), re.S)
            pairs.append((m.group(1), m.group(2)) if m else (SKILLS, line))
    out = []
    for label, items in pairs:
        value = ", ".join(clean(i) for i in items) if isinstance(items, list) else clean(items)
        if value:
            out.append(field(clean(label).rstrip(": ") or SKILLS, value))
    return out


def profile_fields(profile, spec):
    out = []
    for label, block, key, optional in spec:
        raw = profile[block].get(key) if isinstance(profile.get(block), dict) else None
        if optional and not supplied(raw) and NEEDS not in str(raw or ""):
            continue
        out.append(field(label, supplied(raw)))
    return out


def only_you_fields(profile):
    asked = profile.get(SCREENING_KEY)
    asked = [q.strip() for q in asked if isinstance(q, str) and q.strip()] if isinstance(asked, list) else []
    for pattern, wording in SCREENING:
        if not any(re.search(pattern, q, re.I) for q in asked):
            asked.append(wording)
    return ([field(q, "", True) for q in asked]
            + [field(f"{s} (self-identification)", "", True) for s in SELF_ID])


def find_pdf(repo, stem, suffixes):
    for suffix in suffixes:
        for folder in PDF_FOLDERS:
            rel = f"{folder}/{stem}{suffix}"
            if os.path.isfile(os.path.join(repo, rel)):
                return rel
    return ""


def start_fields(repo, stem):
    resume = find_pdf(repo, stem, ("_ATS.pdf", ".pdf"))  # the parser-friendly variant first
    cover = find_pdf(repo, stem, ("_cover.pdf",))
    out = [field("Resume to upload" if resume else "Resume to upload (no rendered PDF found)", resume)]
    if cover:
        out.append(field("Cover letter, if the form takes a second file", cover))
    return out


def load(repo, rel):
    try:
        with open(os.path.join(repo, rel), encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise Failure(f"no {rel} under {repo}") from None
    except json.JSONDecodeError as e:
        raise Failure(f"{rel} is not valid JSON (line {e.lineno})") from None
    if not isinstance(data, dict):
        raise Failure(f"{rel} must be a JSON object")
    return data


def build(stem, repo, now):
    data = load(repo, DATA_REL.format(stem=stem))
    profile = load(repo, PROFILE_REL)
    roles = [r for r in data.get("experience") or [] if isinstance(r, dict)]
    if not roles:
        raise Failure(f"{DATA_REL.format(stem=stem)} has no experience entries")
    edu = data.get("education")
    edu = [e for e in (edu if isinstance(edu, list) else [edu]) if isinstance(e, dict)]
    sections = [section(START, start_fields(repo, stem)),
                section(MY_INFO, profile_fields(profile, MY_INFO_FIELDS), personal=True)]
    sections += [role_section(i, len(roles), r, profile.get("employment"))   # resume order: newest first
                 for i, r in enumerate(roles, 1)]
    sections += [education_section(i, len(edu), e, profile.get("education")) for i, e in enumerate(edu, 1)]
    sections += [section(SKILLS, skill_fields(data.get("skills"))),
                 section(WEBSITES, profile_fields(profile, WEBSITE_FIELDS), personal=True),
                 section(ONLY_YOU, only_you_fields(profile))]
    return {"stem": stem, "generated": now.isoformat(timespec="seconds"),
            "sections": [s for s in sections if s["fields"]]}


def backtick_run(s):
    return max((len(r) for r in re.findall(r"`+", s)), default=0)


def code(value):
    """An inline code span that survives backticks in the value: CommonMark closes a
    span only on a run of the same length, and strips one space of padding."""
    ticks = "`" * (backtick_run(value) + 1)
    pad = " " if value.startswith("`") or value.endswith("`") else ""
    return f"{ticks}{pad}{value}{pad}{ticks}"


def md_text(s):
    """Label text with markdown's own characters escaped. Values never pass through
    here: they sit in code, so what he selects is exactly what the JSON holds."""
    return re.sub(r"([\\`*_\[\]<>|~]|&(?=#?\w+;))", r"\\\1", s)


def md_field(f):
    label = md_text(f["label"])
    head = (f"- `{MARK}` " if f["needs_you"] else "- ") + f"**{label}{'' if label.endswith('?') else ':'}**"
    value = f["value"]
    if not value:
        return [head]
    if "\n" in value or len(value) > FENCE_OVER:
        fence = "`" * max(3, backtick_run(value) + 1)
        return [head, "", fence, *value.split("\n"), fence, ""]
    return [f"{head} {code(value)}"]


def render_md(sheet):
    lines = [f"# Field sheet: {code(sheet['stem'])}", "",
             f"Generated {sheet['generated']} by `pipeline/field_sheet.py` from this package's resume",
             "JSON and the application profile. A script wrote it, so every value below is copied",
             "from one of those two files.", "",
             f"Sections follow the form's own order. `{MARK}` marks something only you can answer;",
             "those are blank on purpose. A month the profile doesn't hold stays `MM`: fill it from",
             "memory, then add it to the profile so the next sheet has it."]
    blanks = []

    def block(*new):
        if lines[-1] != "":
            lines.append("")
        lines.extend(new)

    # No tables anywhere: a pipe in a value would need escaping there, and an escaped
    # value is no longer the text he pastes.
    for n, s in enumerate(sheet["sections"], 1):
        block("---", "", f"## {n}. {md_text(s['title'])}", "")
        if s["title"] in NOTES:
            lines.extend([NOTES[s["title"]], ""])
        for f in s["fields"]:
            lines.extend(md_field(f))
            if f["needs_you"] and s["title"] != ONLY_YOU:
                blanks.append(f"- {n}. {md_text(s['title'])}: {md_text(f['label'])}"
                              + (f" {code(f['value'])}" if f["value"] else ""))
    if blanks:
        block("Also yours, flagged in the sections above:", "", *blanks)
    block("---", "", REVIEW)
    return "\n".join(lines) + "\n"


def write_atomic(out, files):
    """Stage every file beside its target, then swap them all in, so a failed write
    leaves the previous sheet whole rather than one new file beside one old one."""
    staged = []
    try:
        for name, text in files.items():
            fd, tmp = tempfile.mkstemp(prefix=".field_sheet.", suffix=".tmp", dir=out)
            staged.append((tmp, os.path.join(out, name)))
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
        for tmp, path in staged:
            os.replace(tmp, path)
    finally:
        for tmp, _ in staged:
            if os.path.exists(tmp):
                os.remove(tmp)


def parse_args(argv):
    stem, opts = None, {"--out": None, "--repo": REPO}
    args = iter(argv)
    for a in args:
        if a == "--strict":
            continue
        if a in opts:
            opts[a] = next(args, None)
            if not opts[a] or opts[a].startswith("--"):
                raise Failure(f"{a} needs a path")
        elif a.startswith("--") or stem is not None:
            raise Failure(f"unexpected argument {a!r}; {USAGE}")
        else:
            stem = os.path.basename(a)  # a stem names files in two folders; it is never a path
            stem = stem[:-len("_data.json")] if stem.endswith("_data.json") else stem
    if not stem:
        raise Failure(f"no stem given; {USAGE}")
    repo = os.path.abspath(opts["--repo"])
    return stem, repo, opts["--out"] or os.path.join(repo, "tailored")


def main(argv):
    strict = "--strict" in argv
    try:
        stem, repo, out = parse_args(argv)
        sheet = build(stem, repo, datetime.now())
        os.makedirs(out, exist_ok=True)
        write_atomic(out, {f"{stem}_fields.md": render_md(sheet),
                           f"{stem}_fields.json": json.dumps(sheet, ensure_ascii=False, indent=2) + "\n"})
        fields = [f for s in sheet["sections"] for f in s["fields"]]
        print(f"field_sheet: {stem} -> {len(sheet['sections'])} sections, {len(fields)} fields, "
              f"{sum(f['needs_you'] for f in fields)} need you")
        return 0
    except Exception as e:  # noqa: BLE001 - a sheet failure must never fail the run
        reason = str(e) if isinstance(e, Failure) else f"{type(e).__name__}: {e}"
        print(f"field_sheet: FAILED {reason}")
        return 1 if strict else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
