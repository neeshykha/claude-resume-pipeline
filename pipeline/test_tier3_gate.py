"""Unit-check the location gates against real location strings seen in this repo.

  tier3_location_ok  (harvest_ats)  Atlanta or remote-US only
  us_reachable       (harvest_ats)  any US place, or remote with no non-US marker
  location_relevant  (poll_ats)     the daily poller's US filter
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harvest_ats import tier3_location_ok, us_reachable
from poll_ats import location_relevant

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

# Guard the key property: the tier3 gate must be strictly narrower than us_reachable.
every = [loc for loc, _, _ in TIER3_CASES + US_CASES]
wider = [loc for loc in every if tier3_location_ok(loc) and not us_reachable(loc)]
print("tier3 gate admits nothing us_reachable rejects:", "yes" if not wider else f"NO -> {wider}")
sys.exit(1 if fails or wider else 0)
