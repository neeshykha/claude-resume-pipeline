from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER

output_path = "/Users/aneesh/Documents/resume_project/Aneesh_Khan_Resume.pdf"

# Color palette — teal accent with warm contrast
ACCENT = "#0e7c6b"       # Deep teal — headers, name, lines
ACCENT_LIGHT = "#12a08a"  # Lighter teal — links, job titles
DARK = "#1a1a1a"          # Near-black — body text
MEDIUM = "#4a4a4a"        # Medium gray — secondary text
WARM = "#c0392b"          # Warm red — subtle accent for bullets
DIVIDER = "#0e7c6b"       # Teal dividers

doc = SimpleDocTemplate(
    output_path,
    pagesize=letter,
    topMargin=0.5 * inch,
    bottomMargin=0.5 * inch,
    leftMargin=0.65 * inch,
    rightMargin=0.65 * inch,
)

styles = getSampleStyleSheet()

# Custom styles
name_style = ParagraphStyle(
    "Name", parent=styles["Title"], fontSize=22, spaceAfter=2, textColor=HexColor(ACCENT), leading=26,
    fontName="Helvetica-Bold"
)
contact_style = ParagraphStyle(
    "Contact", parent=styles["Normal"], fontSize=9, alignment=TA_CENTER, spaceAfter=6,
    textColor=HexColor(MEDIUM), leading=12
)
section_style = ParagraphStyle(
    "Section", parent=styles["Heading2"], fontSize=11, spaceAfter=4, spaceBefore=10,
    textColor=HexColor(ACCENT), borderWidth=0, leading=14, fontName="Helvetica-Bold"
)
job_title_style = ParagraphStyle(
    "JobTitle", parent=styles["Normal"], fontSize=10, spaceAfter=1, spaceBefore=6,
    textColor=HexColor(ACCENT_LIGHT), leading=13, fontName="Helvetica-Bold"
)
company_style = ParagraphStyle(
    "Company", parent=styles["Normal"], fontSize=9.5, spaceAfter=3,
    textColor=HexColor(MEDIUM), leading=12, fontName="Helvetica-Oblique"
)
bullet_style = ParagraphStyle(
    "Bullet", parent=styles["Normal"], fontSize=9, leftIndent=14, firstLineIndent=-14,
    spaceAfter=2, leading=12, textColor=HexColor(DARK)
)
body_style = ParagraphStyle(
    "Body", parent=styles["Normal"], fontSize=9, spaceAfter=2, leading=12, textColor=HexColor(DARK)
)

story = []

# Name
story.append(Paragraph("ANEESH KHAN", name_style))

# Contact
story.append(Paragraph(
    'Atlanta, GA | Remote &nbsp;&bull;&nbsp; 770-402-8907 &nbsp;&bull;&nbsp; khan.aneesh10@gmail.com &nbsp;&bull;&nbsp; '
    f'<a href="https://www.linkedin.com/in/aneesh-khan-1820b6b5/" color="{ACCENT}">LinkedIn</a>',
    contact_style
))

# HR
story.append(HRFlowable(width="100%", thickness=1.5, color=HexColor(ACCENT), spaceAfter=6))

# Summary
story.append(Paragraph("PROFESSIONAL SUMMARY", section_style))
story.append(Paragraph(
    "Technical operations leader with 10+ years of experience bridging support, product, and engineering teams "
    "across IoT, SaaS, and hardware industries. Proven track record of scaling support operations — doubled case "
    "throughput without adding headcount by implementing AI-driven tooling, automated QA systems, and streamlined "
    "workflows. Deep hands-on technical background spanning Salesforce administration, AWS, Linux infrastructure, "
    "and networking. Experienced managing globally distributed teams through high-growth phases and complex "
    "organizational transitions including acquisitions and platform migrations.",
    body_style
))

# HR
story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor(ACCENT), spaceAfter=2, spaceBefore=6))

# Experience
story.append(Paragraph("PROFESSIONAL EXPERIENCE", section_style))

# iApts
story.append(Paragraph("<b>Technical Support Operations Manager</b>", job_title_style))
story.append(Paragraph("<b>iApts Inc.</b> &nbsp;|&nbsp; February 2023 – Present", company_style))
iapts_bullets = [
    "Lead a globally distributed team of 8 agents across the Philippines, Dominican Republic, and Brazil, overseeing hiring, scheduling, performance reviews, and training across time zones",
    "Scaled monthly case volume from 600 to 1,200 (100% increase) without adding headcount, reducing cost per ticket by approximately 50%",
    "Reduced average call handling time by ~50% through targeted one-on-one coaching, workflow simplification, and improved tooling",
    "Built an automated agent auditing system using Google AI Studio and Claude Code that grades 24 calls and samples 40 cases weekly, saving 6+ hours per week over manual QA reviews",
    "Drove end-to-end AI vendor selection: created evaluation checklist for COO, selected Maven AGI, and served as sole integration partner for 2 months — achieving 85% deflection rate and building knowledge articles through feedback loops",
    "Administer Salesforce Service Cloud: built 25+ Flows/automations, maintain 5 dashboards, manage custom objects, approval processes, case assignment rules, omni-channel routing, and email templates",
    "Designed and implemented a Customer Effort Score (CES) survey system in Salesforce, improving scores over a sustained 6-month period",
    "Authored 150+ knowledge articles and SOPs for the operations team",
    "Manage Jira board structure, dashboards, and workflows for the operations team; create and maintain documentation for cross-functional changes",
    "Coordinate across product, engineering, and operations through regular cross-functional meetings (~30% of weekly time) to align priorities and communicate changes",
]
for b in iapts_bullets:
    story.append(Paragraph(f"•&nbsp;&nbsp;{b}", bullet_style))

# First Alert Resideo
story.append(Paragraph("<b>Tier 3 Support Lead</b>", job_title_style))
story.append(Paragraph("<b>First Alert (Resideo)</b> &nbsp;|&nbsp; 2021 – December 2022", company_style))
fa_resideo_bullets = [
    "Managed a team of 12 support agents handling ~1,000 escalations and advanced technical issues per month for consumer safety and IoT products",
    "Led the operational transition from Zendesk to Salesforce, mapping 25+ categories, products, and issue types and migrating chat and phone channels",
    "Trained a team of 24 Resideo support agents over 6 months to fully absorb First Alert's support operations, creating dedicated training materials and recurring quizzes — validated by sustained reduction in escalation rate",
    "Split time between direct escalation handling (~50%) and transition management (~50%), maintaining service quality during organizational change",
]
for b in fa_resideo_bullets:
    story.append(Paragraph(f"•&nbsp;&nbsp;{b}", bullet_style))

# First Alert Newell
story.append(Paragraph("<b>Tier 2 Support Lead</b>", job_title_style))
story.append(Paragraph("<b>First Alert (Newell Brands)</b> &nbsp;|&nbsp; 2017 – 2021", company_style))
fa_newell_bullets = [
    "Led a support team of up to 20 agents (scaled from 12 to 20, optimized to 16) supporting the Onelink smart home ecosystem and legacy Luma mesh Wi-Fi products",
    "Personally handled 2.5x the case volume of the next closest team member due to deep subject matter expertise in IoT networking and regulated hardware",
    "QA-tested 40+ firmware releases on OpenWrt-based mesh networking devices, serving as the go-between for product, engineering, and support teams",
    "Served as the primary liaison between support, product, and engineering — translating customer feedback into firmware improvement priorities for a heavily regulated product (smoke detector/Wi-Fi)",
    "Managed support operations through a product acquisition and corporate integration, maintaining continuity for existing customer base",
]
for b in fa_newell_bullets:
    story.append(Paragraph(f"•&nbsp;&nbsp;{b}", bullet_style))

# Luma
story.append(Paragraph("<b>Tier 2 Support Lead / Tier 2 Support Agent</b>", job_title_style))
story.append(Paragraph("<b>Luma (Startup)</b> &nbsp;|&nbsp; 2015 – 2017 (Acquired by First Alert)", company_style))
luma_bullets = [
    "Joined as the sole support agent pre-launch; personally onboarded ~500 customers from a 2,500-unit pre-order campaign, building a loyal customer base that requested support by name",
    "Scaled the support organization from 1 to 18 agents (6 Tier 2 + 12 BPO), owning all hiring, training, documentation, and knowledge base development",
    "Authored 50+ knowledge base articles and all support documentation and training materials",
    "Managed the full Zendesk instance and led the migration from Zendesk Chat to Intercom Chat",
    "Transitioned through acquisition by First Alert/Newell Brands, ensuring operational continuity",
]
for b in luma_bullets:
    story.append(Paragraph(f"•&nbsp;&nbsp;{b}", bullet_style))

# Georgia Tech
story.append(Paragraph("<b>Junior Systems Engineer</b>", job_title_style))
story.append(Paragraph("<b>Georgia Tech Institute for Information Security &amp; Privacy</b> &nbsp;|&nbsp; 2014 – 2015", company_style))
gt_bullets = [
    "Managed 25+ servers (Linux and Windows) used for penetration testing and security research",
    "Built and configured Debian desktop environments for ~10 PhD students and 8 faculty members",
    "Administered Docker containers, managed networking infrastructure, and provided hands-on technical support for security research lab operations",
]
for b in gt_bullets:
    story.append(Paragraph(f"•&nbsp;&nbsp;{b}", bullet_style))

# HR
story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor(ACCENT), spaceAfter=2, spaceBefore=6))

# Education
story.append(Paragraph("EDUCATION", section_style))
story.append(Paragraph("<b>Bachelor of Arts in Economics</b>", body_style))
story.append(Paragraph("University of North Carolina at Chapel Hill &nbsp;|&nbsp; 2014", body_style))

# HR
story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor(ACCENT), spaceAfter=2, spaceBefore=6))

# Skills
story.append(Paragraph("TECHNICAL SKILLS", section_style))
skills = [
    ("<b>Platforms &amp; Administration:</b> Salesforce Service Cloud (Admin — Flows, Omni-Channel, Custom Objects, Reports/Dashboards, Approval Processes), Jira (Board/Workflow Administration), Zendesk, Intercom"),
    ("<b>Cloud &amp; Infrastructure:</b> AWS (IoT Core), Docker, Debian/Linux, OpenWrt, Server Build &amp; Administration, Networking"),
    ("<b>AI &amp; Automation:</b> Claude Code, Anthropic Claude Agent SDK, Google AI Studio, Maven AGI, AI-driven QA/auditing pipelines, prompt engineering"),
    ("<b>Programming &amp; Scripting:</b> Shell/Bash scripting, command-line tooling"),
    ("<b>Methodologies &amp; Processes:</b> Cross-functional stakeholder management, vendor evaluation &amp; selection, platform migration, BPO management, distributed team leadership"),
    ("<b>Languages:</b> English (native), German (conversational), Hindi (conversational)"),
]
for s in skills:
    story.append(Paragraph(s, body_style))

# HR
story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor(ACCENT), spaceAfter=2, spaceBefore=6))

# Community
story.append(Paragraph("COMMUNITY", section_style))
story.append(Paragraph("•&nbsp;&nbsp;<b>Head of Steering Committee</b>, Community Garden (Atlanta, GA)", bullet_style))
story.append(Paragraph("•&nbsp;&nbsp;Volunteer, Habitat for Humanity and local Atlanta community organizations", bullet_style))

doc.build(story)
print(f"PDF generated: {output_path}")
