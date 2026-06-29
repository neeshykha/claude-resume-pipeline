# Resume Tailoring Project

## Current Session State

**Live run state lives in `pipeline/SESSION_STATE.md` (gitignored, private).** This repo is
public — surfaced companies, scores, Gmail draft IDs, and the application queue must not be
committed. Read and update `pipeline/SESSION_STATE.md` for the latest run summary, company caps,
and action queue. Do **not** restore that state into this file.

---

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
- Run: `.venv/bin/python pipeline/render_pdf.py resume tailored/Aneesh_Khan_[Company]_[Role]_data.json tailored/Aneesh_Khan_[Company]_[Role].pdf`
- This is dramatically cheaper on tokens than writing a full Python script per resume

**Fallback (manual mode):** If `render_pdf.py` is unavailable:
- Copy `generate_pdf.py` to `tailored/Aneesh_Khan_[Company]_[Role]_pdf.py`
- Update the content in the copy to match the tailored resume
- Run it using the venv: `.venv/bin/python3 tailored/Aneesh_Khan_[Company]_[Role]_pdf.py`

Output PDF to `tailored/Aneesh_Khan_[Company]_[Role].pdf`

### 6. Verify JD Keyword Coverage
- Count how many of the JD's top 15 exact phrases (from Step 1) appear as literal substrings (case-insensitive) in the tailored resume
- **Target: ≥80% (12 of 15).** If below 80%, revise: reorder bullets, swap terminology, or re-surface skills — **without fabricating experience**
- **Second-pass rule (apply before accepting any missing phrase as a gap):** For each phrase still missing after the first tailoring pass, check whether a real experience in `master_resume.md` justifies that language. Ask: "Is there something Aneesh actually did that this phrase describes?" If yes, work the phrase in — don't leave achievable coverage on the table. Only flag a phrase as a genuine gap if no honest mapping exists.
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
  `.venv/bin/python pipeline/render_pdf.py cover tailored/Aneesh_Khan_[Company]_[Role]_cover_data.json tailored/Aneesh_Khan_[Company]_[Role]_cover.pdf`
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

**Three positive framings to use when relevant (from direct voice interview):**
- *Maven story:* The real achievement isn't the 85% deflection number — it's the feedback loop: customer data flowing back in to auto-audit the knowledge base and feed T1 training. Lead with the loop, land on the number. Most companies skip the spec work and get swept up in vendor promises; Aneesh did the spec work. That's the differentiator.
- *People management:* Don't just say "I lead a team of 8." The stronger claim is: he hires well enough that people management becomes the simplest part of his job — which means his attention goes to the harder operational work. Frame it as an outcome, not a credential.
- *Closing angle:* Aneesh has had two jobs in a decade. He stays where he's constantly building and learning. The honest close isn't "I'm excited about your mission" — it's something that gestures toward the building/learning dynamic and signals he's not a short-tenure risk.

**Final self-check before saving:** (1) Read the first sentence — could it have been written by any LLM for any applicant at this company? If yes, rewrite it. (2) Read the close — is it interchangeable with every other letter? If yes, replace with something specific.

## Important Rules
- NEVER invent experience, certifications, or skills that aren't in `master_resume.md`
- NEVER modify `master_resume.md` — it is the source of truth
- NEVER modify `generate_pdf.py` — it is the template
- If the user says "update master" or similar, THEN you may update `master_resume.md`
- The PDF venv is at `.venv/` — always activate it before running Python scripts
- If the user asks to adjust a tailored version, edit that version's files, not the master
- **Never use `python3 -c "..."`** for JSON analysis or file updates — multi-line inline scripts with `#` comments trigger a hardcoded security prompt that no permission entry can bypass. Instead: (a) use `grep` for existence checks on seen_jobs.json, (b) write a named `.py` script to `pipeline/_taskname.py`, run it with `.venv/bin/python pipeline/_taskname.py`, then delete it. The `_*.py` pattern is in the allow-list.
- **Never use bash arrays or shell control-flow (`arr=(...)`, `${arr[@]}`, inline `for`/`while`/`if` loops) in Bash commands.** The permission engine cannot statically analyze them, so they prompt *every time* regardless of allow-list entries — and hang autonomous runs. This is the same failure class as `python3 -c`. For the JD keyword coverage check (Step 6 / Step 4), use the permanent helper: write the JD's top phrases to a JSON file, then run `.venv/bin/python pipeline/check_coverage.py <resume.md> <phrases.json>` (allow-listed, prints ✓/✗ per phrase + `Coverage: N/M (P%)`). Do not hand-roll coverage checks with `grep` inside a bash `for` loop.

## Pipeline Pre-Run: One-Time Notes

At the very start of each pipeline session, before anything else:

1. Check if `pipeline/NEXT_RUN_NOTES.md` exists
2. If it does: read it, incorporate any instructions or context it contains, then **delete the file** before proceeding
3. If it doesn't exist: continue normally

This file is used to pass one-time instructions between sessions (e.g. "new sources added", "config changed", "backlog was reset"). It self-destructs after one read so it doesn't repeat on future runs.

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

Light tailoring is for stretch roles (Tier 3–4 title match) that meet the salary floor but
scored lower due to title distance. Volume over perfection at that tier.

### Scoring Guardrails (apply when computing the full score)

These prevent company-level attributes from drowning out role fit. Added 2026-06-23 after a
run surfaced four roles from a single company because structural bonuses were stacking.

1. **Count the AI/industry bonus ONCE.** A watchlist company's `score_bonus` in
   `watchlist_companies.json` (e.g. Cresta `score_bonus: 20`, `bonus_reason: "AI/ML platform"`)
   IS the AI/ML bonus for that company — do **not** also add a separate generic "+20 AI/ML"
   on top. For a company with a config `score_bonus`, use that value and add nothing more for
   AI/ML. For a non-watchlist AI-native company with no config bonus, apply +20 once. Never both.

2. **Cap total company-level bonuses at +30.** The sum of all structural bonuses that describe
   the *company* rather than the *role* — AI/ML, watchlist (+10), Atlanta-enterprise (+10) /
   Atlanta-startup (+20), IoT (+15) — is capped at **+30 combined**. Role-fit signal
   (title match + keyword overlap, max 60) must remain the larger share of any score. If the
   raw structural bonuses exceed 30, clamp to 30.

3. **Diversity cap — max 2 roles per company per run.** Surface at most 2 roles from any one
   company in a single run, and **fully tailor only the single best-scoring role** at that
   company. List any additional same-company roles as "also live (FYI)" in the digest, not as
   separate tailored applications. `poll_ats.py` already enforces this on the shortlist
   (`MAX_PER_COMPANY_PER_RUN`); apply the same rule to anything added via WebSearch. Rationale:
   applying to 3–4 roles at one company in one day reads as scattershot to that company's
   recruiting team and dilutes the strongest application.

## Target Roles for Reference

Aneesh's background is Technical Support Operations Manager — runs a support function end-to-end
(hiring, training, AI deployment, knowledge base, Salesforce admin, QA auditing, BPO management).
Score title match using `_title_scoring_tiers` in `watchlist_companies.json`.

**Tier 1 — True match (full tailoring, title match +30):**
- Support Operations Manager / Technical Support Operations Manager
- Customer Operations Manager / Technical Operations Manager
- Technical Support Manager / Support Engineering Manager
- Head of Support / Director of Support Operations

**Tier 2 — Strong overlap (full tailoring, title match +22):**
- Technical Account Manager (TAM) / Support Account Manager (SAM)
- Implementation Manager / Deployment Manager / Deployment Strategist
- AI Engagement Manager / AI Deployment Manager / Forward Deployed Engineer
- Professional Services Manager / Implementation Consultant
- Workforce Manager / Contact Center Manager

**Tier 3 — Reasonable stretch (full tailoring if score ≥88, title match +15):**
- Customer Success Manager (only when JD emphasizes technical depth, deployment, or team mgmt)
- Technical CSM / Customer Success Engineer
- Customer Enablement Manager / Technical Enablement Manager
- Solutions Engineer (when JD allows non-engineering background)

**Tier 4 — Weak stretch (light tailoring only, title match +8):**
- Renewal Manager / Partner Success Manager
- Onboarding Manager / Customer Onboarding
- Product Customer Success

## Supplemental WebSearch Sources (Atlanta + Startup Discovery)

The `_websearch_sources` block in `pipeline/watchlist_companies.json` defines additional sources to run each daily pipeline pass. These catch companies NOT on the ATS watchlist — Atlanta startups plus, as of 2026-06-25, broader ATS-host and AI-vertical discovery.

**Run every `status: "active"` source in the `_websearch_sources` block each daily pipeline run**, after ATS board polling. The block is the source of truth — don't hardcode a query count here (it drifts). As of 2026-06-25 the active set is:
1. **BuiltIn Atlanta** / **BuiltIn Remote** — Atlanta + remote mid-size tech (title terms broadened)
2. **Wellfound** — early-stage startups nationally, filter to Atlanta
3. **AI-Titled Roles** — novel AI-prefixed titles (tier2b wildcard)
4. **Ashby / Greenhouse / Lever Boards - Target Roles** — discover companies off the watchlist on each ATS host
5. **AI-Native & AI-Safety Orgs** — vertical/company discovery (catches FAR.AI-type orgs whose fitting roles may be titled differently)
(Hypepotamus remains `disabled` — JS-rendered, not pollable.)

**Discovery sources surface COMPANIES, not just today's jobs.** When an ATS-host or vertical query turns up an unfamiliar company with a Greenhouse/Ashby/Lever board, the goal is to **enroll it**: verify the board is live (direct API check, or `pipeline/verify_workday.py` for Workday), then add it to the watchlist so the poller scans its full roster daily. This is how off-watchlist companies become permanently monitored — a one-time add, not a per-run re-discovery.

**Scoring adjustments for WebSearch-sourced roles:**
- Source quality score: 8 (vs. 10 for direct ATS) — WebSearch results are less structured
- Atlanta small company bonus (+20) applies if company HQ is Atlanta and headcount ≤200
- Salary floor still applies ($100K) — Wellfound roles especially may list equity-only or below-floor comp; skip these
- If a WebSearch-sourced company has a Greenhouse/Ashby/Lever board, switch to direct ATS polling and add them to the watchlist for future runs

## Interview Prep & Post-Mortem Workflow

Interview prep docs and post-mortems live under `interview_prep/` in a per-company directory structure:

```
interview_prep/
├── _lessons_learned.md           ← rolling cross-company patterns + active focus areas
├── _template_prep.md             ← reusable prep template
├── _template_postmortem.md       ← reusable post-mortem template
├── [Company]/
│   ├── prep_round[N]_[type].md
│   └── postmortem_round[N]_[type].md
```

### Skill: `postmortem`

The post-mortem workflow is encoded as a project-level skill at `.claude/skills/postmortem/SKILL.md`. It auto-invokes when Aneesh mentions completing an interview ("just had my call," "let's debrief," "post-mortem [Company]") or can be triggered explicitly. It walks through the call chronologically, captures Q&A with self-grades, synthesizes lessons, and promotes generalizable items to `_lessons_learned.md` in the same session. Refer to the SKILL.md for the full behavior spec.

### Prep workflow (no skill yet — manual)

When Aneesh asks to prep for a new interview round:

- Create `interview_prep/[Company]/prep_round[N]_[type].md` from `_template_prep.md`
- Pre-populate role/company/files-submitted from the tailored resume + cover letter
- Read `_lessons_learned.md` first and surface any "Active Focus Areas" or patterns relevant to this stage/company-type before drafting prep content
- For roles at AI-infra or seed-stage startups specifically: confirm the technical bar with the recruiter before deep prep (this lesson is logged from Kamiwaza R1)

### Rules (apply to both prep and post-mortem)

- Post-mortems should be written within ~24 hours while memory is fresh
- Honest, not flattering — the value is in surfacing blind spots, not making Aneesh feel good
- Generalizable lessons (≥2 future interviews benefit) get promoted to `_lessons_learned.md`. Company-specific notes stay in that company's folder.
- Do NOT fabricate specifics — if Aneesh hasn't told you what was asked or how it landed, leave the section as a placeholder marked with `_[Aneesh — ...]_`
- Voice rules from this CLAUDE.md (no "genuinely," no "directly maps to," no AI tells) apply to any drafted user-facing text — thank-you emails, suggested answer phrasings, etc.

## Quick Commands
- "Tailor for [JD]" — Full tailoring workflow above
- "Compare [company]" — Show diff between tailored version and master
- "List versions" — Show all tailored versions created so far
- "Prep for [Company] round [N]" — Create round-specific interview prep doc
- "Post-mortem [Company] round [N]" — Walk through post-mortem and update lessons learned
