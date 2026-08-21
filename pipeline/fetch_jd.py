#!/usr/bin/env python3
"""Fetch full job descriptions straight from ATS APIs, bypassing WebFetch.

Usage:
    .venv/bin/python pipeline/fetch_jd.py <apply_url> [<apply_url> ...]
    .venv/bin/python pipeline/fetch_jd.py --from-hits pipeline/jobs/ats_hits_<date>.json \
        --match "Scheduling Lead" --match "Commercial Customer Success"

Why this exists (added 2026-08-21). Step 3 says to WebFetch each top job's apply
URL. For three of the five ATSes that actually reach the shortlist, that does not
work, and the failure is silent-ish: WebFetch returns a page containing only the
job title, or a template shell, and the summarizing model dutifully reports "the
content appears to be empty" -- which reads like a transient error rather than a
structural one.

  - Ashby   (jobs.ashbyhq.com)  JS-rendered. Page yields title only.
  - Workday (*.myworkdayjobs.com) JS-rendered at the /en-US/ path.
  - Comeet  (comeet.com/jobs/..) serves a Spark Hire template with
                                 {{position.name}} placeholders and
                                 "no open positions".

On 2026-08-21 that cost the run its entire discovery block: recovering five JDs by
hand (redirect-following, a board-API guess, two WebSearch fallbacks, and a
throwaway script) consumed the WebSearch budget, and Step 1c's ~14 daily board
dorks were skipped outright. This helper makes JD retrieval deterministic and
free of search budget so the two stop competing.

Each ATS is hit at the endpoint that returns structured data:
  Ashby      https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true
             (whole board; filtered locally. Carries descriptionPlain + real
             compensation tiers, which the rendered page does not expose.)
  Workday    https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/job/{path}
             (the CXS JSON behind the SPA; same path, different prefix.)
  Greenhouse https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{id}?questions=false
             (note: job-boards.greenhouse.io 302s to company domains -- Wiz does
             this -- so go to the API host directly and skip the redirect.)
  Lever      https://api.lever.co/v0/postings/{slug}/{id}
  SmartRec.  https://api.smartrecruiters.com/v1/companies/{slug}/postings/{id}

Prints title, location, remote flag, posting date, compensation, and the FULL
description text. Read the requirements yourself rather than asking a summarizing
model for them -- per Step 3, a summarized JD is how Chainguard's "5+ years in
Data Governance" bar got dropped and a disqualified role got fully tailored.

Exit codes: 0 if every URL resolved, 1 if any failed (failures are reported
individually and do not abort the rest).
"""
import argparse
import datetime as dt
import html
import json
import re
import sys
import urllib.parse

import requests

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
TIMEOUT = 45


def strip_html(raw):
    """HTML -> readable text, preserving list structure."""
    if not raw:
        return ""
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    t = re.sub(r"<li[^>]*>", "\n  - ", t, flags=re.I)
    t = re.sub(r"</(p|div|h\d|ul|ol|tr)>", "\n", t, flags=re.I)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def get(url):
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r


def money(comp):
    """Ashby compensation blob -> one line."""
    if not comp:
        return None
    s = comp.get("scrapeableCompensationSalarySummary") or comp.get("compensationTierSummary")
    return s or None


def fetch_ashby(url):
    m = re.search(r"jobs\.ashbyhq\.com/([^/]+)/([0-9a-f-]{36})", url, re.I)
    if not m:
        return None
    slug, posting_id = urllib.parse.unquote(m.group(1)), m.group(2)
    api = f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
    jobs = get(api).json().get("jobs", [])
    for j in jobs:
        if j.get("id") == posting_id or posting_id in json.dumps(j):
            return {
                "ats": "ashby",
                "title": j.get("title"),
                "location": j.get("location"),
                "remote": j.get("isRemote"),
                "posted": j.get("publishedAt"),
                "salary": money(j.get("compensation")),
                "body": j.get("descriptionPlain") or strip_html(j.get("descriptionHtml")),
            }
    return {"ats": "ashby", "error":
            f"posting {posting_id} not on board '{slug}' ({len(jobs)} postings). "
            f"Board may paginate or the req may have closed."}


def fetch_workday(url):
    m = re.search(r"https://([^.]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[^/]+/)?([^/]+)/job/(.+)$", url)
    if not m:
        return None
    tenant, wd, site, path = m.groups()
    # /en-US/{site}/job/... -> /wday/cxs/{tenant}/{site}/job/...
    api = f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/job/{path}"
    d = get(api).json().get("jobPostingInfo", {})
    return {
        "ats": "workday",
        "title": d.get("title"),
        "location": d.get("location"),
        "remote": d.get("remoteType"),
        "posted": d.get("startDate") or d.get("postedOn"),
        "salary": None,
        "body": strip_html(d.get("jobDescription")),
    }


def fetch_greenhouse(url):
    m = re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([^/?]+)(?:/jobs)?/(\d+)", url)
    if not m:
        m = re.search(r"gh_jid=(\d+)", url)
        if not m:
            return None
        return {"ats": "greenhouse", "error":
                "URL carries only gh_jid; re-run with the board-slug form "
                "https://boards-api.greenhouse.io/v1/boards/<slug>/jobs/<id>"}
    slug, job_id = m.group(1), m.group(2)
    api = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}?questions=false"
    d = get(api).json()
    meta = {x.get("name"): x.get("value") for x in (d.get("metadata") or []) if isinstance(x, dict)}
    # Greenhouse returns `content` as HTML-ESCAPED markup ("&lt;div&gt;..."), so
    # a single strip_html() pass leaves every tag visible as literal text. Unescape
    # once first, then strip. Caught 2026-08-21 testing against the Wiz posting.
    return {
        "ats": "greenhouse",
        "title": d.get("title"),
        "location": (d.get("location") or {}).get("name"),
        "remote": None,
        "posted": d.get("updated_at") or d.get("first_published"),
        "salary": meta.get("Salary Range") or meta.get("Compensation"),
        "body": strip_html(html.unescape(d.get("content") or "")),
    }


def fetch_lever(url):
    m = re.search(r"lever\.co/([^/]+)/([0-9a-f-]{36})", url, re.I)
    if not m:
        return None
    api = f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}"
    d = get(api).json()
    lists = "\n\n".join(
        f"{s.get('text')}\n{strip_html(s.get('content'))}" for s in (d.get("lists") or []))
    # Lever reports createdAt as epoch MILLISECONDS and splits comp into
    # min/max, so render both rather than printing 1785347383710 / just the min.
    created = d.get("createdAt")
    posted = None
    if isinstance(created, (int, float)):
        posted = dt.datetime.fromtimestamp(created / 1000, dt.timezone.utc).date().isoformat()
    sr = d.get("salaryRange") or {}
    salary = None
    if sr.get("min") or sr.get("max"):
        cur = sr.get("currency") or ""
        salary = f"{sr.get('min')} - {sr.get('max')} {cur} ({sr.get('interval') or ''})".strip()
    return {
        "ats": "lever",
        "title": d.get("text"),
        "location": (d.get("categories") or {}).get("location"),
        "remote": (d.get("workplaceType")),
        "posted": posted or created,
        "salary": salary,
        "body": strip_html(d.get("description")) + "\n\n" + lists,
    }


def fetch_smartrecruiters(url):
    m = re.search(r"smartrecruiters\.com/([^/]+)/(\d+)", url)
    if not m:
        return None
    api = f"https://api.smartrecruiters.com/v1/companies/{m.group(1)}/postings/{m.group(2)}"
    d = get(api).json()
    sections = (d.get("jobAd") or {}).get("sections") or {}
    body = "\n\n".join(
        f"{v.get('title', k)}\n{strip_html(v.get('text'))}"
        for k, v in sections.items() if isinstance(v, dict))
    loc = d.get("location") or {}
    return {
        "ats": "smartrecruiters",
        "title": d.get("name"),
        "location": ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")])),
        "remote": loc.get("remote"),
        "posted": d.get("releasedDate"),
        "salary": None,
        "body": body,
    }


FETCHERS = (fetch_ashby, fetch_workday, fetch_greenhouse, fetch_lever, fetch_smartrecruiters)


def fetch(url):
    for fn in FETCHERS:
        try:
            out = fn(url)
        except Exception as exc:                      # noqa: BLE001
            return {"error": f"{fn.__name__}: {type(exc).__name__}: {exc}"}
        if out is not None:
            return out
    return {"error": "no fetcher matched this URL. Supported: Ashby, Workday, "
                     "Greenhouse, Lever, SmartRecruiters. Comeet/Pinpoint/Rippling "
                     "have no per-posting JSON endpoint; use WebSearch for those."}


def render(url, rec, limit):
    print("=" * 78)
    print(url)
    if rec.get("error"):
        print(f"  FAILED: {rec['error']}")
        return False
    print(f"  ATS      : {rec.get('ats')}")
    print(f"  TITLE    : {rec.get('title')}")
    print(f"  LOCATION : {rec.get('location')}   remote={rec.get('remote')}")
    print(f"  POSTED   : {rec.get('posted')}")
    print(f"  SALARY   : {rec.get('salary')}")
    body = rec.get("body") or ""
    print(f"  LENGTH   : {len(body)} chars")
    print("-" * 78)
    print(body[:limit] if limit else body)
    if limit and len(body) > limit:
        print(f"\n[truncated at {limit} chars; --chars 0 for the full text]")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="*", help="apply URLs")
    ap.add_argument("--from-hits", help="an ats_hits_<date>.json to pull URLs from")
    ap.add_argument("--match", action="append", default=[],
                    help="with --from-hits: only titles containing this (repeatable)")
    ap.add_argument("--chars", type=int, default=9000,
                    help="truncate each description (0 = unlimited, default 9000)")
    args = ap.parse_args()

    urls = list(args.urls)
    if args.from_hits:
        with open(args.from_hits, encoding="utf-8") as f:
            hits = json.load(f)
        pool = (hits.get("matched") or []) + (hits.get("borderline") or [])
        for e in pool:
            title = e.get("title") or ""
            if not args.match or any(m.lower() in title.lower() for m in args.match):
                if e.get("apply_url"):
                    urls.append(e["apply_url"])

    if not urls:
        ap.error("no URLs given (pass URLs, or --from-hits with --match)")

    seen, ok, failed = set(), 0, 0
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        if render(u, fetch(u), args.chars):
            ok += 1
        else:
            failed += 1
    print("=" * 78)
    print(f"fetched {ok}, failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
