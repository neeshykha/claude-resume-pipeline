#!/usr/bin/env python3
"""
Discover + verify Workday CXS endpoints before adding a tenant to the watchlist.

Workday's host (incl. wdN datacenter), tenant, and site name are NOT guessable
per company. This helper probes a list of likely site names against a tenant's
CXS jobs API and reports the working (host, tenant, site) triple plus a sample
of target-title hits — paste the result straight into watchlist_companies.json
as an ats="workday" entry.

Usage:
    # find the exact careers URL first, e.g. web search 'site:myworkdayjobs.com <company>'
    # then edit CANDIDATES below (host must include the wdN datacenter) and run:
    .venv/bin/python pipeline/verify_workday.py
"""
import requests

TIMEOUT = 20
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (resume-pipeline-verify)",
}

# Target-title keywords (kept loose — this is a discovery aid, not the real filter)
TARGET = [
    "customer success", "technical account", "implementation", "solutions consultant",
    "solutions engineer", "professional services", "deployment", "customer experience",
    "engagement manager", "enablement", "onboarding", "support operations",
    "customer engineer", "adoption", "technical success", "value",
]

# Common Workday site-name patterns probed per tenant. {T} → tenant.
SITE_GUESSES = [
    "careers", "Careers", "External", "External_Careers", "External_Career_Site",
    "ExternalCareerSite", "{T}", "{T}_Careers", "{T}_External", "global", "jobs",
]

# (display, host-with-wdN, tenant). Edit this list, then run.
CANDIDATES = [
    ("Gainsight", "gainsight.wd5.myworkdayjobs.com", "gainsight"),
    ("NCR Voyix", "ncr.wd1.myworkdayjobs.com", "ncr"),
]


def title_hits(titles):
    return [t for t in titles if any(k in t.lower() for k in TARGET)]


def try_site(host, tenant, site):
    url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    body = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}
    try:
        r = requests.post(url, json=body, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        d = r.json()
        return d if "jobPostings" in d else None
    except Exception:
        return None


def main():
    rows = []
    for display, host, tenant in CANDIDATES:
        found = None
        for guess in SITE_GUESSES:
            base = guess.replace("{T}", tenant)
            for s in {base, tenant.capitalize(), tenant.upper()}:
                d = try_site(host, tenant, s)
                if d:
                    found = (s, d)
                    break
            if found:
                break
        if found:
            site, d = found
            titles = [p.get("title", "") for p in d.get("jobPostings", [])]
            hits = title_hits(titles)
            rows.append((display, host, tenant, site, d.get("total"), hits))
            print(f"\n[OK] {display}  host={host} tenant={tenant} site={site}  "
                  f"total={d.get('total')} hits={len(hits)}")
            for h in hits[:6]:
                print(f"       - {h}")
        else:
            print(f"\n[--] {display}  host={host} tenant={tenant} — no working site found")

    print("\n" + "=" * 70 + "\nWATCHLIST-READY:")
    for display, host, tenant, site, total, hits in rows:
        print(f'  "{display}": wd_host={host} wd_tenant={tenant} wd_site={site}')


if __name__ == "__main__":
    main()
