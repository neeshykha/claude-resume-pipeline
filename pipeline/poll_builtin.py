#!/usr/bin/env python3
"""Daily discovery feeder: BuiltIn's COMPANY directory -> enrollment queue.

Usage:
    .venv/bin/python pipeline/poll_builtin.py                 # dry run
    .venv/bin/python pipeline/poll_builtin.py --apply         # append to pending
    .venv/bin/python pipeline/poll_builtin.py --slice atlanta-51-500 --max-pages 4
    .venv/bin/python pipeline/poll_builtin.py --all-pages     # ignore the cursor, walk a slice whole

WHY THIS EXISTS (2026-09-03)
----------------------------
`_websearch_sources` already carried "BuiltIn Atlanta" and "BuiltIn Remote", but both
dork `site:builtin.com/job` for individual ROLES. A role is perishable and reaches the
pipeline once; a COMPANY, once enrolled, gets its whole roster polled daily forever.
That is the same argument Step 1d-2 makes for harvesting companies rather than roles out
of LinkedIn, and Step 1c makes for rotating the dorks. BuiltIn happens to publish the
company directory those dorks were scraping around, so this feeder reads it directly.

Measured against the alternative on 2026-09-03: the WebSearch dork channel produced 46 new
companies over 121 source-runs (~9 source-runs per enrollment, Step 1c). One BuiltIn
directory page is 20 companies for one request, and of the 20 on Atlanta page 1, nine were
checked by hand and seven came back UNKNOWN.

WHAT THE PAGE ACTUALLY GIVES YOU, AND WHAT IT DOES NOT
-------------------------------------------------------
The directory is server-rendered and URL-addressable, so a plain `requests` GET is enough
-- no headless browser. Verified 2026-09-03: 377KB of HTML, no `__NEXT_DATA__`, company
names present in the raw bytes.

Present in that HTML, per card:
    name, /company/<slug>, data-company-id, industry tags,
    "N Offices" with the office list in the tooltip's data-bs-title,
    "N Employees", and a "Hiring Now" badge.

NOT present: the open-positions-by-function breakdown ("8 Open Positions: Customer Success
& Experience (5) - Operations & Support (1) ..."). That is the single most useful field
here, and in the served HTML it is an empty `.job-sections-skeleton` div. Alpine fills it
after load from a same-page Razor handler, batching five companies per request:

    GET <slice url>?handler=JobSectionsEncoded&data=<payload>
    payload = base64(encodeURIComponent(JSON.stringify(
                  [{id, alias, section, featured}, ...]  # <=5, sorted by id asc
              )))

`encodeURIComponent` is not `quote()`: it leaves !'()*-._~ unescaped, which SAFE below
reproduces. The response is an HTML fragment of `.job-section-item[data-company-id]`
blocks, so results map back to companies by id rather than by position. Verified working
from plain Python on 2026-09-03.

FILTERS ARE PATH SEGMENTS, NOT QUERY PARAMS
-------------------------------------------
`?hiring=true` and `?fully_remote=true` are silently ignored -- they come back echoed as
empty in the page's own filter state, and return the unfiltered list. The real forms are
path segments: `/hiring/open-jobs`, `/location/fully-remote`, `/size/<band>/<band>`
(bands stack). Only location stays a query param (`?city=&state=&country=`). Each page
echoes the filters it actually applied into an inline `'filters':{...}` tracking blob,
which `verify_slice()` reads back so a silently-dropped filter is caught rather than
quietly widening the walk.

`/hiring/open-jobs` is the one that pays for itself, since a company with no open roles
cannot produce a lead this run anyway (measured 2026-09-03, by max page number):

    Atlanta 51-500, all filters off .......  36 pages (~720 companies)
    Atlanta 51-500, /hiring/open-jobs .....  12 pages (~240)
    US 51-500, /hiring/open-jobs .......... 500 pages (~10,000; a display cap, not a count)
    US 51-500, hiring + fully-remote ......  27 pages (~540)
    US 501-1000, hiring + fully-remote ....   3 pages (~60)

The national slice is only tractable BECAUSE of fully-remote. Without it the directory is
effectively unbounded and would need its own sampling strategy.

COST CONTROL: A PAGE CURSOR, NOT A FULL WALK
--------------------------------------------
The configured slices are ~42 pages at ~380KB each. Walking all of it daily would be ~16MB
of HTML for a channel whose whole premise is that its finds do not decay -- the same
mistake Step 1c made by running 16 dorks every day until the rotation replaced it. So each
slice carries a persisted `next_page` cursor in `builtin_state.json`, and a run walks
`PAGES_PER_RUN` pages per slice and advances; the cursor wraps to page 1 at the end of a
slice, recording `cycles`. Full coverage lands every ~3-4 days, which is the same tradeoff
Step 1c settled on for the same reason.

DEDUPE BEFORE THE FUNCTION LOOKUP, NOT AFTER
--------------------------------------------
Dedupe is a local dict lookup; the function breakdown is a network round trip per five
companies. So known companies are dropped FIRST and the handler is only ever called for
names that could actually become leads. On a settled watchlist that is most of the page.
Dedupe goes through `check_company.lookup()`, the same surface the CLI reports on -- which
means the blind-spot and unpollable-backlog blocks count as known, so this feeder cannot
re-queue a company that a manual rotation already covers.

EVERY LEAD IS NAME-ONLY
-----------------------
BuiltIn hosts its own apply flow and does not expose the source ATS. Verified on
/company/rethinkfirst/jobs, 2026-09-03: zero outbound greenhouse/lever/ashby/workday
links. So leads are queued with `needs_ats_resolution: true` and nothing else, exactly
like the LinkedIn ones, and `harvest_ats.py --from-pending` resolves the board later.
Do not add an ATS-extraction step here; there is nothing to extract.
"""
import argparse
import base64
import datetime as dt
import html
import json
import os
import re
import subprocess
import sys
from urllib.parse import quote

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import harvest_ats as H  # noqa: E402  (shared UA, per-service pacing, _raw_get)
from check_company import lookup, norm  # noqa: E402

WATCHLIST = os.path.join(SCRIPT_DIR, "watchlist_companies.json")
QUEUE = os.path.join(SCRIPT_DIR, "enrollment_candidates.json")
STATE = os.path.join(SCRIPT_DIR, "builtin_state.json")
VALIDATE = os.path.join(SCRIPT_DIR, "validate_config.py")

SOURCE_LABEL = "BuiltIn directory"
# Step 1d-2 caps LinkedIn at 15 for the same reason: a feeder that can queue a whole
# page is a feeder that can bury the manual-review signal in the next digest. Do not
# raise this to "clear the backlog."
#
# The cap and the cursor interact, and the interaction is deliberate: the cursor
# advances past pages whose leads the cap deferred, so a deferred company is not
# queued NEXT run, it is queued when its slice comes back around (Atlanta ~3 runs at
# the default, remote-51-500 ~7, remote-501-1000 every run). That is only acceptable
# because these are companies rather than perishable reqs -- the same reasoning Step
# 1c uses for rotating the dorks on a ~3-day cycle. Deferred names are printed every
# run so the backlog is never silent. Expect the cap to bind on every run for the
# first week or so and then stop, as the queue warms up and unknown counts fall.
MAX_NEW_PER_RUN = 15
PAGES_PER_RUN = 4          # per slice; 3 slices -> ~12 page fetches per run
CARDS_PER_PAGE = 20        # BuiltIn's own page size, used only for reporting
JOB_SECTIONS_BATCH = 5     # the handler's batch size, set by BuiltIn's own JS

# JS encodeURIComponent leaves exactly these unescaped. Python's quote() defaults to
# safe="/", which would produce a payload the handler rejects.
_URI_SAFE = "!'()*-._~"

# The functions Aneesh's target roles live under, in BuiltIn's own taxonomy. These are
# BuiltIn's category names, not tier names -- the tier judgement happens later, against
# the real JD, once the company is enrolled and the poller sees its actual titles.
TARGET_FUNCTIONS = ("Customer Success & Experience", "Operations & Support")


# ── Slices ───────────────────────────────────────────────────────────────────
# `path` segments carry the filters; `query` carries location only. Keep /hiring/
# open-jobs on every slice: an unfiltered slice is 3x the pages for companies that
# cannot yield a lead today anyway.
SLICES = {
    "atlanta-51-500": {
        "path": "/companies/hiring/open-jobs/size/51-200/201-500",
        "query": "city=Atlanta&state=Georgia&country=USA",
        "label": "Atlanta, 51-500 employees, hiring",
        "expect": {"open_jobs": "true", "size": "51-200,201-500",
                   "geo_location": "Atlanta, Georgia, USA"},
    },
    "remote-51-500": {
        "path": "/companies/hiring/open-jobs/location/fully-remote/size/51-200/201-500",
        "query": "",
        "label": "US fully-remote, 51-500 employees, hiring",
        "expect": {"open_jobs": "true", "fully_remote": "true",
                   "size": "51-200,201-500"},
    },
    "remote-501-1000": {
        "path": "/companies/hiring/open-jobs/location/fully-remote/size/501-1000",
        "query": "",
        "label": "US fully-remote, 501-1000 employees, hiring",
        "expect": {"open_jobs": "true", "fully_remote": "true", "size": "501-1000"},
    },
}
BASE = "https://builtin.com"


def slice_url(spec: dict, page: int) -> str:
    parts = [p for p in (spec["query"], f"page={page}" if page > 1 else "") if p]
    return BASE + spec["path"] + ("?" + "&".join(parts) if parts else "")


# ── Card parsing ─────────────────────────────────────────────────────────────
# One card per `x-data="CompanyCardHorizontal"`. Splitting on that marker rather than
# regexing the whole page keeps each field's match inside its own card, so a company
# with no office tooltip cannot borrow the next company's.
_CARD_SPLIT = re.compile(r'x-data="CompanyCardHorizontal"')
_NAME = re.compile(r'aria-label="View (.+?) company profile"')
_SLUG = re.compile(r'href="/company/([a-z0-9][a-z0-9-]*)"')
_CID = re.compile(r'data-company-id="(\d+)"')
_EMPLOYEES = re.compile(r">\s*([\d,]+)\+?\s*Employees\s*<")
# A card states its location one of two ways, and only the first has a tooltip:
#   multi-office : <span ... data-bs-title="New York&lt;br/&gt;Atlanta">2 Offices</span>
#   single       : <span ...>Fully Remote</span>   (or a bare city)
# Reading only the tooltip form silently loses the location for every single-office
# company, which on the fully-remote slices is MOST of them -- the `why` line then
# fell back to naming the slice and read "offices US fully-remote, 51-500 employees".
_OFFICES = re.compile(r'data-bs-title="([^"]*)"[^>]*>\s*\d+\s+Offices?\s*<')
_OFFICE_ONE = re.compile(r'fa-map-marker-alt[^>]*></i>\s*<span[^>]*>([^<]{2,80})</span>')
_INDUSTRIES = re.compile(r'class="font-barlow fw-medium text-gray-04[^"]*">([^<]*)</div>')
_HIRING = re.compile(r">\s*Hiring Now\s*<")
_FILTERS = re.compile(r"'filters':\{(.*?)\}", re.S)
_PAGE_LINK = re.compile(r'href="/companies[^"]*[?&]page=(\d+)"')


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()


def _offices(chunk: str, tooltip) -> list[str]:
    """Office list for one card, from whichever of the two forms it uses."""
    if tooltip:
        return [o for o in (_clean(x) for x in
                            re.split(r"<br\s*/?>", html.unescape(tooltip.group(1)))) if o]
    single = _OFFICE_ONE.search(chunk)
    if single:
        label = _clean(single.group(1))
        # Guard the degenerate case: if the tooltip regex ever stops matching, the
        # single-office regex would happily return the literal "3 Offices".
        if label and not re.fullmatch(r"\d+\s+Offices?", label, re.I):
            return [label]
    return []


def parse_cards(page_html: str) -> list[dict]:
    """Every company card on one directory page."""
    cards = []
    for chunk in _CARD_SPLIT.split(page_html)[1:]:
        slug = _SLUG.search(chunk)
        cid = _CID.search(chunk)
        name = _NAME.search(chunk)
        if not (slug and cid):
            continue
        offices = _OFFICES.search(chunk)
        emp = _EMPLOYEES.search(chunk)
        ind = _INDUSTRIES.search(chunk)
        cards.append({
            "name": _clean(name.group(1)) if name else _clean(slug.group(1)),
            "slug": slug.group(1),
            "company_id": int(cid.group(1)),
            "employees": _clean(emp.group(1)).replace(",", "") if emp else "",
            "offices": _offices(chunk, offices),
            "industries": [i for i in (_clean(x) for x in
                                       _clean(ind.group(1)).split("•"))
                           if i] if ind else [],
            "hiring_now": bool(_HIRING.search(chunk)),
        })
    return cards


def max_page(page_html: str) -> int:
    pages = [int(p) for p in _PAGE_LINK.findall(html.unescape(page_html))]
    return max(pages) if pages else 1


def applied_filters(page_html: str) -> dict:
    """The filters the SERVER says it applied, from the page's own tracking blob.

    Read back rather than trusted: `?hiring=true` looks like it works (200, a full
    page of companies) while echoing `'hiring':''`. Any future filter typo would
    fail exactly that way -- silently, by widening the walk.
    """
    m = _FILTERS.search(page_html)
    if not m:
        return {}
    return {k: v for k, v in re.findall(r"'([\w-]+)':'([^']*)'", m.group(1))}


def verify_slice(spec: dict, page_html: str) -> list[str]:
    got = applied_filters(page_html)
    return [f"{k}: expected {v!r}, page applied {got.get(k, '')!r}"
            for k, v in spec.get("expect", {}).items() if got.get(k, "") != v]


# ── Open-positions-by-function (the JobSectionsEncoded handler) ──────────────

_SECTION_ITEM = re.compile(
    r'class="[^"]*job-section-item[^"]*"[^>]*data-company-id="(\d+)"', re.I)
_SECTION_ITEM_ALT = re.compile(
    r'data-company-id="(\d+)"[^>]*class="[^"]*job-section-item[^"]*"', re.I)
_OPEN_COUNT = re.compile(r"(\d+)\s+Open Positions?", re.I)
_FUNC = re.compile(r"([A-Za-z][\w&,'\- ]*?)\s*\((\d+)\)")


def _encode_batch(batch: list[dict]) -> str:
    payload = json.dumps(sorted(batch, key=lambda e: e["id"]), separators=(",", ":"))
    return base64.b64encode(quote(payload, safe=_URI_SAFE).encode()).decode()


def _split_fragment(fragment: str) -> dict[int, str]:
    """Handler response -> {company_id: visible text of that company's section}."""
    marks = sorted({(m.start(), int(m.group(1)))
                    for pat in (_SECTION_ITEM, _SECTION_ITEM_ALT)
                    for m in pat.finditer(fragment)})
    out = {}
    for i, (start, cid) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(fragment)
        out[cid] = _clean(re.sub(r"<[^>]+>", " ", fragment[start:end]))
    return out


def parse_sections(text: str) -> dict:
    """One company's section text -> {'total': int, 'functions': {name: count}}."""
    total = _OPEN_COUNT.search(text)
    funcs = {}
    for m in _FUNC.finditer(text):
        label = _clean(m.group(1)).lstrip("• ").strip(" :-•")
        # "8 Open Positions" itself is not a function; the count regex eats the
        # digits but the label would otherwise pick up the trailing prose.
        if not label or label.lower().endswith("open positions"):
            continue
        funcs[label] = int(m.group(2))
    return {"total": int(total.group(1)) if total else 0, "functions": funcs}


def fetch_sections(spec: dict, cards: list[dict], verbose=True) -> dict[int, dict]:
    """Open-positions breakdown for `cards`, batched the way BuiltIn's own JS batches."""
    out: dict[int, dict] = {}
    url_base = BASE + spec["path"]
    for i in range(0, len(cards), JOB_SECTIONS_BATCH):
        batch = cards[i:i + JOB_SECTIONS_BATCH]
        data = _encode_batch([{"id": c["company_id"],
                               "alias": f"/company/{c['slug']}",
                               "section": "all", "featured": "false"} for c in batch])
        r = H._raw_get(f"{url_base}?handler=JobSectionsEncoded&data={quote(data, safe='')}")
        if r is None or r.status_code != 200:
            if verbose:
                status = "network failure" if r is None else r.status_code
                print(f"    job-sections batch {i // JOB_SECTIONS_BATCH + 1}: {status}"
                      f" -- {len(batch)} companies left unresolved")
            continue
        for cid, text in _split_fragment(r.text).items():
            out[cid] = parse_sections(text)
    return out


def qualifying(sections: dict) -> dict[str, int]:
    """The TARGET_FUNCTIONS this company is hiring in, with counts."""
    return {f: n for f, n in (sections or {}).get("functions", {}).items()
            if f in TARGET_FUNCTIONS and n > 0}


def hidden_roles(sections: dict) -> int:
    """Open roles the breakdown did not attribute to any function it showed.

    THE BREAKDOWN IS TRUNCATED AT FOUR FUNCTIONS, descending by count. Measured on
    Atlanta page 1, 2026-09-03: 6 of 20 companies listed fewer roles than their own
    total, worst case Banyan Software at 44 open with 30 attributed. So a company
    hiring ONE Customer Success role behind four larger functions is invisible to
    this filter, and the miss is biased toward big, fast-hiring, engineering-heavy
    companies -- exactly where a single support-ops opening is easiest to overlook
    and least likely to be the fourth-largest function.

    There is no cheap way to recover the rest. /company/<slug>/jobs is
    client-rendered (checked: 139KB, zero job data in the HTML), and BuiltIn's
    category-filtered JOB directory returns ~10 companies a page, mostly ones
    already on the watchlist -- worse yield per request than the directory itself.

    So a truncated non-match is reported as AMBIGUOUS rather than counted as a
    clean rejection, and `--include-ambiguous` queues those too when recall matters
    more than queue noise. Untreated, this would be a silent recall hole; the run
    line makes its size visible every time.
    """
    s = sections or {}
    return max(0, s.get("total", 0) - sum(s.get("functions", {}).values()))


# ── State ────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if not os.path.exists(STATE):
        return {"slices": {}}
    with open(STATE, encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")
    os.replace(tmp, STATE)


# ── Queue ────────────────────────────────────────────────────────────────────

def build_lead(card: dict, funcs: dict[str, int], sections: dict, spec: dict,
               today: dt.date) -> dict:
    # Truncated: a global agency can list 26 offices (Ogilvy, seen 2026-09-03) and
    # the whole list would swamp the one line a human reads in the digest.
    offices = card["offices"]
    where = (", ".join(offices[:4]) + (f" +{len(offices) - 4} more" if len(offices) > 4
                                       else "")) or spec["label"]
    size = f"{card['employees']} employees" if card["employees"] else "headcount unlisted"
    if funcs:
        why_fn = "incl. " + ", ".join(f"{f} ({n})" for f, n in sorted(funcs.items()))
    else:
        why_fn = (f"function breakdown truncated ({hidden_roles(sections)} of "
                  f"{sections.get('total', 0)} unattributed); target function unconfirmed")
    lead = {
        "name": card["name"],
        "ats": None,
        "slug": None,
        "source": SOURCE_LABEL,
        "first_seen": today.isoformat(),
        "why": (f"BuiltIn directory [{spec['label']}]: {size}; offices {where}; "
                f"{sections.get('total', 0)} open positions {why_fn}; "
                f"builtin.com/company/{card['slug']}"),
        "needs_ats_resolution": True,
    }
    if not funcs:
        lead["ambiguous_function_match"] = True
    lead["_target_roles"] = sum(funcs.values())   # ranking only; stripped before queueing
    return lead


def write_pending(entries: list[dict]) -> int:
    with open(QUEUE, encoding="utf-8") as f:
        q = json.load(f)
    have = {norm(e.get("name", "")) for e in q.get("pending", [])}
    added = 0
    for e in entries:
        if norm(e["name"]) in have:
            continue
        q.setdefault("pending", []).append(e)
        have.add(norm(e["name"]))
        added += 1
    tmp = QUEUE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(q, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, QUEUE)
    return added


# ── Orchestration ────────────────────────────────────────────────────────────

def run_slice(key: str, spec: dict, state: dict, wl: dict, enrollment: dict,
              today: dt.date, pages: int, all_pages: bool, seen: set,
              verbose: bool, include_ambiguous: bool) -> dict:
    st = state.setdefault("slices", {}).setdefault(
        key, {"next_page": 1, "cycles": 0, "last_run": None, "max_page": None})
    start = 1 if all_pages else st.get("next_page", 1)

    print(f"\n[{key}] {spec['label']}")
    leads, counters = [], {"pages": 0, "cards": 0, "unknown": 0, "qualified": 0,
                           "ambiguous": 0, "no_sections": 0, "filter_warnings": [],
                           "ambiguous_names": []}
    page, last = start, None
    while True:
        if not all_pages and counters["pages"] >= pages:
            break
        r = H._raw_get(slice_url(spec, page))
        if r is None or r.status_code != 200:
            print(f"  page {page}: {'network failure' if r is None else r.status_code}"
                  f" -- stopping this slice")
            break
        counters["pages"] += 1
        if last is None:
            last = max_page(r.text)
            st["max_page"] = last
            problems = verify_slice(spec, r.text)
            counters["filter_warnings"] = problems
            for p in problems:
                print(f"  FILTER NOT APPLIED -- {p}")
        cards = parse_cards(r.text)
        counters["cards"] += len(cards)
        if not cards:
            print(f"  page {page}: 0 cards (past the end)")
            page = 1
            st["cycles"] = st.get("cycles", 0) + 1
            break

        # Dedupe BEFORE the function lookup: local dict vs. a network round trip.
        fresh = []
        for c in cards:
            if norm(c["name"]) in seen:
                continue
            seen.add(norm(c["name"]))
            if not lookup(c["name"], wl, enrollment):
                fresh.append(c)
        counters["unknown"] += len(fresh)

        sections = fetch_sections(spec, fresh, verbose=verbose) if fresh else {}
        page_qualified = page_ambiguous = 0
        for c in fresh:
            s = sections.get(c["company_id"])
            if s is None:
                counters["no_sections"] += 1
                continue
            funcs = qualifying(s)
            if funcs:
                counters["qualified"] += 1
                page_qualified += 1
                if verbose:
                    print(f"    + {c['name']:34s} {c['employees'] or '?':>5} emp | "
                          + ", ".join(f"{f} ({n})" for f, n in sorted(funcs.items())))
            elif hidden_roles(s):
                # Truncated at four functions, so "no target function" is unproven
                # rather than false. See hidden_roles().
                counters["ambiguous"] += 1
                page_ambiguous += 1
                counters["ambiguous_names"].append(
                    f"{c['name']} ({hidden_roles(s)} of {s['total']} unattributed)")
                if not include_ambiguous:
                    continue
                if verbose:
                    print(f"    ? {c['name']:34s} {c['employees'] or '?':>5} emp | "
                          f"{hidden_roles(s)} of {s['total']} roles unattributed")
            else:
                continue
            leads.append(build_lead(c, funcs, s, spec, today))

        print(f"  page {page}/{last}: {len(cards)} cards, {len(fresh)} unknown, "
              f"{page_qualified} qualified, {page_ambiguous} ambiguous")
        page = page + 1 if page < (last or page) else 1
        if page == 1:
            st["cycles"] = st.get("cycles", 0) + 1
            break

    if not all_pages:
        st["next_page"] = page
        st["last_run"] = today.isoformat()
    counters["leads"] = leads
    counters["resume_at"] = page
    return counters


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true",
                    help="append qualifying UNKNOWN companies to pending")
    ap.add_argument("--slice", action="append", choices=sorted(SLICES),
                    help="run only this slice (repeatable); default is all")
    ap.add_argument("--max-pages", type=int, default=PAGES_PER_RUN,
                    help=f"pages per slice this run (default {PAGES_PER_RUN})")
    ap.add_argument("--all-pages", action="store_true",
                    help="walk each slice from page 1 to its end, ignoring the cursor "
                         "and leaving it untouched. Interactive use only.")
    ap.add_argument("--include-ambiguous", action="store_true",
                    help="also queue companies whose breakdown is truncated past the "
                         "four functions BuiltIn shows, so a target function cannot be "
                         "ruled out. Recall over precision; see hidden_roles().")
    ap.add_argument("--date", help="run date (YYYY-MM-DD); default today")
    ap.add_argument("--quiet", action="store_true", help="skip the per-company lines")
    args = ap.parse_args()

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    keys = args.slice or list(SLICES)

    with open(WATCHLIST, encoding="utf-8") as f:
        wl = json.load(f)
    with open(QUEUE, encoding="utf-8") as f:
        enrollment = json.load(f)
    state = load_state()

    all_leads, warnings, ambiguous_names = [], [], []
    seen: set[str] = set()
    totals = {"pages": 0, "cards": 0, "unknown": 0, "qualified": 0, "ambiguous": 0,
              "no_sections": 0}
    for key in keys:
        c = run_slice(key, SLICES[key], state, wl, enrollment, today,
                      args.max_pages, args.all_pages, seen, not args.quiet,
                      args.include_ambiguous)
        all_leads += c.pop("leads")
        warnings += [f"{key}: {w}" for w in c["filter_warnings"]]
        ambiguous_names += c["ambiguous_names"]
        for k in totals:
            totals[k] += c[k]

    # Rank before capping, so the 15 that survive are the strongest rather than
    # whichever pages happened to be walked first: confirmed target-function
    # matches ahead of ambiguous ones, then by how many target roles are open.
    # This matters on a cold queue, where nearly every card is unknown and the cap
    # binds on every run.
    all_leads.sort(key=lambda e: (e.get("ambiguous_function_match", False),
                                  -e.get("_target_roles", 0), e["name"].lower()))
    for e in all_leads:
        e.pop("_target_roles", None)
    capped = all_leads[:MAX_NEW_PER_RUN]
    deferred = all_leads[MAX_NEW_PER_RUN:]

    print(f"\npages={totals['pages']} cards={totals['cards']} "
          f"unknown={totals['unknown']} qualified={totals['qualified']} "
          f"ambiguous={totals['ambiguous']} "
          f"new_leads={len(capped)} cap_deferred={len(deferred)}")
    if ambiguous_names:
        verb = "queued" if args.include_ambiguous else "NOT queued"
        print(f"ambiguous ({verb}) -- breakdown truncated at 4 functions, so a target "
              f"function could not be ruled out:")
        for a in ambiguous_names:
            print("  ? " + a)
    if totals["no_sections"]:
        print(f"{totals['no_sections']} unknown companies had no job-sections response "
              f"(dropped, not queued -- they resurface on the next cycle)")
    if deferred:
        print("deferred by the per-run cap:", ", ".join(e["name"] for e in deferred))
    if warnings:
        print("FILTER WARNINGS (the walk may be wider than configured):")
        for w in warnings:
            print("  " + w)
    for key in keys:
        st = state.get("slices", {}).get(key, {})
        print(f"  cursor[{key}] -> page {st.get('next_page', 1)}"
              f" of {st.get('max_page', '?')} (cycles {st.get('cycles', 0)})")

    if not args.apply:
        print("\ndry run; re-run with --apply to append to pending "
              "(the page cursor is not advanced either)")
        return 0

    save_state(state)
    added = write_pending(capped)
    print(f"\nappended {added} leads to enrollment_candidates.json -> pending")
    rc = subprocess.run([sys.executable, VALIDATE, "--quiet"]).returncode
    if rc != 0:
        print(f"validate_config.py exited {rc}; inspect enrollment_candidates.json",
              file=sys.stderr)
        return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
