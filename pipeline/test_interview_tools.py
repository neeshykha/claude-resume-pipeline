#!/usr/bin/env python3
"""Tests for rehearsal_block.py and calibration.py. Made-up companies and text only.

    .venv/bin/python pipeline/test_interview_tools.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import calibration  # noqa: E402
import rehearsal_block  # noqa: E402

LESSONS = """# Lessons

## Active Focus Areas (current)

| # | Focus area | Concrete behavior to do | Status | Hit count |
|---|-----------|------------------------|--------|-----------|
| 1 | **Lead with the anchor** | Name the proof point in the first minute. | Active | 1/3 |
| 2 | **Bridge every story** | Close each story with *why it matters here*. | Active | 0/3 (reset) |

### Rehearsal rule

Say it out loud.
"""

POSTMORTEM = """# Post-Mortem — Example Co, Round 2

## 1. Logistics

- **Date**: Fri 2026-01-16, 3:00 PM
- **Format**: hiring manager

## 2. What Went Well

- nothing to see

## 8. Calibration Loop

**At time of post-mortem:**
- **Predicted outcome**: advance to the final round
- **Confidence**: medium
- **Reasoning**: it went fine

**When outcome lands:**
- **Actual outcome**:
- **Date outcome learned**:
- **Delta from prediction**:
"""


class RehearsalBlockTests(unittest.TestCase):
    def test_parses_focus_area_rows(self):
        rows = rehearsal_block.active_focus_areas(LESSONS)
        self.assertEqual([r["n"] for r in rows], ["1", "2"])
        self.assertEqual(rows[0]["name"], "**Lead with the anchor**")
        self.assertEqual(rows[1]["hits"], "0/3 (reset)")

    def test_markdown_carries_rows_and_checklist(self):
        md = rehearsal_block.as_markdown(rehearsal_block.active_focus_areas(LESSONS), "2026-01-01")
        self.assertIn("Lead with the anchor", md)
        self.assertIn("Bridge every story", md)
        self.assertIn("### Cue pairs for this round", md)
        self.assertIn("Rehearsed out loud", md)
        self.assertEqual(md.count("- [ ]"), len(rehearsal_block.OUT_LOUD))

    def test_html_fragment_is_self_contained(self):
        frag = rehearsal_block.as_html(rehearsal_block.active_focus_areas(LESSONS), "2026-01-01")
        self.assertTrue(frag.startswith("<!-- Sixty-second rehearsal block"))
        self.assertEqual(frag.count("<li><b>"), 2)
        self.assertIn("<script>", frag)
        self.assertIn('id="reh-start"', frag)
        self.assertNotIn("**", frag.split("<ol>")[1].split("</ol>")[0])

    def test_no_table_gives_no_rows(self):
        self.assertEqual(rehearsal_block.active_focus_areas("# nothing here\n"), [])


class CalibrationTests(unittest.TestCase):
    def test_blank_field_does_not_swallow_next_line(self):
        s8 = calibration.section(POSTMORTEM, 8)
        self.assertEqual(calibration.field(s8, "Actual outcome"), "")
        self.assertEqual(calibration.field(s8, "Predicted outcome"), "advance to the final round")

    def test_placeholders_and_template_text_read_as_blank(self):
        self.assertEqual(calibration.field("- **Actual outcome**: _[fill in later]_", "Actual outcome"), "")
        self.assertEqual(calibration.field("- **Predicted outcome**: (advance / decline / redirect)", "Predicted outcome"), "")

    def test_late_postmortem_convention_is_unscorable(self):
        for v in ("none (late)", "n/a — outcome was known", "None"):
            predicted = calibration.field("- **Predicted outcome**: " + v, "Predicted outcome")
            self.assertTrue(predicted.lower().startswith(("n/a", "none")), v)

    def test_section_boundaries(self):
        s1 = calibration.section(POSTMORTEM, 1)
        self.assertIn("2026-01-16", s1)
        self.assertNotIn("nothing to see", s1)

    def test_round_number_from_filename(self):
        import pathlib
        self.assertEqual(calibration.round_number(pathlib.Path("postmortem_round3_panel.md")), 3)
        self.assertIsNone(calibration.round_number(pathlib.Path("prep_round1.md")))

    def test_outcome_date_from_notes(self):
        self.assertEqual(calibration.outcome_date("tailored; outcome 2026-08-27"), "2026-08-27")
        self.assertEqual(calibration.outcome_date("outcome 2026-08"), "2026-08")
        self.assertEqual(calibration.outcome_date("no date here"), "?")

    def test_is_match(self):
        self.assertTrue(calibration.is_match("advance", "ADVANCED to R3", "matched"))
        self.assertTrue(calibration.is_match("advance to R3", "ADVANCED. Invited onsite", ""))
        self.assertTrue(calibration.is_match("decline", "no offer; silent", "none; predicted decline, got silence"))
        self.assertFalse(calibration.is_match("decline (no offer)", "offer came", ""))
        self.assertFalse(calibration.is_match("advance", "rejected", "harder than predicted"))

    def test_suggest_needs_a_round_date_before_claiming_a_later_round(self):
        import datetime
        rounds = [{"company": "Example Co", "date": "2026-02-01", "label": "R3"}]
        today = datetime.date(2026, 3, 1)
        self.assertIn("advanced", calibration.suggest("Example Co", "2026-01-16", 2, {}, rounds, {}, today))
        self.assertEqual(calibration.suggest("Example Co", "", 2, {}, rounds, {}, today), "")

    def test_silence_is_named_when_nothing_else_is_on_file(self):
        import datetime
        today = datetime.date(2026, 3, 1)
        s = calibration.suggest("Example Co", "2026-01-16", 2, {}, [], {}, today)
        self.assertIn("silent", s)


if __name__ == "__main__":
    unittest.main()
