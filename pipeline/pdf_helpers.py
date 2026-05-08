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
