#!/usr/bin/env python3
"""Transcript-triggered post-mortem drafts: plan, classify, apply, post, skip, list.

A Wispr Flow meeting that looks like one of Aneesh's interviews becomes a drafted post-mortem
in interview_prep/<Company>/ plus one line in Discord #follow-ups saying it is ready to grade.
The routine's Claude does the reading (Wispr MCP) and the drafting; this script owns everything
that has to be deterministic: the handled ledger (nothing is drafted twice), the company and
round inference, the no-overwrite rule (a file already on disk is never replaced, edited or
not), the draft's shape check, and the post.

Why it exists (D44, 2026-10-23 and 2026-10-26): the Global-e hiring-manager round was debriefed
from its Wispr transcript in about ten minutes of grading instead of a 45-minute recall walk, and
the grading was exact because the transcript was. The recording is the trigger the interview
loop never had: no mail, no calendar, no scan has ever seen a round happen; the transcript proves
it did.

Usage (from the repo root, the way the routine runs it):
    .venv/bin/python pipeline/postmortem_draft.py plan
    .venv/bin/python pipeline/postmortem_draft.py classify <meetings.json>
    .venv/bin/python pipeline/postmortem_draft.py apply <draft.md> --meeting-id <id>
        [--transcript <file>] [--company X] [--round N] [--type T] [--no-post] [--out <path>]
    .venv/bin/python pipeline/postmortem_draft.py post <meeting-id>
    .venv/bin/python pipeline/postmortem_draft.py skip <meeting-id> --reason "<why>"
    .venv/bin/python pipeline/postmortem_draft.py list

`plan` prints what the run needs as JSON: the search window, the pipeline companies with their
folders and prior artifacts, the keyword list, the paths to read, the active focus areas, and
the handled ledger. `classify` reads the raw search_meetings response (a list, or a dict with a
`meetings` key), says which meetings are interview-shaped and unhandled, infers company, round,
type, and the target path, writes `<stage>/classified-<date>.json`, and stamps `last_check`.
`apply` checks the draft's shape, writes it and the transcript into the company folder only when
nothing is there, records the meeting in the ledger, and posts (or, with --no-post, stores the
post for `post`). `--out <path>` writes the draft somewhere else and touches nothing: that is
the proof-case mode. `skip` records a meeting as handled with a reason (Aneesh was the
interviewer, a test recording). Nothing here writes to _lessons_learned.md, outcomes.csv,
interviews.json, or the interview-loop state file; the grading session does those.

State: pipeline/jobs/postmortem_drafts.json (gitignored with the rest of jobs/). Staging files
go in pipeline/jobs/postmortem_stage/.
"""
import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import calibration  # noqa: E402  (field/section parsers; read-only module)
import rehearsal_block  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
PREP = ROOT / "interview_prep"
JOBS = ROOT / "pipeline" / "jobs"
STATE = JOBS / "postmortem_drafts.json"
STAGE = JOBS / "postmortem_stage"
OUTCOMES = ROOT / "pipeline" / "outcomes.csv"
INTERVIEWS = JOBS / "interviews.json"
LOOP_STATE = pathlib.Path.home() / ".claude" / "skills" / "interview-loop" / "state.json"
TEMPLATE = PREP / "_template_postmortem.md"
LESSONS = PREP / "_lessons_learned.md"
WORKER_BRIEF = ROOT / "pipeline" / "postmortem_draft_worker.md"
DISCORD_SEND = pathlib.Path.home() / "PhoneLog" / "bin" / "discord_send.py"
NTFY_SEND = pathlib.Path.home() / "PhoneLog" / "bin" / "ntfy_send.py"
LOCAL_CONFIG = ROOT / "pipeline" / "local_config.json"   # gitignored
TZ = ZoneInfo("America/New_York")

FIRST_RUN_DAYS = 14      # the window on a first run, or after the ledger is lost
OVERLAP_HOURS = 48       # each run re-reads this far behind its last check; the ledger dedupes
MIN_MINUTES = 8          # shorter recordings are tests and pocket dials, not interviews
TRACKER_STAGES = {"applied", "interview", "closed"}
TRACKER_OUTCOMES = {"interview", "pending"}

# Title or summary text that marks a meeting as one of his interviews. Word-bounded so that
# "screenshot" and "screen share" don't count. These are the strong markers; `screen` and
# `panel` alone count only in the title, where a work meeting rarely puts them.
STRONG_MARKERS = [
    r"\binterviews?\b", r"\binterviewing\b", r"\bhiring manager\b", r"\brecruiters?\b",
    r"\brecruiting\b", r"\btalent acquisition\b", r"\bphone screen\b",
    r"\bscreening (?:call|interview)\b", r"\bpanel interview\b", r"\bfinal round\b",
    r"\bon-?site interview\b",
]
TITLE_MARKERS = [r"\bscreen\b", r"\bpanel\b"]
# Companies whose names are also meeting-tool words. A match on one of these never counts on
# its own; it needs a strong marker beside it ("30-min Zoom" is not an interview at Zoom).
GENERIC_NAMES = {"zoom", "teams", "meet", "slack", "notion", "loom", "calendly", "google", "apple", "meta"}
STOPWORDS = {"ai", "inc", "llc", "the", "co", "corp", "labs", "io", "app", "technologies",
             "tech", "software", "systems", "group", "health"}

# Round type: slug, the word for titles and the post, and the label text that implies it.
# Checked in order; the first hit wins. A prep doc's own name beats all of these.
TYPES = [
    ("hiring_manager", "Hiring Manager", [r"hiring manager", r"\bdirector\b"]),
    ("recruiter_screen", "Recruiter Screen", [r"recruiter", r"talent", r"\bscreen"]),
    ("panel", "Panel", [r"\bpanel\b"]),
    ("technical", "Technical", [r"technical (?:interview|round|screen)", r"take-?home", r"\bcoding\b"]),
    ("executive", "Executive", [r"\bvp\b", r"vice president", r"\bcto\b", r"\bceo\b", r"\bcoo\b", r"\bexecutive\b"]),
    ("final", "Final", [r"\bfinal\b", r"on-?site", r"in[- ]person"]),
]
KIND_TYPES = {"screen": "recruiter_screen", "onsite": "final"}
TYPE_WORDS = {slug: words for slug, words, _ in TYPES}
TYPE_WORDS["interview"] = "Interview"

REQUIRED_HEADINGS = [
    "## 1. Logistics", "## 2. What Went Well", "## 3. What Surprised You",
    "## 4. Questions You Got", "## 5. Questions You Wish", "## 6. Lessons Learned",
    "## 7. Follow-Ups", "## 8. Calibration Loop",
]
# Phrases the project's voice rules ban outright. A quote from the interviewer is the one place
# one could legitimately appear; trim the quote rather than carry the phrase.
BANNED_PHRASES = ["genuinely", "delve", "it's worth noting", "it is worth noting",
                  "here's the thing", "let's dive", "in conclusion", "to summarize",
                  "directly maps", "maps directly", "directly relevant"]
GRADE = re.compile(r"^\s*[A-D][+-]?\s*$")
README = ("Handled ledger for pipeline/postmortem_draft.py: one entry per Wispr meeting the routine "
          "has judged. drafted = a post-mortem was written to `path` (sha256 is the draft as written, "
          "so a later edit of his is visible); exists = a post-mortem was already on disk, nothing "
          "written; skipped = not his interview, with the reason. Don't hand-edit.")


# ---------------------------------------------------------------- small helpers

def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def utc_now():
    return dt.datetime.now(dt.timezone.utc)


def iso_z(d):
    return d.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(s):
    if not s:
        return None
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d


def local_date(s):
    d = parse_iso(s)
    return d.astimezone(TZ).date().isoformat() if d else ""


def local_clock(s):
    d = parse_iso(s)
    return d.astimezone(TZ).strftime("%-I:%M %p").replace("AM", "AM").replace("PM", "PM") if d else ""


def day_words(day):
    try:
        return dt.date.fromisoformat(day).strftime("%a %b %-d")
    except (TypeError, ValueError):
        return day or "?"


def sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def company_pattern(name, loose=False):
    """A regex that finds this company in prose with any separator between its words.

    "Acme-x" matches "Acme-x", "Acme X", "Acmex", never "Acmely". With loose=True the trailing
    stopwords are optional, so "Widgetron AI" also matches "Widgetron"; strict needs the whole
    name, which keeps "Level AI" from matching every "level". Returns None for a name too short
    to match on.
    """
    tokens = re.findall(r"[a-z0-9]+", (name or "").lower())
    if not tokens or len("".join(tokens)) < 3:
        return None
    core, tail = [], []
    for t in tokens:
        (tail if t in STOPWORDS and core else core).append(t)
    if not core or not loose:
        core, tail = tokens, []
    body = r"[\W_]*".join(re.escape(t) for t in core)
    if tail:
        body += "".join(r"(?:[\W_]*" + re.escape(t) + ")?" for t in tail)
    return re.compile(r"(?<![a-z0-9])" + body + r"(?![a-z0-9])", re.I)


def same_company(a, b):
    return norm(a) == norm(b)


def type_from_text(text):
    low = (text or "").lower()
    for slug, _, pats in TYPES:
        if any(re.search(p, low) for p in pats):
            return slug
    return ""


def type_from_filename(name):
    m = re.match(r"(?:prep|postmortem)_round\d+_(.+)\.md$", name)
    return m.group(1) if m else ""


def round_from_filename(name):
    m = re.match(r"(?:prep|postmortem)_round(\d+)", name)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- state

def load_state():
    if not STATE.exists():
        return {"_readme": README, "last_check": "", "meetings": {}}
    data = json.loads(STATE.read_text(encoding="utf-8"))
    data.setdefault("meetings", {})
    data.setdefault("last_check", "")
    data["_readme"] = README
    return data


def save_state(data):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    if STATE.exists():
        shutil.copy2(STATE, STATE.with_suffix(".json.bak"))
    tmp = STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, STATE)


# ---------------------------------------------------------------- the pipeline's companies

def load_rounds():
    if not INTERVIEWS.exists():
        return []
    data = json.loads(INTERVIEWS.read_text(encoding="utf-8"))
    rounds = data.get("rounds", []) if isinstance(data, dict) else data
    return [r for r in rounds if isinstance(r, dict) and r.get("company")]


def load_loop_state():
    if not LOOP_STATE.exists():
        return {}
    try:
        return json.loads(LOOP_STATE.read_text(encoding="utf-8")).get("companies", {})
    except (ValueError, AttributeError):
        return {}


def pipeline_companies(rounds=None, loop=None):
    """Every company a Wispr meeting could belong to, keyed by normalized name.

    Sources: interview_prep/<Company>/ folders, outcomes.csv rows that reached applied or
    beyond, the interview-loop state file, and interviews.json. The folder name wins as the
    display name when one exists, because that is where the draft has to land.
    """
    out = {}

    def add(name, source, folder=None, role=None):
        key = norm(name)
        if not key:
            return
        e = out.setdefault(key, {"name": name.strip(), "folder": None, "role": "", "sources": []})
        if folder:
            e["folder"] = folder
            e["name"] = folder
        if role and not e["role"]:
            e["role"] = role
        if source not in e["sources"]:
            e["sources"].append(source)

    if PREP.exists():
        for d in sorted(PREP.iterdir()):
            if d.is_dir() and not d.name.startswith(("_", ".")):
                add(d.name, "interview_prep", folder=d.name)
    if OUTCOMES.exists():
        with OUTCOMES.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if (r.get("stage") in TRACKER_STAGES or r.get("outcome") in TRACKER_OUTCOMES
                        or (r.get("furthest_stage") or "").strip()):
                    add(r.get("company", ""), "outcomes.csv", role=r.get("title", ""))
    for name, e in (loop if loop is not None else load_loop_state()).items():
        add(name, "state.json", role=(e or {}).get("role", ""))
    for r in (rounds if rounds is not None else load_rounds()):
        add(r.get("company", ""), "interviews.json")
    for e in out.values():
        # "Live" means an interview process already exists on file (a prep folder, a logged
        # round, or an interview-loop entry). A live company's name in a summary is enough on
        # its own; a tracker-only company's name must appear in the title, or an interview
        # word must appear beside it, because applied-to companies include Zendesk, Workday,
        # Cursor, and Writer, and his work meetings mention all of those.
        e["live"] = bool(set(e["sources"]) & {"interview_prep", "state.json", "interviews.json"})
        e["pattern"] = company_pattern(e["name"], loose=e["live"])
        e["generic"] = norm(e["name"]) in GENERIC_NAMES
    return out


def folder_artifacts(folder):
    d = PREP / folder
    if not d.is_dir():
        return {"postmortems": [], "preps": [], "transcripts": []}
    names = sorted(p.name for p in d.iterdir() if p.is_file())
    return {
        "postmortems": [n for n in names if n.startswith("postmortem_round")],
        "preps": [n for n in names if n.startswith("prep_round")],
        "transcripts": [n for n in names if n.startswith("transcript_round")],
    }


# ---------------------------------------------------------------- classification

def find_company(title, summary, companies):
    """(company entry or None, standalone, note).

    Ranking: a name in the title (live first, then the longest name), then a live company
    named in the summary, then a single tracker-only company named in the summary (low
    confidence: the summary may be naming a tool, not the employer). Several tracker-only
    summary hits with nothing better is "unknown" with the candidates listed. `standalone`
    says whether the match alone makes the meeting interview-shaped; a generic name (a
    meeting tool's name) never does.
    """
    title_hits, live_hits, other_hits = [], [], []
    for e in companies.values():
        if not e["pattern"]:
            continue
        if e["pattern"].search(title or ""):
            title_hits.append(e)
        elif e["pattern"].search(summary or ""):
            (live_hits if e["live"] else other_hits).append(e)
    longest = lambda e: -len(norm(e["name"]))  # noqa: E731
    if title_hits:
        title_hits.sort(key=lambda e: (not e["live"], longest(e)))
        best = title_hits[0]
        return best, not best["generic"], "named in the title"
    if live_hits:
        live_hits.sort(key=longest)
        best = live_hits[0]
        return best, not best["generic"], "live process, named in the summary"
    if len(other_hits) == 1:
        return other_hits[0], False, "tracker company named in the summary (low confidence: confirm from the transcript)"
    if other_hits:
        names = ", ".join(sorted(e["name"] for e in other_hits))
        return None, False, f"several tracker companies named in the summary ({names}); company unknown"
    return None, False, ""


def interview_markers(title, summary):
    found = []
    for p in STRONG_MARKERS:
        m = re.search(p, (title or "") + "\n" + (summary or ""), re.I)
        if m:
            found.append(m.group(0).lower())
    for p in TITLE_MARKERS:
        m = re.search(p, title or "", re.I)
        if m:
            found.append(m.group(0).lower() + " (title)")
    return sorted(set(found))


def infer_round(company, day, rounds, artifacts):
    """(round, type, how). interviews.json on the same day wins; else the prep doc that has no
    post-mortem yet; else one past the highest round logged or debriefed before this date."""
    mine = [r for r in rounds if same_company(r.get("company"), company) and r.get("kind") != "assessment"]
    same_day = [r for r in mine if r.get("date") == day and r.get("round")]
    pm_rounds = {round_from_filename(n) for n in artifacts["postmortems"]} - {None}
    prep_types = {round_from_filename(n): type_from_filename(n) for n in artifacts["preps"]}
    if same_day:
        r = same_day[0]
        t = prep_types.get(r["round"]) or type_from_text(r.get("label", "")) \
            or KIND_TYPES.get(r.get("kind"), "") or "interview"
        return int(r["round"]), t, "interviews.json"
    open_preps = sorted(n for n in prep_types if n is not None and n not in pm_rounds)
    before = [int(r["round"]) for r in mine if r.get("round") and (r.get("date") or "") < (day or "")]
    if before and (not open_preps or min(open_preps) <= max(before)):
        n = max(before) + 1
        return n, prep_types.get(n) or "", "interviews.json (next after the last logged round)"
    if open_preps:
        n = open_preps[0]
        return n, prep_types.get(n) or "", "prep doc with no post-mortem"
    n = (max(pm_rounds) + 1) if pm_rounds else 1
    return n, prep_types.get(n) or "", "post-mortems on disk" if pm_rounds else "first round on file"


def classify_meetings(meetings, state, companies=None, rounds=None, today=None):
    companies = companies if companies is not None else pipeline_companies()
    rounds = rounds if rounds is not None else load_rounds()
    results = []
    for m in meetings:
        mid = m.get("id") or ""
        title = m.get("title") or ""
        summary = m.get("summary") or m.get("content_excerpt") or ""
        start, end = m.get("start") or "", m.get("end") or ""
        s, e = parse_iso(start), parse_iso(end)
        minutes = round((e - s).total_seconds() / 60) if s and e else None
        day = local_date(start)
        company, standalone, note = find_company(title, summary, companies)
        markers = interview_markers(title, summary)
        reasons = list(markers)
        if company:
            reasons.append(f"company: {company['name']} ({note})")
        elif note:
            reasons.append(note)
        interview_like = bool(markers) or standalone
        entry = {
            "id": mid, "title": title, "date": day,
            "start_local": local_clock(start), "end_local": local_clock(end), "minutes": minutes,
            "share_link": m.get("share_link"), "has_transcript": bool(m.get("has_transcript")),
            "finalized": m.get("finalized", True),
            "interview_like": interview_like, "reasons": reasons,
            "company": None, "company_confidence": ("high" if standalone or (company and company["live"]) else "low") if company else None,
            "folder": None, "role": "", "round": None, "type": None,
            "round_source": "", "target": None, "transcript_target": None, "prior": None,
            "action": "",
        }
        handled = state.get("meetings", {}).get(mid)
        if handled:
            entry["action"] = f"skip:handled ({handled.get('status')})"
        elif not interview_like:
            entry["action"] = "skip:not-interview"
        elif not entry["has_transcript"]:
            entry["action"] = "skip:no-transcript"
        elif minutes is not None and minutes < MIN_MINUTES:
            entry["action"] = f"skip:short ({minutes} min)"
        elif company is None:
            entry["action"] = "draft:company-unknown"
        else:
            folder = company["folder"] or company["name"]
            arts = folder_artifacts(folder)
            n, t, how = infer_round(company["name"], day, rounds, arts)
            t = t or type_from_text(title + "\n" + summary) or "interview"
            target = PREP / folder / f"postmortem_round{n}_{t}.md"
            entry.update({
                "company": company["name"], "folder": folder, "role": company.get("role", ""),
                "round": n, "type": t, "round_source": how,
                "target": str(target.relative_to(ROOT)),
                "transcript_target": str((PREP / folder / f"transcript_round{n}_{t}.md").relative_to(ROOT)),
                "prior": arts,
            })
            entry["action"] = "skip:exists" if target.exists() else "draft"
        results.append(entry)
    return results


# ---------------------------------------------------------------- the draft's shape

def validate_draft(text):
    """A list of problems; empty means the draft has the post-mortem shape."""
    problems = []
    first = text.lstrip().splitlines()[0] if text.strip() else ""
    if not first.startswith("# Post-Mortem"):
        problems.append("first line must be the `# Post-Mortem — Company, Role, Round N (Format)` title")
    # The header blockquote wraps across lines; read it as one line before checking phrases.
    head = re.sub(r"\s*\n>?\s*", " ", text[:1500]).lower()
    if "transcript" not in head or "proposed by claude" not in head:
        problems.append("the header blockquote must say it was drafted from the transcript with grades proposed by Claude")
    if "not yet graded" not in head and "ready to grade" not in head:
        problems.append("the header blockquote must say the grades are not yet graded by Aneesh")
    for h in REQUIRED_HEADINGS:
        if not re.search(r"^" + re.escape(h), text, re.M):
            problems.append(f"missing section heading `{h}`")
    s4 = calibration.section(text, 4)
    rows = [ln for ln in s4.splitlines() if ln.startswith("|") and not ln.startswith("|--") and not ln.startswith("| #")]
    graded = 0
    for ln in rows:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if any(GRADE.match(c) for c in cells):
            graded += 1
    if graded < 3:
        problems.append(f"section 4 needs at least 3 table rows with a letter grade (found {graded})")
    s8 = calibration.section(text, 8)
    if not calibration.field(s8, "Predicted outcome"):
        problems.append("section 8 needs a filled `**Predicted outcome**:` line")
    if not calibration.field(s8, "Confidence"):
        problems.append("section 8 needs a filled `**Confidence**:` line")
    if calibration.field(s8, "Actual outcome"):
        problems.append("section 8 `Actual outcome` must stay blank until the outcome lands")
    low = text.lower()
    for p in BANNED_PHRASES:
        if p in low:
            problems.append(f"banned phrase: `{p}`")
    return problems


# ---------------------------------------------------------------- posting

def post_text(company, n, t, day, path):
    return (f"Heads up: {company} R{n} ({TYPE_WORDS.get(t, t).lower()}, {day_words(day)}) post-mortem "
            f"drafted from the Wispr transcript, ready to grade: {path}")


def local_setting(key):
    """A string from the gitignored pipeline/local_config.json, or "" when the file or the key
    is missing. The #follow-ups channel id (FOLLOWUPS_CHANNEL_ID) and the ntfy topic
    (NTFY_TOPIC) live there and never in this file: the repo is public, and a topic name is
    all it takes to read that feed or post to it."""
    try:
        value = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8")).get(key)
    except (OSError, ValueError, AttributeError):
        return ""
    return value.strip() if isinstance(value, str) else ""


def send(payload_path, record):
    """Run discord_send.py on the payload file; on exit 1 fall back to ntfy. Records the result.
    A channel id or topic missing from local_config.json is recorded as a failed send and
    nothing is guessed."""
    payload = json.loads(pathlib.Path(payload_path).read_text(encoding="utf-8"))
    if payload.get("channel_id"):
        r = subprocess.run(["python3", str(DISCORD_SEND), str(payload_path)], capture_output=True, text=True)
        code, err = r.returncode, (r.stderr or "")[-300:]
    else:
        code, err = 1, "FOLLOWUPS_CHANNEL_ID is missing from pipeline/local_config.json; Discord not tried"
    record["posted"] = {"channel": "discord", "exit": code, "at": iso_z(utc_now()), "stderr": err}
    if code == 1:
        topic = local_setting("NTFY_TOPIC")
        if not topic:
            record["posted"]["fallback"] = {
                "channel": "ntfy", "exit": 1,
                "stderr": "NTFY_TOPIC is missing from pipeline/local_config.json; ntfy not tried"}
            return record["posted"]
        ntfy = {"topic": topic, "title": "Post-mortem draft",
                "text": payload["text"].split(":")[0] + " (see interview_prep)"}
        npath = pathlib.Path(payload_path).with_suffix(".ntfy.json")
        npath.write_text(json.dumps(ntfy, ensure_ascii=False) + "\n", encoding="utf-8")
        n = subprocess.run(["python3", str(NTFY_SEND), str(npath)], capture_output=True, text=True)
        record["posted"]["fallback"] = {"channel": "ntfy", "exit": n.returncode}
    return record["posted"]


# ---------------------------------------------------------------- commands

def cmd_plan(args):
    state = load_state()
    now = utc_now()
    last = parse_iso(state.get("last_check"))
    since = now - dt.timedelta(days=FIRST_RUN_DAYS)
    if last:
        since = max(since, last - dt.timedelta(hours=OVERLAP_HOURS))
    companies = pipeline_companies()
    exemplar = sorted(PREP.glob("*/postmortem_round*.md"), key=lambda p: p.stat().st_mtime)
    lessons = LESSONS.read_text(encoding="utf-8") if LESSONS.exists() else ""
    out = {
        "now": iso_z(now), "today": now.astimezone(TZ).date().isoformat(),
        "since": iso_z(since), "first_run": not bool(last), "last_check": state.get("last_check", ""),
        "stage_dir": str(STAGE), "state_file": str(STATE),
        "paths": {
            "worker_brief": str(WORKER_BRIEF), "template": str(TEMPLATE), "lessons": str(LESSONS),
            "reference_postmortem": str(exemplar[-1]) if exemplar else None,
            "style_guide": str(pathlib.Path.home() / ".claude" / "projects" / "-Users-aneesh" / "memory" / "user_writing_style.md"),
            "postmortem_skill": str(ROOT / ".claude" / "skills" / "postmortem" / "SKILL.md"),
        },
        "markers": {"strong": STRONG_MARKERS, "title_only": TITLE_MARKERS, "min_minutes": MIN_MINUTES},
        "focus_areas": rehearsal_block.active_focus_areas(lessons),
        "companies": [
            {"name": e["name"], "folder": e["folder"] or e["name"], "role": e["role"],
             "sources": e["sources"], "artifacts": folder_artifacts(e["folder"]) if e["folder"] else None}
            for e in sorted(companies.values(), key=lambda e: e["name"].lower())
        ],
        "handled": {mid: {k: v for k, v in e.items() if k in ("status", "company", "round", "type", "date", "path")}
                    for mid, e in state.get("meetings", {}).items()},
    }
    STAGE.mkdir(parents=True, exist_ok=True)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def read_meetings(path):
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("meetings", [])
    if not isinstance(data, list):
        raise ValueError("meetings file must be a list or a dict with a `meetings` list")
    return [m for m in data if isinstance(m, dict) and m.get("id")]


def cmd_classify(args):
    state = load_state()
    meetings = read_meetings(args.meetings)
    results = classify_meetings(meetings, state)
    now = utc_now()
    STAGE.mkdir(parents=True, exist_ok=True)
    out_path = STAGE / f"classified-{now.astimezone(TZ).strftime('%Y%m%d-%H%M')}.json"
    out = {"checked_at": iso_z(now), "meetings": results,
           "to_draft": [r["id"] for r in results if r["action"].startswith("draft")]}
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    state["last_check"] = iso_z(now)
    save_state(state)
    out["written"] = str(out_path)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def latest_classified():
    files = sorted(STAGE.glob("classified-*.json"))
    return files[-1] if files else None


def cmd_apply(args):
    draft_path = pathlib.Path(args.draft)
    text = draft_path.read_text(encoding="utf-8")
    problems = validate_draft(text)
    if problems:
        print("DRAFT REJECTED, nothing written:")
        for p in problems:
            print("  - " + p)
        return 1

    # Classification for this meeting: the latest classified file, with command-line overrides.
    entry = {}
    cl = latest_classified()
    if cl:
        for e in json.loads(cl.read_text(encoding="utf-8")).get("meetings", []):
            if e.get("id") == args.meeting_id:
                entry = e
    company = args.company or entry.get("company")
    if not company:
        print("no company: pass --company (the meeting was classified company-unknown or never classified)")
        return 1
    companies = pipeline_companies()
    known = companies.get(norm(company))
    folder = (known["folder"] or known["name"]) if known else company
    n = args.round or entry.get("round")
    t = args.type or entry.get("type")
    if not n or not t:
        arts = folder_artifacts(folder)
        n2, t2, _ = infer_round(company, entry.get("date") or args.date or "", load_rounds(), arts)
        n, t = n or n2, t or t2 or "interview"
    day = args.date or entry.get("date") or ""
    target = PREP / folder / f"postmortem_round{n}_{t}.md"
    transcript_target = PREP / folder / f"transcript_round{n}_{t}.md"

    if args.out:
        out = pathlib.Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        if args.transcript:
            shutil.copyfile(args.transcript, out.with_name(out.stem + ".transcript.md"))
        print(json.dumps({"mode": "proof", "written": str(out), "would_target": str(target.relative_to(ROOT)),
                          "company": company, "round": n, "type": t, "date": day,
                          "post_text": post_text(company, n, t, day, str(target))}, indent=2, ensure_ascii=False))
        return 0

    state = load_state()
    prior = state["meetings"].get(args.meeting_id)
    if prior and prior.get("status") == "drafted":
        print(f"REFUSED: meeting {args.meeting_id} already drafted to {prior.get('path')} on {prior.get('drafted_at')}")
        return 1
    record = {"status": "", "company": company, "folder": folder, "round": n, "type": t, "date": day,
              "title": entry.get("title", ""), "share_link": entry.get("share_link"),
              "path": str(target.relative_to(ROOT)), "sha256": None, "drafted_at": None,
              "posted": None, "post_payload": None, "reason": ""}
    if target.exists():
        record.update({"status": "exists", "reason": "a post-mortem was already on disk; nothing written, nothing posted"})
        state["meetings"][args.meeting_id] = record
        save_state(state)
        print(json.dumps({"mode": "exists", "target": record["path"], "written": False, "posted": False}, indent=2))
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    if args.transcript and not transcript_target.exists():
        shutil.copyfile(args.transcript, transcript_target)
        record["transcript"] = str(transcript_target.relative_to(ROOT))
    record.update({"status": "drafted", "sha256": sha256(target), "drafted_at": iso_z(utc_now())})

    STAGE.mkdir(parents=True, exist_ok=True)
    payload_path = STAGE / f"post-{args.meeting_id}.json"
    payload = {"channel_id": local_setting("FOLLOWUPS_CHANNEL_ID"),
               "text": post_text(company, n, t, day, str(target))}
    payload_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    record["post_payload"] = str(payload_path)
    if not args.no_post:
        send(payload_path, record)
    state["meetings"][args.meeting_id] = record
    save_state(state)
    print(json.dumps({"mode": "drafted", "target": record["path"], "written": True,
                      "transcript": record.get("transcript"), "post_text": payload["text"],
                      "posted": record["posted"]}, indent=2, ensure_ascii=False))
    return 0


def cmd_post(args):
    state = load_state()
    record = state["meetings"].get(args.meeting_id)
    if not record or record.get("status") != "drafted":
        print(f"no drafted entry for {args.meeting_id}")
        return 1
    if record.get("posted") and record["posted"].get("exit") in (0, 2):
        print(f"already posted at {record['posted'].get('at')}; not resending")
        return 1
    payload_path = record.get("post_payload")
    if not payload_path or not pathlib.Path(payload_path).exists():
        print("no stored payload for this entry")
        return 1
    send(payload_path, record)
    save_state(state)
    print(json.dumps(record["posted"], indent=2))
    return 0 if record["posted"]["exit"] in (0, 2) else 1


def cmd_skip(args):
    state = load_state()
    prior = state["meetings"].get(args.meeting_id)
    if prior and prior.get("status") == "drafted":
        print(f"REFUSED: {args.meeting_id} was drafted to {prior.get('path')}; a skip can't undo that")
        return 1
    state["meetings"][args.meeting_id] = {"status": "skipped", "reason": args.reason,
                                          "skipped_at": iso_z(utc_now())}
    save_state(state)
    print(f"skipped {args.meeting_id}: {args.reason}")
    return 0


def cmd_list(args):
    state = load_state()
    print(f"last_check: {state.get('last_check') or '(never)'}")
    for mid, e in state.get("meetings", {}).items():
        where = e.get("path") or e.get("reason") or ""
        posted = ""
        if e.get("posted"):
            posted = f"  posted exit {e['posted'].get('exit')}"
        print(f"{e.get('status', '?'):8} {e.get('date', '') or '':10} {e.get('company', '') or '':14} "
              f"R{e.get('round') or '?'} {e.get('type') or ''}  {where}{posted}  [{mid}]")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan")
    c = sub.add_parser("classify")
    c.add_argument("meetings")
    a = sub.add_parser("apply")
    a.add_argument("draft")
    a.add_argument("--meeting-id", required=True)
    a.add_argument("--transcript")
    a.add_argument("--company")
    a.add_argument("--round", type=int)
    a.add_argument("--type")
    a.add_argument("--date")
    a.add_argument("--no-post", action="store_true")
    a.add_argument("--out", help="proof mode: write the draft here, touch nothing else")
    p = sub.add_parser("post")
    p.add_argument("meeting_id")
    s = sub.add_parser("skip")
    s.add_argument("meeting_id")
    s.add_argument("--reason", required=True)
    sub.add_parser("list")
    args = ap.parse_args(argv)
    return {"plan": cmd_plan, "classify": cmd_classify, "apply": cmd_apply,
            "post": cmd_post, "skip": cmd_skip, "list": cmd_list}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
