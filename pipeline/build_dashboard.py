#!/usr/bin/env python3
"""Builds the job-search dashboard: one self-contained HTML page for HTML Shelf.

Usage:
    .venv/bin/python pipeline/build_dashboard.py                # Downloads + dated copy in jobs/
    .venv/bin/python pipeline/build_dashboard.py --out DIR      # write only into DIR (first runs, tests)
    .venv/bin/python pipeline/build_dashboard.py --today 2026-09-19
    .venv/bin/python pipeline/build_dashboard.py --strict       # exit 1 on failure (tests only)

Added 2026-09-19. Spec: pipeline/DASHBOARD_SPEC.md.

READ-ONLY against every tracking file. It shows state and never sets it: marking
a role applied stays with mark_applied.py, outcomes with mark_outcome.py. It
imports nothing from the writers and must stay that way.

The page keeps four kinds of state, all in the Shelf's per-page storage:
  letters  an edit he saved to a cover letter (added 2026-11-12), keyed like the marks under
         `jobdash.letters.v1` as {text, base_sha, saved_at}. An inbox too: letter_edits.py
         applies it to the letter's files and writes jobs/letter_edit_results.json, which
         this script reads for "Edited by you" and for a refusal's reason. See the letter
         view section below, by read_letter().
  ticks  "I checked this site" on the manual list. The pipeline never reads them.
  leads  Tailor it / Pass on a weekly lead (added 2026-10-15, D41), keyed by LinkedIn job
         id under `jobdash.leads.v1`. Also an inbox: shelf_inbox.py records them in
         jobs/lead_marks.json through lead_marks.py, and a recorded lead leaves the page.
  marks  Sent / Skip / Later on a queue row, plus a one-click "skip everything older
         than the Fresh window" in the All view (added 2026-10-12, his go-ahead). These
         are an INBOX, not a record: shelf_inbox.py reads them at the start of the
         next run and applies them through mark_applied.py and mark_verdict.py.
         outcomes.csv stays the only record. This script still writes nothing but
         the page; once a mark is recorded its row drops out of the queue here (a
         skip verdict hides it), and the page forgets the mark.

Three lists, the ones where Aneesh is the bottleneck rather than the pipeline:

  queue   stage=surfaced, with a days-left countdown against age_report.py's
          45-day retirement. Default view is fresh roles by score, NOT "dies
          soonest": age_report.py's own finding is that an old surfaced row is
          usually a dead posting, so that sort leads with the least useful rows.
  manual  _blind_spot_companies + _unpollable_backlog_companies. last_checked is
          when the PIPELINE searched, not when he opened the site; the ticks
          fill that gap.
  quiet   stage=applied with outcome blank OR pending (most rows are blank, so
          reading only `pending` shows a sixth of reality), and only from the
          2026-07-28 outcome-data epoch on. Pre-epoch applied rows are
          unfalsifiable by standing decision (CLAUDE.md) and stay off the page.

Since 2026-10-12 the page also carries what used to be the long tail of the digest
email, read from jobs/brief_<date>.json (written at daily_task_prompt.md Step 5):
  today   the last run's picks on top, each with the run's read on it, what its
          cover letter promises, and what changed in the resume.
  run     the FYI lists and the run audit, collapsed.
And since 2026-10-15 what used to be the weekly channel report email, read from
jobs/weekly_leads_<date>.json (weekly_channel_report.py --page, Thursdays):
  leads   strong LinkedIn roles that never became a package, one row each with Tailor it
          and Pass, flags for anything that looks broken, and the channel numbers collapsed.
and, for a package that has one, the paste sheet field_sheet.py wrote
(tailored/<stem>_fields.json), with a click-to-copy value per form field. Sections
that file marks `personal` (address, phone) are never embedded in the page.
A missing or malformed brief or field sheet is skipped, never an error.

Since 2026-11-07 a role he hasn't sent yet, and a manual-check company, says who he knows
there: first-degree LinkedIn connections (name, title, when they connected), read at build
time from the warm-path kit's export, which lives outside this repo. Only exact names under
the kit's own matcher and pairs he confirmed in its reviewed_matches.json count, never a
look-alike. The names reach the page and nothing else; a missing kit means no contact lines
and one footer note saying so. The page shows who; it never drafts or sends anything.

jd_coverage_pct renders as a pass/fail chip at 80 and is never sortable, per the
standing rule that it is a gate and not a ranking signal.

A failed build must never fail the daily run: every failure prints one
`dashboard: FAILED ...` line, leaves yesterday's file in place, and exits 0. The
page itself shows a stale strip when a weekday run should have replaced it and
didn't (schedule-aware, so weekends don't cry wolf), because a failed build is otherwise indistinguishable from a quiet day.

This file is committed to a public repo. No company names, no sample rows.
"""
import csv
import hashlib
import html
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime
from urllib.parse import quote_plus

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SCRIPT_DIR)
OUTCOMES = os.path.join(SCRIPT_DIR, "outcomes.csv")
WATCHLIST = os.path.join(SCRIPT_DIR, "watchlist_companies.json")
QUEUE = os.path.join(SCRIPT_DIR, "enrollment_candidates.json")
TAILORED = os.path.join(REPO, "tailored")
APPLY_NOW = os.path.join(TAILORED, "apply_now")
JOBS_DIR = os.path.join(SCRIPT_DIR, "jobs")
DOWNLOADS = os.path.expanduser("~/Downloads")
OUT_NAME = "job_dashboard.html"

EPOCH = date(2026, 7, 28)
COVERAGE_GATE = 80
PDF_PREFIX = "Aneesh_Khan_"
KNOWN_STAGES = {"surfaced", "applied", "rejected", "closed", "expired", "tailored", ""}
MANUAL_GROUPS = (
    # (watchlist key, label, days before a tick goes stale). The stale windows
    # match how often the pipeline itself looks: daily rotation vs monthly.
    ("_blind_spot_companies", "Blind spot", 7),
    ("_unpollable_backlog_companies", "Backlog", 30),
)

try:
    from age_report import DEFAULT_DAYS as EXPIRY_DAYS
except Exception:  # the number has one home, but a broken import can't sink the build
    EXPIRY_DAYS = 45

try:
    from stages import SEND_PROVEN
except Exception:  # same rule as EXPIRY_DAYS; test_stages.py fails if this copy drifts from stages.py
    SEND_PROVEN = frozenset(("applied", "rejected", "interview", "assessment", "onsite", "offer"))


def parse_date(s):
    try:
        return date(*map(int, (s or "").strip().split("-")))
    except Exception:
        return None


def slug(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def norm_url(u):
    # Same normalization as mark_applied.py and shelf_inbox.py: it is the key a mark is
    # stored under on the page and matched by in the tracker, so all three must agree.
    return (u or "").strip().rstrip("/").lower()


def clip(v, n):
    return v.strip()[:n] if isinstance(v, str) else ""


def to_num(s):
    try:
        return float((s or "").strip())
    except ValueError:
        return None


def tier_of(score, cfg):
    if score is None:
        return ""
    if score >= cfg.get("company_cap_threshold", 110):
        return "priority"
    if score >= cfg.get("full_tailoring_threshold", 88):
        return "full"
    if score >= cfg.get("light_tailoring_threshold", 78):
        return "light"
    return "below"


def list_pdfs():
    """[(package slug, relative path, kind, in apply_now)], apply_now first.

    kind is "resume", "cover", or "ats". The `_ATS` file is the parser-friendly
    variant of the same package (the one to upload on Workday-class forms), so it
    shares the package's slug instead of counting as a second resume.
    """
    found = []
    for folder in (APPLY_NOW, TAILORED):
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for n in names:
            if not n.lower().endswith(".pdf") or not n.startswith(PDF_PREFIX):
                continue
            stem, kind = n[len(PDF_PREFIX):-4], "resume"
            for suffix, k in (("_cover", "cover"), ("_ats", "ats")):
                if stem.lower().endswith(suffix):
                    stem, kind = stem[:-len(suffix)], k
                    break
            found.append((slug(stem), os.path.relpath(os.path.join(folder, n), REPO), kind,
                          folder == APPLY_NOW))
    return found


def match_pdfs(company, pdfs, notes=""):
    """The package's PDFs: by the filename the row's notes record when they record
    exactly one package, else by company slug at the start of the filename.
    Ambiguous is reported, never guessed."""
    if notes:
        # Since 2026-10-09 a tracking row's notes name its package's PDFs. That is exact,
        # where the company-slug match below misses a company whose filename spelling
        # differs from its name (a dotted or abbreviated name, for one).
        named = [p for p in pdfs if p[2] == "resume" and os.path.basename(p[1]) in notes]
        if len({p[0] for p in named}) == 1:
            same = [p for p in pdfs if p[0] == named[0][0]]
            if any(p[3] for p in same):
                same = [p for p in same if p[3]]
            got = {k: [p for p in same if p[2] == k] for k in ("resume", "cover", "ats")}
            return {"resume": got["resume"][0][1] if got["resume"] else "",
                    "cover": got["cover"][0][1] if len(got["cover"]) == 1 else "",
                    "ats": got["ats"][0][1] if len(got["ats"]) == 1 else "",
                    "in_apply_now": same[0][3]}
    keys = [slug(company)]
    first = slug((company or "").split(" ")[0])
    if len(first) >= 4 and first not in keys:
        keys.append(first)
    for key in keys:
        if not key:
            continue
        hits = [p for p in pdfs if p[0].startswith(key)]
        if not hits:
            continue
        if any(p[3] for p in hits):  # prefer what's staged in apply_now
            hits = [p for p in hits if p[3]]
        resumes = [p for p in hits if p[2] == "resume"]
        covers = [p for p in hits if p[2] == "cover"]
        variants = [p for p in hits if p[2] == "ats"]
        if len(resumes) > 1 and notes:
            # Several roles at one company: the row's own notes usually name its file.
            named = [p for p in resumes if os.path.basename(p[1]) in notes]
            if len(named) == 1:
                stem = named[0][0]
                resumes, covers = named, [c for c in covers if c[0] == stem]
        if len(resumes) > 1:
            return {"note": f"{len(resumes)} PDFs match this company", "in_apply_now": hits[0][3]}
        if resumes:
            variants = [v for v in variants if v[0] == resumes[0][0]]
        return {"resume": resumes[0][1] if resumes else "",
                "cover": covers[0][1] if len(covers) == 1 else "",
                "ats": variants[0][1] if len(variants) == 1 else "",
                "in_apply_now": hits[0][3]}
    return {"note": "no PDF matched"}


def read_outcomes(today, cfg):
    with open(OUTCOMES, newline="", encoding="utf-8") as f:
        raw = list(csv.reader(f))
    header, rows = raw[0], raw[1:]
    ci = {n: i for i, n in enumerate(header)}
    need = ("company", "title", "url", "fit_score", "stage", "outcome", "surfaced_date", "applied_date")
    missing = [n for n in need if n not in ci]
    if missing:
        raise ValueError(f"outcomes.csv is missing columns {missing}; run repair_outcomes.py")

    def col(r, name):
        return r[ci[name]].strip() if name in ci else ""

    pdfs = list_pdfs()
    letter_results = read_letter_results()
    queue, quiet = [], []
    counts = {"bad_rows": 0, "in_process": 0, "pre_epoch_quiet": 0, "unknown_stages": [], "skipped": 0}
    for r in rows:
        if len(r) != len(header):
            counts["bad_rows"] += 1  # mark_applied.py silently skips these too
            continue
        stage = col(r, "stage")
        score = to_num(col(r, "fit_score"))
        base = {"company": col(r, "company"), "title": col(r, "title"), "url": col(r, "url"),
                "score": score, "channel": col(r, "source_channel")}
        if stage == "surfaced" and col(r, "his_verdict").lower().startswith("skip_"):
            # He passed on it (mark_verdict.py, usually by way of shelf_inbox.py). The row
            # keeps its stage until age_report.py retires it, but it isn't waiting on him.
            counts["skipped"] += 1
        elif stage == "surfaced":
            unmet_raw = col(r, "unmet_hard_reqs")
            unmet = to_num(unmet_raw)
            cov = to_num(col(r, "jd_coverage_pct"))
            trig = col(r, "hard_req_cap_trigger")
            item = dict(base,
                        key=norm_url(base["url"]) or slug(base["company"]) + "|" + slug(base["title"]),
                        tier=tier_of(score, cfg),
                        coverage_ok=None if cov is None else cov >= COVERAGE_GATE,
                        unmet=None if unmet_raw == "" else (int(unmet) if unmet is not None else -1),
                        unmet_text="" if unmet is not None else unmet_raw,
                        cap_trigger="" if trig in ("", "none") else trig,
                        cap_checked=trig != "",
                        ic_scope=col(r, "ic_scope").lower(),
                        surfaced=col(r, "surfaced_date") if parse_date(col(r, "surfaced_date")) else "")
            item.update(match_pdfs(item["company"], pdfs, col(r, "notes")))
            fields = read_fields(item.get("resume") or item.get("ats") or "")
            if fields:
                item["fields"] = fields
            if not col(r, "his_verdict"):
                # Any verdict on the row is his word that he sent it or passed on it, so only
                # a row with none gets its letter (letter_edits.py refuses the rest anyway).
                try:
                    attach_letter(item, col(r, "notes"), letter_results)
                except Exception:  # noqa: BLE001 - a letter that won't read costs its panel, not the queue
                    pass
            queue.append(item)
        elif stage == "applied" and col(r, "outcome") in ("", "pending"):
            sd, ad = parse_date(col(r, "surfaced_date")), parse_date(col(r, "applied_date"))
            anchor = sd or ad
            if not anchor or anchor < EPOCH:
                counts["pre_epoch_quiet"] += 1
                continue
            sent = ad or sd  # some applied rows carry no applied_date
            quiet.append(dict(base, applied=sent.isoformat(), applied_is_exact=bool(ad),
                              furthest_stage=col(r, "furthest_stage")))
        elif stage not in KNOWN_STAGES:
            counts["in_process"] += 1
            if stage not in counts["unknown_stages"]:
                counts["unknown_stages"].append(stage)
    return queue, quiet, counts


def read_manual(watch):
    out = []
    for key, label, stale_days in MANUAL_GROUPS:
        block = watch.get(key) or {}
        entries = block.get("companies", []) if isinstance(block, dict) else block
        for e in entries:
            if not isinstance(e, dict) or not e.get("name"):
                continue
            query = e.get("query", "")
            url = (e.get("careers_url") or "").strip()
            if url:
                link, kind = url, "careers"
            elif query:
                link, kind = "https://www.google.com/search?q=" + quote_plus(query), "search"
            else:
                link, kind = "", ""
            checked = e.get("last_checked") or ""
            hit = e.get("last_hit") or ""
            # Crude on purpose: it only drives a highlight, and the full text is on the row.
            live = bool(checked and hit.startswith(checked)
                        and not re.search(r"\b(no|null|none|nothing)\b", hit[:90], re.I))
            out.append({"key": slug(e["name"]), "name": e["name"], "group": label,
                        "stale_days": stale_days, "why": e.get("why", ""), "link": link,
                        "link_kind": kind, "last_checked": checked, "last_hit": hit,
                        "hit_is_live": live})
    return out


def read_backlog_counts():
    try:
        with open(QUEUE, encoding="utf-8") as f:
            q = json.load(f)
    except Exception:
        return {}
    entries = [e for b in ("pending", "enrolled", "rejected") for e in q.get(b, []) if isinstance(e, dict)]
    return {"manual_review_unsurfaced": sum(1 for e in entries
                                            if e.get("manual_review") and not e.get("manual_review_surfaced")),
            "unpollable_unreported": sum(1 for e in entries
                                         if e.get("unpollable") and not e.get("weekly_report_surfaced"))}


SCREENED_DAYS = 7
SCREENED_DISMISSED = "screened_dismissed.json"


def read_dismissed():
    """URLs he has passed on from the "Cleared, not tailored" list (added 2026-10-13).

    Source: jobs/screened_dismissed.json, `{"dismissed": [{"url": ...}, ...]}`, written
    by hand or by a session at his ask; a bare URL string works as an entry too, and
    any other field (company, title, date) is for whoever reads the file later. The
    daily run re-lists a cleared role every day it reads the JD again, so taking a row
    out of one day's screened file never held. A missing or malformed file hides
    nothing.
    """
    try:
        with open(os.path.join(JOBS_DIR, SCREENED_DISMISSED), encoding="utf-8") as f:
            entries = json.load(f).get("dismissed") or []
    except Exception:
        return set()
    urls = set()
    for e in entries if isinstance(entries, list) else []:
        url = e.get("url") if isinstance(e, dict) else e
        if isinstance(url, str) and url.strip():
            urls.add(url.strip())
    return urls


def read_screened(today):
    """Roles the daily run's JD screen cleared but did not tailor (added 2026-09-25).

    Source: jobs/screened_<date>.json, written at daily_task_prompt.md Step 6 from
    the Step 2-JD fan-out. Only the last SCREENED_DAYS of files are read; newest
    file wins per URL, and `first` keeps the earliest date it was cleared. A URL
    already in outcomes.csv at any stage is dropped: it was tailored, sent, or
    closed, and the queue or quiet list owns it now. A URL he dismissed is dropped
    the same way (see read_dismissed). Read-only like the rest.
    Returns (rows, days_with_a_file) so the page can tell "nothing cleared"
    from "the step never ran".
    """
    known = set()
    try:
        with open(OUTCOMES, encoding="utf-8", newline="") as f:
            known = {(r.get("url") or "").strip() for r in csv.DictReader(f)}
    except Exception:
        pass
    known |= read_dismissed()
    by_url, days = {}, 0
    for n in range(SCREENED_DAYS):
        d = date.fromordinal(today.toordinal() - n)
        path = os.path.join(JOBS_DIR, f"screened_{d.isoformat()}.json")
        try:
            with open(path, encoding="utf-8") as f:
                roles = json.load(f).get("roles") or []
        except Exception:
            continue
        days += 1
        for r in roles:
            url = (r.get("url") or "").strip()
            if not url or url in known or not isinstance(r, dict):
                continue
            if url in by_url:
                by_url[url]["first"] = d.isoformat()
                continue
            by_url[url] = {"company": r.get("company") or "", "title": r.get("title") or "",
                           "url": url, "score": to_num(str(r.get("score") or "")),
                           "loc": r.get("loc") or "", "pay": r.get("pay") or "",
                           "scope": r.get("scope") or "", "why": r.get("why") or "",
                           "gap": r.get("gap") or "", "last": d.isoformat(), "first": d.isoformat()}
    return list(by_url.values()), days


BRIEF_DAYS = 5


def read_brief(today):
    """The newest jobs/brief_<date>.json from the last BRIEF_DAYS days, or None.

    Written by the daily run at Step 5 with the Write tool, so it is model output:
    everything is type-checked and length-capped here, and anything that doesn't
    fit is dropped rather than trusted. Picks are keyed the way queue rows are.
    """
    for n in range(BRIEF_DAYS):
        d = date.fromordinal(today.toordinal() - n)
        try:
            with open(os.path.join(JOBS_DIR, f"brief_{d.isoformat()}.json"), encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            continue
        if not isinstance(raw, dict):
            continue
        picks = {}
        for p in raw.get("picks") or []:
            key = norm_url(p.get("url")) if isinstance(p, dict) else ""
            if not key:
                continue
            picks[key] = {"read": clip(p.get("read"), 900), "commitment": clip(p.get("commitment"), 700),
                          "check": [clip(x, 300) for x in (p.get("check") or []) if clip(x, 300)][:8],
                          "changes": [clip(x, 400) for x in (p.get("changes") or []) if clip(x, 400)][:12],
                          "note_draft": clip(p.get("note_draft"), 700)}
        sections = []
        for s in raw.get("sections") or []:
            if not isinstance(s, dict) or not clip(s.get("title"), 80):
                continue
            lines = []
            for ln in s.get("lines") or []:
                if isinstance(ln, str):
                    ln = {"text": ln}
                if isinstance(ln, dict) and clip(ln.get("text"), 700):
                    lines.append({"text": clip(ln.get("text"), 700), "url": clip(ln.get("url"), 600),
                                  "label": clip(ln.get("label"), 30)})
            sections.append({"title": clip(s.get("title"), 80), "note": clip(s.get("note"), 600),
                             "lines": lines[:120]})
        return {"run_date": d.isoformat(), "note": clip(raw.get("note"), 900),
                "alerts": [clip(x, 500) for x in (raw.get("alerts") or []) if clip(x, 500)][:10],
                "picks": picks, "sections": sections[:16]}
    return None


# A week's leads stay up until the next week's file replaces them, with a few days' slack
# for a missed Thursday. Older than this and the section says there's no current report.
LEADS_DAYS = 13
LEAD_LISTS = ("unreachable", "never_picked", "no_board")
LEAD_ID_RE = re.compile(r"^\d{6,12}$")
LEAD_MARKS = "lead_marks.json"
LEAD_MARK_DAYS = 21   # backstop: a mark no run has recorded in three weeks is let go


def read_lead_marks():
    """{job id: entry} from jobs/lead_marks.json. Read here, never written: lead_marks.py
    owns the file and shelf_inbox.py fills it. A missing or malformed file hides nothing."""
    try:
        with open(os.path.join(JOBS_DIR, LEAD_MARKS), encoding="utf-8") as f:
            leads = json.load(f).get("leads")
    except Exception:
        return {}
    return {k: v for k, v in leads.items() if isinstance(v, dict)} if isinstance(leads, dict) else {}


COMPANY_ABOUT = "company_about.json"


def company_key(name):
    # Same key as company_about.norm(), which this file can't import. Change both together.
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def read_company_about():
    """{company key: {about, industry, size}} from jobs/company_about.json (added 2026-10-15).

    company_about.py fills it from each company's public LinkedIn page, so a weekly lead can
    say what the company does. Misses are left out. A missing or malformed file hides nothing.
    """
    try:
        with open(os.path.join(JOBS_DIR, COMPANY_ABOUT), encoding="utf-8") as f:
            comps = json.load(f).get("companies")
    except Exception:
        return {}
    out = {}
    for k, v in (comps.items() if isinstance(comps, dict) else ()):
        if isinstance(v, dict) and "miss" not in v:
            info = {"about": clip(v.get("about"), 300), "industry": clip(v.get("industry"), 60),
                    "size": clip(v.get("size"), 40)}
            if info["about"] or info["industry"]:
                out[k] = info
    return out


def read_leads(today):
    """The newest jobs/weekly_leads_<date>.json from the last LEADS_DAYS days, or None.

    Written by weekly_channel_report.py --page (daily_task_prompt.md Step 6.5, Thursdays).
    A lead he has already answered (any entry in lead_marks.json) is left off, which is how
    a recorded Tailor it or Pass leaves the page. Everything is type-checked and capped,
    same as the brief.
    """
    for n in range(LEADS_DAYS + 1):
        d = date.fromordinal(today.toordinal() - n)
        try:
            with open(os.path.join(JOBS_DIR, f"weekly_leads_{d.isoformat()}.json"), encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            continue
        if not isinstance(raw, dict):
            continue
        answered = read_lead_marks()
        about = read_company_about()
        rows, seen, handled = [], set(), 0
        for x in raw.get("leads") or []:
            if not isinstance(x, dict):
                continue
            jid = clip(str(x.get("id") or ""), 20)
            lst = x.get("list") if x.get("list") in LEAD_LISTS else ""
            if not LEAD_ID_RE.match(jid) or not lst or jid in seen:
                continue
            seen.add(jid)
            if jid in answered:
                handled += 1
                continue
            seen_n = x.get("seen")
            company = clip(x.get("company"), 120) or "?"
            rows.append({"id": jid, "list": lst, "company": company,
                         "title": clip(x.get("title"), 200) or "?", "url": clip(x.get("url"), 600),
                         "tier": clip(x.get("tier"), 12), "loc": clip(x.get("loc"), 20),
                         "seen": seen_n if isinstance(seen_n, int) and 0 < seen_n < 1000 else 1,
                         "first": clip(x.get("first"), 10), "note": clip(x.get("note"), 300),
                         **about.get(company_key(company), {})})
        health = []
        for s in raw.get("health") or []:
            if isinstance(s, dict) and clip(s.get("title"), 80):
                lines = [ln[:400] for ln in (s.get("lines") or []) if isinstance(ln, str)][:80]
                health.append({"title": clip(s.get("title"), 80), "lines": lines, "pre": bool(s.get("pre"))})
        window = raw.get("window") if isinstance(raw.get("window"), dict) else {}
        waiting = sum(1 for v in answered.values() if v.get("action") == "tailor" and not v.get("fetched"))
        return {"date": d.isoformat(), "start": clip(window.get("start"), 10),
                "end": clip(window.get("end"), 10) or d.isoformat(),
                "flags": [clip(x, 400) for x in (raw.get("flags") or []) if clip(x, 400)][:8],
                "health": health[:6], "rows": rows, "handled": handled, "waiting": waiting}
    return None


def read_fields(pdf_rel):
    """Non-personal sections of the package's paste sheet (field_sheet.py), or None."""
    if not pdf_rel:
        return None
    stem = os.path.basename(pdf_rel)[:-4]
    if stem.lower().endswith("_ats"):
        stem = stem[:-4]
    try:
        with open(os.path.join(TAILORED, stem + "_fields.json"), encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return None
    out = []
    for s in (raw.get("sections") if isinstance(raw, dict) else None) or []:
        if not isinstance(s, dict) or s.get("personal") is not False:
            continue  # only sections explicitly marked non-personal reach the page
        fs = [{"label": clip(f.get("label"), 80),
               "value": f["value"][:4000] if isinstance(f.get("value"), str) else "",
               "needs_you": bool(f.get("needs_you"))}
              for f in s.get("fields") or [] if isinstance(f, dict) and clip(f.get("label"), 80)]
        # A section with nothing to paste (the "only you" list of screening questions)
        # stays in the .md sheet. On the page it would be labels with no values, and
        # those labels come from his profile file, which this page has no reason to copy.
        if any(f["value"] for f in fs):
            out.append({"title": clip(s.get("title"), 100), "fields": fs[:40]})
    return out or None


# The letter view (added 2026-11-12). A queue row whose package has a cover letter carries the
# letter itself, so he can read it, copy it, and save an edit to it on the page. A saved edit
# waits in the Shelf's storage under `jobdash.letters.v1` and letter_edits.py applies it to the
# letter's files; this script still writes nothing but the page. Whatever decides what a
# letter's body IS lives here (parse_letter, letter_sha, edit_paragraphs) and letter_edits.py
# imports it, so the hash a saved edit carries and the hash the applier checks can't differ.
LETTER_RESULTS = "letter_edit_results.json"  # letter_edits.py owns it; read here, never written
LETTER_MAX_CHARS = 30000                     # a letter runs about 2,500; near this it isn't one
LETTER_FURNITURE_WORDS = 25                  # fit_check.py's TWIN_FURNITURE_WORDS, same purpose
# What a saved edit has to be before it can replace a letter. The page checks these when he
# saves and letter_edits.py checks them again before it writes.
LETTER_LIMITS = {"min_paragraphs": 2, "min_words": 150, "max_words": 600}
_MD_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!])")
_PACKAGE_RE = re.compile(r"(?<![A-Za-z0-9_])(" + re.escape(PDF_PREFIX) + r"[A-Za-z0-9_\-]+?)(?i:_cover|_ats)?\.pdf")


def package_stems(notes):
    """Every package a tracker row's notes name, as file stems."""
    return {m.group(1) for m in _PACKAGE_RE.finditer(notes or "")}


def package_stem(notes):
    """The one package a tracker row's notes name ("tailored/apply_now/<stem>.pdf +
    _cover.pdf"), as a file stem. "" when they name none, or more than one."""
    stems = package_stems(notes)
    return stems.pop() if len(stems) == 1 else ""


def letter_plain(text):
    """The words a reader sees: renderer markup off, whitespace collapsed. The same
    normalization fit_check.py's twin check runs on both of a letter's files."""
    t = re.sub(r"<br\s*/?>", " ", str(text or ""))
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t).replace("\u00a0", " ")
    return re.sub(r"\s+", " ", t).strip()


def edit_paragraphs(text):
    """Text from the page's edit box as paragraphs: split on blank lines, the whitespace
    inside each collapsed. lparas() in the page script does the same."""
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    return [" ".join(p.split()) for p in re.split(r"\n\s*\n", text) if p.strip()]


def letter_sha(paras):
    """The hash a saved edit carries as base_sha: the body it was made against."""
    return hashlib.sha256("\n\n".join(paras).encode("utf-8")).hexdigest()[:16]


def parse_letter(md_text, data):
    """(letter, "") when the .md and the JSON hold the same paragraphs, else (None, why).

    The body is the run of blank-line-separated blocks in the .md that equal the JSON's
    paragraphs, in order, compared as fit_check.py's twin check compares them. Whatever sits
    above it (date, recipient) and below it (sign-off) is kept exactly as written. A letter
    whose two files disagree is not shown: the .md is what he pastes, the JSON is what the PDF
    renders from, and picking one of them would be a guess.
    """
    raw_json = data.get("paragraphs") if isinstance(data, dict) else None
    if not isinstance(raw_json, list) or not raw_json or not all(isinstance(p, str) for p in raw_json):
        return None, "its JSON has no list of paragraphs"
    if not isinstance(md_text, str) or len(md_text) > LETTER_MAX_CHARS:
        return None, "its .md is too long to be a letter"
    text = md_text.replace("\r\n", "\n").replace("\r", "\n")
    spans, pos = [], 0
    for m in re.finditer(r"\n\s*\n", text):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(text)))
    spans = [(a, b) for a, b in spans if text[a:b].strip()]
    in_md = [letter_plain(_MD_ESCAPE.sub(r"\1", text[a:b].replace("**", ""))) for a, b in spans]
    paras = [letter_plain(p) for p in raw_json]
    n = len(paras)
    first = in_md.index(paras[0]) if paras[0] and paras[0] in in_md else -1
    if first < 0 or not all(paras) or in_md[first:first + n] != paras:
        return None, "its .md and the JSON the PDF renders from don't hold the same paragraphs"
    outside = in_md[:first] + in_md[first + n:]
    if any(len(b.split()) > LETTER_FURNITURE_WORDS for b in outside):
        return None, "its .md has a paragraph the JSON the PDF renders from lacks"
    return {"head": text[:spans[first][0]].strip(), "tail": text[spans[first + n - 1][1]:].strip(),
            "paras": paras, "sha": letter_sha(paras),
            # The two files' own spelling of each paragraph (bold, entities), for letter_edits.py
            # to carry over on the paragraphs an edit leaves alone. Never embedded in the page.
            "raw_md": [text[a:b].strip() for a, b in spans[first:first + n]],
            "raw_json": list(raw_json), "data": data}, ""


def read_letter(tailored, stem):
    """(letter, "") for tailored/<stem>_cover.md and _cover_data.json, or (None, why).
    why is "" when the package simply has no letter, which a light-tier package doesn't."""
    md_path = os.path.join(tailored, stem + "_cover.md")
    json_path = os.path.join(tailored, stem + "_cover_data.json")
    if not os.path.exists(md_path):
        return None, ""
    if not os.path.exists(json_path):
        return None, "it has no _cover_data.json beside the .md"
    try:
        with open(md_path, encoding="utf-8") as f:
            md_text = f.read(LETTER_MAX_CHARS + 1)
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:  # noqa: BLE001 - both files are model output
        return None, f"its files couldn't be read ({type(e).__name__})"
    letter, why = parse_letter(md_text, data)
    if letter:
        letter["stem"] = stem
    return letter, why


# The three sentences the letter view marks. Each rule either finds exactly one sentence it
# can stand behind or finds nothing; there is no fallback sentence and no fallback paragraph.
_ABBREVIATIONS = frozenset(("mr", "mrs", "ms", "dr", "sr", "jr", "st", "vs", "etc", "inc", "co",
                            "corp", "ltd", "no", "e.g", "i.e", "a.m", "p.m", "u.s"))
_CLOSERS = "\"')\\]\u201d\u2019"
_SENTENCE_END = re.compile(r"[.!?]+[" + _CLOSERS + r"]*(?=\s|$)")
_SENTENCE_START = re.compile("[\"'(\\[\u201c\u2018]?[A-Z0-9]")
_ENDS_CLEANLY = re.compile(r"[.!?][" + _CLOSERS + r"]*$")
_MONTHS = "January|February|March|April|June|July|August|September|October|November|December"
_WEEKDAYS = "Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday"
_AP = "(?:'|\u2019)"
# Why: he says he's applying, or says outright why he wants the role or what drew him to it.
_WHY = re.compile(r"\bI(?:" + _AP + r"m| am) applying\b"
                  r"|\bwhy I(?:" + _AP + r"d| would)? want the\b.*\brole\b"
                  r"|\b(?:drew|draws) me to the\b.*\brole\b")
# Promise: a time he can be held to, and a verb that commits him to something by then.
_PROMISE_WHEN = re.compile(
    # a date: a month, or a weekday that isn't "every Monday" ("May" only where it can't be the verb)
    r"\b(?:" + _MONTHS + r")\b|(?<!every )\b(?:" + _WEEKDAYS + r")\b|\bMay \d|\b(?:by|in|before|of|through|until|from) May\b"
    r"|\b(?:this|next) (?:week|weekend|month|quarter)\b|\b(?:tonight|tomorrow)\b|\bby then\b"
    # the hiring process as the deadline
    r"|\b(?:[Bb]efore|[Bb]y the time) (?:we|you and I) (?:talk|speak|meet)\b"
    r"|\b(?:[Bb]efore|[Dd]uring|[Aa]head of) (?:the|a|an|our|my|your) (?:first |next )?(?:interview|screen|call)\b"
    # his first days in the role
    r"|\b[Mm]y first (?!question\b)|\b(?:[Ii]n|[Ww]ithin|[Dd]uring|[Oo]ver|[Aa]t|[Ff]or|[Bb]y the end of) the first\b"
    r"|\bfirst (?:30|60|90|thirty|sixty|ninety) days\b|\b(?:day|week) (?:one|1)\b"
    # before he does the thing itself ("Before I change a setting, I'd ...")
    r"|\b[Bb]efore I (?!was\b|had\b|did\b|got\b|came\b|left\b|took\b|ran\b|led\b|\w+ed\b)\w+")
_PROMISE_VERB = re.compile(
    # "I'll" or "I'd", unless it is a question about himself ("how I'd spend it"), a past
    # perfect ("I'd never used one"), or a wish ("I'd like to hear"); "I'm" only with a verb
    # under way ("I'm reading", not "I'm keen on")
    r"(?<![Hh]ow )(?<![Ww]hat )(?<![Ww]here )(?<![Ww]hich )\bI" + _AP + r"(?:ll|d)\b"
    r"(?! (?:also )?(?:never|already|just|been|had|once|only|rather|want|like|love|welcome|enjoy|be glad|be happy)\b)"
    r"|\bI" + _AP + r"m (?:\w+ )?\w+ing\b"
    # or the result stated for him: "we'd count it together", "it'll be done", "they would have seen it"
    r"|\b(?:we|it)" + _AP + r"(?:ll|d)\b|\b(?:will|would) have\b")
# A closing question dressed as a plan ("I'd set up my first week differently depending on
# which it is") names a time and a first-person verb and promises nothing.
_NOT_A_PROMISE = re.compile(r"\bI" + _AP + r"d rather\b|\bdepending on\b|\bthe answer\b")


def sentence_spans(par):
    """[(start, end)] for each sentence of one paragraph of plain text.

    A full stop ends a sentence only when what follows starts like one, and never after a
    listed abbreviation or a lone initial. When that is wrong it joins two sentences; it
    doesn't cut one in half, which is the safer way to be wrong for a mark on the page.
    """
    spans, start = [], 0
    for m in _SENTENCE_END.finditer(par):
        rest = par[m.end():].lstrip()
        if rest and not _SENTENCE_START.match(rest):
            continue
        if par[m.start()] == ".":
            word = re.search(r"[A-Za-z.]+$", par[start:m.start()])
            w = word.group() if word else ""
            if w.lower() in _ABBREVIATIONS or (len(w) == 1 and w.isupper() and w != "I"):
                continue
        spans.append((start, m.end()))
        start = len(par) - len(rest)
    if start < len(par):
        spans.append((start, len(par)))
    return spans


def is_promise(sentence):
    return bool(_PROMISE_WHEN.search(sentence) and _PROMISE_VERB.search(sentence)
                and not _NOT_A_PROMISE.search(sentence))


def find_letter_sentences(paras):
    """{"why": ..., "tie": ..., "promise": ...}: sentences quoted from the letter, each key
    present only when its rule found exactly one. The rules:

      why      the only sentence in the letter that says "I'm applying" (or "I am applying"),
               "why I want the ... role" (or "why I'd want"), or "drew me to the ... role"
               (or "draws me"), and it sits in the first or second paragraph.
      tie      the last sentence of the paragraph before the last, in a letter of three
               paragraphs or more, when it ends in a full stop and isn't the why sentence.
      promise  the only sentence in the last paragraph that names a time (_PROMISE_WHEN: a
               month or weekday; this or next week, month, or quarter; "by then"; before we
               talk or before an interview; "my first ...", "in the first ..."; "before I"
               and a present-tense verb), commits to something by then (_PROMISE_VERB:
               "I'll", "I'd", "I'm ...ing", "we'd", "it'll", "would have", but not "how I'd",
               "I'd never", or "I'd like"), and isn't a question about the role
               (_NOT_A_PROMISE).
    """
    out = {}
    sents = [[p[a:b] for a, b in sentence_spans(p)] for p in paras]
    hits = [(i, s) for i, ss in enumerate(sents) for s in ss if _WHY.search(s)]
    if len(hits) == 1 and hits[0][0] <= 1 and _ENDS_CLEANLY.search(hits[0][1]):
        out["why"] = hits[0][1]
    if len(paras) >= 3 and sents[-2]:
        last = sents[-2][-1]
        if _ENDS_CLEANLY.search(last) and last != out.get("why"):
            out["tie"] = last
    if len(paras) >= 2:
        made = [s for s in sents[-1] if is_promise(s)]
        if len(made) == 1 and _ENDS_CLEANLY.search(made[0]) and made[0] not in out.values():
            out["promise"] = made[0]
    return out


def read_letter_results():
    """{row key: {"last": ..., "applied": ...}} from jobs/letter_edit_results.json, which
    letter_edits.py writes after it applies or refuses an edit. Missing or malformed: {}."""
    try:
        with open(os.path.join(JOBS_DIR, LETTER_RESULTS), encoding="utf-8") as f:
            rows = json.load(f).get("rows")
    except Exception:
        return {}
    return {k: v for k, v in rows.items() if isinstance(v, dict)} if isinstance(rows, dict) else {}


def matched_stem(item):
    """The package match_pdfs() settled on for a row, as a file stem, or ""."""
    for kind, cut in (("resume", len(".pdf")), ("cover", len("_cover.pdf")), ("ats", len("_ATS.pdf"))):
        if item.get(kind):
            return os.path.basename(item[kind])[:-cut]
    return ""


def attach_letter(item, notes, results):
    """Adds `letter` to a queue row whose package has one, or `letter_note` when the letter is
    there and can't be shown. The page gets the words and nothing about the files."""
    named = package_stem(notes)
    stem = named or matched_stem(item)
    if not stem:
        return
    letter, why = read_letter(TAILORED, stem)
    if letter is None:
        if why:
            item["letter_note"] = why
        return
    page = {"head": letter["head"], "tail": letter["tail"], "paras": letter["paras"],
            "sha": letter["sha"], "marks": find_letter_sentences(letter["paras"])}
    if named != stem:
        # letter_edits.py finds a row's files by the package its notes name, and nothing else.
        page["no_edit"] = "This row's tracker notes don't name its package, so an edit made here couldn't be matched to the files."
    res = results.get(item["key"]) or {}
    done, last = res.get("applied"), res.get("last")
    if isinstance(done, dict) and done.get("new_sha") == letter["sha"]:
        # Still his version on disk. A later rewrite of the letter changes the hash and drops the tag.
        page["edited"] = clip(done.get("saved_at"), 40) or clip(done.get("at"), 10)
    if isinstance(last, dict) and last.get("status") in ("refused", "failed"):
        page["refused"] = {"reason": clip(last.get("reason"), 400), "saved_at": clip(last.get("saved_at"), 40),
                           "base_sha": clip(last.get("base_sha"), 64)}
    item["letter"] = page


# Who he knows at each company (added 2026-11-07). The export, the matcher, and his confirmed
# pairs all stay in the warm-path kit and are read fresh at each build. A ping rides on a role
# he'd apply to, before he applies, so the line goes on rows not yet sent and on manual checks.
WARM_PATH_KIT = os.path.expanduser("~/Documents/Projects/Career/warm-path-map")
KNOW_PER_ROW = 12  # the page shows three; the rest are in a tooltip


def connected_on(s):
    for fmt in ("%d %b %Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def read_contacts():
    """(lookup, meta). lookup(company) lists the connections he has there, newest first, or
    lookup is None and meta["note"] says why.

    The kit's wpm_names.py is loaded by path, not imported, so nothing in the kit's folder can
    shadow a pipeline module. Exact means equal under its exact_keys(), which counts a name the
    string itself declares ("X, formerly Y", "X / Y"); a pair from reviewed_matches.json counts
    only in the direction he confirmed it, [company as LinkedIn writes it, company on his lists].
    Only the name, company, title, and connected-on columns are read; email and profile URL never are.
    """
    path = os.path.join(WARM_PATH_KIT, "export", "Connections.csv")
    if not os.path.exists(path):
        return None, {"note": "the connections export wasn't found"}
    try:
        spec = importlib.util.spec_from_file_location("wpm_names", os.path.join(WARM_PATH_KIT, "scripts", "wpm_names.py"))
        wn = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wn)
        with open(path, "rb") as f:
            raw = f.read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        rows = list(csv.reader(io.StringIO(text, newline="")))
        # LinkedIn's export opens with a "Notes:" preamble, so the header is found by its columns.
        head = next((i for i, r in enumerate(rows) if {"first name", "company"} <= {c.strip().lower() for c in r}), None)
        if head is None:
            return None, {"note": "the connections export has no header row"}
        ci = {c.strip().lower(): i for i, c in enumerate(rows[head])}

        def cell(r, name):
            i = ci.get(name)
            return r[i].strip() if i is not None and i < len(r) else ""

        by_key, by_primary = {}, {}
        for r in rows[head + 1:]:
            name = clip(" ".join(filter(None, (cell(r, "first name"), cell(r, "last name")))), 80)
            co = clip(cell(r, "company"), 120)
            if not name or not co:
                continue
            p = {"name": name, "title": clip(cell(r, "position"), 120), "company": co,
                 "since": connected_on(cell(r, "connected on"))}
            for k, _ in wn.exact_keys(co):
                by_key.setdefault(k, []).append(p)
            by_primary.setdefault(wn.exact_key(co), []).append(p)
        accepted = {}
        rpath = os.path.join(WARM_PATH_KIT, "data", "reviewed_matches.json")
        if os.path.exists(rpath):
            with open(rpath, encoding="utf-8") as f:
                for pair in json.load(f).get("accept") or []:
                    if isinstance(pair, list) and len(pair) == 2 and all(isinstance(x, str) for x in pair):
                        accepted.setdefault(wn.exact_key(pair[1]), set()).add(wn.exact_key(pair[0]))
        risk = getattr(wn, "common_name_risk", lambda name: "")
        as_of = date.fromtimestamp(os.path.getmtime(path)).isoformat()
    except Exception as e:  # noqa: BLE001 - the kit is outside this repo; a fault there costs the lines, not the page
        return None, {"note": f"the connections export couldn't be read ({type(e).__name__})"}

    def lookup(company):
        keys = [k for k, _ in wn.exact_keys(company or "")]
        found = {}
        for k in keys:
            for p in by_key.get(k, ()):
                found.setdefault(id(p), (p, False))
            for ck in accepted.get(k, ()):
                for p in by_primary.get(ck, ()):
                    found.setdefault(id(p), (p, True))
        out = []
        for p, confirmed in found.values():
            item = {"name": p["name"], "title": p["title"], "since": p["since"]}
            if wn.exact_key(p["company"]) != wn.exact_key(company):
                item["at"] = p["company"]  # a declared name or a pair he confirmed: say which company
            if not confirmed and risk(p["company"]):
                item["check"] = risk(p["company"])
            out.append(item)
        out.sort(key=lambda x: x["since"], reverse=True)
        return out[:KNOW_PER_ROW]

    return lookup, {"as_of": as_of, "note": ""}


def attach_contacts(data):
    """Adds `know` to every row not yet sent and every manual check, and returns the meta."""
    lookup, meta = read_contacts()
    if lookup is None:
        return meta
    rows = data["queue"] + data["screened"] + ((data.get("leads") or {}).get("rows") or [])
    for x in rows + data["manual"]:
        know = lookup(x.get("company") or x.get("name"))
        if know:
            x["know"] = know
    meta["rows"] = sum(1 for x in rows if x.get("know"))
    return meta


# The Progress section, dashboard phase two (added 2026-10-15, D42): sends a day, interview
# rounds, and what came of each send. Sends count from the epoch only; rounds are dated by
# when they happened, which was never in doubt, so the log keeps the earlier ones too.
# SENT_STAGES is the set in stages.py where the stage alone proves a send; a `closed`
# row is not in it and read_progress() counts one only with evidence.
SENT_STAGES = SEND_PROVEN
FURTHEST_RANK = {"applied": 0, "assessment": 1, "interview": 2, "onsite": 3, "offer": 4}
TARGET_PER_DAY = (6, 7)  # his ramp target, set 2026-10-15
GHOST_DAYS = 30          # 24 of the first 27 post-epoch rejections arrived inside 30 days
INTERVIEWS = "interviews.json"  # written by log_interview.py, from interview-loop's Step 5
ROUND_KINDS = ("screen", "interview", "onsite", "assessment")


def read_confirmations():
    """What the Step 0.5 confirmation files name: posting URLs, and (company, title) pairs
    for the receipts that gave no URL. Only consulted for `closed` rows, below."""
    urls, named = set(), []
    try:
        names = [n for n in os.listdir(JOBS_DIR) if n.startswith("confirmations_") and n.endswith(".json")]
    except OSError:
        return urls, named
    for n in names:
        try:
            with open(os.path.join(JOBS_DIR, n), encoding="utf-8") as f:
                items = json.load(f).get("confirmations") or []
        except Exception:
            continue
        for c in items if isinstance(items, list) else []:
            if not isinstance(c, dict):
                continue
            if clip(c.get("url"), 600):
                urls.add(norm_url(c["url"]))
            elif clip(c.get("company"), 120):
                named.append((slug(c["company"]), clip(c.get("title"), 200).lower()))
    return urls, named


def read_rounds():
    """Interview rounds from jobs/interviews.json, oldest first, plus a note when the log is
    missing or partly unreadable. A round with no number is numbered by its company's order."""
    path = os.path.join(JOBS_DIR, INTERVIEWS)
    if not os.path.exists(path):
        return [], "No interview log yet (pipeline/jobs/interviews.json)."
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f).get("rounds")
    except Exception as e:
        return [], f"The interview log could not be read ({type(e).__name__}), so no rounds are shown."
    out, bad = [], 0
    for r in raw if isinstance(raw, list) else []:
        d = parse_date(r.get("date")) if isinstance(r, dict) else None
        if not d or r.get("kind") not in ROUND_KINDS or not clip(r.get("company"), 120):
            bad += 1
            continue
        n = r.get("round")
        out.append({"date": d.isoformat(), "company": clip(r["company"], 120), "kind": r["kind"],
                    "round": n if isinstance(n, int) and not isinstance(n, bool) and 0 < n < 50 else None,
                    "label": clip(r.get("label"), 120), "url": clip(r.get("url"), 600)})
    out.sort(key=lambda x: x["date"])
    seen = {}
    for x in out:
        if x["kind"] != "assessment":
            seen[slug(x["company"])] = seen.get(slug(x["company"]), 0) + 1
            if x["round"] is None:
                x["round"] = seen[slug(x["company"])]
    note = f"{bad} unreadable entr{'y' if bad == 1 else 'ies'} in the interview log were skipped." if bad else ""
    return out, note


def read_progress(today):
    """Sends a day since the epoch, interview rounds, and the funnel by send week.

    A send is a row past `surfaced` at a stage that proves it went out (SEND_PROVEN in
    stages.py), dated by applied_date, which a confirmation or a Sent mark sets. A
    `closed` row counts only with evidence it went out: a sent verdict, or a confirmation
    file that names it. Today's Sent clicks not yet recorded are added on the page itself.
    """
    with open(OUTCOMES, newline="", encoding="utf-8") as f:
        raw = list(csv.reader(f))
    header, body = raw[0], raw[1:]
    ci = {n: i for i, n in enumerate(header)}

    def col(r, name):
        return r[ci[name]].strip() if name in ci else ""

    conf_urls, conf_named = read_confirmations()
    sends, undated = [], 0
    for r in body:
        if len(r) != len(header):
            continue
        stage, url, co = col(r, "stage"), norm_url(col(r, "url")), col(r, "company")
        if stage == "closed":
            title = col(r, "title").lower()
            if not (col(r, "his_verdict").startswith("sent") or (url and url in conf_urls)
                    or any(c == slug(co) and (not t or t in title) for c, t in conf_named)):
                continue
        elif stage not in SENT_STAGES:
            continue
        sent = parse_date(col(r, "applied_date"))
        exact = sent is not None
        sent = sent or parse_date(col(r, "surfaced_date"))
        rank = max(FURTHEST_RANK.get(col(r, k).lower(), 0) for k in ("furthest_stage", "stage", "outcome"))
        sends.append({"date": sent, "exact": exact, "company": clip(co, 120), "url": url,
                      "stage": stage, "rank": rank, "rounds": []})
        undated += sent is None

    # Each round attaches to the send it belongs to: by posting URL, else the company's latest
    # send on or before the round. Pre-epoch sends are candidates too, so an old process's
    # round never lands on a newer application to the same company.
    rounds, note = read_rounds()
    by_url = {s["url"]: s for s in sends if s["url"]}
    for x in rounds:
        s = by_url.get(norm_url(x["url"])) if x["url"] else None
        if s is None:
            d = parse_date(x["date"])
            same = [s for s in sends if slug(s["company"]) == slug(x["company"]) and (s["date"] is None or s["date"] <= d)]
            s = max(same, key=lambda s: s["date"] or date.min) if same else None
        if s is not None:
            s["rounds"].append(x)

    days, weeks, inexact, pre_epoch = {}, {}, 0, 0
    funnel = dict.fromkeys(("sent", "screen", "later", "offer", "interviewed", "assessment",
                            "rejected", "closed", "ghosted", "waiting"), 0)
    for s in sends:
        if s["date"] is None:
            continue
        if s["date"] < EPOCH:
            pre_epoch += 1
            continue
        inexact += not s["exact"]
        days.setdefault(s["date"].isoformat(), []).append(s["company"] or "?")
        talks = [x for x in s["rounds"] if x["kind"] != "assessment"]
        f = {"sent": 1, "screen": int(bool(talks) or s["rank"] >= 2),
             "later": int(len(talks) >= 2 or s["rank"] >= 3), "offer": int(s["rank"] >= 4)}
        if f["screen"]:
            bucket = "interviewed"
        elif s["stage"] in ("rejected", "closed"):
            bucket = s["stage"]
        elif s["rank"] == 1 or s["rounds"]:
            bucket = "assessment"
        elif (today - s["date"]).days >= GHOST_DAYS:
            bucket = "ghosted"
        else:
            bucket = "waiting"
        f[bucket] = 1
        wk = date.fromordinal(s["date"].toordinal() - s["date"].weekday()).isoformat()
        w = weeks.setdefault(wk, dict.fromkeys(funnel, 0))
        for k, v in f.items():
            w[k] += v
            funnel[k] += v
    return {"epoch": EPOCH.isoformat(), "target": list(TARGET_PER_DAY), "ghost_days": GHOST_DAYS,
            "days": {k: sorted(v, key=str.lower) for k, v in sorted(days.items())},
            "inexact": inexact, "pre_epoch": pre_epoch, "undated": undated,
            "rounds": [{k: x[k] for k in ("date", "company", "kind", "round", "label")} for x in rounds],
            "rounds_note": note, "funnel": funnel,
            "weeks": [dict(v, week=k) for k, v in sorted(weeks.items())]}


def build_data(today, now):
    with open(WATCHLIST, encoding="utf-8") as f:
        watch = json.load(f)
    queue, quiet, counts = read_outcomes(today, watch.get("_scoring_config", {}))
    counts.update(read_backlog_counts())
    screened, counts["screened_days"] = read_screened(today)
    try:
        progress = read_progress(today)
    except Exception as e:  # noqa: BLE001 - a bad chart input must not take the queue down with it
        progress = {"error": f"{type(e).__name__}: {e}"[:200]}
    data = {"generated": now.strftime("%Y-%m-%dT%H:%M"), "expiry_days": EXPIRY_DAYS, "progress": progress,
            "fresh_days": 14, "expiring_days": 7, "quiet_days": 10,
            # The task runs `0 3 * * 1-5`; by 8 AM a weekday's page should exist. JS weekday numbers.
            "run_weekdays": [1, 2, 3, 4, 5], "run_ready_hour": 8,
            "queue": queue, "quiet": quiet, "manual": read_manual(watch), "counts": counts,
            "screened": screened, "screened_window": SCREENED_DAYS,
            "brief": read_brief(today), "later_days": 3, "leads": read_leads(today),
            "letter_limits": LETTER_LIMITS,
            # Every job id a run has recorded. The page drops a lead mark once it's in here.
            "lead_answered": sorted(read_lead_marks()), "lead_mark_days": LEAD_MARK_DAYS}
    try:
        data["contacts"] = attach_contacts(data)
    except Exception as e:  # noqa: BLE001 - same rule as Progress: the queue still builds
        data["contacts"] = {"note": f"the contact lookup failed ({type(e).__name__})"}
    return data


def render(data):
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\u0021--")
    return PAGE.replace("/*__DATA__*/", blob)


def write_atomic(path, text):
    # The temp name must not end in .html, or the Shelf's Downloads scan could import it.
    fd, tmp = tempfile.mkstemp(prefix=".job_dashboard.", suffix=".tmp", dir=os.path.dirname(path))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def summary(data, today):
    def left(i):
        d = parse_date(i["surfaced"])
        return None if not d else data["expiry_days"] - (today - d).days
    expiring = sum(1 for i in data["queue"] if left(i) is not None and left(i) <= data["expiring_days"])
    leads = data.get("leads") or {}
    contacts = data.get("contacts") or {}
    return (f"{len(data['queue'])} queue ({expiring} expiring), "
            f"{len(data.get('screened', []))} cleared, "
            f"{len(leads.get('rows') or [])} weekly leads, "
            f"{len(data['manual'])} manual, {len(data['quiet'])} quiet, "
            + (f"{contacts.get('rows', 0)} roles where you know someone" if not contacts.get("note")
               else f"no contacts ({contacts['note']})"))


def main(argv):
    strict = "--strict" in argv
    try:
        today = parse_date(argv[argv.index("--today") + 1]) if "--today" in argv else date.today()
        if today is None:
            raise ValueError("--today needs YYYY-MM-DD")
        now = datetime.now() if "--today" not in argv else datetime(today.year, today.month, today.day, 7, 0)
        data = build_data(today, now)
        html = render(data)
        if "--out" in argv:
            targets = [os.path.join(argv[argv.index("--out") + 1], OUT_NAME)]
        else:
            targets = [os.path.join(DOWNLOADS, OUT_NAME),
                       os.path.join(JOBS_DIR, f"dashboard_{today.isoformat()}.html")]
        for t in targets:
            os.makedirs(os.path.dirname(t), exist_ok=True)
            write_atomic(t, html)
        print(f"dashboard: {summary(data, today)} -> {targets[0]}")
        return 0
    except Exception as e:  # noqa: BLE001 - a dashboard failure must never fail the run
        print(f"dashboard: FAILED {type(e).__name__}: {e}")
        return 1 if strict else 0


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job Search Dashboard</title>
<style>
:root{--bg:#f6f5f1;--card:#fff;--ink:#1d1f23;--mute:#6b7078;--line:#e3e1da;--accent:#3d4fc4;
--good:#1f7a4d;--warn:#b26a00;--bad:#b3261e;--goodbg:#e6f3ec;--warnbg:#fbf0dc;--badbg:#fae6e4;--chip:#eeece6}
@media (prefers-color-scheme:dark){:root{--bg:#15171b;--card:#1e2126;--ink:#e8e6e1;--mute:#9a9ea6;--line:#2e3239;
--accent:#8f9cf5;--good:#6fcf9b;--warn:#e7b25c;--bad:#f08b83;--goodbg:#1b3328;--warnbg:#3a2e17;--badbg:#3d2220;--chip:#2a2e35}}
/* Progress charts (D42): the dataviz reference blue and orange, each step validated against --card in its mode. */
:root{--s1:#2a78d6;--s1p:#86b6ef;--s2:#eb6834;--ink2:#52514e;--axis:#c3c2b7;--band:rgba(11,11,11,.06)}
@media (prefers-color-scheme:dark){:root{--s1:#3987e5;--s1p:#1c5cab;--s2:#d95926;--ink2:#c3c2b7;--axis:#41464f;--band:rgba(255,255,255,.07)}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1080px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:22px;margin:0}
h2{font-size:16px;margin:32px 0 4px}
.sub{color:var(--mute);font-size:13px}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-variant-numeric:tabular-nums}
.strip{margin:12px 0;padding:10px 12px;border-radius:8px;font-size:14px}
.strip.bad{background:var(--badbg);color:var(--bad)}.strip.warn{background:var(--warnbg);color:var(--warn)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0 6px}
.tile{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--mute);border-radius:10px;
padding:12px;text-align:left;color:inherit;font:inherit;cursor:pointer}
.tile b{display:block;font-size:26px;line-height:1.1}
.tile span{font-size:13px;color:var(--mute)}
.tile.good{border-left-color:var(--good)}.tile.warn{border-left-color:var(--warn)}.tile.bad{border-left-color:var(--bad)}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.chipbtn{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;padding:5px 12px;
font:inherit;font-size:13px;cursor:pointer}
.chipbtn[aria-pressed=true]{background:var(--accent);border-color:var(--accent);color:#fff}
.list{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.row{display:flex;gap:12px;align-items:flex-start;padding:10px 12px;border-top:1px solid var(--line)}
.row:first-child{border-top:0}
.row.dim{opacity:.55}
.body{flex:1;min-width:0}
.top{display:flex;flex-wrap:wrap;gap:4px 10px;align-items:baseline}
.co{font-weight:600}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.meta{display:flex;flex-wrap:wrap;gap:5px;margin-top:5px;font-size:12.5px;color:var(--mute);align-items:center}
.tag{background:var(--chip);border-radius:5px;padding:1px 7px;white-space:nowrap}
.tag.good{background:var(--goodbg);color:var(--good)}.tag.warn{background:var(--warnbg);color:var(--warn)}
.tag.bad{background:var(--badbg);color:var(--bad)}
.right{text-align:right;white-space:nowrap;min-width:84px}
.right b{display:block;font-size:15px}
.right small{color:var(--mute);font-size:12px}
.path{cursor:pointer;border-bottom:1px dotted var(--mute)}
.why{font-size:13px;color:var(--mute);margin-top:3px}
.know{font-size:13px;margin-top:3px}
.hit{font-size:13px;margin-top:3px}
.hit.live{color:var(--good)}
input[type=checkbox]{width:20px;height:20px;margin-top:2px;accent-color:var(--accent);flex:none}
.group{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute);padding:10px 12px 4px;
background:var(--bg);border-top:1px solid var(--line)}
.empty{padding:18px 12px;color:var(--mute)}
.acts{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:7px;font-size:12.5px}
.act{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:6px;padding:3px 9px;
font:inherit;font-size:12.5px;cursor:pointer}
.act:hover{border-color:var(--accent)}
.act.go{background:var(--accent);border-color:var(--accent);color:#fff}
.sk{color:var(--mute);margin-left:6px}
.lnk{border:0;background:none;color:var(--accent);font:inherit;font-size:12.5px;cursor:pointer;padding:0 2px}
.ed{display:inline-flex;align-items:center;color:var(--mute)}
.ed input{width:14px;height:14px;margin:0 4px 0 0}
.promise{font-size:13px;margin-top:4px}
/* The letter view (2026-11-12): a second line of the row, full width, so a letter reads at phone width too. */
.row.wrap{flex-wrap:wrap;row-gap:2px}
.ltr{flex:0 0 100%;min-width:0;padding-left:54px}
.ltr>details{margin-top:2px}
.lt{max-width:700px;padding:2px 0 4px}
.lt p{margin:0 0 10px;font-size:14px;line-height:1.5;color:var(--ink);word-break:break-word}
.lhd{font-size:12.5px;color:var(--mute);white-space:pre-line;margin:8px 0 10px;word-break:break-word}
.lm{color:inherit;border-radius:3px;padding:1px 0;-webkit-box-decoration-break:clone;box-decoration-break:clone}
.lm-w{background:var(--goodbg)}.lm-t{background:var(--chip);box-shadow:inset 0 -2px 0 var(--axis)}.lm-p{background:var(--warnbg)}
.lt .legend i.sw{border:1px solid var(--axis)}
.lta{display:block;width:100%;min-height:340px;margin:8px 0;padding:10px;font:inherit;font-size:14px;line-height:1.5;
color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:8px;resize:vertical}
.lmsg{color:var(--bad);margin-top:4px}
@media (max-width:560px){.ltr{padding-left:0}}
details{margin-top:6px;font-size:13px}
summary{cursor:pointer;color:var(--accent)}
details ul{margin:6px 0 2px;padding-left:18px;color:var(--mute)}
.sec{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:8px 0;overflow:hidden}
.sec>summary{padding:10px 12px;color:var(--ink);font-weight:600;font-size:14px}
.sec .list{border:0;border-top:1px solid var(--line);border-radius:0}
.sec .row{font-size:13.5px}
.fs{margin:8px 0}.fst{font-weight:600;margin-bottom:3px;color:var(--ink)}
.fl{display:flex;gap:10px;padding:2px 0}.fk{flex:0 0 150px;color:var(--mute)}
.fv{white-space:pre-wrap;word-break:break-word;color:var(--ink)}.fv.need{color:var(--warn)}
.gdesc{font-size:12.5px;color:var(--mute);padding:0 12px 8px;background:var(--bg)}
.hs{padding:4px 12px 10px;font-size:13px}.hs b{display:block;margin:6px 0 2px}
.hs ul{margin:0;padding-left:18px;color:var(--ink)}
.hs pre{margin:0;white-space:pre-wrap;font-size:12px;color:var(--ink);overflow-x:auto}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:10px 0 4px}
.kpi{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--mute);border-radius:10px;padding:12px}
.kpi.good{border-left-color:var(--good)}
.kpi b{display:block;font-size:26px;line-height:1.1;font-weight:600}
.kpi span{font-size:13px;color:var(--mute)}
.viz{position:relative;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 12px 6px;margin:10px 0}
.viz h3{font-size:14px;margin:0}
.vsub{font-size:12.5px;color:var(--mute);margin:2px 0 4px}
.legend{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12.5px;color:var(--mute);margin:4px 0 8px}
.legend i{display:inline-block;vertical-align:middle;margin-right:6px}
.legend i.sw{width:10px;height:10px;border-radius:2px}
.legend i.ln{width:14px;height:2px;border-radius:1px}
.legend i.bd{width:14px;height:10px;background:var(--band);border:1px solid var(--line)}
.viz svg{display:block;max-width:100%;touch-action:pan-y}
.viz svg:focus{outline:none}.viz svg:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}
.vtip{position:absolute;pointer-events:none;background:var(--card);border:1px solid var(--line);border-radius:8px;
padding:8px 10px;font-size:12.5px;box-shadow:0 4px 16px rgba(0,0,0,.14);width:max-content;max-width:260px;z-index:5}
.vtip .tt{color:var(--mute);margin-bottom:4px}
.vtip .tr{display:flex;align-items:center;gap:6px;margin:2px 0}.vtip .tr b{font-weight:600}
.vtip .tr i{display:inline-block;width:12px;height:2px;border-radius:1px;flex:none}
.vtip .tn{color:var(--mute);margin-top:5px;line-height:1.35}
.fun{display:grid;grid-template-columns:minmax(110px,max-content) 1fr minmax(64px,max-content);gap:8px 10px;align-items:center;font-size:13px;margin:8px 0 6px}
.fun .trk{height:14px}.fun .bar{height:14px;background:var(--s1);border-radius:0 4px 4px 0}
.fun .fv2{text-align:right;white-space:nowrap}
.stand{font-size:13px;color:var(--mute);margin:4px 0 2px}
.viz details{margin:6px 0 4px}
.tw{overflow-x:auto}
.vt{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:6px}
.vt th{color:var(--mute);font-weight:600}
.vt th,.vt td{text-align:left;padding:4px 8px;border-top:1px solid var(--line);vertical-align:top}
.vt .n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}.vt td:first-child{white-space:nowrap}
footer{margin-top:34px;font-size:13px;color:var(--mute)}
footer li{margin:3px 0}
</style>
</head>
<body>
<main>
<h1>Job Search Dashboard</h1>
<div class="sub" id="stamp"></div>
<div id="strips"></div>
<div class="tiles" id="tiles"></div>

<h2 id="h-progress">Progress</h2>
<div class="sub" id="prog-sub"></div>
<div class="kpis" id="prog-kpis"></div>
<div class="chips" id="prog-range" aria-label="Range for the two charts"></div>
<div class="viz" id="viz-sent"></div>
<div class="viz" id="viz-rounds"></div>
<div class="viz" id="viz-funnel"></div>

<h2 id="h-today">New from the last run</h2>
<div class="sub" id="today-sub"></div>
<div class="list" id="today"></div>

<h2 id="h-queue">Apply queue</h2>
<div class="sub">Tailored, not confirmed sent. Rows retire at <span id="exp"></span> days. Mark a row Sent or Skip and the next weekday run records it; a confirmation email still does the same on its own. Open Letter on a row to read, copy, or edit its cover letter.</div>
<div class="sub" id="marknote"></div>
<div class="chips" id="qchips"></div>
<div class="sub" id="bulk"></div>
<div class="list" id="queue"></div>

<h2 id="h-screened">Cleared, not tailored</h2>
<div class="sub">The daily run read these job descriptions in full and they cleared location, pay, and the scoring bar, but there wasn't a tailored resume for them that day. Last <span id="swin"></span> days; a role leaves once it's tailored or applied.</div>
<div class="list" id="screened"></div>

<h2 id="h-leads">This week's leads</h2>
<div class="sub" id="leads-sub"></div>
<div id="leads-flags"></div>
<div class="sub" id="leads-note"></div>
<div class="list" id="leads"></div>
<div id="leads-health"></div>

<div id="run-wrap">
<h2 id="h-run">More from the last run</h2>
<div class="sub">What used to fill the rest of the digest email. Nothing in here is waiting on you.</div>
<div id="run"></div>
</div>

<h2 id="h-manual">Manual checks</h2>
<div class="sub">Career sites the pipeline can't read. Tick one when you've looked; ticks are yours and the pipeline never sees them.</div>
<div class="list" id="manual"></div>

<h2 id="h-quiet">Gone quiet</h2>
<div class="sub">Applied, nothing recorded since. Only applications from Jul 28 on, where a send can be confirmed.</div>
<div class="chips" id="zchips"></div>
<div class="list" id="quiet"></div>

<footer><b>Not on this page</b><ul id="foot"></ul></footer>
</main>
<script id="data" type="application/json">/*__DATA__*/</script>
<script>
(function(){
var D=JSON.parse(document.getElementById('data').textContent);
var DAY=86400000, KEY='jobdash.ticks.v1', IKEY='jobdash.inbox.v1', LKEY='jobdash.leads.v1', EKEY='jobdash.letters.v1';
var SKIP={fit:'not a fit',time:'no time',materials:'materials',other:'other'};
function el(id){return document.getElementById(id)}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function day(s){var p=String(s||'').slice(0,10).split('-');return p.length===3?new Date(+p[0],+p[1]-1,+p[2]):null}
var now=new Date(), today=new Date(now.getFullYear(),now.getMonth(),now.getDate());
function since(s){var d=day(s);return d?Math.round((today-d)/DAY):null}
function iso(d){return d.getFullYear()+'-'+('0'+(d.getMonth()+1)).slice(-2)+'-'+('0'+d.getDate()).slice(-2)}
function ago(n){if(n==null)return'';if(n<=0)return'today';if(n===1)return'yesterday';if(n<14)return n+' days ago';if(n<60)return Math.round(n/7)+' wks ago';return Math.round(n/30)+' mos ago'}
function nice(s){var d=day(s);return d?d.toLocaleDateString(undefined,{month:'short',day:'numeric'}):''}
function niceY(s,o){var d=day(s);return d?d.toLocaleDateString(undefined,o||{month:'short',day:'numeric',year:'numeric'}):''}
function safeUrl(u){return /^https?:\/\//i.test(u||'')?u:''}

// Ticks and marks. Storage can throw (private window, blocked site data); the page still works without it.
var ticks={}, marks={}, lmarks={}, ledits={}, storageOK=true;
try{ticks=JSON.parse(localStorage.getItem(KEY)||'{}')||{};marks=JSON.parse(localStorage.getItem(IKEY)||'{}')||{};
  lmarks=JSON.parse(localStorage.getItem(LKEY)||'{}')||{};ledits=JSON.parse(localStorage.getItem(EKEY)||'{}')||{}}catch(e){storageOK=false}
function saveTicks(){try{localStorage.setItem(KEY,JSON.stringify(ticks))}catch(e){storageOK=false;strips()}}
// IKEY and the mark shape {a,r,e,d,ts,u,c,t} are read by pipeline/shelf_inbox.py. Change both together.
function saveMarks(){try{localStorage.setItem(IKEY,JSON.stringify(marks))}catch(e){storageOK=false;strips()}}
// LKEY and the lead mark shape {a,d,ts,u,c,t,l,tier,loc}, keyed by LinkedIn job id, are read by
// pipeline/shelf_inbox.py and recorded by pipeline/lead_marks.py. Change all three together.
function saveLeadMarks(){try{localStorage.setItem(LKEY,JSON.stringify(lmarks))}catch(e){storageOK=false;strips()}}
// EKEY and the edit shape {text,base_sha,saved_at}, keyed the way a mark is, are read by
// pipeline/letter_edits.py. Change both together.
function saveEdits(){try{localStorage.setItem(EKEY,JSON.stringify(ledits))}catch(e){storageOK=false;strips()}}
(function prune(){var live={},changed=false;D.manual.forEach(function(m){live[m.key]=1});
  Object.keys(ticks).forEach(function(k){if(!live[k]){delete ticks[k];changed=true}});if(changed)saveTicks()})();

// A Sent or Skip mark whose row has left the queue was recorded by a run (or the row retired).
// It is dropped only when this page was generated after the mark was made, so a mark can't
// vanish on the same build it was made on. A snooze simply runs out.
(function pruneMarks(){var live={},gen=new Date(D.generated).getTime(),changed=false;
  D.queue.forEach(function(q){live[q.key]=1});
  Object.keys(marks).forEach(function(k){var m=marks[k]||{};
    if(m.a==='later'){var n=since(m.d);if(n==null||n>=D.later_days||!live[k]){delete marks[k];changed=true}}
    else if(!live[k]&&(m.ts||0)<gen){delete marks[k];changed=true}});
  if(changed)saveMarks()})();

// A saved letter edit (2026-11-12) is cleared here in two cases: its text is the letter now
// embedded (letter_edits.py applied it, or it changed nothing), or its row has left the queue
// and this page was built after the edit was saved. A refused edit stays, with the reason on
// its row. lparas() is edit_paragraphs() in the generator: change both together.
function lparas(t){return String(t==null?'':t).replace(/\r\n?/g,'\n').split(/\n\s*\n/).map(function(p){return p.replace(/\s+/g,' ').trim()}).filter(Boolean)}
(function pruneEdits(){var rows={},gen=new Date(D.generated).getTime(),changed=false;
  D.queue.forEach(function(q){rows[q.key]=q});
  Object.keys(ledits).forEach(function(k){var e=ledits[k]||{},q=rows[k];
    if(q?(!!q.letter&&lparas(e.text).join('\n\n')===q.letter.paras.join('\n\n')):(new Date(e.saved_at).getTime()||0)<gen){delete ledits[k];changed=true}});
  if(changed)saveEdits()})();

// A lead mark is dropped only once a run has recorded it (its id is in lead_marks.json), or
// after LEAD_MARK_DAYS as a backstop. Not on the lead leaving the data: Thursday's file
// replaces the whole list, and a click made after that morning's drain must survive it.
var L=D.leads||null, LROWS=(L&&L.rows)||[];
(function pruneLeadMarks(){var done={},changed=false;
  (D.lead_answered||[]).forEach(function(k){done[k]=1});
  Object.keys(lmarks).forEach(function(k){var m=lmarks[k]||{},n=since(m.d);
    if(done[k]||n==null||n>D.lead_mark_days){delete lmarks[k];changed=true}});
  if(changed)saveLeadMarks()})();

D.queue.forEach(function(q){q.age=since(q.surfaced);q.left=q.age==null?null:D.expiry_days-q.age});
// shelf_inbox.py matches a mark to its row by posting URL. A row with no link, or two rows
// sharing one, could never be recorded, so those rows explain themselves instead of taking clicks.
var keyN={};D.queue.forEach(function(q){keyN[q.key]=(keyN[q.key]||0)+1});
function canMark(q){return /^https?:\/\//.test(q.key)&&keyN[q.key]===1}
function mk(q){return canMark(q)?(marks[q.key]||null):null}
function isDone(q){var m=mk(q);return !!m&&(m.a==='sent'||m.a==='skip')}
var B=D.brief||null, runDate=(B&&B.run_date)||String(D.generated).slice(0,10);
function isNew(q){return !!q.surfaced&&q.surfaced>=runDate}
D.quiet.forEach(function(z){z.days=since(z.applied)});
function tickState(m){var t=ticks[m.key],n=t?since(t):null;
  var stale=n!=null&&n>m.stale_days, newer=t&&m.hit_is_live&&m.last_checked>t;
  return {date:t,days:n,due:!t||stale||newer,stale:stale,newer:newer}}

var qFilter='fresh', zFilter='old';
var QF={fresh:['Fresh',function(q){return q.age!=null&&q.age<=D.fresh_days&&!mk(q)}],
  expiring:['Expiring',function(q){return q.left!=null&&q.left<=D.expiring_days&&!isDone(q)}],
  full:['Full tier',function(q){return (q.tier==='full'||q.tier==='priority')&&!isDone(q)}],
  all:['All',function(){return true}],
  marked:['Marked',function(q){return isDone(q)}]};
var ZF={old:[D.quiet_days+'+ days',function(z){return z.days!=null&&z.days>=D.quiet_days}],all:['All',function(){return true}]};

function strips(){var h='';
  // Stale = a scheduled run should have rebuilt this page since it was generated. The run is
  // weekdays only, so a flat hour count would cry wolf every weekend.
  var gen=new Date(D.generated), due=new Date(now.getFullYear(),now.getMonth(),now.getDate(),D.run_ready_hour);
  for(var i=0;i<8&&(due>now||D.run_weekdays.indexOf(due.getDay())<0);i++)due=new Date(due.getTime()-DAY);
  var dueDay=new Date(due.getFullYear(),due.getMonth(),due.getDate());
  if(gen<dueDay)h+='<div class="strip bad">This page is from '+esc(nice(D.generated))+' and the '+esc(due.toLocaleDateString(undefined,{weekday:'long'}))+' run should have replaced it. The daily build may have failed.</div>';
  if(D.counts.bad_rows)h+='<div class="strip warn">'+D.counts.bad_rows+' tracker rows are unreadable (column drift) and are missing from every list. Run repair_outcomes.py.</div>';
  if(B)(B.alerts||[]).forEach(function(a){h+='<div class="strip warn">'+esc(a)+'</div>'});
  if(!storageOK)h+='<div class="strip warn">Storage is unavailable here, so ticks, marks, and letter edits last only until this page closes and no run will see them.</div>';
  el('strips').innerHTML=h}

function tiles(){
  var fresh=D.queue.filter(QF.fresh[1]).length, exp=D.queue.filter(QF.expiring[1]).length;
  var due=D.manual.filter(function(m){return tickState(m).due}).length, old=D.quiet.filter(ZF.old[1]).length;
  var fresh_new=D.queue.filter(function(q){return isNew(q)&&!mk(q)}).length;
  var t=[[fresh_new?'good':'',fresh_new,'new from the last run, not yet marked','today',null],
    ['good',fresh,'ready to apply, '+D.fresh_days+' days or newer','queue','fresh'],
    [exp?'warn':'',exp,'expiring within '+D.expiring_days+' days','queue','expiring'],
    [(D.screened||[]).length?'good':'',(D.screened||[]).length,'cleared, not tailored','screened',null],
    [leadsOpen()?'warn':'',leadsOpen(),'weekly leads to answer','leads',null],
    [due?'bad':'good',due,'manual checks due','manual',null],
    ['',old,'applied and quiet '+D.quiet_days+'+ days'+(D.counts.in_process?' ('+D.counts.in_process+' in process)':''),'quiet','old']];
  el('tiles').innerHTML=t.map(function(x,i){return '<button class="tile '+x[0]+'" data-i="'+i+'"><b class="mono">'+x[1]+'</b><span>'+esc(x[2])+'</span></button>'}).join('');
  Array.prototype.forEach.call(el('tiles').children,function(b,i){b.onclick=function(){
    if(t[i][3]==='queue'){qFilter=t[i][4];queue()} if(t[i][3]==='quiet'){zFilter=t[i][4];quiet()}
    el('h-'+t[i][3]).scrollIntoView({behavior:'smooth'})}})}

function chips(id,defs,cur,set){el(id).innerHTML=Object.keys(defs).map(function(k){
  return '<button class="chipbtn" aria-pressed="'+(k===cur)+'" data-k="'+k+'">'+esc(defs[k][0])+'</button>'}).join('');
  Array.prototype.forEach.call(el(id).children,function(b){b.onclick=function(){set(b.getAttribute('data-k'))}})}

function titleLink(x){var u=safeUrl(x.url);return u?'<a href="'+esc(u)+'" target="_blank" rel="noopener">'+esc(x.title)+'</a>':esc(x.title)}
function pathTag(label,p){return p?'<span class="tag path mono" data-copy="'+esc(p)+'" title="'+esc(p)+' (click to copy the path)">'+label+' PDF</span>':''}

function tags(q){var m=[];
  if(q.tier)m.push('<span class="tag">'+esc(q.tier)+'</span>');
  if(q.unmet!=null)m.push('<span class="tag '+(q.unmet===0?'good':q.unmet>=2||q.unmet<0?'warn':'')+'" title="'+esc(q.unmet_text)+'">'+(q.unmet<0?'unmet: see note':q.unmet+' unmet hard req'+(q.unmet===1?'':'s'))+'</span>');
  if(q.cap_trigger)m.push('<span class="tag bad" title="'+esc(q.cap_trigger)+'">hard-req cap</span>');
  if(q.coverage_ok!=null)m.push('<span class="tag '+(q.coverage_ok?'':'warn')+'">ATS gate '+(q.coverage_ok?'pass':'below 80')+'</span>');
  if(q.ic_scope)m.push('<span class="tag">'+esc(q.ic_scope==='ic'?'IC':q.ic_scope)+'</span>');
  if(q.channel&&q.channel!=='pipeline')m.push('<span class="tag">'+esc(q.channel.replace('_',' '))+'</span>');
  m.push(pathTag('resume',q.resume)); m.push(pathTag('cover',q.cover)); m.push(pathTag('ATS',q.ats));
  if(q.note)m.push('<span>'+esc(q.note)+'</span>');
  return m.join('')}
function leftCell(q){return q.left==null?'<b>no date</b><small>never retires</small>':
  '<b class="mono" style="color:var(--'+(q.left<=D.expiring_days?'bad':q.left<=21?'warn':'ink')+')">'+Math.max(q.left,0)+'d left</b><small>surfaced '+esc(ago(q.age))+'<br>'+esc(nice(q.surfaced))+'</small>'}
// One click each. Sent and Skip wait in the Shelf's storage for the next run; Later is the page's own.
function acts(q){if(!canMark(q))return '<div class="acts"><span class="sk" style="margin-left:0">'+(keyN[q.key]>1?"Two tracker rows share this link, so it can't be marked here.":"No posting link on this row, so it can't be marked here.")+'</span></div>';
  var m=mk(q),k=esc(q.key),undo='<button class="lnk" data-act="undo" data-k="'+k+'">undo</button>';
  if(m&&m.a==='sent')return '<div class="acts"><span class="tag good">marked sent '+esc(nice(m.d))+'</span><label class="ed"><input type="checkbox" data-act="edited" data-k="'+k+'"'+(m.e?' checked':'')+'>I edited the materials first</label>'+undo+'</div>';
  if(m&&m.a==='skip')return '<div class="acts"><span class="tag warn">marked skip: '+esc(m.bulk?'cleared in bulk':(SKIP[m.r]||'other'))+'</span>'+undo+'</div>';
  if(m&&m.a==='later')return '<div class="acts"><span class="tag">snoozed '+D.later_days+' days from '+esc(nice(m.d))+'</span>'+undo+'</div>';
  return '<div class="acts"><button class="act go" data-act="sent" data-k="'+k+'">Sent</button><button class="act" data-act="later" data-k="'+k+'">Later</button><span class="sk">Skip:</span>'+
    Object.keys(SKIP).map(function(r){return '<button class="act" data-act="skip" data-r="'+r+'" data-k="'+k+'">'+esc(SKIP[r])+'</button>'}).join('')+'</div>'}
// Marking a row redraws the lists. Remember which panels were open so a click on Sent doesn't
// fold away the form fields he is pasting from. `toggle` doesn't bubble, hence the capture.
var openD={};
function det(id,label){return '<details data-d="'+esc(id)+'"'+(openD[id]?' open':'')+'><summary>'+label+'</summary>'}
document.addEventListener('toggle',function(ev){var d=ev.target,id=d&&d.getAttribute?d.getAttribute('data-d'):null;
  if(id){if(d.open)openD[id]=1;else delete openD[id]}},true);
function fieldsPanel(q){if(!q.fields||!q.fields.length)return '';
  return det(q.key+'|fields','Form fields to paste')+q.fields.map(function(s){
    return '<div class="fs"><div class="fst">'+esc(s.title)+'</div>'+s.fields.map(function(f){
      return '<div class="fl"><span class="fk">'+esc(f.label)+'</span>'+(f.value?'<span class="fv path" data-copy="'+esc(f.value)+'" title="click to copy">'+esc(f.value)+'</span>':'<span class="fv need">'+(f.needs_you?'yours to fill in':'')+'</span>')+'</div>'}).join('')+'</div>'}).join('')+'</details>'}
function briefPanel(q){var p=B&&B.picks?B.picks[q.key]:null,h='';if(!p)return h;
  if(p.read)h+='<div class="why">'+esc(p.read)+'</div>';
  if(p.commitment)h+='<div class="promise"><b>The letter promises:</b> '+esc(p.commitment)+'</div>';
  if(p.check&&p.check.length)h+='<div class="promise"><b>Check before sending:</b> '+p.check.map(esc).join(' · ')+'</div>';
  // A note for the recruiter or hiring manager there (2026-11-08, D53); he sends it himself after applying.
  if(p.note_draft)h+='<div class="promise"><b>Note for a person there, after you apply:</b> <span class="path" data-copy="'+esc(p.note_draft)+'" title="click to copy">'+esc(p.note_draft)+'</span></div>';
  if(p.changes&&p.changes.length)h+=det(q.key+'|changes','What changed in the resume')+'<ul>'+p.changes.map(function(c){return '<li>'+esc(c)+'</li>'}).join('')+'</ul></details>';
  return h}
// Who he knows there (2026-11-07): first-degree LinkedIn connections at the row's company, read
// from the warm-path kit's export at build time, so he can ask before he applies. Shown only.
var KNOW_SHOW=3;
function knowLine(x){var k=x.know;if(!k||!k.length)return '';
  var C=D.contacts||{}, one=function(p){return esc(p.name)+(p.title?', '+esc(p.title):'')+(p.at?' at '+esc(p.at):'')+
    (p.since?' · connected '+esc(niceY(p.since,{month:'short',year:'numeric'})):'')+(p.check?' <span class="tag warn" title="'+esc(p.check)+'">same company?</span>':'')};
  var rest=k.slice(KNOW_SHOW).map(function(p){return p.name+(p.title?', '+p.title:'')+(p.at?' at '+p.at:'')}).join('\n');
  return '<div class="know" title="From your LinkedIn connections export'+(C.as_of?', file dated '+esc(niceY(C.as_of)):'')+'. Titles and companies are as of then.">'+
    '<b>You know:</b> '+k.slice(0,KNOW_SHOW).map(one).join('; ')+(rest?' <span title="'+esc(rest)+'">+'+(k.length-KNOW_SHOW)+' more</span>':'')+'</div>'}
// The letter view (2026-11-12). q.letter holds the letter as plain paragraphs, the lines above
// and below them in the .md, and the sentences the generator's finder was sure of. An edit is
// the paragraphs only. Nothing here reaches the files: Save edit stores his text under EKEY and
// pipeline/letter_edits.py applies it, at the next run or when he asks.
var LIM=D.letter_limits||{min_paragraphs:2,min_words:150,max_words:600}, drafts={}, lmsg={};
var LMARK={why:['w','why this job'],tie:['t','the tie-back'],promise:['p','the promise']};
function ledit(q){var e=canMark(q)?ledits[q.key]:null;return e&&typeof e.text==='string'?e:null}
function lshown(q){var e=ledit(q);return e?lparas(e.text):q.letter.paras}
function lwords(ps){return ps.join(' ').split(/\s+/).filter(Boolean).length}
function lcount(t){var ps=lparas(t);return lwords(ps)+' words in '+plural(ps.length,'paragraph')}
// What Copy letter puts on the clipboard: the .md he pastes into forms, with his edit when one is saved.
function ltext(q){return [q.letter.head,lshown(q).join('\n\n'),q.letter.tail].filter(Boolean).join('\n\n')+'\n'}
function niceTs(s){var d=new Date(s);return /T/.test(String(s))&&!isNaN(d)?d.toLocaleDateString(undefined,{month:'short',day:'numeric'}):nice(s)}
function letterWhy(q){var L=q.letter,w=L&&L.marks?L.marks.why:'',e=L?ledit(q):null;
  return w&&!(e&&e.text.indexOf(w)<0)?'<div class="promise"><b>Why this job, from the letter:</b> '+esc(w)+'</div>':''}
function letterState(q){var L=q.letter,e=ledit(q),m=mk(q),r=L.refused,h='';
  if(e&&r&&r.saved_at===e.saved_at&&r.base_sha===e.base_sha)h='<span class="tag bad">edit not applied</span> '+esc(r.reason)+' Your text is still saved on this page.';
  else if(e&&e.base_sha!==L.sha)h='<span class="tag bad">edit not applied</span> '+"The letter was rewritten after you saved this edit, so it won't be applied. Your text is still saved on this page; discard it to edit the letter as it stands.";
  else if(e&&m&&m.a==='sent')h='<span class="tag warn">edit saved</span> '+"You marked this row Sent, so the edit won't be applied to the letter's files. Undo the mark if it hasn't gone out.";
  else if(e)h='<span class="tag warn">edit saved</span> '+"Your edit is saved. It's applied at the next run, or tell Claude: apply my letter edits. Until then the PDF has the earlier text.";
  else if(L.edited)h='<span class="tag good">Edited by you, '+esc(niceTs(L.edited))+'</span>';
  return h?'<div class="promise">'+h+'</div>':''}
// A marked sentence is found by its own text, so a paragraph he hasn't touched keeps its marks
// while his edit is showing and a sentence he rewrote simply loses its mark.
function lmarked(ps,M,used){return ps.map(function(p){var rs=[];
  Object.keys(LMARK).forEach(function(n){var s=M&&M[n],i=s&&!used[n]?p.indexOf(s):-1;if(i>=0){used[n]=1;rs.push([i,i+s.length,n])}});
  rs.sort(function(a,b){return a[0]-b[0]});var h='',at=0;
  rs.forEach(function(r){if(r[0]<at)return;h+=esc(p.slice(at,r[0]))+'<mark class="lm lm-'+LMARK[r[2]][0]+'" title="'+esc(LMARK[r[2]][1])+'">'+esc(p.slice(r[0],r[1]))+'</mark>';at=r[1]});
  return '<p>'+h+esc(p.slice(at))+'</p>'}).join('')}
function letterPanel(q){var L=q.letter;
  if(!L)return q.letter_note?'<div class="ltr"><div class="sub">'+"This row's letter isn't shown: "+esc(q.letter_note)+'.</div></div>':'';
  var k=esc(q.key),e=ledit(q),m=mk(q),ps=lshown(q),M=L.marks||{};
  var shut=!canMark(q)?"This row can't take marks, so its letter can't be edited here either.":(L.no_edit||(m&&m.a==='sent'?'Marked Sent, so the letter is closed to edits.':''));
  var h='<div class="ltr">'+letterWhy(q)+letterState(q)+det(q.key+'|letter',e?'Letter, with your edit':'Letter')+'<div class="lt">';
  if(L.head)h+='<div class="lhd">'+esc(L.head)+'</div>';
  if(drafts[q.key]!=null&&!shut){
    h+='<textarea class="lta" data-ledit="'+k+'" aria-label="The letter\'s paragraphs, a blank line between each">'+esc(drafts[q.key])+'</textarea>';
    if(L.tail)h+='<div class="lhd">'+esc(L.tail)+'</div>';
    h+='<div class="acts"><button class="act go" data-lt="save" data-k="'+k+'">Save edit</button><button class="act" data-lt="cancel" data-k="'+k+'">Cancel</button>'+(e?'<button class="act" data-lt="discard" data-k="'+k+'">Discard edit</button>':'')+'<span class="sk" data-lcount="1">'+esc(lcount(drafts[q.key]))+'</span></div>';
    h+='<div class="sub">Only the paragraphs change; the date, the recipient, and the sign-off stay as they are. Keep a blank line between paragraphs.</div>';
    if(lmsg[q.key])h+='<div class="sub lmsg">'+esc(lmsg[q.key])+'</div>';
  }else{
    var used={};
    h+='<div class="lbody">'+lmarked(ps,M,used)+'</div>';
    if(L.tail)h+='<div class="lhd">'+esc(L.tail)+'</div>';
    var lg=Object.keys(LMARK).filter(function(n){return used[n]}).map(function(n){return '<span><i class="sw lm-'+LMARK[n][0]+'"></i>'+esc(LMARK[n][1])+'</span>'}).join('');
    if(lg)h+='<div class="legend">'+lg+'</div>';
    h+='<div class="acts"><button class="act go" data-lt="copy" data-k="'+k+'">Copy letter</button>'+(shut?'':'<button class="act" data-lt="edit" data-k="'+k+'">Edit</button>'+(e?'<button class="act" data-lt="discard" data-k="'+k+'">Discard edit</button>':''))+'<span class="sk">'+plural(lwords(ps),'word')+'</span></div>';
    if(shut)h+='<div class="sub">'+esc(shut)+'</div>';
  }
  return h+'</div></details></div>'}
function letterClick(t,a){var k=t.getAttribute('data-k'),q=null;
  for(var i=0;i<D.queue.length;i++)if(D.queue[i].key===k){q=D.queue[i];break}
  if(!q||!q.letter)return;
  var L=q.letter,e=ledit(q),box=t.closest?t.closest('.lt'):null,host=t.closest?t.closest('.list'):null;
  if(a==='copy'){copyText(t,ltext(q),function(){return box?box.querySelector('.lbody'):null});return}
  delete lmsg[k];
  if(a==='edit')drafts[k]=(e?lparas(e.text):L.paras).join('\n\n');
  else if(a==='cancel')delete drafts[k];
  else if(a==='discard'){delete ledits[k];delete drafts[k];saveEdits()}
  else if(a==='save'){var ta=box?box.querySelector('textarea'):null;if(ta)drafts[k]=ta.value;
    var ps=lparas(drafts[k]),n=lwords(ps),text=ps.join('\n\n');
    // Saving the letter as it stands is not an edit, and it clears one he typed his way back out of.
    if(text===L.paras.join('\n\n')){delete ledits[k];delete drafts[k];saveEdits()}
    else if(ps.some(function(p){return !/[A-Za-z0-9]/.test(p)}))lmsg[k]='Not saved: one paragraph has no words in it.';
    else if(ps.length<LIM.min_paragraphs||n<LIM.min_words||n>LIM.max_words)lmsg[k]="Not saved: that's "+plural(n,'word')+' in '+plural(ps.length,'paragraph')+'. A letter here is at least '+LIM.min_paragraphs+' paragraphs and '+LIM.min_words+' to '+LIM.max_words+" words, so a slip can't wipe one.";
    else if(!canMark(q)||L.no_edit)lmsg[k]="Not saved: this row's letter can't be edited here.";
    else{ledits[k]={text:text,base_sha:L.sha,saved_at:new Date().toISOString()};delete drafts[k];saveEdits()}}
  else return;
  openD[k+'|letter']=1;todayList();queue();
  if(a==='edit'&&host){var tas=host.querySelectorAll('textarea[data-ledit]');
    for(var j=0;j<tas.length;j++)if(tas[j].getAttribute('data-ledit')===k){tas[j].focus();break}}}
// An edit box is as tall as its letter, so the whole letter is in view while he edits it.
function lgrow(t){t.style.height='auto';t.style.height=(t.scrollHeight+2)+'px'}
function lfit(id){Array.prototype.forEach.call(el(id).querySelectorAll('textarea[data-ledit]'),lgrow)}
// Redrawing the lists rebuilds an open edit box, so what he has typed is kept as he types it.
document.addEventListener('input',function(ev){var t=ev.target,k=t&&t.getAttribute?t.getAttribute('data-ledit'):null;
  if(k==null)return;drafts[k]=t.value;lgrow(t);
  var c=t.parentNode?t.parentNode.querySelector('[data-lcount]'):null;if(c)c.textContent=lcount(t.value)});
function rowHTML(q,full){
  return '<div class="row'+(q.letter||q.letter_note?' wrap':'')+(mk(q)?' dim':'')+'"><div class="right mono" style="min-width:42px;text-align:left"><b>'+(q.score==null?'':Math.round(q.score))+'</b></div><div class="body"><div class="top"><span class="co">'+esc(q.company)+'</span><span>'+titleLink(q)+'</span></div>'+knowLine(q)+'<div class="meta">'+tags(q)+'</div>'+(full?briefPanel(q):'')+fieldsPanel(q)+acts(q)+'</div><div class="right">'+leftCell(q)+'</div>'+letterPanel(q)+'</div>'}

function todayList(){
  var rows=D.queue.filter(isNew).sort(function(a,b){return (b.score||0)-(a.score||0)}), when=nice(runDate);
  el('h-today').textContent='New from the '+when+' run';
  el('today-sub').textContent=(B&&B.note)?B.note:(rows.length?'Tailored on or after '+when+'.':'');
  el('today').innerHTML=rows.length?rows.map(function(q){return rowHTML(q,true)}).join(''):'<div class="empty">No new packages from the '+esc(when)+' run.</div>';
  lfit('today')}

function runNotes(){var secs=(B&&B.sections)||[];
  el('run-wrap').style.display=secs.length?'':'none'; if(!secs.length)return;
  el('h-run').textContent='More from the '+nice(runDate)+' run';
  el('run').innerHTML=secs.map(function(x,i){return '<details class="sec" data-d="run|'+i+'"'+(openD['run|'+i]?' open':'')+'><summary>'+esc(x.title)+' <span class="sub">'+x.lines.length+'</span></summary>'+(x.note?'<div class="why" style="padding:0 12px 8px">'+esc(x.note)+'</div>':'')+'<div class="list">'+x.lines.map(function(l){var u=safeUrl(l.url);
    return '<div class="row"><div class="body">'+esc(l.text)+(u?' <a href="'+esc(u)+'" target="_blank" rel="noopener">'+esc(l.label||'link')+'</a>':'')+'</div></div>'}).join('')+'</div></details>'}).join('')}

function legacyCopy(p){var ta=document.createElement('textarea'),ok=false;ta.value=p;ta.style.position='fixed';ta.style.opacity='0';
  document.body.appendChild(ta);ta.select();try{ok=document.execCommand('copy')}catch(e){}document.body.removeChild(ta);return ok}
// `where` is for a value too long to show in its own button (a whole letter): it returns the
// element that already displays the text, and the last resort selects that instead.
function copyText(s,p,where){if(s.getAttribute('data-busy'))return;var old=s.textContent;
  function flash(msg,ms){s.setAttribute('data-busy','1');s.textContent=msg;setTimeout(function(){s.textContent=old;s.removeAttribute('data-busy')},ms)}
  function done(){flash('copied',900)}
  // Last resort when neither clipboard path is allowed: show the value and select it, so
  // Command-C finishes the job. (window.prompt is not available in every embedded browser.)
  function fallback(){if(legacyCopy(p)){done();return}
    try{var n=where?where():s;if(!n)return;if(!where)s.textContent=p;var r=document.createRange();r.selectNodeContents(n);var w=window.getSelection();w.removeAllRanges();w.addRange(r);
      s.title='Selected. Press Command-C to copy.';if(where)flash('Selected. Press Command-C.',2500)}catch(e){}}
  if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(p).then(done,fallback);else fallback()}
function copy(s){copyText(s,s.getAttribute('data-copy'))}
// One listener for every copy target and every mark button, wherever the row is drawn.
document.addEventListener('click',function(ev){var t=ev.target;if(!t||!t.getAttribute)return;
  var la=t.getAttribute('data-lact');
  if(la){leadClick(t,la);return}
  var lt=t.getAttribute('data-lt');
  if(lt){letterClick(t,lt);return}
  var a=t.getAttribute('data-act');
  if(!a){var c=t.closest?t.closest('[data-copy]'):null;if(c)copy(c);return}
  if(a==='bulk'){oldRows().forEach(function(o){marks[o.key]={a:'skip',r:'other',bulk:true,d:iso(today),ts:Date.now(),u:o.url,c:o.company,t:o.title}});
    saveMarks();todayList();queue();tiles();return}
  if(a==='unbulk'){Object.keys(marks).forEach(function(x){if(marks[x]&&marks[x].bulk)delete marks[x]});
    saveMarks();todayList();queue();tiles();return}
  var k=t.getAttribute('data-k'),q=null;
  for(var i=0;i<D.queue.length;i++)if(D.queue[i].key===k){q=D.queue[i];break}
  if(!q)return;
  if(a==='undo')delete marks[k];
  else if(a==='edited'){if(marks[k])marks[k].e=!!t.checked}
  else{marks[k]={a:a,d:iso(today),ts:Date.now(),u:q.url,c:q.company,t:q.title};if(a==='skip')marks[k].r=t.getAttribute('data-r')||'other'}
  saveMarks();todayList();queue();tiles();progress()});

// The one-click clear (his pick, 2026-10-12). Rows past the Fresh window that carry no mark
// yet. Recorded as skip (other) with `bulk` set, so shelf_inbox.py notes "cleared in bulk"
// and the fit-versus-materials split in pipeline_quality.py isn't fed guesses.
function oldRows(){return D.queue.filter(function(q){return q.age!=null&&q.age>D.fresh_days&&canMark(q)&&!mk(q)})}
function bulkBar(){var n=oldRows().length,b=0;
  Object.keys(marks).forEach(function(x){if(marks[x]&&marks[x].bulk)b++});
  var h='';
  if(qFilter==='all'&&n)h+=n+' row'+(n===1?'':'s')+' here '+(n===1?'is':'are')+' older than '+D.fresh_days+' days. <button class="act" data-act="bulk">Skip '+(n===1?'it':'all '+n)+' as cleared in bulk</button> ';
  if(b)h+=b+' cleared in bulk, not recorded yet. <button class="lnk" data-act="unbulk">undo the bulk clear</button>';
  el('bulk').innerHTML=h}
function queue(){
  bulkBar();
  var done=D.queue.filter(isDone).length;
  QF.marked[0]='Marked ('+done+')';
  var edited=D.queue.filter(function(q){return q.letter&&ledit(q)}).length;
  el('marknote').textContent=(done?done+' marked. The next weekday run records them, and they leave this list.':'')+
    (edited?(done?' ':'')+plural(edited,'letter edit')+' saved. The next weekday run applies '+(edited===1?'it':'them')+'.':'');
  chips('qchips',QF,qFilter,function(k){qFilter=k;queue()});
  var rows=D.queue.filter(QF[qFilter][1]).slice();
  rows.sort(qFilter==='expiring'?function(a,b){return a.left-b.left}:function(a,b){
    if((a.age==null)!==(b.age==null))return a.age==null?1:-1; return (b.score||0)-(a.score||0)});
  el('queue').innerHTML=rows.length?rows.map(function(q){return rowHTML(q,false)}).join(''):'<div class="empty">Nothing in this view.</div>';
  lfit('queue')}

function screened(){
  var rows=(D.screened||[]).slice().sort(function(a,b){return (b.score||0)-(a.score||0)});
  el('screened').innerHTML=rows.length?rows.map(function(s){var m=[];
    if(s.loc)m.push('<span class="tag'+(s.loc==='ATL'?' good':'')+'">'+esc(s.loc==='ATL'?'Atlanta':s.loc)+'</span>');
    if(s.pay)m.push('<span class="tag">'+esc(s.pay)+'</span>');
    if(s.scope)m.push('<span class="tag">'+esc(s.scope==='ic'?'IC':s.scope)+'</span>');
    if(s.gap)m.push('<span class="tag warn" title="'+esc(s.gap)+'">gap</span>');
    var n=since(s.first);
    return '<div class="row"><div class="right mono" style="min-width:42px;text-align:left"><b>'+(s.score==null?'':Math.round(s.score))+'</b></div><div class="body"><div class="top"><span class="co">'+esc(s.company)+'</span><span>'+titleLink(s)+'</span></div>'+knowLine(s)+(s.why?'<div class="why">'+esc(s.why)+(s.gap?' · gap: '+esc(s.gap):'')+'</div>':'')+'<div class="meta">'+m.join('')+'</div></div><div class="right"><small>cleared '+esc(ago(n))+'<br>'+esc(nice(s.first))+'</small></div></div>'
  }).join(''):'<div class="empty">'+(D.counts.screened_days?'Nothing cleared beyond what was tailored.':'No JD screen results yet. The daily run writes them from its next run on.')+'</div>'}

// The weekly leads (2026-10-15, D41). Two answers a row: Tailor it queues a package for the
// next weekday run, Pass takes it off. Both wait in LKEY until shelf_inbox.py records them.
var LEADG={unreachable:["Strong roles the poller can't reach","Tier 1 or 2 in Atlanta or remote US, at companies with no board the daily run can read. These never competed for a package."],
  never_picked:['Watched companies, never picked','The poller reads these boards and the role still lost on score or rank. Tailor it here says the scoring missed one.'],
  no_board:['Companies with no board yet','A good role turned up at each, and the board its name resolved to looks like some other company.']};
var LOCL={atlanta:'Atlanta','atlanta-hybrid':'Atlanta hybrid',remote:'Remote','us-national':'US'};
var LEAD_SHOW=20, leadsAll=false;
function leadsOpen(){return LROWS.filter(function(x){return !lmarks[x.id]}).length}
function leadsPending(){var live={},n=0;LROWS.forEach(function(x){live[x.id]=1});
  Object.keys(lmarks).forEach(function(k){if(!live[k])n++});return n}
function leadActs(x){var m=lmarks[x.id],k=esc(x.id),undo='<button class="lnk" data-lact="undo" data-k="'+k+'">undo</button>';
  if(m&&m.a==='tailor')return '<div class="acts"><span class="tag good">asked to tailor '+esc(nice(m.d))+'</span>'+undo+'</div>';
  if(m&&m.a==='pass')return '<div class="acts"><span class="tag warn">passed '+esc(nice(m.d))+'</span>'+undo+'</div>';
  return '<div class="acts"><button class="act go" data-lact="tailor" data-k="'+k+'">Tailor it</button><button class="act" data-lact="pass" data-k="'+k+'">Pass</button></div>'}
function leadRow(x){var t=[];
  if(x.tier&&x.tier!=='none')t.push('<span class="tag">'+esc(x.tier)+'</span>');
  if(LOCL[x.loc])t.push('<span class="tag'+(x.loc==='atlanta'?' good':'')+'">'+esc(LOCL[x.loc])+'</span>');
  if(x.seen>1)t.push('<span class="tag">in '+x.seen+' alerts</span>');
  if(x.note)t.push('<span>'+esc(x.note)+'</span>');
  // What the company does, from company_about.py's cache (2026-10-15). Absent until a run looks it up.
  var about=[x.about,x.industry,x.size].filter(Boolean).map(esc).join(' · ');
  return '<div class="row'+(lmarks[x.id]?' dim':'')+'"><div class="body"><div class="top"><span class="co">'+esc(x.company)+'</span><span>'+titleLink(x)+'</span></div>'+knowLine(x)+(about?'<div class="why">'+about+'</div>':'')+'<div class="meta">'+t.join('')+'</div>'+leadActs(x)+'</div><div class="right"><small>'+(x.first?'first seen<br>'+esc(nice(x.first)):'')+'</small></div></div>'}
function leadClick(t,a){if(a==='more'){leadsAll=true;leads();return}
  var k=t.getAttribute('data-k'),x=null;
  for(var i=0;i<LROWS.length;i++)if(LROWS[i].id===k){x=LROWS[i];break}
  if(!x)return;
  if(a==='undo')delete lmarks[k];
  else if(a==='tailor'||a==='pass')lmarks[k]={a:a,d:iso(today),ts:Date.now(),u:x.url,c:x.company,t:x.title,l:x.list,tier:x.tier,loc:x.loc};
  saveLeadMarks();leads();tiles()}
function leads(){
  var empty=function(s){el('leads-sub').textContent=s;['leads','leads-flags','leads-health'].forEach(function(i){el(i).innerHTML=''});el('leads-note').textContent=''};
  if(!L)return empty('No weekly report in the last two weeks. The daily run writes one on Thursdays.');
  el('leads-sub').textContent='From the weekly report, '+nice(L.start)+' to '+nice(L.end)+": LinkedIn roles the daily run didn't turn into a package. Tailor it queues a package for the next weekday run, three a run, oldest click first. Pass takes it off the list.";
  el('leads-flags').innerHTML=(L.flags||[]).map(function(f){return '<div class="strip warn">'+esc(f)+'</div>'}).join('');
  var marked=LROWS.filter(function(x){return lmarks[x.id]}).length, note=[];
  if(marked)note.push(marked+' marked. The next weekday run records them, and they leave this list.');
  var older=leadsPending();
  if(older)note.push(older+' marked on an earlier week, recorded on the next weekday run.');
  if(L.waiting)note.push(L.waiting+' asked for earlier, waiting for a run to read the posting.');
  if(L.handled)note.push(L.handled+' from this week already answered.');
  el('leads-note').textContent=note.join(' ');
  var h='';
  ['unreachable','never_picked','no_board'].forEach(function(g){
    var rows=LROWS.filter(function(x){return x.list===g});if(!rows.length)return;
    var cut=g==='unreachable'&&!leadsAll&&rows.length>LEAD_SHOW;
    h+='<div class="group">'+esc(LEADG[g][0])+' · '+rows.length+'</div><div class="gdesc">'+esc(LEADG[g][1])+'</div>';
    h+=(cut?rows.slice(0,LEAD_SHOW):rows).map(leadRow).join('');
    if(cut)h+='<div class="row"><button class="lnk" data-lact="more">Show '+(rows.length-LEAD_SHOW)+' more</button></div>'});
  el('leads').innerHTML=h||'<div class="empty">Every lead from this week has an answer.</div>';
  var hs=L.health||[];
  el('leads-health').innerHTML=hs.length?'<details class="sec" data-d="leads|health"'+(openD['leads|health']?' open':'')+'><summary>Channel health <span class="sub">the numbers behind the report</span></summary><div class="hs">'+hs.map(function(s){
    return '<b>'+esc(s.title)+'</b>'+(s.pre?'<pre class="mono">'+esc(s.lines.join('\n'))+'</pre>':'<ul>'+s.lines.map(function(l){return '<li>'+esc(l)+'</li>'}).join('')+'</ul>')}).join('')+'</div></details>':''}

function manual(){
  var groups={},order=[];
  D.manual.forEach(function(m){if(!groups[m.group]){groups[m.group]=[];order.push(m.group)}groups[m.group].push(m)});
  var h='';
  order.forEach(function(g){
    var rows=groups[g].slice().sort(function(a,b){var A=tickState(a),B=tickState(b);
      if(A.due!==B.due)return A.due?-1:1; return (A.date||'')<(B.date||'')?-1:1});
    h+='<div class="group">'+esc(g)+' · '+rows.filter(function(m){return tickState(m).due}).length+' due of '+rows.length+'</div>';
    rows.forEach(function(m){var s=tickState(m),u=safeUrl(m.link);
      var mine=!s.date?'not checked yet':(s.newer?'pipeline found something after your last look · ':s.stale?'stale · ':'')+'you checked '+ago(s.days);
      h+='<div class="row'+(s.due?'':' dim')+'"><input type="checkbox" data-k="'+esc(m.key)+'"'+(s.date&&!s.stale&&!s.newer?' checked':'')+' aria-label="Checked '+esc(m.name)+'"><div class="body"><div class="top"><span class="co">'+(u?'<a href="'+esc(u)+'" target="_blank" rel="noopener">'+esc(m.name)+'</a>':esc(m.name))+'</span>'+(m.link_kind==='search'?'<span class="tag">search link</span>':'')+'</div>'+knowLine(m)+'<div class="why">'+esc(m.why)+'</div>'+(m.last_hit?'<div class="hit'+(m.hit_is_live?' live':'')+'">Pipeline: '+esc(m.last_hit)+'</div>':'')+'</div><div class="right"><small>'+esc(mine)+(s.date?'<br>'+esc(nice(s.date)):'')+'</small></div></div>'})});
  el('manual').innerHTML=h||'<div class="empty">No manual-check companies in the watchlist.</div>';
  Array.prototype.forEach.call(el('manual').querySelectorAll('input'),function(c){c.onchange=function(){
    var k=c.getAttribute('data-k'); if(c.checked)ticks[k]=iso(today); else delete ticks[k];
    saveTicks(); manual(); tiles()}})}

function quiet(){
  chips('zchips',ZF,zFilter,function(k){zFilter=k;quiet()});
  var rows=D.quiet.filter(ZF[zFilter][1]).slice().sort(function(a,b){return (b.days||0)-(a.days||0)});
  el('quiet').innerHTML=rows.length?rows.map(function(z){var m=[];
    if(z.furthest_stage&&z.furthest_stage!=='applied')m.push('<span class="tag good">reached '+esc(z.furthest_stage)+'</span>');
    if(z.channel&&z.channel!=='pipeline')m.push('<span class="tag">'+esc(z.channel.replace('_',' '))+'</span>');
    if(!z.applied_is_exact)m.push('<span>send date not recorded; counting from surfaced</span>');
    return '<div class="row"><div class="body"><div class="top"><span class="co">'+esc(z.company)+'</span><span>'+titleLink(z)+'</span></div><div class="meta">'+m.join('')+'</div></div><div class="right"><b class="mono">'+z.days+'d</b><small>applied '+esc(nice(z.applied))+'</small></div></div>'
  }).join(''):'<div class="empty">Nothing in this view.</div>'}

// Progress (dashboard phase two, D42). P is read_progress() in this file. A Sent click the next
// run hasn't recorded yet is counted from the page's own marks, so today's number isn't a day
// behind; once the run records it the row leaves the queue and the tracker's count takes over.
var P=D.progress||{}, pDays=30, PRANGE={30:['Last 30 days'],90:['Last 90 days']}, NS='http://www.w3.org/2000/svg';
function sv(tag,a,parent){var e=document.createElementNS(NS,tag);for(var k in a)e.setAttribute(k,a[k]);if(parent)parent.appendChild(e);return e}
function mkEl(tag,cls,text,parent){var e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;if(parent)parent.appendChild(e);return e}
function addDays(d,n){return new Date(d.getFullYear(),d.getMonth(),d.getDate()+n)}
function monday(d){return addDays(d,-((d.getDay()+6)%7))}
function pct(a,b){if(!b)return '';var p=100*a/b;return (p<10?p.toFixed(1):Math.round(p))+'%'}
function plural(n,one,many){return n+' '+(n===1?one:(many||one+'s'))}
function pendingSends(){var live={},by={};D.queue.forEach(function(q){live[q.key]=1});
  Object.keys(marks).forEach(function(k){var m=marks[k];
    if(m&&m.a==='sent'&&live[k]&&day(m.d))(by[m.d]=by[m.d]||[]).push(m.c||'?')});
  return by}
// Every day from the epoch through today. The 7-day average needs a full week behind it.
function sendSeries(){var ep=day(P.epoch),pend=pendingSends(),out=[];if(!ep)return out;
  for(var d=ep;d<=today;d=addDays(d,1)){var k=iso(d),r=(P.days&&P.days[k])||[],p=pend[k]||[];
    out.push({d:d,k:k,rec:r,pend:p,n:r.length+p.length})}
  out.forEach(function(x,i){if(i<6){x.avg=null;return}var s=0;for(var j=i-6;j<=i;j++)s+=out[j].n;x.avg=s/7});
  return out}
function talks(){return (P.rounds||[]).filter(function(r){return r.kind!=='assessment'})}

// A chart card: title, subtitle, legend, the plot, one tooltip, and a table twin underneath.
function card(id,title,sub,legend){var h=el(id);h.textContent='';
  mkEl('h3',null,title,h);if(sub)mkEl('div','vsub',sub,h);
  if(legend&&legend.length){var lg=mkEl('div','legend',null,h);legend.forEach(function(l){
    var s=mkEl('span',null,null,lg),i=mkEl('i',l[0],null,s);if(l[1])i.style.background=l[1];s.appendChild(document.createTextNode(l[2]))})}
  var plot=mkEl('div',null,null,h),tip=mkEl('div','vtip',null,h);tip.hidden=true;
  return {host:h,plot:plot,tip:tip}}
function tableTwin(host,id,label,head,rows){
  var d=document.createElement('details');d.setAttribute('data-d',id);if(openD[id])d.open=true;host.appendChild(d);
  mkEl('summary',null,label,d);var w=mkEl('div','tw',null,d),t=mkEl('table','vt',null,w),tr=mkEl('tr',null,null,mkEl('thead',null,null,t));
  head.forEach(function(c){mkEl('th',c[1]?'n':null,c[0],tr)});var tb=mkEl('tbody',null,null,t);
  rows.forEach(function(r){var x=mkEl('tr',null,null,tb);r.forEach(function(v,i){mkEl('td',head[i][1]?'n':null,v,x)})});
  if(!rows.length){var e=mkEl('tr',null,null,tb),c=mkEl('td',null,'Nothing in this range.',e);c.colSpan=head.length}}
function barPath(x,y0,w,h,r){r=Math.min(r,w/2,h);
  return 'M'+x+','+(y0+h)+'V'+(y0+r)+'Q'+x+','+y0+' '+(x+r)+','+y0+'H'+(x+w-r)+'Q'+(x+w)+','+y0+' '+(x+w)+','+(y0+r)+'V'+(y0+h)+'Z'}
function niceTicks(max){var st=max<=5?1:max<=10?2:max<=25?5:10,top=Math.max(st,Math.ceil(max/st)*st),t=[];
  for(var v=0;v<=top;v+=st)t.push(v);return t}
// Stacked columns on one baseline, an optional 2px line and a shaded band on the same axis.
// Hover or arrow keys pick the nearest column; the tooltip and the table carry the values.
function columns(cv,c){
  var W=Math.max(280,cv.plot.clientWidth||0),H=c.h||210,m={l:28,r:6,t:8,b:22},pw=W-m.l-m.r,ph=H-m.t-m.b,n=c.n,top,i;
  var max=c.minMax||1;
  for(i=0;i<n;i++){var s=0;c.stacks.forEach(function(st){s+=st.vals[i]});max=Math.max(max,s);
    if(c.line&&c.line.vals[i]!=null)max=Math.max(max,c.line.vals[i])}
  if(c.band)max=Math.max(max,c.band[1]+1);
  var ticks=niceTicks(max);top=ticks[ticks.length-1];
  function y(v){return m.t+ph-v/top*ph}
  var slot=pw/n,bw=slot>6?Math.min(24,slot*0.64):Math.max(1,slot-1);
  function cx(k){return m.l+slot*k+slot/2}
  var svg=sv('svg',{viewBox:'0 0 '+W+' '+H,width:W,height:H,role:'img',tabindex:'0','aria-label':c.aria},cv.plot);
  if(c.band)sv('rect',{x:m.l,y:y(c.band[1]),width:pw,height:y(c.band[0])-y(c.band[1]),fill:'var(--band)'},svg);
  var hl=sv('rect',{x:0,y:m.t,width:slot,height:ph,fill:'var(--band)',visibility:'hidden'},svg);
  ticks.forEach(function(v){sv('line',{x1:m.l,x2:W-m.r,y1:y(v),y2:y(v),stroke:v?'var(--line)':'var(--axis)','stroke-width':1,'shape-rendering':'crispEdges'},svg);
    var t=sv('text',{x:m.l-6,y:y(v)+3.5,'text-anchor':'end','font-size':11,fill:'var(--mute)','font-variant-numeric':'tabular-nums'},svg);t.textContent=v});
  for(i=0;i<n;i++){var base=0,segs=[];c.stacks.forEach(function(st){if(st.vals[i]>0)segs.push([st.color,st.vals[i]])});
    segs.forEach(function(sg,j){var y1=y(base+sg[1]),y0=y(base)-(j?2:0),h=y0-y1;base+=sg[1];if(h<=0)return;
      var x=cx(i)-bw/2;
      if(j===segs.length-1)sv('path',{d:barPath(x,y1,bw,h,4),fill:sg[0]},svg);
      else sv('rect',{x:x,y:y1,width:bw,height:h,fill:sg[0]},svg)})}
  if(c.line){var d='',pen=false,last=-1;for(i=0;i<n;i++){var v=c.line.vals[i];
      if(v==null){pen=false;continue}d+=(pen?'L':'M')+cx(i).toFixed(1)+','+y(v).toFixed(1);pen=true;last=i}
    if(d)sv('path',{d:d,fill:'none',stroke:c.line.color,'stroke-width':2,'stroke-linejoin':'round','stroke-linecap':'round'},svg);
    if(last>=0)sv('circle',{cx:cx(last),cy:y(c.line.vals[last]),r:4,fill:c.line.color,stroke:'var(--card)','stroke-width':2},svg)}
  var every=Math.max(1,Math.ceil(n/Math.max(1,Math.floor(pw/54))));
  for(i=n-1;i>=0;i-=every){var x=cx(i),t=sv('text',{x:x,y:H-6,'font-size':11,fill:'var(--mute)',
      'text-anchor':x>W-m.r-24?'end':x<m.l+24?'start':'middle'},svg);t.textContent=c.xLabel(i)}
  var sel=-1;
  function show(k){if(k<0||k>=n){hide();return}sel=k;hl.setAttribute('x',m.l+slot*k);hl.setAttribute('visibility','visible');
    var tp=c.tip(k),tip=cv.tip;tip.textContent='';mkEl('div','tt',tp.title,tip);
    tp.rows.forEach(function(r){var row=mkEl('div','tr',null,tip),key=mkEl('i',null,null,row);key.style.background=r[0];
      mkEl('b',null,r[1],row);row.appendChild(document.createTextNode(' '+r[2]))});
    if(tp.note)mkEl('div','tn',tp.note,tip);
    tip.hidden=false;var sc=svg.getBoundingClientRect().width/W||1,px=cv.plot.offsetLeft+cx(k)*sc,tw=tip.offsetWidth,hw=cv.host.clientWidth;
    // The plot div, not the svg: SVG elements have no offsetLeft.
    var left=px+14+tw>hw-4?px-14-tw:px+14;tip.style.left=Math.max(4,left)+'px';tip.style.top=(cv.plot.offsetTop+6)+'px'}
  function hide(){sel=-1;hl.setAttribute('visibility','hidden');cv.tip.hidden=true}
  function at(ev){var r=svg.getBoundingClientRect(),x=(ev.clientX-r.left)*W/r.width;return Math.floor((x-m.l)/slot)}
  svg.addEventListener('pointermove',function(ev){var k=at(ev);if(k!==sel)show(k)});
  svg.addEventListener('pointerdown',function(ev){show(at(ev))});
  svg.addEventListener('pointerleave',hide);
  svg.addEventListener('focus',function(){show(sel<0?n-1:sel)});svg.addEventListener('blur',hide);
  svg.addEventListener('keydown',function(ev){if(ev.key==='ArrowLeft'||ev.key==='ArrowRight'){ev.preventDefault();
      show(Math.min(n-1,Math.max(0,(sel<0?n-1:sel)+(ev.key==='ArrowLeft'?-1:1))))}else if(ev.key==='Escape')hide()})}

function names(list,max){var u={};list.forEach(function(x){u[x]=(u[x]||0)+1});
  var k=Object.keys(u).map(function(x){return u[x]>1?x+' ×'+u[x]:x});
  return k.length>max?k.slice(0,max).join(', ')+', and '+(k.length-max)+' more':k.join(', ')}

function progress(){
  if(P.error){el('prog-sub').textContent='';el('prog-kpis').textContent='';el('prog-range').textContent='';
    ['viz-sent','viz-rounds','viz-funnel'].forEach(function(x){el(x).style.display='none'});
    el('prog-sub').innerHTML='<div class="strip bad">The progress charts could not be built this run: '+esc(P.error)+'</div>';return}
  var all=sendSeries(),T=P.target||[6,7],R=talks();if(!all.length)return;
  var sub='A send is an application the tracker has recorded, from a confirmation email or your Sent click, counted from '+nice(P.epoch)+' on. Sent clicks show up here the moment you make them.';
  if(P.inexact)sub+=' '+plural(P.inexact,'send has','sends have')+' no send date and '+(P.inexact===1?'is':'are')+' counted on the day it was tailored.';
  if(P.rounds_note)sub+=' '+P.rounds_note;
  el('prog-sub').textContent=sub;

  // Headline numbers.
  var t=all[all.length-1],wk=all.slice(-7),wn=0;wk.forEach(function(x){wn+=x.n});
  var since30=iso(addDays(today,-29)),r30=R.filter(function(r){return r.date>=since30}),lastR=R[R.length-1];
  var k=[[t.n>=T[0]?'good':'',t.n,'sent today, against a target of '+T[0]+'-'+T[1]+(t.pend.length?' ('+t.pend.length+' not recorded yet)':'')],
    [wn/7>=T[0]?'good':'',wn,'sent in the last 7 days, '+(wn/7).toFixed(1)+' a day'],
    [r30.length?'good':'',r30.length,'interview '+(r30.length===1?'round':'rounds')+' in the last 30 days'+(lastR?'; the last was '+lastR.company+', '+nice(lastR.date):'')]];
  var kh=el('prog-kpis');kh.textContent='';
  k.forEach(function(x){var d=mkEl('div','kpi'+(x[0]?' '+x[0]:''),null,kh);mkEl('b',null,String(x[1]),d);mkEl('span',null,x[2],d)});

  chips('prog-range',PRANGE,String(pDays),function(v){pDays=+v;progress()});

  // Sends a day.
  var s=all.slice(-pDays),hasPend=s.some(function(x){return x.pend.length});
  var cv=card('viz-sent','Applications sent per day','Each column is one day. The line is the trailing 7-day average.',
    [['sw','var(--s1)','Sent, recorded']].concat(hasPend?[['sw','var(--s1p)','Marked Sent, not recorded yet']]:[]).concat([['ln','var(--ink2)','7-day average'],['bd','','Target, '+T[0]+'-'+T[1]+' a day']]));
  columns(cv,{n:s.length,band:T,minMax:T[1]+1,
    stacks:[{color:'var(--s1)',vals:s.map(function(x){return x.rec.length})},{color:'var(--s1p)',vals:s.map(function(x){return x.pend.length})}],
    line:{color:'var(--ink2)',vals:s.map(function(x){return x.avg})},
    xLabel:function(i){return nice(s[i].k)},
    aria:'Applications sent per day, last '+s.length+' days. '+wn+' in the last 7 days. The table below the chart has every value.',
    tip:function(i){var x=s[i],rows=[['var(--s1)',x.rec.length,'sent'+(x.pend.length?', recorded':'')]];
      if(x.pend.length)rows.push(['var(--s1p)',x.pend.length,'marked Sent, not recorded yet']);
      if(x.avg!=null)rows.push(['var(--ink2)',x.avg.toFixed(1),'a day, 7-day average']);
      return {title:x.d.toLocaleDateString(undefined,{weekday:'short',month:'short',day:'numeric'}),rows:rows,note:names(x.rec.concat(x.pend),8)}}});
  tableTwin(cv.host,'prog|sent','Show the numbers',[['Day'],['Sent',1],['Not recorded yet',1],['7-day avg',1],['Companies']],
    s.slice().reverse().filter(function(x){return x.n||x.avg}).map(function(x){
      return [nice(x.k),String(x.rec.length),x.pend.length?String(x.pend.length):'',x.avg==null?'':x.avg.toFixed(1),names(x.rec.concat(x.pend),40)]}));

  // Interview rounds a week, over the same range.
  var w0=monday(addDays(today,-(pDays-1))),weeks=[];
  for(var d=w0;d<=today;d=addDays(d,7))weeks.push({d:d,k:iso(d),end:iso(addDays(d,6)),first:[],later:[],tests:[]});
  (P.rounds||[]).forEach(function(r){weeks.forEach(function(w){if(r.date>=w.k&&r.date<=w.end)
    (r.kind==='assessment'?w.tests:(r.round||1)>1?w.later:w.first).push(r)})});
  var rn=0;weeks.forEach(function(w){rn+=w.first.length+w.later.length});
  var cr=card('viz-rounds','Interview rounds per week',rn?'Each column is a week, Monday to Sunday. '+plural(rn,'round')+' in this range.':
      'No rounds logged in this range'+(lastR?'. The last one was '+lastR.company+' on '+nice(lastR.date)+'.':'.'),
    [['sw','var(--s1)','First conversation'],['sw','var(--s2)','Later rounds']]);
  columns(cr,{n:weeks.length,minMax:2,h:150,
    stacks:[{color:'var(--s1)',vals:weeks.map(function(w){return w.first.length})},{color:'var(--s2)',vals:weeks.map(function(w){return w.later.length})}],
    xLabel:function(i){return nice(weeks[i].k)},
    aria:'Interview rounds per week, '+weeks.length+' weeks. '+rn+' rounds in this range. The table below the chart lists every round.',
    tip:function(i){var w=weeks[i],rows=[['var(--s1)',w.first.length,'first '+(w.first.length===1?'conversation':'conversations')],['var(--s2)',w.later.length,'later '+(w.later.length===1?'round':'rounds')]];
      var list=w.first.concat(w.later,w.tests).map(function(r){return r.company+(r.kind==='assessment'?' (assessment)':' R'+(r.round||1))+', '+nice(r.date)});
      return {title:'Week of '+nice(w.k),rows:rows,note:list.join('; ')}}});
  tableTwin(cr.host,'prog|rounds','Every logged round',[['Date'],['Company'],['Round'],['What it was']],
    (P.rounds||[]).slice().reverse().map(function(r){return [nice(r.date),r.company,r.kind==='assessment'?'assessment':'R'+(r.round||1)+' '+r.kind,r.label||'']}));

  // What came of each send, since the epoch.
  var f=P.funnel||{},fh=el('viz-funnel');fh.textContent='';
  mkEl('h3',null,'What came of each send',fh);
  mkEl('div','vsub','All '+f.sent+' sends since '+nice(P.epoch)+'. A send reaches a stage once a round is logged for it or the tracker records the stage.',fh);
  var g=mkEl('div','fun',null,fh);
  [['Sent',f.sent],['Reached a screen',f.screen],['Reached a later round',f.later],['Offer',f.offer]].forEach(function(r,i){
    mkEl('div',null,r[0],g);var b=mkEl('div','bar',null,mkEl('div','trk',null,g));
    b.style.width=(f.sent&&r[1]?Math.max(0.8,100*r[1]/f.sent):0)+'%';
    mkEl('div','fv2',r[1]+(i&&r[1]&&f.sent?' · '+pct(r[1],f.sent):''),g)});
  var st=[[f.waiting,'still inside '+P.ghost_days+' days'],[f.ghosted,'no reply after '+P.ghost_days+' days'],[f.rejected,'rejected without an interview'],
    [f.closed,'closed'],[f.assessment,'at an assessment'],[f.interviewed,'interviewed']].filter(function(x){return x[0]});
  mkEl('div','stand','Where they stand: '+st.map(function(x){return x[0]+' '+x[1]}).join(' · ')+'.',fh);
  tableTwin(fh,'prog|weeks','By the week they were sent',[['Week of'],['Sent',1],['Screen',1],['Later round',1],['Offer',1],['Rejected',1],['Closed',1],['No reply '+P.ghost_days+'d+',1],['Waiting',1]],
    (P.weeks||[]).slice().reverse().map(function(w){return [nice(w.week)].concat(['sent','screen','later','offer','rejected','closed','ghosted','waiting'].map(function(x){return String(w[x]||0)}))}))}
var pW=0,pT=null;
window.addEventListener('resize',function(){clearTimeout(pT);pT=setTimeout(function(){var w=el('viz-sent').clientWidth;if(w!==pW){pW=w;progress()}},150)});

function foot(){var c=D.counts,f=[];
  if(c.pre_epoch_quiet)f.push(c.pre_epoch_quiet+' applied rows from before Jul 28, where a send was never confirmable.');
  if(c.manual_review_unsurfaced)f.push(c.manual_review_unsurfaced+' discovery-queue companies flagged for manual review. They arrive through the digest a few at a time.');
  if(c.unpollable_unreported)f.push(c.unpollable_unreported+' unpollable companies waiting their turn in the weekly report.');
  if(c.in_process)f.push(c.in_process+' rows with an in-process stage ('+esc((c.unknown_stages||[]).join(', '))+'). Their interview rounds are charted under Progress.');
  if(c.skipped)f.push(c.skipped+' roles you marked skip. They stay in the tracker until they retire.');
  if(D.contacts&&D.contacts.note)f.push('Who you know at each company: '+esc(D.contacts.note)+', so no row shows a contact.');
  el('foot').innerHTML=f.map(function(x){return '<li>'+x+'</li>'}).join('')}

el('stamp').textContent='Generated '+new Date(D.generated).toLocaleString(undefined,{weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
el('exp').textContent=D.expiry_days;
el('swin').textContent=D.screened_window||7;
strips();tiles();progress();todayList();queue();screened();leads();runNotes();manual();quiet();foot();
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
