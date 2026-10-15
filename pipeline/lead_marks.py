#!/usr/bin/env python3
"""What Aneesh did with the weekly leads: Tailor it or Pass, one LinkedIn role at a time.

    .venv/bin/python pipeline/lead_marks.py            # list what's recorded and what's waiting

Added 2026-10-15, when the weekly channel report stopped being an email (D41). Its three
lists (strong roles the poller can't reach, roles at watched companies that never got
picked, and companies with no board where a good role turned up) now sit on the Shelf
dashboard as "This week's leads", each row with two buttons. The page keeps his clicks in
the Shelf's storage under `jobdash.leads.v1`, an inbox like the apply queue's
`jobdash.inbox.v1`. shelf_inbox.py drains it at daily_task_prompt.md Step 0 item 4b and
calls record() here. This module owns the one file that remembers the answers:

    jobs/lead_marks.json (gitignored, like every run-state file)
    {"leads": {"<LinkedIn job id>": {
        "action": "tailor" | "pass",
        "marked": "YYYY-MM-DD",      # the day he clicked
        "recorded": "YYYY-MM-DD",    # the day a run drained it
        "list": "unreachable" | "never_picked" | "no_board",
        "company", "title", "url", "tier", "loc",
        "fetched": "YYYY-MM-DD",     # tailor only, once linkedin_followup.py --requested read it
        "fetch_status": "ok" | "thin" | "closed" | "on-site elsewhere" | "error: ...",
        "tries", "last_error"}}}     # a read that failed in a way that may pass (note_retry)

RULES
- Keyed by the LinkedIn job id, digits only. A mark under any other key is reported and
  not recorded: nothing downstream could find its posting.
- The first recorded answer is final. Once a lead is recorded the dashboard drops it, so a
  second answer can only be a stale mark from before the drain. It is counted as already
  recorded and changes nothing.
- A tailor request waits here until linkedin_followup.py --requested reads its posting,
  oldest click first, a few a run. A read that LinkedIn throttled is not stamped, so the
  request rolls to the next run instead of vanishing. Neither is a timeout or a server
  error, until the third one (note_retry).
- Every write goes through a temp file and os.replace, and a malformed file is never
  overwritten: load() raises, and the caller reports it.

This file is committed to a public repo. No company names, no sample rows.
"""
import json
import os
import re
import sys
from datetime import date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.path.join(SCRIPT_DIR, "jobs")
PATH = os.path.join(JOBS_DIR, "lead_marks.json")

ACTIONS = ("tailor", "pass")
LISTS = ("unreachable", "never_picked", "no_board")
JOB_ID_RE = re.compile(r"^\d{6,12}$")
CARRIED = ("company", "title", "url", "list", "tier", "loc")


def load(path=None):
    """{job id: entry}. A missing file is empty; a malformed one raises."""
    path = path or PATH
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError:
        return {}
    leads = doc.get("leads") if isinstance(doc, dict) else None
    if not isinstance(leads, dict):
        raise ValueError(f"{os.path.basename(path)} has no `leads` object")
    return {k: v for k, v in leads.items() if isinstance(v, dict)}


def save(leads, path=None):
    path = path or PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"leads": leads}, f, indent=1, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def _text(v, n=200):
    return v.strip()[:n] if isinstance(v, str) else ""


def plan(marks, leads):
    """Sort page marks into new / already / bad. Pure: reads nothing, writes nothing."""
    out = {"new": [], "already": [], "bad": []}
    for key, m in sorted(marks.items()):
        key = str(key)
        if not isinstance(m, dict):
            out["bad"].append(f"{key[:40]} (not an object)")
            continue
        action = m.get("a")
        if not JOB_ID_RE.match(key):
            out["bad"].append(f"{key[:40]} (not a LinkedIn job id)")
        elif action not in ACTIONS:
            out["bad"].append(f"{key} (unknown action {str(action)[:20]!r})")
        elif key in leads:
            out["already"].append(key)
        else:
            out["new"].append((key, m))
    return out


def record(marks, today, path=None, apply=True):
    """Record new marks. Returns (plan, n tailor, n pass). Writes only when apply is set."""
    leads = load(path)
    p = plan(marks, leads)
    if not p["new"]:
        return p, 0, 0
    for key, m in p["new"]:
        entry = {"action": m["a"], "recorded": today.isoformat(),
                 "marked": _text(m.get("d"), 10) or today.isoformat()}
        for short, field in (("c", "company"), ("t", "title"), ("u", "url"), ("l", "list"),
                             ("tier", "tier"), ("loc", "loc")):
            val = _text(m.get(short))
            if val:
                entry[field] = val
        if entry.get("list") not in LISTS:
            entry.pop("list", None)
        leads[key] = entry
    if apply:
        save(leads, path)
    n_tailor = sum(1 for _, m in p["new"] if m["a"] == "tailor")
    return p, n_tailor, len(p["new"]) - n_tailor


def pending_requests(limit, path=None):
    """Tailor requests whose posting hasn't been read yet, oldest click first."""
    leads = load(path)
    waiting = [dict(v, job_id=k) for k, v in leads.items()
               if v.get("action") == "tailor" and not v.get("fetched")]
    waiting.sort(key=lambda e: (e.get("marked") or "", e.get("recorded") or "", e["job_id"]))
    return waiting[:max(limit, 0)], len(waiting)


def stamp(results, today, path=None):
    """Mark tailor requests as read: {job id: fetch_status}. Unknown ids are ignored."""
    if not results:
        return 0
    leads = load(path)
    n = 0
    for jid, status in results.items():
        e = leads.get(str(jid))
        if e is None or e.get("action") != "tailor" or e.get("fetched"):
            continue
        e["fetched"] = today.isoformat()
        e["fetch_status"] = _text(status, 120) or "ok"
        n += 1
    if n:
        save(leads, path)
    return n


RETRY_LIMIT = 3


def note_retry(errors, today, path=None, limit=RETRY_LIMIT):
    """A read that failed for a reason that may pass (timeout, 5xx): {job id: error}.

    Counts the try on the request and leaves it waiting, so a network blip doesn't use up
    his click. On the `limit`th failure it is stamped like any other error, so one broken
    posting can't hold a slot forever. Returns the ids that gave up.
    """
    if not errors:
        return []
    leads = load(path)
    gave_up = []
    for jid, err in errors.items():
        e = leads.get(str(jid))
        if e is None or e.get("action") != "tailor" or e.get("fetched"):
            continue
        e["tries"] = int(e.get("tries") or 0) + 1
        e["last_error"] = _text(err, 120)
        if e["tries"] >= limit:
            e["fetched"] = today.isoformat()
            e["fetch_status"] = f"error: {_text(err, 100)} ({e['tries']} tries)"
            gave_up.append(str(jid))
    save(leads, path)
    return gave_up


def recorded_ids(path=None):
    """Job ids with any recorded answer. The dashboard hides these. Never raises."""
    try:
        return set(load(path))
    except Exception:  # noqa: BLE001 - a bad file hides nothing rather than breaking the page
        return set()


def main():
    try:
        leads = load()
    except Exception as e:  # noqa: BLE001
        print(f"lead_marks: cannot read {PATH}: {type(e).__name__}: {e}")
        return 1
    waiting, n_waiting = pending_requests(10 ** 6)
    by = {}
    for v in leads.values():
        k = (v.get("action"), v.get("list") or "?")
        by[k] = by.get(k, 0) + 1
    print(f"lead_marks: {len(leads)} recorded, {n_waiting} tailor request(s) waiting for a read")
    for (action, lst), n in sorted(by.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        print(f"  {action:<7} {lst:<13} {n}")
    for e in waiting:
        print(f"  waiting: {e.get('company', '?')}: {e.get('title', '?')} | {e['job_id']} "
              f"(asked {e.get('marked', '?')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
