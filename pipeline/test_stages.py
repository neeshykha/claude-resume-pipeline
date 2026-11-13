#!/usr/bin/env python3
"""Tests for stages.py: each script that asks "was this sent?" still gets the
exact stages it had before the five definitions moved into one file (2026-11-12).

One of the five has changed on purpose since: pipeline_quality.py counts sends
with stages.counts_as_sent(), which takes a `closed` row only when the row shows
a send. Every branch of that rule is checked at the bottom, on made-up rows.

Run: .venv/bin/python pipeline/test_stages.py

Nothing here reads the tracker.
"""
import importlib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_dashboard  # noqa: E402
import check_voice  # noqa: E402
import pipeline_quality  # noqa: E402
import shelf_inbox  # noqa: E402
import stages  # noqa: E402
import update_tracking  # noqa: E402
from repair_outcomes import FURTHEST_STAGES  # noqa: E402

FAILS = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


# What each script's own SENT_STAGES literal held before the move, copied from the
# files as they stood. Written out here and not read from stages.py, so a change
# to a shared set fails once for every script it would change.
# pipeline_quality.py is not in these two tables any more: it held the seven stages
# of SENT_COUNTING_CLOSED until its count moved to counts_as_sent() (checked below).
BEFORE = {
    "build_dashboard": {"applied", "rejected", "interview", "assessment", "onsite", "offer"},
    "update_tracking": {"applied", "rejected", "interview", "assessment", "onsite", "offer"},
    "shelf_inbox": {"applied", "rejected", "closed", "interview", "assessment"},
    "check_voice": {"applied", "rejected", "closed", "expired", "interview", "assessment", "onsite", "offer"},
}
# The named set each script imports now.
USES = {
    "build_dashboard": (build_dashboard, "SEND_PROVEN"),
    "update_tracking": (update_tracking, "SEND_PROVEN"),
    "shelf_inbox": (shelf_inbox, "SEND_ALREADY_RECORDED"),
    "check_voice": (check_voice, "ASSUME_SENT_FOR_SAFETY"),
}
# SENT_COUNTING_CLOSED has no importer now; it is still the base of the guard set.
NAMED = sorted({name for _, name in USES.values()} | {"SENT_COUNTING_CLOSED"})

# --- each script, before against now ---------------------------------------
for script, (module, named) in USES.items():
    check(f"{script}: SENT_STAGES holds the stages it held before the move",
          set(module.SENT_STAGES) == BEFORE[script])
    check(f"{script}: SENT_STAGES is stages.{named}, not a copy of its own",
          module.SENT_STAGES is getattr(stages, named))
    check(f"{script}: every stage it had is in the vocabulary", BEFORE[script] <= stages.STAGES)

# fit_check.py reads the guard's set through check_voice, as a set.
check("check_voice.SENT_STAGES still works as fit_check.py uses it",
      set(check_voice.SENT_STAGES) & {"expired", "surfaced"} == {"expired"})


# --- the two scripts that must never fail the daily run ---------------------
def without_stages(module):
    """The module's SENT_STAGES when stages.py cannot be imported: its guarded copy."""
    real = sys.modules["stages"]
    sys.modules["stages"] = None  # `from stages import ...` now raises ImportError
    try:
        return importlib.reload(module).SENT_STAGES
    finally:
        sys.modules["stages"] = real
        importlib.reload(module)


for script in ("build_dashboard", "shelf_inbox"):
    module, named = USES[script]
    check(f"{script}: with stages.py broken it still loads, on the same stages",
          set(without_stages(module)) == BEFORE[script])
    check(f"{script}: and it is back on stages.{named} afterward",
          module.SENT_STAGES is getattr(stages, named))

# --- the vocabulary and the named sets --------------------------------------
for named in NAMED:
    value = getattr(stages, named)
    check(f"stages.{named} is a frozenset, so no importer can change it for the others",
          isinstance(value, frozenset))
    check(f"stages.{named} uses only stage names in the vocabulary", value <= stages.STAGES)
check("no stage name is listed twice in the vocabulary",
      len(stages.DOCUMENTED_STAGES + stages.IN_PROCESS_STAGES) == len(stages.STAGES))
check("`surfaced` and `tailored` are in no sent set",
      not any({"surfaced", "tailored"} & getattr(stages, named) for named in NAMED))
check("IN_PROCESS_STAGES is repair_outcomes.FURTHEST_STAGES past `applied`",
      list(stages.IN_PROCESS_STAGES) == FURTHEST_STAGES[FURTHEST_STAGES.index("applied") + 1:])
check("DOCUMENTED_STAGES matches the stages build_dashboard.py knows",
      set(stages.DOCUMENTED_STAGES) == build_dashboard.KNOWN_STAGES - {""})

# CLAUDE.md is where the documented vocabulary comes from. Compared only when the
# paragraph is there to read: a doc that moved is not this test's failure to report.
try:
    with open(os.path.join(os.path.dirname(HERE), "CLAUDE.md"), encoding="utf-8") as f:
        para = re.search(r"\*\*Stage vocabulary:\*\*(.*?)(?:\n\s*\n|\Z)", f.read(), re.S)
except OSError:
    para = None
if para:
    check("DOCUMENTED_STAGES matches CLAUDE.md's Stage vocabulary line",
          re.findall(r"`([a-z]+)`", para.group(1)) == list(stages.DOCUMENTED_STAGES))
else:
    print("SKIP CLAUDE.md has no Stage vocabulary line to compare against")

check("SENT_COUNTING_CLOSED is still SEND_PROVEN plus `closed`, and the guard set is built on it",
      stages.SENT_COUNTING_CLOSED == stages.SEND_PROVEN | {"closed"}
      and stages.ASSUME_SENT_FOR_SAFETY == stages.SENT_COUNTING_CLOSED | {"expired"})


# --- the quality report's rule: counts_as_sent ------------------------------
# Every row is made up. A row here is the three columns the rule reads.
def r(stage, verdict="", notes="", **more):
    return dict(stage=stage, his_verdict=verdict, notes=notes, **more)


TAILORING = "Full tailoring + cover. Remote US, $120K-$140K. Coverage 14/15"   # what a row's notes open with
sent = stages.counts_as_sent
ROWS = []          # every row checked below, for the pipeline_quality comparison at the end


def rule(name, row, want):
    ROWS.append(row)
    check(f"counts_as_sent: {name}", sent(row) is want)


# 1. the stage alone proves it
for stage in sorted(stages.SEND_PROVEN):
    rule(f"`{stage}` is a send with nothing else on the row", r(stage), True)
rule("`applied` is a send even when its notes carry a never-sent marker",
     r("applied", notes=f"{TAILORING}; outcome 2026-02-03; posting gone 2026-02-03, never sent"), True)
rule("`rejected` is a send with a skip verdict on it", r("rejected", "skip_fit"), True)

# 2. any other stage but `closed`: his verdict, and only his verdict
for stage in ("surfaced", "expired", "tailored", ""):
    rule(f"`{stage or '(blank)'}` with no verdict is not a send", r(stage), False)
rule("`surfaced` with a sent_as_is verdict is a send", r("surfaced", "sent_as_is"), True)
rule("`expired` with a sent_edited verdict is a send", r("expired", "sent_edited"), True)
rule("`surfaced` with a skip verdict is not a send", r("surfaced", "skip_time"), False)
rule("`expired` is not a send on a company email in its notes; only `closed` rows are read that way",
     r("expired", notes=f"{TAILORING}; outcome 2026-02-03; Email 2026-02-03: role filled"), False)
rule("`surfaced` with a sent verdict stays a send beside a never-sent marker; the markers are for `closed`",
     r("surfaced", "sent_as_is", notes="posting gone 2026-02-03"), True)

# 3. `closed`: nothing either way
rule("`closed` with nothing on the row is not a send", r("closed"), False)
rule("`closed` with only tailoring notes is not a send", r("closed", notes=TAILORING), False)
rule("`closed` with a date in applied_date and nothing else is not a send",
     r("closed", notes=TAILORING, applied_date="2026-02-01"), False)
rule("`closed` with a skip verdict is not a send", r("closed", "skip_other", notes=TAILORING), False)
rule("`closed` with an outcome stamp and no note after it is not a send",
     r("closed", notes=f"{TAILORING}; outcome 2026-02-03"), False)

# 3. `closed`: each thing that shows a send
rule("`closed` with a sent_as_is verdict is a send", r("closed", "sent_as_is", notes=TAILORING), True)
rule("`closed` with a sent_edited verdict and no notes is a send", r("closed", "sent_edited"), True)
rule("`closed` with an applied-date line in the closing note is a send",
     r("closed", notes=f"{TAILORING}; outcome 2026-02-17; Role filled. Applied 2026-02-03, 14 days."), True)
for word, note in (("email", "Email 2026-02-17 from the recruiting inbox: role recently filled"),
                   ("e-mail", "Their e-mail of 2026-02-17 says the search has ended"),
                   ("notice", "2026-02-17 notice: 'we've recently filled this position'"),
                   ("notified", "Position filled; the company notified him 2026-02-17 that the req was closed"),
                   ("notification", "ATS notification 2026-02-17: no longer considering applicants")):
    rule(f"`closed` with a company {word} in the closing note is a send",
         r("closed", notes=f"{TAILORING}; outcome 2026-02-17; {note}"), True)

# 3. `closed`: each never-sent marker. The first row has no send on it, so it is not
# a send either way; the rest each sit beside a company email, so the marker decides.
rule("`closed` with a never-sent marker and no send on the row is not a send",
     r("closed", notes=f"{TAILORING}; outcome 2026-02-03; closed at his OK in chat; never sent"), False)
for marker in stages.NEVER_SENT_MARKERS:
    rule(f'`closed` with "{marker}" beside a company email is not a send',
         r("closed", notes=f"{TAILORING}; outcome 2026-02-03; Email 2026-02-03: req closed. Closed at his OK, {marker}"),
         False)
check("the never-sent markers are the seven he listed",
      set(stages.NEVER_SENT_MARKERS) == {"never sent", "never submitted", "not pursued", "not to apply",
                                         "do not count", "posting gone", "dropped"})

# 3. `closed`: a send and a never-sent marker on the same row; the marker wins
rule("`closed` with a sent verdict and a never-sent marker is not a send",
     r("closed", "sent_as_is", notes=f"{TAILORING}; outcome 2026-02-03; posting gone 2026-02-03, closed"), False)
rule("`closed` with an applied-date line and a never-sent marker is not a send",
     r("closed", notes=f"{TAILORING}; outcome 2026-02-03; Applied 2026-02-01. Do NOT count this row in send-rate math"),
     False)
rule("`closed` with a company email and a never-sent marker is not a send",
     r("closed", notes=f"{TAILORING}; outcome 2026-02-03; Email 2026-02-03 said the req closed; never sent"), False)
for row, want in ((r("closed", "sent_as_is", notes="outcome 2026-02-03; posting gone"), (True, True)),
                  (r("closed", "sent_as_is"), (True, False)),
                  (r("closed", notes="never sent"), (False, True)),
                  (r("closed"), (False, False))):
    shows, never = stages.closed_row_evidence(row)
    check(f"closed_row_evidence: a send {want[0]}, a never-sent marker {want[1]}", (bool(shows), bool(never)) == want)

# 3. `closed`: only the closing note is read when there is an outcome stamp
rule("`closed`: the word email in the tailoring notes, before the stamp, is not a send",
     r("closed", notes="Bullet on the email digests he built; outcome 2026-02-03; req closed"), False)
rule("`closed`: an applied-date line before the stamp is not a send",
     r("closed", notes="He applied 2026-01-05 to a sibling req; outcome 2026-02-03; req closed"), False)
rule("`closed`: the word dropped in the tailoring notes does not undo a send in the closing note",
     r("closed", notes="Dropped the IoT bullet for length; outcome 2026-02-17; Email 2026-02-17: role filled"), True)
rule("`closed`: with two stamps, the note after the last one is read",
     r("closed", notes="x; outcome 2026-02-03; never sent; outcome 2026-02-17; Email 2026-02-17: role filled"), True)
rule("`closed`: and the other way round",
     r("closed", notes="x; outcome 2026-02-03; Email 2026-02-03: role filled; outcome 2026-02-17; never sent"), False)

# 3. `closed`: no outcome stamp, so all of the notes are read
rule("`closed` by hand, no stamp: a company email anywhere in the notes is read",
     r("closed", notes=f"{TAILORING}; recruiter email 2026-02-03: role filled"), True)
rule("`closed` by hand, no stamp: a never-sent marker anywhere in the notes is read",
     r("closed", notes=f"{TAILORING}; recruiter email 2026-02-03: role filled; Closed 2026-02-10, not pursued."), False)

# how the row is read
rule("letter case does not matter for a marker",
     r("closed", notes="outcome 2026-02-03; Email 2026-02-03: req closed. NEVER SENT"), False)
rule("letter case does not matter for the evidence", r("closed", notes="outcome 2026-02-03; EMAIL 2026-02-03"), True)
rule("a marker split across a line break is still read",
     r("closed", notes="outcome 2026-02-03; Email 2026-02-03: req closed; never\n sent"), False)
rule("emailed and noticed are not the words email and notice",
     r("closed", notes="outcome 2026-02-03; nobody emailed, and he noticed the req was gone"), False)
rule("blank columns read as blank", dict(stage=" closed ", his_verdict=None, notes=None), False)
rule("a row with no his_verdict or notes column at all", dict(stage="closed"), False)
rule("spaces around the stage and the verdict are ignored", dict(stage=" closed ", his_verdict=" sent_as_is ", notes=""), True)

# --- pipeline_quality.py reads the rule and keeps no set of its own -----------
check("pipeline_quality: is_sent() agrees with counts_as_sent() on every row above",
      all(pipeline_quality.is_sent(row) is sent(row) for row in ROWS))
check("pipeline_quality: it has no SENT_STAGES of its own any more", not hasattr(pipeline_quality, "SENT_STAGES"))
check("pipeline_quality: a `closed` row is no longer a send on its stage",
      not pipeline_quality.is_sent(r("closed")))

print(f"\n{'ALL PASS' if not FAILS else str(len(FAILS)) + ' FAILED'}")
sys.exit(1 if FAILS else 0)
