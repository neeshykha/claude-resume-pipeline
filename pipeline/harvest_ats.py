#!/usr/bin/env python3
"""ATS directory-harvest layer: company name -> slug -> live board -> fit-space -> enroll.

Usage:
    .venv/bin/python pipeline/harvest_ats.py --from-pending
    .venv/bin/python pipeline/harvest_ats.py --names "Outreach" "Rippling" "Deel"
    .venv/bin/python pipeline/harvest_ats.py --from-pending --apply
    .venv/bin/python pipeline/harvest_ats.py --prune            # dead-board audit

WHY THIS EXISTS
---------------
CLAUDE.md carried a standing decision from 2026-07-02: a third WitnessAI-class
miss (real company, pollable board, invisible to discovery) triggers building an
ATS directory-harvest layer. That trigger has since fired many times over --
Nexus Cognitive, Docusign, Netflix, and a 2026-07-31 audit that found 35 of 47
well-known scaleups untracked.

The gap was NOT a shortage of company names: Step 1d-2 (LinkedIn), HN hiring,
80,000 Hours, and the board dorks all feed names into `enrollment_candidates.json
-> pending`. The bottleneck was that turning a NAME into a verified slug required
Claude to run a WebSearch per company, which is why Step 1d is capped at 4 per
run and why the queue silently stalled for 26 days.

This script does that resolution deterministically and in bulk: it generates
slug candidates from the company name, probes each supported ATS directly, and
scores the resulting board against the SAME TitleMatcher the poller uses -- so a
company is judged by real tier1/tier2 fit-titles, not by keyword guessing. A full
pass over a dozen names costs seconds and zero WebSearches.

DELIBERATELY NOT A CRAWLER. It never enumerates or brute-forces slug space; it
only tries a handful of deterministic variants of a name someone already
surfaced, with a polite delay between requests.

TWO RESOLUTION MODELS, NOT ONE (Comeet, added 2026-09-03). Everything above
assumes a board is addressed by a name-derived slug, which held for every ATS
here until Comeet. Comeet boards are keyed by a `comeet_uid` + `comeet_token`
pair that exists only in the company's own careers page, so no slug guess can
ever reach one. That gave this script a blind spot it could not report
accurately: it rejected Upwind Security on 2026-09-02 for "no board resolved
from deterministic name-variant slugs" while Upwind ran a live 58-position
Comeet board -- an ATS poll_ats.py has supported since 2026-08-20. probe_comeet
inverts the walk for that one case (name -> own domain -> careers page ->
scraped credentials -> board) and is documented in full at the Comeet section
below.
"""
import argparse
import json
import os
import re
import sys
import time
from urllib.parse import urlsplit

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST = os.path.join(SCRIPT_DIR, "watchlist_companies.json")
QUEUE = os.path.join(SCRIPT_DIR, "enrollment_candidates.json")

TIMEOUT = 20
DELAY = 0.35          # politeness pause between HTTP calls
UA = {"User-Agent": "Mozilla/5.0 (resume-pipeline-harvest)"}

# Wall-clock ceiling for ONE company, across every probe including Workday.
# Nothing in this script is individually unbounded -- TIMEOUT caps each request
# and probe_workday's 422 short-circuit caps each tenant -- but the PRODUCT of
# those bounds is not small: 4 tenant slugs x 5 hosts x 15 site names x 20s is
# roughly 100 minutes for a single name in the worst case. That case is not
# hypothetical. It is exactly what a large enterprise whose Workday tenant
# RESOLVES but matches none of our site names does, and on 2026-09-02 a 16-name
# batch holding four of them (Palo Alto Networks, RSA Security, Forescout,
# Worldwide Clinical Trials) was SIGKILLed at ~10 minutes, re-run, and was still
# silent past 40, leaving 21 queue entries unresolved and forcing a hand
# enrollment. --skip-workday was added the same day to route around it, at the
# cost of giving up Workday resolution for the whole batch.
#
# 60s is chosen so the daily ~15-name harvest has a hard 15-minute ceiling
# instead of an open-ended one. It is a CEILING, not a target: the common case
# is 5-20s per name (a board resolves early and returns), and only names that
# resolve nothing anywhere approach it.
PER_COMPANY_BUDGET = 60.0


class Budget:
    """Per-company wall-clock cap, consulted between and during probes.

    Threaded explicitly rather than kept in a module global so prune() and any
    future caller can keep the old unbounded behaviour by simply not passing one
    -- `budget=None` everywhere means "no cap", which is what every existing call
    site outside assess() wants.

    Two mechanisms, and both are needed:

      expired()  gates the loops, so a tripped budget stops the walk instead of
                 letting it run to its natural end.
      timeout()  shrinks the per-request HTTP timeout to whatever is left, so a
                 single hung socket cannot overshoot the cap by a full TIMEOUT.
                 Without it the cap would be honoured only to +/-20s, which is a
                 third of the budget.
    """

    def __init__(self, seconds=PER_COMPANY_BUDGET):
        self.seconds = seconds
        self.start = time.monotonic()
        self.deadline = self.start + seconds
        self.tripped = False

    def elapsed(self):
        return time.monotonic() - self.start

    def remaining(self):
        return self.deadline - time.monotonic()

    def expired(self):
        if self.remaining() <= 0:
            self.tripped = True
            return True
        return False

    def timeout(self):
        """HTTP timeout for the next request: never longer than what is left.

        Floored at 1s rather than at 0 so the last request before the cap is a
        real attempt and not a guaranteed failure.
        """
        return max(1.0, min(TIMEOUT, self.remaining()))

    def sleep(self, seconds):
        """Politeness pause, clipped to the remaining budget.

        A 2s _confirm_empty pause with 0.4s left on the clock is 1.6s of pure
        overshoot for no information, and those pauses are the largest
        non-network cost in a full slug walk.
        """
        time.sleep(max(0.0, min(seconds, self.remaining())))


# Location strings that count as US-reachable. Mirrors the intent of the
# poller's location handling: we only want fit-titles Aneesh could actually take.
US_HINTS = (
    "united states", "usa", "u.s.", "remote", "anywhere", "north america",
    "california", "new york", "texas", "washington", "massachusetts", "illinois",
    "colorado", "georgia", "florida", "utah", "oregon", "arizona", "virginia",
    "boston", "chicago", "atlanta", "denver", "austin", "seattle", "nyc",
    "san francisco", "los angeles", "san diego", "miami", "philadelphia",
)

# Tiers that count as real fit-space for auto-enrollment ANYWHERE US-reachable.
# tier4/supplemental stay excluded outright: a company whose only match is a weak
# stretch title is not worth a permanent daily poll slot.
STRONG_TIERS = ("tier1_true_match", "tier2_strong_overlap", "tier2c_tooling_systems")

# tier3 counts too, but ONLY in Atlanta or remote-US (see tier3_location_ok).
#
# Added 2026-08-21, Aneesh's call. tier3 used to be lumped in with tier4 and
# supplemental, which conflated two different things: the rubric gives
# tier3_reasonable_stretch +15 title match and CLAUDE.md says "full tailoring if
# score >= 88", whereas tier4 is the genuinely weak one. The cost was concrete --
# five companies were rejected for "ZERO US-reachable tier1/tier2/tier2c titles"
# in three weeks while each had a live tier3 role: Evident ID (Atlanta CSM),
# Britive, Sonatype, Nylas, Placemakr. Evident ID had to be hand-enrolled.
#
# The proof that tier3 is not weak: the Vanta "Sr. Manager, Commercial Customer
# Success" role surfaced 2026-08-21 is a tier3 title and scored 96, one of the two
# best picks of that day. Discovered by this layer with only that role live, it
# would have been thrown away.
#
# Gated on location rather than admitted outright because tier3 is a broad family
# (CSM, Technical CSM, Customer Success Engineer, Solutions Engineer) and an
# ungated rule would widen auto-enrollment sharply against an already 291-company
# watchlist where every entry costs poll time. Location is the right gate because
# it is exactly what makes a stretch title worth taking: Atlanta carries +20
# in-office / +18 hybrid and a further +20 Atlanta-startup, and remote-US carries
# +16, which is the difference between a tier3 role scoring ~80 and scoring ~105.
TIER3_TIER = "tier3_reasonable_stretch"

ATLANTA_HINTS = ("atlanta", "georgia", ", ga", " ga)", "(ga)")
REMOTE_HINTS = ("remote", "anywhere", "distributed", "work from home")

# Country markers that disqualify a "Remote" string from meaning remote-US.
# "Remote CAN" and "Remote - EMEA" both contain "remote"; neither is US-reachable.
# Long names are matched as substrings; short codes MUST be matched as whole
# tokens, because a bare "can" substring also fires on "Duncan" and "Vatican",
# and "de"/"es"/"se" fire on half the dictionary. Caught by the unit cases.
NON_US_MARKERS = (
    "canada", "united kingdom", "great britain", "emea", "apac", "latam",
    "latin america", "australia", "new zealand", "india", "ireland", "germany",
    "france", "poland", "netherlands", "singapore", "japan", "brazil", "mexico",
    "spain", "sweden", "israel", "philippines", "colombia", "argentina",
    "portugal", "romania", "indonesia", "thailand", "vietnam", "south africa",
    "london", "dublin", "berlin", "paris", "amsterdam", "sydney", "toronto",
    "vancouver", "bangalore", "tel aviv",
)
NON_US_CODES = frozenset((
    "can", "uk", "gb", "eu", "ca-on", "ca-bc", "mex", "bra", "deu", "fra",
    "nld", "esp", "swe", "isr", "ind", "aus", "nzl", "sgp", "jpn", "irl", "pol",
))


_LEADING_STOPWORDS = {"the", "a", "an"}


def _first_word(text: str) -> str:
    """First meaningful word, skipping a leading article.

    "The Scion Group" must not reduce to "the": that is not a plausible tenant
    and probing it costs a full site-name walk against whatever tenant happens
    to answer to it.
    """
    words = re.sub(r"[^a-z0-9 ]+", " ", text).split()
    while words and words[0] in _LEADING_STOPWORDS:
        words = words[1:]
    return words[0] if words else ""


def workday_slug_candidates(name: str):
    """The few tenant-plausible slugs worth spending a Workday probe on.

    Added 2026-08-31. Kept separate from slug_variants() because the two answer
    different questions: that one asks "what might this company's board be called
    on any ATS", which is worth being generous about since a wrong guess costs one
    cheap 404. This one asks "what might the Workday TENANT be", where a wrong
    guess costs up to ~12s because probe_workday walks 15 site names per tenant.

    Workday tenants are plain company names or short abbreviations. They are never
    the Rippling `-careers` suffixes, never dotted, never brand-suffixed
    (`gongio`, `ironcladhq`), and case is irrelevant to the CXS endpoint.
    """
    n = re.sub(r"[''`]", "", name.strip().lower())
    detld = re.sub(r"\.(io|com|ai|co|dev|so|app|net|org|xyz)$", "", n)
    forms = [
        re.sub(r"[^a-z0-9]+", "", n),                                  # thesciongroup
        re.sub(r"[^a-z0-9]+", "", detld),                              # honeycomb
        re.sub(r"(inc|llc|ltd|corp|co|company|labs|technologies|technology)$",
               "", re.sub(r"[^a-z0-9]+", "", detld)),                  # legal form dropped
        _first_word(detld),                                            # motorola, brown
    ]
    out, seen = [], set()
    for f in forms:
        if f and len(f) > 1 and f not in seen:
            seen.add(f)
            out.append(f)
    return out


def slug_variants(name: str):
    """Deterministic slug candidates from a company name, most-likely first.

    Handles the real-world cases hit by hand on 2026-07-29..31: Gong's board is
    'gongio', Navan's is still the legacy 'tripactions', Anduril's is
    'andurilindustries', Ironclad's is 'ironcladhq'. Suffix/legal-form stripping
    covers the first class; the rest need a manual slug and are reported as
    unresolved rather than guessed at further.
    """
    n = name.strip().lower()
    n = re.sub(r"[''`]", "", n)
    base = re.sub(r"[^a-z0-9]+", "", n)
    words = re.sub(r"[^a-z0-9 ]+", " ", n).split()
    nospace = "".join(words)
    hyphen = "-".join(words)
    stripped = re.sub(r"(inc|llc|ltd|corp|co|company|labs|technologies|technology)$", "", base)

    # TLD STRIPPING (added 2026-08-31). A company whose NAME is a domain slugs to
    # the bare name far more often than to name-plus-TLD: Honeycomb.io is
    # `honeycomb`, Owner.com is `owner`. This function already knew the inverse
    # (it appends "io" to catch Gong's `gongio`) but never removed one, so both
    # of those were reported unresolved on 2026-08-04 and sat in the unpollable
    # backlog for four weeks with live boards the whole time.
    detld_name = re.sub(r"\.(io|com|ai|co|dev|so|app|net|org|xyz)$", "", n)
    detld = re.sub(r"[^a-z0-9]+", "", detld_name)
    detld_hyphen = "-".join(re.sub(r"[^a-z0-9 ]+", " ", detld_name).split())

    # PUNCTUATION-PRESERVING (added 2026-08-31). Ashby board names may keep a dot:
    # Ambient.ai's board really is `ambient.ai`, not `ambientai`. Every other
    # candidate here is punctuation-stripped by construction, so that board was
    # unreachable no matter how many suffixes were tried.
    dotted = re.sub(r"[^a-z0-9.]+", "", n)

    cands = [base, nospace, hyphen, stripped, detld, detld_hyphen, dotted,
             base + "io", base + "hq",
             # Legal-form suffixes are STRIPPED above but were never ADDED, which
             # is a different miss: The Scion Group's board is `thesciongroupllc`
             # and Advisor360's is `advisor360-llc`. Advisor360's own rejection
             # note has said "the auto-guesser missed the '-llc' slug suffix"
             # since 2026-08-15; it was diagnosed and never fixed until now.
             base + "inc", base + "llc", hyphen + "-llc", hyphen + "-inc",
             base + "industries", base + "ai",
             # Dotted-TLD APPENDING, the inverse of the stripping above (added
             # 2026-08-31). A queue lead named plainly "Ambient" has to reach a
             # board named `ambient.ai`; `base + "ai"` yields `ambientai` and
             # misses it. Common for AI-native companies whose brand IS the
             # domain, and the queue often carries the bare name.
             base + ".ai", base + ".io", base + ".com",
             # Rippling-hosted boards commonly append one of these to the bare
             # name rather than using it plain (seen live 2026-08-12:
             # routeware-careers, gaiias-open-positions, nerdio-careers,
             # alongside bare rippling/supper/tixr/kion) -- harmless no-ops
             # against every other ATS, which just 404 on them.
             hyphen + "-careers", hyphen + "-open-positions", hyphen + "-jobs"]

    # Capitalised variants -- REQUIRED for Ashby and SmartRecruiters, whose board
    # names are CASE-SENSITIVE. Everything above is lowercased by construction
    # (`n = name.strip().lower()`), so before 2026-08-27 a company whose board is
    # named "Lime" or "TrimbleCareers" could never be resolved no matter how many
    # suffixes were tried: every candidate 404'd on a case mismatch alone.
    # Found via a user-surfaced Lime posting whose own embed script pointed at
    # `jobs.ashbyhq.com/Lime` while this function had only ever probed `lime`.
    # Same harmless-no-op property as the Rippling suffixes above: a wrong-case
    # candidate just 404s on the case-insensitive ATSes.
    cased = []
    for c in (base, nospace, hyphen, stripped, detld, dotted):
        if c:
            cased.append(c[:1].upper() + c[1:])          # Lime, Tripactions
    if words:
        cased.append("".join(w.capitalize() for w in words))  # TrimbleCareers-style
    cands += cased

    out, seen = [], set()
    for c in cands:
        if c and len(c) > 1 and c not in seen:
            seen.add(c)
            out.append(c)
    return out


# Last request time per SERVICE, for the politeness pause below.
_SERVICE_LAST_HIT = {}


def _service(url: str) -> str:
    """Registrable domain of a URL: 'greenhouse.io', 'myworkdayjobs.com'.

    Deliberately not the full hostname. Pinpoint and Workday put the tenant in
    the hostname ({slug}.pinpointhq.com, {slug}.wd5.myworkdayjobs.com), so
    keying on the hostname would give every slug its own fresh quota and
    throttle nothing at all -- which is the opposite of the intent.
    """
    host = urlsplit(url).hostname or ""
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _pace(url, budget=None):
    """Politeness pause, measured PER SERVICE rather than globally.

    DELAY exists so we do not hammer any one ATS. It used to be an unconditional
    sleep after every request, which charged the pause to the WRONG party: the
    inner loop walks every supported cheap ATS in a row (see the tuple in
    assess()), so all but one of every full cycle's pauses were spent being
    polite to a host we were not about to contact.

    That was not merely inelegant, it is what made the 60s cap unusable. A
    19-variant name like "Palo Alto Networks" issues one request per variant per
    cheap ATS -- 114 of them when this was measured against six adapters, and it
    grows with every adapter added -- so
    the old global pause put a ~40s floor under the cheap phase alone -- two
    thirds of the budget in time.sleep() before a single byte moved -- and the
    Workday walk the cap was written to bound could never be reached. Measured
    2026-09-03: the cheap phase for that name took 77s, of which 40s was sleep.

    Per-service is also the stricter reading of politeness where it counts. Each
    ATS still sees at most one request per DELAY, and in practice far fewer,
    because a full cycle across every cheap ATS takes longer than DELAY on its own.
    """
    svc = _service(url)
    wait = DELAY - (time.monotonic() - _SERVICE_LAST_HIT.get(svc, 0.0))
    if wait > 0:
        if budget is None:
            time.sleep(wait)
        else:
            budget.sleep(wait)
    _SERVICE_LAST_HIT[svc] = time.monotonic()


def _get(url, budget=None):
    if budget is not None and budget.expired():
        return None
    _pace(url, budget)
    try:
        r = requests.get(url, headers=UA,
                         timeout=TIMEOUT if budget is None else budget.timeout())
        return r if r.status_code == 200 else None
    except Exception:
        return None


def _raw_get(url, budget=None):
    """GET returning the response on ANY HTTP status; None only on network failure.

    _get collapses "the host does not exist" and "the host exists and 404'd"
    into the same None, which is exactly the distinction the Comeet careers-page
    walk needs: a dead domain should be abandoned after one request, while a
    live domain that 404s on /careers is worth trying /jobs on. Every ATS probe
    above genuinely only cares about 200, so they keep using _get.
    """
    if budget is not None and budget.expired():
        return None
    _pace(url, budget)
    try:
        return requests.get(url, headers=UA,
                            timeout=TIMEOUT if budget is None else budget.timeout(),
                            allow_redirects=True)
    except Exception:
        return None


def _confirm_empty(ats: str, slug: str, budget=None):
    """Re-probe a board that came back empty, to tell a real empty board from load noise.

    Added 2026-08-31, from a false positive that reached the repo. A 30-company
    backlog run reported FOUR resolved-but-empty boards -- workable/microsoft-inc,
    workable/lime, workable/frame, workable/trustonic. Re-probed slowly and in
    isolation, every one of them returns 404. Microsoft plainly does not recruit
    through a Workable board called "microsoft-inc"; the signal was an artifact.

    The mechanism: `_get` returns None on any non-200 and the caller turns a 200
    into a list, so a 200 carrying an empty jobs array is indistinguishable from a
    real empty board. Under burst load Workable evidently serves exactly that.
    Greenhouse and Pinpoint appear honest -- greenhouse/appomni and
    pinpoint/coursedog re-confirm as genuinely empty -- but the guard is applied
    uniformly because there is no reason to trust that asymmetry to hold.

    Empties are rare, so this costs almost nothing: one extra request, after a
    pause, only when a board reports zero jobs. Returning False makes the caller
    treat it as no-board, which is the safe direction: under-claiming a board
    costs one missed re-check, over-claiming writes a wrong ats/slug onto a
    company's permanent record and suppresses the manual search that would have
    found the real one.
    """
    if budget is None:
        time.sleep(max(DELAY, 2.0))
    else:
        budget.sleep(max(DELAY, 2.0))
    again = probe(ats, slug, budget)
    return again is not None and len(again) == 0


# SmartRecruiters is the one cheap probe whose endpoint is NOT hardcoded here.
# Every other branch of probe() builds a URL from a literal, which is fine because
# those URLs have never moved; the SmartRecruiters one has already been edited once
# (the limit=100 pagination fix of 2026-08-06) and a second copy of it in this file
# would be a second thing to remember to change. Read it from the same
# `_endpoints` block fetch_smartrecruiters reads, cached so a 15-name harvest does
# not re-parse a 1500-line watchlist per probe.
_SR_ENDPOINT = None

# Pagination cap for the SmartRecruiters probe, matching poll_ats.py's
# SMARTRECRUITERS_MAX_POSTINGS so discovery judges the same board the poller will
# read. NOT first-page-only, unlike the Rippling branch below, and the difference
# is not stylistic: SmartRecruiters serves 100/page and its large boards are the
# ones this project has already been burned by. See the branch for the Canva case.
SMARTRECRUITERS_PROBE_MAX = 500


def smartrecruiters_endpoint():
    """`_endpoints["smartrecruiters"]` from the watchlist, read once."""
    global _SR_ENDPOINT
    if _SR_ENDPOINT is None:
        with open(WATCHLIST, encoding="utf-8") as f:
            _SR_ENDPOINT = json.load(f)["_endpoints"]["smartrecruiters"]
    return _SR_ENDPOINT


def probe(ats: str, slug: str, budget=None):
    """Return [(title, location)] if the board resolves, else None."""
    if ats == "greenhouse":
        r = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", budget)
        if not r:
            return None
        return [(j.get("title", ""), (j.get("location") or {}).get("name", ""))
                for j in r.json().get("jobs", [])]
    if ats == "ashby":
        r = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", budget)
        if not r:
            return None
        return [(j.get("title", ""), j.get("location", ""))
                for j in r.json().get("jobs", [])]
    if ats == "lever":
        r = _get(f"https://api.lever.co/v0/postings/{slug}?mode=json", budget)
        if not r:
            return None
        return [(j.get("text", ""), (j.get("categories") or {}).get("location", ""))
                for j in r.json()]
    if ats == "workable":
        r = _get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true",
                 budget)
        if not r:
            return None
        return [(j.get("title", ""), j.get("location", "") or j.get("city", ""))
                for j in r.json().get("jobs", [])]
    if ats == "pinpoint":
        r = _get(f"https://{slug}.pinpointhq.com/postings.json", budget)
        if not r:
            return None
        out = []
        for j in r.json().get("data", []):
            loc = j.get("location") or {}
            parts = [p.strip() for p in [loc.get("city"), loc.get("province")] if p and p.strip()]
            label = ", ".join(parts) if parts else (loc.get("name") or "")
            out.append((j.get("title", ""), label))
        return out
    if ats == "jazzhr":
        # JazzHR answers 200 for a slug with no board, serving a fixed "JazzHR -
        # Inactive Career Page" instead of redirecting or 404ing. So the title
        # check below is the whole probe: without it a name-variant sweep would
        # "resolve" amazon, microsoft, oracle, cisco and capitalone, all of which
        # return that page (verified 2026-09-03). Reuses the poller's own parser
        # so the probe and the daily fetch cannot drift apart.
        import poll_ats as _P
        r = _raw_get(f"https://{slug}.applytojob.com/apply/", budget)
        if not _P.jazzhr_board_live(r):
            return None
        out = []
        for block in _P.JAZZHR_ITEM_RE.split(r.text)[1:]:
            m = _P.JAZZHR_LINK_RE.search(block)
            if not m:
                continue
            loc = _P.JAZZHR_LOC_RE.search(block)
            out.append((_P._jazzhr_text(m.group(2)),
                        _P._jazzhr_text(loc.group(1)) if loc else ""))
        return out
    if ats == "rippling":
        # First page only (20 postings) -- enough to judge fit-space; the real
        # daily poll (fetch_rippling in poll_ats.py) paginates fully once a
        # company is actually enrolled.
        r = _get(f"https://ats.rippling.com/{slug}/jobs", budget)
        if not r:
            return None
        m = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            r.text, re.DOTALL)
        if not m:
            return None
        try:
            next_data = json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            return None
        queries = (next_data.get("props", {}).get("pageProps", {})
                   .get("dehydratedState", {}).get("queries", []))
        job_query = next(
            (qy for qy in queries
             if isinstance(qy.get("queryKey"), list) and "job-posts" in qy["queryKey"]),
            None)
        if not job_query:
            return None
        items = job_query.get("state", {}).get("data", {}).get("items", []) or []
        out = []
        for j in items:
            locs = j.get("locations") or []
            names = [l.get("name") for l in locs if l.get("name")]
            out.append((j.get("name", ""), ", ".join(names)))
        return out
    if ats == "smartrecruiters":
        # Added 2026-09-03, the SmartRecruiters half of the same gap probe_comeet
        # closed the same day: poll_ats.py has read this ATS since 2026-06-30
        # (fetch_smartrecruiters, ServiceNow and Nexthink polled through it daily)
        # while discovery could not resolve it, so a SmartRecruiters-hosted company
        # was written to `rejected` with unpollable=True -- the one flag that stops
        # it ever being re-checked. Unlike Comeet this needed no new resolution
        # model: the boards ARE slug-addressed, and slug_variants() has generated
        # the capitalised forms they require since 2026-08-27.
        #
        # RETURNS None, NEVER [], AND THAT IS THE WHOLE DIFFICULTY. The postings
        # API answers 200 with {"totalFound": 0, "content": []} for a slug that
        # does not exist rather than 404ing, so "no such company" and "real board,
        # nothing posted" are the same response. An empty result here is therefore
        # overwhelmingly a slug collision, not a quiet board, and it must not reach
        # assess()'s _confirm_empty path: that guard exists to re-probe a flaky
        # 200-with-no-jobs, and a re-probe of a nonexistent slug returns the same
        # confident 200, so it would CONFIRM the collision and write a wrong
        # ats/slug onto the company's permanent record. This is not hypothetical --
        # it is the failure probe_workday's docstring cites, where a 2026-08-28
        # sweep reported ten companies resolved and every one was a collision.
        #
        # PAGINATES, and must. This was first-page-only for a few hours on
        # 2026-09-03, copying the Rippling branch's "enough to judge fit-space"
        # reasoning, and that reasoning is wrong for this ATS specifically -- it
        # reintroduced one layer up the exact bug _smartrecruiters_notes records
        # fetch_smartrecruiters being fixed for on 2026-08-06, where a live
        # Atlanta CSM role at ServiceNow was invisible because it sorted past
        # position 100. Caught the same day on Canva: 267 postings, and all FOUR
        # of its US Implementation Manager reqs (tier2) sit past the first page,
        # so the probe reported the board as having zero fit-space and the
        # company stayed rejected. A board big enough to need page two is exactly
        # the board most likely to be carrying something.
        #
        # Cost is negligible because pagination only happens on a board that has
        # already resolved, which is rare -- 12 of 213 names in the backlog sweep.
        base = smartrecruiters_endpoint().format(slug=slug)
        sep = "&" if "?" in base else "?"
        postings = []
        offset = 0
        while offset < SMARTRECRUITERS_PROBE_MAX:
            r = _get(f"{base}{sep}offset={offset}", budget)
            if not r:
                break
            try:
                data = r.json()
            except ValueError:
                break
            page = data.get("content") or []
            total = data.get("totalFound")
            # The no-board test is the FIRST page's answer only. A later page
            # failing or coming back short is a truncated read of a real board,
            # which is worth keeping; page one coming back empty is a collision.
            if not postings and (not page or (isinstance(total, int) and total <= 0)):
                return None
            if not page:
                break
            postings.extend(page)
            offset += len(page)
            if isinstance(total, int) and offset >= total:
                break
        if not postings:
            return None
        out = []
        for j in postings:
            # Same location assembly as poll_ats.py's smartrecruiters branch in
            # extract_location, so a board scores here the way it will score once
            # enrolled -- including folding `remote` into the string, which is what
            # us_reachable / tier3_location_ok read.
            loc = j.get("location") or {}
            full = loc.get("fullLocation") or ", ".join(
                p for p in [loc.get("city"), (loc.get("country") or "").upper()] if p)
            if loc.get("remote"):
                full = f"Remote {full}".strip()
            out.append((j.get("name", ""), full))
        return out
    return None


WORKDAY_HOSTS = ["wd1", "wd5", "wd3", "wd12", "wd101"]
WORKDAY_SITES = ["Careers", "External", "ExternalCareers", "External_Career_Site",
                 "Search", "careers", "Jobs", "US", "Global", "ext", "CareerSite"]


def probe_workday(slug: str, budget=None):
    """Resolve a Workday board. Returns ([(title, location)], meta) or (None, None).

    Workday is addressed by THREE parts (tenant, host, site) rather than the
    single slug every other ATS here uses, so it gets its own function instead
    of being bent into probe(). Added 2026-08-28: harvest_ats.py probed five
    ATSes and never Workday, which is why it rejected General Motors, Brown &
    Brown, and Reputation as unpollable even though all three had large live
    Workday boards. The documented site:myworkdayjobs.com fallback was supposed
    to catch those by hand and reliably did not, because the rejection reason
    said "worth one manual search if the company matters" and nobody ran it.

    Cost is controlled by the STATUS CODE, not by DNS. myworkdayjobs.com serves
    wildcard DNS -- every tenant name resolves, including gibberish -- so a DNS
    gate was tried first and did nothing but add latency ahead of 55 requests per
    slug variant (5 hosts x 11 sites), which timed out a three-company test run at
    600s. The CXS endpoint distinguishes the two failures cleanly and fast (~0.3s):

        422  tenant does not exist on this host  -> stop, skip its 11 site names
        404  tenant exists, wrong site name      -> keep walking the site list
        200  hit

    So one request rules a host out. The common all-miss case is 5 requests per
    slug variant instead of 55, and the full site walk only happens on a host that
    has already proven the tenant is real.

    Requires total > 0. An empty-but-valid board is treated as no board, matching
    how assess() already handles the other ATSes -- and more sharply, a probe that
    accepts a zero count is how the 2026-08-28 sweep initially reported ten
    companies as resolved when every one was a slug collision (the SmartRecruiters
    API returns totalFound:0 rather than 404 for nonexistent slugs).
    """
    # Static site names plus ones derived from the tenant. The derived forms are
    # not speculative: crowdstrikecareers, TrimbleCareers, and SynechronCareers
    # are all real boards resolved by hand, and they share this shape. They cost
    # nothing in the common case, because a 422 short-circuits the whole list
    # before any of them is tried; they only lengthen the walk on a host where the
    # tenant has already proven real, which is exactly when trying harder pays.
    sites = WORKDAY_SITES + [
        f"{slug}careers", f"{slug}Careers", f"{slug}_careers",
        f"Careers_{slug.upper()}",
    ]
    body = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}
    for host in WORKDAY_HOSTS:
        if budget is not None and budget.expired():
            return None, None
        fqdn = f"{slug}.{host}.myworkdayjobs.com"
        for site in sites:
            # Checked per SITE, not just per host. The 422 short-circuit only
            # helps when the tenant is absent; the expensive case is a tenant
            # that RESOLVES and 404s on all ~15 site names, and that walk lives
            # entirely inside this inner loop.
            if budget is not None and budget.expired():
                return None, None
            url = f"https://{fqdn}/wday/cxs/{slug}/{site}/jobs"
            _pace(url, budget)
            try:
                r = requests.post(url, json=body, headers=UA,
                                  timeout=TIMEOUT if budget is None else budget.timeout())
            except Exception:
                break          # network trouble on this host; try the next one
            if r.status_code == 422:
                break          # no such tenant here -- don't try the other sites
            if r.status_code != 200:
                continue       # 404: wrong site name, keep walking
            try:
                d = r.json()
            except Exception:
                continue
            if not isinstance(d.get("total"), int) or d["total"] <= 0:
                continue
            jobs = [(p.get("title", ""), p.get("locationsText", ""))
                    for p in d.get("jobPostings", [])]
            return jobs, {"wd_host": fqdn, "wd_tenant": slug, "wd_site": site,
                          "total": d["total"]}
    return None, None


# ---------------------------------------------------------------------------
# Comeet
# ---------------------------------------------------------------------------
# Added 2026-09-03, from the FOURTH instance of the "unsupported-ATS-looks-like-
# no-ATS" miss class named in watchlist_companies.json -> _comeet_notes (Napier
# AI/Pinpoint, Nerdio/Rippling, Stampli/Comeet were one through three). Upwind
# Security is the sharpest of the four, because Comeet is NOT unsupported here:
# poll_ats.py has had fetch_comeet since 2026-08-20 and polls Stampli through it
# daily. Only DISCOVERY was broken, and it was broken structurally rather than
# by a missing slug guess.
#
# WHY NO AMOUNT OF SLUG WIDENING COULD EVER HAVE FIXED THIS. Every other adapter
# in this file is addressed by a name-derived string, so slug_variants() is the
# whole resolution strategy and widening it (as on 2026-08-31) buys real
# coverage. Comeet has no slug at all: its API is keyed by a per-company
# `comeet_uid` ("49.004", "F6.007") and a public widget `comeet_token`, neither
# of which is derivable from anything -- they exist only in the company's own
# careers page. So Upwind was rejected on 2026-09-02 with "No board resolved
# from deterministic name-variant slugs", which was true and useless: it had a
# live 58-position board carrying a "Technical Account Manager (US Remote)" req,
# and the LinkedIn harvest had surfaced that same req twice while the poller
# structurally could not see it.
#
# The resolution path is therefore inverted from every other probe: name ->
# careers page -> scraped credentials -> board, instead of name -> slug ->
# board. That is more speculative than a slug guess, so it runs LAST among the
# cheap probes and its result is written with the careers URL it came from
# (comeet_careers_url on the watchlist entry) so a wrong-company hit is
# auditable rather than silent.
COMEET_ENDPOINT = ("https://www.comeet.co/careers-api/2.0/company/{uid}/positions"
                   "?token={token}&details=false")

# details=false, unlike poll_ats.py's ATS_ENDPOINTS["comeet"]. The position list
# is identical either way; `details` only adds the Description/Requirements HTML,
# which the poller flattens for the industry exclusion and this file has no use
# for. Dropping it takes the Upwind payload from ~287KB to a fraction of that.

# Markup the Comeet widget leaves on a careers page. The class names come from
# the widget's own DOM and the last two from the two embed shapes below.
COMEET_MARKERS = ("comeet-outer-wrapper", "comeet-groups-list", "comeet-position-info",
                  "comeetvar", "careers-api/2.0/company")

# Paths worth trying on a domain that has proven live. Ordered by how common
# they are; /careers alone covers both companies confirmed on Comeet so far.
CAREERS_PATHS = ("/careers", "/jobs", "/company/careers", "/about/careers", "/join-us")

# TLDs tried when guessing a company's own domain. Deliberately short: this is
# the speculative half of the walk and each miss is a DNS failure, which is
# cheap but not free.
DOMAIN_TLDS = ("com", "io", "ai", "co")

# A domain that resolves but has no Comeet widget still costs a full path walk,
# so cap how many live domains are walked. Two is enough in practice (the apex
# and one alternate spelling); the third is slack for names whose first-word
# guess collides with an unrelated live site.
MAX_CAREERS_DOMAINS = 3

# Same-origin scripts followed when a page shows Comeet markup but no inline
# credentials -- see comeet_credentials().
MAX_SCRIPT_HOPS = 3

# Embed shape 1, the Comeet WordPress plugin: a wp_localize_script block reading
# `var comeetvar = {"comeet_token":"...","comeet_uid":"...", ...}`. Both
# companies confirmed live on Comeet (Stampli 2026-08-20, Upwind 2026-09-03) use
# this, and in both the credentials sit inline in the raw careers HTML.
_COMEET_WP_UID = re.compile(r'"comeet_uid"\s*:\s*"([^"]{2,32})"')
_COMEET_WP_TOKEN = re.compile(r'"comeet_token"\s*:\s*"([^"]{8,64})"')

# Embed shape 2, the generic script embed: the credentials ride in the URL of a
# comeet.co careers-api include rather than in a JS object. Matched against the
# page source AND against followed script bodies, since a bootstrap loader can
# build this URL rather than emitting it.
_COMEET_API_URL = re.compile(
    r'careers-api/2\.0/company/([A-Za-z0-9][A-Za-z0-9.\-]{1,30})'
    r'/[A-Za-z_]+\?[^"\'\s>]{0,200}?token=([A-Za-z0-9]{8,64})')

# Loose fallback for a hand-rolled embed that assigns the two values separately.
# Kept tight on SHAPE rather than on key name -- a Comeet uid is two chars, a
# dot, three chars ("49.004", "F6.007"), and the token is a long hex string --
# because bare `uid`/`token` keys appear all over a marketing page's analytics
# and consent scripts. Only consulted once the markers above already proved the
# page is a Comeet page.
_COMEET_LOOSE_UID = re.compile(
    r'\buid\s*[:=]\s*["\']([A-Za-z0-9]{2}\.[A-Za-z0-9]{3})["\']')
_COMEET_LOOSE_TOKEN = re.compile(
    r'\btoken\s*[:=]\s*["\']([A-Fa-f0-9]{16,64})["\']')

_COMEET_SCRIPT_SRC = re.compile(r'<script[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)


def looks_like_comeet(html: str) -> bool:
    return any(m in html for m in COMEET_MARKERS)


def _credentials_from_text(text: str):
    """(uid, token) from one document, or None. Tries both embed shapes."""
    uid = _COMEET_WP_UID.search(text)
    token = _COMEET_WP_TOKEN.search(text)
    if uid and token:
        return uid.group(1), token.group(1)
    pair = _COMEET_API_URL.search(text)
    if pair:
        return pair.group(1), pair.group(2)
    uid = _COMEET_LOOSE_UID.search(text)
    token = _COMEET_LOOSE_TOKEN.search(text)
    if uid and token:
        return uid.group(1), token.group(1)
    return None


def comeet_credentials(html: str, page_url: str, budget=None):
    """Scrape (comeet_uid, comeet_token) from a careers page, or None.

    The credentials are usually inline (the WordPress plugin emits them in a
    `comeetvar` block), but they do not have to be: a site can include a
    bootstrap script that carries them instead, leaving the raw HTML with only
    the widget's wrapper divs. So when the page is recognisably a Comeet page
    and yet holds no credentials, follow its own comeet-named scripts and look
    there. Bounded at MAX_SCRIPT_HOPS and to same-origin comeet-named includes
    -- this is a credential scrape, not a crawl, and following arbitrary
    third-party scripts off a marketing page is not something this script should
    ever do.
    """
    found = _credentials_from_text(html)
    if found:
        return found
    origin = "{0.scheme}://{0.netloc}".format(urlsplit(page_url))
    hops = 0
    for m in _COMEET_SCRIPT_SRC.finditer(html):
        if hops >= MAX_SCRIPT_HOPS:
            break
        src = m.group(1)
        if "comeet" not in src.lower():
            continue
        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/"):
            src = origin + src
        elif not src.startswith("http"):
            continue
        if urlsplit(src).netloc not in (urlsplit(page_url).netloc, "www.comeet.co",
                                        "comeet.co"):
            continue
        hops += 1
        r = _get(src, budget)
        if r is None:
            continue
        found = _credentials_from_text(r.text)
        if found:
            return found
    return None


def domain_candidates(name: str):
    """Plausible own-domains for a company, most-specific first.

    Comeet is reached through the company's own site, so this is the one place
    in the file that has to guess a DOMAIN rather than a board slug. Full name
    before first word ("upwindsecurity.com" before "upwind.com") because the
    longer form is far less likely to collide with an unrelated business; the
    hit that matters, Upwind's real "upwind.io", is found on the first-word pass.
    """
    n = re.sub(r"[''`]", "", name.strip().lower())

    # A name that already IS a domain resolves to itself and nothing else.
    if re.search(r"\.(io|com|ai|co|dev|so|app|net|org|xyz)$", n):
        return [re.sub(r"[^a-z0-9.\-]+", "", n)]

    words = re.sub(r"[^a-z0-9 ]+", " ", n).split()
    nospace = "".join(words)
    stripped = re.sub(r"(inc|llc|ltd|corp|co|company|labs|technologies|technology)$",
                      "", nospace)
    bases, seen = [], set()
    for b in (nospace, stripped, _first_word(n)):
        if b and len(b) > 2 and b not in seen:
            seen.add(b)
            bases.append(b)
    return [f"{b}.{tld}" for b in bases for tld in DOMAIN_TLDS]


def _redirected_home(response) -> bool:
    """True if a careers URL landed on the site root -- i.e. the path did not exist.

    A soft 404. It matters more here than the status code does, because the two
    pages this walk must tell apart are "the careers page" and "the homepage",
    and a homepage on a Comeet-using site trips looks_like_comeet() on its
    sitewide script and CSS includes while carrying no credentials at all. That
    is not hypothetical: upwindsecurity.io is a parked domain that redirects
    every path to https://www.upwind.io/, whose 490KB homepage matches the
    markers, yields no credentials, and then costs three script hops to
    disprove.
    """
    return urlsplit(response.url).path.strip("/") == ""


def probe_comeet(name: str, budget=None):
    """Resolve a Comeet board from a company NAME. ([(title, location)], meta) or (None, None).

    Walks name-derived domains, and on each one that actually answers, walks a
    short list of careers paths looking for the widget.

    Three rules keep this from turning into an open-ended fetch of company
    marketing pages, which is the real cost risk here -- a careers page is
    hundreds of KB where an ATS API response is a few. All three were added
    after measuring the Upwind walk at 63s standalone, against a 60s
    per-company budget that also has to cover the slug walk. With them it is
    22s, and the whole harvest of that name went 57.5s -> 47.6s. Measured
    misses are cheaper still (Nscale 3.4s, 11 requests), because rule three
    ends most domains after a single page:

      - A path that redirects to the site root did not exist (_redirected_home).
        Skip it, and abandon that domain: a domain that answers /careers from
        its homepage is ignoring paths, so its other paths will do the same.
        Re-queue where it redirected TO instead, which is how a parked
        name-variant domain leads to the real site rather than wasting the walk.
      - A domain whose careers page resolves onto a host already walked is a
        duplicate, not a second chance.
      - A 200 careers page WITHOUT Comeet markup ends that domain's walk. The
        careers page has been found and it is not Comeet; trying four more paths
        on the same site cannot change that.

    Requires a non-empty board, matching probe() and probe_workday(): an
    empty-or-invalid response must not be allowed to write a uid/token pair onto
    a company's permanent record.
    """
    queue = list(domain_candidates(name))
    seen_domains = set(queue)
    walked_hosts = set()
    walked = 0
    while queue:
        if budget is not None and budget.expired():
            return None, None
        if walked >= MAX_CAREERS_DOMAINS:
            break
        domain = queue.pop(0)
        first = _raw_get(f"https://{domain}{CAREERS_PATHS[0]}", budget)
        if first is None:
            continue          # domain does not resolve; nothing else to try here
        host = urlsplit(first.url).netloc
        if host in walked_hosts:
            continue          # a second spelling of a site already walked
        if _redirected_home(first):
            # Parked or path-ignoring domain. Follow it to the host it actually
            # serves, and try the careers paths there.
            if host and host not in seen_domains:
                seen_domains.add(host)
                queue.append(host)
            continue
        walked_hosts.add(host)
        walked += 1
        for path in CAREERS_PATHS:
            if budget is not None and budget.expired():
                return None, None
            url = f"https://{domain}{path}"
            r = first if path == CAREERS_PATHS[0] else _raw_get(url, budget)
            if r is None or r.status_code != 200 or _redirected_home(r):
                continue
            html = r.text
            if not looks_like_comeet(html):
                break         # real careers page, different ATS -- stop here
            creds = comeet_credentials(html, r.url or url, budget)
            if not creds:
                continue
            uid, token = creds
            api = _get(COMEET_ENDPOINT.format(uid=uid, token=token), budget)
            if api is None:
                continue
            try:
                positions = api.json()
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(positions, list) or not positions:
                continue
            jobs = []
            for p in positions:
                if p.get("is_internal"):
                    continue
                loc = p.get("location") or {}
                # Mirrors parse_location's comeet branch in poll_ats.py: city +
                # state, falling back to the location name. is_remote is
                # deliberately NOT consulted -- it was true on 19/19 Stampli
                # postings, 17 of which describe in-office days, and reading it
                # here would hand tier3's location gate a constant.
                parts = [q.strip() for q in (loc.get("city"), loc.get("state"))
                         if q and q.strip()]
                jobs.append((p.get("name", ""),
                             ", ".join(parts) if parts else (loc.get("name") or "")))
            if not jobs:
                continue
            return jobs, {"comeet_uid": uid, "comeet_token": token,
                          "comeet_careers_url": r.url or url, "total": len(jobs)}
    return None, None


def comeet_slug(name: str) -> str:
    """Human-readable stand-in for the slug Comeet does not have.

    validate_config.py requires `slug` on every watchlist entry and the poller
    prefixes dedup keys with it, but for Comeet it addresses nothing -- the API
    is keyed by comeet_uid/comeet_token. Stampli's hand-written entry set it to
    'stampli', so follow that: the company name, lowercased and hyphenated.
    """
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


def us_reachable(loc: str) -> bool:
    return any(h in (loc or "").lower() for h in US_HINTS)


def tier3_location_ok(loc: str) -> bool:
    """Narrower than us_reachable(): Atlanta or remote-US only.

    us_reachable() is deliberately broad (any US state or major city), which is
    right for tier1/tier2 but wrong for tier3 -- a Customer Success Manager in
    Boston is the stretch title WITHOUT the location premium that justifies
    taking it. This predicate is what makes the tier3 gate meaningful, so keep it
    strict; loosening it to any US city silently restores the ungated behaviour.
    """
    loc = (loc or "").lower()
    if any(m in loc for m in NON_US_MARKERS):
        return False
    if NON_US_CODES & set(re.split(r"[^a-z0-9-]+", loc)):
        return False
    if any(h in loc for h in ATLANTA_HINTS):
        return True
    # A bare "Remote" with no country marker is read as remote-US. Slight
    # over-admission risk on non-US boards, accepted because auto-enrollment is
    # LOW priority and every enrollment is reported in the run digest.
    return any(h in loc for h in REMOTE_HINTS)


def tier_breakdown(strong):
    """'2 tier2, 1 tier3(location-gated)' -- so an enrollment reason records WHICH
    tiers carried it, not just a count. Without this a tier3-only enrollment is
    indistinguishable from a tier1 one when reviewing the watchlist later."""
    counts = {}
    for _, _, tier in strong:
        label = tier.split("_")[0]
        if tier == TIER3_TIER:
            label += "(location-gated)"
        counts[label] = counts.get(label, 0) + 1
    return ", ".join(f"{n} {t}" for t, n in sorted(counts.items()))


def load_known():
    wl = json.load(open(WATCHLIST, encoding="utf-8"))
    q = json.load(open(QUEUE, encoding="utf-8"))
    names = {c["name"].lower() for c in wl["companies"]}
    pairs = {(c.get("ats"), (c.get("slug") or "").lower())
             for c in wl["companies"] if c.get("ats") and c.get("slug")}
    # Deliberately excludes "pending": --from-pending sources its targets from
    # that same bucket, so including it here made every pending entry match its
    # own name and get skipped as "already known" -- --from-pending was a silent
    # no-op until this fix (found 2026-08-01, targets always skipped in the same run
    # that built them).
    for bucket in ("enrolled", "rejected"):
        for e in q.get(bucket, []):
            if e.get("name"):
                names.add(str(e["name"]).lower())
    return wl, q, names, pairs


def _score_board(jobs, matcher, hard_excluded):
    """Split a board's titles into the strong-fit subset used for enrollment."""
    strong = []
    for title, loc in jobs:
        if hard_excluded(title):
            continue
        m = matcher.match_exact(title)
        if not m:
            continue
        tier = m[0]
        if tier in STRONG_TIERS and us_reachable(loc):
            strong.append((title, loc, tier))
        elif tier == TIER3_TIER and tier3_location_ok(loc):
            strong.append((title, loc, tier))
    return strong


def assess(name, matcher, hard_excluded, known_pairs, skip_workday=False,
           skip_comeet=False, budget_seconds=PER_COMPANY_BUDGET):
    """Resolve a company to (ats, slug, strong_hits, total_jobs) or a reason.

    skip_workday=True stops before the Workday tenant walk; skip_comeet=True
    stops before the Comeet careers-page walk. See main().

    budget_seconds caps the WALL CLOCK for this one company across every probe
    (see the Budget class). On a trip this returns a `timed_out` result rather
    than raising: a name that ran out of clock is a name we could not resolve,
    which is the same actionable state as no-board, and the caller records it
    with a reason that says so. Raising would abort the whole batch, which is
    the failure mode being fixed here -- the point is that one slow name must
    not cost the other fourteen. 0 or None disables the cap entirely.
    """
    budget = Budget(budget_seconds) if budget_seconds else None

    def timed_out(phase):
        return {"timed_out": True, "phase": phase, "empty_hits": empty_hits,
                "elapsed": budget.elapsed(), "budget": budget.seconds}

    # Boards that resolved but returned zero jobs. Remembered rather than
    # discarded (added 2026-08-31): continuing to look is right, but FORGETTING
    # was a reporting bug. Before this, a company whose only hit was an empty
    # board fell through to `return None` and was written up as "No board
    # resolved from deterministic name-variant slugs ... worth one manual
    # site:myworkdayjobs.com search", tagged unpollable=True. That is false on
    # both counts: the board was found, and no search can help.
    #
    # AppOmni is the case. greenhouse/appomni resolves and returns 0 jobs; it was
    # rejected 2026-08-04 as no-board, which put it on the weekly unpollable
    # punch list and cost a manual search on 2026-08-31 that could never have
    # paid off. "Board found, currently empty" and "no board exists" need
    # different reasons because they need different actions: the first is one
    # cheap API re-check, the second is human research.
    empty_hits = []
    for slug in slug_variants(name):
        # SmartRecruiters runs LAST of the cheap probes. It is as cheap as any of
        # them (one JSON GET), so this is a collision-risk ordering, not a cost
        # one: its API cannot 404 a bad slug, so it is the branch most likely to
        # answer for the wrong company. Letting a genuine Greenhouse or Ashby
        # board answer first costs nothing and removes that chance entirely.
        for ats in ("greenhouse", "ashby", "lever", "workable", "pinpoint",
                    "rippling", "jazzhr", "smartrecruiters"):
            if budget is not None and budget.expired():
                return timed_out("cheap-ATS slug walk")
            if (ats, slug) in known_pairs:
                continue
            jobs = probe(ats, slug, budget)
            if jobs is None:
                continue
            if not jobs:
                # Keep looking under other slugs before concluding anything; an
                # empty board is weak evidence that we found the right company
                # at all. But hold on to it in case nothing better turns up --
                # and only after confirming it is a real empty board rather than
                # a load artifact (see _confirm_empty).
                if _confirm_empty(ats, slug, budget):
                    empty_hits.append((ats, slug))
                continue
            return {"ats": ats, "slug": slug, "total": len(jobs),
                    "strong": _score_board(jobs, matcher, hard_excluded)}

    # COMEET, after every slug-addressable ATS has failed and before Workday.
    #
    # Ordered here for two reasons. It cannot run earlier: resolving a Comeet
    # board means guessing the company's own domain and fetching marketing
    # pages, which is both more speculative and (per page) far heavier than a
    # slug probe, so it must not run against a company whose Greenhouse board
    # would have answered on the first try. And it runs before Workday because
    # it is much cheaper -- a handful of requests that mostly fail at DNS,
    # against Workday's 5 hosts x ~15 site names per tenant.
    #
    # See the Comeet section above for why the discovery gap was structural.
    if not skip_comeet:
        if budget is not None and budget.expired():
            return timed_out("Comeet careers-page walk")
        jobs, meta = probe_comeet(name, budget)
        if jobs:
            slug = comeet_slug(name)
            if ("comeet", slug) not in known_pairs:
                res = {"ats": "comeet", "slug": slug, "total": meta["total"],
                       "strong": _score_board(jobs, matcher, hard_excluded)}
                res.update({k: meta[k] for k in
                            ("comeet_uid", "comeet_token", "comeet_careers_url")})
                return res

    # Workday LAST, and only once every cheaper ATS has failed for every slug
    # variant. It is the most expensive probe here (DNS gate per host, then up
    # to 11 site names) and the least likely to hit, so running it first would
    # slow down the common case for no benefit. Added 2026-08-28 -- see
    # probe_workday for why this gap mattered.
    # BOUND THE WORKDAY SLUG SET (added 2026-08-31, with the slug-variant widening
    # the same day). Workday is by far the most expensive probe -- it walks 11
    # common site names plus 4 derived ones per tenant, ~12s worst case -- and
    # this loop used to run it against EVERY slug variant. Widening the variant
    # list from 13 to ~23 candidates therefore multiplied the slowest probe and
    # pushed a 4-company run past 7 minutes, which would have made the daily
    # 15-company harvest unusable.
    #
    # Workday TENANTS are plain-name-shaped by construction (`equifax`, `humana`,
    # `reputation`, `salesforce`) or a short abbreviation. They are never the
    # Rippling-style `-careers` / `-open-positions` suffixes, never dotted
    # (`ambient.ai`), never brand-suffixed (`gongio`, `ironcladhq`), and case does
    # not matter to the CXS endpoint. So build the tenant-plausible set directly
    # rather than slicing slug_variants positionally -- a positional slice fills
    # up with `+io`/`+hq` forms for single-word names, which are pure waste here.
    # SKIP ENTIRELY on request (added 2026-09-02). The bound above is per slug;
    # it does not bound the batch. On 2026-09-02 a 16-company --from-pending run
    # that included several large enterprises with live Workday tenants (Palo
    # Alto Networks, RSA Security, Forescout, Worldwide Clinical Trials) was
    # SIGKILLed at ~10 min and, re-run, was still silent past 40 min. A tenant
    # that resolves but matches no site name costs the full walk, and five hosts
    # x ~15 sites x TIMEOUT=20s is the worst case per slug, so a handful of such
    # names in one batch is enough. --skip-workday lets the cheap ATSes run to
    # completion so a stuck Workday probe cannot hold the whole queue hostage;
    # the names it leaves unresolved are reported as no-board in the usual way
    # and keep their manual site:myworkdayjobs.com fallback.
    # The wall-clock cap (2026-09-03) is the real fix the flag was standing in
    # for: it bounds the product of the nested loops rather than any one factor,
    # so a Workday walk that would have run for an hour is cut at the cap and
    # reported against a named company instead of stalling the batch.
    wd_slugs = [] if skip_workday else workday_slug_candidates(name)
    for slug in wd_slugs:
        if budget is not None and budget.expired():
            return timed_out("Workday tenant walk")
        if ("workday", slug) in known_pairs:
            continue
        jobs, meta = probe_workday(slug, budget)
        if not jobs:
            continue
        res = {"ats": "workday", "slug": slug, "total": meta["total"],
               "strong": _score_board(jobs, matcher, hard_excluded)}
        res.update({k: meta[k] for k in ("wd_host", "wd_tenant", "wd_site")})
        return res

    # A trip on the LAST slug leaves both loops normally, so re-check here.
    # Without this the run would report a truncated walk as a clean no-board,
    # which is the exact conflation this cap exists to prevent: "we looked
    # everywhere and found nothing" and "we ran out of clock" need different
    # follow-ups, and only the second one is worth re-running.
    if budget is not None and budget.tripped:
        return timed_out("Workday tenant walk" if wd_slugs else "cheap-ATS slug walk")

    # Nothing had jobs anywhere. If a board DID resolve and was merely empty,
    # say that instead of claiming no board exists (see empty_hits above).
    if empty_hits:
        ats, slug = empty_hits[0]
        return {"ats": ats, "slug": slug, "total": 0, "strong": [],
                "empty_board": True, "empty_hits": empty_hits}
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", nargs="*", default=[])
    ap.add_argument("--names-file",
                    help="JSON file holding a list of company names. Same effect as "
                         "--names (the already-known check is bypassed), but usable "
                         "with far more names than fit sanely on a command line. "
                         "Added 2026-08-21 to re-check the 66 fit-space rejections "
                         "against the newly location-gated tier3 rule.")
    ap.add_argument("--from-pending", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--prune", action="store_true")
    ap.add_argument("--skip-workday", action="store_true",
                    help="Probe only Greenhouse/Ashby/Lever/Workable/Pinpoint/Rippling/"
                         "JazzHR/SmartRecruiters. "
                         "Added 2026-09-02 after the Workday walk hung two full runs. "
                         "Since the per-company wall-clock cap landed (2026-09-03) this "
                         "is an option for trimming a run, not a requirement for large "
                         "batches; see the Budget class.")
    ap.add_argument("--skip-comeet", action="store_true",
                    help="Skip the Comeet careers-page walk (name -> own domain -> "
                         "scraped comeet_uid/comeet_token). Unlike every other probe "
                         "here this one fetches company marketing pages, so it is the "
                         "one to drop when a run must stay light.")
    ap.add_argument("--budget-seconds", type=float, default=PER_COMPANY_BUDGET,
                    help=f"Wall-clock cap per company across all probes "
                         f"(default {PER_COMPANY_BUDGET:g}s). 0 disables the cap and "
                         f"restores the pre-2026-09-03 unbounded behaviour -- only "
                         f"sensible on a one-name run you are watching.")
    args = ap.parse_args()

    if args.names_file:
        with open(args.names_file, encoding="utf-8") as f:
            loaded = json.load(f)
        if not isinstance(loaded, list):
            print("--names-file must contain a JSON list of names", file=sys.stderr)
            return 2
        args.names = list(args.names) + [str(n) for n in loaded]

    sys.path.insert(0, SCRIPT_DIR)
    import poll_ats as P

    wl, q, known_names, known_pairs = load_known()
    P._init_config(wl)
    matcher = P.TitleMatcher(wl)

    if args.prune:
        return prune(wl, matcher, P.title_hard_excluded)

    pending_by_name = {e["name"].lower(): e for e in q.get("pending", []) if e.get("name")}

    targets = list(args.names)
    if args.from_pending:
        targets += [e["name"] for e in q.get("pending", []) if e.get("name")]
    if not targets:
        print("nothing to do: pass --names or --from-pending")
        return 0

    # PROGRESS IS PRINTED PER COMPANY AND FLUSHED (added 2026-09-03). Every
    # print here used to inherit Python's block buffering, so a run redirected
    # to a file or read through a pipe -- which is how the scheduled pipeline
    # runs it -- emitted absolutely nothing until the process exited. That is
    # why the 2026-09-02 hang was diagnosed only by wall-clock: a stalled run
    # and a slow-but-healthy run looked identical from outside, and there was no
    # way to name the company that was stuck. The `-> name` line goes out BEFORE
    # the probing starts, so whatever company is on the last printed line is the
    # one currently in flight.
    enrollable, no_board, no_fit, empty_board, skipped = [], [], [], [], []
    timed_out = []
    run_started = time.monotonic()
    total_targets = len(targets)
    for idx, name in enumerate(targets, 1):
        if name.lower() in known_names and not args.names:
            skipped.append(name)
            print(f"  [{idx}/{total_targets}] -> {name:24s} already known, skipped",
                  flush=True)
            continue
        print(f"  [{idx}/{total_targets}] -> {name}", flush=True)
        t0 = time.monotonic()
        res = assess(name, matcher, P.title_hard_excluded, known_pairs,
                     skip_workday=args.skip_workday,
                     skip_comeet=args.skip_comeet,
                     budget_seconds=args.budget_seconds)
        took = f"{time.monotonic() - t0:5.1f}s"
        if res is not None and res.get("timed_out"):
            timed_out.append((name, res))
            print(f"  [TO] {name:24s} {took} hit the {res['budget']:g}s cap during "
                  f"the {res['phase']}; unresolved", flush=True)
            continue
        if res is None:
            no_board.append((name, None))
            print(f"  [--] {name:24s} {took} no board resolved from name variants",
                  flush=True)
            continue
        if res.get("empty_board"):
            empty_board.append((name, res))
            print(f"  [00] {name:24s} {took} {res['ats']}/{res['slug']:20s} "
                  f"board resolves but returns 0 jobs", flush=True)
            continue
        if not res["strong"]:
            no_fit.append((name, res))
            print(f"  [..] {name:24s} {took} {res['ats']}/{res['slug']:20s} "
                  f"{res['total']:>4} jobs, 0 US fit-titles", flush=True)
            continue
        enrollable.append((name, res))
        print(f"  [OK] {name:24s} {took} {res['ats']}/{res['slug']:20s} "
              f"{res['total']:>4} jobs, {len(res['strong'])} fit-titles "
              f"({tier_breakdown(res['strong'])})", flush=True)
        for t, l, tier in res["strong"][:3]:
            # tier2c_tooling_systems and tier2_strong_overlap both truncate to
            # "tier2" at 5 chars, so label from the full tier name instead.
            label = {"tier1_true_match": "tier1", "tier2_strong_overlap": "tier2",
                     "tier2c_tooling_systems": "tier2c",
                     TIER3_TIER: "tier3*"}.get(tier, tier[:6])
            print(f"         [{label:6s}] {t[:44]:44s} | {str(l)[:24]}", flush=True)
        if any(tier == TIER3_TIER for _, _, tier in res["strong"]):
            print("         * tier3 counted only because the role is Atlanta or remote-US",
                  flush=True)

    print(f"\nenrollable={len(enrollable)} no_fit={len(no_fit)} "
          f"empty_board={len(empty_board)} no_board={len(no_board)} "
          f"timed_out={len(timed_out)} already_known_skipped={len(skipped)} "
          f"[{time.monotonic() - run_started:.0f}s total]", flush=True)
    if timed_out:
        print("TIMED OUT (unresolved, safe to re-run individually): "
              + ", ".join(n for n, _ in timed_out), flush=True)

    if not args.apply:
        print("dry run; re-run with --apply to enroll", flush=True)
        return 0

    today = __import__("datetime").date.today().isoformat()
    for name, res in enrollable:
        entry = {
            "name": name, "ats": res["ats"], "slug": res["slug"],
            "priority": "low",
            "enrolled_date": today,
            # Comeet is not resolved by a slug -- saying so would misdescribe the
            # only entries whose provenance a reader is likely to question, since
            # their uid/token came off a guessed careers URL rather than an API.
            "enrolled_via": (
                "harvest_ats.py Comeet careers-page resolution "
                f"(credentials scraped from {res.get('comeet_careers_url')})"
                if res["ats"] == "comeet"
                else "harvest_ats.py automated slug resolution"),
            # This layer CANNOT assign a vertical bonus. score_bonus/bonus_reason
            # are hand-curated on purpose (a keyword pass was ~40% wrong in both
            # directions -- see CLAUDE.md Scoring Guardrails), so auto-enrolled
            # companies land with none at all and are under-scored by up to 20-30
            # points until a human classifies them. Flag it so the gap is visible
            # and drainable (daily_task_prompt.md Step 1e-2) rather than silent.
            # Found 2026-08-21: 45 auto-enrolled companies had accumulated this
            # way since 2026-07-31, including Snorkel AI (AI/ML), Cribl and Drata
            # (tooling) -- Cribl and Doppel were both fully tailored while
            # carrying the handicap.
            "needs_vertical_classification": True,
            "reason": (f"Auto-enrolled by the ATS harvest layer. Board verified live "
                       f"({res['total']} jobs) with {len(res['strong'])} fit-titles at "
                       f"harvest time ({tier_breakdown(res['strong'])}), e.g. "
                       f"{res['strong'][0][0][:60]!r} [{res['strong'][0][1][:40]}]. "
                       f"Qualifying tiers: tier1/tier2/tier2c anywhere US-reachable, "
                       f"plus tier3 in Atlanta or remote-US only. Enrolled at LOW "
                       f"priority by design: auto-enrollment should not outrank "
                       f"hand-vetted companies. Prune via --prune if the board goes "
                       f"dead or fit-space-empty."),
        }
        # Workday needs the full three-part address on the watchlist entry;
        # poll_ats.py cannot reach a Workday board from ats+slug alone. Comeet
        # is the same shape of problem -- its `slug` addresses nothing, so
        # fetch_comeet needs comeet_uid/comeet_token or it errors out (and
        # validate_config.py rejects the entry outright). comeet_careers_url is
        # not read by anything; it records WHICH page the credentials were
        # scraped from, so a domain-guess that landed on the wrong company can
        # be spotted by reading the entry instead of by re-deriving the walk.
        for k in ("wd_host", "wd_tenant", "wd_site",
                  "comeet_uid", "comeet_token", "comeet_careers_url"):
            if k in res:
                entry[k] = res[k]
        wl["companies"].append(entry)
        q.setdefault("enrolled", []).append(
            {"name": name, "ats": res["ats"], "slug": res["slug"],
             "enrolled_date": today, "via": "harvest_ats.py"})
    for name, res in no_fit:
        q.setdefault("rejected", []).append(
            {"name": name, "ats": res["ats"], "slug": res["slug"],
             "rejected_date": today,
             "reason": (f"Board resolves and is live ({res['total']} jobs) but ZERO "
                        f"qualifying fit-titles at harvest time: no tier1/tier2/tier2c "
                        f"anywhere US-reachable, and no tier3 in Atlanta or remote-US. "
                        f"Rejected on fit-space, not pollability -- recheck if the "
                        f"company resurfaces. NOTE: a tier3 role outside Atlanta/remote-US "
                        f"does NOT qualify, so this company may still have a Boston or SF "
                        f"CSM open; that is intended."),
             "recheck_if_resurfaced": True})
    for name, res in empty_board:
        # NOT unpollable: the board was found. A manual site: search cannot help
        # here, so this must never reach the weekly unpollable punch list.
        q.setdefault("rejected", []).append(
            {"name": name, "ats": res["ats"], "slug": res["slug"],
             "rejected_date": today,
             "reason": (f"Board RESOLVED at {res['ats']}/{res['slug']} but returned ZERO "
                        f"jobs, so there was nothing to score. This is NOT an unpollable "
                        f"company and a manual site: search will not help: the slug is "
                        f"known and re-checking costs one API call. Either the board is "
                        f"between postings or the company has paused hiring. Recheck on "
                        f"any resurfacing and enroll directly if it has repopulated. "
                        f"(Slugs that resolved empty: "
                        f"{', '.join(a + '/' + s for a, s in res.get('empty_hits', []))}.)"),
             "recheck_if_resurfaced": True,
             "unpollable": False})
    for name, _ in no_board:
        # The old wording here read "across Greenhouse/Ashby/Lever/Workable" long
        # after the probe list had grown past those four, and named a
        # site:myworkdayjobs.com search as the only follow-up. That is what
        # Upwind Security's 2026-09-02 rejection said while it was running a
        # live 58-position Comeet board -- a true sentence pointing at the wrong
        # next step. Keep this text honest about what was actually tried.
        # The skip flags change what was tried, so the text must follow them: a
        # --skip-workday run must not claim "no Workday tenant answered".
        workday_clause = ("Workday was NOT probed (--skip-workday)" if args.skip_workday
                          else "no Workday tenant answered")
        comeet_clause = ("Comeet was NOT probed (--skip-comeet)" if args.skip_comeet
                         else "no Comeet widget was found on a name-derived careers page")
        entry = {"name": name, "ats": None, "slug": None, "rejected_date": today,
                  "reason": ("No board resolved: no deterministic name-variant slug matched "
                             "Greenhouse/Ashby/Lever/Workable/Pinpoint/Rippling/"
                             f"JazzHR/SmartRecruiters; {workday_clause}; {comeet_clause}. "
                             "May still be pollable under a "
                             "non-obvious slug, on a careers page this script could not "
                             "guess the domain of, or on an ATS with no adapter yet "
                             "(Paylocity boards are GUID-addressed and can never be "
                             "auto-resolved). Worth one manual look at the company's own "
                             "careers page if the company matters."),
                  "recheck_if_resurfaced": True,
                  "unpollable": True}
        pending_entry = pending_by_name.get(name.lower(), {})
        for field in ("manual_review", "manual_review_why", "manual_review_surfaced"):
            if field in pending_entry:
                entry[field] = pending_entry[field]
        q.setdefault("rejected", []).append(entry)

    # A timeout is NOT a finding about the company, so it gets its own reason and
    # is explicitly not marked unpollable: nothing was learned about whether a
    # board exists, and writing the standard no-board text would put the company
    # on the weekly unpollable punch list on the strength of a clock. The queue
    # entry is still drained (see `handled` below) so the batch makes forward
    # progress, but the reason tells the next reader that a targeted --names
    # re-run is the cheap next step, not a manual search.
    for name, res in timed_out:
        found = ", ".join(a + "/" + s for a, s in res.get("empty_hits", []))
        q.setdefault("rejected", []).append(
            {"name": name, "ats": None, "slug": None, "rejected_date": today,
             "reason": (f"UNRESOLVED ON TIMEOUT, not on evidence. The probe walk hit the "
                        f"{res['budget']:g}s per-company wall-clock cap after "
                        f"{res['elapsed']:.0f}s, during the {res['phase']}, so the "
                        f"remaining probes never ran and nothing is known about whether "
                        f"this company has a board. Typical cause: a Workday tenant that "
                        f"resolves but matches none of the site names tried, which costs "
                        f"the full 5-host walk. Cheap next step is a targeted re-run "
                        f"(--names \"{name}\" --budget-seconds 300), NOT a manual "
                        f"site:myworkdayjobs.com search."
                        + (f" Boards that resolved empty before the cap: {found}."
                           if found else "")),
             "recheck_if_resurfaced": True,
             "unpollable": False,
             "timed_out": True})

    handled = ({n.lower() for n, _ in enrollable} | {n.lower() for n, _ in no_fit}
               | {n.lower() for n, _ in empty_board} | {n.lower() for n, _ in no_board}
               | {n.lower() for n, _ in timed_out})
    q["pending"] = [e for e in q.get("pending", [])
                    if str(e.get("name", "")).lower() not in handled]

    for path, data in ((WATCHLIST, wl), (QUEUE, q)):
        tmp = path + ".tmp"
        json.dump(data, open(tmp, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    print(f"\nenrolled {len(enrollable)}, "
          f"rejected {len(no_fit) + len(empty_board) + len(no_board)}, "
          f"unresolved-on-timeout {len(timed_out)}; "
          f"watchlist now {len(wl['companies'])}", flush=True)
    return 0


def prune(wl, matcher, hard_excluded):
    """Dead-board audit: report enrolled companies whose board 404s or is empty."""
    dead, empty, ok = [], [], 0
    # One probe per enrolled company, several hundred of them, so this is a
    # multi-minute run by nature. It reports each dead/empty board as it finds
    # one (flushed, same reasoning as the harvest loop) instead of holding the
    # entire audit until the last company; a heartbeat every 25 companies keeps
    # an all-healthy stretch from looking like a stall.
    checked = 0
    for c in wl["companies"]:
        ats, slug = c.get("ats"), c.get("slug")
        if ats not in ("greenhouse", "ashby", "lever", "workable") or not slug:
            continue  # Workday and custom hosts are out of scope for this audit
        jobs = probe(ats, slug)
        checked += 1
        if jobs is None:
            dead.append(c["name"])
            print(f"  [XX] {c['name']:32s} {ats}/{slug} 404", flush=True)
        elif not jobs:
            empty.append(c["name"])
            print(f"  [00] {c['name']:32s} {ats}/{slug} 0 jobs", flush=True)
        else:
            ok += 1
        if checked % 25 == 0:
            print(f"  ... {checked} checked", flush=True)
    print(f"live={ok} dead(404)={len(dead)} empty={len(empty)}", flush=True)
    if dead:
        print("DEAD:", ", ".join(dead), flush=True)
    if empty:
        print("EMPTY:", ", ".join(empty), flush=True)
    print("\nReport only; no changes written. Set board_status by hand after review.",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
