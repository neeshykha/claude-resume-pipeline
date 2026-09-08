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
  Paylocity  https://{host}/Recruiting/Jobs/Details/{id}
             (no API at all; the detail page is server-rendered HTML and is
             scraped directly. See fetch_paylocity.)
  Workable   https://apply.workable.com/api/v1/accounts/{account}/jobs/{shortcode}
             (Description and Requirements are SEPARATE fields, and comp is
             often prose inside `benefits`. See fetch_workable.)
  UKG Pro    https://{tenant}.rec.pro.ukg.net/{code}/JobBoard/{board}/OpportunityDetail
             (Knockout page, but the server renders the whole opportunity object
             inline; carries a pay range even when hidden from the posting, and
             two different posting dates. See fetch_ukg.)

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
import os
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
        # first_published FIRST, matching poll_ats.extract_posted_date. Fixed
        # 2026-08-25: this used to prefer updated_at, and most large Greenhouse
        # boards bulk-refresh every req daily, so updated_at is almost always
        # "today". That produced phantom "the poller's date is wrong" reports
        # whenever a JD read was compared against the shortlist — Snorkel AI
        # (first_published 2026-07-31, updated_at 2026-08-24) and Sprout Social
        # (2026-07-23 vs 2026-08-24) both got flagged as ~30-day drift when the
        # poller was reading the correct field the whole time. Posting AGE is
        # the question this field answers, so first publication is the right
        # answer and updated_at is only a fallback.
        "posted": d.get("first_published") or d.get("updated_at"),
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


UKG_RE = re.compile(
    r"https?://([A-Za-z0-9-]+)\.rec\.pro\.ukg\.net/([A-Za-z0-9]+)/JobBoard/"
    r"([0-9a-f-]{36})/OpportunityDetail", re.I)


def _balanced_obj(text, from_idx):
    """Return the JSON object starting at the first '{' at or after from_idx.

    Same reasoning as fetch_paylocity's bracket-balancing: Description strings
    carry braces and escaped quotes, so a regex cannot find the end of the
    object. Counts depth while skipping over string literals and escapes.
    """
    start = text.find("{", from_idx)
    if start == -1:
        return None
    depth, i, in_str, esc = 0, start, False, False
    while i < len(text):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    return None


def fetch_ukg(url):
    """UKG Pro Recruiting (`*.rec.pro.ukg.net`), by reading the page's own payload.

    Added 2026-09-08 from a user-surfaced role (TASI Measurement / Mission
    Communications, Customer Experience and Technical Support Manager). The page
    LOOKS client-rendered -- it is Knockout, and `<title data-bind="text: title()">`
    is empty in the raw HTML, which is exactly the shape that gets an ATS written
    off as needing a browser. It is not: the server renders the COMPLETE
    opportunity object inline into a `US.Opportunity.CandidateOpportunityDetail({...})`
    call, so a plain GET has everything. The board listing page does the same thing
    through `US.Opportunity.OpportunitiesViewModel(...)`, which means this ATS is
    pollable too, not merely readable. Generalize the Comeet lesson: an empty
    rendered page is not evidence about the payload behind it.

    THREE FIELDS THAT WILL MISLEAD IF READ NAIVELY, all found on the first live req:

    - **`PayRange` is populated even when `PayRangeVisible` is false.** TASI's req
      renders no salary anywhere on the page and carries
      `PayRangeMinimum 100000 / PayRangeMaximum 145000` in the payload. Scoring
      should use it, since a real disclosed range beats treating the role as
      salary-neutral. Do not quote an undisclosed range back to the employer.
    - **`PostedDate` is requisition CREATION, not publication.** TASI reads
      2026-06-03 there and `JobBoardMemberships[].ExternalPostedDate` 2026-07-22:
      97 days versus 48. The external date is the one that answers "how long has a
      candidate been able to see this", and it is the field MAX_POSTING_AGE_DAYS
      should be measured against. Same class as the Greenhouse
      `first_published`-vs-`updated_at` trap, in the opposite direction.
    - **`JobLocationType`** carries the on-site/remote answer (0 = on-site on the
      reqs seen so far) and the address lives in `Locations[].Address`, so location
      never has to be guessed from a display string.

    `OpportunityIsClosed` distinguishes a filled req from a live one.
    """
    m = UKG_RE.search(url)
    if not m:
        return None
    raw = get(url).text
    anchor = raw.find("CandidateOpportunityDetail(")
    if anchor == -1:
        return {"ats": "ukg", "error":
                "no CandidateOpportunityDetail payload on the page "
                "(wrong opportunityId, or the req was removed)"}
    blob = _balanced_obj(raw, anchor)
    if blob is None:
        return {"ats": "ukg", "error": "CandidateOpportunityDetail object never closed"}
    d = json.loads(blob)

    loc = (d.get("Locations") or [{}])[0]
    addr = loc.get("Address") or {}
    state = (addr.get("State") or {}).get("Code")
    where = ", ".join(filter(None, [addr.get("City"), state,
                                    (addr.get("Country") or {}).get("Code")]))

    memberships = d.get("JobBoardMemberships") or [{}]
    external = memberships[0].get("ExternalPostedDate")
    created = d.get("PostedDate")

    pay = d.get("PayRange") or {}
    salary = None
    if pay.get("PayRangeMinimum") or pay.get("PayRangeMaximum"):
        cur = d.get("PayRangeCurrencyCode") or ""
        hidden = "" if d.get("PayRangeVisible") else "  [NOT shown on the posting]"
        salary = (f"{pay.get('PayRangeMinimum')} - {pay.get('PayRangeMaximum')} "
                  f"{cur}{hidden}").strip()

    notes = []
    if d.get("OpportunityIsClosed"):
        notes.append("REQ IS CLOSED")
    if created and external and created[:10] != external[:10]:
        notes.append(f"requisition created {created[:10]}, "
                     f"published externally {external[:10]} -- age from the latter")
    if d.get("TravelDescription"):
        notes.append(f"travel: {d['TravelDescription']}")
    if d.get("JobLocationType") == 0:
        notes.append("JobLocationType=0 (on-site)")

    body = strip_html(d.get("Description"))
    if notes:
        body = "===== FETCHER NOTES =====\n" + "\n".join(f" - {n}" for n in notes) + "\n\n" + body

    return {
        "ats": "ukg",
        "title": d.get("Title"),
        "location": where or loc.get("LocalizedName"),
        "remote": "on-site" if d.get("JobLocationType") == 0 else d.get("JobLocationType"),
        "posted": (external or created or "")[:10] or None,
        "salary": salary,
        "body": body,
    }


def fetch_workable(url):
    """Workable, via the public per-posting account API.

    Added 2026-09-08 from a user-surfaced role (Seeq, Technical Account Manager).
    This was the same shape of gap Paylocity had until 2026-09-03: poll_ats.py has
    read Workable boards since 2026-07-27 and harvest_ats.py probes Workable slugs,
    so a Workable req could reach the shortlist while Step 3 had nothing to read it
    with and fell back to WebFetch.

    `https://apply.workable.com/api/v1/accounts/<account>/jobs/<shortcode>` returns
    the posting as JSON with no auth. Two things make it worth having:

    - **Description and Requirements are SEPARATE fields**, and the requirements
      block is where the years-of-experience bar lives. A Description-only read
      returns a JD with no requirements in it, silently, looking complete -- the
      exact defect fetch_paylocity was built to avoid on tenants that split the
      posting the same way.
    - **Compensation is often prose inside `benefits`, not a structured field.**
      Seeq states "$130,000 USD" in a perks list. poll_ats treats Workable hits as
      salary-neutral, so the number only exists here; `benefits` is therefore
      appended to the body rather than dropped.

    `remote` is a real boolean and `location` is a dict, unlike Ashby's isRemote,
    which lies in both directions. The account slug comes from the URL path, so a
    tenant that renames itself 404s loudly rather than resolving to someone else.
    """
    m = re.search(r"apply\.workable\.com/([^/]+)/j/([0-9A-Za-z]+)", url)
    if not m:
        return None
    account, shortcode = m.group(1), m.group(2)
    api = f"https://apply.workable.com/api/v1/accounts/{account}/jobs/{shortcode}"
    d = get(api).json()
    body = "\n\n".join(
        f"===== {k.upper()} =====\n{strip_html(d.get(k))}"
        for k in ("description", "requirements", "benefits") if d.get(k))
    loc = d.get("location") or {}
    where = ", ".join(filter(None, [loc.get("city"), loc.get("region"),
                                    loc.get("country")]))
    return {
        "ats": "workable",
        "title": d.get("title"),
        "location": where or None,
        "remote": d.get("workplace") or d.get("remote"),
        "posted": (d.get("published") or "")[:10] or None,
        "salary": d.get("salary"),
        "body": body,
    }


def fetch_comeet(url):
    """Comeet, via the same public board API poll_ats.py already speaks.

    Added 2026-08-31, correcting a claim this file made from the start. The
    Comeet *hosted page* really is a Spark Hire template (see the module
    docstring), and that was generalized into "Comeet has no per-posting JSON
    endpoint" here and in daily_task_prompt.md Step 3. That is wrong: Comeet's
    BOARD endpoint returns every posting with a `details` array holding the
    full Description / Requirements HTML -- the same whole-board-filter-locally
    shape as Ashby.

    The cost of the wrong claim was concrete. On 2026-08-31 Stampli's
    "Implementation Consultant/Onboarding Specialist" took the top pre-score of
    the run (74) and was written off as unreadable, so nobody saw that it pays
    $80-95K base (under the $100K floor AND the $90K near-miss floor) and sits
    in the Mountain View office three days a week. It was a hard-filter
    elimination wearing a near-miss label.

    Comeet has no slug-derivable credentials: the API needs the company `uid`
    and a public widget `token`. The uid IS in the URL
    (comeet.com/jobs/<slug>/<uid>/...), and the token is stored on the
    watchlist entry at enrollment time, so resolve the pair from there.
    """
    m = re.search(r"comeet\.com/jobs/([^/]+)/([^/]+)/", url)
    if not m:
        return None
    slug, uid = m.group(1), m.group(2)
    wl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "watchlist_companies.json")
    with open(wl_path) as fh:
        wl = json.load(fh)
    entry = next((c for c in wl.get("companies", [])
                  if c.get("ats") == "comeet"
                  and (c.get("comeet_uid") == uid or c.get("slug") == slug)), None)
    if not entry or not entry.get("comeet_token"):
        return {"ats": "comeet", "title": None, "location": None, "remote": None,
                "posted": None, "salary": None,
                "body": f"Comeet needs a widget token, and no watchlist entry was found "
                        f"for uid={uid} / slug={slug}. Enroll the company (which stores "
                        f"comeet_uid + comeet_token) and retry."}
    # Same endpoint shape as ATS_ENDPOINTS["comeet"] in watchlist_companies.json;
    # `details=true` is what returns the Description / Requirements HTML.
    api = (f"https://www.comeet.co/careers-api/2.0/company/{uid}/positions"
           f"?token={entry['comeet_token']}&details=true")
    jobs = get(api).json()
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    job = next((j for j in jobs
                if tail in str(j.get("url_comeet_hosted_page", ""))
                or tail == str(j.get("uid", ""))), None)
    if job is None:
        return {"error": f"comeet: no posting on {slug}'s board matched {tail}"}
    loc = job.get("location") or {}
    body = "\n\n".join(
        f"### {d.get('name')}\n{strip_html(d.get('value'))}"
        for d in (job.get("details") or []) if isinstance(d, dict))
    return {
        "ats": "comeet",
        "title": job.get("name"),
        "location": ", ".join(filter(None, [loc.get("city"), loc.get("state")])) or loc.get("name"),
        # Reported for visibility, NOT trusted: this field was true on 19/19
        # Stampli postings including ones that state in-office days. Same
        # constant-field problem as Ashby isRemote and Paylocity IsRemote.
        # poll_ats.py ignores it; read the body for the real policy.
        "remote": f"{loc.get('is_remote')} (UNRELIABLE, read the body)",
        "posted": job.get("time_updated"),
        "salary": None,
        "body": body,
    }


# --- Paylocity -------------------------------------------------------------
# Two host forms, matching poll_ats.fetch_paylocity and _paylocity_notes: the
# shared `recruiting.paylocity.com` (Paylocity's customers, the common case) and
# a tenant-prefixed `<id>recruiting.paylocity.com` (Paylocity itself is 2000).
# The prefix is glued to the label with no dot, so the host label is
# `<something>recruiting`, not `<something>.recruiting`.
PAYLOCITY_DETAIL = re.compile(
    r"https?://([A-Za-z0-9-]*recruiting)\.paylocity\.com"
    r"/Recruiting/Jobs/Details/(\d+)", re.I)
PAYLOCITY_MARKETING = re.compile(
    r"https?://(?:www\.)?paylocity\.com/company/careers/", re.I)
# A segment of the bullet-separated header line that states a work arrangement
# rather than a place. The line is NOT positional: Paylocity's own board renders
# "Fully Remote / Remote, US / Operations" while Momentus renders
# "Fully Remote / Brisbane, Queensland, AUS" with no department at all, so
# reading by index mislabels the policy as the location and drops the city.
PAYLOCITY_POLICY = re.compile(
    r"^(fully\s+remote|remote|hybrid|on[-\s]?site|in[-\s]?office|"
    r"work\s+from\s+home|telecommute|flexible)\b", re.I)
_PAYLOCITY_BOARD_CACHE = {}


def _balanced_div(text, from_idx):
    """Inner HTML of the first <div> at or after from_idx, nesting-aware.

    Paylocity's description block is a bare <div> holding arbitrary posting
    markup, so a non-greedy `<div>(.*?)</div>` truncates at the first nested
    close. Same reasoning as poll_ats.fetch_paylocity bracket-balancing the
    Jobs array instead of regexing it.
    """
    open_re = re.compile(r"<div\b[^>]*>", re.I)
    tok_re = re.compile(r"<div\b[^>]*>|</div\s*>", re.I)
    m = open_re.search(text, from_idx)
    if not m:
        return ""
    depth, pos, end = 1, m.end(), len(text)
    while depth:
        t = tok_re.search(text, pos)
        if not t:
            break
        depth += 1 if t.group(0)[1] != "/" else -1
        pos = t.end()
        if depth == 0:
            end = t.start()
    return text[m.end():end]


def _paylocity_published(host, guid, job_id):
    """PublishedDate for one req, read off its own board listing.

    The detail page carries no posting date, but the board page server-renders
    the whole `"Jobs":[...]` array with a real ISO PublishedDate per req -- the
    same payload poll_ats.fetch_paylocity reads. The board GUID is on the detail
    page itself, in its "View All Jobs" link, so no watchlist lookup is needed
    and reqs at unenrolled tenants still resolve. Cached per board: a run that
    reads several reqs from one tenant pays for the listing once.

    Best-effort by design. A missing date is a neutral freshness signal, not a
    reason to fail a JD read.
    """
    key = (host, guid)
    if key not in _PAYLOCITY_BOARD_CACHE:
        jobs = []
        try:
            text = get(f"https://{host}/Recruiting/Jobs/All/{guid}").text
            anchor = text.find('"Jobs":[')
            if anchor != -1:
                start = anchor + len('"Jobs":')
                depth = 0
                for i in range(start, len(text)):
                    if text[i] == "[":
                        depth += 1
                    elif text[i] == "]":
                        depth -= 1
                        if depth == 0:
                            jobs = json.loads(text[start:i + 1])
                            break
        except Exception:                                 # noqa: BLE001
            jobs = []
        _PAYLOCITY_BOARD_CACHE[key] = {str(j.get("JobId")): j.get("PublishedDate")
                                       for j in jobs if isinstance(j, dict)}
    return _PAYLOCITY_BOARD_CACHE[key].get(str(job_id))


def _paylocity_salary(body):
    """Pull a pay range out of the description text.

    Salary lives nowhere structured on Paylocity -- not in the listing payload
    (which is why poll_ats treats every Paylocity hit as salary-neutral) and not
    in any field on the detail page. It is a sentence inside the posting, so it
    has to be read out of the prose. Prefer a range that follows a comp keyword
    so an unrelated dollar range in the body ("$50M ARR") does not win.
    """
    rng = re.compile(r"\$\s?[\d,]+(?:\.\d\d)?\s*(?:-|--|–|—|to)\s*"
                     r"\$?\s?[\d,]+(?:\.\d\d)?", re.I)
    kw = re.compile(r"base pay|pay range|salary range|base salary|compensation|"
                    r"hourly rate|pay for this", re.I)
    hits = list(rng.finditer(body))
    if not hits:
        return None
    for k in kw.finditer(body):
        for h in hits:
            if 0 <= h.start() - k.end() <= 220:
                return re.sub(r"\s+", " ", h.group(0)).strip()
    return re.sub(r"\s+", " ", hits[0].group(0)).strip()


def fetch_paylocity(url):
    """Paylocity Recruiting, scraped from the server-rendered detail page.

    Added 2026-09-03. poll_ats.py gained a Paylocity adapter on 2026-08-28, so
    Paylocity reqs have been reaching the shortlist since -- but this file had no
    branch for them and failed fast with "no fetcher matched this URL", which
    forced a WebFetch fallback for every Paylocity hit (Paylocity's own "Lead
    Technical Support Ops" req, 2026-09-03). WebFetch works here, unlike on
    Ashby/Workday/Comeet, because the page really is server-rendered -- but it
    spends a summarizing model on text a plain GET already returns verbatim, and
    Step 3 needs the requirements block VERBATIM.

    There is no JSON anywhere on the detail page: no embedded model, no
    ld+json, no itemprop. Everything comes out of the rendered markup:

      title     <span class="job-preview-title left"><span>...</span></span>
      location  <div class="preview-location">, bullet-separated, and NOT
                positional -- see PAYLOCITY_POLICY. Segments are classified by
                shape: the first work-arrangement-shaped one is the remote
                policy, the first of the rest is the location, and anything
                left over is the hiring department.
      body      EVERY <div class="job-listing-header">Label</div> plus the
                balanced <div> after it, in document order. Labels seen live:
                Description, Requirements, Job Type, Salary Description.

    Take every section rather than just Description. Momentus Technologies
    (recruiting.paylocity.com/.../4281459) splits the posting into Description
    AND a separate Requirements block, so a Description-only read returns a JD
    with no requirements in it at all -- silently, and looking complete. That is
    the exact failure Step 3 forbids, and it is invisible unless you compare
    against the page. Short one-line sections stay inline (`Job Type:
    Full-time`); long ones get a `### Label` heading.

    Note the remote flag here is the page's OWN rendered policy text, not the
    listing payload's `IsRemote` boolean that poll_ats.py deliberately ignores
    (it disagrees with LocationName in both directions). This one is the string
    a human reads on the posting, so it is trustworthy in a way IsRemote is not
    -- and the full policy paragraph is in the body regardless.

    A closed req is not a 404: the host 302s to /Recruiting/Jobs/JobNotFound and
    serves it with HTTP 200, so the redirect target is the only signal.

    The www.paylocity.com/company/careers/*.job.<id>/ URLs are NOT usable: they
    302 to a department index, not a posting. Matched here only to say so.
    """
    if PAYLOCITY_MARKETING.search(url):
        return {"ats": "paylocity", "error":
                "www.paylocity.com/company/careers/ URLs redirect to a department "
                "index, not a posting. Use the real host form: "
                "https://<tenant>recruiting.paylocity.com/Recruiting/Jobs/Details/<id>"}
    m = PAYLOCITY_DETAIL.search(url)
    if not m:
        return None
    host_label, job_id = m.group(1), m.group(2)
    host = f"{host_label}.paylocity.com"
    resp = get(f"https://{host}/Recruiting/Jobs/Details/{job_id}")
    if "JobNotFound" in resp.url:
        return {"ats": "paylocity", "error":
                f"req {job_id} is closed or was pulled ({host} redirected to "
                f"JobNotFound). Search indexes keep dead Paylocity reqs for a "
                f"long time, so this is the common case for an aging link."}
    page = resp.text

    title = None
    tm = re.search(r'class="job-preview-title[^"]*"\s*>(.*?)</span>\s*</span>',
                   page, re.S | re.I)
    if tm:
        title = strip_html(tm.group(1)) or None

    location, remote, department = None, None, None
    lm = re.search(r'<div class="preview-location"\s*>(.*?)</div>', page, re.S | re.I)
    if lm:
        for seg in [strip_html(p) for p in re.split(r"(?:&bull;|•)", lm.group(1))]:
            if not seg:
                continue
            if remote is None and PAYLOCITY_POLICY.match(seg):
                remote = seg
            elif location is None:
                location = seg
            elif department is None:
                department = seg
        # A remote-only header line ("Fully Remote" and nothing else) leaves the
        # location field empty; the policy text is the best answer available.
        location = location or remote

    sections, salary_label = [], None
    for hm in re.finditer(r'<div class="job-listing-header"\s*>(.*?)</div>',
                          page, re.S | re.I):
        label = strip_html(hm.group(1))
        value = strip_html(_balanced_div(page, hm.end()))
        if not label or not value:
            continue
        if "\n" in value or len(value) > 120:
            sections.append(f"### {label}\n\n{value}")
        else:
            sections.append(f"{label}: {value}")
            if salary_label is None and re.search(r"salary|pay|compensation",
                                                  label, re.I):
                salary_label = value
    if department:
        sections.insert(0, f"Department: {department}")
    if not sections:
        return {"ats": "paylocity", "error":
                f"no job-listing-header sections on {host}"
                f"/Recruiting/Jobs/Details/{job_id} (page shape changed)"}
    body = "\n\n".join(sections)

    guid = None
    gm = re.search(r"/Recruiting/Jobs/All/([0-9a-f-]{36})", page, re.I)
    if gm:
        guid = gm.group(1)
    return {
        "ats": "paylocity",
        "title": title,
        "location": location,
        "remote": remote,
        "posted": _paylocity_published(host, guid, job_id) if guid else None,
        "salary": salary_label or _paylocity_salary(body),
        "body": body,
    }


FETCHERS = (fetch_ashby, fetch_workday, fetch_greenhouse, fetch_lever,
            fetch_smartrecruiters, fetch_comeet, fetch_paylocity, fetch_workable,
            fetch_ukg)


def fetch(url):
    for fn in FETCHERS:
        try:
            out = fn(url)
        except Exception as exc:                      # noqa: BLE001
            return {"error": f"{fn.__name__}: {type(exc).__name__}: {exc}"}
        if out is not None:
            return out
    return {"error": "no fetcher matched this URL. Supported: Ashby, Workday, "
                     "Greenhouse, Lever, SmartRecruiters, Comeet, Paylocity, "
                     "Workable, UKG Pro Recruiting. Pinpoint/Rippling have no per-posting JSON "
                     "endpoint; use WebSearch for those."}


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
