"""SAP SuccessFactors Recruiting Marketing (RMK) board adapter -- shared module.

Added 2026-09-18 from the 2026-09-11 provider sweep, which found four backlog
companies (Avanos Medical, CRH, Gainwell Technologies, Wipro) all running SF's
Recruiting Marketing career sites on per-company hosts (jobs.<company>.com or
careers.<company>.com), confirmed by `rmkcdn.successfactors.com` /
`career41.sapsf.com` references on their public careers pages. See
`docs/ats_contract.md` section 2, model 3 ("hand-enrolled only"): the identifier
is a compound, per-company HOST (`sf_host`), never derivable from a company name
the way a Greenhouse/Ashby/Lever slug is, so `harvest_ats.py` can never sweep for
these; a board is added by hand once its host is found (a careers-page link, or
the `rmkcdn.successfactors.com` / `sapsf.com` fingerprint on the company's own
site), the same posture as Paylocity's GUID.

READ PATH (verified live 2026-09-18 against all four sweep companies). The
background note assumed a single shape: a server-rendered `/search/?q=&
startrow=N` page, 25/page, "Results 1-25 of N". That assumption is WRONG for
every live board checked -- SF's current "Unify" career-site template renders
search results with a client-side React widget (`reactWidgetLoader.js`) that
calls `api4.successfactors.com` from the browser; the server-rendered
`/search/` HTML carries zero job cards. A plain GET (no browser) therefore
cannot read the search page at all, on any of the four companies.

The robust, script-reachable read path turned out to be `/sitemap.xml`, which
every board serves in one of two shapes -- and NOT by company choice; it is
apparently a per-tenant template setting, since three of the four sweep
companies serve one shape and the fourth serves the other:

  "rss"     A complete Google-for-Jobs feed: <rss><channel><item> per posting,
            carrying <title>, <description> (full JD HTML), <link> (the
            canonical apply/detail URL), <g:location>, <g:id>. ONE request
            reads the whole board with real per-posting locations already
            resolved -- no per-job fetch needed. Seen live on CRH (854 items).
  "urlset"  A bare Google sitemap: <url><loc> per posting, no title/location/
            description at all -- just the URL and a lastmod (crawl date, not
            posting date, so it is not used as `posted`). Seen live on Avanos
            (55 items) and Wipro (5290 items). Resolving title/location here
            costs one GET per posting (see `resolve_board`'s urlset branch),
            which is a materially different cost profile from every other
            adapter in this pipeline -- see SUCCESSFACTORS_URLSET_DETAIL_CAP.

Both shapes are handled by `parse_feed`; `resolve_board` is the one function
that walks either shape to a bounded, capped `postings` list, and it is the
single parser shared by the poller (`poll_ats.fetch_successfactors`) and
discovery (`harvest_ats.probe_successfactors`), per the contract's "scrapers
share one parser" rule (section 2). `fetch_jd_successfactors` (used by
fetch_jd.py) shares `parse_detail_page`, the same per-job-page parser the
urlset branch uses, so a Step-3 JD pull and a urlset-shape poll can't drift.

NO CIRCULAR IMPORT: this module imports only `re`, `requests`, `time`, and the
stdlib XML parser. `poll_ats.py`, `harvest_ats.py`, and `fetch_jd.py` each
import THIS module; this module never imports any of them. harvest_ats.py's
probe passes in its own budgeted `_raw_get`/`_pace`-backed callable rather than
this module reaching into harvest internals, which is also what keeps a
company's re-check able to honor `Budget` without this module knowing what a
Budget is (duck-typed: anything with `.expired()` works, and `budget=None`
means unbounded, same convention as harvest_ats.Budget itself).

KNOWN LIMITATIONS (report these, don't paper over them):
  - No reliable per-posting POSTED date on either shape. The urlset `lastmod`
    is a sitemap-regeneration date (Avanos and Wipro both stamp EVERY entry
    with the same day, live-verified 2026-09-18), not a real posting date, so
    it is not read. CRH's feed has `g:expiration_date` (when the posting will
    stop advertising) but nothing for when it started. `extract_posted_date`
    therefore always returns None for this ATS -- same "no data -> don't
    filter" treatment as Pinpoint and Rippling get in poll_ats.py.
  - No salary field on either shape.
  - The urlset per-job-detail walk is capped far lower than
    SUCCESSFACTORS_MAX_POSTINGS (see SUCCESSFACTORS_URLSET_DETAIL_CAP) because
    it costs one HTTP request per posting rather than one request per ~20-100
    postings the way every paginated adapter in this file does. A urlset-shape
    board larger than the cap (Wipro: 5290) is read only up to the cap; this is
    a real, documented under-read, not a bug -- see the constant's docstring.
"""
import re
import time
from html import unescape
from xml.etree import ElementTree as ET

import requests

REQUEST_TIMEOUT = 30  # seconds; mirrors poll_ats.REQUEST_TIMEOUT

# Pagination cap for the "rss" feed shape (CRH-style): the whole board arrives
# in ONE response, so this only bounds how many entries we keep in memory/
# process, mirroring the defensive intent of SMARTRECRUITERS_MAX_POSTINGS even
# though there is no second request to cap here. Shared by the poller and the
# probe so discovery judges the same board the poller will read (contract
# section 3's "the cap is a named constant, and the probe and the poller use
# the same cap").
SUCCESSFACTORS_MAX_POSTINGS = 1000

# Pagination cap for the "urlset" feed shape (Avanos/Wipro-style): resolving a
# posting's title/location here costs one full HTTP GET of its detail page,
# because the sitemap gives nothing but the URL. That is a fundamentally more
# expensive read than every other adapter in this pipeline (Workday: 20/
# request; SmartRecruiters/Rippling: 100 and 20/request); reading Wipro's full
# 5290-entry board at one request each, every day, is not a reasonable poll
# cost. Kept as its own constant rather than reusing
# SUCCESSFACTORS_MAX_POSTINGS specifically so the two shapes' costs are never
# silently conflated. 60 is a deliberate, modest starting cap -- raise it (with
# a measured request-count/latency tradeoff, the way WORKDAY_MAX_POSTINGS was
# raised 200->1000 off a measured 46-board census) once this adapter has run
# for real and the actual miss rate on capped urlset boards is known.
SUCCESSFACTORS_URLSET_DETAIL_CAP = 60

# Courtesy delay between requests in the POLLER's own walk (poll_ats.py has no
# shared pacing layer -- see contract section 5 -- but the urlset branch can
# issue dozens of sequential requests to one host, which no other adapter in
# this file does at this granularity, so this fetcher paces itself rather than
# relying on a layer that does not exist here).
SF_POLL_COURTESY_DELAY = 0.15

SF_UA = "Mozilla/5.0 (resume-pipeline; SuccessFactors adapter)"

# Sentinel a caller's `get_fn` may return in place of a response, meaning "the
# host rate-limited this request and the retry (if any) also failed -- the
# answer is unknown, not no-board." harvest_ats.py's THROTTLED is a distinct
# object; probe_successfactors() translates between the two so this module
# never has to import harvest_ats.
THROTTLED = object()

# A bare /sitemap.xml exists on a huge number of unrelated sites (it is a
# standard SEO convention), so HTTP 200 there is not proof of an SF board --
# see the contract's "no board is decided on evidence the API actually gives"
# rule. Require the fingerprint the platform's own CDN/API leaves in genuine
# RMK output.
RMK_SIGNATURE_MARKERS = ("successfactors", "rmkcdn", "sapsf")

_JOB_PATH_RE = re.compile(r"/job/[^/]+/[\w-]+/?(?:$|\?)", re.I)
_OG_TITLE_RE = re.compile(r'<meta\s+property="og:title"\s+content="([^"]*)"', re.I)
_TITLE_TAG_RE = re.compile(r"<title>(.*?)</title>", re.I | re.S)
_CANONICAL_RE = re.compile(r'<link\s+rel="canonical"\s+href="([^"]*)"', re.I)
_JOBPOSTING_ITEMTYPE_RE = re.compile(r'itemtype="http://schema\.org/JobPosting"', re.I)


def looks_like_rmk_feed(text: str) -> bool:
    """True if `text` (the body fetched at /sitemap.xml) is an SF RMK feed.

    Two independent signals, either is sufficient: (1) the platform's own CDN/
    API host appears somewhere in the document -- present on every live sample
    seen 2026-09-18 (Avanos, Wipro, Gainwell all reference `rmkcdn.
    successfactors.com`; CRH's feed names no CDN but is checked by signal 2);
    (2) every <loc>/<link> in the document follows the /job/<slug>/<id>/ path
    convention, which is specific enough that a generic e-commerce or blog
    sitemap will not accidentally satisfy it.
    """
    head = text[:4000]
    if "<rss" not in head and "<urlset" not in head:
        return False
    lowered = text.lower()
    if any(m in lowered for m in RMK_SIGNATURE_MARKERS):
        return True
    urls = re.findall(r"<(?:loc|link)>([^<]+)</(?:loc|link)>", text)
    return bool(urls) and all(_JOB_PATH_RE.search(u) for u in urls[: min(20, len(urls))])


def _local(tag: str) -> str:
    """Strip a `{namespace}` prefix off an ElementTree tag name."""
    return tag.rsplit("}", 1)[-1]


def _strip_location_suffix(title: str, location: str) -> str:
    """Drop a trailing "(<location>)" from an RSS <title> when it duplicates
    <g:location> word-for-word (CRH: "Contracts Administrator (Lunenburg, MA,
    US, 01462)" alongside a <g:location> of "Lunenburg, MA, US, 01462"). Only
    strips an EXACT case-insensitive match, so a title that legitimately ends
    in parentheses for another reason ("Field Tech (Contract)") is untouched.
    """
    if not title or not location:
        return title
    suffix = f"({location})"
    if title.lower().endswith(suffix.lower()):
        return title[: -len(suffix)].strip()
    return title


def _parse_rss_item(item_el) -> dict:
    title = location = link = job_id = description = None
    for child in item_el:
        name = _local(child.tag)
        text = child.text or ""
        if name == "title":
            title = unescape(text.strip())
        elif name == "link":
            link = text.strip()
        elif name == "location":  # g:location
            location = unescape(text.strip())
        elif name == "id":  # g:id
            job_id = text.strip()
        elif name == "description":
            description = _strip_html(unescape(text))
    title = _strip_location_suffix(title or "", location or "")
    return {
        "title": title or "",
        "location": location or "Unknown",
        "url": link or "",
        "id": job_id or "",
        "description": description or "",
    }


def _strip_html(raw: str) -> str:
    """Minimal HTML->text for the RSS feed's <description> CDATA block.

    Not fetch_jd.py's strip_html (that module cannot be imported here without
    creating a cross-import this adapter does not need) -- deliberately small,
    since this only has to flatten the feed's own JD HTML enough for the
    industry-exclusion keyword scan in poll_ats.py to see real words.
    """
    if not raw:
        return ""
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    t = re.sub(r"<(br|/p|/div|/li)\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def parse_feed(text: str):
    """Parse an SF /sitemap.xml body into (shape, items).

    shape is "rss" (Google-for-Jobs feed, items carry title/location/url/id/
    description already resolved) or "urlset" (bare URL list, items carry only
    `url`; caller must resolve title/location per posting, see
    `parse_detail_page`). Returns (None, None) if `text` does not parse as XML
    or its root is neither shape -- "not proof of a board," per the probe
    contract (section 2).
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None, None
    tag = _local(root.tag)
    if tag == "rss":
        items = []
        for el in root.iter():
            if _local(el.tag) == "item":
                items.append(_parse_rss_item(el))
        return "rss", items
    if tag == "urlset":
        items = []
        for url_el in root:
            if _local(url_el.tag) != "url":
                continue
            loc = None
            for child in url_el:
                if _local(child.tag) == "loc":
                    loc = (child.text or "").strip()
            if loc:
                items.append({"url": loc})
        return "urlset", items
    return None, None


def parse_detail_page(html: str, fallback_url: str = "") -> dict | None:
    """title/location/apply-url from an SF job detail page.

    Shared by the urlset-shape poll branch (one fetch per posting) and
    fetch_jd_successfactors (Step 3 JD retrieval), so both read the page the
    same way. Every live sample (Avanos, Wipro, Gainwell) renders these two
    fields identically regardless of template skin:

      `<meta property="og:title" content="<Title> - <Location>">`  -- the
        clean form, no site chrome.
      `<link rel="canonical" href=".../job/<slug>/<reqid>-en_US/">`  -- the
        STABLE detail/apply URL. This can differ from the numeric-ID URL a
        sitemap lists (Avanos: sitemap gives .../1425822800/, canonical gives
        .../7257-en_US/); the canonical form is what's returned as the apply
        URL, on the theory that it is the one SF itself considers permanent.

    Falls back to the plain `<title>` tag ("<Title> - <Location> Job Details |
    <companyId>") when og:title is absent, stripping the " Job Details | ..."
    suffix. Returns None if neither is present, or if the page does not carry
    the `schema.org/JobPosting` microdata wrapper every live sample had --
    that second check is what stops a same-shaped-URL page on some unrelated
    site from being silently accepted as a posting.
    """
    if not _JOBPOSTING_ITEMTYPE_RE.search(html):
        return None
    m = _OG_TITLE_RE.search(html)
    raw = unescape(m.group(1)) if m else None
    if not raw:
        m = _TITLE_TAG_RE.search(html)
        if not m:
            return None
        raw = unescape(m.group(1))
        raw = re.sub(r"\s+Job Details\s*\|.*$", "", raw).strip()
    if not raw:
        return None
    if " - " in raw:
        title, location = raw.rsplit(" - ", 1)
    else:
        title, location = raw, "Unknown"
    m = _CANONICAL_RE.search(html)
    apply_url = unescape(m.group(1)) if m else fallback_url
    return {"title": title.strip(), "location": location.strip() or "Unknown",
            "url": apply_url or fallback_url}


def resolve_board(host: str, get_fn, budget=None,
                  max_postings: int = SUCCESSFACTORS_MAX_POSTINGS,
                  urlset_detail_cap: int = SUCCESSFACTORS_URLSET_DETAIL_CAP):
    """Walk a SuccessFactors board at `host` to a bounded postings list.

    `get_fn(url)` is injected so this one walk serves both callers without a
    circular import (contract section 1's Endpoint/Poller-fetch split, done
    here as dependency injection instead): the poller passes a plain
    `requests.get` wrapper, harvest_ats.py's probe passes its own budgeted
    `_raw_get` so the walk honors `Budget` and per-service pacing without this
    module importing harvest internals. `get_fn` must return a response-like
    object (`.status_code`, `.text`), `None` on network failure, or the
    `THROTTLED` sentinel above.

    Returns a 3-tuple `(status, postings, total)`:
      ("ok", [...], total)    board resolved. `total` is the number of entries
                              the feed itself reports (len(items) BEFORE
                              capping) -- the number a pagination proof checks
                              a capped read against. `postings` may be `[]`
                              for a real, confirmed-empty board.
      ("no_board", None, None)   no /sitemap.xml, or it isn't RMK-shaped.
      ("throttled", None, None)  a request was rate-limited; unknown, not no-board.
    """
    url = f"https://{host}/sitemap.xml"
    r = get_fn(url)
    if r is THROTTLED:
        return "throttled", None, None
    if r is None or getattr(r, "status_code", None) != 200:
        return "no_board", None, None
    text = r.text
    if not looks_like_rmk_feed(text):
        return "no_board", None, None
    shape, items = parse_feed(text)
    if shape is None:
        return "no_board", None, None
    total = len(items)
    if shape == "rss":
        postings = [{"title": it["title"], "location": it["location"],
                     "url": it["url"], "id": it["id"],
                     "description": it["description"]}
                    for it in items[:max_postings]]
        return "ok", postings, total
    # urlset: one GET per posting to resolve title/location, capped well below
    # max_postings -- see SUCCESSFACTORS_URLSET_DETAIL_CAP.
    postings = []
    for entry in items[:urlset_detail_cap]:
        if budget is not None and budget.expired():
            break
        dr = get_fn(entry["url"])
        if dr is THROTTLED:
            return "throttled", None, None
        if dr is None or getattr(dr, "status_code", None) != 200:
            continue  # one dead link in a sitemap does not fail the whole board
        parsed = parse_detail_page(dr.text, entry["url"])
        if parsed:
            parsed["id"] = ""
            parsed["description"] = ""
            postings.append(parsed)
    return "ok", postings, total


def fetch_successfactors(company: dict) -> list[dict]:
    """Poller-facing fetch: `company` carries `sf_host` (see
    watchlist_companies.json -> _successfactors_notes). Returns postings in the
    shape poll_ats.poll_all's shared loop expects, or the `_error` sentinel.
    """
    host = (company.get("sf_host") or "").strip()
    if not host:
        return [{"_error": "SuccessFactors entry missing sf_host"}]

    def _get(url):
        time.sleep(SF_POLL_COURTESY_DELAY)
        return requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": SF_UA})

    try:
        status, postings, _total = resolve_board(host, _get)
    except Exception as e:
        return [{"_error": f"{type(e).__name__}: {e}"}]
    if status != "ok":
        return [{"_error": f"SuccessFactors: no RMK board found at {host} "
                           f"(sitemap.xml missing, unreachable, or not RMK-shaped)"}]
    out = []
    for p in postings:
        out.append({
            "title": p.get("title", ""),
            "_sf_location": p.get("location") or "Unknown",
            "_apply_url": p.get("url", ""),
            "description": p.get("description", ""),
            "id": p.get("id", ""),
        })
    return out


# ── Step 3 JD retrieval (shared with fetch_jd.py) ────────────────────────────
# Host-agnostic on purpose, same reasoning as fetch_jd.py's Paylocity matcher:
# SF hosts are per-company (jobs.<company>.com, careers.<company>.com, or a
# bare custom domain), so nothing about the hostname is a usable signal. The
# path convention (/job/<slug>/<reqid-or-numeric-id>/) is the only constant
# across companies, and parse_detail_page's schema.org/JobPosting check is
# what keeps a coincidentally-shaped URL on an unrelated site from being
# accepted.
SF_JOB_URL_RE = re.compile(r"https?://[^/]+/job/[^/]+/[\w-]+/?(?:\?.*)?$", re.I)


def fetch_jd_successfactors(url: str, get=None) -> dict | None:
    """fetch_jd.py's per-ATS fetcher: None if `url` isn't an SF detail page,
    else {ats, title, location, remote, posted, salary, body}.

    `get` is injected (defaults to a plain `requests.get`) so fetch_jd.py can
    pass its own 45s-timeout, browser-UA `get()` and share this parser rather
    than duplicating the request logic.
    """
    if not SF_JOB_URL_RE.match(url):
        return None
    get = get or (lambda u: requests.get(
        u, timeout=REQUEST_TIMEOUT, headers={"User-Agent": SF_UA}))
    resp = get(url)
    html = resp.text
    parsed = parse_detail_page(html, url)
    if not parsed:
        return {"ats": "successfactors",
                "error": f"{url} does not look like an SF job detail page "
                         f"(no schema.org/JobPosting markup, or page shape changed)"}
    # Full JD body: every itemprop="description" span in document order, same
    # convention as the RSS branch's flattened description. A posting can
    # render its content across more than one such span (Avanos: a leading
    # "Requisition ID: NNNN" span, then the real body in a second one).
    body_parts = re.findall(r'itemprop="description"[^>]*>(.*?)</span>',
                            html, re.S | re.I)
    body = "\n\n".join(_strip_html(unescape(p)) for p in body_parts if p.strip()).strip()
    return {
        "ats": "successfactors",
        "title": parsed["title"],
        "location": parsed["location"],
        "remote": None,
        "posted": None,  # no reliable per-posting date on either feed shape; see module docstring
        "salary": None,  # not exposed on either feed shape
        "body": body,
    }
