#!/usr/bin/env python3
"""Tests for postmortem_draft.py. Made-up companies, meetings, and text only.

    .venv/bin/python pipeline/test_postmortem_draft.py
"""
import json
import os
import pathlib
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import postmortem_draft as pd  # noqa: E402


def companies(*names, folders=(), live=()):
    """Fake pipeline companies. Those in `folders` or `live` count as having a process on file."""
    out = {}
    for n in names:
        is_live = n in folders or n in live
        out[pd.norm(n)] = {"name": n, "folder": n if n in folders else None, "role": "Example Role",
                           "sources": ["test"], "live": is_live,
                           "pattern": pd.company_pattern(n, loose=is_live),
                           "generic": pd.norm(n) in pd.GENERIC_NAMES}
    return out


GOOD_DRAFT = """# Post-Mortem — Example Co, Example Role, Round 2 (Hiring Manager)

> Drafted 2026-01-17 by the transcript routine from the Wispr Flow transcript. Grades proposed by
> Claude, not yet graded by Aneesh.

## 1. Logistics

- **Date**: Fri 2026-01-16, 3:00 PM

## 2. What Went Well

- a thing

## 3. What Surprised You

- a thing

## 4. Questions You Got + How You Answered

| # | Question | Your answer (summary) | Grade | Notes |
|---|----------|----------------------|-------|-------|
| 1 | q | a | B | n |
| 2 | q | a | C+ | n |
| 3 | q | a | A- | n |

## 5. Questions You Wish You'd Asked / Things You Wish You'd Said

- a thing

## 6. Lessons Learned

### For this company / next round
- a thing

## 7. Follow-Ups

- [ ] a thing

## 8. Calibration Loop

**At time of post-mortem:**
- **Predicted outcome**: advance
- **Confidence**: medium
- **Reasoning**: because

**When outcome lands:**
- **Actual outcome**:
- **Date outcome learned**:
"""


class CompanyPatternTests(unittest.TestCase):
    def test_hyphenated_name_matches_its_spellings_and_not_lookalikes(self):
        p = pd.company_pattern("Acme-x")
        for text in ("Acme-x", "Acme X", "Acmex", "likely Acme-x)", "ACME x"):
            self.assertTrue(p.search(text), text)
        for text in ("Acmexa", "Acmely", "acme", "xacme x"):
            self.assertFalse(p.search(text), text)

    def test_trailing_stopword_is_optional_only_when_loose(self):
        loose = pd.company_pattern("Widgetron AI", loose=True)
        self.assertTrue(loose.search("a screen at Widgetron"))
        self.assertTrue(loose.search("Widgetron AI, Inc."))
        self.assertFalse(loose.search("Widgetronics"))
        strict = pd.company_pattern("Level AI")
        self.assertFalse(strict.search("the next level of the plan"))
        self.assertTrue(strict.search("a call with Level AI"))

    def test_too_short_names_do_not_match(self):
        self.assertIsNone(pd.company_pattern("AI"))
        self.assertIsNone(pd.company_pattern(""))

    def test_most_specific_company_wins_in_the_title(self):
        cs = companies("Beam", "Beam Robotics")
        best, standalone, _ = pd.find_company("Recruiter call with Beam Robotics", "", cs)
        self.assertEqual(best["name"], "Beam Robotics")
        self.assertTrue(standalone)

    def test_summary_mention_stands_alone_only_for_a_live_company(self):
        cs = companies("Example Co", "Ticketron", live=("Example Co",))
        live, standalone, _ = pd.find_company("Chat", "Caught up with the Example Co team", cs)
        self.assertEqual((live["name"], standalone), ("Example Co", True))
        other, standalone, note = pd.find_company("Ops sync", "we moved the queue into Ticketron", cs)
        self.assertEqual((other["name"], standalone), ("Ticketron", False))
        self.assertIn("low confidence", note)

    def test_live_company_outranks_a_tool_named_in_the_summary(self):
        cs = companies("Example Co", "Ticketron", live=("Example Co",))
        best, _, _ = pd.find_company("Interview", "Interview at Example Co; they use Ticketron", cs)
        self.assertEqual(best["name"], "Example Co")

    def test_two_tracker_only_mentions_leave_the_company_unknown(self):
        cs = companies("Ticketron", "Formly")
        best, standalone, note = pd.find_company("Hiring manager interview", "they run Ticketron and Formly", cs)
        self.assertIsNone(best)
        self.assertIn("company unknown", note)


class MarkerTests(unittest.TestCase):
    def test_strong_markers_in_summary_count(self):
        self.assertIn("hiring manager", pd.interview_markers("Weekly sync", "Call with the hiring manager"))
        self.assertIn("recruiter", pd.interview_markers("Intro", "A recruiter walked through the role"))

    def test_screen_and_panel_count_only_in_title(self):
        self.assertEqual(pd.interview_markers("Ops sync", "we did a screen share and a control panel demo"), [])
        self.assertIn("screen (title)", pd.interview_markers("Phone Screen", ""))

    def test_screenshot_is_not_a_screen(self):
        self.assertEqual(pd.interview_markers("Screenshot review", "screenshots of the dashboard"), [])


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self._old = (pd.PREP, pd.ROOT)
        pd.ROOT = root
        pd.PREP = root / "interview_prep"
        (pd.PREP / "Example Co").mkdir(parents=True)
        (pd.PREP / "Example Co" / "prep_round2_hiring_manager.md").write_text("x")
        (pd.PREP / "Example Co" / "postmortem_round1_recruiter_screen.md").write_text("x")
        self.companies = companies("Example Co", "Zoom", folders=("Example Co",))
        self.rounds = [
            {"company": "Example Co", "date": "2026-01-09", "kind": "screen", "round": 1, "label": "R1 recruiter screen"},
        ]

    def tearDown(self):
        pd.PREP, pd.ROOT = self._old
        self.tmp.cleanup()

    def meeting(self, **kw):
        m = {"id": "m1", "title": "Example Co Interview", "content_excerpt": "Interview for a role at Example Co",
             "start": "2026-01-16T20:00:00Z", "end": "2026-01-16T20:40:00Z", "has_transcript": True,
             "finalized": True, "share_link": "https://example.invalid/x"}
        m.update(kw)
        return m

    def classify(self, meetings, state=None):
        return pd.classify_meetings(meetings, state or {"meetings": {}}, self.companies, self.rounds)

    def test_interview_at_pipeline_company_is_drafted_with_round_and_type_from_prep_doc(self):
        r = self.classify([self.meeting()])[0]
        self.assertTrue(r["interview_like"])
        self.assertEqual(r["action"], "draft")
        self.assertEqual(r["company"], "Example Co")
        self.assertEqual(r["round"], 2)
        self.assertEqual(r["type"], "hiring_manager")  # from prep_round2_hiring_manager.md
        self.assertEqual(r["target"], "interview_prep/Example Co/postmortem_round2_hiring_manager.md")
        self.assertEqual(r["date"], "2026-01-16")  # 20:00Z is 3 PM Eastern, same day

    def test_same_day_round_in_interviews_json_wins(self):
        self.rounds.append({"company": "Example Co", "date": "2026-01-16", "kind": "onsite", "round": 3,
                            "label": "R3 panel with the team"})
        r = self.classify([self.meeting()])[0]
        self.assertEqual((r["round"], r["type"]), (3, "panel"))
        self.assertEqual(r["round_source"], "interviews.json")

    def test_existing_postmortem_is_never_overwritten(self):
        (pd.PREP / "Example Co" / "postmortem_round2_hiring_manager.md").write_text("his graded file")
        r = self.classify([self.meeting()])[0]
        self.assertEqual(r["action"], "skip:exists")

    def test_handled_meeting_is_skipped(self):
        state = {"meetings": {"m1": {"status": "drafted"}}}
        r = self.classify([self.meeting()], state)[0]
        self.assertEqual(r["action"], "skip:handled (drafted)")

    def test_company_only_match_counts_unless_the_name_is_generic(self):
        r = self.classify([self.meeting(title="Chat", content_excerpt="Caught up with the Example Co team")])[0]
        self.assertTrue(r["interview_like"])
        self.assertEqual(r["company_confidence"], "high")
        z = self.classify([self.meeting(id="m2", title="Quarterly review", content_excerpt="30-min Zoom with the ops team")])[0]
        self.assertFalse(z["interview_like"])
        self.assertEqual(z["action"], "skip:not-interview")

    def test_tracker_only_company_in_a_summary_needs_an_interview_word(self):
        self.companies.update(companies("Ticketron"))
        quiet = self.classify([self.meeting(id="m3", title="Ops sync", content_excerpt="moved the queue into Ticketron")])[0]
        self.assertEqual(quiet["action"], "skip:not-interview")
        loud = self.classify([self.meeting(id="m4", title="Recruiter call", content_excerpt="a role at Ticketron")])[0]
        self.assertEqual((loud["action"], loud["company"], loud["company_confidence"]), ("draft", "Ticketron", "low"))
        titled = self.classify([self.meeting(id="m5", title="Ticketron chat", content_excerpt="the team and the role")])[0]
        self.assertEqual((titled["action"], titled["company_confidence"]), ("draft", "high"))

    def test_short_recordings_and_missing_transcripts_are_skipped(self):
        short = self.classify([self.meeting(end="2026-01-16T20:05:00Z")])[0]
        self.assertTrue(short["action"].startswith("skip:short"))
        none = self.classify([self.meeting(has_transcript=False)])[0]
        self.assertEqual(none["action"], "skip:no-transcript")

    def test_interview_at_unknown_company_still_surfaces(self):
        r = self.classify([self.meeting(title="Hiring manager interview", content_excerpt="A call with Nobody Corp")])[0]
        self.assertEqual(r["action"], "draft:company-unknown")

    def test_work_meeting_is_not_an_interview(self):
        r = self.classify([self.meeting(title="Thermostat escalation sync", content_excerpt="Reviewed the escalations dashboard")])[0]
        self.assertEqual(r["action"], "skip:not-interview")


class RoundInferenceTests(unittest.TestCase):
    def test_next_after_last_logged_round(self):
        rounds = [{"company": "Example Co", "date": "2026-01-09", "kind": "screen", "round": 1}]
        arts = {"postmortems": ["postmortem_round1_recruiter_screen.md"], "preps": [], "transcripts": []}
        self.assertEqual(pd.infer_round("Example Co", "2026-01-16", rounds, arts)[:2], (2, ""))

    def test_open_prep_doc_names_the_round_when_nothing_is_logged(self):
        arts = {"postmortems": [], "preps": ["prep_round1_intro.md"], "transcripts": []}
        self.assertEqual(pd.infer_round("Example Co", "2026-01-16", [], arts)[:2], (1, "intro"))

    def test_first_round_on_file(self):
        arts = {"postmortems": [], "preps": [], "transcripts": []}
        n, t, how = pd.infer_round("Example Co", "2026-01-16", [], arts)
        self.assertEqual((n, t), (1, ""))
        self.assertEqual(how, "first round on file")

    def test_type_from_label_and_kind(self):
        self.assertEqual(pd.type_from_text("R2 hiring manager (A Director)"), "hiring_manager")
        self.assertEqual(pd.type_from_text("R1 recruiter screen"), "recruiter_screen")
        self.assertEqual(pd.type_from_text("R3 in person with the CTO"), "executive")
        self.assertEqual(pd.type_from_text("Weekly sync"), "")
        self.assertEqual(pd.KIND_TYPES["screen"], "recruiter_screen")


class DraftShapeTests(unittest.TestCase):
    def test_good_draft_passes(self):
        self.assertEqual(pd.validate_draft(GOOD_DRAFT), [])

    def test_missing_pieces_are_named(self):
        bad = GOOD_DRAFT.replace("## 7. Follow-Ups", "## 7. Followups").replace("- **Predicted outcome**: advance", "- **Predicted outcome**:")
        problems = pd.validate_draft(bad)
        self.assertTrue(any("## 7. Follow-Ups" in p for p in problems))
        self.assertTrue(any("Predicted outcome" in p for p in problems))

    def test_filled_actual_outcome_is_rejected(self):
        bad = GOOD_DRAFT.replace("- **Actual outcome**:", "- **Actual outcome**: advanced")
        self.assertTrue(any("Actual outcome" in p for p in pd.validate_draft(bad)))

    def test_banned_phrase_is_rejected(self):
        bad = GOOD_DRAFT.replace("- a thing", "- it's worth noting that he was genuinely good", 1)
        problems = pd.validate_draft(bad)
        self.assertTrue(any("genuinely" in p for p in problems))
        self.assertTrue(any("worth noting" in p for p in problems))

    def test_header_must_say_it_is_a_draft_from_the_transcript(self):
        bad = GOOD_DRAFT.replace("not yet graded by Aneesh", "graded")
        self.assertTrue(any("not yet graded" in p for p in pd.validate_draft(bad)))

    def test_fewer_than_three_graded_rows_fails(self):
        bad = GOOD_DRAFT.replace("| 3 | q | a | A- | n |\n", "")
        self.assertTrue(any("section 4" in p for p in pd.validate_draft(bad)))


class PostTextTests(unittest.TestCase):
    def test_one_line_with_company_round_type_and_path(self):
        t = pd.post_text("Example Co", 2, "hiring_manager", "2026-01-16", "/x/postmortem_round2_hiring_manager.md")
        self.assertNotIn("\n", t)
        self.assertTrue(t.startswith("Heads up: Example Co R2 (hiring manager, Fri Jan 16)"))
        self.assertTrue(t.endswith("ready to grade: /x/postmortem_round2_hiring_manager.md"))


class StateTests(unittest.TestCase):
    def test_state_round_trips_with_backup(self):
        with tempfile.TemporaryDirectory() as d:
            old = pd.STATE
            pd.STATE = pathlib.Path(d) / "postmortem_drafts.json"
            try:
                s = pd.load_state()
                self.assertEqual(s["meetings"], {})
                s["meetings"]["m1"] = {"status": "skipped"}
                pd.save_state(s)
                pd.save_state(s)
                self.assertTrue(pd.STATE.exists())
                self.assertTrue(pd.STATE.with_suffix(".json.bak").exists())
                self.assertEqual(json.loads(pd.STATE.read_text())["meetings"]["m1"]["status"], "skipped")
            finally:
                pd.STATE = old


class LocalSettingTests(unittest.TestCase):
    """The channel id and the ntfy topic come from the gitignored local config, never the source."""

    def test_reads_a_string_and_tolerates_a_missing_file_or_key(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = pathlib.Path(d) / "local_config.json"
            with mock.patch.object(pd, "LOCAL_CONFIG", cfg):
                self.assertEqual(pd.local_setting("NTFY_TOPIC"), "")              # no file
                cfg.write_text('{"NTFY_TOPIC": " made-up-topic ", "COUNT": 5}', encoding="utf-8")
                self.assertEqual(pd.local_setting("NTFY_TOPIC"), "made-up-topic")
                self.assertEqual(pd.local_setting("FOLLOWUPS_CHANNEL_ID"), "")    # no key
                self.assertEqual(pd.local_setting("COUNT"), "")                   # not a string
                cfg.write_text("not json", encoding="utf-8")
                self.assertEqual(pd.local_setting("NTFY_TOPIC"), "")

    def test_a_missing_channel_id_and_topic_send_nothing_and_say_why(self):
        with tempfile.TemporaryDirectory() as d:
            payload = pathlib.Path(d) / "post-m1.json"
            payload.write_text(json.dumps({"channel_id": "", "text": "Heads up: Example Co R2"}), encoding="utf-8")
            with mock.patch.object(pd, "LOCAL_CONFIG", pathlib.Path(d) / "absent.json"), \
                    mock.patch.object(pd.subprocess, "run") as run:
                posted = pd.send(payload, {})
            run.assert_not_called()
            self.assertEqual(posted["exit"], 1)
            self.assertIn("FOLLOWUPS_CHANNEL_ID", posted["stderr"])
            self.assertIn("NTFY_TOPIC", posted["fallback"]["stderr"])

    def test_no_channel_id_or_topic_is_written_in_the_source(self):
        src = pathlib.Path(pd.__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\b\d{17,19}\b", src), "a Discord-id-shaped number is in the source")
        self.assertNotIn("ntfy.sh", src)


if __name__ == "__main__":
    unittest.main()
