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

**Wellfound dork is disabled** (status="disabled" in `_websearch_sources`) — it returns SEO category pages, not live jobs. Don't run it. The freed slot goes to the Ashby/Greenhouse/Lever board dorks, which are the channel that actually reaches sub-500 companies.

### Step 1b: Run discovery feeders + process the enrollment queue (turns sightings into permanent monitoring)

`pipeline/enrollment_candidates.json` is the standing queue that stops off-watchlist sightings from dead-ending. Feeders append to `pending`; you verify + enroll/reject each entry.

**First, run the feeders** (they only append to the queue — cheap, structured, no in-context board dumps):
- `.venv/bin/python pipeline/poll_remotive.py` — daily. Appends NAME-ONLY leads (`needs_ats_resolution: true`).
- `.venv/bin/python pipeline/harvest_hn_hiring.py` — **only on/after the 1st of the month** (new HN "Who is hiring" thread). Appends directly-enrollable `(ats, slug)` candidates. Skip on other days (it's idempotent, but it's a monthly source).
- Board dorks (Ashby/Greenhouse/Lever, from `_websearch_sources`) — append any UNFAMILIAR company to `pending`.

**Then process every `pending` entry:**
1. If `needs_ats_resolution: true` (name-only lead), resolve the ATS first: `site:greenhouse.io OR site:jobs.ashbyhq.com OR site:jobs.lever.co <company>`. If no board is found, reject with that reason.
2. Verify the board is live (direct ATS API check; `pipeline/verify_workday.py` for Workday) and has **US-reachable** fit-space roles. Reject Europe/APAC-only boards — their fit roles aren't reachable.
3. If it passes → add a full entry to `watchlist_companies.json → companies` (with `headcount_band`, `enrolled_date`, `enrolled_via`, any `score_bonus`), then move it from `pending` to `enrolled`. If not → move it to `rejected` with a one-line reason (so it's never re-evaluated). The poller picks up new watchlist companies automatically next run.
4. **Bias toward sub-500.** This layer exists to catch the long tail the big-company watchlist misses. A 150-person company where a support-ops/CSM/implementation role has real scope beats yet another CSM seat at a 3,000-person name.

ATS providers the poller now speaks: Greenhouse, Ashby, Lever, Workday, **SmartRecruiters** (slug = case-sensitive company identifier, e.g. `BoschGroup`). Workable is not yet supported — if a great company is Workable-only, note it in the digest.

## Step 2: Filter and Score

From the combined ATS hits + WebSearch results, apply the full scoring rubric. **The canonical
rubric is the absolute-point model in `CLAUDE.md` (`## Pipeline Scoring Tiers` + title tiers in
`watchlist_companies.json → _title_scoring_tiers`) — not percentages.** Each component adds points:
- Title match (T1 +30 / T2 +22 / T3 +15 / T4 +8) + keyword overlap (up to +30) + location
  (Atlanta in-office +20 / hybrid +18 / remote +16 / NYC-NJ +12) + salary (≥$140K +10 / ≥$120K
  +8 / ≥$100K or unlisted +5 / below 0) + source quality (Greenhouse·Lever +10 / Ashby·BuiltIn +8)
- Bonuses (points, not %): AI/ML +20, watchlist +10, Atlanta-startup +20, Atlanta-enterprise +10, IoT +15, small-company +15 (≤200) / +8 (201-500)
- **Small-company bonus:** if the company entry carries a `headcount_band`, add +15 for ≤200 or +8 for 201-500 (see `_scoring_config → small_company_bonus`). Absent band = neutral (0); do NOT guess headcount. It's a company-level bonus, so it falls under the +30 cap below — which means it mostly lifts small NON-AI companies (PermitFlow, Antithesis, Mintlify) that have role fit but no AI/Atlanta bonus to clear threshold.
- Penalties: title gap -5, seniority mismatch -5
- **Apply the Scoring Guardrails in CLAUDE.md:** count the AI/industry bonus ONCE (a company's
  config `score_bonus` IS its AI bonus — don't also add generic +20); cap total company-level
  bonuses (AI/ML + watchlist + Atlanta + IoT + small-company) at +30 so role fit dominates;
  surface ≤2 roles per company per run and tailor only the best one (the rest are "also live (FYI)").
- Eliminate: crypto/web3, salary <$100K (midpoint), VP/Head/Staff/Principal, clearances, >21 days old
- Company cap: suppress companies with ≥3 PENDING APPLICATIONS (applied=true AND outcome=null) unless score >110. Queued/unapplied roles do NOT count toward the cap — this is the canonical rule in `watchlist_companies.json → _scoring_config`. `poll_ats.py` enforces this same rule; trust its `capped_companies` output.

Pick the top 3-4 jobs (subject to the ≤2-per-company diversity cap above).

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
- Append to `pipeline/outcomes.csv` (the canonical tracker, gitignored; schema: `applied_date,company,title,url,fit_score,jd_coverage_pct,stage,outcome,notes`). NOTE: `pipeline/jobs/outcomes.csv` is a stale orphan — do not write to it.

## Important Rules
- NEVER fabricate experience, certifications, or skills
- NEVER modify `master_resume.md` or `generate_pdf.py`
- Every resume claim must map to actual experience from the master resume
- If fewer than 3 good matches are found, send what you have — don't pad with bad matches
- If zero matches are found, send a brief email saying "No strong matches today"
