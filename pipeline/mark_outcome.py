#!/usr/bin/env python3
"""Records real application OUTCOMES into outcomes.csv.

Usage:
    .venv/bin/python pipeline/mark_outcome.py <outcomes.json>

Companion to mark_applied.py. That script answers "did he apply?"; this one
answers "what happened?" -- rejection, interview, offer. Until 2026-07-28 the
pipeline had no way to record the latter at all, so `outcome` was empty on
every row and the company-cap logic had to fall back on an age-out heuristic
to guess whether a silent application was dead.

Input schema:

{
  "outcomes": [
    {
      "company": "Harvey",
      "title": "User Operations Manager",     # optional substring match
      "url": "https://...",                   # optional, matched first
      "stage": "rejected",                    # optional, defaults per outcome
      "outcome": "rejected",
      "outcome_date": "2026-07-15",           # optional
      "notes": "role filled",                 # optional, appended to notes
      "source_channel": "pipeline",           # optional, only used on append
      "furthest_stage": "interview",          # optional; the furthest point the
                                              # role is KNOWN to have reached,
                                              # for an outcome that does not say
                                              # so itself (see below)
      "title_exact": false,                   # optional; require an exact
                                              # title match instead of a
                                              # substring, for when one req's
                                              # title is a prefix of another's
      "append_if_missing": true,              # optional, default false
      "sender": "Acme Talent <no-reply@acme.example>"
                                              # the From address, when the
                                              # outcome came from an email
    }
  ]
}

Matching: URL first (exact, normalized), then company + optional title
substring, across ALL rows regardless of stage -- an outcome can land on a row
that was never promoted to applied. A company/title pair matching more than one
row is SKIPPED and reported, never guessed.

`append_if_missing` exists for applications the tracker never saw: roles applied
to before the pipeline covered them, or found through channels it cannot poll.
Appended rows carry stage/outcome from the input and a note recording that they
came from a confirmation backfill rather than a pipeline run.

`furthest_stage` (added 2026-11-12; CLAUDE.md "Tracking files", DECISIONS.md
D7). `outcome` holds one terminal state, so a rejection that follows an
interview leaves the row reading only `rejected`. The `furthest_stage` column
is what keeps the interview, and until this date nothing in this script wrote
it: the rule said to set it alongside every run that records an interview, so
it was filled in outside this script or not at all. Now:

  - an outcome of assessment, interview, onsite, or offer is itself a stage
    the role reached, and moves the row's furthest_stage to it;
  - an item may name the stage outright, which is how a rejection that
    followed an interview is recorded: outcome "rejected", furthest_stage
    "interview";
  - the column only moves right (the order is repair_outcomes.FURTHEST_STAGES).
    A value at or left of what the row holds changes nothing, the column is
    never cleared, and a rejection or closure that names no stage never sets
    it: empty means NOT RECORDED, not "never interviewed";
  - a value outside that vocabulary is refused. The item is printed under
    REFUSED and nothing is written for it (no outcome, stage, or notes
    either), and the script exits 1 after doing the rest of its work.

An item that names a stage still needs its `outcome`. This script writes
whatever outcome the item carries, an empty one included, so to add a stage to
a row whose outcome is already right, restate that outcome.

The three sections this adds to the output (moved right, NOT RECORDED, REFUSED)
print only when they have something in them, so a run that touches no
furthest_stage prints exactly what it always printed.

`sender` (added 2026-11-19, DECISIONS.md D60). Step 0.5 writes the From address
of every outcome email, and sender_check.py decides whether that sender may move
a row: an ATS domain, LinkedIn's application sender, Indeed, or the matched
row's own job-URL domain. Any other sender writes nothing for that item (no
outcome, stage, notes, or appended row), is listed under UNTRUSTED SENDER, and
goes in the brief's alerts. An appended row has no tracker URL to vouch for the
sender, so only the first three count there. Items without a sender (outcomes
he records by hand, the interview loop) are not checked.
"""
import csv
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from repair_outcomes import FURTHEST_STAGES  # noqa: E402
import sender_check  # noqa: E402

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTCOMES = os.path.join(SCRIPT_DIR, "outcomes.csv")
# Same rule as mark_applied.py (2026-11-07): a LinkedIn job link of any shape
# reduces to its job id, so a link out of a LinkedIn notice matches the row.
LINKEDIN_JOB_RE = re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(?:[^/?#]*-)?(\d+)(?=[/?#]|$)", re.I)

# Terminal outcomes imply the application is closed; interview implies it is
# still live. Used only to default `stage` when the caller omits it.
STAGE_DEFAULTS = {
    "rejected": "rejected",
    "closed": "closed",
    "offer": "offer",
    "interview": "interview",
    "pending": "applied",
}

# furthest_stage. The vocabulary and its order live in repair_outcomes.py and
# nowhere else. "" (not recorded) ranks lowest, so any stage is a move right
# from an empty cell.
STAGE_RANK = {s: i for i, s in enumerate(FURTHEST_STAGES)}
# An outcome to the right of `applied` in that list is itself a stage the role
# reached. rejected, closed, and pending are not stages and never move the
# column.
OUTCOME_STAGES = FURTHEST_STAGES[FURTHEST_STAGES.index("applied") + 1:]


def wanted_furthest(entry, outcome):
    """The furthest_stage one input item asks its row to hold: (stage, error).

    It is the further right of the item's own `furthest_stage` and its outcome,
    when the outcome is a stage. "" means the item says nothing about it. An
    explicit value outside the vocabulary comes back as an error, and the
    caller writes nothing at all for that item.
    """
    given = entry.get("furthest_stage")
    if given is None:
        given = ""
    if not isinstance(given, str) or given.strip().lower() not in STAGE_RANK:
        return "", (f"furthest_stage {given!r} is not one of: "
                    f"{', '.join(s for s in FURTHEST_STAGES if s)}")
    given = given.strip().lower()
    reached = outcome.lower() if outcome.lower() in OUTCOME_STAGES else ""
    return max(given, reached, key=STAGE_RANK.get), None


def norm_url(u):
    m = LINKEDIN_JOB_RE.search(u or "")
    if m:
        return f"https://www.linkedin.com/jobs/view/{m.group(1)}"
    return (u or "").rstrip("/").lower()


def merge_notes(existing, addition):
    existing, addition = (existing or "").strip(), (addition or "").strip()
    if not addition:
        return existing
    if not existing:
        return addition
    if addition in existing:
        return existing
    return f"{existing}; {addition}"


def main():
    if len(sys.argv) != 2:
        print("usage: mark_outcome.py <outcomes.json>", file=sys.stderr)
        return 2
    with open(sys.argv[1], encoding="utf-8") as f:
        entries = json.load(f).get("outcomes", [])
    if not entries:
        print("no outcomes in input file")
        return 0

    with open(OUTCOMES, newline="", encoding="utf-8") as f:
        raw = list(csv.reader(f))
    header, rows = raw[0], raw[1:]
    try:
        ci = {n: header.index(n) for n in
              ("applied_date", "company", "title", "url", "stage", "outcome",
               "notes", "source_channel")}
    except ValueError:
        print("outcomes.csv is not on the current schema; run "
              "repair_outcomes.py --apply first", file=sys.stderr)
        return 2

    def well_formed(r):
        return len(r) == len(header)

    # A file on a schema older than 2026-08-27 has no furthest_stage column.
    # Everything else here still works on it, so that is not an error: the
    # stage is reported as not recorded instead.
    fi = header.index("furthest_stage") if "furthest_stage" in header else None

    updated, appended, ambiguous, missing = [], [], [], []
    moved, unrecorded, refused = [], [], []
    untrusted = []

    def advance(r, want):
        """Move one row's furthest_stage right to `want`: never left, never cleared."""
        if not want:
            return
        c, t = r[ci["company"]], r[ci["title"]]
        if fi is None:
            unrecorded.append((c, t, want, "outcomes.csv has no furthest_stage column; "
                                           "run repair_outcomes.py --apply first"))
            return
        have = r[fi].strip().lower()
        if have not in STAGE_RANK:
            # It cannot be ranked, so there is no telling whether `want` is a
            # move right. Leave the cell for a person to look at.
            unrecorded.append((c, t, want, f"the row holds {r[fi]!r}, which is not in the "
                                           f"vocabulary; left as it is"))
            return
        if STAGE_RANK[want] > STAGE_RANK[have]:
            r[fi] = want
            moved.append((c, t, have, want))

    for e in entries:
        company = (e.get("company") or "").strip()
        title = (e.get("title") or "").strip()
        url = norm_url(e.get("url"))
        outcome = (e.get("outcome") or "").strip()
        stage = (e.get("stage") or STAGE_DEFAULTS.get(outcome, "")).strip()

        # Checked before the row is looked for, so a refused item writes
        # nothing: no outcome, no notes, no appended row.
        furthest, problem = wanted_furthest(e, outcome)
        if problem:
            refused.append((company, title, problem))
            continue

        candidates = [r for r in rows if well_formed(r)]
        matches = []
        if url:
            matches = [r for r in candidates if norm_url(r[ci["url"]]) == url]
        if not matches and company:
            matches = [r for r in candidates
                       if r[ci["company"]].strip().lower() == company.lower()]
            # A supplied title is a REQUIREMENT, not a tie-breaker. Filtering
            # only when several rows matched would let a company with exactly
            # one row absorb an outcome meant for a different req there --
            # which is how an Arize "AI Product Manager" rejection landed on
            # their "AI Solutions Manager, SMB" row on the first backfill run.
            if title:
                if e.get("title_exact"):
                    matches = [r for r in matches
                               if r[ci["title"]].strip().lower() == title.lower()]
                else:
                    matches = [r for r in matches
                               if title.lower() in r[ci["title"]].lower()]

        if "sender" in e:
            row_url = matches[0][ci["url"]] if len(matches) == 1 else ""
            ok, why = sender_check.check(e.get("sender"), row_url)
            if not ok:
                untrusted.append((company, title, why))
                continue

        if len(matches) == 1:
            r = matches[0]
            r[ci["outcome"]] = outcome
            if stage:
                r[ci["stage"]] = stage
            if e.get("outcome_date"):
                r[ci["notes"]] = merge_notes(
                    r[ci["notes"]], f"outcome {e['outcome_date']}")
            r[ci["notes"]] = merge_notes(r[ci["notes"]], e.get("notes"))
            if e.get("source_channel"):
                r[ci["source_channel"]] = e["source_channel"]
            advance(r, furthest)
            updated.append((r[ci["company"]], r[ci["title"]], outcome))
        elif len(matches) > 1:
            ambiguous.append((company, title, len(matches)))
        elif e.get("append_if_missing"):
            new = [""] * len(header)
            new[ci["applied_date"]] = e.get("applied_date", "")
            new[ci["company"]] = company
            new[ci["title"]] = title
            new[ci["url"]] = e.get("url", "")
            new[ci["stage"]] = stage or "applied"
            new[ci["outcome"]] = outcome
            new[ci["notes"]] = merge_notes(
                e.get("notes"), "added by confirmation backfill")
            new[ci["source_channel"]] = e.get("source_channel", "pipeline")
            advance(new, furthest)
            rows.append(new)
            appended.append((company, title, outcome))
        else:
            missing.append((company, title))

    if updated or appended:
        shutil.copy2(OUTCOMES, OUTCOMES + ".bak")
        tmp = OUTCOMES + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
        os.replace(tmp, OUTCOMES)

    print(f"updated {len(updated)} existing rows")
    for c, t, o in updated:
        print(f"  {c} / {t} -> {o}")
    print(f"appended {len(appended)} new rows")
    for c, t, o in appended:
        print(f"  {c} / {t} -> {o}")
    if ambiguous:
        print(f"AMBIGUOUS, skipped ({len(ambiguous)}):")
        for c, t, n in ambiguous:
            print(f"  {c} / {t or '(no title given)'} matched {n} rows")
    if missing:
        print(f"NO MATCH and append_if_missing not set ({len(missing)}):")
        for c, t in missing:
            print(f"  {c} / {t}")
    if untrusted:
        print(f"UNTRUSTED SENDER, nothing recorded; put each in the brief's alerts ({len(untrusted)}):")
        for c, t, why in untrusted:
            print(f"  {c} / {t or '(no title given)'}: {why}")
    if moved:
        print(f"furthest_stage moved right on {len(moved)} rows")
        for c, t, was, now in moved:
            print(f"  {c} / {t}: {was or '(not recorded)'} -> {now}")
    if unrecorded:
        print(f"FURTHEST_STAGE NOT RECORDED ({len(unrecorded)}):")
        for c, t, want, why in unrecorded:
            print(f"  {c} / {t}: wanted {want}; {why}")
    if refused:
        print(f"REFUSED, nothing written for these ({len(refused)}):")
        for c, t, why in refused:
            print(f"  {c} / {t or '(no title given)'}: {why}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
