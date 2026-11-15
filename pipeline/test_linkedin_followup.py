"""Unit-check linkedin_followup.select() ordering. No network, no real data files.

Added 2026-11-14 (D57). The sort key put company status first, so every card at
a never-resolved company ranked above every card at a rejected one. On that
day's run the 24-card cap deferred the strongest cards of the day: tier-1
support-operations roles at rejected companies, the only cards no other step
reads. Title tier and location now lead and status only breaks ties.

What is pinned here:
  - a tier-1 Atlanta card at a rejected company (status 2) outranks a tier-2c
    unknown-location card at a never-resolved company (status 0) under a cap of 1;
  - with tier and location equal, status still orders never-resolved, then
    aggregator, then rejected;
  - the one-per-(company, title) dedupe runs after the sort, so the copy that
    survives is the better-ranked one;
  - cards cut by the cap come back as deferred, and watchlist cards are skipped.

Every company and title below is made up. select() reads the enrollment queue
and outcomes.csv for its skip sets; both readers are replaced with empty sets.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import linkedin_followup as L

L.unresolved_names = lambda: set()
L.tracked_roles = lambda: set()

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def _card(jid, company, title, tier, loc, status=None, aggregator=False):
    return {"job_id": jid, "company": company, "title": title, "tier_name": tier,
            "location_verdict": loc, "company_status": status or [],
            "aggregator": aggregator}


def _ids(cards):
    return [c["job_id"] for c in cards]


@case
def tier1_at_rejected_company_beats_tier2c_at_new_company():
    doc = {"cards": [
        _card("1", "Zzq Newco", "Systems Manager", "tier2c_tooling_systems", "unknown"),
        _card("2", "Zzq Oldco", "Support Operations Manager", "tier1_true_match",
              "atlanta", status=["rejected"]),
    ]}
    picked, deferred, _ = L.select(doc, set(), 1)
    ok = _ids(picked) == ["2"] and _ids(deferred) == ["1"] and picked[0]["_class"] == 2
    return ok, (_ids(picked), _ids(deferred))


@case
def status_breaks_ties_within_tier_and_location():
    doc = {"cards": [
        _card("r", "Zzq Rejected", "Technical Support Manager", "tier1_true_match",
              "remote", status=["rejected"]),
        _card("n", "Zzq Unknown", "Technical Support Manager", "tier1_true_match", "remote"),
    ], "aggregator_cards": [
        _card("a", "Zzq Reposter", "Technical Support Manager", "tier1_true_match",
              "remote", aggregator=True),
    ]}
    picked, _, _ = L.select(doc, set(), 10)
    return _ids(picked) == ["n", "a", "r"], _ids(picked)


@case
def dedupe_keeps_the_better_ranked_copy():
    doc = {"cards": [
        _card("far", "Zzq Dupe", "Support Engineering Manager", "tier1_true_match", "other"),
        _card("near", "Zzq Dupe", "Support Engineering Manager", "tier1_true_match", "atlanta"),
    ]}
    picked, deferred, _ = L.select(doc, set(), 10)
    return _ids(picked) == ["near"] and not deferred, (_ids(picked), _ids(deferred))


@case
def watchlist_skipped_and_overflow_deferred():
    doc = {"cards": [
        _card("w", "Zzq Watched", "Head of Support", "tier1_true_match", "atlanta",
              status=["watchlist"]),
        _card("1", "Zzq One", "Implementation Manager", "tier2_strong_overlap", "remote"),
        _card("2", "Zzq Two", "Implementation Manager", "tier2_strong_overlap", "us-national"),
        _card("3", "Zzq Three", "AI Deployment Lead", "tier2b_ai_wildcard", "remote"),
    ]}
    picked, deferred, skipped = L.select(doc, set(), 2)
    ok = (_ids(picked) == ["1", "2"] and _ids(deferred) == ["3"]
          and skipped["watchlist"] == 1)
    return ok, (_ids(picked), _ids(deferred), skipped)


def main():
    passed = 0
    for fn in CASES:
        ok, detail = fn()
        print(f"  [{'ok ' if ok else 'FAIL'}] {fn.__name__}" + (f"   {detail}" if not ok else ""))
        passed += bool(ok)
    print(f"  {passed}/{len(CASES)} passed")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
