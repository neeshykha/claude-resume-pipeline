#!/usr/bin/env python3
"""Records the marks Aneesh makes on the Shelf dashboard: Sent, Skip, Later.

Usage:
    .venv/bin/python pipeline/shelf_inbox.py              # report only, writes nothing
    .venv/bin/python pipeline/shelf_inbox.py --apply      # record them in the tracker
    .venv/bin/python pipeline/shelf_inbox.py --inbox FILE # read marks from a JSON file (tests)
    .venv/bin/python pipeline/shelf_inbox.py --strict     # exit 1 on failure (tests only)

Added 2026-10-12, on his go-ahead. Until then the dashboard was read-only and the
only two ways to tell the pipeline anything were a confirmation email or a typed
message. Nothing could say "I'm passing on this one", so the apply queue only
ever shrank by the 45-day retirement: 98 rows that day, `his_verdict` blank on
197 of 230 post-epoch rows, and a weekly send rate that had slid from about half
to 15%. On 2026-10-02 he asked whether he could add notes on the dashboard
itself. This is that.

HOW IT STAYS ONE SOURCE OF TRUTH
The 2026-09-19 decision against write-back from the page still holds in the way
that matters: `outcomes.csv` is the only record, and the page is not a second
one. The page keeps an INBOX of marks in the Shelf's per-page storage, under the
key `jobdash.inbox.v1`. This script reads that inbox and applies each mark
through the scripts that already own those columns:

    Sent   -> mark_applied.py (stage surfaced -> applied, by URL)
              and mark_verdict.py (sent_as_is, or sent_edited when he ticked it)
    Skip   -> mark_verdict.py (skip_fit / skip_time / skip_materials / skip_other)
    Later  -> nothing. A snooze is the page's business only.

It never writes the CSV itself and never touches a Shelf file. A recorded row
leaves the queue on the next dashboard build (build_dashboard.py drops rows with
a skip verdict), and the page forgets a mark once its row is gone. That is the
whole loop; there is no acknowledgement to write back.

RULES
- A mark is matched to its row by posting URL, exactly, normalized the way
  mark_applied.py does it. No URL, no row, or two rows sharing the URL: the mark
  is reported and nothing is written for it. It never guesses.
- Idempotent. A mark whose row already shows what it asks for is counted as
  already recorded, so re-running, or a failed run retrying tomorrow, is safe.
- A Skip mark on a row that has since been applied or closed is stale and is
  ignored: the tracker's stage is evidence, the mark is an opinion from earlier.
- A Sent or Skip mark dated before its row's surfaced_date is stale too (added
  2026-10-13). A click cannot come before the package it is about, except on a
  row update_tracking.py reopened for a new package: marks are stored under the
  posting URL, so one made on the old package would land on the new one.
- A Sent mark is HIS WORD, not a confirmation. The row's notes say so, so anything
  reasoning about confirmed sends can tell the two apart. When the confirmation
  email arrives later, Step 0.5 finds the row already applied and moves on.
- One backup of outcomes.csv is taken before the first write of the day's first
  drain (`outcomes.csv.bak-shelf-inbox-<weekday>`, so a week of them and no
  more), because mark_applied.py and mark_verdict.py each overwrite the plain
  `.bak` on every call. A second drain the same day leaves that backup alone:
  it holds the state before any of the day's marks were applied.
- The storage file is the page's, and the page is local, but nothing in a mark
  is trusted: one malformed mark is reported and the rest are still recorded.
- Like build_dashboard.py, a failure here must never fail the daily run: it prints
  one `shelf_inbox: FAILED ...` line and exits 0. The marks stay on the page and
  the next run tries again.

The Shelf has to be this machine's: the iPhone app is read-only and a mark made
there never reaches this file.

THE WEEKLY LEADS (added 2026-10-15, D41)
The same page carries the weekly report's leads, each with Tailor it and Pass, kept
under a second key, `jobdash.leads.v1`, keyed by LinkedIn job id. Those aren't
outcomes.csv rows, so they never go near mark_applied.py or mark_verdict.py:
drain_leads() hands them to lead_marks.py, which records them in jobs/lead_marks.json.
It runs first, reports as one `leads:` clause on the same line, and a failure there
never stops the queue marks.

This file is committed to a public repo. No company names, no sample rows.
"""
import contextlib
import csv
import io
import json
import os
import re
import shutil
import sys
from datetime import date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTCOMES = os.path.join(SCRIPT_DIR, "outcomes.csv")
SEEN_JOBS = os.path.join(SCRIPT_DIR, "jobs", "seen_jobs.json")
JOBS_DIR = os.path.join(SCRIPT_DIR, "jobs")
SHELF_DIR = os.path.expanduser("~/Library/Application Support/HTMLShelf")
PAGE_FILE = "job_dashboard.html"   # the page's originalName in the Shelf library
INBOX_KEY = "jobdash.inbox.v1"     # must match build_dashboard.py's page script
LEADS_KEY = "jobdash.leads.v1"     # the weekly leads' Tailor it / Pass; same page, same rule
BACKUP_SUFFIX = ".bak-shelf-inbox"   # + "-mon" .. "-sun"; pipeline/*.bak* is gitignored

SKIP_VERDICTS = {"fit": "skip_fit", "time": "skip_time",
                 "materials": "skip_materials", "other": "skip_other"}
SENT_STAGES = {"applied", "rejected", "closed", "interview", "assessment"}


def norm_url(u):
    return (u or "").strip().rstrip("/").lower()


def parse_date(s):
    try:
        return date(*map(int, str(s or "").strip()[:10].split("-")))
    except Exception:
        return None


def find_storage_file():
    """Path of the Shelf's storage file for the dashboard page, or (None, why)."""
    lib_path = os.path.join(SHELF_DIR, "library.json")
    try:
        with open(lib_path, encoding="utf-8") as f:
            lib = json.load(f)
    except FileNotFoundError:
        return None, "no Shelf library on this machine"
    docs = lib.get("documents") if isinstance(lib, dict) else lib
    hits = [d for d in docs or [] if isinstance(d, dict)
            and (d.get("originalName") == PAGE_FILE
                 or str(d.get("trackedSource") or "").endswith("/" + PAGE_FILE))]
    if len(hits) > 1:
        # A duplicate import would split the marks across two pages. Prefer the one
        # the Shelf is refreshing from Downloads; refuse to pick between equals.
        tracked = [d for d in hits if str(d.get("trackedSource") or "").endswith("/" + PAGE_FILE)]
        hits = tracked if len(tracked) == 1 else hits
    if len(hits) != 1:
        return None, f"{len(hits)} Shelf pages named {PAGE_FILE}; expected one"
    return os.path.join(SHELF_DIR, "Data", f"{hits[0].get('id')}.json"), ""


def load_marks(inbox_path=None, key=INBOX_KEY):
    """{row key: mark dict}. The Shelf stores each localStorage value as a string."""
    if inbox_path is None:
        inbox_path, why = find_storage_file()
        if inbox_path is None:
            return {}, why
    try:
        with open(inbox_path, encoding="utf-8") as f:
            store = json.load(f)
    except FileNotFoundError:
        return {}, "the page has no stored data yet"
    raw = store.get(key) if isinstance(store, dict) else None
    if isinstance(raw, str):
        raw = json.loads(raw or "{}")
    if raw is None:
        return {}, "no marks on the page"
    if not isinstance(raw, dict):
        raise ValueError(f"{key} is not an object")
    return {k: v for k, v in raw.items() if isinstance(v, dict)}, ""


def drain_leads(inbox_path, today, apply):
    """Record the weekly leads' Tailor it / Pass marks (added 2026-10-15, D41).

    Returns one clause for the `shelf_inbox:` line, or "" when there were none. Never
    raises: a failure here is reported and must not stop the apply-queue marks.
    lead_marks.py owns jobs/lead_marks.json; this only hands it the page's marks.
    """
    try:
        marks, _ = load_marks(inbox_path, LEADS_KEY)
        if not marks:
            return ""
        import lead_marks
        p, n_tailor, n_pass = lead_marks.record(marks, today, apply=apply)
        for item in p["bad"]:
            print(f"  lead not recorded: {item}")
        extra = (f", {len(p['already'])} already recorded" if p["already"] else "") + (
            f", {len(p['bad'])} not recorded" if p["bad"] else "")
        if not p["new"]:
            return f"leads: nothing new{extra}"
        return (f"leads: {'recorded' if apply else 'would record'} {n_tailor} to tailor, "
                f"{n_pass} passed{extra}")
    except Exception as e:  # noqa: BLE001
        return f"leads: FAILED {type(e).__name__}: {e}"


def read_rows():
    with open(OUTCOMES, newline="", encoding="utf-8") as f:
        raw = list(csv.reader(f))
    header = raw[0]
    need = ("company", "title", "url", "stage", "his_verdict", "surfaced_date")
    missing = [n for n in need if n not in header]
    if missing:
        raise ValueError(f"outcomes.csv is missing columns {missing}; run repair_outcomes.py --apply")
    ci = {n: header.index(n) for n in need}
    by_url = {}
    for r in raw[1:]:
        if len(r) != len(header):
            continue  # mark_applied.py and mark_verdict.py skip drifted rows too
        by_url.setdefault(norm_url(r[ci["url"]]), []).append(
            {n: r[i].strip() for n, i in ci.items()})
    return by_url


def plan(marks, by_url, today):
    """Sort every mark into what to do with it. Pure: reads nothing, writes nothing."""
    out = {"promote": [], "verdict": [], "already": [], "stale": [], "later": [],
           "unmatched": [], "ambiguous": [], "unknown": []}
    for key, m in sorted(marks.items()):
        try:
            _plan_one(out, str(key), m, by_url, today)
        except Exception as e:  # noqa: BLE001 - one bad mark must not block the others
            out["unknown"].append(f"{str(key)[:80]} ({type(e).__name__}: {e})")
    return out


def _text(v):
    return v if isinstance(v, str) else ""


def _plan_one(out, key, m, by_url, today):
    action = _text(m.get("a"))
    label = f"{_text(m.get('c')) or '?'}: {_text(m.get('t')) or '?'}"[:160]
    if action == "later":
        out["later"].append(label)
        return
    if action not in ("sent", "skip"):
        out["unknown"].append(f"{label} (action {action[:20]!r})")
        return
    url = norm_url(_text(m.get("u")) or (key if key.startswith("http") else ""))
    rows = by_url.get(url, []) if url else []
    if not rows:
        out["unmatched"].append(label)
        return
    if len(rows) > 1:
        out["ambiguous"].append(label)
        return
    row = rows[0]
    label = f"{row['company']}: {row['title']}"
    marked, surfaced = parse_date(m.get("d")), parse_date(row["surfaced_date"])
    if marked and surfaced and marked < surfaced:
        out["stale"].append(f"{label} (marked {action} {marked.isoformat()}, before this row's "
                            f"package was surfaced {surfaced.isoformat()})")
        return
    when = marked or today
    if when > today:
        when = today  # a clock set wrong on the page must not date a send in the future
    if action == "sent":
        verdict = "sent_edited" if m.get("e") else "sent_as_is"
        did = False
        if row["stage"] == "surfaced":
            out["promote"].append({"url": url, "company": row["company"], "title": row["title"],
                                   "applied_date": when.isoformat(), "label": label})
            did = True
        elif row["stage"] not in SENT_STAGES:
            out["stale"].append(f"{label} (marked sent, row is {row['stage'] or 'blank'})")
            return
        # A sent verdict already there stands (as-is versus edited was his call then).
        # A blank is filled. A skip is replaced: he passed on it earlier and sent it
        # after all, and "applied, verdict skip" would be a row that contradicts itself.
        if not row["his_verdict"].startswith("sent_"):
            # Only a promotion made here is on his word alone; a row the
            # confirmation email already promoted keeps its clean provenance.
            note = (f"marked sent on the Shelf {when.isoformat()}, no confirmation email yet"
                    if did else "")
            out["verdict"].append({"url": url, "company": row["company"], "verdict": verdict,
                                   "note": note, "label": label})
            did = True
        if not did:
            out["already"].append(label)
    else:
        verdict = SKIP_VERDICTS.get(_text(m.get("r")), "skip_other")
        if row["stage"] != "surfaced":
            out["stale"].append(f"{label} (marked skip, row is {row['stage'] or 'blank'})")
        elif row["his_verdict"].startswith("skip_"):
            out["already"].append(label)
        else:
            # Blank, or a sent verdict on a row that never got promoted (a drain that
            # died halfway, then he changed the mark). The newer mark is the answer.
            # `bulk` is the page's one-click clear of old rows: always skip_other, and the
            # note says so, because it is a tidy-up and not a judgment on the role.
            bulk = m.get("bulk") is True
            out["verdict"].append({"url": url, "company": row["company"],
                                   "verdict": "skip_other" if bulk else verdict,
                                   "note": f"skipped on the Shelf {when.isoformat()}"
                                           + (", cleared in bulk" if bulk else ""),
                                   "label": label})


def apply_plan(p, today):
    """Run the owning scripts. Returns (rows promoted, verdicts written, problems).

    Verdicts go first, promotions second, on purpose. A Sent mark is two writes, and
    the verdict is the one that carries the "his word, no confirmation email yet"
    note. If the run dies between the two, a verdict-then-promote order leaves a
    surfaced row with a sent verdict, which the next drain finishes cleanly; the
    other order would leave an applied row whose note is never written.
    One refused or crashed write is reported and the rest still run.
    """
    import mark_applied
    import mark_verdict

    problems = []
    backup = f"{OUTCOMES}{BACKUP_SUFFIX}-{today.strftime('%a').lower()}"
    try:
        fresh = date.fromtimestamp(os.path.getmtime(backup)) == today
    except OSError:
        fresh = False
    if not fresh:  # today's first drain: keep the state from before any of today's marks
        shutil.copy2(OUTCOMES, backup)

    written = 0
    for v in p["verdict"]:
        argv = [v["company"], v["verdict"], "--url", v["url"]]
        if v["note"]:
            argv += ["--note", v["note"]]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = mark_verdict.main(argv, path=OUTCOMES)
        except SystemExit as e:  # argparse, or a tracker with no his_verdict column
            rc = e.code if isinstance(e.code, int) else 1
        except Exception as e:  # noqa: BLE001
            rc = 1
            buf.write(f"{type(e).__name__}: {e}")
        if rc == 0:
            written += 1
        else:
            problems.append(f"mark_verdict.py refused {v['label']}: " + buf.getvalue().strip()[:200])

    promoted = 0
    if p["promote"]:
        os.makedirs(JOBS_DIR, exist_ok=True)
        conf = os.path.join(JOBS_DIR, f"confirmations_{today.isoformat()}_shelf.json")
        with open(conf, "w", encoding="utf-8") as f:
            json.dump({"source": "shelf_inbox.py: marked sent on the dashboard, not a confirmation email",
                       "confirmations": [{k: c[k] for k in ("url", "company", "title", "applied_date")}
                                         for c in p["promote"]]}, f, indent=2)
        mark_applied.OUTCOMES, mark_applied.SEEN_JOBS = OUTCOMES, SEEN_JOBS
        buf, argv, rc = io.StringIO(), sys.argv, 1
        sys.argv = ["mark_applied.py", conf]
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = mark_applied.main()
        except Exception as e:  # noqa: BLE001
            buf.write(f"{type(e).__name__}: {e}")
        finally:
            sys.argv = argv
        text = buf.getvalue()
        m = re.search(r"(\d+) promoted to stage=applied", text)
        promoted = int(m.group(1)) if m else 0
        if rc != 0 or promoted != len(p["promote"]):
            problems.append(f"mark_applied.py promoted {promoted} of {len(p['promote'])}: "
                            + " | ".join(text.strip().splitlines()[-4:]))
    return promoted, written, problems


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    strict = "--strict" in argv
    try:
        today = parse_date(argv[argv.index("--today") + 1]) if "--today" in argv else date.today()
        if today is None:
            raise ValueError("--today needs YYYY-MM-DD")
        inbox = argv[argv.index("--inbox") + 1] if "--inbox" in argv else None
        lead_note = drain_leads(inbox, today, "--apply" in argv)
        sfx = f"; {lead_note}" if lead_note else ""
        lead_failed = lead_note.startswith("leads: FAILED")
        marks, why = load_marks(inbox)
        if not marks:
            print(f"shelf_inbox: nothing to record ({why or 'no marks on the page'}){sfx}")
            return 1 if (strict and lead_failed) else 0
        p = plan(marks, read_rows(), today)
        n_sent, n_verdict = len(p["promote"]), len(p["verdict"])
        skips = sum(1 for v in p["verdict"] if v["verdict"].startswith("skip_"))
        tail = (f"{len(p['already'])} already recorded, {len(p['later'])} snoozed (page only), "
                f"{len(p['stale'])} stale, {len(p['unmatched']) + len(p['ambiguous']) + len(p['unknown'])} not matched")
        for name in ("stale", "unmatched", "ambiguous", "unknown"):
            for item in p[name]:
                print(f"  {name}: {item}")
        if "--apply" not in argv:
            print(f"shelf_inbox: would record {n_sent} sent, {skips} skipped, "
                  f"{n_verdict - skips} sent verdicts; {tail}{sfx} (report only; --apply records them)")
            for c in p["promote"]:
                print(f"  sent: {c['label']} ({c['applied_date']})")
            for v in p["verdict"]:
                print(f"  {v['verdict']}: {v['label']}")
            return 1 if (strict and lead_failed) else 0
        if not (n_sent or n_verdict):
            print(f"shelf_inbox: nothing new to record; {tail}{sfx}")
            return 1 if (strict and lead_failed) else 0
        promoted, written, problems = apply_plan(p, today)
        log = os.path.join(JOBS_DIR, f"shelf_inbox_{today.isoformat()}.json")
        with open(log, "w", encoding="utf-8") as f:
            json.dump({"date": today.isoformat(), "promoted": promoted, "verdicts_written": written,
                       "plan": p, "problems": problems}, f, indent=2)
        for item in problems:
            print(f"  problem: {item}")
        print(f"shelf_inbox: recorded {promoted} sent, {written} verdicts ({skips} skips); {tail}"
              + (f"; {len(problems)} PROBLEMS, see above" if problems else "") + sfx)
        return 1 if (strict and (problems or lead_failed)) else 0
    except Exception as e:  # noqa: BLE001 - an inbox failure must never fail the run
        print(f"shelf_inbox: FAILED {type(e).__name__}: {e}")
        return 1 if strict else 0


if __name__ == "__main__":
    sys.exit(main())
