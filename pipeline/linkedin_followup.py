#!/usr/bin/env python3
"""Role-level follow-through for LinkedIn alert cards (daily_task_prompt.md Step 1d-3).

    .venv/bin/python pipeline/linkedin_followup.py            # today's cards
    .venv/bin/python pipeline/linkedin_followup.py --dry-run  # select and print, fetch nothing
    .venv/bin/python pipeline/linkedin_followup.py --ids 4474329851 4473170805
    .venv/bin/python pipeline/linkedin_followup.py --requested   # Step 1d-4: the roles he
                                    # asked for with Tailor it on the dashboard (D41)

Why this exists (2026-10-05). Step 1d-2 harvests COMPANIES from the alert emails
and deliberately never follows a role. That design holds for a company the poller
can then watch, and it loses the role everywhere else. An audit of one day's alerts
found four ways a strong card went nowhere:

  * the card came from an aggregator, so the reposter's name was dropped and the
    role with it (TalentHop's "AI Operations Manager (Remote)", six alerts);
  * the company name matched a different company's old rejection (Echo);
  * the company lookup was rate-limited or timed out, so nothing was known and
    nothing was surfaced (Arclin);
  * LinkedIn's PLAIN-TEXT alert body omits the Remote / Hybrid tag that the app
    and the HTML email show, so "New York, NY (Remote)" arrives as "New York, NY"
    and is graded as an on-site role in another city (Echo again, Nuvia).

The last one cannot be fixed in the parser: the tag is not in the text we fetch.
What CAN be read without a login is LinkedIn's guest posting endpoint, which
returns the full job description for any job id. So this script takes the cards
worth a look, fetches each JD once, and writes them in the same shape
jd_prefetch.py uses, into jobs/jd_cache/<date>_linkedin/. The Step 2-JD screen
workers and jd_screen_table.py then read them unchanged:

    .venv/bin/python pipeline/jd_screen_table.py --date <date>_linkedin

Selection, in order, capped at --max (default 24, i.e. three worker batches):
  1. cards at companies the pipeline has never resolved (new, or parked on a
     timeout / rate limit), strong tier or AI wildcard;
  2. aggregator reposts with a strong title (employer unknown);
  3. cards at companies rejected or covered only by a manual rotation.
Cards at watchlist companies are skipped: the poller reads those boards daily.
Non-US cards, demoted and hard-excluded titles, and VP-and-above are skipped.
A role already in outcomes.csv is skipped. Each job id is fetched once, ever
(jobs/linkedin_followup_seen.json); ids cut by the cap are NOT marked seen, so
they roll to the next run instead of vanishing.

A card whose location is a US city with no workplace tag is kept unless the JD
body itself says on-site or hybrid without also saying remote. That is the Echo
case: the body is silent, the app says Remote, and only a read settles it.

Read-only against every tracking file. Writes the cache directory and the seen
file, and with --requested stamps each read onto its request in jobs/lead_marks.json
through lead_marks.py. Nothing else. Standard library plus requests.
"""
import argparse
import csv
import datetime as dt
import html
import json
import os
import re
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
JOBS = os.path.join(HERE, "jobs")
OUTCOMES = os.path.join(HERE, "outcomes.csv")
ENROLLMENT = os.path.join(HERE, "enrollment_candidates.json")
SEEN = os.path.join(JOBS, "linkedin_followup_seen.json")

GUEST_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{jid}"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
DELAY = 1.5
DEFAULT_MAX = 24       # three worker batches
REQUESTED_MAX = 3      # roles he asked for, read and tailored per run (D41)
TIMEOUT = (5, 20)
MAX_BODY = 20000
BATCH_SIZE = 8

FOLLOW_TIERS = ("tier1_true_match", "tier2_strong_overlap", "tier2c_tooling_systems",
                "tier2b_ai_wildcard")
TIER_RANK = {t: i for i, t in enumerate(FOLLOW_TIERS)}
LOC_RANK = {"atlanta": 0, "atlanta-hybrid": 1, "remote": 2, "us-national": 3, "other": 4,
            "unknown": 5}
# Seniority flags from poll_ats.title_exclusion_reasons that end the follow-up.
# "director" and "head of" stay in: exact tier1 titles carry them.
TOO_SENIOR = ("vice president", "vp", "chief", "principal", "staff", "svp", "evp")

ELSEWHERE_RE = re.compile(
    r"\b(in[- ]office|on[- ]?site|in[- ]person|"
    r"hybrid (?:role|position|work|schedule|model|environment)|"
    r"days? (?:a|per|each) week (?:in|at|from) (?:the|our) )", re.I)
REMOTE_RE = re.compile(r"\b(remote|work from home|telecommut|distributed team)\b", re.I)


def slugify(s, n=40):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:n]


def norm(s):
    return "".join(c for c in (s or "").lower() if c.isalnum())


def unresolved_names():
    """Companies whose rejection is a timeout or a rate limit: nothing is known."""
    try:
        with open(ENROLLMENT, encoding="utf-8") as f:
            q = json.load(f)
    except (OSError, ValueError):
        return set()
    return {norm(e.get("name")) for e in q.get("rejected", [])
            if e.get("throttled") or e.get("timed_out")}


def tracked_roles():
    """(company, title) pairs already in outcomes.csv, normalized."""
    out = set()
    try:
        with open(OUTCOMES, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                out.add((norm(r.get("company")), norm(r.get("title"))))
    except OSError:
        pass
    return out


def status_class(card, unresolved):
    """0 never resolved, 1 aggregator repost, 2 rejected / manual rotation, None skip."""
    if card.get("aggregator"):
        return 1
    status = card.get("company_status") or []
    if "watchlist" in status:
        return None
    if not status or "pending" in status or norm(card["company"]) in unresolved:
        return 0
    return 2


def select(cards_doc, seen, limit):
    unresolved = unresolved_names()
    tracked = tracked_roles()
    picked, skipped = [], {"watchlist": 0, "seen": 0, "tracked": 0, "title": 0, "non_us": 0}
    by_id = {}
    for card in (cards_doc.get("cards") or []) + (cards_doc.get("aggregator_cards") or []):
        by_id.setdefault(card["job_id"], card)
    for card in by_id.values():
        if card.get("tier_name") not in FOLLOW_TIERS or card.get("title_tier") in ("demoted", "excluded"):
            skipped["title"] += 1
            continue
        if any(s in f.lower() for f in (card.get("seniority_flags") or []) for s in TOO_SENIOR):
            skipped["title"] += 1
            continue
        if card.get("location_verdict") == "non-us":
            skipped["non_us"] += 1
            continue
        cls = status_class(card, unresolved)
        if cls is None:
            skipped["watchlist"] += 1
            continue
        if card["job_id"] in seen:
            skipped["seen"] += 1
            continue
        co, ti = norm(card["company"]), norm(card["title"])
        if any(c and (c in co or co in c) and t == ti for c, t in tracked):
            skipped["tracked"] += 1
            continue
        picked.append((cls, TIER_RANK[card["tier_name"]],
                       LOC_RANK.get(card.get("location_verdict"), 9), card["company"].lower(), card))
    picked.sort(key=lambda x: x[:4])
    # One follow-up per (company, title): saved searches re-send the same role
    # under a new job id, and aggregators do it on purpose.
    out, dupes = [], set()
    for cls, _, _, _, card in picked:
        k = (norm(card["company"]), norm(card["title"]))
        if k in dupes:
            continue
        dupes.add(k)
        card["_class"] = cls
        out.append(card)
    return out[:limit], out[limit:], skipped


def html_to_text(fragment):
    t = re.sub(r"(?i)<li[^>]*>", "\n - ", fragment)
    t = re.sub(r"(?i)<(br|/p|/div|/ul|/ol|/h\d)[^>]*>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", t).strip()


def fetch(session, jid):
    """One guest-endpoint read. Returns a dict with either `body` or `error`."""
    try:
        r = session.get(GUEST_URL.format(jid=jid), headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    if r.status_code == 429:
        return {"error": "429", "throttled": True}
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}"}
    h = r.text
    desc = re.search(r'show-more-less-html__markup[^>]*>(.*?)</div>', h, re.S)
    if not desc:
        return {"error": "no description block (posting closed, or the page shape changed)"}
    title = re.search(r'topcard__title[^>]*>([^<]+)<', h)
    org = re.search(r'topcard__org-name-link[^>]*>\s*([^<]+?)\s*<', h)
    loc = re.search(r'topcard__flavor topcard__flavor--bullet[^>]*>\s*([^<]+?)\s*<', h)
    posted = re.search(r'posted-time-ago__text[^>]*>\s*([^<]+?)\s*<', h)
    closed = bool(re.search(r"No longer accepting applications", h))
    return {
        "body": html_to_text(desc.group(1)),
        "title": html.unescape(title.group(1).strip()) if title else None,
        "company": html.unescape(org.group(1)) if org else None,
        "location": html.unescape(loc.group(1)) if loc else None,
        "posted": posted.group(1) if posted else None,
        "closed": closed,
    }


def elsewhere(card, body):
    """True when a US-city card's own JD says on-site or hybrid and never says remote."""
    if card.get("location_verdict") != "other":
        return False
    return bool(ELSEWHERE_RE.search(body)) and not REMOTE_RE.search(body)


def transient(error):
    """A fetch error that may pass: a request exception or a 5xx. A 4xx or a page with no
    description block is the posting itself, and retrying won't change it."""
    if error.startswith("HTTP "):
        return error.startswith("HTTP 5")
    return not error.startswith("no description")


def write_jd(cache, c, rec, url, note=None):
    """One JD file in the Step 2-JD shape. Returns its path."""
    body = rec["body"]
    name = f"li_{c['job_id']}_{slugify(c['company'], 20)}_{slugify(c['title'], 40)}.txt"
    path = os.path.join(cache, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"COMPANY : {rec.get('company') or c['company']}\n")
        f.write(f"TITLE   : {rec.get('title') or c['title']}\n")
        f.write(f"URL     : {url}\n")
        f.write("ATS     : linkedin-guest (public LinkedIn posting, not the source ATS)\n")
        f.write(f"LOCATION: {rec.get('location') or c.get('location')}   remote=None\n")
        f.write(f"LISTING LOCATION: {c.get('location')}  [LinkedIn's alert email and public page "
                f"omit the Remote/Hybrid tag: workplace is UNKNOWN unless the body states it]\n")
        f.write(f"POSTED  : {rec.get('posted')}\n")
        f.write("SALARY  : None\n")
        if c.get("aggregator"):
            f.write("NOTE    : posted by a job-board aggregator; the real employer is named or "
                    "described in the body, if at all\n")
        if note:
            f.write(f"NOTE    : {note}\n")
        f.write("-" * 70 + "\n")
        f.write(body[:MAX_BODY])
        if len(body) > MAX_BODY:
            f.write(f"\n[truncated at {MAX_BODY} of {len(body)} chars]\n")
    return path


def run_requested(args):
    """Read the postings he asked for with Tailor it on the dashboard (Step 1d-4, D41).

    The requests are in jobs/lead_marks.json, recorded there by shelf_inbox.py at Step 0
    item 4b. Oldest click first, REQUESTED_MAX a run, into jobs/jd_cache/<date>_requested/
    in the same shape as the normal follow-through, so the Step 2-JD worker and
    jd_screen_table.py read them unchanged. Each read is stamped back on its request
    (ok, thin, closed, on-site elsewhere, or the error), which is what takes it out of the
    waiting list. A 429 stops the walk and stamps nothing further: those roll to the next
    run. Unlike the normal walk there is no tier or company filter; he already chose.
    """
    import lead_marks
    limit = REQUESTED_MAX if args.max is None else args.max
    try:
        chosen, waiting = lead_marks.pending_requests(limit)
    except Exception as exc:  # noqa: BLE001
        print(f"linkedin_followup: FAILED, cannot read {lead_marks.PATH}: {type(exc).__name__}: {exc}")
        return 1
    print(f"linkedin_followup --requested: {len(chosen)} selected of {waiting} waiting")
    if args.dry_run or not chosen:
        for c in chosen:
            print(f"  {c.get('company', '?')}: {c.get('title', '?')} | {c['job_id']} (asked {c.get('marked', '?')})")
        return 0

    try:
        with open(SEEN, encoding="utf-8") as f:
            seen = json.load(f)
    except (OSError, ValueError):
        seen = {}
    cache = os.path.join(JOBS, "jd_cache", f"{args.date}_requested")
    os.makedirs(cache, exist_ok=True)
    session = requests.Session()
    entries, stamps, retry, dropped = [], {}, {}, []
    today = dt.date.fromisoformat(args.date)
    for i, req in enumerate(chosen, 1):
        jid = req["job_id"]
        c = {"job_id": jid, "company": req.get("company") or "?", "title": req.get("title") or "?",
             "location": req.get("loc") or "", "location_verdict": req.get("loc") or "unknown"}
        url = f"https://www.linkedin.com/jobs/view/{jid}/"
        e = {"idx": i, "company": c["company"], "title": c["title"], "url": url, "ats": "linkedin-guest",
             "source": "dashboard_request", "job_id": jid, "listing_location": c["location"],
             "card_tier": req.get("tier"), "card_location_verdict": req.get("loc"),
             "company_class": f"asked for on the dashboard ({req.get('list') or 'weekly lead'})",
             "asked": req.get("marked"), "jd_verification_required": True}
        rec = fetch(session, jid)
        if rec.get("throttled"):
            print(f"  [RL] LinkedIn returned 429 at {c['company']}; stopping. "
                  f"{len(chosen) - i + 1} request(s) stay waiting for the next run.")
            break
        if rec.get("error") and transient(rec["error"]):
            # A timeout or a server error may pass by tomorrow. Count the try, keep the
            # request waiting, and don't mark the id seen.
            e.update(status="error", error=rec["error"])
            retry[jid] = rec["error"]
            entries.append(e)
            time.sleep(DELAY)
            continue
        if rec.get("error"):
            e.update(status="error", error=rec["error"])
            stamps[jid] = f"error: {rec['error']}"
        elif rec.get("closed"):
            e.update(status="skipped: posting closed")
            stamps[jid] = "closed"
            dropped.append(f"{c['company']}: {c['title']} (no longer accepting applications)")
        elif elsewhere(c, rec["body"]):
            e.update(status="skipped: on-site or hybrid outside Atlanta per the JD body")
            stamps[jid] = "on-site elsewhere"
            dropped.append(f"{c['company']}: {c['title']} (JD body says on-site or hybrid)")
        else:
            path = write_jd(cache, c, rec, url, note="Aneesh asked for this one with Tailor it on the dashboard")
            status = "ok" if len(rec["body"]) >= 400 else "thin"
            e.update(status=status, file=path, chars=len(rec["body"]))
            stamps[jid] = status
        entries.append(e)
        seen[jid] = args.date
        time.sleep(DELAY)

    readable = [e for e in entries if e.get("file")]
    batches = [readable[i:i + BATCH_SIZE] for i in range(0, len(readable), BATCH_SIZE)]
    for n, b in enumerate(batches, 1):
        for e in b:
            e["batch"] = n
        with open(os.path.join(cache, f"batch_{n:02d}.json"), "w", encoding="utf-8") as f:
            json.dump([e["file"] for e in b], f, indent=1)
            f.write("\n")
    manifest = {"date": args.date, "source": lead_marks.PATH,
                "counts": {"selected": len(chosen), "waiting_before": waiting, "fetched": len(readable),
                           "errors": sum(1 for e in entries if e["status"] == "error"),
                           "dropped": len(dropped), "batches": len(batches)},
                "batches": [[e["file"] for e in b] for b in batches], "entries": entries}
    with open(os.path.join(cache, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
        f.write("\n")
    with open(SEEN, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=1, sort_keys=True)
        f.write("\n")
    stamped = lead_marks.stamp(stamps, today)
    gave_up = lead_marks.note_retry(retry, today)
    k = manifest["counts"]
    print(f"fetched {k['fetched']}, errors {k['errors']}, dropped {k['dropped']}; "
          f"{k['batches']} batch file(s) in {cache}; {stamped} request(s) stamped as read")
    if retry:
        print(f"  {len(retry) - len(gave_up)} request(s) hit a timeout or server error and stay waiting"
              + (f"; {len(gave_up)} gave up after {lead_marks.RETRY_LIMIT} tries" if gave_up else ""))
    for d in dropped:
        print(f"  dropped  {d}")
    for e in entries:
        if e["status"] == "error":
            print(f"  ERROR    {e['company']}: {e['title']} -- {e['error'][:100]}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--max", type=int, default=None,
                    help=f"JDs to fetch this run (default {DEFAULT_MAX}; {REQUESTED_MAX} with --requested)")
    ap.add_argument("--ids", nargs="*", help="fetch exactly these job ids, ignoring selection and the seen file")
    ap.add_argument("--requested", action="store_true",
                    help="read the roles he asked for on the dashboard (jobs/lead_marks.json), oldest first")
    ap.add_argument("--dry-run", action="store_true", help="print the selection, fetch nothing")
    args = ap.parse_args()
    if args.requested:
        if args.ids:
            ap.error("--requested picks its own ids; drop --ids")
        return run_requested(args)
    args.max = DEFAULT_MAX if args.max is None else args.max

    cards_path = os.path.join(JOBS, f"linkedin_cards_{args.date}.json")
    try:
        with open(cards_path, encoding="utf-8") as f:
            cards_doc = json.load(f)
    except (OSError, ValueError) as exc:
        print(f"linkedin_followup: FAILED, cannot read {cards_path}: {exc}")
        return 1
    try:
        with open(SEEN, encoding="utf-8") as f:
            seen = json.load(f)
    except (OSError, ValueError):
        seen = {}

    if args.ids:
        index = {c["job_id"]: c for c in (cards_doc.get("cards") or []) + (cards_doc.get("aggregator_cards") or [])}
        chosen = [index.get(j) or {"job_id": j, "company": "?", "title": "?", "location": "",
                                   "location_verdict": "unknown", "tier_name": None,
                                   "title_prescore": 0, "location_points": 0}
                  for j in args.ids]
        deferred, skipped = [], {}
    else:
        chosen, deferred, skipped = select(cards_doc, seen, args.max)

    label = {0: "unresolved company", 1: "aggregator repost", 2: "rejected or manual-rotation company"}
    print(f"linkedin_followup: {len(chosen)} selected, {len(deferred)} deferred by the cap; skipped {skipped}")
    if args.dry_run:
        for c in chosen:
            print(f"  [{c.get('title_tier')} | {c.get('location_verdict')}] {c['company']}: {c['title']} "
                  f"| {c['job_id']} | {label.get(c.get('_class'), 'by id')}")
        return 0

    # --ids is an ad-hoc read and must not overwrite the run's own manifest.
    cache = os.path.join(JOBS, "jd_cache", f"{args.date}_linkedin" + ("_adhoc" if args.ids else ""))
    os.makedirs(cache, exist_ok=True)
    session = requests.Session()
    entries, dropped = [], []
    for i, c in enumerate(chosen, 1):
        jid = c["job_id"]
        url = f"https://www.linkedin.com/jobs/view/{jid}/"
        e = {"idx": i, "company": c["company"], "title": c["title"], "url": url, "ats": "linkedin-guest",
             "source": "linkedin_card", "job_id": jid, "listing_location": c.get("location"),
             "pre_score": (c.get("title_prescore") or 0) + (c.get("location_points") or 0),
             "card_tier": c.get("title_tier"), "card_location_verdict": c.get("location_verdict"),
             "company_class": label.get(c.get("_class"), "by id"),
             "jd_verification_required": True}
        rec = fetch(session, jid)
        if rec.get("throttled"):
            print(f"  [RL] LinkedIn returned 429 at {c['company']}; stopping. "
                  f"{len(chosen) - i + 1} unfetched id(s) stay unseen and roll to the next run.")
            break
        if rec.get("error"):
            e.update(status="error", error=rec["error"])
            entries.append(e)
            seen[jid] = args.date
            time.sleep(DELAY)
            continue
        body = rec["body"]
        if rec.get("closed"):
            e.update(status="skipped: posting closed")
            dropped.append(f"{c['company']}: {c['title']} (no longer accepting applications)")
        elif elsewhere(c, body):
            e.update(status="skipped: on-site or hybrid outside Atlanta per the JD body")
            dropped.append(f"{c['company']}: {c['title']} [{c.get('location')}] (JD body says on-site or hybrid)")
        else:
            path = write_jd(cache, c, rec, url)
            e.update(status="ok" if len(body) >= 400 else "thin", file=path, chars=len(body))
        entries.append(e)
        seen[jid] = args.date
        time.sleep(DELAY)

    readable = [e for e in entries if e.get("file")]
    batches = [readable[i:i + BATCH_SIZE] for i in range(0, len(readable), BATCH_SIZE)]
    for n, b in enumerate(batches, 1):
        for e in b:
            e["batch"] = n
        with open(os.path.join(cache, f"batch_{n:02d}.json"), "w", encoding="utf-8") as f:
            json.dump([e["file"] for e in b], f, indent=1)
            f.write("\n")
    manifest = {
        "date": args.date, "cards_file": cards_path,
        "counts": {"selected": len(chosen), "deferred": len(deferred), "fetched": len(readable),
                   "errors": sum(1 for e in entries if e["status"] == "error"),
                   "dropped": len(dropped), "batches": len(batches)},
        "batches": [[e["file"] for e in b] for b in batches],
        "entries": entries,
        "deferred": [f"{c['company']}: {c['title']} | {c['job_id']}" for c in deferred],
    }
    with open(os.path.join(cache, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
        f.write("\n")
    if not args.ids:
        with open(SEEN, "w", encoding="utf-8") as f:
            json.dump(seen, f, indent=1, sort_keys=True)
            f.write("\n")

    k = manifest["counts"]
    print(f"fetched {k['fetched']}, errors {k['errors']}, dropped {k['dropped']}; "
          f"{k['batches']} batch file(s) in {cache}")
    for d in dropped:
        print(f"  dropped  {d}")
    for e in entries:
        if e["status"] == "error":
            print(f"  ERROR    {e['company']}: {e['title']} -- {e['error'][:100]}")
    for d in manifest["deferred"][:12]:
        print(f"  deferred {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
