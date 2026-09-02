"""JD keyword coverage check for tailored resumes.

Replaces inline bash-array coverage checks, which use shell syntax the Claude Code
permission engine cannot statically analyze (and therefore always prompts on).
This script is a single, allow-listable command.

Usage:
    .venv/bin/python pipeline/check_coverage.py <resume_file> <phrases_json>

    <resume_file>   the tailored resume. Either the render_pdf.py data file
                    (tailored/Aneesh_Khan_[Company]_[Role]_data.json) or a markdown
                    resume (.md). Format is picked by extension.
    <phrases_json>  path to a JSON file containing a list of the JD's top phrases,
                    e.g. ["own the deployment lifecycle", "conversational ai agent", ...]

Prints a ✓/✗ line per phrase (case-insensitive literal substring match) and a
final "Coverage: N/M (P%)" summary line. Exit code is 0 always — coverage is
reported, not enforced, so the caller decides whether to revise.

THE DATA FILE IS THE SOURCE OF TRUTH (2026-09-02 retro). Until then this script read
only tailored/*.md while render_pdf.py read tailored/*_data.json, so every resume was
authored twice and every coverage fix had to be applied twice; on 2026-09-02 the Cresta
tailoring made 4 fixes as 8 edits. Pointing the check at the JSON the PDF is rendered
from means what is measured is what ships. Markdown input is kept for the archive of
older tailored versions, not for new work.

What counts as resume text in the JSON: summary, core_competencies, every experience
title / company line / bullet, education, skills, and community. Markup the renderer
understands (<b>, &amp;, <br/>) is stripped before matching, so a phrase never fails
on a tag.
"""
import html
import json
import re
import sys


def _plain(s) -> str:
    """Strip the small HTML subset the PDF renderer accepts."""
    s = re.sub(r"<[^>]+>", " ", str(s or ""))
    return html.unescape(s)


def resume_text_from_data(data: dict) -> str:
    """Flatten a render_pdf.py resume data file into one searchable string."""
    parts = [data.get("summary", ""), data.get("core_competencies", "")]
    for job in data.get("experience", []) or []:
        parts += [job.get("title", ""), job.get("company", "")]
        parts += list(job.get("bullets", []) or [])
    edu = data.get("education") or {}
    parts += [edu.get("degree", ""), edu.get("school", "")]
    parts += list(data.get("skills", []) or [])
    parts += list(data.get("community", []) or [])
    return "\n".join(_plain(p) for p in parts if p)


def load_resume_text(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    if path.lower().endswith(".json"):
        data = json.loads(raw)
        if not isinstance(data, dict) or "experience" not in data:
            print(f"{path} is not a resume data file (no 'experience' key)", file=sys.stderr)
            sys.exit(2)
        return resume_text_from_data(data)
    return raw


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: check_coverage.py <resume_file(.json|.md)> <phrases_json>", file=sys.stderr)
        return 2

    resume_path, phrases_path = sys.argv[1], sys.argv[2]
    haystack = load_resume_text(resume_path).lower()

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
