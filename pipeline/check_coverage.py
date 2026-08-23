"""JD keyword coverage check for tailored resumes.

Replaces inline bash-array coverage checks, which use shell syntax the Claude Code
permission engine cannot statically analyze (and therefore always prompts on).
This script is a single, allow-listable command.

Usage:
    .venv/bin/python pipeline/check_coverage.py <resume_file> <phrases_json>

    <resume_file>   path to the tailored resume (.md)
    <phrases_json>  path to a JSON file containing a list of the JD's top phrases,
                    e.g. ["own the deployment lifecycle", "conversational ai agent", ...]

Prints a ✓/✗ line per phrase (case-insensitive literal substring match) and a
final "Coverage: N/M (P%)" summary line. Exit code is 0 always — coverage is
reported, not enforced, so the caller decides whether to revise.
"""
import json
import sys


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: check_coverage.py <resume_file> <phrases_json>", file=sys.stderr)
        return 2

    resume_path, phrases_path = sys.argv[1], sys.argv[2]

    with open(resume_path, encoding="utf-8") as f:
        haystack = f.read().lower()

    with open(phrases_path, encoding="utf-8") as f:
        phrases = json.load(f)

    if not isinstance(phrases, list):
        print("phrases_json must contain a JSON list of strings", file=sys.stderr)
        return 2

    hits = 0
    for phrase in phrases:
        present = str(phrase).lower() in haystack
        mark = "✓" if present else "✗"
        print(f"{mark} {phrase}")
        if present:
            hits += 1

    total = len(phrases)
    pct = round(100 * hits / total) if total else 0
    print(f"Coverage: {hits}/{total} ({pct}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
