"""Unit-check the location gates against real location strings seen in this repo.

  tier3_location_ok  (harvest_ats)  Atlanta or remote-US only
  us_reachable       (harvest_ats)  any US place, or remote with no non-US marker
  location_relevant  (poll_ats)     the daily poller's US filter
  countries.stamp    (assembly)     the per-posting country the ATSes return

The fourth table and the two property checks at the bottom cover the 2026-09-11
country stamp: the first three tables read STRINGS, and the stamp is what puts a
real country into them instead of leaving the gates to infer one from a city
blocklist. Every stamped string below is one a live board actually produced.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import countries
from harvest_ats import ATLANTA_HINTS, tier3_location_ok, us_reachable
from poll_ats import location_relevant, parse_location

TIER3_CASES = [
    # (location, expected, why)
    ("Atlanta, GA", True, "Evident ID CSM -- the case that motivated this"),
    ("Atlanta, GEORGIA, United States", True, "ServiceNow-style Atlanta string"),
    ("Remote", True, "bare remote, no country marker -> read as remote-US"),
    ("Remote - USA", True, "explicit remote US"),
    ("US (Remote)", True, "Argyle style"),
    ("United States (Remote)", True, "Snorkel style"),
    ("Remote U.S.", True, "Vanta style"),
    ("San Francisco, CA", False, "US but not Atlanta and not remote -> must NOT qualify"),
    ("Boston, MA", False, "the exact case the gate exists to exclude"),
    ("New York, NY (HQ)", False, "NYC on-site"),
    ("Austin", False, "Miro style, US city on-site"),
    ("Remote CAN", False, "Absorb style -- contains 'remote' but is Canada"),
    ("Remote, Canada", False, "explicit Canada"),
    ("Remote - EMEA", False, "EMEA"),
    ("Australia; New Zealand", False, "Cloudbeds ANZ"),
    ("Latin America", False, "Cloudbeds LATAM"),
    ("Thailand", False, "Cloudbeds Thailand"),
    ("London", False, "Orbital London"),
    ("Remote (United States)", True, "Aspire style"),
    ("Indonesia; Philippines", False, "Cloudbeds support coach"),
    ("Remote - New York", True, "Headway RevOps: remote, no non-US marker"),
    ("North America", False, "region but neither Atlanta nor remote"),
    # Short-code token matching must not fire on words that merely contain them.
    ("Duncan, SC", False, "'can' inside Duncan -- must not be read as Canada, but SC is not ATL/remote anyway"),
    ("Remote - Duncan, Oklahoma", True, "'can' inside Duncan must NOT disqualify a remote-US role"),
    ("Remote, CAN", False, "bare CAN token is Canada"),
    ("Remote (UK)", False, "bare UK token"),
    ("Remote - Vatican City", True, "'can' inside Vatican must not fire (contrived, guards the tokenizer)"),
    # 2026-09-11: remote strings from SmartRecruiters and Comeet boards.
    ("Remote Bangkok, , Thailand", False, "Trustonic TAM, SmartRecruiters folds remote in"),
    ("Remote Mexico City, , Mexico", False, "Trustonic Sr. TAM"),
    ("Montreal, Remote", False, "Dot Compliance Comeet: names the city, never the country"),
    ("Remote - Indiana", True, "'india' inside Indiana must not disqualify"),
    ("Remote - New Mexico", True, "'mexico' inside New Mexico must not disqualify"),
    # 2026-09-11: strings the country stamp now produces (live Comeet boards).
    ("Montreal, Remote (non-US: Canada)", False, "Dot Compliance, stamped from country=CA"),
    ("Nordics (Remote) (non-US: Sweden)", False,
     "Upwind: reads 'remote', names no country, and country=SE is the only signal"),
    ("Remote (non-US: Iceland)", False, "Upwind Iceland: no marker list would have caught it"),
    ("Tbilisi (non-US: GE)", False,
     "GE stamps as a code: 'Georgia' in the string would read as the Atlanta bonus"),
    ("Chicago, IL", False, "Upwind returns country='' here -- absent must not stamp"),
]

US_CASES = [
    # Trustonic, 2026-09-11: all three tier2 titles that made it enrollable were
    # outside the US, passing only because "remote" was a US hint.
    ("Remote Bangkok, , Thailand", False, "Trustonic TAM"),
    ("Remote Mexico City, , Mexico", False, "Trustonic Sr. TAM"),
    ("Remote Johannesburg, , South Africa", False, "SmartRecruiters remote, non-US"),
    ("Montreal, Remote", False, "Dot Compliance Comeet: names the city, never the country"),
    ("Remote CAN", False, "Absorb style"),
    ("Remote - EMEA", False, "region marker"),
    ("Remote (UK)", False, "bare UK token"),
    ("Jerusalem, Israel", False, "'usa' inside Jerusalem must not read as the US"),
    ("Remote", True, "bare remote stays US-reachable"),
    ("Remote - USA", True, "explicit remote US"),
    ("US", True, "bare US token"),
    ("Remote U.S.", True, "Vanta style"),
    ("North America East Coast Remote", True, "Dot Compliance's real US role"),
    ("Boston, MA", True, "US city on-site: this gate admits it, tier3 does not"),
    ("San Francisco, CA", True, "US city on-site"),
    ("Atlanta, GA", True, "Atlanta"),
    ("Remote - Indiana", True, "'india' inside Indiana"),
    ("Remote - New Mexico", True, "'mexico' inside New Mexico"),
    ("Remote - Duncan, Oklahoma", True, "'can' inside Duncan"),
    ("Remote, US or Canada", True, "dual-region string that names the US outright"),
    ("New York; London", True, "multi-location with a US city"),
    # 2026-09-11: the country stamp. These are the cases NON_US_MARKERS could
    # never have covered without another hand-added city or country.
    ("Montreal, Remote (non-US: Canada)", False, "Dot Compliance, stamped from country=CA"),
    ("Rehovot, Center District (non-US: Israel)", False, "Dot Compliance Salesforce Engineer"),
    ("OSAKA (non-US: Japan)", False, "Dot Compliance Osaka: city only, uppercased"),
    ("Nordics (Remote) (non-US: Sweden)", False,
     "Upwind: 'remote' with no marker -- reachable before the stamp, not after"),
    ("Kópavogur, Kópavogsbær (non-US: Iceland)", False, "Upwind Iceland"),
    ("Remote Bangkok, , Thailand (non-US)", False,
     "SmartRecruiters names the country already, so the tag drops the name"),
    ("New York, NY (non-US: Canada)", False,
     "contrived: a stamped country beats the dual-region rescue, unlike free text"),
    ("Chicago, IL", True, "Upwind country='' on a real US posting: absence stamps nothing"),
    ("North America East Coast Remote", True, "Dot Compliance's US role, country=US, unstamped"),
    ("Remote", True, "ChargeAfter's remote CSM, country=US, unstamped"),
]

POLL_CASES = [
    ("Remote Bangkok, , Thailand", False, "Trustonic TAM"),
    ("Remote Mexico City, , Mexico", False, "Trustonic Sr. TAM"),
    ("Remote Johannesburg, , South Africa", False, "SmartRecruiters remote, non-US"),
    ("Montreal, Remote", False, "Dot Compliance Comeet"),
    ("Remote", True, "bare remote"),
    ("Remote - USA", True, "explicit remote US"),
    ("Remote - New York", True, "remote, US city"),
    ("North America East Coast Remote", True, "Dot Compliance's real US role"),
    ("Remote, US or Canada", True, "dual-region rescue"),
    # 2026-09-11: LOCATION_EXCLUDE/LOCATION_INCLUDE matched as plain substrings,
    # which was wrong in both directions. Boundary matching fixes three of these;
    # "New Mexico" needs LOCATION_LOOKALIKES on top, since a whole-word "mexico"
    # really is inside it.
    ("Remote - Indiana", True, "'india' inside Indiana must not exclude"),
    ("Remote - Indianapolis, IN", True, "the string harvest_linkedin hit 2026-09-02"),
    ("Remote - New Mexico", True, "'mexico' inside New Mexico: boundary alone is not enough"),
    ("Remote - Milwaukee, WI", True, "'uk' inside Milwaukee must not exclude"),
    ("Remote - Waukesha, WI", True, "same 'uk', different city"),
    ("Minsk, Belarus", False, "'us' inside Belarus must not read as the US"),
    ("Port Louis, Mauritius", False, "'us' inside Mauritius"),
    ("Remote - Mexico", False, "the lookalike blank-out must not rescue real Mexico"),
    ("EMEA / US Remote", True, "dual-region rescue on a bare US token"),
    ("LATAM & USA", True, "dual-region rescue on USA"),
    ("Remote - EMEA", False, "single excluded region, no US option"),
    # 2026-09-11: the country stamp, checked before the exclude/include scans.
    ("Montreal, Remote (non-US: Canada)", False, "Dot Compliance"),
    ("Nordics (Remote) (non-US: Sweden)", False, "Upwind: 'remote' is an include term"),
    ("Vienna (non-US: Austria)", False,
     "'Austria' contains the include term 'us'; the tag is read first, so it cannot rescue"),
    ("Remote (non-US: Iceland)", False, "no marker list entry exists for Iceland"),
    ("Chicago, IL", True, "country='' stamps nothing"),
]

# (ats, job payload, expected location) -- the assembly, not just the gate.
# Payloads are trimmed from live responses captured 2026-09-11.
PARSE_CASES = [
    ("comeet", {"location": {"name": "Canada - Remote", "city": "Montreal",
                             "state": "Remote", "country": "CA", "is_remote": True}},
     "Montreal, Remote (non-US: Canada)", "Dot Compliance's Canadian support lead"),
    ("comeet", {"location": {"name": "North America East Coast Remote", "city": None,
                             "state": None, "country": "US", "is_remote": True}},
     "North America East Coast Remote", "its US twin, untouched"),
    ("comeet", {"location": {"name": "Greater Chicago", "city": "Chicago", "state": "IL",
                             "country": "", "is_remote": True}},
     "Chicago, IL", "Upwind: blank country on a real US posting"),
    ("comeet", {"location": {"name": "Osaka, Japan", "city": "OSAKA", "state": None,
                             "country": "JP", "is_remote": True}},
     "OSAKA (non-US: Japan)", "city-only fallback still gets the country"),
    ("smartrecruiters", {"location": {"city": "Santa Clara", "country": "us",
                                      "fullLocation": "Santa Clara, CA, United States"}},
     "Santa Clara, CA, United States", "lowercase 'us' must resolve as the US"),
    ("smartrecruiters", {"location": {"city": "Bangkok", "country": "th", "remote": True,
                                      "fullLocation": "Bangkok, , Thailand"}},
     "Remote Bangkok, , Thailand (non-US)", "Trustonic TAM"),
    ("smartrecruiters", {"location": {"city": "Toronto", "country": "ca"}},
     "Toronto, Canada (non-US)",
     "the fullLocation-less fallback used to emit 'Toronto, CA' -- California"),
    ("lever", {"categories": {"location": "Atlanta, GA"}, "country": "US",
               "workplaceType": "hybrid"},
     "Hybrid Atlanta, GA", "FinQuery: US stays byte-identical"),
    ("ashby", {"location": "US - New York, NY", "workplaceType": "Hybrid",
               "address": {"postalAddress": {"addressCountry": "United States"}}},
     "Hybrid US - New York, NY", "Kustomer: addressCountry is a name, not a code"),
    ("ashby", {"location": "London", "workplaceType": "Remote",
               "address": {"postalAddress": {"addressCountry": "United Kingdom"}}},
     "Remote London (non-US: United Kingdom)",
     "the field says United Kingdom, the string says London -> the tag keeps the name"),
    ("ashby", {"location": "Remote - Ireland", "workplaceType": "Remote",
               "address": {"postalAddress": {"addressCountry": "Ireland"}}},
     "Remote - Ireland (non-US)", "name already in the string -> bare tag"),
    ("workable", {"city": "", "state": "", "country": "United States",
                  "telecommuting": True},
     "Remote United States", "Seeq: workable already spells the country out"),
    ("paylocity", {"LocationName": "Phoenix, AZ",
                   "JobLocation": {"Country": "USA"}},
     "Phoenix, AZ", "every Paylocity tenant polled so far is US-only"),
]


def run(name, fn, cases):
    print(f"{name}:")
    fails = 0
    for loc, want, why in cases:
        got = fn(loc)
        if got != want:
            fails += 1
        flag = "ok " if got == want else "FAIL"
        print(f"  [{flag}] {str(got):5s} (want {str(want):5s})  {loc!r:40s} {why}")
    print(f"  {len(cases) - fails}/{len(cases)} passed\n")
    return fails


fails = run("tier3_location_ok", tier3_location_ok, TIER3_CASES)
fails += run("us_reachable", us_reachable, US_CASES)
fails += run("poll_ats.location_relevant", lambda loc: location_relevant(loc, ""), POLL_CASES)

print("poll_ats.parse_location:")
parse_fails = 0
for ats, payload, want, why in PARSE_CASES:
    got = parse_location(payload, ats)
    ok = got == want
    parse_fails += 0 if ok else 1
    print(f"  [{'ok ' if ok else 'FAIL'}] {got!r:45s} (want {want!r})  {ats}: {why}")
print(f"  {len(PARSE_CASES) - parse_fails}/{len(PARSE_CASES)} passed\n")
fails += parse_fails

# Property 1: the stamp is a no-op for the US and its territories, and shuts
# every gate for all 270-odd other countries. This is what makes the country
# field a real signal rather than another list to keep adding cities to: a
# country nobody has thought about yet is covered the day an ATS returns it.
leaks, noops = [], []
for code in sorted(countries.COUNTRY_NAMES):
    stamped = countries.stamp("Remote", code)
    if code in countries.US_EQUIVALENT_CODES:
        if stamped != "Remote" or not us_reachable(stamped):
            noops.append(code)
        continue
    if (us_reachable(stamped) or tier3_location_ok(stamped)
            or location_relevant(stamped, "")):
        leaks.append((code, stamped))
print("every non-US country shuts all three gates:",
      "yes" if not leaks else f"NO -> {leaks[:8]}")
print("US and its territories stamp nothing:", "yes" if not noops else f"NO -> {noops}")

# Property 2: no stamped string may contain an Atlanta hint. pre_score_job reads
# the raw location for "atlanta"/"georgia" and awards +24 without consulting the
# tag, so stamping GE with its name would score a Tbilisi posting as Atlanta.
atl = [(c, s) for c in countries.COUNTRY_NAMES
       for s in [countries.stamp("Remote", c).lower()]
       if any(h in s for h in ATLANTA_HINTS)]
print("no country name collides with an Atlanta hint:", "yes" if not atl else f"NO -> {atl}")

# Guard the key property: the tier3 gate must be strictly narrower than us_reachable.
every = [loc for loc, _, _ in TIER3_CASES + US_CASES]
wider = [loc for loc in every if tier3_location_ok(loc) and not us_reachable(loc)]
print("tier3 gate admits nothing us_reachable rejects:", "yes" if not wider else f"NO -> {wider}")
sys.exit(1 if fails or wider or leaks or noops or atl else 0)
