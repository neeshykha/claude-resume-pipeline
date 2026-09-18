"""Gem ATS adapter (jobs.gem.com).

Gem boards are slug-addressed (`jobs.gem.com/<slug>`, e.g. `jobs.gem.com/retool`)
but the rendered page is a React/Apollo app with no visible REST API: every
board and every job page is served by ONE fixed GraphQL endpoint,

    POST https://jobs.gem.com/api/public/graphql/batch

with the slug passed as a `boardId` GraphQL variable, never as part of the
URL. Found 2026-09-18 by loading a live board (jobs.gem.com/retool) in a
real browser and reading its network requests -- the page's own minified JS
bundle (jobBoards.*.v2.min.js) names the query but not the endpoint; the
endpoint only showed up in the actual XHR. Confirmed the endpoint needs no
browser: a bare `requests.post` with a JSON body works identically outside
a browser session (no auth, no cookies, no CSRF token).

THE BOGUS-SLUG SIGNAL (contract section 2's hard requirement). A board that
does not exist answers HTTP 200 -- this API never 404s -- with
`jobBoardExternal: null` and `oatsExternalJobPostings.jobPostings: []`.
A board that DOES exist, even with zero postings open, answers with
`jobBoardExternal` populated (id/teamDisplayName/pageTitle) and an empty
`jobPostings` array. So `jobBoardExternal is not None` is the board-exists
signal -- NOT job count -- and probe() must read it before it can ever
return `[]`. Verified live 2026-09-18:
  - jobs.gem.com/retool           -> jobBoardExternal set,  21 postings
  - jobs.gem.com/function-health  -> jobBoardExternal set,  33 postings
  - jobs.gem.com/transluce        -> jobBoardExternal set,  11 postings
  - jobs.gem.com/thisboarddoesnotexist12345xyz -> jobBoardExternal NULL
  - jobs.gem.com/retool.ai (dotted, bogus)     -> jobBoardExternal NULL,
    HTTP 200 -- confirms a dotted slug is safe to send (it is a GraphQL
    variable, never part of a hostname or path segment the way it is for
    JazzHR/Pinpoint/SmartRecruiters), so this ATS is NOT added to
    harvest_ats.NO_DOTTED_SLUG_ATSES.

PAGINATION: NONE. The board-list query returns every open posting in one
response; there is no offset/limit/page parameter anywhere in the query the
live page itself sends. Verified against the largest board found in this
sweep, jobs.gem.com/function-health: the API returned exactly 33
jobPostings and the rendered board page's own "Open positions (33)" header
lists the same 33 titles by hand-count. This is the contract's "one
response holds the whole board" (n/a) class, same as Greenhouse -- there is
no MAX_POSTINGS constant here because there is nothing to cap.

NO POSTING-DATE FIELD IN THE LIST QUERY. The board-list query
(JOB_BOARD_LIST_QUERY) exposes no publish/created timestamp at all -- the
single-job detail query does (`firstPublishedTsSec`), but the poller never
calls that query, so `extract_posted_date` returns None for every Gem
posting the daily fetch sees, same "no data -> don't filter" treatment as
Pinpoint/Rippling/JazzHR.

LOCATION DATA QUALITY GOTCHA. A posting can carry several `locations`
entries, and for postings open to several remote regions, Gem represents
each region as its own synthetic location row with a human-readable `name`
("US - Remote", "Canada - Remote", "Mexico - Remote", "LATAM - Remote",
"Americas - Remote") but ALL of them carry the SAME `isoCountry` ("USA")
and the SAME fallback `city` (the company's home office city) regardless of
which region the name actually describes. Verified on Function Health's
"Staff Data Architect": all five rows above read isoCountry "USA". Trusting
isoCountry on a remote row would therefore silently pass a Canada/Mexico/
LATAM posting as US-only. A real, single, physical office location does
NOT have this problem -- Retool's London posting carries isoCountry "GBR"
correctly. So `location_string()` only stamps a non-US country off a
location row with isRemote=False. The synthetic remote-region rows are not
left silently wrong: their `name` text already says "Canada - Remote" /
"Mexico - Remote" / "LATAM - Remote" in the assembled string, and
poll_ats.LOCATION_EXCLUDE / harvest_ats.NON_US_MARKERS already block
"canada", "mexico", and "latam" as free text, so the existing gates still
catch these without a Gem-specific rule.

APPLY URL: `https://jobs.gem.com/<slug>/<extId>` -- confirmed by clicking a
real posting (Function Health's "Staff Data Architect") in a live browser
and reading window.location.href.
"""
import requests

import countries

GRAPHQL_URL = "https://jobs.gem.com/api/public/graphql/batch"

# Guard against a pathological response the way fetch_ashby guards content-length;
# nothing this large has been observed (function-health's 33-posting board is
# ~28KB decoded), but a board is unpaginated by construction, so nothing bounds
# response size except this.
MAX_RESPONSE_BYTES = 5_000_000

JOB_BOARD_LIST_QUERY = """query JobBoardList($boardId: String!) {
  oatsExternalJobPostings(boardId: $boardId) {
    jobPostings {
      id
      extId
      title
      locations { id name city isoCountry isRemote extId }
      job { id department { id name extId } locationType employmentType }
    }
  }
  jobBoardExternal(vanityUrlPath: $boardId) { id teamDisplayName pageTitle }
}"""

# Single-posting query, used only by fetch_jd.py (a job-detail URL carries its
# own extId, so this is a per-JD lookup, never used by the daily board poll).
JOB_DETAIL_QUERY = """query ExternalJobPosting($boardId: String!, $extId: String!) {
  oatsExternalJobPosting(boardId: $boardId, extId: $extId) {
    title
    descriptionHtml
    firstPublishedTsSec
    locations { name city isoCountry isRemote }
    job { locationType employmentType }
    compensationHtml
    jobPostSectionHtml { introHtml outroHtml }
  }
}"""


def build_list_payload(slug: str) -> list:
    """The GraphQL batch body for one board-list request."""
    return [{"operationName": "JobBoardList",
             "variables": {"boardId": slug},
             "query": JOB_BOARD_LIST_QUERY}]


def build_detail_payload(slug: str, ext_id: str) -> list:
    """The GraphQL batch body for one single-posting detail request."""
    return [{"operationName": "ExternalJobPosting",
             "variables": {"boardId": slug, "extId": ext_id},
             "query": JOB_DETAIL_QUERY}]


def parse_board_response(data):
    """(board_exists, job_postings) from a decoded JobBoardList batch response.

    `data` is the list `resp.json()` returns for the batch endpoint (one
    element per operation sent; this adapter only ever sends one).
    `board_exists` is read off `jobBoardExternal` -- see the module
    docstring for why job count cannot be used instead. Raises
    (KeyError/IndexError/TypeError) on a response shaped unlike the one this
    module knows; callers catch that the same way every other fetcher's
    `except Exception` does.
    """
    payload = data[0]["data"]
    board_exists = payload.get("jobBoardExternal") is not None
    postings = (payload.get("oatsExternalJobPostings") or {}).get("jobPostings") or []
    return board_exists, postings


def _apply_workplace_label(full: str, location_type) -> str:
    """Prefix "Remote"/"Hybrid" off job.locationType, mirroring poll_ats's
    _apply_workplace_type. "IN_OFFICE" is deliberately not prefixed, same
    reasoning as that helper's "OnSite"."""
    lt = (location_type or "").strip().upper()
    label = {"REMOTE": "Remote", "HYBRID": "Hybrid"}.get(lt)
    full = (full or "").strip()
    if label and label.lower() not in full.lower():
        full = f"{label} {full}".strip()
    return full


def location_string(posting: dict) -> str:
    """The same location text the Gem board page itself renders.

    Joins each `locations[].name` in API order -- exactly the comma-joined
    text the rendered board shows (verified against jobs.gem.com/
    function-health's "Staff Data Architect": API order matches the page's
    "Americas - Remote, US - Remote, Canada - Remote, Mexico - Remote,
    LATAM - Remote"). See the module docstring for why only a non-remote
    location's isoCountry is trusted for the non-US stamp.
    """
    locs = posting.get("locations") or []
    names = [l.get("name") for l in locs if l.get("name")]
    full = ", ".join(names)
    job = posting.get("job") or {}
    full = _apply_workplace_label(full, job.get("locationType"))
    office = next((l for l in locs if not l.get("isRemote") and l.get("isoCountry")), None)
    if office:
        full = countries.stamp(full, office.get("isoCountry"))
    return full or "Unknown"


def apply_url(slug: str, ext_id: str) -> str:
    return f"https://jobs.gem.com/{slug}/{ext_id}"


def fetch_gem(slug: str, timeout: int = 30) -> list:
    """Poller fetch: every open posting on `slug`'s board.

    Returns the `_error` sentinel list on any failure, including a slug with
    no board (this function is only ever called for an ENROLLED company, so
    a missing board at fetch time is an error worth surfacing, unlike
    probe()'s deliberate None/[] distinction for discovery).
    """
    try:
        resp = requests.post(GRAPHQL_URL, json=build_list_payload(slug), timeout=timeout)
        resp.raise_for_status()
        content_length = resp.headers.get("content-length")
        if content_length and int(content_length) > MAX_RESPONSE_BYTES:
            return [{"_error": f"Response too large: {content_length} bytes"}]
        board_exists, postings = parse_board_response(resp.json())
        if not board_exists:
            return [{"_error": f"Gem: no board at slug '{slug}'"}]
        return postings
    except Exception as e:
        return [{"_error": f"{type(e).__name__}: {e}"}]
