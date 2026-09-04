"""Unit-check in_fit_space against the real BuiltIn tag sets this feeder has seen.

Every case below is a company poll_builtin.py actually queued on 2026-09-03 or
2026-09-04, with its verbatim industry tags from the directory card and the outcome
harvest_ats.py recorded for it. The point of the file is the ENROLLED block: those ten
are the feeder's entire proven yield, and an edit to INDUSTRY_ALLOW that drops any of
them is a regression, not a tradeoff. Vetcove ("Healthtech, Pet") and OfficeSpace
Software ("Real Estate, Software") are the load-bearing ones -- each shares a tag with
a company in the BLOCKED block, so a gate written by eyeballing tag names rather than
by set membership tends to lose exactly those two.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from poll_builtin import in_fit_space

CASES = [
    # (name, industries, expected, why)
    # ── enrolled: the feeder's proven yield. All ten MUST pass. ──────────────
    ("Vetcove", ["Healthtech", "Pet"], True,
     "shares 'Pet' with LifeLine Animal Project; Healthtech is what separates them"),
    ("OfficeSpace Software", ["Real Estate", "Software"], True,
     "shares 'Real Estate' with ECI Group; Software is what separates them"),
    ("Moov", ["Fintech", "Payments"], True, "payments infra"),
    ("Pie Insurance", ["Fintech", "Insurance", "Machine Learning", "Analytics",
                       "Financial Services", "Automation"], True,
     "carries 'Financial Services', Premier Bankcard's only tag, plus four tech tags"),
    ("Dragos", ["Security", "Cybersecurity"], True, "OT security"),
    ("Doximity", ["Healthtech", "Information Technology", "Mobile", "Productivity",
                  "Software", "Analytics", "Telehealth"], True, "unambiguous"),
    ("Clipboard", ["Edtech", "Healthtech", "Information Technology", "Hospitality"], True,
     "shares 'Hospitality' with hotel operators and 'Edtech' with Linc Education"),
    ("Keyfactor", ["Cloud", "Information Technology", "Internet of Things"], True,
     "no 'Software' tag at all -- Cloud/IT/IoT must be sufficient on their own"),
    ("Lob", ["Logistics", "Marketing Tech", "Software"], True,
     "shares 'Logistics' with freight brokers"),
    ("NPHub", ["Healthtech"], True, "single tag, and it must be enough"),

    # ── blocked: queued by TARGET_FUNCTIONS alone, produced nothing ──────────
    ("Caliber Car Wash", ["Other", "Automotive Retail"], False, "no board resolved"),
    ("Turaco", ["Insurance", "Financial Services"], False, "no board resolved"),
    ("LifeLine Animal Project", ["Pet", "Social Impact"], False,
     "animal shelter; burned the full 60s harvest budget unresolved"),
    ("ECI Group", ["Real Estate"], False, "apartment operator; timed out"),
    ("Premier Bankcard", ["Financial Services"], False, "card issuer; timed out"),
    ("Mountfitchet Group", ["Logistics", "Transportation", "Travel"], False,
     "77 open jobs, zero fit titles"),

    # ── known misses, asserted so the cost stays visible rather than implied ──
    # These are real technology companies BuiltIn tags only by vertical. They are the
    # ~10% false-positive rate recorded on INDUSTRY_ALLOW. If a later edit fixes one,
    # flip its expectation here rather than deleting the row.
    ("Bluefin Payment Systems", ["Financial Services"], False, "KNOWN MISS: payments tech"),
    ("Knock", ["Real Estate"], False, "KNOWN MISS: proptech SaaS"),
    ("PadSplit", ["Real Estate"], False, "KNOWN MISS: Atlanta proptech marketplace"),
    ("Openly", ["Insurance"], False, "KNOWN MISS: insurtech"),
    ("Cultura Technologies", ["Agriculture"], False, "KNOWN MISS: agtech software"),

    # ── fail-open ────────────────────────────────────────────────────────────
    ("parser regression", [], True,
     "untagged card means _INDUSTRIES stopped matching, not that the company is "
     "off-space; must never silently empty the feeder"),
]


def main() -> int:
    failures = []
    for name, industries, expected, why in CASES:
        got = in_fit_space({"industries": industries})
        if got != expected:
            failures.append(f"  {name!r} {industries} -> {got}, expected {expected} ({why})")
    print(f"{len(CASES) - len(failures)}/{len(CASES)} cases pass")
    proven = sum(1 for n, _, exp, why in CASES
                 if exp and not why.startswith("KNOWN MISS") and n != "parser regression")
    print(f"  (of which {proven} are companies that actually enrolled "
          f"and must never be dropped)")
    if failures:
        print("FAILURES:")
        for f in failures:
            print(f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
