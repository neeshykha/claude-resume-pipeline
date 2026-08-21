"""Unit-check tier3_location_ok against real location strings seen in this repo."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harvest_ats import tier3_location_ok as ok, us_reachable

CASES = [
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
]

fails = 0
for loc, want, why in CASES:
    got = ok(loc)
    flag = "ok " if got == want else "FAIL"
    if got != want:
        fails += 1
    print(f"  [{flag}] {str(got):5s} (want {str(want):5s})  {loc!r:34s} {why}")

print(f"\n{len(CASES) - fails}/{len(CASES)} passed")

# Guard the key property: the tier3 gate must be strictly narrower than us_reachable.
wider = [loc for loc, _, _ in CASES if ok(loc) and not us_reachable(loc)]
print("tier3 gate admits nothing us_reachable rejects:", "yes" if not wider else f"NO -> {wider}")
sys.exit(1 if fails else 0)
