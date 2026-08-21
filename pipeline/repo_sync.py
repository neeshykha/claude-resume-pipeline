"""Stage only what THIS run changed, instead of everything in the working tree.

Step 7 used `git add -A`, which commits whatever happens to be dirty — including
edits a human had in progress when the run fired. That is not hypothetical: on
2026-08-21 an unattended run swept an uncommitted change to `audit_scores.py`
into a commit titled "add Applications Manager family to tier2c", where it is
now permanently mislabeled.

A static path allowlist would be the obvious fix and it is the wrong one. Runs
legitimately commit across a wide surface — `watchlist_companies.json`,
`enrollment_candidates.json`, `daily_task_prompt.md`, `harvest_ats.py`,
`README.md`, `CLAUDE.md` — including same-run bug fixes to the pipeline's own
code. Freezing that list would block real work.

So the rule is temporal rather than path-based: **commit what the run changed,
not what it found.** Step 0 records which paths were already dirty; Step 7
stages only paths that became dirty afterward, and reports the rest instead of
silently absorbing them.

Usage:
    .venv/bin/python pipeline/repo_sync.py --snapshot   # Step 0
    .venv/bin/python pipeline/repo_sync.py --stage      # Step 7, replaces git add -A
"""

import argparse
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(BASE)
BASELINE = os.path.join(BASE, "jobs", "repo_baseline.json")


def git(*args):
    return subprocess.run(("git",) + args, cwd=REPO, capture_output=True,
                          text=True, check=True).stdout


def dirty_paths():
    """Every path git reports as changed, from `status --porcelain -z`.

    -z is not optional here: the default format quotes and escapes paths with
    spaces or non-ASCII, which would then not round-trip back into `git add`.
    """
    out = git("status", "--porcelain", "-z", "--untracked-files=all")
    fields = out.split("\0")
    paths, i = set(), 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        paths.add(path)
        # Renames and copies carry the source path as a second NUL-separated
        # field; consume it so it isn't parsed as a status entry.
        if "R" in status or "C" in status:
            if i < len(fields):
                paths.add(fields[i])
                i += 1
    return paths


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--snapshot", action="store_true",
                   help="record paths already dirty before the run (Step 0)")
    g.add_argument("--stage", action="store_true",
                   help="stage only paths that changed during the run (Step 7)")
    args = ap.parse_args()

    current = dirty_paths()

    if args.snapshot:
        os.makedirs(os.path.dirname(BASELINE), exist_ok=True)
        with open(BASELINE, "w") as f:
            json.dump({"dirty": sorted(current)}, f, indent=2)
        print(f"baseline recorded: {len(current)} path(s) already dirty")
        for p in sorted(current):
            print(f"    pre-existing  {p}")
        return 0

    try:
        with open(BASELINE) as f:
            baseline = set(json.load(f)["dirty"])
        have_baseline = True
    except (OSError, ValueError, KeyError):
        baseline, have_baseline = set(), False

    if not have_baseline:
        # Falling back to the old behaviour is still better than staging
        # nothing and silently losing a run's work, but it is exactly the
        # situation this script exists to prevent, so say so loudly.
        print("WARNING: no baseline from Step 0 — cannot tell this run's changes "
              "from pre-existing ones.")
        print("WARNING: staging everything, which is the old `git add -A` behaviour. "
              "Report this in the digest.")

    to_stage = sorted(current - baseline)
    skipped = sorted(current & baseline)

    if not to_stage:
        print("nothing to stage: no paths changed during this run")
    else:
        # -A over an explicit pathspec so deletions and renames stage correctly,
        # while still touching only these paths.
        git("add", "-A", "--", *to_stage)
        print(f"staged {len(to_stage)} path(s) changed by this run:")
        for p in to_stage:
            print(f"    staged   {p}")

    if skipped:
        print(f"\nleft alone — dirty before this run started ({len(skipped)}):")
        for p in skipped:
            print(f"    skipped  {p}")
        print("These are someone else's in-progress edits. Do NOT stage them; "
              "mention them in the digest so they aren't forgotten.")

    if os.path.exists(BASELINE):
        os.remove(BASELINE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
