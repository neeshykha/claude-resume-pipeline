# ATS provider contract

What a new ATS adapter has to implement to be a full citizen of this pipeline. Everything
here is read off the adapters that already exist (Workday, SmartRecruiters, Comeet, and
Paylocity, plus Pinpoint, Rippling, and JazzHR) as of 2026-09-11. It describes the
conventions as they stand. Where the code is inconsistent or silent, this doc says so
rather than inventing a rule.

> **Changed since this was written (2026-09-17, not yet folded into the sections below):**
> - Probes have a third answer, `THROTTLED`, for HTTP 429. A walk that finds nothing while any
>   probe was throttled is a `throttled` result (`unpollable: false`, `recheck_if_resurfaced:
>   true`), never `no_board`. Section 6's class table is missing this row. One retry per
>   request after `Retry-After` or 2 s, capped at 10 s and never past the budget.
> - The eight cheap slug ATSes run concurrently in `probe_cheap`, one thread each, with
>   answers read back in `CHEAP_ATSES` order so the collision rules in section 2 still hold.
>   Section 5's pacing description predates this.
> - Every probe request passes `(CONNECT_TIMEOUT, read)` = `(5, 20)`, shrunk to fit the
>   remaining budget, because a scalar timeout let one dead host with two A records cost 40 s.
> - Dotted slug variants (`unit21.ai`) are no longer sent to JazzHR, Pinpoint, or
>   SmartRecruiters.
>
> `daily_task_prompt.md` Step 1d has the full account of each.

## 1. Where an adapter lives

An ATS is supported only when every layer below knows about it. Nothing syncs these lists,
and every coverage gap so far has been exactly one layer missing. SmartRecruiters was polled
from 2026-06-30 but not discoverable until 2026-09-03; Comeet was polled from 2026-08-20 and
also discoverable only from 2026-09-03. In both cases the miss wrote real companies to
`rejected` with `unpollable: true`, which is the flag that stops them being re-checked.

| Layer | File | What it holds |
|---|---|---|
| Poller fetch | `poll_ats.py` `fetch_<ats>()` + a dispatch branch in `poll_all()` | the daily read of an enrolled board |
| Normalizers | `poll_ats.py` `parse_location`, `extract_posted_date`, `build_apply_url` | one branch each |
| Endpoint | `watchlist_companies.json` → `_endpoints` | URL template; `_init_config` loads every entry not starting with `POST` into `ATS_ENDPOINTS` |
| Notes | `watchlist_companies.json` → `_<ats>_notes` | how to find the identifier, known limits, the date and the case that prompted it |
| Validation | `validate_config.py` `SUPPORTED_ATS`, plus required extra fields | a missing entry fails validation and blocks the whole daily run |
| Discovery | `harvest_ats.py` `probe()` branch, or `probe_<ats>()` for non-slug models, plus its slot in `assess()` | name → board |
| JD fetch | `fetch_jd.py` `fetch_<ats>(url)` + the `FETCHERS` tuple + the unmatched-URL error text | Step 3 JD retrieval |
| Prune | `harvest_ats.prune()` | only for ATSes whose probe separates dead-404 from resolved-empty |

## 2. Board resolution

Three addressing models exist.

1. **Slug-addressed.** Greenhouse, Ashby, Lever, Workable, Pinpoint (subdomain), Rippling
   (path segment), JazzHR (subdomain), SmartRecruiters (case-insensitive concatenation). The
   identifier is derivable from the company name through `slug_variants()`, so `harvest_ats.py`
   resolves these automatically.
2. **Compound, scraped once at enrollment.** Workday needs `wd_host` (including the `wdN`
   datacenter), `wd_tenant`, and `wd_site`; `probe_workday` walks five hosts and a site-name
   list, and reads the status code (422 = no such tenant, stop; 404 = wrong site, keep
   walking; 200 = hit). Comeet needs `comeet_uid` + `comeet_token`, which exist only in the
   company's own careers page; `probe_comeet` walks name → guessed domain → careers page →
   scraped credentials → board. For both, the poller's fetcher takes the company dict rather
   than a slug, `validate_config.py` enforces the extra fields, and `slug` is still required
   as a human-readable dedup prefix (`comeet_slug()`). A scraped resolution records where it
   came from (`comeet_careers_url`) so a wrong-company hit is auditable.
3. **Hand-enrolled only.** Paylocity is GUID-addressed (`slug` holds the GUID, optional
   `paylocity_host`). Nothing derives it from a name; any single job-detail page carries a
   backlink to the board GUID.

Rules every probe follows:

- **Return contract.** `probe(ats, slug, budget)` returns `None` (no board), `[]` (board
  resolved, zero jobs), or `[(title, location), ...]`. Compound probes return
  `(jobs, meta)` or `(None, None)`, where `meta` carries the watchlist fields plus `total`.
- **"No board" is decided on evidence the API actually gives.** Where a host answers 200 for
  an identifier that doesn't exist, the probe has to detect that and return `None`:
  SmartRecruiters (200 with `totalFound: 0` → `None`, never `[]`), JazzHR (200 serving a fixed
  "Inactive Career Page" → `jazzhr_board_live()` checks the final host and the page title, not
  the byte count), Paylocity (200 with no `"Jobs":[` array → error), Workday (requires
  `total > 0`). Returning `[]` for a nonexistent identifier routes into `_confirm_empty`,
  whose re-probe gets the same confident answer and so confirms a slug collision onto the
  company's permanent record. That's how a 2026-08-28 sweep reported ten resolved companies
  that were all collisions.
- **Empty results on an honest API are re-checked** through `_confirm_empty` (2 s pause, one
  re-probe) before they're believed. Workable served empty 200s under burst load.
- **Location assembly matches the poller.** The probe builds location strings the same way
  the poller's `parse_location` branch does for that ATS, so a board scores in discovery the
  way it will score once enrolled (SmartRecruiters folds `remote` into the string; Comeet
  ignores `is_remote`; Paylocity ignores `IsRemote` in favor of `LocationName`).
- **Probe order in `assess()` is a collision-risk ordering, then a cost ordering.** Cheap slug
  probes run first, with any API that can't 404 a bad identifier last among them
  (SmartRecruiters). Speculative walks (Comeet) run after every slug probe fails. Workday runs
  last because it's the most expensive.
- **Scrapers share one parser.** When a board is HTML rather than JSON, the probe imports the
  poller's parser (JazzHR reuses `poll_ats`'s regexes) so discovery and the daily fetch can't
  drift apart.

## 3. Pagination past page 1

| ATS | Mechanism | Cap | Stop condition |
|---|---|---|---|
| SmartRecruiters | `offset` param, 100 per page (`limit=100` in the endpoint) | `SMARTRECRUITERS_MAX_POSTINGS = 500` (poller) and `SMARTRECRUITERS_PROBE_MAX = 500` (probe) | empty page, or `offset >= totalFound` |
| Workday | POST body `offset`/`limit`, 20 per page | `WORKDAY_MAX_POSTINGS = 1000` (raised from 200 on 2026-09-11, measured across all 46 live boards) | empty or short page, or `offset >= total`, where `total` is read once from the offset-0 response (later pages answer `total: 0`); 0.2 s sleep between pages |
| Rippling | `?page=N` | `RIPPLING_MAX_PAGES = 10` (20 per page) | no items, or `page >= totalPages`. A custom-domain board (listing redirects off ats.rippling.com) falls back to `_endpoints.rippling_board_api`, one unpaginated list |
| Greenhouse, Ashby, Lever, Workable, Pinpoint, JazzHR, Comeet, Paylocity | one response holds the whole board | n/a | n/a |

Conventions:

- The cap is a named constant, and the probe and the poller use the same cap for the same ATS.
- Stop on the total the API reports when it reports one; an empty page alone isn't the only
  exit.
- Page one failing or empty decides "no board." A later page failing is a truncated read of a
  real board: keep what you have. Rippling makes this explicit (a page-0 parse failure is an
  `_error`; a later one just ends the loop).
- The discovery probe paginates whenever the ATS paginates. A first-page-only probe missed all
  four of Canva's US Implementation Manager reqs, which sat past page one. Rippling's probe is
  still first-page-only; its comment calls that out as a known exception.
- Unverified: multi-page Rippling boards, and pagination on a large Pinpoint board. Both
  docstrings say so.

## 4. Per-company wall-clock budget

Only `harvest_ats.py` has one. The `Budget` class:

- `PER_COMPANY_BUDGET = 60` seconds. `budget=None` everywhere means unbounded, which is what
  `prune()` and any caller outside `assess()` get.
- `expired()` gates every loop, including per site name inside Workday's inner loop, because
  the expensive case is a tenant that resolves and 404s on every site.
- `timeout()` shrinks each request's HTTP timeout to whatever's left, floored at 1 s, so one
  hung socket can't overshoot the cap by a full `TIMEOUT`.
- `sleep()` clips politeness pauses to the remaining time.
- A trip returns `{"timed_out": True, "phase": ..., "elapsed": ..., "budget": ...}` instead
  of raising, so one slow name can't cost the rest of the batch. A board already held
  (a no-fit answer on a reduced name form) is returned in preference to the timeout.
- After the loops, `budget.tripped` is re-checked so a walk cut short on its last slug isn't
  reported as a clean no-board.

The poller has no per-company budget. Each `fetch_<ats>` passes `timeout=REQUEST_TIMEOUT`
(30 s) on every request, so a paginating fetcher's worst case is pages × 30 s. `fetch_jd.py`
uses `TIMEOUT = 45` per request. A new provider's probe accepts and honors `budget`; its
poller fetch passes `REQUEST_TIMEOUT` on every request and caps its pages.

## 5. Per-service pacing

Also harvest-only. `_pace(url, budget)` spaces requests to the same service by
`DELAY = 0.35` s, keyed by registrable domain (`_service()`: the last two host labels), so
ATSes that put the tenant in the hostname (Pinpoint, Workday, JazzHR) share one quota instead
of each slug getting a fresh one. Every probe request goes through `_get` (200 or `None`) or
`_raw_get` (any status, `None` only on network failure); a probe that needs POST calls `_pace`
itself first, as `probe_workday` does. The poller has no pacing layer: companies are fetched
one after another, and Workday sleeps 0.2 s between pages.

## 6. Error taxonomy

**Poller (`poll_ats.py`).** Fetchers never raise. Any failure returns a one-element sentinel,
`[{"_error": "<ExceptionType>: <message>"}]`, or a specific reason where one is known
("Workday entry missing wd_host/wd_tenant/wd_site", "Paylocity board has no Jobs array (wrong
GUID, or the board was removed)", "JazzHR: no board at slug ..."). `poll_all` records
`{company, ats, slug, error}`, increments `stats["errors"]`, and moves on. An `ats` with no
dispatch branch records "Unknown ATS: <ats>".

On success, each posting is normalized for the shared loop:

- The title lives under `title`. (`poll_all` also reads `text` for Lever and `JobTitle` for
  Paylocity, but newer adapters rename `name` → `title` inside the fetcher.)
- Internal-only postings are dropped (`is_internal`, `IsInternal`).
- Description text is flattened into `description` where the ATS offers one, for the industry
  exclusion.
- Values the generic helpers can't derive are pre-stashed under a leading underscore:
  `_apply_url`, `_detail_url`, `_posted`, `_workday_location`, `_paylocity_location`,
  `_paylocity_url`.
- A browser User-Agent is sent where the host demands one (Rippling trips Cloudflare without
  one; JazzHR). Huge responses are guarded (Ashby, 5 MB).
- Missing data is neutral, never negative. No posting date means `extract_posted_date` returns
  `None` (don't filter, no freshness bonus); no salary means neutral; a future-dated timestamp
  is treated as no data (Comeet).

**Discovery (`harvest_ats.py`).** Every name lands in exactly one class, and the class decides
what's written to `enrollment_candidates.json`:

| Class | Meaning | `unpollable` | Reason text |
|---|---|---|---|
| enrollable | board resolved with fit-titles | n/a (enrolled) | n/a |
| no_fit | board resolved, no qualifying titles | not set | rejected on fit-space, not pollability |
| empty_board | board resolved, zero jobs, confirmed | `false` | "Board RESOLVED ... ZERO jobs" |
| no_board | nothing resolved | `true` | lists exactly which ATSes were probed and which were skipped |
| timed_out | budget tripped | `false`, plus `timed_out: true` | "UNRESOLVED ON TIMEOUT, not on evidence" plus the cheap next step |
| collision | a board with jobs, but none matching the card's role | `true`, plus `manual_review` | "PROBABLE NAME COLLISION" |

The reason text has to say what was actually tried. Upwind Security was rejected with an
accurate sentence that pointed at the wrong next step while it ran a live Comeet board. A new
ATS gets added to the `no_board` reason's probe list in the same change.

**JD fetch (`fetch_jd.py`).** `fetch_<ats>(url)` returns `None` when the URL isn't this ATS's
(the dispatcher tries the next one), a dict with `ats, title, location, remote, posted,
salary, body` on success, and may raise; `fetch()` turns a raise into
`{"error": "fetch_<ats>: <Type>: <msg>"}`. The CLI exits 1 if any URL failed. The
unmatched-URL error lists every supported ATS by name, so it needs the new one too.

## 7. Enrollment writes

- Watchlist entries carry `name`, `ats`, `slug`, plus the ATS's extra fields; scraped
  resolutions also carry where they came from.
- JSON escaping is per file: `enrollment_candidates.json` is written escaped
  (`ensure_ascii` default), `watchlist_companies.json` raw (`ensure_ascii=False`). Harvest
  branches on `ensure_ascii=(path == QUEUE)`. Every write ends with one `"\n"` and goes
  through a `.tmp` file plus `os.replace`.
- Run `validate_config.py` after any hand edit.

## 8. Test shape

What exists today:

- **Plain-script self-checks, no pytest.** `test_tier3_gate.py`, `test_builtin_fit_gate.py`,
  and `test_harvest_linkedin.py` each insert the pipeline directory on `sys.path`, import the
  function under test directly, run a `CASES` list of `(input, expected, why)` where `why`
  names the real case that motivated the row, print `[ok ]` or `[FAIL]` per case and then
  `N/M passed`, and `sys.exit(1 if fails else 0)`. Run as
  `.venv/bin/python pipeline/test_<name>.py`.
- **Fixtures are synthetic and safe for this public repo**: no real addresses, tokens, or
  tracking IDs (see `test_harvest_linkedin.py`'s docstring).
- **Live verification is a script, not a test.** `verify_workday.py` hits the real endpoint,
  prints `[OK]`/`[--]` per candidate and a paste-ready block. The result is recorded in the
  adapter's notes with the date and the count seen ("verified live 2026-08-21: total=290").
- `validate_config.py` has to pass after enrollment.

What a new provider has to pass. This is the bar the horizon-builds Milestone 6 sets. Items
1 and 2 extend existing precedent; items 3 and 4 have no precedent in the repo yet, which is
worth knowing before assuming there's a pattern to copy.

1. **Live integration against one real requisition.** Resolve a real board, find a named req
   on it, and parse its title, location, and apply URL. Written so it fails before the adapter
   exists. (Precedent: `verify_workday.py` and the dated "verified live" notes.)
2. **No-board classification, in `CASES` form.** Nonexistent identifier → `None`; real but
   empty → `[]` if the API can express it; real → a list. (Precedent: JazzHR's inactive page,
   SmartRecruiters' `totalFound: 0`.)
3. **Pagination past page 1** against a live board with more than one page: the count exceeds
   one page and matches the API's reported total up to the cap. No live test does this today;
   the SmartRecruiters fix was checked by hand (ServiceNow went from 100 to about 465 postings
   read). `test_workday_pagination.py` (2026-09-11) covers the loop logic with a fake session,
   which is the offline half of this bar, not the live half.
4. **The budget under a simulated hang.** A request that never answers ends the probe at the
   budget, plus at most the 1 s timeout floor, with a `timed_out` result rather than an
   exception. No test does this today; the budget was validated by measured runs (the Upwind
   walk went from 63 s to 22 s). Simulate the hang with the standard library only.

## 9. Checklist for a new ATS

1. `fetch_<ats>()` in `poll_ats.py`, returning the `_error` sentinel on failure, capped
   pagination, `REQUEST_TIMEOUT` on every request.
2. Dispatch branch in `poll_all()`.
3. `parse_location`, `extract_posted_date`, and `build_apply_url` branches (return `None` for
   a date the ATS doesn't expose).
4. `_endpoints` entry, or a `POST` template if the fetcher builds its own URL.
5. `_<ats>_notes` in the watchlist: identifier source, limits, date, the case that prompted it.
6. `SUPPORTED_ATS` and any required extra fields in `validate_config.py`.
7. `probe()` branch or `probe_<ats>()` in `harvest_ats.py`, honoring `budget`, going through
   `_get`/`_raw_get`/`_pace`, returning `None` on anything that isn't proof of a board.
8. Its slot in the `assess()` order, and its name in the `no_board` reason text.
9. `fetch_<ats>(url)` in `fetch_jd.py`, added to `FETCHERS` and to the unmatched-URL message.
10. `prune()` only if the probe can tell dead-404 from resolved-empty.
11. The four tests in section 8, output kept with the change.
