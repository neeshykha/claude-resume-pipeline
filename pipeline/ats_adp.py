#!/usr/bin/env python3
"""ADP adapter core: WorkforceNow (cid-addressed) board resolution.

Added 2026-09-18 (Milestone 6, horizon-builds ADP backlog: Caliber Car Wash,
Mountain Seed, Parallels, RK&K, Steel Partners). This module holds the URL
building, response parsing, and normalization shared by the poller
(`poll_ats.fetch_adp`), discovery (`harvest_ats.probe_adp`), and JD retrieval
(`fetch_jd.fetch_adp`) -- kept out of those three shared files per the
horizon-build convention of minimizing merge conflicts across parallel
adapter builds. It has no dependency on any of them (leaf module, `re` and
`datetime` only), so it can be imported from all three without a cycle.

THREE URL SHAPES SEEN LIVE ON THE FIVE BACKLOG COMPANIES' OWN CAREERS PAGES
(fetched 2026-09-18):

  1. WorkforceNow, cid-addressed (Caliber Car Wash, Mountain Seed, Parallels --
     3 of 5). `workforcenow.adp.com/mascsr/default/mdf/recruitment/
     recruitment.html?cid=<GUID>...`, backed by a public JSON API at
     `workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/
     v1/job-requisitions?cid=<GUID>`. THIS IS THE ONLY SHAPE THIS MODULE
     SUPPORTS. Picked because it is the majority shape in the known backlog,
     it has a real JSON API (no scraping, no headless browser), and it is a
     genuinely multi-tenant platform the same way Paylocity is -- any other
     company on WorkforceNow's shared host is reachable through the same
     adapter once its cid is known, not just these three.
  2. `recruiting.adp.com/srccar/public/RTI.home?r=...&c=...&d=...&rb=...`
     (RK&K, alongside its own myjobs.adp.com board -- see shape 3). This is
     ADP Recruiting/Virtual Edge, a DIFFERENT product from WorkforceNow with a
     different URL grammar entirely. NOT SUPPORTED. No public JSON endpoint
     was found for it during this build; each `r=` parameter looks like a
     per-requisition token, which suggests there is no single board-level
     listing call the way job-requisitions is for WorkforceNow. Unsupported by
     the poller and by validate_config.py; a company found only on this shape
     stays off the watchlist.
  3. `myjobs.adp.com/<name>careers` (RK&K, Steel Partners). ADP's newer
     "MyJobs" career-site product, a third distinct codebase from both of the
     above. NOT SUPPORTED. Not investigated beyond confirming the URL shape
     live -- out of scope for this first cut; worth a follow-up build if more
     of the backlog turns out to sit here than on WorkforceNow.

  RK&K and Steel Partners therefore have NO supported ADP path today and stay
  unpollable/hand-enrollment candidates only if a WorkforceNow cid surfaces
  for them some other way (e.g. a job-alert email, which is how Paylocity
  GUIDs get recovered per _paylocity_notes).

HAND-ENROLLMENT ONLY, LIKE PAYLOCITY. A WorkforceNow cid is a GUID with no
relationship to the company name, so it can never be derived the way a
Greenhouse/Ashby/Lever slug is. `probe_adp()` in harvest_ats.py can VALIDATE a
cid someone already found (a careers-page link, a job-alert email, a posting
URL) but cannot discover one by searching on a name. Store the cid in the
watchlist entry's `slug` field, exactly like Paylocity's GUID -- no separate
`adp_cid` field, so validate_config.py needs no new required-field rule.
"""
import re
from datetime import date, datetime

ADP_WFN_HOST = "workforcenow.adp.com"
ADP_JOB_REQ_PATH = "/mascsr/default/careercenter/public/events/staffing/v1/job-requisitions"
ADP_RECRUITMENT_PATH = "/mascsr/default/mdf/recruitment/recruitment.html"

# The API's real page size, verified live 2026-09-18 against Caliber Car Wash
# (cid 2fe51c8e-72c9-4ef8-b866-3bb618f66134): requesting $top=100 still
# returned only 20 rows (meta.totalNumber correctly read 58 across all
# requests, so the server clamps the page rather than erroring or ignoring
# the param). Pagination is therefore mandatory for any board over 20
# postings, and increasing $top buys nothing.
ADP_PAGE_SIZE = 20

# Cap on total postings read per board, shared by the poller (poll_ats.fetch_adp)
# and the discovery probe (harvest_ats.probe_adp) per ats_contract.md section 9
# ("capped pagination (named constant shared by probe and poller)"). 500
# matches the SmartRecruiters/Rippling precedent for a hand-enrolled ATS with a
# small number of companies; the largest board seen during this build (Caliber
# Car Wash, 58) is nowhere near it.
ADP_MAX_POSTINGS = 500

CID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

# Matches a WorkforceNow recruitment.html / job-requisitions URL and captures
# cid= and, if present, jobId=. Verified against the live apply-URL shape
# (window.location.href after clicking a real posting): recruitment.html?
# cid=<GUID>&lang=en_US&jobId=<ExternalJobID>, with ccId optional wherever it
# appears (see apply_url()'s docstring for why it's omitted on write).
RECRUITMENT_URL_RE = re.compile(
    r"workforcenow\.adp\.com/mascsr/default/mdf/recruitment/recruitment\.html"
    r"\?(?P<query>[^\s\"'<>]+)", re.I)


def requisitions_url(cid: str, skip: int = 0, top: int = ADP_PAGE_SIZE) -> str:
    """Build one page of the job-requisitions listing URL.

    `ccId` is deliberately omitted. Every company's own careers-page link
    embeds one, and the value is per-company (Caliber Car Wash:
    ccId=19000101_000001; Mountain Seed: ccId=1586553131112931_5480) and not
    guessable from cid alone -- but verified live 2026-09-18 that dropping it
    entirely changes nothing: the job-requisitions response for Caliber's cid
    was byte-identical (same meta.totalNumber=58) with and without it, and the
    recruitment.html deep link rendered the correct posting with no ccId at
    all. Both appear to route on cid alone.
    """
    return (f"https://{ADP_WFN_HOST}{ADP_JOB_REQ_PATH}"
            f"?cid={cid}&lang=en_US&%24top={top}&%24skip={skip}")


def detail_url(cid: str, ext_job_id: str) -> str:
    """Single-requisition detail endpoint: everything the listing has PLUS the
    full `requisitionDescription` HTML body the listing omits.

    Discovered by network capture 2026-09-18: recruitment.html's own JS calls
    `GET .../job-requisitions/{jobId}?cid=<cid>` when rendering one posting
    (jobId is ExternalJobID, same as apply_url()). Used by fetch_jd.py's JD
    fetcher, which needs the body text and only ever wants one requisition --
    unlike the poller and probe, which need the whole board and use
    requisitions_url() instead.
    """
    return f"https://{ADP_WFN_HOST}{ADP_JOB_REQ_PATH}/{ext_job_id}?cid={cid}&lang=en_US"


def apply_url(cid: str, ext_job_id: str) -> str:
    """The public deep link to one requisition.

    Verified live 2026-09-18: opening Caliber Car Wash's "Site Manager" req
    (itemID 9205237211496_1) and reading window.location.href after click-
    through gave exactly this shape with jobId=638063 -- which is the
    requisition's customFieldGroup ExternalJobID stringField, NOT its itemID.
    """
    if not cid or not ext_job_id:
        return ""
    return (f"https://{ADP_WFN_HOST}{ADP_RECRUITMENT_PATH}"
            f"?cid={cid}&lang=en_US&jobId={ext_job_id}")


def parse_recruitment_url(url: str):
    """(cid, jobId) from a recruitment.html URL, jobId possibly None. None if
    the URL isn't this shape at all.

    The captured query group starts right at its first param (no leading
    "?" or "&" survives the outer match), so `cid=` can be the very first
    thing in it -- matching only "[?&]cid=" missed that case entirely and
    this function returned None for every real apply URL until caught by a
    live fetch_jd.py smoke test. `(?:^|[&?])` covers both positions.
    """
    m = RECRUITMENT_URL_RE.search(url or "")
    if not m:
        return None
    query = m.group("query")
    cid_m = re.search(r"(?:^|[&?])cid=([^&]+)", query, re.I)
    if not cid_m:
        return None
    job_m = re.search(r"(?:^|[&?])jobId=([^&]+)", query, re.I)
    return (cid_m.group(1), job_m.group(1) if job_m else None)


def extract_page(data: dict):
    """(items, total) from one job-requisitions response.

    `total` is None when the response carries no `meta` key at all, which is
    what a genuinely out-of-range page returns (verified live: skip=60 against
    a 58-total board answered exactly `{"jobRequisitions": []}`, no `meta`).
    Callers must not treat a missing total as zero.
    """
    items = data.get("jobRequisitions") or []
    total = (data.get("meta") or {}).get("totalNumber")
    return items, total


def _custom_string(req: dict, code: str):
    cfg = req.get("customFieldGroup") or {}
    for f in cfg.get("stringFields") or []:
        if (f.get("nameCode") or {}).get("codeValue") == code:
            return f.get("stringValue")
    return None


def _custom_indicator(req: dict, code: str):
    cfg = req.get("customFieldGroup") or {}
    for f in cfg.get("indicatorFields") or []:
        if (f.get("nameCode") or {}).get("codeValue") == code:
            return f.get("indicatorValue")
    return None


def external_job_id(req: dict):
    """The public jobId the apply URL uses -- NOT itemID. See apply_url()."""
    return _custom_string(req, "ExternalJobID")


def is_internal(req: dict) -> bool:
    """InternalPostingFlag, buried in customFieldGroup.indicatorFields.

    Same convention as Paylocity's IsInternal / Comeet's is_internal: internal-
    only reqs are not public applications and fetch_adp drops them rather than
    leaving it to poll_all's generic title-based filtering, which has no
    internal-only concept.
    """
    return bool(_custom_indicator(req, "InternalPostingFlag"))


def salary_range(req: dict):
    """Free-text salary string ("55000.00 To 60000.00 (USD) Annually"), when
    the requisition carries one. Neutral (None) when absent -- same "no data,
    don't penalize" rule as every other adapter."""
    return _custom_string(req, "SalaryRange")


def posted_date(req: dict):
    """postDate is a real ISO-8601 timestamp with offset, unlike Workday's
    relative-string posting date -- no floor-resolution machinery needed."""
    raw = req.get("postDate")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except (ValueError, TypeError):
        return None


def location_string(req: dict) -> str:
    """Join every requisitionLocations entry into one display string.

    Prefers each location's own `nameCode.shortName` (already human-formatted,
    e.g. " Cross Roads, TX, US" -- note the leading space, stripped here) and
    falls back to assembling city + state code from `address` when shortName
    is absent. Multiple locations (seen on the live board only as distinct
    single-location postings so far, but the schema allows a list) are joined
    with "; ", deduplicated in order.

    Country is NOT read here. Every posting seen live across all five backlog
    companies is a US small/mid-size employer with no non-US requisitions to
    test against, so there is no live evidence to build a country stamp from
    -- same position Rippling is documented in as taking (CLAUDE.md
    "Rippling is the one adapter left with a country field it does not
    read"). Revisit if an ADP board with a non-US requisition turns up.
    """
    locs = req.get("requisitionLocations") or []
    parts = []
    for loc in locs:
        name = ((loc.get("nameCode") or {}).get("shortName") or "").strip()
        if not name:
            addr = loc.get("address") or {}
            city = addr.get("cityName")
            state = (addr.get("countrySubdivisionLevel1") or {}).get("codeValue")
            bits = [b for b in (city, state) if b]
            name = ", ".join(bits)
        if name and name not in parts:
            parts.append(name)
    return "; ".join(parts) if parts else "Unknown"


def normalize(req: dict, cid: str) -> dict:
    """One job-requisitions item -> the shape poll_ats.py's shared loop and
    parse_location/extract_posted_date/build_apply_url branches read.

    Keeps every raw field (so extract_posted_date can read `postDate`
    directly -- it's already real ISO-8601, no stash needed) and adds:
      title           requisitionTitle, so the generic `title` lookup works
      _adp_location   precomputed display string (location_string())
      _apply_url      precomputed apply URL (apply_url()) -- reuses the same
                      generic `_apply_url` key Workday's branch already reads
      _adp_internal   bool, so fetch_adp can drop internal-only reqs
      _adp_salary     free-text salary, or None
    """
    ext_id = external_job_id(req)
    out = dict(req)
    out["title"] = req.get("requisitionTitle") or ""
    out["_adp_location"] = location_string(req)
    out["_apply_url"] = apply_url(cid, ext_id) if ext_id else ""
    out["_adp_internal"] = is_internal(req)
    out["_adp_salary"] = salary_range(req)
    out["_adp_req_id"] = req.get("clientRequisitionID")
    out["_adp_ext_job_id"] = ext_id
    return out
