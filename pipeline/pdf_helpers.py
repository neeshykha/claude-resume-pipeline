"""
Shared PDF generation helpers for resume and cover letter tailoring.

Usage:
    from pipeline.pdf_helpers import build_resume_pdf, build_cover_pdf

    build_resume_pdf(resume_data, "/path/to/output.pdf")
    build_cover_pdf(cover_data, "/path/to/output.pdf")

--- Resume data schema ---
{
    "summary": "paragraph text",
    "experience": [
        {
            "title": "Job Title",
            "company": "Company Name  |  Date Range",
            "bullets": ["bullet 1", "bullet 2", ...]
        },
        ...
    ],
    "education": {
        "degree": "Bachelor of Arts in Economics",
        "school": "University of North Carolina at Chapel Hill  |  2014"
    },
    "skills": [
        "<b>Category:</b> item1, item2",
        ...
    ],
    "community": [
        "bullet text (no leading bullet char needed)",
        ...
    ]
}

--- Cover letter data schema ---
{
    "date": "March 28, 2026",
    "recipient": "Hiring Team<br/>Company Name",
    "paragraphs": [
        "paragraph 1 text (HTML ok, e.g. <b>bold</b>)",
        ...
    ],
    "closing": "Warmly,",   # optional, defaults to "Best,"
    "name": "Aneesh Khan"   # optional, defaults to ANEESH KHAN
}
"""

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER

ACCENT       = "#0e7c6b"
ACCENT_LIGHT = "#12a08a"
DARK         = "#1a1a1a"
MEDIUM       = "#4a4a4a"

CONTACT_LINE = (
    'Atlanta, GA | Remote &nbsp;&bull;&nbsp; 770-402-8907 &nbsp;&bull;&nbsp; '
    'khan.aneesh10@gmail.com &nbsp;&bull;&nbsp; '
    '<a href="https://www.linkedin.com/in/aneesh-khan-1820b6b5/" color="{accent}">LinkedIn</a>'
)

def _resume_styles():
    base = getSampleStyleSheet()
    return {
        "name": ParagraphStyle(
            "Name", parent=base["Title"], fontSize=22, spaceAfter=2,
            textColor=HexColor(ACCENT), leading=26, fontName="Helvetica-Bold"
        ),
        "contact": ParagraphStyle(
            "Contact", parent=base["Normal"], fontSize=9, alignment=TA_CENTER,
            spaceAfter=6, textColor=HexColor(MEDIUM), leading=12
        ),
        "section": ParagraphStyle(
            "Section", parent=base["Heading2"], fontSize=11, spaceAfter=4, spaceBefore=10,
            textColor=HexColor(ACCENT), borderWidth=0, leading=14, fontName="Helvetica-Bold"
        ),
        "job_title": ParagraphStyle(
            "JobTitle", parent=base["Normal"], fontSize=10, spaceAfter=1, spaceBefore=6,
            textColor=HexColor(ACCENT_LIGHT), leading=13, fontName="Helvetica-Bold"
        ),
        "company": ParagraphStyle(
            "Company", parent=base["Normal"], fontSize=9.5, spaceAfter=3,
            textColor=HexColor(MEDIUM), leading=12, fontName="Helvetica-Oblique"
        ),
        "bullet": ParagraphStyle(
            "Bullet", parent=base["Normal"], fontSize=9, leftIndent=14, firstLineIndent=-14,
            spaceAfter=2, leading=12, textColor=HexColor(DARK)
        ),
        "body": ParagraphStyle(
            "Body", parent=base["Normal"], fontSize=9, spaceAfter=2,
            leading=12, textColor=HexColor(DARK)
        ),
    }


def _cover_styles():
    base = getSampleStyleSheet()
    return {
        "name": ParagraphStyle(
            "Name", parent=base["Title"], fontSize=20, spaceAfter=2,
            textColor=HexColor(ACCENT), leading=24, fontName="Helvetica-Bold"
        ),
        "contact": ParagraphStyle(
            "Contact", parent=base["Normal"], fontSize=9, alignment=TA_CENTER,
            spaceAfter=4, textColor=HexColor(MEDIUM), leading=12
        ),
        "body": ParagraphStyle(
            "Body", parent=base["Normal"], fontSize=10, spaceAfter=10,
            leading=15, textColor=HexColor(DARK)
        ),
        "sig": ParagraphStyle(
            "Sig", parent=base["Normal"], fontSize=10, spaceAfter=4,
            leading=14, textColor=HexColor(DARK), fontName="Helvetica-Bold"
        ),
    }


def _hr_thick(story):
    story.append(HRFlowable(width="100%", thickness=1.5, color=HexColor(ACCENT), spaceAfter=6))


def _hr_thin(story):
    story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor(ACCENT), spaceAfter=2, spaceBefore=6))


def build_resume_pdf(data: dict, output_path: str) -> None:
    """Generate a tailored resume PDF from structured data."""
    s = _resume_styles()

    doc = SimpleDocTemplate(
        output_path, pagesize=letter,
        topMargin=0.5*inch, bottomMargin=0.5*inch,
        leftMargin=0.65*inch, rightMargin=0.65*inch,
    )

    story = []

    # Header
    story.append(Paragraph("ANEESH KHAN", s["name"]))
    story.append(Paragraph(CONTACT_LINE.format(accent=ACCENT), s["contact"]))
    _hr_thick(story)

    # Summary
    story.append(Paragraph("PROFESSIONAL SUMMARY", s["section"]))
    story.append(Paragraph(data["summary"], s["body"]))
    _hr_thin(story)

    # Core Competencies (optional — pipe-separated string)
    if data.get("core_competencies"):
        story.append(Paragraph("CORE COMPETENCIES", s["section"]))
        story.append(Paragraph(data["core_competencies"], s["body"]))
        _hr_thin(story)

    # Experience
    story.append(Paragraph("PROFESSIONAL EXPERIENCE", s["section"]))
    for job in data["experience"]:
        story.append(Paragraph(f"<b>{job['title']}</b>", s["job_title"]))
        story.append(Paragraph(job["company"], s["company"]))
        for b in job["bullets"]:
            story.append(Paragraph(f"•&nbsp;&nbsp;{b}", s["bullet"]))

    _hr_thin(story)

    # Education
    story.append(Paragraph("EDUCATION", s["section"]))
    story.append(Paragraph(f"<b>{data['education']['degree']}</b>", s["body"]))
    story.append(Paragraph(data["education"]["school"], s["body"]))
    _hr_thin(story)

    # Skills
    story.append(Paragraph("TECHNICAL SKILLS", s["section"]))
    for skill_line in data["skills"]:
        story.append(Paragraph(skill_line, s["body"]))

    # Community (optional — omit by default per master_resume.md)
    if "community" in data:
        _hr_thin(story)
        story.append(Paragraph("COMMUNITY", s["section"]))
        for item in data["community"]:
            story.append(Paragraph(f"•&nbsp;&nbsp;{item}", s["bullet"]))

    doc.build(story)
    print(f"PDF generated: {output_path}")


def _plain(text: str) -> str:
    """Strip inline markup and normalize characters that break ATS parsers.

    Entities and tags first, then the character substitutions: en/em dashes and
    curly quotes are the ones that most often come back as mojibake or as a
    token glued to its neighbour in a parsed field.
    """
    import html as _html
    import re as _re
    t = _re.sub(r"<br\s*/?>", " ", text or "")
    t = _re.sub(r"<[^>]+>", "", t)
    t = _html.unescape(t)
    for bad, good in (("–", "-"), ("—", "-"), ("’", "'"),
                      ("‘", "'"), ("“", '"'), ("”", '"'),
                      ("•", "-"), (" ", " ")):
        t = t.replace(bad, good)
    return _re.sub(r"\s{2,}", " ", t).strip()


def _ats_styles():
    """One font, one colour, one column. Every deviation from that is a place a
    parser can guess wrong, and none of them win an interview."""
    base = getSampleStyleSheet()
    black = HexColor("#000000")
    return {
        "name": ParagraphStyle("AtsName", parent=base["Normal"], fontSize=14,
                               spaceAfter=2, leading=17, textColor=black,
                               fontName="Helvetica-Bold"),
        "contact": ParagraphStyle("AtsContact", parent=base["Normal"], fontSize=10,
                                  spaceAfter=1, leading=13, textColor=black),
        "section": ParagraphStyle("AtsSection", parent=base["Normal"], fontSize=11,
                                  spaceBefore=12, spaceAfter=4, leading=14,
                                  textColor=black, fontName="Helvetica-Bold"),
        "job_title": ParagraphStyle("AtsJobTitle", parent=base["Normal"], fontSize=10,
                                    spaceBefore=8, spaceAfter=1, leading=13,
                                    textColor=black, fontName="Helvetica-Bold"),
        "company": ParagraphStyle("AtsCompany", parent=base["Normal"], fontSize=10,
                                  spaceAfter=3, leading=13, textColor=black),
        "bullet": ParagraphStyle("AtsBullet", parent=base["Normal"], fontSize=10,
                                 leftIndent=12, spaceAfter=3, leading=13,
                                 textColor=black),
        "body": ParagraphStyle("AtsBody", parent=base["Normal"], fontSize=10,
                               spaceAfter=4, leading=13, textColor=black),
    }


def build_ats_resume_pdf(data: dict, output_path: str) -> None:
    """Render the SAME resume data in a deliberately parser-friendly layout.

    Built 2026-08-28. Workday and Paylocity both make you retype your entire
    work history after uploading a resume, and the working theory is that the
    styled template is part of why their parse is bad enough to be useless. This
    is the control: identical content, stripped of everything an ATS parser is
    known to mishandle, so the two can be compared through a real autofill.

    What is deliberately removed relative to build_resume_pdf, and why each one
    is a real hazard rather than a superstition:

    - Centered contact line with bullet separators and an inline <a> hyperlink.
      Becomes left-aligned plain lines, one field per line. The bullet glyph
      fuses tokens ("Atlanta, GA | Remote * 770-402-8907") and a hyperlink is a
      separate text run, which is how phone numbers and emails go missing.
    - Horizontal rules. Vector flowables that can read as column or table edges.
    - Colour. Every heading and body run is pure black.
    - Italics for the company line. Style changes mid-block can split runs.
    - Hanging indents (firstLineIndent=-14). Text positioned left of its own
      block is a classic source of out-of-order extraction.
    - "*" bullets with non-breaking spaces. U+2022 followed by U+00A0 does not
      split on whitespace in many parsers, so the marker glues to the first
      word. Replaced with "- " and a real space.
    - En dashes and curly quotes throughout (see _plain).

    What is deliberately KEPT: exact section headings ATS look for
    (PROFESSIONAL SUMMARY / PROFESSIONAL EXPERIENCE / EDUCATION / SKILLS), one
    column, one font, and title-then-company-then-dates ordering.

    Note SKILLS rather than TECHNICAL SKILLS: the plain heading is the one in
    every ATS keyword list, and the styled template's "TECHNICAL SKILLS" is a
    small unnecessary risk. Category labels inside skill lines survive as plain
    "Category: value" text.
    """
    s = _ats_styles()
    doc = SimpleDocTemplate(
        output_path, pagesize=letter,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
    )
    story = []

    story.append(Paragraph("Aneesh Khan", s["name"]))
    for line in ("Atlanta, GA", "770-402-8907", "khan.aneesh10@gmail.com",
                 "linkedin.com/in/aneesh-khan-1820b6b5"):
        story.append(Paragraph(line, s["contact"]))

    story.append(Paragraph("PROFESSIONAL SUMMARY", s["section"]))
    story.append(Paragraph(_plain(data["summary"]), s["body"]))

    if data.get("core_competencies"):
        story.append(Paragraph("CORE COMPETENCIES", s["section"]))
        story.append(Paragraph(_plain(data["core_competencies"]), s["body"]))

    story.append(Paragraph("PROFESSIONAL EXPERIENCE", s["section"]))
    for job in data["experience"]:
        story.append(Paragraph(_plain(job["title"]), s["job_title"]))
        story.append(Paragraph(_plain(job["company"]), s["company"]))
        for b in job["bullets"]:
            story.append(Paragraph("- " + _plain(b), s["bullet"]))

    story.append(Paragraph("EDUCATION", s["section"]))
    story.append(Paragraph(_plain(data["education"]["degree"]), s["body"]))
    story.append(Paragraph(_plain(data["education"]["school"]), s["body"]))

    story.append(Paragraph("SKILLS", s["section"]))
    for skill_line in data["skills"]:
        story.append(Paragraph(_plain(skill_line), s["body"]))

    if "community" in data:
        story.append(Paragraph("COMMUNITY", s["section"]))
        for item in data["community"]:
            story.append(Paragraph("- " + _plain(item), s["bullet"]))

    doc.build(story)
    print(f"ATS-formatted PDF generated: {output_path}")


def build_cover_pdf(data: dict, output_path: str) -> None:
    """Generate a tailored cover letter PDF from structured data."""
    s = _cover_styles()

    doc = SimpleDocTemplate(
        output_path, pagesize=letter,
        topMargin=0.75*inch, bottomMargin=0.75*inch,
        leftMargin=1.0*inch, rightMargin=1.0*inch,
    )

    story = []

    # Header
    story.append(Paragraph("ANEESH KHAN", s["name"]))
    story.append(Paragraph(CONTACT_LINE.format(accent=ACCENT), s["contact"]))
    _hr_thick(story)

    # Date + recipient
    story.append(Paragraph(data["date"], s["body"]))
    story.append(Spacer(1, 0.05 * inch))
    story.append(Paragraph(data["recipient"], s["body"]))
    story.append(Spacer(1, 0.1 * inch))

    # Body paragraphs
    for para in data["paragraphs"]:
        story.append(Paragraph(para, s["body"]))

    # Sign-off
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph(data.get("closing", "Best,"), s["body"]))
    story.append(Paragraph(data.get("name", "Aneesh Khan"), s["sig"]))

    doc.build(story)
    print(f"PDF generated: {output_path}")
