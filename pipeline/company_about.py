#!/usr/bin/env python3
"""A line or two on what each weekly-lead company does, from its public LinkedIn page.

    .venv/bin/python pipeline/company_about.py                 # fill gaps for the newest weekly leads
    .venv/bin/python pipeline/company_about.py --leads FILE    # a specific weekly_leads_<date>.json
    .venv/bin/python pipeline/company_about.py --list          # what's cached

Added 2026-10-15, the day This week's leads replaced the weekly email (D41). Aneesh didn't
want to answer Tailor it or Pass blind on a company he'd never heard of, and most of these
have no ATS board and no watchlist entry, so nothing in the pipeline said what they do.

Source: the LinkedIn job id every lead carries. The public posting page
(jobs-guest/jobs/api/jobPosting/<id>, no sign-in) links the company's LinkedIn page, and
that page's About section has the description, industry, and headcount. Going through the
posting instead of searching the name is what keeps a short or common company name from
landing on some other company. No model.

    jobs/company_about.json (gitignored, like every run-state file)
    {"companies": {"<norm(name)>": {"name", "slug", "about", "industry", "size", "checked"}
                                 | {"name", "miss": "<why>", "checked", "retry"}}}

build_dashboard.py reads it at render time, joined on norm(company name), so a line
fetched on any day shows up on that day's build without touching the weekly file.

RULES
- Polite and bounded: one request at a time, PAUSE seconds apart, and a wall-clock budget
  (--budget). Throttling (HTTP 429 or 999, or a redirect to the sign-in wall) waits BACKOFF
  and tries again, and stops the run after RETRIES in a row. Whatever is left waits for the
  next run. The cache is saved after every company, so a killed run loses at most one lookup.
- A hit is kept KEEP_DAYS, then looked up again. A miss (closed posting, no company link,
  no About section, a university page, which LinkedIn never shows a guest) waits MISS_DAYS;
  a network error or a refused company page waits a day.
- Always exits 0. A failure here leaves a lead without its line and changes nothing else.
"""
import argparse
import glob
import html
import json
import os
import re
import sys
import time
from datetime import date, timedelta
from urllib.parse import unquote

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.path.join(SCRIPT_DIR, "jobs")
CACHE_NAME = "company_about.json"

POSTING_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"
COMPANY_URL = "https://www.linkedin.com/{slug}"
# Same endpoint, headers, and pace as linkedin_followup.py, which reads these postings' JDs.
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
TIMEOUT = (5, 20)
PAUSE = 3
# The posting endpoint allows a short burst, then answers 429 for a few minutes (measured
# 2026-10-15: about six postings in half a minute, clear again within three minutes). So a
# 429 waits BACKOFF and tries the same company again, and the RETRIES-th in a row stops.
BACKOFF = 90
RETRIES = 3
REFUSALS = 2
BUDGET = 420
KEEP_DAYS = 180
MISS_DAYS = 14
ERROR_DAYS = 1
# Sentences are added until the line reaches BLURB_MIN, and never past BLURB_MAX.
BLURB_MIN, BLURB_MAX = 110, 240
JOB_ID_RE = re.compile(r"^\d{6,12}$")


class Throttled(Exception):
    pass


def norm(name):
    # build_dashboard.py joins on this same key and can't import it. Change both together.
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _text(fragment):
    t = re.sub(r"<br\s*/?>", "\n", fragment or "", flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def blurb(text):
    """The first sentence or two of an About section, BLURB_MAX characters at most."""
    text = _text(text)
    out = ""
    for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", text):
        if out and len(out) + 1 + len(s) > BLURB_MAX:
            break
        out = (out + " " + s).strip()
        if len(out) >= BLURB_MIN:
            break
    if len(out) > BLURB_MAX:
        out = out[:BLURB_MAX].rsplit(" ", 1)[0].rstrip(",;:-–— ") + "…"
    return out


def company_slug(posting_html):
    """The employer's LinkedIn page path from a public posting, "company/<slug>" or
    "school/<slug>" (a university), or None."""
    # Only the posting's top card: a looser match could pick up some other company's link.
    page = r"((?:company|school|showcase)/[^/?\"#]+)"
    m = (re.search(r'topcard__org-name-link[^>]*href="https://www\.linkedin\.com/' + page, posting_html or "")
         or re.search(r"linkedin\.com/" + page + r"/?\?trk=public_jobs_topcard", posting_html or ""))
    return unquote(m.group(1)) if m else None


def _dd(page, test_id):
    m = re.search(r'data-test-id="%s".*?<dd[^>]*>(.*?)</dd>' % re.escape(test_id), page, re.S)
    return _text(m.group(1))[:60] if m else ""


def parse_company(page):
    """{about, industry, size} from a public company page; about is "" when there's none."""
    page = page or ""
    m = re.search(r'data-test-id="about-us__description"[^>]*>(.*?)</p>', page, re.S)
    about = blurb(m.group(1)) if m else ""
    if not about:
        # Older or school pages: "<Name> | 1,234 followers on LinkedIn. <tagline> | <about>"
        m = re.search(r'<meta name="description" content="([^"]*)"', page)
        if m:
            d = re.sub(r"^.*?followers on LinkedIn\.\s*", "", html.unescape(m.group(1)))
            about = blurb(d.split(" | ")[-1])
    return {"about": about, "industry": _dd(page, "about-us__industry"),
            "size": _dd(page, "about-us__size")}


def get(url):
    """Page text, or None for a page that isn't there. Raises Throttled on any sign of it."""
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    if r.status_code in (429, 999) or "authwall" in r.url or "/login" in r.url:
        raise Throttled(f"HTTP {r.status_code} at {r.url[:80]}")
    if r.status_code in (404, 410):
        return None
    r.raise_for_status()
    return r.text


def lookup(job_id, name, today, fetch=get, pause=PAUSE, sleep=time.sleep):
    """One cache entry for the company behind this posting. Two requests at most."""
    def miss(why, days=MISS_DAYS):
        return {"name": name, "miss": why, "checked": today.isoformat(),
                "retry": (today + timedelta(days=days)).isoformat()}
    try:
        posting = fetch(POSTING_URL.format(id=job_id))
        slug = company_slug(posting) if posting else None
        if not slug:
            return miss("posting closed" if posting is None else "no company link on the posting")
        sleep(pause)
        try:
            page = fetch(COMPANY_URL.format(slug=slug))
        except Throttled as e:
            # A university's page answers every guest with a 999, so that's a plain miss. A
            # company's refusal may pass by tomorrow, and fill() stops after REFUSALS in a row.
            school = slug.startswith("school/")
            return {**miss(f"page refused ({e})", MISS_DAYS if school else ERROR_DAYS),
                    "slug": slug, "refused": not school}
    except requests.RequestException as e:
        return miss(f"error: {type(e).__name__}", ERROR_DAYS)
    info = parse_company(page) if page else {}
    if not info.get("about") and not info.get("industry"):
        return miss("no About section")
    return {"name": name, "slug": slug, **info, "checked": today.isoformat()}


def is_fresh(entry, today):
    if not isinstance(entry, dict) or not entry.get("checked"):
        return False
    try:
        if "miss" in entry:
            return date.fromisoformat(entry.get("retry") or "") > today
        return date.fromisoformat(entry["checked"]) + timedelta(days=KEEP_DAYS) > today
    except ValueError:
        return False


def load_cache(path):
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        comps = raw.get("companies") if isinstance(raw, dict) else None
        return {"companies": comps if isinstance(comps, dict) else {}}
    except (OSError, ValueError):
        return {"companies": {}}


def save_cache(cache, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=1, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def fill(leads, cache_path, today, budget=BUDGET, fetch=get, pause=PAUSE, backoff=BACKOFF,
         clock=time.monotonic, sleep=time.sleep):
    """Look up every lead company the cache has nothing fresh for, in page order.

    Returns {looked_up, hits, misses, cached, left, stopped}.
    """
    cache = load_cache(cache_path)
    comps = cache["companies"]
    todo, seen = [], set()
    for x in leads:
        if not isinstance(x, dict):
            continue
        key, jid = norm(x.get("company")), str(x.get("id") or "")
        if not key or key in seen or not JOB_ID_RE.match(jid):
            continue
        seen.add(key)
        if not is_fresh(comps.get(key), today):
            todo.append((key, jid, (x.get("company") or "").strip()))
    stats = {"looked_up": 0, "hits": 0, "misses": 0, "cached": len(seen) - len(todo),
             "left": 0, "stopped": ""}
    start, i, throttles, refusals = clock(), 0, 0, 0
    while i < len(todo):
        key, jid, name = todo[i]
        if clock() - start > budget:
            stats["stopped"] = f"budget of {budget}s"
            break
        if i or throttles:
            sleep(pause)
        try:
            comps[key] = lookup(jid, name, today, fetch=fetch, pause=pause, sleep=sleep)
        except Throttled as e:
            throttles += 1
            if throttles >= RETRIES or clock() - start + backoff > budget:
                stats["stopped"] = f"throttled ({e})"
                break
            sleep(backoff)
            continue
        throttles = 0
        stats["looked_up"] += 1
        stats["misses" if "miss" in comps[key] else "hits"] += 1
        save_cache(cache, cache_path)
        i += 1
        refusals = refusals + 1 if comps[key].get("refused") else 0
        if refusals >= REFUSALS:
            stats["stopped"] = f"{REFUSALS} company pages refused in a row"
            break
    stats["left"] = len(todo) - i
    return stats


def newest_leads_file():
    files = sorted(glob.glob(os.path.join(JOBS_DIR, "weekly_leads_*.json")))
    return files[-1] if files else None


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--leads", help="A weekly_leads_<date>.json; default is the newest in jobs/.")
    p.add_argument("--budget", type=int, default=BUDGET, help="Wall-clock seconds for lookups.")
    p.add_argument("--list", action="store_true", help="Print the cache and stop.")
    args = p.parse_args(argv)
    cache_path = os.path.join(JOBS_DIR, CACHE_NAME)
    if args.list:
        for key, e in sorted(load_cache(cache_path)["companies"].items()):
            line = e.get("about") or f"(miss: {e.get('miss')}, retry {e.get('retry')})"
            print(f"{e.get('name') or key}: {line}")
        return 0
    path = args.leads or newest_leads_file()
    try:
        with open(path, encoding="utf-8") as f:
            leads = json.load(f).get("leads") or []
    except (TypeError, OSError, ValueError, AttributeError) as e:
        print(f"company_about: no weekly leads to read ({type(e).__name__}); nothing looked up.")
        return 0
    try:
        s = fill(leads, cache_path, date.today(), budget=args.budget)
    except Exception as e:  # noqa: BLE001 - a missing line must never fail the run
        print(f"company_about: FAILED ({type(e).__name__}: {e}); the page shows leads without lines.")
        return 0
    print(f"company_about: {os.path.basename(path)}: {s['looked_up']} looked up "
          f"({s['hits']} with a line, {s['misses']} without), {s['cached']} already cached, "
          f"{s['left']} left for the next run" + (f"; stopped on {s['stopped']}" if s["stopped"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
