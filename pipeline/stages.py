#!/usr/bin/env python3
"""The tracker's stage names, and each meaning of "sent", in one place.

Until 2026-11-12 five scripts each defined their own SENT_STAGES, and the five
held four different sets of stages. Some of that is meant: a guard that stops a
sent letter from being edited has to lean toward "sent", and a count of sends
should not. The rest could not be told apart from accident, because nothing said
which set was for what.

Each set below is named for what it is for. Each of the five scripts imports the
one whose membership it already had, so moving them here changed no behavior.
test_stages.py pins every script to the set it had before the move.

One script has moved since, the same day and on his call: pipeline_quality.py no
longer counts every `closed` row as a send. Its count is counts_as_sent(), at the
bottom of this file, which asks a `closed` row to show that it went out.

When a script needs a meaning none of these has, add a named set. Changing the
membership of an existing set changes every script that imports it.

This file is committed to a public repo. No company names, no sample rows.
"""
import re

# --- the vocabulary -------------------------------------------------------

# The `stage` column of outcomes.csv, from CLAUDE.md ("Stage vocabulary"):
#   surfaced   tailored, not confirmed sent
#   expired    retired by age_report.py after 45 days with no confirmation
#   tailored   legacy
DOCUMENTED_STAGES = ("surfaced", "applied", "rejected", "closed", "expired", "tailored")

# furthest_stage names (FURTHEST_STAGES in repair_outcomes.py, past `applied`)
# that the `stage` column also holds. mark_outcome.py writes `interview` and
# `offer` there by default, and any stage its input names. DASHBOARD_SPEC.md
# calls these off-vocabulary for `stage`, but the rows exist, so every set below
# has to say whether it takes them.
IN_PROCESS_STAGES = ("assessment", "interview", "onsite", "offer")

STAGES = frozenset(DOCUMENTED_STAGES + IN_PROCESS_STAGES)

# --- what counts as sent --------------------------------------------------
# `surfaced` and `tailored` are in none of these.

# The stage alone proves the application went out. `closed` is left out on
# purpose: a posting can come down before he applies, so a closed row may never
# have been sent, and each script that uses this set judges `closed` on other
# evidence.
#   build_dashboard.py   a send on the Progress charts; a `closed` row counts
#                        only with a sent verdict or a confirmation naming it (D42)
#   update_tracking.py   a retailor refuses the row; a `closed` row needs
#                        "never_sent": true (D39)
SEND_PROVEN = frozenset(("applied", "rejected", "interview", "assessment", "onsite", "offer"))

# SEND_PROVEN plus every `closed` row, sent or not, with no evidence asked for.
# This counts a closed row that never went out as a send. pipeline_quality.py
# counted sends this way until 2026-11-12 and now uses counts_as_sent() below;
# no script counts with this set any more. It stays because the guard set under
# it is built on it and SEND_ALREADY_RECORDED is described against it.
SENT_COUNTING_CLOSED = SEND_PROVEN | {"closed"}

# A send is possible and has to be assumed: SENT_COUNTING_CLOSED plus `expired`.
# For guards on the record of what an employer read, where calling an unsent
# letter sent costs a question and the opposite mistake rewrites a letter that
# went out. check_voice.py's rule is that a letter whose row has left `surfaced`
# is that record. `expired` belongs here because it only means no confirmation
# was matched in 45 days, and confirmations get missed.
#   check_voice.py       a letter at one of these stages is reported, never edited
#   fit_check.py         reads check_voice.SENT_STAGES; that package is not rendered
ASSUME_SENT_FOR_SAFETY = SENT_COUNTING_CLOSED | {"expired"}

# A send is already on the row, so a new send signal for it is filed as already
# recorded.
#   shelf_inbox.py       a Sent mark on a row at one of these stages; at any other
#                        stage past `surfaced` the mark is stale
# mark_applied.py keeps a local set with these same five names, for a
# confirmation email whose row is past `surfaced`.
# This is SENT_COUNTING_CLOSED without `onsite` and `offer`, and nothing in
# either script says the gap is meant. update_tracking.py and build_dashboard.py
# were both written as "the stages mark_applied.py and shelf_inbox.py treat as
# sent, less closed", and they hold `onsite` and `offer` where these two do not.
# It has its own name so the difference stays visible: pointing shelf_inbox.py at
# a wider set would change what it does with a Sent mark on an onsite or offer row.
SEND_ALREADY_RECORDED = frozenset(("applied", "rejected", "closed", "interview", "assessment"))

# --- the quality report's count of sends ----------------------------------
#   pipeline_quality.py  is_sent(): the send rate, the "sent roles only"
#                        traction, and the monthly trend's sent column

# mark_outcome.py appends "; outcome YYYY-MM-DD" to a row's notes and then the
# note about how the row ended. A closed row is read from what follows the last
# of those stamps, because the tailoring notes before it use the same words for
# other reasons (a resume bullet about email, a line that was dropped). A row
# closed by hand has no stamp, and then the whole of its notes is read.
_OUTCOME_STAMP_RE = re.compile(r"(?:^|;)\s*outcome \d{4}-\d{2}-\d{2}\s*(?=;|$)")
_SEND_EVIDENCE = (
    ("an applied-date line", re.compile(r"\bapplied \d{4}-\d{2}-\d{2}\b", re.I)),
    ("a company email or notice", re.compile(r"\b(?:e-?mail|notice|notified|notification)\b", re.I)),
)
# Words in a closing note that say the application never went out. Matched as
# written, in any letter case.
NEVER_SENT_MARKERS = ("never sent", "never submitted", "not pursued", "not to apply",
                      "do not count", "posting gone", "dropped")


def closed_row_evidence(row):
    """What a `closed` row says about a send, as two lists of short labels:
    (what shows a send, which never-sent markers its closing note carries).
    Either list may be empty. counts_as_sent() is the rule that weighs them.
    """
    verdict = (row.get("his_verdict") or "").strip()
    notes = row.get("notes") or ""
    parts = _OUTCOME_STAMP_RE.split(notes)
    text = " ".join((parts[-1] if len(parts) > 1 else notes).split())
    shows = [f"his_verdict {verdict}"] if verdict.startswith("sent") else []
    shows += [label for label, rx in _SEND_EVIDENCE if rx.search(text)]
    low = text.lower()
    return shows, [marker for marker in NEVER_SENT_MARKERS if marker in low]


def counts_as_sent(row):
    """Did this row's application go out? The quality report's one rule for a send.

    A row counts as sent when any of these holds:

      1. Its stage is in SEND_PROVEN (applied, rejected, interview, assessment,
         onsite, offer). The stage alone proves it.
      2. Its stage is anything but `closed` and his_verdict starts with `sent`.
         That is his own word for it, and the report has always taken it.
      3. Its stage is `closed` and the row shows a send and nothing on it says
         otherwise. A send shows as a his_verdict that starts with `sent`, or
         as a closing note that carries an applied-date line ("Applied
         2026-01-15") or a company email or notice ("email", "notice",
         "notified", "notification"). "Says otherwise" is a closing note with
         any of NEVER_SENT_MARKERS in it: never sent, never submitted, not
         pursued, not to apply, do not count, posting gone, dropped.

    A `closed` row with nothing either way is not a send: a posting can come
    down before he applies, so the stage proves nothing. A `closed` row with
    both a send and a never-sent marker is not a send either; the marker wins,
    his verdict included, and pipeline_quality.py names how many such rows it
    met so one can be looked at by hand. The closing note is what follows the
    last "; outcome YYYY-MM-DD" stamp in the notes, or all of the notes when
    there is no stamp (see _OUTCOME_STAMP_RE). The `applied_date` column is not
    evidence: closed rows that never went out carry a date there too.

    `row` is one outcomes.csv row as a dict. Only `stage`, `his_verdict`, and
    `notes` are read.
    """
    stage = (row.get("stage") or "").strip()
    if stage in SEND_PROVEN:
        return True
    if stage != "closed":
        return (row.get("his_verdict") or "").strip().startswith("sent")
    shows, never = closed_row_evidence(row)
    return bool(shows) and not never
