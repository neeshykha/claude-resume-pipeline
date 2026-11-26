#!/usr/bin/env python3
"""The roles Aneesh asked for from "Cleared, not tailored": Tailor it, one posting at a time.

    .venv/bin/python pipeline/cleared_requests.py                  # what's recorded, what's waiting
    .venv/bin/python pipeline/cleared_requests.py --read           # Step 1d-4: read the waiting ones
    .venv/bin/python pipeline/cleared_requests.py --read --dry-run # select and print, fetch nothing

Added 2026-11-26 (D63). On 2026-11-12 he chose to have packages written after he picks a
role (D54), and the dashboard never got a way to pick: asking by name in a session was the
only path. Each row of the dashboard's "Cleared, not tailored" section now has a Tailor it
button. The page keeps his clicks in the Shelf's storage under `jobdash.cleared.v1`, keyed
by posting URL, an inbox like the weekly leads' `jobdash.leads.v1`. shelf_inbox.py drains it
at daily_task_prompt.md Step 0 item 4b and calls record() here. This module owns the one
file that remembers the requests:

    jobs/cleared_requests.json (gitignored, like every run-state file)
    {"requests": {"<normalized posting url>": {
        "action": "tailor",
        "marked": "YYYY-MM-DD",       # the day he clicked
        "recorded": "YYYY-MM-DD",     # the day a run drained it
        "company", "title", "url",    # url as the page had it; the key is normalized
        "score", "gap",               # what the row showed when he clicked
        "read": "YYYY-MM-DD",         # once --read handled it
        "read_status": "live" | "cached" | "closed" | "unreadable" | "already in the tracker (...)",
        "read_note"}}}

HOW A REQUEST GETS ITS JOB DESCRIPTION
The weekly leads go through LinkedIn's guest endpoint (linkedin_followup.py --requested)
because a lead is a LinkedIn card and nothing else. A cleared role is different: the
daily run already read its posting at the source ATS and a screen worker already carded
it. So --read re-reads the posting from its own URL with fetch_jd.fetch(), the reader
jd_prefetch.py uses (a LinkedIn posting URL goes through the guest endpoint instead), and
reuses the card read beside the newest cached copy when the body hasn't changed (the
header lines differ between readers, so only the body is compared; see body_key()). Why
read again rather than take the cached copy:
  * A row stays on the page for seven days and he may click on the last one. The live
    read is the only thing that says the posting is still open, and a package for a
    closed posting is a writer spent on nothing.
  * The writer drafts from today's text, not last week's.
  * It costs one request a role, and when the text hasn't changed no worker is spent.
When the live read fails for any reason but a closed posting, the newest cached copy
from jobs/jd_cache/ (and the card read beside it) stands in, and the request says so
(`cached`), so the run can tell him the posting wasn't confirmed open.

Out: jobs/jd_cache/<date>_cleared/ in the Step 2-JD shape (txt files, manifest.json,
cards_batch_cached.json for reused cards, batch_01.json for a worker when any text is
new), so jd_screen_table.py --date <date>_cleared reads it unchanged.

RULES
- Keyed by the normalized posting URL (strip, drop a trailing slash, lowercase), the same
  key shelf_inbox.py and build_dashboard.py use for the queue. Only an http(s) URL and the
  action "tailor" are recorded; anything else is reported and left.
- The first recorded answer is final, as with the weekly leads: once a request is recorded
  the page shows it as asked and takes no second click.
- Oldest click first, CLEARED_MAX a run. A request is stamped `read` once --read has
  handled it, whatever came back, and leaves the waiting list. One the run didn't reach
  rolls to the next run.
- A URL already in outcomes.csv is stamped and not read: it was tailored or sent another way.
- Every write goes through a temp file and os.replace, and a malformed file is never
  overwritten: load() raises, and the caller reports it.
- Tier: full whatever the score (priority at company_cap_threshold), never light. Clicking
  Tailor it is asking for the role by name, and a role he asks for by name gets a full
  package (CLAUDE.md Step 1). See tier_for().

This file is committed to a public repo. No company names, no sample rows.
"""
import argparse
import csv
import glob
import json
import os
import re
import shutil
import sys
from datetime import date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
JOBS_DIR = os.path.join(SCRIPT_DIR, "jobs")
PATH = os.path.join(JOBS_DIR, "cleared_requests.json")
OUTCOMES = os.path.join(SCRIPT_DIR, "outcomes.csv")
WATCHLIST = os.path.join(SCRIPT_DIR, "watchlist_companies.json")

ACTIONS = ("tailor",)
CLEARED_MAX = 5          # read and tailored per run, apart from the weekly leads' three (his call, D63)
LOOKBACK_DAYS = 21       # how far back a cached copy may come from
THIN = 400               # a live page shorter than this is treated like a failed read
MAX_BODY = 20000
RULE = "-" * 70          # the Step 2-JD header/body divider; jd_prefetch.RULE
REUSED_CARDS = "cards_batch_cached.json"   # jd_prefetch.REUSED_CARDS; jd_screen_table.py reads it first
LINKEDIN_RE = re.compile(r"linkedin\.com/jobs/view/(\d{6,12})", re.I)
# A failed read that means the posting itself is gone, not that the read went wrong.
CLOSED_RE = re.compile(r"\b(404|410)\b|not on board|may have closed|no longer accepting|"
                       r"no description block", re.I)
DAY_DIR = re.compile(r"(\d{4}-\d{2}-\d{2})(?:_[a-z]+)?")
CARRIED = (("c", "company", 160), ("t", "title", 240), ("u", "url", 600), ("g", "gap", 400))


def norm_url(u):
    # Same normalization as shelf_inbox.py and build_dashboard.py. Change all three together.
    return (u or "").strip().rstrip("/").lower()


def _text(v, n=200):
    return v.strip()[:n] if isinstance(v, str) else ""


def load(path=None):
    """{normalized url: entry}. A missing file is empty; a malformed one raises."""
    path = path or PATH
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError:
        return {}
    reqs = doc.get("requests") if isinstance(doc, dict) else None
    if not isinstance(reqs, dict):
        raise ValueError(f"{os.path.basename(path)} has no `requests` object")
    return {k: v for k, v in reqs.items() if isinstance(v, dict)}


def save(reqs, path=None):
    path = path or PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"requests": reqs}, f, indent=1, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def recorded_keys(path=None):
    """Normalized URLs with a recorded request. Never raises: a bad file hides nothing."""
    try:
        return set(load(path))
    except Exception:  # noqa: BLE001
        return set()


def plan(marks, reqs):
    """Sort page marks into new / already / bad. Pure: reads nothing, writes nothing."""
    out = {"new": [], "already": [], "bad": []}
    for key, m in sorted(marks.items(), key=lambda kv: str(kv[0])):
        key = str(key)
        if not isinstance(m, dict):
            out["bad"].append(f"{key[:80]} (not an object)")
            continue
        url = _text(m.get("u"), 600) or key
        k = norm_url(url)
        if not re.match(r"^https?://", k):
            out["bad"].append(f"{key[:80]} (not a posting URL)")
        elif m.get("a") not in ACTIONS:
            out["bad"].append(f"{key[:80]} (unknown action {str(m.get('a'))[:20]!r})")
        elif k in reqs:
            out["already"].append(k)
        else:
            out["new"].append((k, url, m))
    return out


def record(marks, today, path=None, apply=True):
    """Record new requests. Returns (plan, n new). Writes only when apply is set."""
    reqs = load(path)
    p = plan(marks, reqs)
    seen = set()
    for k, url, m in p["new"]:
        if k in seen:   # two page keys for one posting (case, a trailing slash): one request
            continue
        seen.add(k)
        entry = {"action": m["a"], "recorded": today.isoformat(),
                 "marked": _text(m.get("d"), 10) or today.isoformat(), "url": url}
        for short, field, n in CARRIED:
            val = _text(m.get(short), n)
            if val and field != "url":
                entry[field] = val
        score = m.get("s")
        if isinstance(score, (int, float)) and not isinstance(score, bool) and 0 <= score < 1000:
            entry["score"] = round(score)
        reqs[k] = entry
    if apply and seen:
        save(reqs, path)
    return p, len(seen)


def pending(limit, path=None):
    """Requests not read yet, oldest click first: ([entry + key], how many wait)."""
    reqs = load(path)
    waiting = [dict(v, key=k) for k, v in reqs.items()
               if v.get("action") == "tailor" and not v.get("read")]
    waiting.sort(key=lambda e: (e.get("marked") or "", e.get("recorded") or "", e["key"]))
    return waiting[:max(limit, 0)], len(waiting)


def stamp(results, today, path=None):
    """Mark requests as read: {key: (status, note)}. Unknown or already-read keys are ignored."""
    if not results:
        return 0
    reqs = load(path)
    n = 0
    for k, (status, note) in results.items():
        e = reqs.get(k)
        if e is None or e.get("read"):
            continue
        e["read"] = today.isoformat()
        e["read_status"] = _text(status, 120)
        if note:
            e["read_note"] = _text(note, 300)
        n += 1
    if n:
        save(reqs, path)
    return n


def tier_for(score, cfg):
    """The package tier for a cleared request: priority at the cap threshold, else full.

    Never light, and neither the hard-requirement cap nor the IC-comp rule lowers it. He
    picked this role from the list with its gap showing, which is asking for it by name,
    and a role he names gets a full package (CLAUDE.md Step 1). The cap stays recorded in
    `hard_req_cap_trigger` like any row's; it just doesn't choose the tier here. D63.
    """
    cap = (cfg or {}).get("company_cap_threshold", 110)
    return "priority" if isinstance(score, (int, float)) and score >= cap else "full"


def tracked_stages():
    """{normalized url: stage} from outcomes.csv. A missing tracker knows nothing."""
    try:
        with open(OUTCOMES, newline="", encoding="utf-8") as f:
            return {norm_url(r.get("url")): (r.get("stage") or "").strip() for r in csv.DictReader(f)}
    except OSError:
        return {}


def scoring_config():
    try:
        with open(WATCHLIST, encoding="utf-8") as f:
            return json.load(f).get("_scoring_config") or {}
    except Exception:  # noqa: BLE001 - the default thresholds are what the config holds
        return {}


def cached_copy(url, today, cache_root=None, lookback=LOOKBACK_DAYS):
    """(txt path, day, card or None) for the newest cached read of this posting, or None.

    Walks jobs/jd_cache/<date>[_suffix]/manifest.json newest first, any run's dir (the main
    run, the LinkedIn follow-up, an earlier request) within `lookback` days before today,
    today's own dir excluded. The card is the one a worker wrote, or reused, for that
    same file in that same dir.
    """
    cache_root = cache_root or os.path.join(JOBS_DIR, "jd_cache")
    key = norm_url(url)
    try:
        names = os.listdir(cache_root)
    except OSError:
        return None
    dated = []
    for name in names:
        m = DAY_DIR.fullmatch(name)
        try:
            day = date.fromisoformat(m.group(1)) if m else None
        except ValueError:
            day = None
        if day and 0 < (today - day).days <= lookback:
            dated.append((day, name))
    for day, name in sorted(dated, reverse=True):
        d = os.path.join(cache_root, name)
        try:
            with open(os.path.join(d, "manifest.json"), encoding="utf-8") as f:
                entries = json.load(f).get("entries") or []
        except (OSError, ValueError, AttributeError):
            continue
        for e in entries:
            if not isinstance(e, dict) or norm_url(e.get("url")) != key or not isinstance(e.get("file"), str):
                continue
            txt = os.path.join(d, os.path.basename(e["file"]))
            if not os.path.isfile(txt):
                continue
            return txt, day, _card_beside(d, txt)
    return None


def _card_beside(d, txt):
    base = os.path.basename(txt)
    found = None
    for p in sorted(glob.glob(os.path.join(d, "cards_batch_*.json")),
                    key=lambda p: (not p.endswith("cards_batch_cached.json"), p)):
        try:
            with open(p, encoding="utf-8") as f:
                cards = json.load(f)
        except (OSError, ValueError):
            continue
        for c in cards if isinstance(cards, list) else []:
            if isinstance(c, dict) and isinstance(c.get("file"), str) \
                    and os.path.basename(c["file"]) == base and c.get("read_ok", True) is not False:
                found = c   # later files win, as in jd_screen_table.py
    return found


def _slug(s, n):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:n]


def _write_txt(path, req, rec, note):
    body = rec.get("body") or ""
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"COMPANY : {req.get('company') or '?'}\n")
        f.write(f"TITLE   : {rec.get('title') or req.get('title') or '?'}\n")
        f.write(f"URL     : {req['url']}\n")
        f.write(f"ATS     : {rec.get('ats')}\n")
        f.write(f"LOCATION: {rec.get('location')}   remote={rec.get('remote')}\n")
        f.write(f"POSTED  : {rec.get('posted')}\n")
        f.write(f"SALARY  : {rec.get('salary')}\n")
        f.write(f"NOTE    : {note}\n")
        f.write(RULE + "\n")
        f.write(body[:MAX_BODY])
        if len(body) > MAX_BODY:
            f.write(f"\n[truncated at {MAX_BODY} of {len(body)} chars]\n")


def live_read(url, session=None):
    """One read of the posting at its own URL: the fetch_jd record, or {"error": ...}."""
    m = LINKEDIN_RE.search(url or "")
    if m:
        import linkedin_followup
        import requests
        rec = linkedin_followup.fetch(session or requests.Session(), m.group(1))
        if rec.get("throttled"):
            rec = {"error": "LinkedIn returned 429"}
        if rec.get("body"):
            rec.setdefault("ats", "linkedin-guest")
        return rec
    import fetch_jd
    return fetch_jd.fetch(url)


NOTE_LINE = re.compile(r"^\[(truncated at|cached copy read) ")


def body_key(text):
    """A cached txt's body, or a live body, reduced to what a worker reads: whitespace
    collapsed, the header and this module's trailing notes left out. Two reads of a posting
    whose text didn't change give the same key."""
    head, sep, body = text.partition("\n" + RULE + "\n")
    if not sep:
        body = text
    lines = body.rstrip().splitlines()
    while lines and NOTE_LINE.match(lines[-1].strip()):
        lines.pop()
    return " ".join("\n".join(lines).split())


def _reuse(card, path, day):
    out = dict(card)
    out["file"] = path
    out["reused_from"] = card.get("reused_from") or day.isoformat()
    return out


def read_one(req, today, cache, read=live_read):
    """Read one request into `cache`. Returns (manifest entry, card to reuse or None, stamp).

    The card read beside the newest cached copy is reused when the live body matches that
    copy's body; a changed body goes to a worker. A failed live read falls back to the
    cached copy and its card. A closed posting is stamped and nothing is written.
    """
    path = os.path.join(cache, f"{req['n']:02d}_{_slug(req.get('company'), 20)}_{_slug(req.get('title'), 40)}.txt")
    e = {"source": "cleared_request", "company": req.get("company") or "?",
         "title": req.get("title") or "?", "url": req["url"], "pre_score": req.get("score"),
         "score": req.get("score"), "gap": req.get("gap", ""), "asked": req.get("marked"),
         "jd_verification_required": False}
    hit = cached_copy(req["url"], today)
    rec = read(req["url"])
    err = rec.get("error") or ""
    body = rec.get("body") or ""
    if rec.get("closed") or (err and CLOSED_RE.search(err)):
        e["status"] = "skipped: posting closed"
        return e, None, ("closed", err[:200] or "the posting says it's no longer accepting applications")
    if not err and len(body) >= THIN:
        e.update(status="ok", file=path, chars=len(body), ats=rec.get("ats"), read_status="live")
        if hit and hit[2]:
            with open(hit[0], encoding="utf-8") as f:
                same = body_key(f.read()) == " ".join(body[:MAX_BODY].split())
            if same:
                # Same text: the earlier file is today's file, and its card stands.
                shutil.copyfile(hit[0], path)
                card = _reuse(hit[2], path, hit[1])
                e["reused_from"] = card["reused_from"]
                return e, card, ("live", "")
        _write_txt(path, req, rec, "read live from the posting's own URL for a Tailor it request")
        return e, None, ("live", "text changed since the screen read it" if hit else "")
    why = err[:200] or f"the live page came back with {len(body)} characters"
    if hit:
        src, day, card = hit
        shutil.copyfile(src, path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n[cached copy read {day.isoformat()}; the live read failed: {why}]\n")
        e.update(status="ok", file=path, read_status="cached", cached_from=day.isoformat(), live_error=why)
        out = _reuse(card, path, day) if card else None
        if out:
            e["reused_from"] = out["reused_from"]
        return e, out, ("cached", f"live read failed ({why}); used the copy read {day.isoformat()}")
    e.update(status="error", error=why)
    return e, None, ("unreadable", why)


def run_read(args):
    """Step 1d-4 for cleared requests: read up to --max of them into jobs/jd_cache/<date>_cleared/."""
    today = date.fromisoformat(args.date)
    limit = CLEARED_MAX if args.max is None else args.max
    try:
        chosen, waiting = pending(limit)
    except Exception as exc:  # noqa: BLE001
        print(f"cleared_requests: FAILED, cannot read {PATH}: {type(exc).__name__}: {exc}")
        return 1
    cfg = scoring_config()
    print(f"cleared_requests --read: {len(chosen)} selected of {waiting} waiting")
    if args.dry_run or not chosen:
        for r in chosen:
            print(f"  {r.get('company', '?')}: {r.get('title', '?')} | score {r.get('score', '?')}, "
                  f"tier {tier_for(r.get('score'), cfg)} (asked {r.get('marked', '?')})")
        return 0

    cache = os.path.join(JOBS_DIR, "jd_cache", f"{args.date}_cleared")
    os.makedirs(cache, exist_ok=True)
    stages = tracked_stages()
    entries, cards, stamps = [], [], {}
    for n, req in enumerate(chosen, 1):
        req = dict(req, n=n)
        stage = stages.get(req["key"])
        if stage is not None:
            stamps[req["key"]] = (f"already in the tracker ({stage or 'no stage'})", "")
            entries.append({"source": "cleared_request", "company": req.get("company") or "?",
                            "title": req.get("title") or "?", "url": req["url"],
                            "status": f"skipped: already in outcomes.csv ({stage or 'no stage'})"})
            continue
        try:
            e, card, st = read_one(req, today, cache, read=args.reader or live_read)
        except Exception as exc:  # noqa: BLE001 - one bad read must not cost the others
            e = {"source": "cleared_request", "company": req.get("company") or "?",
                 "title": req.get("title") or "?", "url": req["url"], "status": "error",
                 "error": f"{type(exc).__name__}: {exc}"[:200]}
            card, st = None, ("unreadable", e["error"])
        e["tier"] = tier_for(req.get("score"), cfg)
        entries.append(e)
        if card:
            cards.append(card)
        stamps[req["key"]] = st

    readable = [e for e in entries if e.get("file")]
    to_read = [e["file"] for e in readable if "reused_from" not in e]
    with open(os.path.join(cache, REUSED_CARDS), "w", encoding="utf-8") as f:
        json.dump(cards, f, indent=1)
        f.write("\n")
    batches = [to_read] if to_read else []
    for old in glob.glob(os.path.join(cache, "batch_*.json")):
        os.remove(old)   # a second run the same day must not leave the first one's batch behind
    if to_read:
        with open(os.path.join(cache, "batch_01.json"), "w", encoding="utf-8") as f:
            json.dump(to_read, f, indent=1)
            f.write("\n")
    manifest = {"date": args.date, "source": PATH,
                "counts": {"selected": len(chosen), "waiting_before": waiting, "fetched": len(readable),
                           "live": sum(1 for e in entries if e.get("read_status") == "live"),
                           "cached": sum(1 for e in entries if e.get("read_status") == "cached"),
                           "reused_cards": len(cards), "to_read": len(to_read), "batches": len(batches)},
                "batches": batches, "entries": entries}
    with open(os.path.join(cache, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
        f.write("\n")
    stamped = stamp(stamps, today)
    k = manifest["counts"]
    print(f"read {k['fetched']} ({k['live']} live, {k['cached']} from a cached copy), "
          f"{k['reused_cards']} card(s) reused, {k['to_read']} for a worker"
          + (" in batch_01.json" if to_read else "") + f"; {stamped} request(s) stamped; dir {cache}")
    for e in entries:
        tail = f"tier {e['tier']}, score {e.get('score', '?')}" if e.get("tier") else ""
        line = f"{e['company']}: {e['title']}"
        if e.get("read_status") == "cached":
            print(f"  CACHED   {line} ({tail}) -- not confirmed open: {e['live_error'][:100]}")
        elif e.get("file"):
            print(f"  OK       {line} ({tail})" + (" card reused" if e.get("reused_from") else " needs a worker"))
        elif e["status"].startswith("skipped: posting closed"):
            print(f"  CLOSED   {line}")
        elif e["status"].startswith("skipped"):
            print(f"  SKIPPED  {line} -- {e['status'][9:]}")
        else:
            print(f"  UNREAD   {line} -- {e.get('error', '')[:100]}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--read", action="store_true", help="read the waiting requests (Step 1d-4)")
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--max", type=int, default=None, help=f"requests to read (default {CLEARED_MAX})")
    ap.add_argument("--dry-run", action="store_true", help="with --read: print the selection, fetch nothing")
    args = ap.parse_args(argv)
    args.reader = None   # tests put a stand-in for the network here
    if args.read:
        return run_read(args)
    try:
        reqs = load()
    except Exception as e:  # noqa: BLE001
        print(f"cleared_requests: cannot read {PATH}: {type(e).__name__}: {e}")
        return 1
    waiting, n = pending(10 ** 6)
    print(f"cleared_requests: {len(reqs)} recorded, {n} waiting for a read")
    for e in waiting:
        print(f"  waiting: {e.get('company', '?')}: {e.get('title', '?')} (asked {e.get('marked', '?')})")
    for k, v in sorted(reqs.items(), key=lambda kv: kv[1].get("read") or ""):
        if v.get("read"):
            print(f"  read {v['read']}: {v.get('company', '?')}: {v.get('title', '?')} -- {v.get('read_status', '?')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
