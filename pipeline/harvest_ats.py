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
"""
import argparse
import json
import os
import re
import sys
import time

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST = os.path.join(SCRIPT_DIR, "watchlist_companies.json")
QUEUE = os.path.join(SCRIPT_DIR, "enrollment_candidates.json")

TIMEOUT = 20
DELAY = 0.35          # politeness pause between HTTP calls
UA = {"User-Agent": "Mozilla/5.0 (resume-pipeline-harvest)"}

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


def _get(url):
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        return r if r.status_code == 200 else None
    except Exception:
        return None
    finally:
        time.sleep(DELAY)


def _confirm_empty(ats: str, slug: str):
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
    time.sleep(max(DELAY, 2.0))
    again = probe(ats, slug)
    return again is not None and len(again) == 0


def probe(ats: str, slug: str):
    """Return [(title, location)] if the board resolves, else None."""
    if ats == "greenhouse":
        r = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
        if not r:
            return None
        return [(j.get("title", ""), (j.get("location") or {}).get("name", ""))
                for j in r.json().get("jobs", [])]
    if ats == "ashby":
        r = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
        if not r:
            return None
        return [(j.get("title", ""), j.get("location", ""))
                for j in r.json().get("jobs", [])]
    if ats == "lever":
        r = _get(f"https://api.lever.co/v0/postings/{slug}?mode=json")
        if not r:
            return None
        return [(j.get("text", ""), (j.get("categories") or {}).get("location", ""))
                for j in r.json()]
    if ats == "workable":
        r = _get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true")
        if not r:
            return None
        return [(j.get("title", ""), j.get("location", "") or j.get("city", ""))
                for j in r.json().get("jobs", [])]
    if ats == "pinpoint":
        r = _get(f"https://{slug}.pinpointhq.com/postings.json")
        if not r:
            return None
        out = []
        for j in r.json().get("data", []):
            loc = j.get("location") or {}
            parts = [p.strip() for p in [loc.get("city"), loc.get("province")] if p and p.strip()]
            label = ", ".join(parts) if parts else (loc.get("name") or "")
            out.append((j.get("title", ""), label))
        return out
    if ats == "rippling":
        # First page only (20 postings) -- enough to judge fit-space; the real
        # daily poll (fetch_rippling in poll_ats.py) paginates fully once a
        # company is actually enrolled.
        r = _get(f"https://ats.rippling.com/{slug}/jobs")
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
    return None


WORKDAY_HOSTS = ["wd1", "wd5", "wd3", "wd12", "wd101"]
WORKDAY_SITES = ["Careers", "External", "ExternalCareers", "External_Career_Site",
                 "Search", "careers", "Jobs", "US", "Global", "ext", "CareerSite"]


def probe_workday(slug: str):
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
        fqdn = f"{slug}.{host}.myworkdayjobs.com"
        for site in sites:
            url = f"https://{fqdn}/wday/cxs/{slug}/{site}/jobs"
            try:
                r = requests.post(url, json=body, headers=UA, timeout=TIMEOUT)
            except Exception:
                break          # network trouble on this host; try the next one
            finally:
                time.sleep(DELAY)
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


def assess(name, matcher, hard_excluded, known_pairs):
    """Resolve a company to (ats, slug, strong_hits, total_jobs) or a reason."""
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
        for ats in ("greenhouse", "ashby", "lever", "workable", "pinpoint", "rippling"):
            if (ats, slug) in known_pairs:
                continue
            jobs = probe(ats, slug)
            if jobs is None:
                continue
            if not jobs:
                # Keep looking under other slugs before concluding anything; an
                # empty board is weak evidence that we found the right company
                # at all. But hold on to it in case nothing better turns up --
                # and only after confirming it is a real empty board rather than
                # a load artifact (see _confirm_empty).
                if _confirm_empty(ats, slug):
                    empty_hits.append((ats, slug))
                continue
            return {"ats": ats, "slug": slug, "total": len(jobs),
                    "strong": _score_board(jobs, matcher, hard_excluded)}

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
    wd_slugs = workday_slug_candidates(name)
    for slug in wd_slugs:
        if ("workday", slug) in known_pairs:
            continue
        jobs, meta = probe_workday(slug)
        if not jobs:
            continue
        res = {"ats": "workday", "slug": slug, "total": meta["total"],
               "strong": _score_board(jobs, matcher, hard_excluded)}
        res.update({k: meta[k] for k in ("wd_host", "wd_tenant", "wd_site")})
        return res

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

    enrollable, no_board, no_fit, empty_board, skipped = [], [], [], [], []
    for name in targets:
        if name.lower() in known_names and not args.names:
            skipped.append(name)
            continue
        res = assess(name, matcher, P.title_hard_excluded, known_pairs)
        if res is None:
            no_board.append(name)
            print(f"  [--] {name:24s} no board resolved from name variants")
            continue
        if res.get("empty_board"):
            empty_board.append((name, res))
            print(f"  [00] {name:24s} {res['ats']}/{res['slug']:20s} "
                  f"board resolves but returns 0 jobs")
            continue
        if not res["strong"]:
            no_fit.append((name, res))
            print(f"  [..] {name:24s} {res['ats']}/{res['slug']:20s} "
                  f"{res['total']:>4} jobs, 0 US fit-titles")
            continue
        enrollable.append((name, res))
        print(f"  [OK] {name:24s} {res['ats']}/{res['slug']:20s} "
              f"{res['total']:>4} jobs, {len(res['strong'])} fit-titles "
              f"({tier_breakdown(res['strong'])})")
        for t, l, tier in res["strong"][:3]:
            # tier2c_tooling_systems and tier2_strong_overlap both truncate to
            # "tier2" at 5 chars, so label from the full tier name instead.
            label = {"tier1_true_match": "tier1", "tier2_strong_overlap": "tier2",
                     "tier2c_tooling_systems": "tier2c",
                     TIER3_TIER: "tier3*"}.get(tier, tier[:6])
            print(f"         [{label:6s}] {t[:44]:44s} | {str(l)[:24]}")
        if any(tier == TIER3_TIER for _, _, tier in res["strong"]):
            print("         * tier3 counted only because the role is Atlanta or remote-US")

    print(f"\nenrollable={len(enrollable)} no_fit={len(no_fit)} "
          f"empty_board={len(empty_board)} no_board={len(no_board)} "
          f"already_known_skipped={len(skipped)}")

    if not args.apply:
        print("dry run; re-run with --apply to enroll")
        return 0

    today = __import__("datetime").date.today().isoformat()
    for name, res in enrollable:
        entry = {
            "name": name, "ats": res["ats"], "slug": res["slug"],
            "priority": "low",
            "enrolled_date": today,
            "enrolled_via": "harvest_ats.py automated slug resolution",
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
        # poll_ats.py cannot reach a Workday board from ats+slug alone.
        for k in ("wd_host", "wd_tenant", "wd_site"):
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
    for name in no_board:
        entry = {"name": name, "ats": None, "slug": None, "rejected_date": today,
                  "reason": ("No board resolved from deterministic name-variant slugs across "
                             "Greenhouse/Ashby/Lever/Workable. May still be pollable under a "
                             "non-obvious slug or on Workday: worth one manual "
                             "site:myworkdayjobs.com search if the company matters."),
                  "recheck_if_resurfaced": True,
                  "unpollable": True}
        pending_entry = pending_by_name.get(name.lower(), {})
        for field in ("manual_review", "manual_review_why", "manual_review_surfaced"):
            if field in pending_entry:
                entry[field] = pending_entry[field]
        q.setdefault("rejected", []).append(entry)

    handled = ({n.lower() for n, _ in enrollable} | {n.lower() for n, _ in no_fit}
               | {n.lower() for n, _ in empty_board} | {n.lower() for n in no_board})
    q["pending"] = [e for e in q.get("pending", [])
                    if str(e.get("name", "")).lower() not in handled]

    for path, data in ((WATCHLIST, wl), (QUEUE, q)):
        tmp = path + ".tmp"
        json.dump(data, open(tmp, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    print(f"\nenrolled {len(enrollable)}, "
          f"rejected {len(no_fit) + len(empty_board) + len(no_board)}; "
          f"watchlist now {len(wl['companies'])}")
    return 0


def prune(wl, matcher, hard_excluded):
    """Dead-board audit: report enrolled companies whose board 404s or is empty."""
    dead, empty, ok = [], [], 0
    for c in wl["companies"]:
        ats, slug = c.get("ats"), c.get("slug")
        if ats not in ("greenhouse", "ashby", "lever", "workable") or not slug:
            continue  # Workday and custom hosts are out of scope for this audit
        jobs = probe(ats, slug)
        if jobs is None:
            dead.append(c["name"])
        elif not jobs:
            empty.append(c["name"])
        else:
            ok += 1
    print(f"live={ok} dead(404)={len(dead)} empty={len(empty)}")
    if dead:
        print("DEAD:", ", ".join(dead))
    if empty:
        print("EMPTY:", ", ".join(empty))
    print("\nReport only; no changes written. Set board_status by hand after review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
