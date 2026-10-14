#!/usr/bin/env python3
"""Deterministic tracking-file updater for the daily pipeline (Step 6).

Replaces hand-editing of seen_jobs.json / seen_urls.json / outcomes.csv with
Read+Write tools, which (a) burns tokens re-writing a 140KB+ JSON file and
(b) caused the 2026-06-30 corruption where entries were written outside the
top-level "jobs" object and broke poll_ats.py dedup.

Usage:
    .venv/bin/python pipeline/update_tracking.py <track_file.json> [--touch-reseen <ats_hits.json>]

<track_file.json> is a small per-run file Claude writes with this schema:
{
  "run_date": "2026-07-01",
  "jobs": [
    {
      "dedup_key": "acme::ai-deployment-manager",
      "company": "Acme Robotics",
      "title": "AI Deployment Manager",
      "url": "https://...",
      "score": 103,
      "jd_coverage_pct": 100,        // optional
      "notes": "",                    // optional
      "retailor": "Jane_Doe_Acme_AIDM_2",   // optional, see RETAILOR below
      "never_sent": true              // optional, read only with retailor
    }
  ]
}

Behavior:
- seen_jobs.json: adds new entries under the top-level "jobs" object
  (applied=false, outcome=null). For existing dedup_keys, updates
  last_seen_date ONLY — never clobbers first_seen_date/applied/outcome/notes.
- seen_urls.json: appends new URLs, dedupes, keeps last 500.
- outcomes.csv: appends one row per NEW job using the canonical header
  (OUTCOMES_HEADER below) with stage=surfaced and empty outcome. Skips a job
  whose dedup key was seen before or whose URL already has a row, and prints
  each one it skips under NO ROW WRITTEN.
- --touch-reseen: reads the ats_hits file's reseen_keys array and bumps
  last_seen_date on those seen_jobs entries.
- Writes seen_jobs.json atomically (tmp file + rename) and keeps a .bak of
  the previous version.

RETAILOR (added 2026-10-13)
The dedup above is right when a job is the same package coming around again.
It was wrong, and silent, when the job was a NEW package for a posting the
tracker already knew. Replaying the track files on 2026-10-13 found four
packages since 2026-08-14 whose posting already had a retired row at the same
URL, and three postings tailored as a new requisition under an old dedup key.
None got a row, so none could reach the dashboard queue or be marked sent. The
case that surfaced it was a package he asked for that day, for a posting first
tailored in July whose row had since expired.

Two things changed.

1. Nothing is skipped quietly. Every job that gets no row is printed under
   NO ROW WRITTEN with the reason, unless its own row was written earlier the
   same day (a second run of the same track file).

2. "retailor": "<new package stem>" on a job says: this is a new package,
   tailored now, so record it. The value is the stem fit_check.py --claim
   handed out, and the job's notes must name <stem>.pdf like any Step 6 row.
     - The URL has no row: a row is appended, as for any new job.
     - The URL has exactly one row and it is `expired`: that row is REOPENED
       IN PLACE. It becomes stage=surfaced with today's surfaced_date and
       applied_date and the job's score, coverage, readiness columns, and
       notes; his_verdict is emptied, because a verdict was his call on the
       earlier package. The URL stays on one row, which is the point:
       mark_applied.py, mark_verdict.py, shelf_inbox.py, mark_outcome.py, and
       the dashboard all find a row by its URL, and the first three write
       nothing when two rows share one.
     - A `closed` row is reopened only with "never_sent": true as well.
       Closed usually follows a send and the row cannot always say which, so
       somebody has to: set it only when Aneesh says he never applied.
     - Everything else is refused, printed under RETAILOR REFUSED, and the
       script exits 1 after doing the rest of its work:
         a row in a sent stage, or showing any sign of a send (a sent_*
         verdict, a furthest_stage, an outcome, a "marked sent" note, and for
         a post-epoch row an applied_date that moved off its surfaced_date or
         a seen_jobs.json entry flipped to applied, the two things a
         promotion leaves): it is the record of that application;
         a row that is still `surfaced`: a Sent or Skip click on the
         dashboard is stored under the row's URL and the page hides a marked
         row, so a click made on the old package would land on the new one.
         Adjust an open package under its own stem instead (CLAUDE.md,
         "Adjusting a package from an earlier day");
         a row at that URL under a different company name;
         two rows sharing the URL;
         a stem some row already names (a retailor records a new package; it
         cannot restart the clock on an old one);
         notes that do not name the stem.
   Before the rewrite the row as it stood is appended to
   jobs/reopened_rows.jsonl (a crash right after can leave a spare entry
   there, never a rewritten row with no record) and outcomes.csv is copied to
   outcomes.csv.prereopen.bak. The new notes end with a `reopened <date>`
   stamp naming the old stage, date, verdict, and package.
   This is the only way surfaced_date ever changes on an existing row.

   Leftover dashboard marks: a retired row left the page's queue at the
   rebuild after it was retired, and the page drops a mark for a row it no
   longer lists the next time it is opened. A mark can outlive the row all
   the same (the page was never reopened, or that day's drain failed), so
   shelf_inbox.py treats a mark dated before its row's surfaced_date as stale:
   only a reopened row can be younger than a click on it. What that cannot see
   is a click made the same day as the reopen, so when the old row had a
   verdict the reopen prints it; look at the page before the next drain.

The daily run never sets the key: Step 4-pre stops it from tailoring a posting
that already has a row. It is for a package Aneesh asked for.

Two small differences on the plain path, both toward fewer duplicate rows: a
URL is compared with surrounding whitespace stripped (as mark_applied.py does),
and two jobs in one track file that share a URL make one row, not two.
"""
import argparse
import csv
import json
import os
import re
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SEEN_JOBS = os.path.join(SCRIPT_DIR, "jobs", "seen_jobs.json")
SEEN_URLS = os.path.join(SCRIPT_DIR, "jobs", "seen_urls.json")
OUTCOMES = os.path.join(SCRIPT_DIR, "outcomes.csv")
# NOTE: this list is the canonical outcomes.csv schema and must stay in sync
# with CANONICAL in repair_outcomes.py. Three incompatible shapes accumulated
# here historically and silently hid 32% of the file from mark_applied.py;
# change both files together, then run repair_outcomes.py to migrate.
OUTCOMES_HEADER = ["applied_date", "company", "title", "url", "fit_score",
                   "jd_coverage_pct", "stage", "outcome", "notes",
                   "source_channel", "surfaced_date", "unmet_hard_reqs",
                   "vendor_tool_named_in_jd", "hard_req_cap_trigger",
                   "furthest_stage", "ic_scope", "his_verdict"]

# Retailor (see the docstring). jobs/ is gitignored, like outcomes.csv itself.
REOPENED_ROWS = os.path.join(SCRIPT_DIR, "jobs", "reopened_rows.jsonl")
REOPEN_BACKUP = ".prereopen.bak"     # pipeline/*.bak* is gitignored
# The application went out. Same stages mark_applied.py and shelf_inbox.py treat
# as sent, less `closed`, which is handled on its own.
SENT_STAGES = ("applied", "rejected", "interview", "assessment", "onsite", "offer")
PACKAGE_PDFS = (".pdf", "_cover.pdf", "_ATS.pdf")
# A package stem inside a row's notes ("tailored/X.pdf + _cover.pdf" gives X).
PACKAGE_IN_NOTES = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]*?)(?:_cover|_ATS)?\.pdf")
# The outcome-data epoch (CLAUDE.md). From here on only mark_applied.py's
# promotion moves a row's applied_date off its surfaced_date.
EPOCH = "2026-07-28"


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def atomic_write_json(path, data):
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def norm_url(u):
    # Same normalization as mark_applied.py: a reopened row has to be found by
    # the key a confirmation or a dashboard mark will look it up with.
    return (u or "").strip().rstrip("/").lower()


def slug(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def names_package(notes, stem):
    """Do these notes name one of the package's PDFs? Substring, because that is
    how check_voice.py and rotate_apply_folder.py find a package's row."""
    return any(stem + suffix in (notes or "") for suffix in PACKAGE_PDFS)


def build_row(j, run_date):
    """One outcomes.csv row for a freshly tailored job, in OUTCOMES_HEADER order."""
    # surfaced_date is written here and nowhere else. mark_applied.py overwrites
    # applied_date on promotion, so this is the only durable record of when the
    # package on this row was surfaced. It changes only when a retailor reopens
    # the row for a new package.
    return [run_date, j["company"], j["title"], j.get("url", ""),
            j.get("score", ""), j.get("jd_coverage_pct", ""),
            "surfaced", "", j.get("notes", ""),
            j.get("source_channel", "pipeline"),
            run_date,
            j.get("unmet_hard_reqs", ""),
            j.get("vendor_tool_named_in_jd", ""),
            j.get("hard_req_cap_trigger", ""),
            # furthest_stage: added to OUTCOMES_HEADER on 2026-08-27
            # but NOT to this row, so every row appended after
            # that date came out 14 columns wide against a 15-column
            # header. mark_applied.py silently skips any row whose
            # column count differs from the header, so those rows
            # could never be promoted when their confirmation
            # arrived -- the exact failure the 2026-07-28 audit found
            # for 32% of the file. Caught 2026-08-28.
            #
            # Empty is CORRECT here and must stay empty: per
            # CLAUDE.md, "" means not recorded, which is what a
            # freshly surfaced row is. It is not "never interviewed".
            "",
            # ic_scope: added 2026-09-07 alongside the IC-scope
            # salary floor (_scoring_config -> ic_scope_rule).
            # Values: "ic", "manages", or "" for NOT RECORDED --
            # the same three-state rule as hard_req_cap_trigger and
            # furthest_stage. Empty is correct for the ~265 rows
            # that predate the column and must NOT be backfilled by
            # assumption: "nobody checked" and "checked, has no
            # reports" are different facts.
            #
            # ADDED TO THE HEADER AND TO THIS ROW IN THE SAME
            # COMMIT, deliberately. furthest_stage was added to
            # OUTCOMES_HEADER on 2026-08-27 and NOT here, so every
            # row appended for a month came out one column short and
            # mark_applied.py silently skipped all of them.
            j.get("ic_scope", ""),
            # his_verdict: added 2026-09-30, header and row in
            # the same commit for the reason above. Always "" here:
            # only Aneesh sets it, via mark_verdict.py.
            ""]


def record_outcomes(track_jobs, added_set, run_date, header, rows, applied_urls=frozenset()):
    """Decide what each track-file job does to outcomes.csv. No file I/O.

    `applied_urls` is the normalized URLs seen_jobs.json has as applied=true,
    which mark_applied.py sets on every promotion.

    Mutates `rows`: a reopened row is rewritten in place and an appended row is
    added to the end, so a later job in the same file sees what an earlier one
    did. Returns a dict:
        appended  rows to write, in order
        reopened  one dict per reopened row: the row as it stood (`old`), and
                  what main() prints and archives
        already   count of jobs whose row was written earlier today
        skipped   (label, why) for jobs the dedup left without a row
        refused   (label, why) for retailor jobs that could not be recorded
    """
    ci = {n: i for i, n in enumerate(header)}
    out = {"appended": [], "reopened": [], "already": 0, "skipped": [], "refused": []}

    def cell(r, name):
        # str(): a row added by this run still holds the job's raw values, and a
        # job's notes or score can be null or a number until csv.writer writes them.
        i = ci.get(name)
        if i is None or i >= len(r) or r[i] is None:
            return ""
        return str(r[i]).strip()

    def where(r):
        return (f"stage={cell(r, 'stage') or 'blank'}, "
                f"surfaced {cell(r, 'surfaced_date') or 'date not recorded'}")

    def add(j):
        row = build_row(j, run_date)
        out["appended"].append(row)
        rows.append(row)

    for j in track_jobs:
        label = f"{j['company']} — {j['title']}"
        u = norm_url(j.get("url"))
        same = [r for r in rows if u and norm_url(cell(r, "url")) == u]
        stem = j.get("retailor")

        if not stem:
            # The dedup as it has always been: a row for a new key whose URL is
            # not tracked yet. What is new is that the rest gets printed.
            if same:
                # "Already recorded" means this job's own row: surfaced today and
                # carrying this job's notes (a verdict or a Shelf mark only ever
                # appends to them). A row surfaced today for a different package
                # is a skip like any other, and gets printed.
                mine = str(j.get("notes") or "").strip()

                def own(r):
                    if cell(r, "surfaced_date") != run_date:
                        return False
                    if mine:   # every later writer joins its addition with "; "
                        n = cell(r, "notes")
                        return n == mine or (n.startswith(mine)
                                             and n[len(mine):].lstrip().startswith(";"))
                    return (cell(r, "company"), cell(r, "title")) == \
                        (str(j["company"]).strip(), str(j["title"]).strip())

                if any(own(r) for r in same):
                    out["already"] += 1
                else:
                    out["skipped"].append((label, f"its URL already has a row ({where(same[0])})"))
            elif j["dedup_key"] in added_set:
                add(j)
            else:
                out["skipped"].append((label, "its dedup key was seen before and "
                                       + ("its URL has no row" if u else "it has no URL")))
            continue

        def refuse(why):
            out["refused"].append((label, why))

        if not isinstance(stem, str) or not re.fullmatch(r"[A-Za-z0-9_]+", stem):
            refuse('"retailor" must be the new package\'s stem, the one fit_check.py --claim '
                   'gave you (letters, digits, and underscores)')
            continue
        if header != OUTCOMES_HEADER:
            refuse("outcomes.csv is not on the current schema; run repair_outcomes.py --apply first")
            continue
        if not u:
            refuse("a retailor needs the posting URL")
            continue
        if stem + ".pdf" not in str(j.get("notes") or ""):
            refuse(f"its notes must name {stem}.pdf; that filename is how the other scripts "
                   f"find the row")
            continue
        target = same[0] if len(same) == 1 else None
        taken = [r for r in rows if r is not target and names_package(cell(r, "notes"), stem)]
        if taken:
            refuse(f"{stem}.pdf is already named by another row ({cell(taken[0], 'company')} — "
                   f"{cell(taken[0], 'title')}); claim a free stem with fit_check.py --claim")
            continue
        if not same:
            add(j)   # a new requisition under a dedup key the tracker had seen
            continue
        if target is None:
            refuse(f"{len(same)} rows share its URL; look at them by hand")
            continue
        if len(target) != len(header):
            refuse("the row at its URL has drifted columns; run repair_outcomes.py --apply first")
            continue
        stage = cell(target, "stage").lower()
        if names_package(cell(target, "notes"), stem):
            # It names this very package. Surfaced today, it is this job's own row
            # (whatever has happened to it since); older, it is a clock restart.
            if cell(target, "surfaced_date") == run_date:
                out["already"] += 1
            else:
                refuse(f"its row already names {stem}.pdf ({where(target)}). A retailor records "
                       f"a new package; it does not restart the clock on an old one")
            continue
        if slug(cell(target, "company")) != slug(j["company"]):
            refuse(f"the row at its URL belongs to {cell(target, 'company')} "
                   f"({cell(target, 'title')}). If that is this posting, use that company name "
                   f"on the job; if it is not, the URL is too general to match on")
            continue
        verdict = cell(target, "his_verdict").lower()
        outcome = cell(target, "outcome").lower()
        applied, surfaced = cell(target, "applied_date"), cell(target, "surfaced_date")
        sent = (f"stage={stage}" if stage in SENT_STAGES
                else f"his_verdict={verdict}" if verdict.startswith("sent_")
                else f"furthest_stage={cell(target, 'furthest_stage')}" if cell(target, "furthest_stage")
                else f"outcome={outcome}" if outcome not in ("", "closed")
                else "its notes say he marked it sent" if "marked sent on the shelf" in cell(target, "notes").lower()
                else (f"applied_date {applied} moved off surfaced_date {surfaced}, which only a "
                      f"promotion does") if applied and surfaced >= EPOCH and applied != surfaced
                # A send on the day it was surfaced leaves the two dates equal.
                else "seen_jobs.json has this URL as applied" if surfaced >= EPOCH and u in applied_urls
                else "")
        if sent:
            refuse(f"its row looks sent ({sent}), and a sent row is the record of that application")
            continue
        if stage == "surfaced":
            refuse(f"its row is still open (surfaced {surfaced or 'on a date not recorded'}). "
                   f"A retailor reopens a retired row; for an open one, adjust the package under "
                   f"its own stem (CLAUDE.md, \"Adjusting a package from an earlier day\")")
            continue
        if stage == "closed" and j.get("never_sent") is not True:
            refuse('its row is closed, and a closed row may have been sent. If Aneesh says he '
                   'never applied to it, add "never_sent": true and run this again')
            continue
        if stage not in ("expired", "closed"):
            refuse(f"stage={stage or 'blank'} is not one a retailor reopens")
            continue

        old = list(target)
        new = build_row(j, run_date)
        new[ci["url"]] = old[ci["url"]]   # the stored spelling; marks and confirmations key on it
        if not j.get("source_channel"):
            new[ci["source_channel"]] = cell(target, "source_channel") or "pipeline"
        # The stamp names the earlier package without ".pdf", on purpose: the other
        # scripts find a row by a PDF filename in its notes, and this row now
        # answers for the new package only.
        packages = sorted({m.group(1) for m in PACKAGE_IN_NOTES.finditer(cell(target, "notes"))})
        stamp = (f"reopened {run_date}: this row was {stage}, last surfaced "
                 f"{surfaced or 'on a date not recorded'}"
                 + (f", his verdict then {verdict}" if verdict else "")
                 + (f", package {' and '.join(packages)}" if packages else "")
                 + "; it now carries a new package, and the row as it stood is in "
                   "jobs/reopened_rows.jsonl")
        notes = str(new[ci["notes"]] or "").strip()
        new[ci["notes"]] = f"{notes}; {stamp}"
        target[:] = new
        was_title = cell(old, "title")
        out["reopened"].append({"old": old, "label": label, "stage": stage, "stem": stem,
                                "verdict": verdict, "packages": packages,
                                "was_title": was_title if was_title != str(j["title"]).strip() else ""})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("track_file")
    ap.add_argument("--touch-reseen", metavar="ATS_HITS_JSON", default=None)
    args = ap.parse_args()

    track = load_json(args.track_file, None)
    if not track or "jobs" not in track or "run_date" not in track:
        print("track file must contain run_date and jobs[]", file=sys.stderr)
        return 2
    run_date = track["run_date"]

    seen = load_json(SEEN_JOBS, {"jobs": {}})
    if "jobs" not in seen or not isinstance(seen["jobs"], dict):
        print("seen_jobs.json malformed: missing top-level 'jobs' object", file=sys.stderr)
        return 2
    jobs = seen["jobs"]
    # Sanity: warn about any stray top-level keys (the 2026-06-30 bug class)
    strays = [k for k in seen if k not in ("jobs", "schema_version", "description")]
    if strays:
        print(f"WARNING: stray top-level keys in seen_jobs.json: {strays}", file=sys.stderr)

    added, touched = [], []
    for j in track["jobs"]:
        key = j["dedup_key"]
        if key in jobs:
            jobs[key]["last_seen_date"] = run_date
            touched.append(key)
        else:
            jobs[key] = {
                "company": j["company"],
                "title": j["title"],
                "url": j.get("url", ""),
                "first_seen_date": run_date,
                "last_seen_date": run_date,
                "score": j.get("score"),
                "applied": False,
                "outcome": None,
            }
            if j.get("notes"):
                jobs[key]["notes"] = j["notes"]
            added.append(key)

    reseen_touched = 0
    if args.touch_reseen:
        hits = load_json(args.touch_reseen, {})
        for key in hits.get("reseen_keys", []):
            if key in jobs:
                jobs[key]["last_seen_date"] = run_date
                reseen_touched += 1

    atomic_write_json(SEEN_JOBS, seen)

    # seen_urls.json
    urls = load_json(SEEN_URLS, [])
    known = {u.rstrip("/").lower() for u in urls}
    new_urls = 0
    for j in track["jobs"]:
        u = (j.get("url") or "").rstrip("/")
        if u and u.lower() not in known:
            urls.append(u)
            known.add(u.lower())
            new_urls += 1
    atomic_write_json(SEEN_URLS, urls[-500:])

    # outcomes.csv — a row for each NEW job, and a reopened row for each retailor
    header, rows = OUTCOMES_HEADER, []
    file_exists = os.path.exists(OUTCOMES)
    if file_exists:
        with open(OUTCOMES, newline="", encoding="utf-8") as f:
            raw = list(csv.reader(f))
        if raw:
            header, rows = raw[0], raw[1:]
    applied_urls = {norm_url(e.get("url")) for e in jobs.values()
                    if isinstance(e, dict) and e.get("applied") is True and isinstance(e.get("url"), str)}
    res = record_outcomes(track["jobs"], set(added), run_date, header, rows, applied_urls)
    if res["reopened"]:
        # The row as it stood goes to the archive first: a crash after this line
        # leaves a spare archive entry, never a rewritten row with no record.
        os.makedirs(os.path.dirname(REOPENED_ROWS), exist_ok=True)
        try:
            with open(REOPENED_ROWS, "rb") as f:
                f.seek(-1, os.SEEK_END)
                torn = f.read(1) != b"\n"   # an earlier crash left a line unfinished
        except OSError:                      # no archive yet, or an empty one
            torn = False
        with open(REOPENED_ROWS, "a", encoding="utf-8") as f:
            if torn:
                f.write("\n")
            for r in res["reopened"]:
                f.write(json.dumps({"reopened_on": run_date, "new_package": r["stem"],
                                    "row": dict(zip(header, r["old"]))}, ensure_ascii=False) + "\n")
        shutil.copy2(OUTCOMES, OUTCOMES + REOPEN_BACKUP)
        tmp = OUTCOMES + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)   # the appended rows are already at the end
        os.replace(tmp, OUTCOMES)
    else:
        with open(OUTCOMES, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if not file_exists:
                w.writerow(OUTCOMES_HEADER)
            w.writerows(res["appended"])

    print(f"seen_jobs: +{len(added)} new, {len(touched)} re-touched, "
          f"{reseen_touched} reseen-touched (total {len(jobs)})")
    print(f"seen_urls: +{new_urls} new")
    print(f"outcomes.csv: +{len(res['appended'])} rows"
          + (f", {res['already']} already recorded today" if res["already"] else ""))
    for k in added:
        print(f"  added: {k}")
    if res["reopened"]:
        print(f"outcomes.csv: {len(res['reopened'])} reopened for a new package "
              f"(backup at outcomes.csv{REOPEN_BACKUP})")
        for r in res["reopened"]:
            print(f"  {r['label']} [was {r['stage']}] -> {r['stem']}")
            if r["was_title"]:
                print(f"    the row's title was \"{r['was_title']}\"")
            if r["verdict"]:
                print(f"    his earlier verdict, {r['verdict']}, is cleared: it was on the earlier "
                      f"package. If that mark is still on the dashboard page, undo it there, or "
                      f"the next drain writes it back.")
            for stem in r["packages"]:
                print(f"    earlier package {stem}: its PDFs no longer match a row. Move any "
                      f"still in tailored/apply_now/ back to tailored/ by hand.")
    if res["refused"]:
        print(f"RETAILOR REFUSED (nothing written for these): {len(res['refused'])}")
        for label, why in res["refused"]:
            print(f"  {label}: {why}")
    if res["skipped"]:
        print(f"NO ROW WRITTEN (the tracker already knew the posting): {len(res['skipped'])}")
        for label, why in res["skipped"]:
            print(f"  {label}: {why}")
        print('  If one of these is a new package tailored today, set "retailor": '
              '"<its stem>" on that job and run this again.')
    return 1 if res["refused"] else 0


if __name__ == "__main__":
    sys.exit(main())
