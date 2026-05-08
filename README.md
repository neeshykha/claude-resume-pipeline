# Claude Resume Pipeline

An AI-powered resume tailoring and job discovery system built on [Claude Code](https://claude.ai/code). The core insight: modern ATS platforms and AI screeners don't just keyword-match — they do semantic scoring, recency weighting, and title-similarity ranking. This pipeline encodes that logic explicitly so every application is optimized before it's submitted.

---

## How It Works

The system has two layers:

**`CLAUDE.md` — the instruction layer**
The brain of the pipeline. A 300-line instruction set that tells Claude Code exactly how to analyze a job description, extract the top 15 ATS-critical phrases, tailor resume content to maximize keyword coverage, apply the 6-second recruiter scan rule, bridge title gaps in the summary, and generate a cover letter in a specific voice. Claude Code reads this file at the start of every session and executes it.

**`pipeline/` — the automation layer**
Python scripts that handle the mechanical parts: polling 50+ company ATS boards (Greenhouse, Ashby, Lever), scoring jobs against a candidate profile, deduplicating against seen jobs, and rendering polished PDFs from JSON data files. Claude Code calls these scripts as tools during a session.

A typical run looks like this:

```
Claude reads CLAUDE.md
→ Runs poll_ats.py to fetch new jobs from 50+ company boards
→ Scores and ranks jobs using scorer.py
→ Fetches full JDs for top matches
→ Tailors resume + cover letter for each (following CLAUDE.md logic)
→ Writes JSON data files → renders PDFs via render_pdf.py
→ Sends email digest with apply links and file paths
```

---

## What's in CLAUDE.md

The instruction set encodes real ATS/AI screening research:

- **Keyword extraction**: pull the top 15 exact phrases from a JD — AI screeners do literal and semantic matching, so "cross-functional collaboration" ≠ "worked across teams"
- **Coverage verification**: count how many top-15 phrases appear verbatim in the tailored resume; target ≥80%
- **Title bridge rule**: AI screeners compute title similarity against the summary section heavily — if the target title differs from the current title, the summary's first sentence must frame the connection explicitly
- **First-bullet rule**: human recruiters spend ~6 seconds on initial scan; the first bullet of the most recent role must be the single most metrics-dense achievement relevant to *this* JD
- **Tiered tailoring**: score 110+ → full tailoring with bullet reorder; 88–109 → summary rewrite + cover letter; 78–87 → summary swap only; <78 → skip
- **Voice rules**: cover letters follow a specific set of constraints built up over many iterations (no "genuinely excited", no company-observation openers, specific close requirements)

---

## Repo Structure

```
CLAUDE.md                    # The instruction layer — start here
generate_pdf.py              # Legacy standalone PDF generator (reference)
pipeline/
  config.py                  # Search parameters: titles, locations, salary floor
  models.py                  # Job data model
  scorer.py                  # Keyword + title + location composite scoring
  poll_ats.py                # Polls Greenhouse/Ashby/Lever boards for 50+ companies
  orchestrator.py            # Coordinates a full pipeline run
  render_pdf.py              # PDF renderer — takes JSON data files, outputs PDFs
  pdf_helpers.py             # ReportLab helpers and schema documentation
  scrapers/                  # Per-source scrapers (Wellfound, YC, Builtin, etc.)
  watchlist_companies.json   # Target companies with ATS slugs + scoring config
  daily_task_prompt.md       # Prompt template for scheduled daily runs
```

Not in this repo (gitignored): the master resume, tailored outputs, job tracking data, and pipeline logs — those stay local.

---

## Setup

```bash
# Clone and set up environment
git clone https://github.com/neeshykha/claude-resume-pipeline
cd claude-resume-pipeline
python -m venv .venv
source .venv/bin/activate
pip install reportlab requests

# Configure
# Edit pipeline/config.py — set DIGEST_RECIPIENT and adjust search parameters

# Add your master resume
# Create master_resume.md in the project root (gitignored)
```

Then open the project in Claude Code. From there, paste any job description and the tailoring workflow runs automatically per `CLAUDE.md`.

---

## Using the PDF Pipeline

The renderer takes a JSON data file and outputs a formatted PDF — no per-resume Python scripting needed:

```bash
source .venv/bin/activate

# Resume
python pipeline/render_pdf.py resume data/resume_data.json output/resume.pdf

# Cover letter
python pipeline/render_pdf.py cover data/cover_data.json output/cover.pdf
```

See `pipeline/pdf_helpers.py` for the full JSON schema.

---

## ATS Polling

`poll_ats.py` polls all watchlist companies in parallel, filters by title/location/salary, deduplicates against previously seen jobs, and outputs a structured JSON file. Running this once replaces 50+ individual API calls that would otherwise consume context window:

```bash
source .venv/bin/activate
python pipeline/poll_ats.py
# → pipeline/jobs/ats_hits_YYYY-MM-DD.json
```

Companies and their ATS slugs are defined in `pipeline/watchlist_companies.json`. To add a company, find their Greenhouse/Ashby/Lever slug and add an entry.

---

## Tech Stack

- **Claude Code** — orchestration and tailoring intelligence
- **Python / ReportLab** — PDF generation
- **Greenhouse / Ashby / Lever APIs** — job discovery
- **Gmail MCP** — digest delivery (optional)
