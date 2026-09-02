#!/usr/bin/env python3
"""LinkedIn job-alert extractor with GRADED cards (daily_task_prompt.md Step 1d-2).

Usage:
    .venv/bin/python pipeline/harvest_linkedin.py --from-transcripts            # daily run, dry
    .venv/bin/python pipeline/harvest_linkedin.py --from-transcripts --apply    # daily run, queue
    .venv/bin/python pipeline/harvest_linkedin.py --input-dir <dir> [--apply]   # saved bodies
    .venv/bin/python pipeline/harvest_linkedin.py --gmail [--newer-than 3d]     # needs a credential
    .venv/bin/python pipeline/test_harvest_linkedin.py          # parser + grading self-check

Read-only by default: it prints the graded card block and the UNKNOWN company list and
writes nothing but the run artifacts under pipeline/jobs/ (gitignored). `--apply` is the
only flag that touches enrollment_candidates.json, and it runs validate_config.py after.

WHY THIS EXISTS (2026-09-02 retro, Aneesh's call)
--------------------------------------------------
Step 1d-2 had the model open every LinkedIn job-alert body through the Gmail MCP. Each
body is ~8k tokens and ~80% tracking URLs; the 2026-09-02 run read 13 of 29 threads for
roughly 100k tokens and one real find (Cloudbeds). Worse, the step harvested only COMPANY
names by design and threw the role away, so a tier1 title in Atlanta looked the same in
the run record as a sales job in Lisbon; `manual_review` recovered a slice of that signal
and nothing else did. Aneesh's observation was that the roles inside these emails read
better than what the pipeline exported from them. This script keeps the company-discovery
output the step already needed and adds the missing half: every card is parsed, graded
with the SAME TitleMatcher the poller uses, given a location verdict under the Step 2c
rules, and rendered one line per card for the digest.

HOW GMAIL IS REACHED, HONESTLY
------------------------------
The pipeline's Gmail access is the claude.ai Gmail connector (an MCP server the model
calls). A script cannot use that connector: there is no local token, no Google API client
in .venv, and no OAuth client on this machine (checked 2026-09-02: nothing under
~/.config, no googleapiclient in .venv, no Gmail credential referenced anywhere in the
repo). So this script has three input paths, none of which is the connector:

  --input-dir DIR   Reads saved message records from a directory.
                    Accepted per file (auto-detected):
                      * a Gmail-MCP `get_message` JSON record (dict with `plaintextBody`,
                        `sender`, `subject`, `id`, `threadId`, `date`)
                      * a Gmail-MCP `search_messages` listing (dict with `threads`): counts
                        threads/senders, contributes no bodies
                      * a JSON list of either of the above
                      * an RFC-822 .eml export (text/plain part is used)
                      * a bare plaintext body (must contain "View job:")
                    A pipeline session can save each MCP result verbatim to a file; that
                    is the fallback the spec names. The CARD GRADING is the part that saves
                    tokens regardless of who fetched the body, because the model no longer
                    has to read 8k tokens to find three lines.

  --from-transcripts
                    The daily-run path today. Every Gmail-MCP `get_message` result the
                    session receives is written verbatim into the session transcript
                    (~/.claude/projects/<project slug>/<session>.jsonl) before the model
                    sees it. So the run calls `get_message` on each job-alert thread and
                    then runs this flag, which scans the transcripts modified inside the
                    window for LinkedIn job-sender records dated inside the window. The
                    body still transits the model's context once (that input cost is the
                    part only a Gmail API credential can remove), but nothing is read,
                    extracted, or re-typed by the model: zero reasoning, zero output
                    tokens. Verified 2026-09-02 against the transcript of that day's run
                    (14 records recovered, 64 cards). `--transcript-dir` overrides the
                    derived location; `--input-dir` is the same loader over a directory
                    you assembled yourself.

  --gmail           Gmail API path, UNVERIFIED. Needs `google-api-python-client` and
                    `google-auth` installed in .venv plus an authorized-user token at
                    pipeline/gmail_token.json (gitignored) carrying gmail.readonly scope.
                    Neither exists yet; creating them is an OAuth setup Aneesh has to do
                    or approve, so the script does not attempt it. Until then this flag
                    prints exactly what is missing and exits 3. The request shape is the
                    standard users().messages().list / .get(format="full"); it is written
                    from the API reference, not from a live run, and should be treated as
                    a starting point when the credential exists.

The Gmail query is the Step 1d-2 one: `deliveredto:{{CONFIRM_ALIAS}} from:linkedin.com
newer_than:Nd`, restricted after fetch to the two job senders. {{CONFIRM_ALIAS}} is read
from pipeline/local_config.json at runtime and is never written into any output; the
run artifacts carry the placeholder. The window defaults to what linkedin_window.py
computes (gap since the last run_*.json plus one day, capped at 7).

BODY SHAPE (verified against 14 real bodies from 2026-09-02, both senders)
--------------------------------------------------------------------------
    Your job alert for <saved search> in <place>        (jobalerts-noreply@ only)
    New jobs match your preferences.

    <title>
    <company>
    <location>
    [blank]
    [<connection / alum / actively hiring line>]      (optional)
    View job: https://www.linkedin.com/comm/jobs/view/<job id>/?trackingId=...
    ---------------------------------------------------------
    ... repeated ...
    See all jobs on LinkedIn: ...                     (or "View all jobs:" on jobs-noreply@)

`jobs-noreply@` ("Expand your search" / "Jobs you may be interested in") uses the same
card block with a different header. Both senders are multi-company digests; the subject
names one role and the body carries ~6.

GRADING
-------
  title_tier      TitleMatcher.match_exact() over the live config tiers (tier1/2/2b/2c/3/4,
                  supplemental), then the poller's own overrides in the poller's own order:
                  hard-exclude terms kill outright, function_mismatch_titles demote (the
                  GTM-Systems / Salesforce-Administrator half of tier2c), the AI wildcard
                  catches novel AI-prefixed titles no exact tier names.
  seniority       TITLE_EXCLUDE terms the title trips (director, vp, ...). Reported, not
                  applied: the poller relaxes director/head-of at small companies and the
                  card cannot say how big the company is, so the human decides.
  location        Step 2c: Atlanta in-office (+20) / Atlanta hybrid (+18) / remote US (+16)
                  / everything else 0. A bare "United States" card is reported as
                  `us-national` and scored like remote-US, because that is how LinkedIn
                  labels remote-eligible national postings and how the 2026-09-01 run read
                  Vultr's card; it is a distinct label so it can be judged separately.
  manual_review   Step 1d-2 item 2: title matches tier1/tier2/tier2c, either by the strict
                  matcher or by the LOOSE substring-either-direction rule ("Operations
                  Manager" flags off "Support Operations Manager"), AND the location verdict
                  is Atlanta or remote-US. Carried onto the pending entry as
                  manual_review / manual_review_why.
  blind_spot      The company resolves to `_blind_spot_companies`. Counted for Step 1d-2
                  item 3b so the run can decide whether to spend a verification search.

COMPANY DEDUPE AND THE QUEUE
----------------------------
Aggregators (Swooped, RemoteHunter, Jobot, ...) are dropped at extraction; the list lives
in watchlist_companies.json -> _poller_config.linkedin_aggregator_blocklist. Everything
else is checked against the watchlist, the blind-spot and unpollable blocks, and all three
enrollment buckets through check_company.lookup(), so the same name never queues twice.
Only UNKNOWN companies are queued, in the standard pending schema, at most 15 per run;
cards carrying manual_review go first, then order of appearance.
"""
import argparse
import datetime as dt
import email
import email.policy
import glob
import html
import json
import os
import re
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

WATCHLIST = os.path.join(SCRIPT_DIR, "watchlist_companies.json")
QUEUE = os.path.join(SCRIPT_DIR, "enrollment_candidates.json")
LOCAL_CONFIG = os.path.join(SCRIPT_DIR, "local_config.json")
JOBS_DIR = os.path.join(SCRIPT_DIR, "jobs")
GMAIL_TOKEN = os.path.join(SCRIPT_DIR, "gmail_token.json")
VALIDATE = os.path.join(SCRIPT_DIR, "validate_config.py")

JOB_SENDERS = ("jobalerts-noreply@linkedin.com", "jobs-noreply@linkedin.com")
MAX_NEW_PER_RUN = 15          # Step 1d-2 item 4; do not raise to "clear the backlog"
SOURCE_LABEL = "LinkedIn alert"

TIER_LABELS = {
    "tier1_true_match": "tier1",
    "tier2_strong_overlap": "tier2",
    "tier2b_ai_wildcard": "tier2b",
    "tier2c_tooling_systems": "tier2c",
    "tier3_reasonable_stretch": "tier3",
    "tier4_weak_stretch": "tier4",
    "supplemental": "supp",
}
# Sort order for the digest block: strongest first. Anything not listed sorts last.
TIER_ORDER = ["tier1", "tier2", "tier2c", "tier2b", "tier3", "supp", "tier4",
              "demoted", "none", "excluded"]
LOCATION_ORDER = ["atlanta", "atlanta-hybrid", "remote", "us-national", "other",
                  "non-us", "unknown"]
LOCATION_POINTS = {"atlanta": 20, "atlanta-hybrid": 18, "remote": 16, "us-national": 16}
LOCATION_DISPLAY = {"atlanta": "Atlanta", "atlanta-hybrid": "Atlanta hybrid",
                    "remote": "Remote US", "us-national": "US (unspecified)",
                    "non-us": "non-US", "unknown": "?"}
STRONG_TIERS = ("tier1_true_match", "tier2_strong_overlap", "tier2c_tooling_systems")

# Metro-Atlanta suburbs that appear on LinkedIn cards as the city instead of Atlanta.
METRO_ATLANTA = ("alpharetta", "marietta", "sandy springs", "roswell", "duluth, ga",
                 "norcross", "peachtree", "kennesaw", "decatur, ga", "smyrna, ga",
                 "dunwoody", "johns creek", "lawrenceville, ga", "cumming, ga",
                 "buckhead", "midtown atlanta")

# The optional fourth line of a card. Usually separated from the block by a blank line
# ("3 connections", "This company is actively hiring"), but NOT always: "Apply with
# resume & profile" sits directly under the location with no blank, which on the real
# 2026-09-02 corpus shifted five cards so the location became the company and the
# apply-hint became the location. So the block is delimited by the blank line when
# there is one, and by this regex when there is not (see parse_cards).
EXTRA_LINE_RE = re.compile(
    r"(connection|alum\b|alumni|actively hiring|actively recruiting|early applicant|"
    r"applicants?\b|promoted|easy apply|apply with|apply on|skills? match|profile match|"
    r"top applicant|\bviewed\b|is hiring|be an early)", re.I)
JOB_URL_RE = re.compile(r"/jobs/view/(\d+)")
ALERT_HEADER_RE = re.compile(r"^Your job alert for (.+?)(?: in (.+?))?\s*$", re.M)
RULE_RE = re.compile(r"^\s*-{5,}\s*$", re.M)


# ── Input loading ────────────────────────────────────────────────────────────

def _norm_record(d: dict, source: str) -> dict | None:
    """Gmail-MCP get_message record -> normalized message, or None if not one."""
    if not isinstance(d, dict):
        return None
    body = d.get("plaintextBody") or d.get("body") or ""
    if "plaintextBody" not in d and not body:
        return None
    return {
        "id": d.get("id") or "",
        "thread_id": d.get("threadId") or d.get("id") or source,
        "sender": (d.get("sender") or d.get("from") or "").lower(),
        "subject": d.get("subject") or "",
        "date": d.get("date") or "",
        "body": body,
        "source": source,
    }


def _from_listing(d: dict, source: str) -> list[dict]:
    """Gmail-MCP search_messages listing -> body-less records (sender/subject only)."""
    out = []
    for th in d.get("threads", []):
        for m in th.get("messages", []) or []:
            out.append({
                "id": m.get("id") or "",
                "thread_id": th.get("id") or m.get("threadId") or "",
                "sender": (m.get("sender") or "").lower(),
                "subject": m.get("subject") or "",
                "date": m.get("date") or "",
                "body": "",
                "source": source,
            })
    return out


def _from_eml(text: str, source: str) -> dict:
    msg = email.message_from_string(text, policy=email.policy.default)
    body = ""
    part = msg.get_body(preferencelist=("plain",))
    if part is not None:
        body = part.get_content()
    else:
        part = msg.get_body(preferencelist=("html",))
        if part is not None:
            body = html.unescape(re.sub(r"<[^>]+>", "\n", part.get_content()))
    sender = email.utils.parseaddr(str(msg.get("From", "")))[1].lower()
    return {
        "id": str(msg.get("Message-ID", "")).strip("<>"),
        "thread_id": str(msg.get("Message-ID", "")).strip("<>") or source,
        "sender": sender,
        "subject": str(msg.get("Subject", "")),
        "date": str(msg.get("Date", "")),
        "body": body,
        "source": source,
    }


def load_input_dir(path: str) -> list[dict]:
    """Every message record found under `path` (see module docstring for formats)."""
    records: list[dict] = []
    files = sorted(p for p in glob.glob(os.path.join(path, "*")) if os.path.isfile(p))
    for p in files:
        with open(p, encoding="utf-8", errors="replace") as f:
            text = f.read()
        src = os.path.basename(p)
        stripped = text.lstrip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, list):
                for item in data:
                    rec = _norm_record(item, src)
                    if rec:
                        records.append(rec)
                    elif isinstance(item, dict) and "threads" in item:
                        records += _from_listing(item, src)
                continue
            if isinstance(data, dict):
                if "threads" in data:
                    records += _from_listing(data, src)
                    continue
                if "messages" in data and isinstance(data["messages"], list):
                    for item in data["messages"]:
                        rec = _norm_record(item, src)
                        if rec:
                            records.append(rec)
                    continue
                rec = _norm_record(data, src)
                if rec:
                    records.append(rec)
                    continue
        if re.search(r"^(From|Subject|Received|Return-Path):", text, re.M):
            records.append(_from_eml(text, src))
            continue
        if "View job:" in text or "Your job alert for" in text:
            sender = ("jobalerts-noreply@linkedin.com" if "Your job alert for" in text
                      else "jobs-noreply@linkedin.com")
            records.append({"id": "", "thread_id": src, "sender": sender, "subject": "",
                            "date": "", "body": text, "source": src})
    return records


# ── Session-transcript path ──────────────────────────────────────────────────

def default_transcript_dir() -> str:
    """~/.claude/projects/<slug>, where <slug> is the repo root with every
    non-alphanumeric character replaced by '-' (that is how Claude Code names it:
    /Users/aneesh/Documents/resume_project -> -Users-aneesh-Documents-resume-project)."""
    root = os.path.dirname(SCRIPT_DIR)
    slug = re.sub(r"[^A-Za-z0-9]", "-", root)
    return os.path.join(os.path.expanduser("~"), ".claude", "projects", slug)


def _records_from_json_text(text: str, source: str) -> list[dict]:
    """Every Gmail-MCP record inside one JSON payload (record, list, or listing)."""
    stripped = text.lstrip()
    if not (stripped.startswith("{") or stripped.startswith("[")):
        return []
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return []
    items = data if isinstance(data, list) else [data]
    out = []
    for item in items:
        rec = _norm_record(item, source)
        if rec:
            out.append(rec)
        elif isinstance(item, dict) and "threads" in item:
            out += _from_listing(item, source)
    return out


def load_transcripts(tdir: str, since: dt.date) -> list[dict]:
    """LinkedIn job-sender records from session transcripts modified on/after `since`.

    Reads the .jsonl session logs plus any oversized tool results the harness spilled
    to <session>/tool-results/. Only lines that mention a LinkedIn job sender are
    parsed, so a long transcript costs a grep, not a JSON parse per line.
    """
    if not os.path.isdir(tdir):
        return []
    cutoff = dt.datetime.combine(since, dt.time.min).timestamp()
    needles = tuple(f'"sender":"{s}"' for s in JOB_SENDERS)
    records: list[dict] = []
    for path in sorted(glob.glob(os.path.join(tdir, "*.jsonl"))):
        if os.path.getmtime(path) < cutoff:
            continue
        sid = os.path.basename(path)[:8]
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if not any(n in line for n in needles):
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                content = (rec.get("message") or {}).get("content", [])
                if isinstance(content, str):
                    continue
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue
                    inner = block.get("content", "")
                    if isinstance(inner, list):
                        inner = "\n".join(b.get("text", "") for b in inner if isinstance(b, dict))
                    records += _records_from_json_text(inner, f"transcript:{sid}")
    for path in glob.glob(os.path.join(tdir, "*", "tool-results", "*")):
        if not os.path.isfile(path) or os.path.getmtime(path) < cutoff:
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        if any(n in text for n in needles):
            records += _records_from_json_text(text, f"tool-result:{os.path.basename(path)}")
    # Keep records dated inside the window; undated ones (rare) are kept.
    kept = []
    for r in records:
        d = r.get("date", "")[:10]
        try:
            if d and dt.date.fromisoformat(d) < since:
                continue
        except ValueError:
            pass
        kept.append(r)
    return kept


# ── Gmail API path (UNVERIFIED; see module docstring) ────────────────────────

class GmailUnavailable(RuntimeError):
    pass


def fetch_gmail(query: str, max_messages: int = 200) -> list[dict]:
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as e:
        raise GmailUnavailable(
            "google-api-python-client / google-auth are not installed in .venv. The "
            "pipeline's Gmail access is the claude.ai connector, which a script cannot "
            "use. Either set up an API credential (an OAuth step Aneesh must approve) or "
            "run with --input-dir on saved bodies.") from e
    if not os.path.exists(GMAIL_TOKEN):
        raise GmailUnavailable(
            f"no authorized-user token at {GMAIL_TOKEN}. This path needs a gmail.readonly "
            f"token created by an OAuth flow that has not been built or approved. Use "
            f"--input-dir on saved bodies instead.")
    creds = Credentials.from_authorized_user_file(
        GMAIL_TOKEN, ["https://www.googleapis.com/auth/gmail.readonly"])
    svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
    ids, token = [], None
    while len(ids) < max_messages:
        resp = svc.users().messages().list(userId="me", q=query, maxResults=100,
                                           pageToken=token).execute()
        ids += [m["id"] for m in resp.get("messages", [])]
        token = resp.get("nextPageToken")
        if not token:
            break

    def _walk(part):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            import base64
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", "replace")
        for sub in part.get("parts", []) or []:
            got = _walk(sub)
            if got:
                return got
        return ""

    records = []
    for mid in ids[:max_messages]:
        m = svc.users().messages().get(userId="me", id=mid, format="full").execute()
        headers = {h["name"].lower(): h["value"] for h in m.get("payload", {}).get("headers", [])}
        records.append({
            "id": m["id"], "thread_id": m.get("threadId", m["id"]),
            "sender": email.utils.parseaddr(headers.get("from", ""))[1].lower(),
            "subject": headers.get("subject", ""), "date": headers.get("date", ""),
            "body": _walk(m.get("payload", {})), "source": "gmail-api",
        })
    return records


# ── Card parsing ─────────────────────────────────────────────────────────────

def parse_cards(body: str) -> list[dict]:
    """Every (title, company, location, job_id) card in one alert body."""
    body = body.replace("\r\n", "\n")
    cards = []
    for chunk in RULE_RE.split(body):
        m = JOB_URL_RE.search(chunk)
        if not m or "View job" not in chunk:
            continue
        head = chunk[:chunk.index("View job")]
        lines = [ln.rstrip() for ln in head.split("\n")]
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            continue
        extra = ""
        # "title / company / location [blank] extra" -- the blank line marks the extra.
        if len(lines) >= 2 and not lines[-2].strip():
            extra = lines[-1].strip()
            lines = lines[:-2]
            while lines and not lines[-1].strip():
                lines.pop()
        # Contiguous block ending at the last non-empty line.
        block = []
        for ln in reversed(lines):
            if not ln.strip():
                break
            block.append(ln.strip())
        block.reverse()
        # Defensive: an unrecognised layout may glue the extra line onto the block.
        if len(block) > 3 and EXTRA_LINE_RE.search(block[-1]):
            extra = extra or block[-1]
            block = block[:-1]
        if len(block) < 3:
            continue
        title, company, location = block[-3], block[-2], block[-1]
        if not title or not company or title.startswith("http"):
            continue
        cards.append({
            "title": html.unescape(title), "company": html.unescape(company),
            "location": html.unescape(location), "job_id": m.group(1),
            "url": f"https://www.linkedin.com/jobs/view/{m.group(1)}/",
            "extra": extra,
        })
    return cards


def alert_search(body: str) -> str:
    m = ALERT_HEADER_RE.search(body or "")
    if not m:
        return ""
    return m.group(1).strip() + (f" in {m.group(2).strip()}" if m.group(2) else "")


# ── Grading ──────────────────────────────────────────────────────────────────

class Grader:
    def __init__(self, wl: dict, enrollment: dict):
        import poll_ats as P
        from check_company import lookup, norm
        import harvest_ats as H
        self.P, self.H = P, H
        self.lookup, self.norm = lookup, norm
        P._init_config(wl)
        self.matcher = P.TitleMatcher(wl)
        self.wl, self.enrollment = wl, enrollment
        tiers = wl["_title_scoring_tiers"]
        self.loose_titles = []
        for tier in STRONG_TIERS:
            for t in tiers.get(tier, {}).get("titles", []):
                self.loose_titles.append((t.lower(), tier))
        pc = wl.get("_poller_config", {})
        self.aggregators = [a for a in pc.get("linkedin_aggregator_blocklist", {}).get("names", [])]
        self.matched_ai_wildcard_score = tiers["tier2b_ai_wildcard"]["title_match_score"]

    # -- title ---------------------------------------------------------------
    def title_grade(self, title: str) -> dict:
        P, m = self.P, self.matcher
        out = {"tier": "none", "tier_name": None, "prescore": 0, "demoted_from": None,
               "hard_excluded": False, "seniority": P.title_exclusion_reasons(title),
               "loose_tier": None}
        for cfg, tier in self.loose_titles:
            t = title.lower()
            if cfg in t or t in cfg:
                out["loose_tier"] = TIER_LABELS[tier]
                break
        if P.title_hard_excluded(title):
            out.update(tier="excluded", hard_excluded=True)
            return out
        ex = m.match_exact(title)
        if ex:
            tier_name, score = ex
            out.update(tier_name=tier_name, prescore=score, tier=TIER_LABELS.get(tier_name, tier_name))
            if m.is_function_mismatch(title, tier_name):
                out.update(demoted_from=out["tier"], tier="demoted")
        elif m.matches_ai_wildcard(title):
            out.update(tier="tier2b", tier_name="tier2b_ai_wildcard",
                       prescore=self.matched_ai_wildcard_score)
        return out

    # -- location -------------------------------------------------------------
    def location_grade(self, location: str, title: str) -> str:
        H = self.H
        loc = (location or "").strip().lower()
        text = f"{loc} {title.lower()}"
        if not loc:
            return "unknown"
        has_us = "united states" in loc or re.search(r"\b(usa|u\.s\.|us)\b", loc)
        non_us = (any(mk in loc for mk in H.NON_US_MARKERS)
                  or bool(H.NON_US_CODES & set(re.split(r"[^a-z0-9-]+", loc))))
        if non_us and not has_us:
            return "non-us"
        atlanta = any(h in loc for h in H.ATLANTA_HINTS) or any(c in loc for c in METRO_ATLANTA)
        remote = bool(re.search(r"\bremote\b", text)) or "work from home" in text
        hybrid = "hybrid" in text
        if atlanta:
            return "remote" if (remote and not hybrid) else ("atlanta-hybrid" if hybrid else "atlanta")
        if remote:
            return "remote"
        if re.fullmatch(r"(united states|usa|u\.s\.|us|united states of america)", loc):
            return "us-national"
        return "other"

    # -- company --------------------------------------------------------------
    def is_aggregator(self, company: str) -> bool:
        from check_company import hit
        return any(hit(company, a) for a in self.aggregators)

    def company_status(self, company: str) -> list[str]:
        hits = self.lookup(company, self.wl, self.enrollment)
        seen, out = set(), []
        for where, _ in hits:
            if where not in seen:
                seen.add(where)
                out.append(where)
        return out

    def grade(self, card: dict) -> dict:
        tg = self.title_grade(card["title"])
        verdict = self.location_grade(card["location"], card["title"])
        strong = tg["tier_name"] in STRONG_TIERS
        # A demoted or hard-excluded title never earns the review flag, even when the
        # loose rule would fire on it: "GTM Systems Manager" is a substring of a tier2c
        # title by construction, and demotion exists precisely to keep it off the queue.
        review = (tg["tier"] not in ("demoted", "excluded")
                  and (strong or tg["loose_tier"] is not None)
                  and verdict in LOCATION_POINTS)
        status = self.company_status(card["company"])
        g = dict(card)
        g.update({
            "title_tier": tg["tier"], "tier_name": tg["tier_name"],
            "title_prescore": tg["prescore"], "demoted_from": tg["demoted_from"],
            "hard_excluded": tg["hard_excluded"], "seniority_flags": tg["seniority"],
            "loose_tier": tg["loose_tier"],
            "location_verdict": verdict, "location_points": LOCATION_POINTS.get(verdict, 0),
            "manual_review": review,
            "company_status": status,
            "company_known": bool(status),
            "blind_spot": "blind_spot_companies" in status,
        })
        return g


def sort_key(card: dict):
    t = card["title_tier"]
    ti = TIER_ORDER.index(t) if t in TIER_ORDER else len(TIER_ORDER)
    lv = card["location_verdict"]
    li = LOCATION_ORDER.index(lv) if lv in LOCATION_ORDER else len(LOCATION_ORDER)
    return (ti, li, -card.get("title_prescore", 0), card["company"].lower())


def digest_line(card: dict) -> str:
    verdict = card["location_verdict"]
    loc = LOCATION_DISPLAY.get(verdict, card["location"] or "?")
    if verdict == "other":
        loc = card["location"]
    tier = card["title_tier"]
    if tier == "demoted" and card.get("demoted_from"):
        tier = f"demoted:{card['demoted_from']}"
    status = "new" if not card["company_known"] else "/".join(
        s.replace("_companies", "") for s in card["company_status"])
    line = f"[{tier} | {loc}] {card['company']}: {card['title']} | {card['job_id']} | {status}"
    tags = []
    if card["manual_review"]:
        tags.append("review")
    if card["seniority_flags"]:
        tags.append(",".join(card["seniority_flags"]))
    if card.get("loose_tier") and tier == "none":
        tags.append(f"loose:{card['loose_tier']}")
    return line + (f"  ({'; '.join(tags)})" if tags else "")


# ── Orchestration ────────────────────────────────────────────────────────────

def resolve_alias() -> str | None:
    if not os.path.exists(LOCAL_CONFIG):
        return None
    with open(LOCAL_CONFIG, encoding="utf-8") as f:
        return json.load(f).get("CONFIRM_ALIAS")


def default_window(today: dt.date) -> tuple[str, str]:
    import linkedin_window as LW
    w = LW.compute_window(today)
    return f"{w['window']}d", w["note"]


def harvest(records: list[dict], grader: Grader, today: dt.date, run_meta: dict) -> dict:
    job_records = [r for r in records if r["sender"] in JOB_SENDERS]
    threads = {}
    for r in job_records:
        key = r["thread_id"] or r["source"]
        cur = threads.get(key)
        if cur is None or (r["body"] and not cur["body"]):
            threads[key] = r
    bodies = [r for r in threads.values() if r["body"].strip()]

    cards_by_id: dict[str, dict] = {}
    order: list[str] = []
    for r in sorted(bodies, key=lambda x: x["date"], reverse=True):
        search = alert_search(r["body"])
        for c in parse_cards(r["body"]):
            if c["job_id"] in cards_by_id:
                continue                   # LinkedIn re-sends the same card hours apart
            c["alert_subject"] = r["subject"]
            c["alert_date"] = r["date"][:10]
            c["alert_search"] = search
            cards_by_id[c["job_id"]] = c
            order.append(c["job_id"])

    graded, dropped_aggregators = [], []
    for jid in order:
        c = cards_by_id[jid]
        if grader.is_aggregator(c["company"]):
            if c["company"] not in dropped_aggregators:
                dropped_aggregators.append(c["company"])
            continue
        graded.append(grader.grade(c))

    # Company roll-up: one entry per normalized name, best card first.
    companies: dict[str, dict] = {}
    for g in graded:
        key = grader.norm(g["company"])
        entry = companies.setdefault(key, {"name": g["company"], "cards": [],
                                           "status": g["company_status"]})
        entry["cards"].append(g)
    for entry in companies.values():
        entry["cards"].sort(key=sort_key)

    unknown = [e for e in companies.values() if not e["status"]]
    flagged = [e for e in unknown if any(c["manual_review"] for c in e["cards"])]
    rest = [e for e in unknown if e not in flagged]
    ordered_unknown = flagged + rest
    queued, deferred = ordered_unknown[:MAX_NEW_PER_RUN], ordered_unknown[MAX_NEW_PER_RUN:]

    pending_entries = []
    for e in queued:
        best = e["cards"][0]
        entry = {
            "name": e["name"], "ats": None, "slug": None,
            "source": SOURCE_LABEL, "first_seen": today.isoformat(),
            "why": (f"LinkedIn alert {best['alert_date'] or today.isoformat()}: "
                    f"{best['title']} [{best['location']}] "
                    f"(graded {best['title_tier']} / {best['location_verdict']}; "
                    f"linkedin job {best['job_id']})"),
            "needs_ats_resolution": True,
        }
        if best["manual_review"]:
            entry["manual_review"] = True
            entry["manual_review_why"] = (
                f"{best['title']} [{best['location']}] -- "
                f"{best['title_tier'] if best['title_tier'] != 'none' else 'loose:' + str(best['loose_tier'])}"
                f" title, {LOCATION_DISPLAY.get(best['location_verdict'], best['location_verdict'])}; "
                f"LinkedIn job {best['job_id']}")
        pending_entries.append(entry)

    graded_sorted = sorted(graded, key=sort_key)
    blind_spot = [g for g in graded_sorted if g["blind_spot"] and
                  (g["tier_name"] in STRONG_TIERS or g["loose_tier"])]

    jobalerts_seen = sum(1 for r in threads.values() if r["sender"] == JOB_SENDERS[0])
    jobs_noreply_seen = sum(1 for r in threads.values() if r["sender"] == JOB_SENDERS[1])
    counters = {
        "query": run_meta.get("query"),
        "window_used": run_meta.get("window_used"),
        "input_mode": run_meta.get("input_mode"),
        "threads_returned": len({(r["thread_id"] or r["source"]) for r in records}),
        "job_alert_threads_seen": len(threads),
        "jobalerts_threads_seen": jobalerts_seen,
        "jobs_noreply_threads_seen": jobs_noreply_seen,
        "bodies_read": len(bodies),
        "digest_bodies_opened": sum(1 for r in bodies if r["sender"] == JOB_SENDERS[1]),
        "non_job_threads_skipped": len({(r["thread_id"] or r["source"]) for r in records
                                        if r["sender"] not in JOB_SENDERS}),
        "cards_parsed": len(order),
        "aggregators_dropped": dropped_aggregators,
        "companies_extracted": len(companies),
        "unknown_after_dedupe": len(unknown),
        "newly_queued": len(queued),
        "cap_deferred": len(deferred),
        "cap_deferred_names": [e["name"] for e in deferred],
        "manual_review_flagged": [f"{c['company']} - {c['title']} [{c['location']}]"
                                  for c in graded_sorted if c["manual_review"]],
        "blind_spot_qualifying": [f"{c['company']} - {c['title']} [{c['location']}]"
                                  for c in blind_spot],
    }
    return {
        "run_date": today.isoformat(),
        "counters": counters,
        "cards": graded_sorted,
        "unknown_companies": [e["name"] for e in ordered_unknown],
        "pending_entries": pending_entries,
        "digest_lines": [digest_line(c) for c in graded_sorted],
    }


def write_pending(entries: list[dict]) -> int:
    with open(QUEUE, encoding="utf-8") as f:
        q = json.load(f)
    have = {str(e.get("name", "")).lower() for e in q.get("pending", [])}
    added = 0
    for e in entries:
        if e["name"].lower() in have:
            continue
        q.setdefault("pending", []).append(e)
        have.add(e["name"].lower())
        added += 1
    tmp = QUEUE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(q, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, QUEUE)
    return added


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--input-dir", help="directory of saved message records / .eml / bodies")
    src.add_argument("--from-transcripts", action="store_true",
                     help="read get_message records the session already fetched from the "
                          "project's Claude Code transcripts (the daily-run path)")
    src.add_argument("--gmail", action="store_true", help="fetch via Gmail API (unverified)")
    ap.add_argument("--transcript-dir", help="override the derived ~/.claude/projects/<slug>")
    ap.add_argument("--newer-than", help="Gmail window like 3d; default from linkedin_window.py")
    ap.add_argument("--apply", action="store_true", help="append UNKNOWN companies to pending")
    ap.add_argument("--date", help="run date (YYYY-MM-DD) for output names; default today")
    ap.add_argument("--out-dir", default=JOBS_DIR)
    ap.add_argument("--quiet", action="store_true", help="skip the card block on stdout")
    args = ap.parse_args()

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    window, window_note = (args.newer_than, "from --newer-than") if args.newer_than \
        else default_window(today)
    window = window if window.endswith("d") else window + "d"
    query_placeholder = f"deliveredto:{{{{CONFIRM_ALIAS}}}} from:linkedin.com newer_than:{window}"

    with open(WATCHLIST, encoding="utf-8") as f:
        wl = json.load(f)
    with open(QUEUE, encoding="utf-8") as f:
        enrollment = json.load(f)
    grader = Grader(wl, enrollment)
    if not grader.aggregators:
        print("WARNING: _poller_config.linkedin_aggregator_blocklist is empty; nothing "
              "will be dropped as an aggregator", file=sys.stderr)

    if args.gmail:
        alias = resolve_alias()
        if not alias:
            print("CONFIRM_ALIAS missing from pipeline/local_config.json", file=sys.stderr)
            return 2
        try:
            records = fetch_gmail(query_placeholder.replace("{{CONFIRM_ALIAS}}", alias))
        except GmailUnavailable as e:
            print(f"GMAIL PATH UNAVAILABLE: {e}", file=sys.stderr)
            return 3
        input_mode = "gmail-api"
    elif args.from_transcripts:
        tdir = args.transcript_dir or default_transcript_dir()
        since = today - dt.timedelta(days=int(window[:-1]))
        records = load_transcripts(tdir, since)
        input_mode = f"transcripts:{os.path.basename(tdir)} since {since.isoformat()}"
        if not records:
            print(f"no LinkedIn job-sender records dated >= {since} found under {tdir}. "
                  f"Either get_message was not called this run, or the transcript dir "
                  f"is elsewhere (--transcript-dir). Fall back to the manual rule and "
                  f"say so in the run record.", file=sys.stderr)
    else:
        if not os.path.isdir(args.input_dir):
            print(f"not a directory: {args.input_dir}", file=sys.stderr)
            return 2
        records = load_input_dir(args.input_dir)
        input_mode = f"input-dir:{os.path.basename(os.path.normpath(args.input_dir))}"

    result = harvest(records, grader, today,
                     {"query": query_placeholder, "window_used": f"{window} ({window_note})",
                      "input_mode": input_mode})
    c = result["counters"]

    os.makedirs(args.out_dir, exist_ok=True)
    json_path = os.path.join(args.out_dir, f"linkedin_cards_{today.isoformat()}.json")
    txt_path = os.path.join(args.out_dir, f"linkedin_cards_{today.isoformat()}.txt")
    block = "\n".join(result["digest_lines"]) or "(no cards parsed)"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        f.write("\n")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("LinkedIn alert cards, graded\n" + block + "\n")

    print(f"window {c['window_used']} | input {c['input_mode']}")
    print(f"threads_returned={c['threads_returned']} job_alert_threads_seen="
          f"{c['job_alert_threads_seen']} (jobalerts {c['jobalerts_threads_seen']}, "
          f"jobs-noreply {c['jobs_noreply_threads_seen']}) bodies_read={c['bodies_read']} "
          f"non_job_skipped={c['non_job_threads_skipped']}")
    print(f"cards_parsed={c['cards_parsed']} companies_extracted={c['companies_extracted']} "
          f"unknown_after_dedupe={c['unknown_after_dedupe']} newly_queued={c['newly_queued']} "
          f"cap_deferred={c['cap_deferred']} aggregators_dropped={len(c['aggregators_dropped'])}")
    if c["bodies_read"] < c["job_alert_threads_seen"]:
        print(f"SHORTFALL: {c['job_alert_threads_seen'] - c['bodies_read']} job-alert threads "
              f"had no body in the input; name this in the digest.")
    if not args.quiet:
        print("\nLinkedIn alert cards, graded")
        print(block)
    print("\nUNKNOWN companies (queue order):",
          ", ".join(result["unknown_companies"]) or "none")
    if c["aggregators_dropped"]:
        print("aggregators dropped:", ", ".join(c["aggregators_dropped"]))
    if c["manual_review_flagged"]:
        print("manual_review:", "; ".join(c["manual_review_flagged"]))
    if c["blind_spot_qualifying"]:
        print("blind-spot qualifying (Step 1d-2 3b):", "; ".join(c["blind_spot_qualifying"]))
    print(f"\nwrote {json_path}\nwrote {txt_path}")

    if not args.apply:
        print("dry run; re-run with --apply to append the UNKNOWN companies to pending")
        return 0
    added = write_pending(result["pending_entries"])
    print(f"appended {added} to enrollment_candidates.json -> pending")
    rc = subprocess.run([sys.executable, VALIDATE, "--quiet"]).returncode
    if rc != 0:
        print(f"validate_config.py exited {rc}; inspect enrollment_candidates.json",
              file=sys.stderr)
        return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
