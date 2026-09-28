#!/usr/bin/env python3
"""iCIMS ATS adapter: shared HTML parser + URL builder for poll_ats.py,
harvest_ats.py, and fetch_jd.py.

Added 2026-09-18, closing the GitHub/RealPage/Avalara/Peraton gap found in the
2026-09-11 provider sweep (`~/.claude/scheduled-tasks/horizon-builds/m5_work/
provider_sweep.json`, search `"provider": "icims"`).

DELIBERATE LEAF MODULE. This file imports nothing from `poll_ats.py` or
`harvest_ats.py`, and neither of those imports the other. `poll_ats.py` and
`harvest_ats.py` both import THIS module and call its parsing/URL functions
with their own request mechanics (plain `requests` + `REQUEST_TIMEOUT` for the
poller; budget-aware `_get`/`_pace` for the probe) -- see
`fetch_icims()` in poll_ats.py and the `icims` branch of `probe()` in
harvest_ats.py. That is how "scrapers share one parser" (ats_contract.md
section 2) is satisfied here without a circular import: JazzHR's probe branch
reaches this by doing `import poll_ats as _P` and reusing its regexes, which
this repo's own contract calls out as a thing worth avoiding when a new ATS
can just live in its own leaf module instead.

BOARD RESOLUTION -- WHAT WAS ACTUALLY VERIFIED LIVE (2026-09-18)
------------------------------------------------------------------
Host pattern: `careers-<tenant>.icims.com`, classic server-rendered HTML at
`/jobs/search?pr=<page>&in_iframe=1&searchRelation=keyword_all` (0-indexed
page param, "pr"), and a job detail page at `/jobs/<id>/<title-slug>/job`.

NO-BOARD DETECTION IS A CLEAN 404, NOT A BODY-SNIFF (unlike JazzHR, which
never 404s and instead serves a fixed "Inactive Career Page" at HTTP 200 for
every dead slug). Tested six bogus tenants against the live host --
`zzqxnotreal`, `totallyfakecompanyxyz123`, `microsoftinc`, and three more,
both with and without the `careers-` prefix -- and every one answered HTTP 404
with a body titled "gone: <host> : dc<n>". Every one of the four real tenants
below answered HTTP 200. That is a reliable discriminator, so iCIMS IS added
to the cheap slug walk (`CHEAP_ATSES` in harvest_ats.py) rather than treated
like Comeet/Paylocity's non-derivable identifiers -- the doubt the build brief
raised going in ("decide based on evidence whether a nonexistent tenant can be
told apart from a real one") resolves in iCIMS's favor.

Real tenants confirmed live, and what verifying them actually took (the build
brief's warning that GitHub/Avalara were "detected only through an iCIMS
privacy link" was correct and mattered):

  - Peraton   careers-peraton.icims.com            -- direct, classic HTML,
              1526 live reqs across 31 pages @ 50/page. Used as the live-test
              board for pagination (section 3 below) because it is the only
              one of the four large enough to prove capped pagination against.
  - RealPage  careers-realpagepms.icims.com         -- direct, classic HTML,
              ~75 reqs across 2 pages. Tenant is NOT derivable from the company
              name by slug_variants() (`realpage`, `realpage-llc`, etc. all
              404; the real tenant appends "pms", RealPage's product suite
              name, which no generic suffix list would guess). Used as the
              live-integration test board (section 8 item 1) because it is
              small and the classic HTML is simple to eyeball.
  - GitHub    careers-githubinc.icims.com           -- the tenant DOES
              resolve (HTTP 200, and it happens to be exactly the
              `base + "inc"` candidate slug_variants() already generates) but
              the classic search page immediately client-redirects
              (`window.top.location.href = 'https://www.github.careers/jobs'`)
              to a custom-skinned front end that does not serve the
              `iCIMS_JobsTable` markup this parser reads. GitHub is therefore
              a REAL iCIMS tenant this scraper cannot read, not a no-board
              case -- see `looks_like_redirect_skin()` below, which exists
              specifically so this shape reads as "unresolvable", not as a
              false "confirmed empty board". Excluded from the live test for
              this reason.
  - Avalara   careers.avalara.com (marketing site)   -- NOT used. The only
              iCIMS string anywhere on Avalara's own career page is the
              boilerplate `www.icims.com/legal/privacy-notice-website/` link
              every iCIMS customer's site carries; there is no
              `careers-*.icims.com` host linked anywhere, and the real apply
              flow is a different vendor entirely
              (`app.careerpuck.com/job-board/avalara`). The 2026-09-11
              provider sweep's "icims" signature for Avalara was a false
              positive from that boilerplate link, not evidence of a real
              board. Not treated as a confirmed iCIMS tenant on this evidence.

STRUCTURE IS TENANT-CUSTOMIZABLE, which is why the parser below reads fields
by their stable CSS-class shape rather than by position. Confirmed live on
Peraton vs. RealPage: both put location in the "header left" div's second
`<span>` (Peraton labels it "Job Locations", RealPage labels it plain
"Location" -- the label text is read only to gate the OTHER header field, see
below), but the "header right" div holds a posted-date timestamp on Peraton
and a bare requisition ID on RealPage. Reading "header right" positionally
would silently read RealPage's req ID as a posting date. `_posted_date_raw()`
therefore only trusts that field when its own `field-label` text contains
"post" (case-insensitive); every other tenant reads back None, which is the
correct "no data -> don't filter" answer per ats_contract.md section 6, not a
guess.

PAGINATION. `ICIMS_PAGE_SIZE = 50` (measured on both live boards: exactly 50
`iCIMS_JobCardItem` blocks on every full page). Page count is read once from
page 0's "Page 1 of N" header text (`icims_page_count()`); a page past the
last one answers 200 with zero job cards and no "Page X of Y" text at all
(verified: Peraton pr=31, one past its real last page pr=30, came back with 0
cards). Stop condition mirrors ats_contract.md section 3: page 0 deciding
no-board, a short/empty LATER page just ending the walk with what was read,
never flipping an already-resolved board back to "no board".

`ICIMS_MAX_POSTINGS = 500`. Chosen to match SmartRecruiters's cap rather than
Workday's 1000: Peraton alone carries 1526 live reqs, and a single huge iCIMS
board (a staffing/defense contractor, going by these four names) blowing the
whole per-company harvest budget is exactly the failure SmartRecruiters's cap
was set to avoid. At 50/page this reads 10 of Peraton's 31 pages before
capping -- enough to demonstrate real multi-page pagination live, cheaply.
"""
import html
import re

# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------

# Default template. Real callers pass the copy loaded from
# watchlist_companies.json -> _endpoints.icims (poll_ats.py via ATS_ENDPOINTS,
# harvest_ats.py via its own cached icims_endpoint() reader, same precedent as
# smartrecruiters_endpoint()/rippling_board_api_endpoint()) so there is one
# place to edit the URL shape. This constant is the fallback for direct callers
# (this module's own tests, verify scripts) and the seam a hang test overrides
# to point at a local socket instead of the real host -- see test_icims.py.
ICIMS_HOST_TMPL = ("https://careers-{slug}.icims.com/jobs/search"
                    "?pr={page}&in_iframe=1&searchRelation=keyword_all")

ICIMS_PAGE_SIZE = 50
ICIMS_MAX_POSTINGS = 500


def icims_search_url(tenant: str, page: int = 0, template: str | None = None) -> str:
    """The paginated job-search URL for one iCIMS tenant/page.

    `template` lets a caller override the host entirely (the hang-simulation
    test points this at 127.0.0.1) without touching ICIMS_HOST_TMPL globally.
    """
    return (template or ICIMS_HOST_TMPL).format(slug=tenant, page=page)


def icims_job_url(tenant: str, job_path: str) -> str:
    """Absolute URL for a job detail path already carrying its own /jobs/<id>/... shape."""
    if job_path.startswith("http"):
        return job_path
    return f"https://careers-{tenant}.icims.com{job_path}"


# ---------------------------------------------------------------------------
# Parsing -- shared by the poller's fetch and the harvest probe
# ---------------------------------------------------------------------------

# One <li> per posting on the classic listing page. Same split-then-search
# technique fetch_jazzhr/JAZZHR_ITEM_RE uses: split on the marker and search
# each resulting chunk for the fields, rather than trying to match a whole
# card non-greedily (which breaks the moment one HTML attribute's quoting
# style differs from another tenant's).
ICIMS_CARD_RE = re.compile(r'<li class="iCIMS_JobCardItem">', re.I)

# Title + URL. The anchor always carries href first, then class="iCIMS_Anchor";
# text of interest is in the immediately-following <h3>, not the anchor's own
# title="<reqid> - <title>" attribute (which duplicates the requisition ID
# into the string and is asking to be double-read wrong).
ICIMS_TITLE_RE = re.compile(
    r'<a\s+href="([^"]+)"[^>]*class="iCIMS_Anchor"[^>]*>.*?<h3[^>]*>\s*(.*?)\s*</h3>',
    re.I | re.S)

# Location: the "header left" div's own value span. The div always opens with
# a sr-only <span class="field-label">...</span> naming the field ("Location",
# "Job Locations", tenant-configurable) and then a BARE `<span >` (note the
# literal space before '>', which is what iCIMS's own template emits) carrying
# the value. Matching literally on `<span\s*>` rather than `<span[^>]*>` is
# what skips the labeled span without needing to parse its class attribute.
ICIMS_LOCATION_RE = re.compile(r'header\s+left">.*?<span\s*>\s*(.*?)\s*</span>', re.I | re.S)

# "header right" is NOT reliably a posted-date field -- see the module
# docstring's RealPage/Peraton comparison. Read the whole div, then gate on
# its own field-label text before trusting the value.
ICIMS_HEADER_RIGHT_RE = re.compile(r'header\s+right">(.*?)</div>', re.I | re.S)
ICIMS_FIELD_LABEL_RE = re.compile(r'field-label">([^<]*)</span>', re.I)
# The value span itself carries the parseable absolute timestamp in its
# title="" attribute ("9/18/2026 3:02 PM"); the visible text is a relative
# string ("18 minutes ago") that extract_posted_date has no use for.
ICIMS_DATED_SPAN_RE = re.compile(r'<span\s+title="([^"]+)"', re.I)

# "Page 1 of 31" in the results header. Absent on an out-of-range page and on
# a board with only one page's worth of postings (untested whether iCIMS omits
# it for a genuinely single-page board; RealPage's smallest board seen live
# still had 2 pages, so treat a missing match as "unknown page count", not as
# "single page", and rely on the short-page stop condition instead).
ICIMS_PAGE_COUNT_RE = re.compile(r'Page\s+\d+\s+of\s+(\d+)', re.I)

# GitHub's shape: a 200 that carries no job-search markup at all, just a
# client-side redirect off to a custom-skinned front end this parser cannot
# read. Detected so that shape can be told apart from a genuine empty board
# (see the module docstring).
#
# `window.top.location.href` ALONE IS NOT A SAFE SIGNAL -- caught live
# 2026-09-18 testing against Peraton and RealPage, both of which false-
# positived on the first version of this check. EVERY classic iCIMS page,
# including a completely normal 1526-job board, carries that exact string as
# part of its standard iframe-parameter-stripping boilerplate
# (`icimsWindow = window.top.location.href.indexOf(...)`, then
# `window.top.location.href = icims_stripIFrameParameter(windowUrl)`).
# GitHub's stub is a DIFFERENT shape: it assigns a literal external URL
# string (not a function-call result) and, more reliably, the page carries
# NONE of the classic template's own `iCIMS_JobsTable` container markup at
# all -- confirmed on a genuinely out-of-range page too (Peraton pr=31, zero
# job cards, `iCIMS_JobsTable` still present twice), so "board markup absent"
# is not something a normal empty/last page can trigger by accident. Both
# conditions are required so this can only fire on a page that is nothing but
# the redirect stub.
ICIMS_JOBS_TABLE_MARKER_RE = re.compile(r'iCIMS_JobsTable', re.I)
ICIMS_LITERAL_REDIRECT_RE = re.compile(
    r"window\.top\.location\.href\s*=\s*['\"]https?:", re.I)


def _icims_text(raw: str) -> str:
    """Tag-stripped, entity-decoded, whitespace-collapsed inner text."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw or ""))).strip()


def _posted_date_raw(card: str) -> str | None:
    """The card's raw posted-date string, or None if this tenant doesn't expose one.

    Only trusted when the "header right" field's own label mentions "post"
    (case-insensitive) -- see the module docstring for why a positional read
    is wrong here (RealPage puts a requisition ID in the same slot).
    """
    m = ICIMS_HEADER_RIGHT_RE.search(card)
    if not m:
        return None
    inner = m.group(1)
    label = ICIMS_FIELD_LABEL_RE.search(inner)
    if not label or "post" not in label.group(1).lower():
        return None
    dated = ICIMS_DATED_SPAN_RE.search(inner)
    return dated.group(1) if dated else None


def looks_like_redirect_skin(page_html: str) -> bool:
    """True for a 200 that is actually a client-side bounce to a non-classic front end.

    See the GitHub case in the module docstring for why this needs BOTH the
    missing board markup and a literal-URL redirect assignment, not just a
    `window.top.location.href` match -- that string alone appears on every
    normal classic iCIMS page as iframe-stripping boilerplate. Checked only on
    page 0 with zero cards parsed -- a real board's later pages never carry
    the literal-redirect shape at all.
    """
    page_html = page_html or ""
    return (not ICIMS_JOBS_TABLE_MARKER_RE.search(page_html)
            and bool(ICIMS_LITERAL_REDIRECT_RE.search(page_html)))


def parse_icims_page(page_html: str) -> list[dict]:
    """One listing page's HTML -> [{title, url, location, posted}, ...].

    `url` is the absolute job detail URL (already the apply-entry page, same
    convention as fetch_jazzhr/fetch_rippling/fetch_pinpoint's "url" field).
    `posted` is the raw "M/D/YYYY H:MM AM/PM" string or None; parsing it into
    a date is extract_posted_date's job in poll_ats.py, not this module's --
    this module has no opinion on date formats beyond extracting the string.
    """
    jobs = []
    for block in ICIMS_CARD_RE.split(page_html)[1:]:
        m = ICIMS_TITLE_RE.search(block)
        if not m:
            continue
        url, title = m.group(1), _icims_text(m.group(2))
        if not title:
            continue
        loc_m = ICIMS_LOCATION_RE.search(block)
        location = _icims_text(loc_m.group(1)) if loc_m else "Unknown"
        jobs.append({
            "title": title,
            "url": url,
            "location": location or "Unknown",
            "posted": _posted_date_raw(block),
        })
    return jobs


def icims_page_count(page_html: str) -> int | None:
    """Total page count from "Page X of N", or None if the marker is absent."""
    m = ICIMS_PAGE_COUNT_RE.search(page_html)
    return int(m.group(1)) if m else None


def posted_date_raw(html_fragment: str) -> str | None:
    """Public alias of _posted_date_raw, for fetch_jd.py's detail-page fetcher.

    The job DETAIL page (careers-{tenant}.icims.com/jobs/{id}/.../job) repeats
    the same "header left"/"header right" div shape the listing card uses --
    verified live on RealPage req 14575 -- so the same label-gated read applies
    unchanged; this just avoids a cross-module leading-underscore import.
    """
    return _posted_date_raw(html_fragment)
