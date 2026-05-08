# Daily Job Pipeline — Scheduled Task Prompt

You are running the daily job search pipeline for Aneesh Khan. Follow these steps exactly.

**Token optimization notes:** This pipeline is designed to fit in ONE context window.
- ATS polling is handled by `poll_ats.py` (Python, not Claude) — read the small output file
- PDF generation uses `render_pdf.py` — write JSON data, don't write Python scripts
- Read `master_resume.md` ONCE at the start, reuse for all tailoring
- WebSearch is limited to 6-8 high-ROI queries

## Step 0: ATS Polling (pre-built script)

Run the ATS polling script — this replaces 50+ individual WebFetch calls:

```bash
source .venv/bin/activate && python pipeline/poll_ats.py
```

This polls all ~57 watchlist companies, filters by title/location/salary, deduplicates against `seen_jobs.json`, enforces company caps, and outputs `pipeline/jobs/ats_hits_YYYY-MM-DD.json` with:
- Top 25 matched jobs (pre-scored by title/location/priority)
- Up to 20 borderline titles for your semantic review
- Polling stats and errors

Read the output file. It's ~20KB instead of ~5MB of raw API JSON.

## Step 1: Review & Supplement with WebSearch

1. **Read** `pipeline/jobs/ats_hits_YYYY-MM-DD.json`
2. **Review borderline titles** — use your semantic judgment to promote any that are genuinely relevant (e.g., "AI Deployment Architect" or "Field Enablement Manager (Customer Success)" might be worth including even though the title filter didn't catch them exactly)
3. **Run 6-8 targeted WebSearch queries** to catch jobs from companies NOT on the watchlist:
   - `"Technical Account Manager" OR "Customer Success Manager" jobs remote OR Atlanta posted this week`
   - `"Solutions Engineer" OR "Implementation Consultant" AI OR agentic remote posted this week`
   - `site:builtin.com "Technical Account Manager" OR "Customer Success Manager" Atlanta OR remote`
   - `site:jobs.ashbyhq.com CSM OR TAM OR "Solutions Engineer" this week`
   - `site:job-boards.greenhouse.io TAM OR CSM OR "Implementation" this week`
   - `site:jobs.lever.co TAM OR CSM remote this week`
   - (optional) 1-2 Atlanta-specific or AI-specific queries based on what the ATS hits show

**Do NOT re-run** the 17 broad queries from the old prompt. The ATS poller already covers all watchlist companies.

## Step 2: Filter and Score

From the combined ATS hits + WebSearch results, apply the full scoring from CLAUDE.md:
- Title match (30%) + keyword overlap with master_resume.md (30%) + location (20%) + salary (10%) + source quality (10%)
- Bonuses: IoT +15%, AI/ML +20%, Atlanta startup +20%, Atlanta enterprise +10%, watchlist +10%
- Penalties: title gap -5%, seniority mismatch -5%
- Eliminate: crypto/web3, salary <$100K, VP/Head/Staff/Principal, clearances, >21 days old
- Company cap: suppress companies with ≥3 unapplied (applied=false, outcome=null) unless score >110

Pick the top 3-4 jobs.

**Read `master_resume.md` NOW** — read it once here and reuse for all 4 tailorings below.

## Step 3: Fetch Full JDs

For each of the top 3-4 jobs, WebFetch the apply URL to get the full job description.
If WebFetch fails (403, JS-rendered), fall back to WebSearch for cached/indexed versions.

## Step 4: Tailor Resumes and Cover Letters

For each of the top 3-4 jobs, follow the CLAUDE.md tailoring workflow:

1. **Tailor resume markdown** → save to `tailored/Aneesh_Khan_[Company]_[Role].md`
2. **Write resume JSON data file** → save to `tailored/Aneesh_Khan_[Company]_[Role]_data.json`
   Schema matches `pipeline/pdf_helpers.py`:
   ```json
   {
     "summary": "...",
     "experience": [{"title": "...", "company": "...", "bullets": ["..."]}],
     "education": {"degree": "...", "school": "..."},
     "skills": ["<b>Category:</b> item1, item2"]
   }
   ```
3. **Generate resume PDF**:
   ```bash
   python pipeline/render_pdf.py resume tailored/Aneesh_Khan_[Company]_[Role]_data.json tailored/Aneesh_Khan_[Company]_[Role].pdf
   ```
4. **Tailor cover letter markdown** → save to `tailored/Aneesh_Khan_[Company]_[Role]_cover.md`
5. **Write cover letter JSON data file** → save to `tailored/Aneesh_Khan_[Company]_[Role]_cover_data.json`
   ```json
   {
     "date": "May 1, 2026",
     "recipient": "Hiring Team<br/>Company Name",
     "paragraphs": ["Dear...", "paragraph 2...", "..."],
     "closing": "Warmly,"
   }
   ```
6. **Generate cover letter PDF**:
   ```bash
   python pipeline/render_pdf.py cover tailored/Aneesh_Khan_[Company]_[Role]_cover_data.json tailored/Aneesh_Khan_[Company]_[Role]_cover.pdf
   ```

**IMPORTANT:** Do NOT copy `generate_pdf.py` or write custom `*_pdf.py` scripts. Use `render_pdf.py` with JSON data files.

## Step 5: Send Email Digest

Use Gmail MCP to create a draft email to your email address with:
- Subject: "Daily Job Matches — [date] ([N] jobs)"
- Body: HTML table with each job's title, company, location, salary, score, JD coverage %, and apply link
- Include file paths for resume and cover letter PDFs
- Note any ATS errors, filtered companies, and Python/skill gaps

## Step 6: Update Tracking

- Append new jobs to `pipeline/jobs/seen_jobs.json` with full schema
- Append new URLs to `pipeline/jobs/seen_urls.json`
- Create `pipeline/jobs/jobs_YYYY-MM-DD.json` with full structured records
- Create `pipeline/jobs/run_YYYY-MM-DD.json` with run metadata and email draft ID
- Append to `pipeline/jobs/outcomes.csv`

## Important Rules
- NEVER fabricate experience, certifications, or skills
- NEVER modify `master_resume.md` or `generate_pdf.py`
- Every resume claim must map to actual experience from the master resume
- If fewer than 3 good matches are found, send what you have — don't pad with bad matches
- If zero matches are found, send a brief email saying "No strong matches today"
