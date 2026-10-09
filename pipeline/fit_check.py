#!/usr/bin/env python3
"""One fit check per tailored package: every mechanical Step 4 / 4.5 gate in one command.

Usage:
    .venv/bin/python pipeline/fit_check.py --drafted-now Aneesh_Khan_[Company]_[Role]:full [more ...]
    .venv/bin/python pipeline/fit_check.py Aneesh_Khan_[Company]_[Role] [more ...]     # report only
    .venv/bin/python pipeline/fit_check.py --claim Aneesh_Khan_[Company]_[Role] [more ...]
    .venv/bin/python pipeline/fit_check.py --recent 5
    .venv/bin/python pipeline/fit_check.py --recent 15 --resumes

    --drafted-now   assert the current run authored these packages. Only then does this
                    script render: resume and cover PDFs into tailored/apply_now/. Every
                    package named with it carries its tier, STEM:full or STEM:light.
    --ats           also render the _ATS.pdf variant (Workday, Paylocity, Taleo, iCIMS).
    --claim         before a writer is dispatched: exit 1 when a stem already belongs to
                    an earlier package, and print the first free suffix to use instead.
                    Reads the tracker and tailored/, writes nothing.
    --recent N      print the N most recently written cover letters and exit (Step 4-W
                    hands the last five to each writer). With --resumes, print the N most
                    recent resume packages with their tracker stage instead, which is how
                    the orchestrator picks a calibration package without listing tailored/.

A package is named by its stem. Any of its file paths works too; the directory and the
_data.json / _phrases.json / _cover.md / _cover_data.json / .pdf suffix are stripped.

WHY THIS EXISTS
---------------
Measured on the 2026-10-09 run, where five writer subagents each produced one package.
After the first draft each of them looped over the same commands: check_coverage.py,
check_voice.py, two `grep -c` em-dash counts, `wc -w`, two render_pdf.py calls, and a
page count. Between them they made 46 to 101 tool calls each. The writing was a few
percent of the cost; the rest was the whole conversation re-read on every round.

Three things went wrong that a single script fixes:

  1. NOBODY OWNED THE PAGE COUNT. Nothing in pipeline/ counted pages, so each writer
     improvised: `mdls` (reads Spotlight's index, which is not a file check), a throwaway
     pipeline/_pagecount.py written twice in one run, or reading the PDF back in. Two of
     the five never counted at all, and both of those resumes reached tailored/apply_now/
     at three pages.
  2. NOBODY KNEW HOW FAR OVER A DRAFT WAS. All five first-draft resumes rendered to three
     pages. One writer trimmed five times, a few hundred characters at a time, because a
     bare page count says "still three" and nothing about distance. This prints how much
     text spills past the limit and how the draft compares to the sizes that have fit.
  3. `grep -c` COUNTS LINES, NOT DASHES. A paragraph is one line, so three em-dashes in one
     paragraph read as 1. This counts characters, in the text that actually renders.

It adds no new judgment. Coverage matching, the voice arithmetic, the sent stages, and the
renderers are imported from check_coverage.py, check_voice.py, and render_pdf.py, so a
threshold changed there changes here.

WHAT IT CHECKS
--------------
Resume (tailored/<stem>_data.json, tailored/<stem>_phrases.json):
    schema      pdf_helpers.validate_resume_data plus the renderer's required fields
    coverage    JD phrases present, target 80%. Below target prints CHECK, not FAIL:
                a genuine gap is reported, never papered over (Step 4 item 4).
    em-dashes   cap from check_voice.EM_DASH_MAX, counted in the rendered strings
    pages       RESUME_MAX_PAGES after rendering

Cover letter (tailored/<stem>_cover.md, tailored/<stem>_cover_data.json):
    schema      pdf_helpers.validate_cover_data plus the renderer's required fields
    twin        the .md and the JSON carry the same prose. The PDF renders from the JSON
                and the voice gate reads the .md, so an edit made to one of them passes
                every other check while the PDF keeps the old text (Step 4.5 item 3).
    voice       check_voice.check(): contractions, em-dash cap, sentence-length band
    em-dashes   the same cap, counted in the JSON that renders
    pages       COVER_MAX_PAGES after rendering

THE TIER MARKER. This script cannot tell a light-tier package (resume only, by design)
from a full-tier one whose writer died before the letter: both are a resume with no cover
files. So the caller says which it is. STEM:full with no letter is a FAIL; STEM:light
passes on the resume alone. --drafted-now refuses to run without a marker on every
package, because that is the mode whose PASS means "ready to send". A bare stem is fine
in report-only mode, where a missing letter is printed and not judged. One cover file
without the other fails at any tier.

NEVER RENDERS A PACKAGE IT CANNOT SHOW IS THIS RUN'S. A sent PDF is the record of what
the employer received, the same rule check_voice.py enforces for letters. --drafted-now is
an assertion nobody can verify, so two things are checked against it:
  - a package with a tracker row in a sent stage is never re-rendered;
  - a package with ANY tracker row surfaced on an earlier day is never re-rendered. A
    package this run authored cannot have one yet: Step 6 writes tracking after the gate.
Either way the package FAILS on a `claim` line when --drafted-now was asserted, because
the page counts below it would be for the old PDF and a PASS would say otherwise. Rows
are matched on the whole filename and every matching row is read, so a reused stem cannot
hide behind a newer `surfaced` row.

That guard runs after the writer has already overwritten the files, so it only limits the
damage. --claim is the one that prevents it, and it also looks at tailored/ itself:
tracker notes started naming the PDF partway through the archive, so an older package can
have a row that never mentions its stem.

Exit code: 0 when every package passes (or every claim is free), 1 when any gate fails
(or any stem is taken), 2 on a usage error or when the tracker cannot be read in a mode
that depends on it. CHECK and note lines never change the exit code.
"""
import argparse
import contextlib
import csv
import datetime
import glob
import html
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Page limits. The cover limit is CLAUDE.md Step 8 ("under one page"). The resume limit
# was never written down before this script: 137 of the 150 most recent resumes render to
# two pages, and writers had been inferring the limit by counting pages on old PDFs.
# Two pages is a hard limit (Aneesh, 2026-10-09).
RESUME_MAX_PAGES = 2
COVER_MAX_PAGES = 1

COVERAGE_TARGET = 0.80          # Step 4 item 4: 12 of 15

# Size guides, printed as notes and never enforced. Measured 2026-10-09 over the 150 most
# recent packages, on the same flattened text check_coverage.py reads:
#   two-page resumes    137 of them, 685 to 1,261 words, at most 8,422 characters
#   three-page resumes  13 of them, 7,662 characters and up
# The ranges overlap from about 7,650 to 8,400, where bullet count decides it (every
# bullet costs spacing as well as lines). Everything at or under 7,600 fit.
RESUME_CHARS_DRAFT_BUDGET = 7500
# Cover letter body (the paragraphs, no date or sign-off): median 351 words. One page
# holds about 480, so the guide is about length a reader will finish, not about fit.
# A note and never a gate (Aneesh, 2026-10-09).
COVER_WORDS_GUIDE = 370
# A block of the .md outside the letter body longer than this is prose, not a header line.
TWIN_FURNITURE_WORDS = 25

SUFFIXES = ("_cover_data.json", "_cover.md", "_cover.pdf", "_phrases.json",
            "_data.json", "_ATS.pdf", ".pdf")
TIERS = ("full", "light")
PACKAGE_FILES = ("_data.json", "_cover.md", "_cover_data.json")
MD_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!])")


def stem_of(arg):
    name = os.path.basename(arg.rstrip("/"))
    for suffix in SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def split_tier(arg):
    """'Stem:full' -> ('Stem', 'full'); no marker -> ('Stem', None). Raises on a typo."""
    tier = None
    for t in TIERS:
        if arg.endswith(":" + t):
            arg, tier = arg[: -len(t) - 1], t
            break
    stem = stem_of(arg)
    if ":" in stem:
        raise ValueError(f"unknown tier marker in {arg!r}: use :full or :light")
    return stem, tier


def plain(text):
    """The text a reader sees: renderer markup stripped, whitespace collapsed."""
    t = re.sub(r"<br\s*/?>", " ", str(text or ""))
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t).replace(" ", " ")
    return re.sub(r"\s+", " ", t).strip()


def strings_in(value):
    """Every string inside a parsed JSON value."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings_in(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings_in(v)


def em_dashes(value):
    return sum(html.unescape(s).count("—") for s in strings_in(value))


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def tracker_rows(root):
    """Every outcomes.csv row, or None when the tracker cannot be read."""
    try:
        with open(os.path.join(root, "pipeline", "outcomes.csv"), newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except (OSError, ValueError, csv.Error):
        return None


def rows_naming(rows, stem):
    """Tracker rows whose notes name one of this package's PDFs, matched whole.

    Step 6 notes record the pair as "tailored/X.pdf + _cover.pdf". The lookbehind keeps a
    stem from matching inside a longer one, and every match is returned: check_voice's
    stage_of() stops at the first row, which is wrong the day a stem is reused.
    """
    named = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(stem) + r"(?:_cover|_ATS)?\.pdf")
    return [r for r in rows or [] if named.search(r.get("notes") or "")]


def stage(row):
    return (row.get("stage") or "").strip().lower()


def day_of(path):
    return datetime.date.fromtimestamp(os.path.getmtime(path)).isoformat()


def quiet(fn, *args):
    """Run a renderer or checker, returning (result, captured stdout, error text)."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            result = fn(*args)
        return result, buf.getvalue(), None
    except SystemExit as exc:               # render_pdf.py exits on a missing field
        return None, buf.getvalue(), f"exited with status {exc.code}"
    except Exception as exc:                # a failed render is a finding, not a crash
        return None, buf.getvalue(), f"{type(exc).__name__}: {exc}"


def page_report(pdf_path, limit):
    """Return (pages, spill_lines, spill_chars, spill_start). Spill is text past `limit`.

    Raises when the PDF cannot be opened or parsed; check_pages turns that into a FAIL.
    The page count is the gate and the spill is a courtesy, so a page whose text will not
    extract costs the spill figures and keeps the count.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        # reportlab writes one uncompressed "/Type /Page" object per page.
        with open(pdf_path, "rb") as f:
            pages = len(re.findall(rb"/Type\s*/Page(?![s\w])", f.read()))
        return pages, None, None, ""
    reader = PdfReader(pdf_path)
    pages = len(reader.pages)
    try:
        lines = []
        for page in reader.pages[limit:]:
            lines += [ln.strip() for ln in (page.extract_text() or "").splitlines() if ln.strip()]
    except Exception:
        return pages, None, None, ""
    return pages, len(lines), sum(len(ln) for ln in lines), (lines[0][:70] if lines else "")


def find_pdf(root, name):
    for folder in ("tailored/apply_now", "tailored"):
        path = os.path.join(root, folder, name)
        if os.path.exists(path):
            return path
    return None


class Report:
    def __init__(self):
        self.lines = []
        self.failed = []

    def _add(self, mark, label, text):
        self.lines.append(f"  [{mark:<5}] {label:<10}{text}".rstrip())

    def ok(self, label, text=""):
        self._add("ok", label, text)

    def fail(self, label, text):
        self._add("FAIL", label, text)
        self.failed.append(label)

    def check(self, label, text):
        self._add("CHECK", label, text)

    def note(self, label, text):
        self._add("note", label, text)

    def head(self, text):
        self.lines.append(text)


def check_pages(rep, label, pdf_path, limit, rel):
    """Report the page count against `limit`. Returns True when it fits."""
    try:
        pages, spill_lines, spill_chars, start = page_report(pdf_path, limit)
    except Exception as exc:                # one unreadable PDF must not end the batch
        rep.fail(label, f"render/parse failed: {type(exc).__name__}: {exc}  {rel}")
        return False
    if pages < 1:
        rep.fail(label, f"render/parse failed: no pages found in {rel}")
        return False
    if pages <= limit:
        rep.ok(label, f"{pages} (limit {limit})  {rel}")
        return True
    if not spill_lines:
        rep.fail(label, f"{pages} (limit {limit})  {rel}")
        return False
    rep.fail(label, f"{pages} (limit {limit}): {spill_lines} lines / {spill_chars} characters "
                    f"spill past page {limit}, starting \"{start}\". Cut at least half again "
                    f"that much in ONE pass; a cut the exact size of the spill usually leaves a line behind.")
    return False


def check_resume(rep, mods, root, stem, render, ats):
    check_coverage, check_voice, render_pdf, pdf_helpers = mods
    data_path = os.path.join(root, "tailored", stem + "_data.json")
    phrases_path = os.path.join(root, "tailored", stem + "_phrases.json")
    rep.head(" resume")
    if not os.path.exists(data_path):
        rep.fail("schema", f"missing tailored/{stem}_data.json")
        return
    try:
        data = load_json(data_path)
        pdf_helpers.validate_resume_data(data, data_path)
        missing = [k for k in ("summary", "experience", "education", "skills") if k not in data]
        if missing:
            raise ValueError(f"missing required field(s): {', '.join(missing)}")
    except (ValueError, OSError) as exc:
        rep.fail("schema", " ".join(str(exc).split()))
        return
    rep.ok("schema", "")

    text = check_coverage.resume_text_from_data(data)
    try:
        phrases = load_json(phrases_path)
        if not isinstance(phrases, list) or not phrases:
            raise ValueError("phrases file must be a non-empty JSON list")
    except (ValueError, OSError) as exc:
        rep.fail("coverage", f"cannot read tailored/{stem}_phrases.json ({type(exc).__name__}); "
                             f"the coverage gate did not run")
    else:
        haystack = text.lower()
        missing = [str(p) for p in phrases if str(p).lower() not in haystack]
        hits, total = len(phrases) - len(missing), len(phrases)
        summary = f"{hits}/{total} ({round(100 * hits / total)}%)"
        if hits / total >= COVERAGE_TARGET:
            rep.ok("coverage", summary + (f"  missing: {' | '.join(missing)}" if missing else ""))
        else:
            rep.check("coverage", f"{summary}, target {round(COVERAGE_TARGET * 100)}%. missing: "
                                  f"{' | '.join(missing)}. Apply the second-pass rule once; "
                                  f"report what is left as genuine gaps. Never fabricate.")

    cap = check_voice.EM_DASH_MAX
    dashes = em_dashes(data)
    (rep.ok if dashes <= cap else rep.fail)("em-dashes", f"{dashes} (cap {cap})")

    bullets = sum(len(job.get("bullets") or []) for job in data.get("experience") or [])
    chars, words = len(text), len(text.split())
    size = f"{words} words / {chars} characters / {bullets} bullets"

    pdf_rel = f"tailored/apply_now/{stem}.pdf"
    if render:
        _, _, err = quiet(render_pdf.render_resume, data_path, os.path.join(root, pdf_rel))
        if err:
            rep.fail("pages", f"render failed: {err}")
            return
        pdf_path = os.path.join(root, pdf_rel)
    else:
        pdf_path = find_pdf(root, stem + ".pdf")
        if not pdf_path:
            rep.note("pages", "no PDF found and nothing rendered (report only)")
            rep.note("size", size)
            return
        pdf_rel = os.path.relpath(pdf_path, root)
        if os.path.getmtime(pdf_path) + 1 < os.path.getmtime(data_path):
            rep.note("pages", "the PDF is older than its JSON; the count below is for the old text")
    fits = check_pages(rep, "pages", pdf_path, RESUME_MAX_PAGES, pdf_rel)
    if not fits and chars > RESUME_CHARS_DRAFT_BUDGET:
        size += (f". Every recent resume at or under {RESUME_CHARS_DRAFT_BUDGET} characters fit "
                 f"{RESUME_MAX_PAGES} pages; this one is {chars - RESUME_CHARS_DRAFT_BUDGET} over that")
    rep.note("size", size)

    if ats and render:
        ats_rel = f"tailored/apply_now/{stem}_ATS.pdf"
        _, _, err = quiet(render_pdf.render_ats, data_path, os.path.join(root, ats_rel))
        if err:
            rep.fail("ats", f"render failed: {err}")
            return
        try:
            pages = page_report(os.path.join(root, ats_rel), 99)[0]
        except Exception as exc:
            rep.fail("ats", f"render/parse failed: {type(exc).__name__}: {exc}  {ats_rel}")
        else:
            rep.note("ats", f"{pages} pages  {ats_rel}")


def check_cover(rep, mods, root, stem, tier, render):
    check_coverage, check_voice, render_pdf, pdf_helpers = mods
    md_path = os.path.join(root, "tailored", stem + "_cover.md")
    json_path = os.path.join(root, "tailored", stem + "_cover_data.json")
    have_md, have_json = os.path.exists(md_path), os.path.exists(json_path)
    if not have_md and not have_json:
        if tier == "full":
            rep.head(" cover")
            rep.fail("schema", f"full tier, but tailored/{stem}_cover.md and _cover_data.json "
                               f"do not exist: the letter was never written")
        elif tier == "light":
            rep.head(" cover     none (light tier: resume only)")
        else:
            rep.head(" cover     none (no tier given, so not judged)")
        return
    rep.head(" cover")
    if tier == "light":
        rep.note("tier", "marked light, but letter files exist; checked anyway")
    if not (have_md and have_json):
        gone = "_cover.md" if have_json else "_cover_data.json"
        rep.fail("schema", f"missing tailored/{stem}{gone}; a cover letter is both files")
        return
    try:
        data = load_json(json_path)
        pdf_helpers.validate_cover_data(data, json_path)
        missing = [k for k in ("date", "recipient", "paragraphs") if k not in data]
        if missing:
            raise ValueError(f"missing required field(s): {', '.join(missing)}")
    except (ValueError, OSError) as exc:
        rep.fail("schema", " ".join(str(exc).split()))
        return
    rep.ok("schema", "")

    # Twin check, paragraph by paragraph. Every JSON paragraph must equal one blank-line-
    # separated block of the .md, and the .md may hold nothing else between its first and
    # last matching block. What sits above and below (date, recipient, a title line, the
    # sign-off) is furniture and varies across the archive, so only a paragraph-sized
    # block out there is treated as prose the JSON is missing.
    # Markdown escapes come off the .md side too: a writer that types sf\_caseops\_mcp in
    # the .md and the bare name in the JSON has written the same prose, and a twin FAIL
    # over an invisible backslash is two fix rounds spent finding it.
    paragraphs = [plain(p) for p in data.get("paragraphs") or []]
    try:
        with open(md_path, encoding="utf-8") as f:
            blocks = [plain(MD_ESCAPE.sub(r"\1", b.replace("**", "")))
                      for b in re.split(r"\n\s*\n", f.read())]
    except (OSError, ValueError) as exc:
        rep.fail("twin", f"cannot read tailored/{stem}_cover.md ({type(exc).__name__}: {exc})")
    else:
        blocks = [b for b in blocks if b]
        wanted = set(paragraphs)
        absent = [i + 1 for i, p in enumerate(paragraphs) if p not in blocks]
        matched = [i for i, b in enumerate(blocks) if b in wanted]
        extra = []
        if matched:
            extra = [b for i, b in enumerate(blocks) if b not in wanted
                     and (matched[0] < i < matched[-1] or len(b.split()) > TWIN_FURNITURE_WORDS)]
        if absent:
            rep.fail("twin", f"paragraph(s) {', '.join(map(str, absent))} of _cover_data.json do not match "
                             f"a paragraph of _cover.md word for word. The PDF renders from the JSON "
                             f"and the voice gate reads the .md. Make them identical.")
        elif extra:
            rep.fail("twin", f"_cover.md has a paragraph the JSON lacks, starting "
                             f"\"{' '.join(extra[0].split()[:8])}\". The PDF renders from the JSON.")
        else:
            rep.ok("twin", "_cover.md and _cover_data.json carry the same prose")

    passed, out, err = quiet(check_voice.check, md_path, render)
    voice_lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    detail = "  ".join(voice_lines[1:]) if len(voice_lines) > 1 else "  ".join(voice_lines)
    if err:
        rep.fail("voice", f"check_voice.py failed: {err}")
    elif passed:
        rep.ok("voice", detail)
    else:
        rep.fail("voice", detail)

    cap = check_voice.EM_DASH_MAX
    dashes = em_dashes(data)
    (rep.ok if dashes <= cap else rep.fail)("em-dashes", f"{dashes} in the JSON that renders (cap {cap})")

    pdf_rel = f"tailored/apply_now/{stem}_cover.pdf"
    if render:
        _, _, err = quiet(render_pdf.render_cover, json_path, os.path.join(root, pdf_rel))
        if err:
            rep.fail("pages", f"render failed: {err}")
            return
        pdf_path = os.path.join(root, pdf_rel)
    else:
        pdf_path = find_pdf(root, stem + "_cover.pdf")
        if pdf_path:
            pdf_rel = os.path.relpath(pdf_path, root)
            if os.path.getmtime(pdf_path) + 1 < os.path.getmtime(json_path):
                rep.note("pages", "the PDF is older than its JSON; the count below is for the old text")
    if pdf_path:
        check_pages(rep, "pages", pdf_path, COVER_MAX_PAGES, pdf_rel)
    else:
        rep.note("pages", "no PDF found and nothing rendered (report only)")
    words = sum(len(p.split()) for p in paragraphs)
    size = f"body {words} words in {len(paragraphs)} paragraphs"
    if words > COVER_WORDS_GUIDE:
        size += f" (guide {COVER_WORDS_GUIDE}; a note, not a gate)"
    rep.note("size", size)


def print_recent(root, count, resumes, rows):
    """--recent: newest letters, or with --resumes the newest resume packages."""
    if not resumes:
        # The ramp-sentence rule (CLAUDE.md Step 8) checks a new letter against the last
        # five. tailored/ holds 2,000+ files, so listing it to find them costs more than
        # the letters do. Absolute paths: they go straight into a writer's prompt.
        letters = sorted(glob.glob(os.path.join(root, "tailored", "*_cover.md")),
                         key=os.path.getmtime, reverse=True)[:count]
        for path in letters:
            print(f"{day_of(path)}  {os.path.abspath(path)}")
        return 0
    # Calibration candidates. The stage column says which were sent, the role is in the
    # stem, and "apply_now" marks a PDF still waiting in the apply folder.
    found = [p for p in glob.glob(os.path.join(root, "tailored", "*_data.json"))
             if not p.endswith("_cover_data.json")]
    for path in sorted(found, key=os.path.getmtime, reverse=True)[:count]:
        stem = stem_of(path)
        stages = [stage(r) for r in rows_naming(rows, stem)]
        marks = [f"stage={stages[-1]}" if stages else "stage=no row"]
        if os.path.exists(os.path.join(root, "tailored", stem + "_cover.md")):
            marks.append("letter")
        if os.path.exists(os.path.join(root, "tailored", "apply_now", stem + ".pdf")):
            marks.append("apply_now")
        print(f"{day_of(path)}  {', '.join(marks):<34}  {os.path.abspath(path)}")
    return 0


def claim(root, stems, rows, today):
    """--claim: say whether each stem is free for a new package. Writes nothing."""
    def taken_by(stem):
        named = rows_naming(rows, stem)
        if named:
            row = named[0]
            return (f"outcomes.csv already names {stem}.pdf (stage={stage(row) or 'blank'}, "
                    f"surfaced {(row.get('surfaced_date') or '').strip() or 'date not recorded'})")
        for suffix in PACKAGE_FILES:
            path = os.path.join(root, "tailored", stem + suffix)
            if os.path.exists(path) and day_of(path) != today:
                return f"tailored/{stem}{suffix} was written {day_of(path)}, before this run"
        return None

    taken = 0
    for stem in stems:
        why = taken_by(stem)
        if not why:
            print(f"free   {stem}")
            continue
        taken += 1
        # A stem that is already a suffixed one counts on from its own number, so the
        # third package for a role is _3 and not _2_2.
        numbered = re.fullmatch(r"(.+)_(\d+)", stem)
        base, n = (numbered.group(1), int(numbered.group(2)) + 1) if numbered else (stem, 2)
        while taken_by(f"{base}_{n}"):
            n += 1
        print(f"TAKEN  {stem}: {why}. Use {base}_{n} instead; that one is free.")
    print(f"CLAIM: {len(stems) - taken} free, {taken} taken")
    return 1 if taken else 0


def main():
    ap = argparse.ArgumentParser(description="Run every mechanical tailoring gate for one or more packages.")
    ap.add_argument("packages", nargs="*",
                    help="package stem(s), e.g. Aneesh_Khan_Acme_TAM, with :full or :light "
                         "appended under --drafted-now")
    ap.add_argument("--drafted-now", action="store_true",
                    help="assert this run authored the packages: render their PDFs and treat "
                         "their letters as editable")
    ap.add_argument("--ats", action="store_true", help="also render the _ATS.pdf variant")
    ap.add_argument("--claim", action="store_true",
                    help="exit 1 when a stem already belongs to an earlier package")
    ap.add_argument("--recent", type=int, metavar="N",
                    help="print the N most recently written cover letters and exit")
    ap.add_argument("--resumes", action="store_true",
                    help="with --recent: list resume packages and their tracker stage instead")
    ap.add_argument("--root", default=os.path.dirname(HERE), help=argparse.SUPPRESS)
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    rows = tracker_rows(root)
    today = datetime.date.today().isoformat()
    if args.claim and args.drafted_now:
        ap.error("--claim runs before a writer is dispatched and --drafted-now after it "
                 "returns; use one at a time")
    listing = args.recent and args.resumes
    if (args.claim or args.drafted_now or listing) and rows is None:
        # These modes exist to keep an earlier package from being overwritten or mistaken
        # for an untracked one, and the tracker is how an earlier package is recognised.
        # Without it, do nothing. This is the only exit 2 that is not a usage message.
        print("fit_check: cannot read pipeline/outcomes.csv, so a new package cannot be told "
              "from one already sent. Nothing checked, nothing rendered.", file=sys.stderr)
        return 2
    if args.recent:
        return print_recent(root, args.recent, args.resumes, rows)
    if not args.packages:
        ap.error("name at least one package, or use --recent N")
    if args.claim:
        # A tier marker means nothing to a claim. Drop whatever follows a colon rather
        # than fail on a typo: exit 2 here would read as "tracker unreadable" and stop
        # the morning's tailoring over a stray character.
        return claim(root, [stem_of(arg.split(":")[0]) for arg in args.packages], rows, today)
    try:
        packages = [split_tier(arg) for arg in args.packages]
    except ValueError as exc:
        ap.error(str(exc))
    if args.drafted_now:
        bare = [stem for stem, tier in packages if not tier]
        if bare:
            ap.error("--drafted-now needs the tier on every package, STEM:full or STEM:light "
                     "(a missing letter is a failure on one and correct on the other): "
                     + ", ".join(bare))

    sys.path.insert(0, os.path.join(root, "pipeline"))
    import check_coverage
    import check_voice
    import pdf_helpers
    import render_pdf
    mods = (check_coverage, check_voice, render_pdf, pdf_helpers)

    results = []
    for stem, tier in packages:
        named = rows_naming(rows, stem)
        sent = sorted({stage(r) for r in named} & set(check_voice.SENT_STAGES))
        older = sorted({(r.get("surfaced_date") or "").strip() or "date not recorded"
                        for r in named if (r.get("surfaced_date") or "").strip() != today})
        refusal = None
        if sent:
            label = f"[stage={'/'.join(sent)}: ALREADY SENT. Report only, nothing rendered. Do not edit.]"
            refusal = f"the tracker has this package at stage={'/'.join(sent)}"
        elif args.drafted_now and older:
            label = (f"[tracker row surfaced {', '.join(older)}: NOT this run's package. "
                     f"Report only, nothing rendered. Do not edit.]")
            refusal = f"the tracker already has a row for this stem, surfaced {', '.join(older)}"
        elif args.drafted_now:
            label = f"[drafted this run, {tier} tier]"
        else:
            label = "[report only, nothing rendered]"
        render = args.drafted_now and not refusal
        rep = Report()
        rep.head(f"== {stem}  {label}")
        if args.drafted_now and refusal:
            rep.fail("claim", f"--drafted-now was asserted, but {refusal}. Nothing was rendered, "
                              f"so the page counts below are for the PDF already on disk. If a "
                              f"writer just wrote to this stem, it overwrote an earlier package: "
                              f"say so in the digest and ask Aneesh; do not fix it yourself.")
        try:
            if render:
                os.makedirs(os.path.join(root, "tailored", "apply_now"), exist_ok=True)
            check_resume(rep, mods, root, stem, render, args.ats)
            check_cover(rep, mods, root, stem, tier, render)
        except Exception as exc:            # one broken package must not end the batch
            rep.fail("crash", f"{type(exc).__name__}: {exc}. The checks after this point did "
                              f"not run for this package.")
        verdict = "FAIL (" + ", ".join(dict.fromkeys(rep.failed)) + ")" if rep.failed else "PASS"
        rep.head(f" RESULT {stem}: {verdict}")
        print("\n".join(rep.lines))
        print()
        results.append((stem, not rep.failed))

    failed = [s for s, good in results if not good]
    print(f"FIT CHECK: {len(results) - len(failed)} pass, {len(failed)} fail"
          + (f"  ->  {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
