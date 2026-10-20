"""Regression check for domain_candidates() in harvest_ats.py (2026-10-20).

The Comeet probe reaches a board through the company's own site, so it guesses
domains from the name. "Global-e" lost its hyphen and was only ever tried as
globale.com and global.com, while its Comeet board lives at global-e.com. No
network: this only checks the guessed list.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harvest_ats

CASES = [
    # (name, must be first, must be present, must be absent, why)
    ("Global-e", "global-e.com", ["globale.com"], [],
     "a hyphenated name tries the hyphenated domain first"),
    ("Upwind Security", "upwindsecurity.com", ["upwind.io"], ["upwind-security.com"],
     "a name with no hyphen gets no hyphenated guesses"),
    ("linear.app", "linear.app", [], [],
     "a name that is already a domain resolves to itself"),
]

fails = 0
for name, first, present, absent, why in CASES:
    got = harvest_ats.domain_candidates(name)
    ok = (bool(got) and got[0] == first
          and all(d in got for d in present)
          and not any(d in got for d in absent))
    if not ok:
        fails += 1
    print(f"{'PASS' if ok else 'FAIL'}  {name!r:<18} first={got[0] if got else None}  {why}")

print(f"\n{len(CASES) - fails}/{len(CASES)} passed")
sys.exit(1 if fails else 0)
