"""Company matching in weekly_channel_report.classify_card (fixed 2026-09-26).

Every name here is invented. The shapes are the real ones: a legal suffix on one
side only, a brand carried in a parenthetical, an apostrophe, a short brand that
is a substring of an unrelated name, and a short brand that prefixes a longer
one. Run: .venv/bin/python pipeline/test_weekly_channel_report.py
"""
import sys
import unittest

sys.path.insert(0, "pipeline")
import weekly_channel_report as w  # noqa: E402


def index(*rows):
    return [(w._company_aliases(company), w._norm(title)) for company, title in rows]


def card(company, title, status="rejected"):
    return {"company": company, "title": title, "company_status": [status]}


class CompanyMatching(unittest.TestCase):
    def test_suffix_only_on_tracker_side(self):
        idx = index(("Quillon Technologies", "Head of Support Operations"))
        self.assertEqual(w.classify_card(card("Quillon", "Head of Support Operations"), idx), "tailored")

    def test_suffix_only_on_card_side(self):
        idx = index(("Marrowby", "Service Delivery Manager"))
        self.assertEqual(w.classify_card(card("Marrowby, Inc.", "SERVICE DELIVERY MANAGER"), idx), "tailored")

    def test_parenthetical_brand_on_tracker_side(self):
        idx = index(("Halvern Measurement (Brightwater Communications)", "Support Manager"))
        self.assertEqual(w.classify_card(card("Brightwater Communications LLC", "Support Manager"), idx), "tailored")

    def test_parent_name_matches_too(self):
        idx = index(("Halvern Measurement (Brightwater Communications)", "Support Manager"))
        self.assertEqual(w.classify_card(card("Halvern Measurement", "Other Role"), idx), "company_worked")

    def test_apostrophe_and_longer_card_name(self):
        idx = index(("Pell's Clinic of Dunmore", "AI Specialist"))
        self.assertEqual(w.classify_card(card("Pells Clinic of Dunmore Cardiology", "Contact Center Manager"), idx),
                         "company_worked")

    def test_substring_inside_a_word_never_matches(self):
        idx = index(("NOVA", "Customer Success Manager"), ("CrowdStriven", "Business Systems Analyst"))
        self.assertEqual(w.classify_card(card("OVA", "Customer Success Manager"), idx), "unpollable")
        self.assertEqual(w.classify_card(card("STR", "Product Ops Manager"), idx), "unpollable")

    def test_short_single_word_needs_exact_match(self):
        idx = index(("ZQ Holdings Energy", "Technical Account Manager"))
        self.assertEqual(w.classify_card(card("ZQ", "Technical Account Manager"), idx), "unpollable")
        idx = index(("ZQ", "Technical Account Manager"))
        self.assertEqual(w.classify_card(card("ZQ Inc.", "Technical Account Manager"), idx), "tailored")

    def test_different_company_with_shared_later_word(self):
        idx = index(("Global Tallow", "AI Lead"))
        self.assertEqual(w.classify_card(card("Tallow", "AI Lead"), idx), "unpollable")

    def test_unmatched_card_falls_through_to_status(self):
        idx = index(("Quillon", "Head of Support"))
        self.assertEqual(w.classify_card(card("Brevik", "Head of Support", "watchlist"), idx), "pollable_not_picked")


if __name__ == "__main__":
    unittest.main(verbosity=1)
