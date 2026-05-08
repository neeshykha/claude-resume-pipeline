# Resume Tailoring Project

## What This Is
This is Aneesh Khan's resume optimization project. The master resume is in `master_resume.md`. The PDF generator is `generate_pdf.py`. Tailored versions go in `tailored/`.

## Default Behavior
When the user pastes a job description (or a link to one), do the following:

### 1. Analyze the JD
- Extract the job title, company name, and key requirements
- Identify keywords that appear in the JD (tools, methodologies, soft skills, industry terms)
- Note any terminology differences from the master resume (e.g., "customer success" vs "support", "account management" vs "client management")
- **Extract the JD's top 15 exact phrases** (hard skills, tools, methodologies, role-specific terminology, responsibility verbs). Save this list — Step 6 verifies coverage. If a JD has fewer than 15 substantive phrases, use all of them.

### 2. ATS & AI Screening Optimization
Before tailoring, apply these principles based on how modern ATS (Greenhouse, Lever, Workday, Taleo) and AI screening tools (HireVue, Pymetrics, Eightfold, etc.) parse and rank resumes:

**Keyword Strategy:**
- Extract EXACT phrases from the JD — AI screeners do literal and semantic matching. If the JD says "cross-functional collaboration," use that exact phrase, not a synonym.
- Include both the spelled-out term AND acronym where applicable (e.g., "Customer Effort Score (CES)", "Key Performance Indicators (KPIs)")
- Embed keywords naturally in achievement bullets, not in a keyword-stuffed block. AI tools now penalize obvious stuffing.
- Match the JD's ratio of hard skills to soft skills. If the JD is 70% technical requirements, the resume should reflect that weighting.

**Formatting for Parsability:**
- Use standard section headers that ATS tools expect: "Professional Experience", "Education", "Skills", "Certifications"
- No tables, columns, headers/footers, or text boxes — these break ATS parsing
- Job titles, company names, and dates must be clearly separated and consistently formatted
- Use standard bullet characters, not custom Unicode symbols

**Semantic Matching (for AI-powered screeners):**
- AI tools like Eightfold and HiredScore do semantic similarity scoring, not just keyword matching. Frame experience using the same *concepts* the JD describes, even when exact keywords differ.
- Quantified achievements score higher — AI tools are trained to identify and weight metrics (%, $, #, time saved, team size)
- Action verbs that match the JD's tone matter. If the JD emphasizes "driving" and "leading," use those over "managed" or "handled"
- Recency weighting: AI screeners weight recent experience more heavily. Ensure the most JD-relevant content is in the current/most recent role.

**First-scan optimization (6-second rule):**
- Human recruiters spend ~6 seconds on initial visual scan before deciding to read or skip. The first bullet of the most recent role is the highest-visibility content after the name and summary.
- The first iApts bullet must lead with a quantified, metrics-dense achievement directly relevant to this JD. Never open with a soft organizational statement ("Lead a globally distributed team...") unless team leadership is the JD's explicit top priority.
- Strong openers: start with an action verb + specific outcome + metric. Weak openers: "Serve as...", "Work with...", "Responsible for...". Recruiters pattern-match on the first 5 words.
- If the most JD-relevant achievement for this application is the Maven AGI deployment, the CES system, the Salesforce admin work, or the scaling story — reorder so that one is bullet #1.

**Role Relevance Scoring:**
- Many AI screeners calculate a "fit score" based on title similarity, years of experience match, industry alignment, and skill overlap. Ensure the summary section explicitly bridges any title gap (e.g., if applying for "Technical Program Manager" but current title is "Technical Support Operations Manager," the summary should frame the overlap clearly).
- **Title bridge rule**: The first sentence of the summary must contain a framing that connects Aneesh to the JD's exact title. If the JD title is "Customer Success Manager," open with language like "Customer success and technical operations leader with 10+ years..." Do not keep the master resume's default "Technical operations leader..." opener when the JD title differs — AI screeners compute title similarity against the summary heavily.

### 3. Tailor the Resume Content
- Read `master_resume.md` as the source of truth — NEVER fabricate experience or skills
- **Summary**: Rewrite to mirror the JD's language, bridge any title gap, and prioritize the most relevant experience
- **Bullet order**: Reorder bullets within each role to front-load the ones most relevant to this JD
- **Bullet selection**: For older roles, you may drop 1-2 less relevant bullets to save space
- **Terminology**: Swap synonyms to match JD language exactly (e.g., if JD says "stakeholder engagement", use that instead of "stakeholder management")
- **Skills section**: Reorder skill categories so the most relevant ones appear first. Mirror the JD's skill language precisely.
- **First bullet rule**: Apply the 6-second rule (see Step 2). The first iApts bullet must be the single most compelling, metrics-dense achievement relative to this JD. Choose from: Maven AGI 85% deflection, CES system implementation, Salesforce 25+ automations, 100% case volume scale, 8-person global team build. Which one leads depends entirely on what the JD weights most.
- **Keep it honest**: Every claim must be backed by actual experience from the master resume

### 4. Save the Tailored Version
- Save the tailored markdown to `tailored/Aneesh_Khan_[Company]_[Role].md` (e.g., `tailored/Aneesh_Khan_Datadog_TAM.md`)
- Use `Aneesh_Khan_` prefix — recruiter inboxes and ATS systems often surface the filename; including the candidate name improves recognition and reduces the chance of misrouted files
- Use TitleCase for company, short role abbreviation (TAM, CSM, SAM, SE, IC)

### 5. Generate PDF
**Preferred (pipeline mode):** Write a JSON data file and use the renderer:
- Save resume data to `tailored/Aneesh_Khan_[Company]_[Role]_data.json` (schema: see `pipeline/pdf_helpers.py` docstring)
- Run: `source .venv/bin/activate && python pipeline/render_pdf.py resume tailored/Aneesh_Khan_[Company]_[Role]_data.json tailored/Aneesh_Khan_[Company]_[Role].pdf`
- This is dramatically cheaper on tokens than writing a full Python script per resume

**Fallback (manual mode):** If `render_pdf.py` is unavailable:
- Copy `generate_pdf.py` to `tailored/Aneesh_Khan_[Company]_[Role]_pdf.py`
- Update the content in the copy to match the tailored resume
- Run it using the venv: `source .venv/bin/activate && python3 tailored/Aneesh_Khan_[Company]_[Role]_pdf.py`

Output PDF to `tailored/Aneesh_Khan_[Company]_[Role].pdf`

### 6. Verify JD Keyword Coverage
- Count how many of the JD's top 15 exact phrases (from Step 1) appear as literal substrings (case-insensitive) in the tailored resume
- **Target: ≥80% (12 of 15).** If below 80%, revise: reorder bullets, swap terminology, or re-surface skills — **without fabricating experience**
- If a JD phrase genuinely cannot be covered because Aneesh doesn't have that experience, flag it in the Step 7 summary as a true gap, don't fake it
- Log the coverage % and the list of missing phrases in the Step 7 summary

### 7. Show a Summary
After generating, display:
- **Targeting**: [Job Title] at [Company]
- **JD Coverage**: N/15 top JD phrases present (exact substring match) + % — this is the authoritative ATS readiness metric
- **Key changes**: Brief list of what was adjusted and why
- **Keyword match**: List of JD keywords that are now reflected in the resume, grouped by (exact match vs. semantic match)
- **Missing keywords**: Any JD requirements that don't map to actual experience (flag these honestly — do NOT add fake experience)
- **Title gap risk**: If the target title differs significantly from Aneesh's actual titles, flag this and explain how the summary bridges it
- **Recommendations**: Suggest 1-3 things Aneesh could do to strengthen future applications (e.g., "Getting a Salesforce Admin cert would close the certification gap many JDs mention")

### 8. Generate Cover Letter
Always generate a tailored cover letter alongside the resume:
- Save markdown to `tailored/Aneesh_Khan_[Company]_[Role]_cover.md`
- **Preferred:** Save cover data to `tailored/Aneesh_Khan_[Company]_[Role]_cover_data.json` and run:
  `python pipeline/render_pdf.py cover tailored/Aneesh_Khan_[Company]_[Role]_cover_data.json tailored/Aneesh_Khan_[Company]_[Role]_cover.pdf`
- **Fallback:** Write a `*_cover_pdf.py` script only if `render_pdf.py` is unavailable
- Mirror the JD's language just like the resume
- Keep it under one page (4–5 short paragraphs)

**Voice rules** (full profile in memory: `feedback_cover_letter_voice.md`):

**OPENER — never start with an observation about the company or industry.**
The #1 failure pattern: opening with a philosophical statement about what the company does or what the industry is experiencing. Examples of what NOT to write: "[Company] is fundamentally about X", "Voice AI is having its enterprise moment", "The hardest part of deploying AI is...". These are AI output and read as such. The opener must be specific to Aneesh — a personal experience with the company/product, a pointed claim about his fit, or something unusual about his candidacy. Self-check: could this sentence have been written by any applicant? If yes, cut it and start on the sentence after it.

**Structure — vary it.** Not every letter needs three bold-header bullets. Sometimes a strong paragraph, sometimes two items, sometimes no bullets. The template is visible when every letter has the same "Three specific things I'd bring:" structure.

**Never use these:**
- "genuinely excited," "genuinely committed," "genuine [anything]" — drop the qualifier, just say it
- "maps directly to," "directly relevant," "translates directly" — trust the reader to see the connection
- "~30% of my weekly time in cross-functional meetings" as a verbatim line — it appears in too many letters; show the cross-functional work through a specific example instead
- "Here's how my experience maps to the role:" — just make the case

**Close — be specific.** "I'd welcome the chance to discuss how my experience translates. Thank you for your consideration." adds nothing. The close must include at least one sentence specific to this role or company — a real question, an observation about the team structure, a practical note. Keep it short.

**Honesty moments — keep them.** When there's a real technical gap, acknowledge it directly and without apology ("Python is a growing area for me," "I am not a software developer"). This is a distinctive voice feature that makes letters feel real. Don't suppress it.

**Final self-check before saving:** (1) Read the first sentence — could it have been written by any LLM for any applicant at this company? If yes, rewrite it. (2) Read the close — is it interchangeable with every other letter? If yes, replace with something specific.

## Important Rules
- NEVER invent experience, certifications, or skills that aren't in `master_resume.md`
- NEVER modify `master_resume.md` — it is the source of truth
- NEVER modify `generate_pdf.py` — it is the template
- If the user says "update master" or similar, THEN you may update `master_resume.md`
- The PDF venv is at `.venv/` — always activate it before running Python scripts
- If the user asks to adjust a tailored version, edit that version's files, not the master

## Pipeline Pre-Run: One-Time Notes

At the very start of each pipeline session, before anything else:

1. Check if `pipeline/NEXT_RUN_NOTES.md` exists
2. If it does: read it, incorporate any instructions or context it contains, then **delete the file** before proceeding
3. If it doesn't exist: continue normally

This file is used to pass one-time instructions between sessions (e.g. "new sources added", "config changed", "backlog was reset"). It self-destructs after one read so it doesn't repeat on future runs.

## Pipeline Pre-Run: Application Status Check

At the **start of every pipeline session** (before discovering new jobs), do the following:

1. Read `pipeline/jobs/seen_jobs.json` and pull all entries where `applied: false` AND `outcome: null`
2. Present them as a numbered checklist, sorted by `first_seen_date` ascending, with this format:

   ```
   Applications to log — which of these did you submit since last time?

   1. Observe.AI — Senior CSM Evergreen (score 116, seen 2026-05-07)
   2. Assembled — Enterprise Deployment Strategist (score 112, seen 2026-05-06)
   ...
   Reply with numbers (e.g. "1, 3"), "none", or "skip" to proceed without updating.
   ```

3. Wait for the reply before proceeding with the new run
4. For each confirmed application, update `seen_jobs.json`:
   - Set `applied: true`
   - Set `applied_date` to today's date
   - Leave `outcome: null` (outcome tracking is separate)
5. Proceed with the new run

**Rules:**
- If the user replies "skip" or doesn't respond within the same turn, proceed without updating — don't block the run
- If the unapplied list is empty, skip this step silently
- After updating, confirm: "Logged N applications. Proceeding with today's run."
- Do not ask about entries already marked `applied: true`

## Pipeline Scoring Tiers

When the daily pipeline surfaces jobs, apply tailoring based on score (thresholds in
`pipeline/watchlist_companies.json` → `_scoring_config`). When a user pastes a JD
directly, always do full tailoring regardless of score.

| Score | Tier | Steps |
|-------|------|-------|
| 110+  | Priority / Full | Full tailoring — required for company-capped roles |
| 88–109 | Full | Summary rewrite, bullet reorder, skills reorder, cover letter |
| 78–87 | Light | Summary rewrite + skills reorder only — no bullet reorder, no cover letter |
| <78  | Skip | Do not surface |

Light tailoring is for IC-level roles (Senior CSM, Renewal Manager, Onboarding Manager)
that meet the salary floor but scored lower due to seniority or keyword penalties.
Volume over perfection at that tier.

## Target Roles for Reference

**Full tailoring track (score 88+):**
- Technical Account Manager (TAM) / Support Account Manager (SAM)
- Customer Success Manager (CSM) / Senior CSM / Manager, Customer Success / Technical CSM / Product CSM
- Technical Support Manager / Support Operations Manager / Technical Operations Manager
- Solutions Engineer (SE) / Customer Engineer / Sales Engineer (when JD allows non-engineering background)
- Implementation Manager / Implementation Consultant / Professional Services Manager / Deployment Strategist
- AI Engagement Manager / Engagement Manager / AI Deployment Manager / Forward Deployed Engineer (AI-native roles)
- Product Manager (Associate/Technical PM)

**Light tailoring track (score 78–87, salary ≥ $110K):**
- Renewal Manager / Partner Success Manager
- Onboarding Manager / Customer Onboarding Specialist
- Customer Enablement Manager / Customer Education Manager

## Supplemental WebSearch Sources (Atlanta + Startup Discovery)

The `_websearch_sources` block in `pipeline/watchlist_companies.json` defines additional sources to run each daily pipeline pass. These catch companies NOT on the ATS watchlist — primarily small and mid-size Atlanta startups.

**Run all three queries every daily pipeline run**, after ATS board polling:
1. **Hypepotamus** (`hypepotamus.com/job-board`) — Atlanta startup-focused, best for unknown small companies
2. **BuiltIn Atlanta** (`builtin.com/atlanta`) — mid-size Atlanta tech companies
3. **Wellfound** (`wellfound.com/jobs`) — early-stage startups nationally, filter to Atlanta

**Scoring adjustments for WebSearch-sourced roles:**
- Source quality score: 8 (vs. 10 for direct ATS) — WebSearch results are less structured
- Atlanta small company bonus (+20) applies if company HQ is Atlanta and headcount ≤200
- Salary floor still applies ($110K) — Wellfound roles especially may list equity-only or below-floor comp; skip these
- If a WebSearch-sourced company has a Greenhouse/Ashby/Lever board, switch to direct ATS polling and add them to the watchlist for future runs

## Quick Commands
- "Tailor for [JD]" — Full tailoring workflow above
- "Compare [company]" — Show diff between tailored version and master
- "List versions" — Show all tailored versions created so far
