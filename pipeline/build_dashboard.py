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

The page keeps three kinds of state, all in the Shelf's per-page storage:
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

jd_coverage_pct renders as a pass/fail chip at 80 and is never sortable, per the
standing rule that it is a gate and not a ranking signal.

A failed build must never fail the daily run: every failure prints one
`dashboard: FAILED ...` line, leaves yesterday's file in place, and exits 0. The
page itself shows a stale strip when a weekday run should have replaced it and
didn't (schedule-aware, so weekends don't cry wolf), because a failed build is otherwise indistinguishable from a quiet day.

This file is committed to a public repo. No company names, no sample rows.
"""
import csv
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
                          "changes": [clip(x, 400) for x in (p.get("changes") or []) if clip(x, 400)][:12]}
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
            rows.append({"id": jid, "list": lst, "company": clip(x.get("company"), 120) or "?",
                         "title": clip(x.get("title"), 200) or "?", "url": clip(x.get("url"), 600),
                         "tier": clip(x.get("tier"), 12), "loc": clip(x.get("loc"), 20),
                         "seen": seen_n if isinstance(seen_n, int) and 0 < seen_n < 1000 else 1,
                         "first": clip(x.get("first"), 10), "note": clip(x.get("note"), 300)})
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


def build_data(today, now):
    with open(WATCHLIST, encoding="utf-8") as f:
        watch = json.load(f)
    queue, quiet, counts = read_outcomes(today, watch.get("_scoring_config", {}))
    counts.update(read_backlog_counts())
    screened, counts["screened_days"] = read_screened(today)
    return {"generated": now.strftime("%Y-%m-%dT%H:%M"), "expiry_days": EXPIRY_DAYS,
            "fresh_days": 14, "expiring_days": 7, "quiet_days": 10,
            # The task runs `0 3 * * 1-5`; by 8 AM a weekday's page should exist. JS weekday numbers.
            "run_weekdays": [1, 2, 3, 4, 5], "run_ready_hour": 8,
            "queue": queue, "quiet": quiet, "manual": read_manual(watch), "counts": counts,
            "screened": screened, "screened_window": SCREENED_DAYS,
            "brief": read_brief(today), "later_days": 3, "leads": read_leads(today),
            # Every job id a run has recorded. The page drops a lead mark once it's in here.
            "lead_answered": sorted(read_lead_marks()), "lead_mark_days": LEAD_MARK_DAYS}


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
    return (f"{len(data['queue'])} queue ({expiring} expiring), "
            f"{len(data.get('screened', []))} cleared, "
            f"{len(leads.get('rows') or [])} weekly leads, "
            f"{len(data['manual'])} manual, {len(data['quiet'])} quiet")


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

<h2 id="h-today">New from the last run</h2>
<div class="sub" id="today-sub"></div>
<div class="list" id="today"></div>

<h2 id="h-queue">Apply queue</h2>
<div class="sub">Tailored, not confirmed sent. Rows retire at <span id="exp"></span> days. Mark a row Sent or Skip and the next weekday run records it; a confirmation email still does the same on its own.</div>
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
var DAY=86400000, KEY='jobdash.ticks.v1', IKEY='jobdash.inbox.v1', LKEY='jobdash.leads.v1';
var SKIP={fit:'not a fit',time:'no time',materials:'materials',other:'other'};
function el(id){return document.getElementById(id)}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function day(s){var p=String(s||'').slice(0,10).split('-');return p.length===3?new Date(+p[0],+p[1]-1,+p[2]):null}
var now=new Date(), today=new Date(now.getFullYear(),now.getMonth(),now.getDate());
function since(s){var d=day(s);return d?Math.round((today-d)/DAY):null}
function iso(d){return d.getFullYear()+'-'+('0'+(d.getMonth()+1)).slice(-2)+'-'+('0'+d.getDate()).slice(-2)}
function ago(n){if(n==null)return'';if(n<=0)return'today';if(n===1)return'yesterday';if(n<14)return n+' days ago';if(n<60)return Math.round(n/7)+' wks ago';return Math.round(n/30)+' mos ago'}
function nice(s){var d=day(s);return d?d.toLocaleDateString(undefined,{month:'short',day:'numeric'}):''}
function safeUrl(u){return /^https?:\/\//i.test(u||'')?u:''}

// Ticks and marks. Storage can throw (private window, blocked site data); the page still works without it.
var ticks={}, marks={}, lmarks={}, storageOK=true;
try{ticks=JSON.parse(localStorage.getItem(KEY)||'{}')||{};marks=JSON.parse(localStorage.getItem(IKEY)||'{}')||{};
  lmarks=JSON.parse(localStorage.getItem(LKEY)||'{}')||{}}catch(e){storageOK=false}
function saveTicks(){try{localStorage.setItem(KEY,JSON.stringify(ticks))}catch(e){storageOK=false;strips()}}
// IKEY and the mark shape {a,r,e,d,ts,u,c,t} are read by pipeline/shelf_inbox.py. Change both together.
function saveMarks(){try{localStorage.setItem(IKEY,JSON.stringify(marks))}catch(e){storageOK=false;strips()}}
// LKEY and the lead mark shape {a,d,ts,u,c,t,l,tier,loc}, keyed by LinkedIn job id, are read by
// pipeline/shelf_inbox.py and recorded by pipeline/lead_marks.py. Change all three together.
function saveLeadMarks(){try{localStorage.setItem(LKEY,JSON.stringify(lmarks))}catch(e){storageOK=false;strips()}}
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
  if(!storageOK)h+='<div class="strip warn">Storage is unavailable here, so ticks and marks last only until this page closes and no run will see them.</div>';
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
  if(p.changes&&p.changes.length)h+=det(q.key+'|changes','What changed in the resume')+'<ul>'+p.changes.map(function(c){return '<li>'+esc(c)+'</li>'}).join('')+'</ul></details>';
  return h}
function rowHTML(q,full){
  return '<div class="row'+(mk(q)?' dim':'')+'"><div class="right mono" style="min-width:42px;text-align:left"><b>'+(q.score==null?'':Math.round(q.score))+'</b></div><div class="body"><div class="top"><span class="co">'+esc(q.company)+'</span><span>'+titleLink(q)+'</span></div><div class="meta">'+tags(q)+'</div>'+(full?briefPanel(q):'')+fieldsPanel(q)+acts(q)+'</div><div class="right">'+leftCell(q)+'</div></div>'}

function todayList(){
  var rows=D.queue.filter(isNew).sort(function(a,b){return (b.score||0)-(a.score||0)}), when=nice(runDate);
  el('h-today').textContent='New from the '+when+' run';
  el('today-sub').textContent=(B&&B.note)?B.note:(rows.length?'Tailored on or after '+when+'.':'');
  el('today').innerHTML=rows.length?rows.map(function(q){return rowHTML(q,true)}).join(''):'<div class="empty">No new packages from the '+esc(when)+' run.</div>'}

function runNotes(){var secs=(B&&B.sections)||[];
  el('run-wrap').style.display=secs.length?'':'none'; if(!secs.length)return;
  el('h-run').textContent='More from the '+nice(runDate)+' run';
  el('run').innerHTML=secs.map(function(x,i){return '<details class="sec" data-d="run|'+i+'"'+(openD['run|'+i]?' open':'')+'><summary>'+esc(x.title)+' <span class="sub">'+x.lines.length+'</span></summary>'+(x.note?'<div class="why" style="padding:0 12px 8px">'+esc(x.note)+'</div>':'')+'<div class="list">'+x.lines.map(function(l){var u=safeUrl(l.url);
    return '<div class="row"><div class="body">'+esc(l.text)+(u?' <a href="'+esc(u)+'" target="_blank" rel="noopener">'+esc(l.label||'link')+'</a>':'')+'</div></div>'}).join('')+'</div></details>'}).join('')}

function legacyCopy(p){var ta=document.createElement('textarea'),ok=false;ta.value=p;ta.style.position='fixed';ta.style.opacity='0';
  document.body.appendChild(ta);ta.select();try{ok=document.execCommand('copy')}catch(e){}document.body.removeChild(ta);return ok}
function copy(s){if(s.getAttribute('data-busy'))return;var p=s.getAttribute('data-copy'),old=s.textContent;
  function done(){s.setAttribute('data-busy','1');s.textContent='copied';setTimeout(function(){s.textContent=old;s.removeAttribute('data-busy')},900)}
  // Last resort when neither clipboard path is allowed: show the value and select it, so
  // Command-C finishes the job. (window.prompt is not available in every embedded browser.)
  function fallback(){if(legacyCopy(p)){done();return}
    try{s.textContent=p;var r=document.createRange();r.selectNodeContents(s);var w=window.getSelection();w.removeAllRanges();w.addRange(r);s.title='Selected. Press Command-C to copy.'}catch(e){}}
  if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(p).then(done,fallback);else fallback()}
// One listener for every copy target and every mark button, wherever the row is drawn.
document.addEventListener('click',function(ev){var t=ev.target;if(!t||!t.getAttribute)return;
  var la=t.getAttribute('data-lact');
  if(la){leadClick(t,la);return}
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
  saveMarks();todayList();queue();tiles()});

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
  el('marknote').textContent=done?done+' marked. The next weekday run records them, and they leave this list.':'';
  chips('qchips',QF,qFilter,function(k){qFilter=k;queue()});
  var rows=D.queue.filter(QF[qFilter][1]).slice();
  rows.sort(qFilter==='expiring'?function(a,b){return a.left-b.left}:function(a,b){
    if((a.age==null)!==(b.age==null))return a.age==null?1:-1; return (b.score||0)-(a.score||0)});
  el('queue').innerHTML=rows.length?rows.map(function(q){return rowHTML(q,false)}).join(''):'<div class="empty">Nothing in this view.</div>'}

function screened(){
  var rows=(D.screened||[]).slice().sort(function(a,b){return (b.score||0)-(a.score||0)});
  el('screened').innerHTML=rows.length?rows.map(function(s){var m=[];
    if(s.loc)m.push('<span class="tag'+(s.loc==='ATL'?' good':'')+'">'+esc(s.loc==='ATL'?'Atlanta':s.loc)+'</span>');
    if(s.pay)m.push('<span class="tag">'+esc(s.pay)+'</span>');
    if(s.scope)m.push('<span class="tag">'+esc(s.scope==='ic'?'IC':s.scope)+'</span>');
    if(s.gap)m.push('<span class="tag warn" title="'+esc(s.gap)+'">gap</span>');
    var n=since(s.first);
    return '<div class="row"><div class="right mono" style="min-width:42px;text-align:left"><b>'+(s.score==null?'':Math.round(s.score))+'</b></div><div class="body"><div class="top"><span class="co">'+esc(s.company)+'</span><span>'+titleLink(s)+'</span></div>'+(s.why?'<div class="why">'+esc(s.why)+(s.gap?' · gap: '+esc(s.gap):'')+'</div>':'')+'<div class="meta">'+m.join('')+'</div></div><div class="right"><small>cleared '+esc(ago(n))+'<br>'+esc(nice(s.first))+'</small></div></div>'
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
  return '<div class="row'+(lmarks[x.id]?' dim':'')+'"><div class="body"><div class="top"><span class="co">'+esc(x.company)+'</span><span>'+titleLink(x)+'</span></div><div class="meta">'+t.join('')+'</div>'+leadActs(x)+'</div><div class="right"><small>'+(x.first?'first seen<br>'+esc(nice(x.first)):'')+'</small></div></div>'}
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
      h+='<div class="row'+(s.due?'':' dim')+'"><input type="checkbox" data-k="'+esc(m.key)+'"'+(s.date&&!s.stale&&!s.newer?' checked':'')+' aria-label="Checked '+esc(m.name)+'"><div class="body"><div class="top"><span class="co">'+(u?'<a href="'+esc(u)+'" target="_blank" rel="noopener">'+esc(m.name)+'</a>':esc(m.name))+'</span>'+(m.link_kind==='search'?'<span class="tag">search link</span>':'')+'</div><div class="why">'+esc(m.why)+'</div>'+(m.last_hit?'<div class="hit'+(m.hit_is_live?' live':'')+'">Pipeline: '+esc(m.last_hit)+'</div>':'')+'</div><div class="right"><small>'+esc(mine)+(s.date?'<br>'+esc(nice(s.date)):'')+'</small></div></div>'})});
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

function foot(){var c=D.counts,f=[];
  if(c.pre_epoch_quiet)f.push(c.pre_epoch_quiet+' applied rows from before Jul 28, where a send was never confirmable.');
  if(c.manual_review_unsurfaced)f.push(c.manual_review_unsurfaced+' discovery-queue companies flagged for manual review. They arrive through the digest a few at a time.');
  if(c.unpollable_unreported)f.push(c.unpollable_unreported+' unpollable companies waiting their turn in the weekly report.');
  if(c.in_process)f.push(c.in_process+' rows with an in-process stage ('+esc((c.unknown_stages||[]).join(', '))+'). Interviews get their own section in phase two.');
  if(c.skipped)f.push(c.skipped+' roles you marked skip. They stay in the tracker until they retire.');
  el('foot').innerHTML=f.map(function(x){return '<li>'+x+'</li>'}).join('')}

el('stamp').textContent='Generated '+new Date(D.generated).toLocaleString(undefined,{weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
el('exp').textContent=D.expiry_days;
el('swin').textContent=D.screened_window||7;
strips();tiles();todayList();queue();screened();leads();runNotes();manual();quiet();foot();
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
