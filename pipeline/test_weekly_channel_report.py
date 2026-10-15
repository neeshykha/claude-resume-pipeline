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


# --- The page (D41, 2026-10-15). Invented names, real shapes. ---------------------------

def lcard(jid, company, title, tier="tier2", loc="us-national", **kw):
    c = {"job_id": jid, "company": company, "title": title, "title_tier": tier,
         "location_verdict": loc, "url": f"https://www.linkedin.com/jobs/view/{jid}/",
         "alert_date": "2026-10-10", "seen_times": 1}
    c.update(kw)
    return c


def unpollable(name, jid, title, **kw):
    e = {"name": name, "card_job_id": jid, "card_title": title,
         "card_url": f"https://www.linkedin.com/jobs/view/{jid}/", "rejected_date": "2026-10-09",
         "first_seen": "2026-10-08", "manual_review_why": f"{title} -- LinkedIn card role"}
    e.update(kw)
    return e


class PageLeads(unittest.TestCase):
    def test_order_dedupe_and_tailored_drop(self):
        buckets = {
            "unpollable": [lcard("2000002", "Ostravik", "Support Manager", tier="tier2", loc="atlanta"),
                           lcard("2000001", "Brevik", "Head of Support", tier="tier1", loc="us-national")],
            "blind_spot": [lcard("2000003", "Corvane", "Technical Support Manager", tier="tier1", loc="atlanta",
                                 blind_spot=True)],
            "pollable_not_picked": [lcard("2000004", "Velquist", "Implementation Manager")],
        }
        batch = [unpollable("Brevik", "2000001", "Head of Support"),          # also unreachable: shown once
                 unpollable("Quillon", "2000005", "Head of Support Operations"),  # already tailored: dropped
                 unpollable("Marrowby", "2000006", "Ops Lead", collision_board="ashby/marrow"),
                 unpollable("Nameless", "", "No id")]                          # no job id: unmarkable
        idx = index(("Quillon Technologies", "Head of Support Operations"))
        leads, no_id = w.build_leads(buckets, batch, idx,
                                     cards=[lcard("2000006", "Marrowby", "Ops Lead", tier="tier2c", loc="remote")])
        ids = [x["id"] for x in leads]
        self.assertEqual(ids, ["2000003", "2000001", "2000002", "2000004", "2000006"])
        self.assertEqual([x["list"] for x in leads],
                         ["unreachable", "unreachable", "unreachable", "never_picked", "no_board"])
        self.assertIn("blind-spot", leads[0]["note"])
        last = leads[-1]
        self.assertEqual((last["tier"], last["loc"]), ("tier2c", "remote"), "tier and location come from the card")
        self.assertIn("ashby/marrow", last["note"])
        self.assertEqual(no_id, 1, "an entry without a card id can't be a row, and is counted so the page says so")
        self.assertIn("1 no-board company has no LinkedIn role", " ".join(w.page_flags(None, ({}, 0, 0, 0), [], 1)))

    def test_company_with_a_package_says_so(self):
        idx = index(("Marrowby", "Some Other Role"))
        lead = w._lead_from_unpollable(unpollable("Marrowby", "2000007", "Ops Lead"), idx, {})
        self.assertIn("package at this company", lead["note"])
        self.assertEqual(lead["list"], "no_board")

    def test_flags(self):
        from datetime import date
        n = w.channel_numbers([(date(2026, 10, 13), {"feeders": {"poll_remotive_status": "DEGRADED (x)"},
                                                     "websearch": {"sources_run": 6},
                                                     "linkedin_harvest": {"threads_found": 40}})])
        attribution = ({"websearch": {"enrolled": [], "rejected": []},
                        "linkedin_harvest": {"enrolled": [{}], "rejected": []}}, 0, 0, 1)
        gaps = w._weekday_gaps([(date(2026, 10, 13), {})], [], date(2026, 10, 9), date(2026, 10, 15))
        self.assertEqual([d.isoformat() for d in gaps], ["2026-10-09", "2026-10-12", "2026-10-14"],
                         "weekdays only, and never today")
        flags = w.page_flags(n, attribution, gaps)
        text = " ".join(flags)
        self.assertIn("Fri Oct 9, Mon Oct 12, Wed Oct 14", text)
        self.assertIn("Remotive was degraded on all 1", text)
        self.assertIn("WebSearch ran 6", text)
        self.assertNotIn("LinkedIn alerts", text, "LinkedIn did enroll one")
        self.assertIn("No applications were tailored", text)
        self.assertEqual(w.page_flags(None, attribution, []), [])


class PageWrite(unittest.TestCase):
    """--page --apply marks the batch only after the file is written."""

    def setUp(self):
        import json
        import os
        import tempfile
        self.json, self.os = json, os
        self.dir = tempfile.mkdtemp(prefix="wcr_test_")
        self.saved = (w.QUEUE_PATH, w.LINKEDIN_CARDS_GLOB, w.PAGE_PATH, w.load_window, w.quality_text,
                      w.load_tailored_index)
        w.QUEUE_PATH = os.path.join(self.dir, "queue.json")
        w.LINKEDIN_CARDS_GLOB = os.path.join(self.dir, "linkedin_cards_*.json")
        w.load_window = lambda days=7: ([], [], __import__("datetime").date(2026, 10, 9))
        w.quality_text = lambda: ""
        w.load_tailored_index = lambda path=None: []
        with open(w.QUEUE_PATH, "w") as f:
            json.dump({"rejected": [unpollable("Brevik", "2000001", "Head of Support", unpollable=True)]}, f)

    def tearDown(self):
        (w.QUEUE_PATH, w.LINKEDIN_CARDS_GLOB, w.PAGE_PATH, w.load_window, w.quality_text,
         w.load_tailored_index) = self.saved

    def run_main(self, *argv):
        import contextlib
        import io
        saved = sys.argv
        sys.argv = ["weekly_channel_report.py"] + list(argv)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = w.main()
        finally:
            sys.argv = saved
        return rc, buf.getvalue()

    def queue(self):
        with open(w.QUEUE_PATH) as f:
            return self.json.load(f)["rejected"][0]

    def test_written_then_marked(self):
        out = self.os.path.join(self.dir, "page.json")
        rc, text = self.run_main("--page-out", out, "--apply")
        self.assertEqual(rc, 0, text)
        with open(out) as f:
            doc = self.json.load(f)
        self.assertEqual([x["id"] for x in doc["leads"]], ["2000001"])
        self.assertTrue(self.queue().get("weekly_report_surfaced"))

    def test_failed_write_marks_nothing(self):
        blocker = self.os.path.join(self.dir, "not_a_dir")
        with open(blocker, "w") as f:
            f.write("x")
        rc, text = self.run_main("--page-out", self.os.path.join(blocker, "page.json"), "--apply")
        self.assertEqual(rc, 1)
        self.assertIn("Nothing was marked", text)
        self.assertFalse(self.queue().get("weekly_report_surfaced"))

    def test_a_retried_run_rewrites_and_marks_nothing(self):
        out = self.os.path.join(self.dir, "page.json")
        with open(out, "w") as f:
            f.write('{"leads": ["what he is answering"]}')
        rc, text = self.run_main("--page-out", out, "--apply")
        self.assertEqual(rc, 0)
        self.assertIn("already written today", text)
        with open(out) as f:
            self.assertIn("what he is answering", f.read())
        self.assertFalse(self.queue().get("weekly_report_surfaced"))

    def test_resurface_rebuilds_and_refuses_apply(self):
        q = {"rejected": [unpollable("Brevik", "2000001", "Head of Support", unpollable=True,
                                     weekly_report_surfaced=True, weekly_report_surfaced_date="2026-10-15")]}
        with open(w.QUEUE_PATH, "w") as f:
            self.json.dump(q, f)
        out = self.os.path.join(self.dir, "page.json")
        rc, _ = self.run_main("--page-out", out, "--resurface", "2026-10-15")
        with open(out) as f:
            self.assertEqual(len(self.json.load(f)["leads"]), 1)
        with self.assertRaises(SystemExit):
            self.run_main("--page-out", out, "--resurface", "2026-10-15", "--apply")


if __name__ == "__main__":
    unittest.main(verbosity=1)
