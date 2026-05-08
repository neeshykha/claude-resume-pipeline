#!/usr/bin/env python3
"""
PDF Renderer CLI — converts JSON data files into resume/cover letter PDFs.

Replaces the per-tailoring pattern of copying generate_pdf.py and rewriting
it with content. Claude now writes a small JSON data file, and this script
renders it using the shared pdf_helpers templates.

Usage:
    python pipeline/render_pdf.py resume  path/to/resume_data.json  path/to/output.pdf
    python pipeline/render_pdf.py cover   path/to/cover_data.json   path/to/output.pdf
    python pipeline/render_pdf.py both    path/to/resume.json path/to/cover.json  output_dir/

For 'both' mode, output filenames are derived from the JSON filenames.

--- Resume JSON schema ---
{
    "summary": "paragraph text",
    "core_competencies": "optional — pipe-separated skill tags for CORE COMPETENCIES section",
    "experience": [
        {
            "title": "Job Title",
            "company": "<b>Company Name</b>  |  Date Range",
            "bullets": ["bullet 1", "bullet 2"]
        }
    ],
    "education": {
        "degree": "Bachelor of Arts in Economics",
        "school": "University of North Carolina at Chapel Hill  |  2014"
    },
    "skills": [
        "<b>Category:</b> item1, item2"
    ]
}

--- Cover letter JSON schema ---
{
    "date": "May 1, 2026",
    "recipient": "Hiring Team<br/>Company Name",
    "paragraphs": [
        "paragraph 1 text (HTML ok)"
    ],
    "closing": "Warmly,"
}
"""

import argparse
import json
import os
import sys

# Add project root to path so we can import pipeline.pdf_helpers
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from pipeline.pdf_helpers import build_resume_pdf, build_cover_pdf


def render_resume(data_path: str, output_path: str) -> None:
    """Render a resume PDF from a JSON data file."""
    with open(data_path) as f:
        data = json.load(f)

    # Validate required fields
    required = ["summary", "experience", "education", "skills"]
    missing = [k for k in required if k not in data]
    if missing:
        print(f"ERROR: Missing required fields in {data_path}: {missing}", file=sys.stderr)
        sys.exit(1)

    build_resume_pdf(data, output_path)


def render_cover(data_path: str, output_path: str) -> None:
    """Render a cover letter PDF from a JSON data file."""
    with open(data_path) as f:
        data = json.load(f)

    # Validate required fields
    required = ["date", "recipient", "paragraphs"]
    missing = [k for k in required if k not in data]
    if missing:
        print(f"ERROR: Missing required fields in {data_path}: {missing}", file=sys.stderr)
        sys.exit(1)

    build_cover_pdf(data, output_path)


def main():
    parser = argparse.ArgumentParser(description="Render resume/cover PDFs from JSON data")
    parser.add_argument("type", choices=["resume", "cover", "both"],
                        help="Type of PDF to render")
    parser.add_argument("inputs", nargs="+",
                        help="JSON data file(s). For 'both': resume.json cover.json output_dir/")

    args = parser.parse_args()

    if args.type == "resume":
        if len(args.inputs) != 2:
            print("Usage: render_pdf.py resume <data.json> <output.pdf>", file=sys.stderr)
            sys.exit(1)
        render_resume(args.inputs[0], args.inputs[1])

    elif args.type == "cover":
        if len(args.inputs) != 2:
            print("Usage: render_pdf.py cover <data.json> <output.pdf>", file=sys.stderr)
            sys.exit(1)
        render_cover(args.inputs[0], args.inputs[1])

    elif args.type == "both":
        if len(args.inputs) != 3:
            print("Usage: render_pdf.py both <resume.json> <cover.json> <output_dir/>", file=sys.stderr)
            sys.exit(1)
        resume_json, cover_json, output_dir = args.inputs
        os.makedirs(output_dir, exist_ok=True)

        # Derive output names from input JSON names
        resume_base = os.path.splitext(os.path.basename(resume_json))[0]
        cover_base = os.path.splitext(os.path.basename(cover_json))[0]

        resume_pdf = os.path.join(output_dir, f"{resume_base}.pdf")
        cover_pdf = os.path.join(output_dir, f"{cover_base}.pdf")

        render_resume(resume_json, resume_pdf)
        render_cover(cover_json, cover_pdf)


if __name__ == "__main__":
    main()
