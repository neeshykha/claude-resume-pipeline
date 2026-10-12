"""Unit-check where the resume's phone and email come from (2026-10-12).

Both used to be string literals in pdf_helpers.py and generate_pdf.py, and a
quoted extraction example copied them into daily_task_prompt.md as well. The
renderers now read them from application_profile.json (gitignored) through
pdf_helpers.load_contact.

Three things are pinned. load_contact raises rather than returning a blank or a
placeholder, because a resume with an empty contact line still looks finished.
All three builders put what it returns into the PDF, and write no file when it
raises. And no tracked .py or .md file holds anything shaped like a phone
number or a personal mailbox address, apart from the 555-01xx numbers reserved
for examples, so pasting a real one back in fails here.

No real value appears in this file and none is read from the profile: every
case uses its own fake.
"""
import contextlib, io, json, os, re, subprocess, sys, tempfile
BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
sys.path.insert(0, ROOT)
from pipeline import pdf_helpers
from pypdf import PdfReader

FAKE = {"phone": "555-555-0100", "email": "jane.doe@example.com"}
TMP = tempfile.mkdtemp(prefix="contact_source_")
fails = 0


def check(ok, what):
    global fails
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {what}")


def profile(content, name):
    """Write a throwaway profile and return its path. None means no file at all."""
    path = os.path.join(TMP, name)
    if content is not None:
        with open(path, "w") as f:
            f.write(content if isinstance(content, str) else json.dumps(content))
    return path


# --- load_contact ----------------------------------------------------------
LOAD_CASES = [
    # (profile contents, loads?, why)
    ({"contact": dict(FAKE, city="Atlanta")}, True, "both present, other keys ignored"),
    (None, False, "no profile file, as in a fresh clone or a worktree"),
    ("{not json", False, "profile is not valid JSON"),
    ([1, 2], False, "profile is not an object"),
    ({"legal_name": "x"}, False, "no contact block"),
    ({"contact": {"phone": FAKE["phone"]}}, False, "email key missing"),
    ({"contact": dict(FAKE, phone="  ")}, False, "phone blank"),
    ({"contact": dict(FAKE, phone=None)}, False, "phone null"),
    ({"contact": dict(FAKE, email="NEEDS_ANEESH")}, False, "email never supplied"),
]
for i, (content, want, why) in enumerate(LOAD_CASES):
    try:
        got = pdf_helpers.load_contact(profile(content, f"profile_{i}.json"))
        loaded = True
    except RuntimeError:
        got, loaded = None, False
    check(loaded == want and (not want or got == FAKE),
          f"load_contact {'loads' if want else 'raises'}: {why}")

# --- the builders use it, and stop when it does ----------------------------
RESUME = {
    "summary": "Summary line.",
    "experience": [{"title": "Lead", "company": "Quokka Desk  |  2020 to 2026", "bullets": ["Did a thing."]}],
    "education": {"degree": "Bachelor of Arts", "school": "A University  |  2014"},
    "skills": ["<b>Tools:</b> one, two"],
}
COVER = {"date": "October 12, 2026", "recipient": "Hiring Team", "paragraphs": ["One paragraph."]}
BUILDERS = [
    ("build_resume_pdf", pdf_helpers.build_resume_pdf, RESUME),
    ("build_ats_resume_pdf", pdf_helpers.build_ats_resume_pdf, RESUME),
    ("build_cover_pdf", pdf_helpers.build_cover_pdf, COVER),
]
real_load = pdf_helpers.load_contact
missing = profile(None, "never_written.json")
for name, build, data in BUILDERS:
    out = os.path.join(TMP, f"{name}.pdf")
    pdf_helpers.load_contact = lambda: dict(FAKE)
    with contextlib.redirect_stdout(io.StringIO()):
        build(data, out)
    text = "".join(page.extract_text() for page in PdfReader(out).pages)
    check(FAKE["phone"] in text and FAKE["email"] in text,
          f"{name} prints the phone and email load_contact returns")

    blocked = os.path.join(TMP, f"{name}_blocked.pdf")
    pdf_helpers.load_contact = lambda: real_load(missing)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            build(data, blocked)
        raised = False
    except RuntimeError:
        raised = True
    check(raised and not os.path.exists(blocked),
          f"{name} raises and writes no file when the profile is missing")
pdf_helpers.load_contact = real_load

# --- nothing personal in the published code and docs -----------------------
PHONE = re.compile(r"(?<![\w.-])(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}(?![\w-])")
EXAMPLE_PHONE = re.compile(r"555[-. ]01\d\d$")
MAILBOX = re.compile(
    r"[A-Za-z0-9._%+-]+@(?:gmail|googlemail|icloud|me|mac|outlook|hotmail|live|msn|yahoo|"
    r"aol|proton|protonmail|pm|fastmail|hey)\.[A-Za-z.]{2,}", re.I)

listing = subprocess.run(["git", "-C", ROOT, "ls-files", "*.py", "*.md"],
                         capture_output=True, text=True)
tracked = listing.stdout.split()
check(listing.returncode == 0 and len(tracked) > 10, f"git lists the tracked .py and .md files ({len(tracked)})")
hits = []
for rel in tracked:
    with open(os.path.join(ROOT, rel), errors="replace") as f:
        for n, line in enumerate(f, 1):
            if any(not EXAMPLE_PHONE.search(m) for m in PHONE.findall(line)):
                hits.append(f"{rel}:{n} phone-shaped")
            if MAILBOX.search(line):
                hits.append(f"{rel}:{n} personal mailbox address")
# Locations only: the point of the check is that the value itself is not repeated.
check(not hits, f"no phone number or personal mailbox address in tracked code or docs: {hits or 'none'}")

print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
sys.exit(1 if fails else 0)
