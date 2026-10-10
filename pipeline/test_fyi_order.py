"""Checks for the function_mismatch (digest FYI) order in poll_ats (2026-10-10).

The list used to be sorted by company and sliced to 40, so on an 82-hit day
every line past the 40th was dropped by company name while
stats.function_mismatch still counted it. It is now written whole and ordered
Georgia, remote, elsewhere, newest posting first. Fixtures are made up.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poll_ats

PLACE_CASES = [
    ("Hybrid Atlanta, GA", 0, "names Atlanta"),
    ("ALPHARETTA, GEORGIA", 0, "names Georgia"),
    ("Site 4: 100 Example Parkway, Kennesaw, GA, 30144 USA", 0,
     "Workday street address: only the GA token says Georgia"),
    ("US-GA-Atlanta", 0, "hyphenated state code"),
    ("Georgia, US, Remote", 0, "Georgia outranks remote"),
    ("Gainesville, FL", 2, "'ga' inside a word is not Georgia"),
    ("Remote - United States", 1, "remote"),
    ("New Jersey Remote Work, More...", 1, "remote named mid-string"),
    ("San Mateo, CA United States", 2, "on-site elsewhere"),
    ("", 2, "blank"),
    (None, 2, "missing"),
]


def job(company, location, age):
    return {"company": company, "title": "Engineering Manager", "location": location,
            "apply_url": "https://example.com", "title_tier": None,
            "posting_age_days": age}


# Deliberately in the old (company, title) order, with the lines that matter last.
JOBS = [
    job("Acme", "San Mateo, CA United States", 1),
    job("Borealis", "Remote - United States", 30),
    job("Cobalt", "Remote - United States", None),
    job("Yarrow", "Remote - United States", 2),
    job("Zephyr", "Site 4: 100 Example Parkway, Kennesaw, GA, 30144 USA", 20),
]
WANT_ORDER = ["Zephyr", "Yarrow", "Borealis", "Cobalt", "Acme"]

fails = 0
for loc, want, why in PLACE_CASES:
    got = poll_ats._fyi_place(loc)
    ok = got == want
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'}  place={got} (want {want})  {loc!r}  {why}")

got_order = [j["company"] for j in sorted(JOBS, key=poll_ats.fyi_sort_key)]
ok = got_order == WANT_ORDER
fails += not ok
print(f"{'PASS' if ok else 'FAIL'}  order {got_order} (want {WANT_ORDER})  "
      "Georgia, remote, elsewhere; newest first, undated last")

total = len(PLACE_CASES) + 1
print(f"\n{total - fails}/{total} passed")
sys.exit(1 if fails else 0)
