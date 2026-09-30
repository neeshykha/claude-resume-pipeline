# Resume Tailoring Project

## Current Session State

**Live run state lives in `pipeline/SESSION_STATE.md` (gitignored, private).** This repo is
public — surfaced companies, scores, Gmail draft IDs, and the application queue must not be
committed. Read and update `pipeline/SESSION_STATE.md` for the latest run summary, company caps,
and action queue. Do **not** restore that state into this file.

**A local commit on `main` here is as good as published.** Other sessions commit and push this
branch (the daily run at Step 7, the portfolio routine). Decide whether something is fit for a
public repo when you commit it, not when you push. [D1](DECISIONS.md#d1-a-local-commit-reached-origin-within-the-hour)

**This file holds current rules only. The incidents behind them live in `DECISIONS.md`**, and a
rule that came from one links to its entry (`[D7]` and so on). Read an entry when you're about to
change or question that rule, not by default. When a new incident produces a rule, the rule goes
here in a line or two and the story goes there.

---

## What This Is
This is Aneesh Khan's resume optimization project. The master resume is in `master_resume.md`. The PDF generator is `generate_pdf.py`. Tailored versions go in `tailored/`.

## Default Behavior
When the user pastes a job description (or a link to one), do the following:

### 0. Read the writing style guide (mandatory, every task)
Before drafting ANY resume, cover letter, email, or other prose, read
`/Users/aneesh/.claude/projects/-Users-aneesh/memory/user_writing_style.md` in full and apply
it. This is not optional and not satisfied by memory of a previous session — the file changes
(e.g., 2026-07-01 it flagged that past resumes and cover letters were saturated with em-dashes).
Non-negotiables that have already been violated in shipped documents:
- **Em-dash rule:** prefer colons and semicolons for asides and clarifications. Hard cap:
  2 em-dashes per document. Before rendering any PDF, count them (`grep -c '—' <file>` is
  allow-listed) and rewrite until under the cap.
- No AI tells (phrase or structural), no corporate speak, varied sentence rhythm, confident
  voice. Run the guide's Gut Check on every finished document.

Also read `.claude/skills/career-narrative/SKILL.md` (auto-triggers as a skill in
interactive sessions; the daily pipeline reads it at Step 0). It owns Aneesh's
POSITIONING: five signature frameworks, STAR story bank, the Agent Operations evidence
map, transferable-parallel template.
Precedence: style guide + the voice rules below govern form; career narrative governs
substance; `master_resume.md` is the only source of factual claims.

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
- **First bullet rule**: Apply the 6-second rule (see Step 2). The first iApts bullet must be the single most compelling, metrics-dense achievement relative to this JD. Choose from: the Maven AGI deployment, the CES system implementation, the Salesforce automations, the case-volume scale-up, the global team build. The numbers for each come from `master_resume.md`. Which one leads depends entirely on what the JD weights most.
- **Portfolio projects**: `portfolio_projects.md` lists public GitHub projects citable in resumes and cover letters, each with a "cite when" trigger and a resume-ready line. Check it during tailoring; when the JD matches a trigger (AI evaluation, deployment rigor, workflow automation), work the project in — a verifiable public repo is stronger evidence than a claim. Never embellish beyond what that file states. The Friday portfolio routine appends new entries after each build. As of 2026-09-07 the renderer has a dedicated `projects` array (see Step 4), so a cited project goes in its own SELECTED TECHNICAL PROJECTS section rather than being worked into an experience bullet. Pick 2-4 per role, not every entry: `portfolio_projects.md` governs WHEN to cite via its `Cite when:` triggers, `master_resume.md` governs the factual line itself, and the career-narrative skill's Agent Operations evidence map carries the recommended order for agent-operating roles. Omit the field entirely when the JD does not earn the space; it is optional and costs a page.
- **Keep it honest**: Every claim must be backed by actual experience from the master resume

### 4. Save the Tailored Version
- Save the tailored resume as `tailored/Aneesh_Khan_[Company]_[Role]_data.json` (schema: see `pipeline/pdf_helpers.py` docstring; e.g., `tailored/Aneesh_Khan_Datadog_TAM_data.json`). **The JSON is the single source of truth**: the PDF renders from it and the coverage check reads it. Don't also write a markdown twin; write a `.md` only if Aneesh asks for one. [D2](DECISIONS.md#d2-the-tailored-json-became-the-only-resume-copy)
- `projects` is optional and guarded: omit the key and nothing renders. Include it as a list of strings, same shape as `community`, one repo per string. `check_coverage.py` counts it, so project text scores toward JD coverage like any other section.
- Use `Aneesh_Khan_` prefix — recruiter inboxes and ATS systems often surface the filename; including the candidate name improves recognition and reduces the chance of misrouted files
- Use TitleCase for company, short role abbreviation (TAM, CSM, SAM, SE, IC)

### 5. Generate PDF
**Preferred (pipeline mode):** Render the JSON from Step 4:
- Run: `.venv/bin/python pipeline/render_pdf.py resume tailored/Aneesh_Khan_[Company]_[Role]_data.json tailored/Aneesh_Khan_[Company]_[Role].pdf`
- This is dramatically cheaper on tokens than writing a full Python script per resume

**Fallback (manual mode):** If `render_pdf.py` is unavailable:
- Copy `generate_pdf.py` to `tailored/Aneesh_Khan_[Company]_[Role]_pdf.py`
- Update the content in the copy to match the tailored resume
- Run it using the venv: `.venv/bin/python3 tailored/Aneesh_Khan_[Company]_[Role]_pdf.py`

Output PDF to `tailored/Aneesh_Khan_[Company]_[Role].pdf`

### 6. Verify JD Keyword Coverage
- Write the JD's top 15 exact phrases (from Step 1) to `tailored/Aneesh_Khan_[Company]_[Role]_phrases.json` and run `.venv/bin/python pipeline/check_coverage.py tailored/Aneesh_Khan_[Company]_[Role]_data.json tailored/Aneesh_Khan_[Company]_[Role]_phrases.json`. It reports each phrase as a literal, case-insensitive substring of the resume JSON (summary, competencies, titles, bullets, education, skills, community; renderer markup stripped). It also still accepts a `.md` path for older tailored versions.
- **Target: ≥80% (12 of 15).** If below 80%, revise the JSON: reorder bullets, swap terminology, or re-surface skills — **without fabricating experience** — then re-run the check and re-render the PDF
- **Second-pass rule (apply before accepting any missing phrase as a gap):** For each phrase still missing after the first tailoring pass, check whether a real experience in `master_resume.md` justifies that language. Ask: "Is there something Aneesh actually did that this phrase describes?" If yes, work the phrase in — don't leave achievable coverage on the table. Only flag a phrase as a genuine gap if no honest mapping exists.
- If a JD phrase genuinely cannot be covered because Aneesh doesn't have that experience, flag it in the Step 7 summary as a true gap, don't fake it
- Log the coverage % and the list of missing phrases in the Step 7 summary

### 7. Show a Summary
After generating, display:
- **Targeting**: [Job Title] at [Company]
- **JD Coverage**: N/15 top JD phrases present (exact substring match) + %. This is a pass/fail ATS-parsing gate at 80%, NOT a readiness or fit metric — do not rank roles by it (see the `jd_coverage_pct` note in the tracking-files section for why)
- **Unmet hard requirements**: the count of JD hard requirements that can't be honestly claimed, plus a one-line list. This is the readiness signal; it goes in `outcomes.csv → unmet_hard_reqs`
- **Vendor tool named in the JD**: the incumbent AI/support tool the posting names, if any (`Intercom/Fin`, `Forethought AI`). Goes in `outcomes.csv → vendor_tool_named_in_jd`, blank if none
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

**Content comes from the career narrative** (`.claude/skills/career-narrative/SKILL.md`):
one framework max per letter, one STAR story, one transferable-parallel connection,
positioning early but never as a templated opener. The voice rules below win any conflict
about how the letter reads.

**Voice rules** (full profile in memory: `feedback_cover_letter_voice.md`):

**OPENER — never start with an observation about the company or industry.**
The #1 failure pattern: opening with a philosophical statement about what the company does or what the industry is experiencing. Examples of what NOT to write: "[Company] is fundamentally about X", "Voice AI is having its enterprise moment", "The hardest part of deploying AI is...". These are AI output and read as such. The opener must be specific to Aneesh — a personal experience with the company/product, a pointed claim about his fit, or something unusual about his candidacy. Self-check: could this sentence have been written by any applicant? If yes, cut it and start on the sentence after it.

**OPENER — never lead with a schedule/location accommodation.** Even when the accommodation is real and easy, a fast resume-screen reads the gap before it reads any qualification. Make the fit case first; if a JD states a timezone/location requirement Aneesh can meet but doesn't natively satisfy, address it later in the letter (middle paragraph or close) and frame it as a settled fact of how he already works rather than a hypothetical adjustment. [D3](DECISIONS.md#d3-cover-letter-opened-on-a-schedule-accommodation)

**Structure — vary it.** Not every letter needs three bold-header bullets. Sometimes a strong paragraph, sometimes two items, sometimes no bullets. The template is visible when every letter has the same "Three specific things I'd bring:" structure.

**Never use these:**
- "genuinely excited," "genuinely committed," "genuine [anything]" — drop the qualifier, just say it
- "maps directly to," "directly relevant," "translates directly" — trust the reader to see the connection
- "~30% of my weekly time in cross-functional meetings" as a verbatim line — it appears in too many letters; show the cross-functional work through a specific example instead
- "Here's how my experience maps to the role:" — just make the case

**Close — be specific.** "I'd welcome the chance to discuss how my experience translates. Thank you for your consideration." adds nothing. The close must include at least one sentence specific to this role or company — a real question, an observation about the team structure, a practical note. Keep it short.

**Honesty moments — keep them, but verify the gap is still real.** When there's a genuine technical gap, acknowledge it directly and without apology. This is a distinctive voice feature that makes letters feel real, and suppressing it costs more than it saves. What it is not is a license to keep repeating a concession after it stops being true. Before conceding any technical gap, read `portfolio_projects.md`, not just `master_resume.md` — the public repos are where a lot of his evidence lives and none of them appear in the master resume.

**Python is no longer one of these.** Don't concede it. `skill-regression-harness` and `deflection-audit` are unit-tested Python tools, and `sf-caseops-mcp` is a working MCP server running daily against a live Salesforce org. Their current sizes and test counts live in `portfolio_projects.md` and each repo's README; quote numbers from there, never from this file. [D4](DECISIONS.md#d4-python-stopped-being-a-conceded-gap)

The replacement is scope, not volume. Claim: Python for tooling and evaluation harnesses, API clients, CLI utilities, unit-tested modules, an MCP server against a live org. Don't claim: software engineer as a role he has held, production application development, or shipping code in a team codebase; there's no code review, no CI, and no on-call for a service behind any of it. `master_resume.md` states exactly this scope under TECHNICAL SKILLS, so match it rather than improvising a fresh hedge per letter. The career-narrative skill's Language calibration paragraph arbitrates anything not covered here.

"I am not a software developer" stays available, because it's still true and it's the right answer when a JD asks for an engineer. Just don't let it carry the Python question — it answers a different one, and pairing it with the repos reads as someone who hasn't looked at his own work.

**Do not edit the five letters that used the old Python line** (sent 2026-04-30 to 2026-07-23; see [D4](DECISIONS.md#d4-python-stopped-being-a-conceded-gap)). They're sent letters, so the sent-letter rule covers them too. They're the record of what those employers read (see the sent-letter rule in the voice-gate section). This correction governs new letters only.

**Always pair a named gap with a concrete ramp commitment (added 2026-08-20, Aneesh's direct ask).** Naming the gap is half the move; the other half is showing he intends to close it and can. A bare admission leaves the reader to decide how much it costs them. Do NOT write generic filler — "I'm a fast learner," "I pick things up quickly," "eager to grow" are exactly the vague fluff the style guide bans, and they read as padding. The commitment has to be specific enough to be checkable, and ideally starts before he's asked:

- **Name when he'll start, and make it early.** A dated, checkable claim about behavior beats any adjective about learning speed. **Don't build it on a stock construction.** Pick the form that fits this gap: something he's already working through this week, a named resource with a start date, a first concrete step already taken, or what he'll have done by the end of his first week in the role. Before saving, read the ramp sentence in the last five letters in `tailored/` and don't reuse its structure; the per-letter voice gate can't see repetition across letters. Promise only work he'll actually do, because a sent letter commits him to it. [D5](DECISIONS.md#d5-ramp-commitments-converged-on-one-sentence), [D28](DECISIONS.md#d28-the-ramp-line-converged-again)
- **Re-read what the requirement actually demands, then aim at that.** Requirements are often looser than they look. Framer's bar was "enough to read our code and dig in from day one," which is a *reading* bar, not a writing one; naming that distinction turned the weakest paragraph in the letter into an argument. Check for this before conceding a requirement wholesale.
- **Cite evidence he ramps fast rather than asserting it.** Real precedents, all in `master_resume.md` (take the numbers from there): sole integration partner on the Maven AGI deployment with no prior AI-vendor experience at the company; training the Resideo agents to absorb an entire support function; the support-org scale-up; teaching himself the Claude Agent SDK and MCP server development (both on the AI & Automation skills line; it gives no automation count, so don't quote one). One concrete precedent beats three claims.
- **Keep it to two or three sentences, in or beside the gap paragraph.** This is a beat inside the honesty moment, not its own section, and it must never turn into a plea.

The move is: gap, dated commitment, re-read the requirement, aim at what it actually asks. The Framer letter (2026-08-20) is the worked example, described in [D5](DECISIONS.md#d5-ramp-commitments-converged-on-one-sentence); its sentences are deliberately not reproduced anywhere.

**Three positive framings to use when relevant (from direct voice interview):**
- *Maven story:* The real achievement isn't the 85% deflection number — it's the feedback loop: customer data flowing back in to auto-audit the knowledge base and feed T1 training. Lead with the loop, land on the number. Most companies skip the spec work and get swept up in vendor promises; Aneesh did the spec work. That's the differentiator.
- *People management:* Don't just say "I lead a team of 8." The stronger claim is: he hires well enough that people management becomes the simplest part of his job — which means his attention goes to the harder operational work. Frame it as an outcome, not a credential.
- *Closing angle:* Aneesh has had two jobs in a decade. He stays where he's constantly building and learning. The honest close isn't "I'm excited about your mission" — it's something that gestures toward the building/learning dynamic and signals he's not a short-tenure risk.

**Opener anti-template log:** `tailored/_cover_openers.md` holds one line per letter (`- [date] [Company]: "first sentence"`). Before writing a new letter, read it — the new opener must not reuse the structure of the last 5 logged openers. After saving the letter, append its first sentence to the log. This catches template convergence that the per-letter self-check misses.

**Final self-check before saving:** (1) Read the first sentence — could it have been written by any LLM for any applicant at this company? If yes, rewrite it. (2) Read the close — is it interchangeable with every other letter? If yes, replace with something specific. (3) Check the opener log for structural repetition.

**Mechanical voice gate:** run
`.venv/bin/python pipeline/check_voice.py --drafted-now <cover.md>` before rendering. It checks
the contraction ratio, the em-dash cap, and sentence-length uniformity, and exits 1 on failure.
The daily pipeline runs this plus an `avoid-ai-writing` detect pass at Step 4.5.
- **Never edit a letter that has already been sent** — the file is the record of what the
  employer read, and editing it makes the archive disagree with the submission. The script
  labels each letter's stage. `surfaced` does NOT mean unsent: it means no confirmation was
  matched. Only `--drafted-now` (letters the current run authored) is safe to edit without asking.
- **Contractions are the one that keeps slipping.** Aneesh's own letters use contractions
  throughout with no expanded forms. No single "I have never" or "does not" looks wrong, so the
  drift only shows in aggregate, which is why it's a script and not a habit.
  [D6](DECISIONS.md#d6-voice-gate-and-the-contraction-slip)

## Important Rules
- NEVER invent experience, certifications, or skills that aren't in `master_resume.md`
- NEVER modify `master_resume.md` — it is the source of truth
- NEVER modify `generate_pdf.py` — it is the template
- If the user says "update master" or similar, THEN you may update `master_resume.md`
- The PDF venv is at `.venv/` — always activate it before running Python scripts
- If the user asks to adjust a tailored version, edit that version's files, not the master
- **Never use `python3 -c "..."`** for JSON analysis or file updates — multi-line inline scripts with `#` comments trigger a hardcoded security prompt that no permission entry can bypass. Instead: (a) use `grep` for existence checks on seen_jobs.json, (b) write a named `.py` script to `pipeline/_taskname.py`, run it with `.venv/bin/python pipeline/_taskname.py`, then delete it. The `_*.py` pattern is in the allow-list.
- **Never use bash arrays or shell control-flow (`arr=(...)`, `${arr[@]}`, inline `for`/`while`/`if` loops) in Bash commands.** The permission engine cannot statically analyze them, so they prompt *every time* regardless of allow-list entries — and hang autonomous runs. This is the same failure class as `python3 -c`. For the JD keyword coverage check (Step 6 / Step 4), use the permanent helper: write the JD's top phrases to a JSON file, then run `.venv/bin/python pipeline/check_coverage.py <resume _data.json> <phrases.json>` (allow-listed, prints ✓/✗ per phrase + `Coverage: N/M (P%)`; a `.md` path still works for older versions). Do not hand-roll coverage checks with `grep` inside a bash `for` loop.

## Pipeline Routine — Source of Truth

The daily pipeline's canonical, executable spec is **`pipeline/daily_task_prompt.md`** (consolidated 2026-07-01). The scheduled task's SKILL.md (`~/.claude/scheduled-tasks/daily-job-pipeline/SKILL.md`) is a thin loader that reads and executes that file — never add steps, thresholds, or query lists to the SKILL.md, and never maintain a second copy of the routine anywhere. Scoring numbers live in `watchlist_companies.json → _scoring_config`. Tracking-file updates go through `pipeline/update_tracking.py` (never hand-edit `seen_jobs.json`).

### Tracking files: which script owns what (updated 2026-07-28)

| File | Written by | Never do |
|---|---|---|
| `seen_jobs.json`, `seen_urls.json`, new `outcomes.csv` rows | `update_tracking.py` | hand-edit |
| `outcomes.csv` stage → applied | `mark_applied.py` (from Gmail confirmations) | hand-edit the stage column |
| `outcomes.csv` outcome (rejected/interview/offer) | `mark_outcome.py` | infer an outcome from silence |
| `outcomes.csv` schema migrations | `repair_outcomes.py` | hand-fix drifted rows |

**`outcomes.csv` canonical schema (16 columns as of 2026-09-07, when `ic_scope` landed):**
`applied_date,company,title,url,fit_score,jd_coverage_pct,stage,outcome,notes,source_channel,surfaced_date,unmet_hard_reqs,vendor_tool_named_in_jd,hard_req_cap_trigger,furthest_stage,ic_scope`

**`furthest_stage`** records the furthest point a role ever reached and **only ever moves right**.
`outcome` is a single terminal-state column, so a role that reached an interview and was then
rejected reads only `rejected`; this column is what keeps the interview.
Vocabulary, weakest to strongest, in `FURTHEST_STAGES` (`repair_outcomes.py`):
`applied` · `assessment` · `interview` · `onsite` · `offer`.
**Empty means NOT RECORDED, not "never interviewed."** Rows that predate the column
(2026-08-27) stay blank on purpose; never backfill them to "no interview." Populate it going
forward whenever a stage is confirmed, and set it alongside any `mark_outcome.py` run that
records an interview, assessment, or offer. [D7](DECISIONS.md#d7-furthest_stage-and-the-lost-interviews)

Columns 11–13 [D8](DECISIONS.md#d8-conversion-audit-columns):

- **`surfaced_date`** — when the pipeline first surfaced the role, written once by
  `update_tracking.py` and never updated. `age_report.py` reads this column. Rows the backfill
  couldn't recover stay blank rather than guessed.
- **`unmet_hard_reqs`** — count of JD hard requirements that cannot be honestly claimed. This is
  the intended replacement for `jd_coverage_pct` as a readiness signal. Populate it at Step 6
  from the genuine gaps already identified during tailoring.
- **`vendor_tool_named_in_jd`** — the incumbent AI/support tool the JD names, when it names one
  (`Intercom/Fin`, `Forethought AI`, `Zendesk`). Blank when the JD names none. Recorded to test
  whether vendor mismatch is a recurring rejection cause; it's a hypothesis, not a finding.

**`hard_req_cap_trigger`** records whether the HARD-REQUIREMENT TIER CAP fired: a stated
years-minimum in a function Aneesh has zero years in, or a requirement the JD calls
non-negotiable. `unmet_hard_reqs` can't express that, because it counts every disclosed gap and
most are soft. Three states, and the distinction is load-bearing
[D9](DECISIONS.md#d9-hard_req_cap_trigger):

| Value | Meaning |
|-------|---------|
| `""` | not recorded — every row before 2026-08-21, or a run that skipped the check |
| `none` | checked; nothing triggers the cap |
| *verbatim text* | the triggering requirement, quoted (`5+ years in Data Governance or GTM Systems`) |

**Empty is not "no cap."** Populate it at Step 6 whenever you set `unmet_hard_reqs`; write `none`
rather than leaving it blank, because blank is what an unrecorded row looks like. Pre-existing
rows stay empty (no backfill), and `audit_scores.py` falls back to reading their notes,
labelling that inference as a guess.

**Stage vocabulary:** `surfaced` (tailored, not confirmed sent), `applied`, `rejected`, `closed`,
`expired` (retired by `age_report.py` after 45 days with no confirmation), `tailored` (legacy).

**2026-07-28 is the outcome-data epoch. Do not audit, reconcile, or reason about `applied` rows
that predate it.** The Gmail `+jobs` forwarding filter (Step 0.5) went live 2026-07-28; before
that date nothing could confirm a send, so `stage=applied` on an older row is self-reported and
often just means "tailored." [D10](DECISIONS.md#d10-outcome-data-epoch)

**Standing decision (2026-08-20, Aneesh's call): those historical gaps are out of scope. Do not
spend a run trying to reconcile them, do not surface them in digests, and do not propose bulk
audits of them.** The data is unfalsifiable, so the work has no terminal state. Treat 2026-07-28
as the start of trustworthy outcome data instead: conversion rates, send rates, channel
effectiveness, and any claim about what happened to an application should be computed from
`surfaced_date >= 2026-07-28` and say so. A pre-epoch row is fine to leave sitting in whatever
state it is in; correct one only when Aneesh raises that specific role.

`source_channel` is `pipeline`, `user_surfaced`, `referral`, or `linkedin`, because a referral
and a cold ATS apply convert at very different rates. Vocabulary lives in `KNOWN_CHANNELS`
(`repair_outcomes.py`); add there first or the migration will treat the row as drifted.

**This schema is duplicated in two places on purpose** (`OUTCOMES_HEADER` in
`update_tracking.py`, `CANONICAL` in `repair_outcomes.py`). Change both together, then run
`.venv/bin/python pipeline/repair_outcomes.py --apply` to migrate. Schema drift here is not
cosmetic: `mark_applied.py` silently skips any row whose column count differs from the header.
[D11](DECISIONS.md#d11-source_channel-and-schema-drift)

**`jd_coverage_pct` is a pass/fail gate, not a ranking signal. Never sort, compare, or
prioritize roles by it.** It measures whether the resume mirrors the posting's language, not
whether Aneesh clears the hiring manager's bar. Step 6 tailors every resume toward the 80% target,
so the metric has almost no variance and no amount of outcome data will make it predictive.
Use it exactly one way: as a gate at 80% during tailoring. For readiness, use `unmet_hard_reqs`.
[D12](DECISIONS.md#d12-jd_coverage_pct-has-no-variance)

Title matching is config-driven: `poll_ats.py` builds its matcher at runtime from `watchlist_companies.json → _title_scoring_tiers` + `_poller_config` (stemmed-token matching, so word-form and word-order variants match automatically). To teach the poller a new title, edit the JSON; `poll_ats.py` carries no title lists, endpoints, or scoring numbers of its own. Any `_title_scoring_tiers` key starting with `tier` (except the specially-handled `tier2b_ai_wildcard`) loads automatically as a tier. After ANY hand edit to `watchlist_companies.json` or `enrollment_candidates.json`, run `.venv/bin/python pipeline/validate_config.py` (syntax + schema check). The daily run also runs it at Step 1-pre, and `poll_ats.py` refuses to poll against a malformed watchlist. [D13](DECISIONS.md#d13-config-driven-title-matching)

**JSON escaping is per-file and load-bearing (set 2026-09-07).** `enrollment_candidates.json` is stored ESCAPED (`json.dump(..., indent=2)`, `ensure_ascii` left at its default True); `watchlist_companies.json` is stored RAW (`ensure_ascii=False`). Every writer must match its file, and each write ends with a single `f.write("\n")`. A writer on the wrong setting rewrites every non-ASCII line in a 350-430KB file, so whichever script ran last flips the escaping of the whole file and buries a two-line logical change in a ~180-line diff — in a repo that is pushed publicly. Writers of the queue: `harvest_ats.py`, `poll_builtin.py`, `harvest_linkedin.py`, `poll_remotive.py`, `poll_80k.py`, `harvest_hn_hiring.py`, `harvest_vc_portfolios.py`, `weekly_channel_report.py`. Of the watchlist: `harvest_ats.py`, `websearch_rotation.py`. `harvest_ats.py` writes both in one loop and branches on `ensure_ascii=(path == QUEUE)` — don't collapse that to one setting. Hand edits must also round-trip: a stray `,` on its own line in the watchlist (fixed 2026-09-07) was valid JSON that no writer would emit, so it reflowed on the next run.

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

**These guardrails are checked mechanically after the fact.** `pipeline/audit_scores.py`
re-derives every recorded score from this rubric and flags ones the rubric could not have
produced, plus rows still carrying a bonus a later rule change retired. It runs report-only
at `daily_task_prompt.md` Step 6 item 4 — the spec for it lives there, not here. Relevant when
editing anything below: **changing a rule does not rescore the rows already recorded under
it**, so a guardrail edit strands the existing queue until `--sweep-drift` reconciles it.
**But `--sweep-drift` only ever SUBTRACTS a retired bonus** (see `sweep_drift()`), so a rule
change that RAISES scores leaves the queue under-scored with nothing to reconcile it. Measure
the affected rows by hand when a rule moves scores upward.
[D14](DECISIONS.md#d14-score-audit-and-rule-changes-that-raise-scores)

1. **Count the vertical bonus ONCE.** A watchlist company's `score_bonus` in
   `watchlist_companies.json` IS that company's complete vertical bonus — do **not** add a
   separate generic "+20 AI/ML" or "+20 tooling" on top. Read `bonus_reason` to see which
   vertical it encodes. There are three cases (how many companies sit in each is in the JSON):
   - `20` + "AI/ML platform" — AI-native company
   - `20` + "Developer/infra tooling" — the company's product is a tool: devtools, dev infra,
     observability, security tooling, data/API platforms. Added after Aneesh
     named tool creation and maintenance as his primary interest, AI co-equal secondary.
   - `30` + both — genuinely both, already pre-clamped at the +30 cap

   For a non-watchlist company with no config bonus: +20 once if AI-native, +20 once if a
   tooling company, +30 if clearly both. Never a config bonus and a manual one together.

   **The tooling list is curated by hand and must stay that way.** A keyword pass over the
   `reason` text was tried on 2026-07-28 and got it wrong in both directions. To classify a new
   company, edit its `score_bonus`/`bonus_reason` directly.
   [D15](DECISIONS.md#d15-vertical-bonus-and-the-hand-curated-tooling-list)

   **This rule is about free text, not about publisher-assigned taxonomies.**
   `poll_builtin.py -> INDUSTRY_ALLOW` reads BuiltIn's own closed industry vocabulary with set
   membership, and the tag split itself was curated by hand; its measured error rates are
   recorded on the constant. It does NOT feed scoring — it gates queue admission only, so a
   miss costs a lead, never a wrong score.

2. **Cap total company-level bonuses at +30.** The sum of all structural bonuses that describe
   the *company* rather than the *role* — AI/ML, watchlist (+10), Atlanta-enterprise (+10) /
   Atlanta-startup (+20), IoT (+15), small-company (+15 ≤200 / +8 201-500), passion-domain
   (+10, current domain list lives in `_scoring_config → passion_domains` — that JSON is the
   only source of truth, don't restate the domain names here) — is capped at **+30 combined**.
   Role-fit signal (title match + keyword overlap, max 60) must remain the
   larger share of any score. If the raw structural bonuses exceed 30, clamp to 30.

   **Small-company bonus (added 2026-06-30 to fix the ignored sub-500 segment).** When a company
   entry in `watchlist_companies.json` carries a `headcount_band`, add +15 (≤200) or +8 (201-500);
   absent band = 0, never guess. Because it lives under this +30 cap, a small AI-native company
   (AI +20 + small +15 → clamped to 30) gains little — by design. The lift lands on small NON-AI
   companies (vertical SaaS, dev infra: PermitFlow, Antithesis, Mintlify) that have real role fit
   but no AI/Atlanta bonus to clear threshold. Rationale: at a 150-person company an ops/CSM/
   implementation hire has real scope; at a 3,000-person company it's one of dozens. Full spec:
   `_scoring_config → small_company_bonus`. Companies are enrolled via the standing queue in
   `pipeline/enrollment_candidates.json` (see `daily_task_prompt.md` Step 1b).

3. **Diversity cap — max 2 roles per company per run.** Surface at most 2 roles from any one
   company in a single run, and **fully tailor only the single best-scoring role** at that
   company. List any additional same-company roles as "also live (FYI)" in the digest, not as
   separate tailored applications. `poll_ats.py` already enforces this on the shortlist
   (`MAX_PER_COMPANY_PER_RUN`); apply the same rule to anything added via WebSearch. Rationale:
   applying to 3–4 roles at one company in one day reads as scattershot to that company's
   recruiting team and dilutes the strongest application.

4. **Unpollable companies can never earn the watchlist +10, so their scores read ~10 points
   low. That is a rubric artifact, not a fit signal.** The watchlist bonus requires enrollment,
   and enrollment requires a supported ATS board. A company with a self-hosted careers site
   (Framer, Alston Construction) or an unresolved Workday tenant is structurally barred from it
   no matter how good the role is. The penalty usually compounds: these companies also tend not
   to publish salary (+5 instead of +8/+10) and score lower on source quality (+8 vs. +10 for
   Greenhouse/Lever), so the same role can land 5–12 points below an identical one at an
   enrolled company.

   Do **not** invent a compensating bonus, and do not enroll a company just to unlock it. Handle
   it in the read instead: when a role sourced from `_blind_spot_companies`,
   `_unpollable_backlog_companies`, or a rejected-as-unpollable entry lands near a tier
   threshold, say so in the digest ("scored 94; ~10 of that gap is the unearnable watchlist
   bonus, not fit") and use judgment on the tier rather than deferring to the number.
   [D16](DECISIONS.md#d16-unpollable-companies-score-low)

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

**Tier 2c — Tooling / systems ownership (full tailoring, title match +22):**
Aneesh's stated PRIMARY interest is building and maintaining tools, with AI co-equal
secondary, backed by the Salesforce automation and admin work, the Maven AGI deployment, and the
CES/QA tooling in `master_resume.md`.
- Business Systems Manager / Analyst · Support Systems Manager · Systems Manager
- Platform Operations Manager · Internal Tools Manager · Tooling Manager · Automation Manager
- Applications Manager family (Business / Enterprise / IT Applications Manager)
- Revenue Operations Manager

**Narrow platform-administration variants are DEMOTED.** The governing rule is
Aneesh's own: *"it's the narrow admin work I don't want."* **The line is ALTITUDE, not domain:**
own a function (build the tooling, run adoption, decide what the system does) versus be someone's
platform administrator (configure the tool, work the queue, hold the cert). Use that test on
titles the list has not seen yet; full statement lives in the career-narrative skill's
Target-Role Criteria. Analyst level is fine and this is not a seniority rule; the
*administrator* rung is the one he declines. A "Manager" in the title does not rescue a role
either: check the responsibilities. Don't count on the salary floor to screen the admin end out,
since AI-native companies pay well for that work.

The demoted titles stay in the tier2c list so they still match and surface, but `_poller_config →
function_mismatch_titles` demotes them to digest FYI lines: `GTM Systems`, `Go-to-Market`,
`Revenue Systems`, `Sales Systems`, `Salesforce Administrator`, `Salesforce Business Systems`,
`CRM Administrator`, `Applications Administrator`. Reverting is a one-line delete per pattern.
[D17](DECISIONS.md#d17-tier-2c-and-the-narrow-admin-demotion)

**Tier 4 — Weak stretch (light tailoring only, title match +8):**
- Renewal Manager / Partner Success Manager
- Onboarding Manager / Customer Onboarding
- Product Customer Success

**Stretch lane (added 2026-08-30, Aneesh's explicit risk-accepted ask):** Forward Deployed
Engineer and Solutions Engineer postings that fail the normal bar still get a bounded
conditional review; spec is `daily_task_prompt.md` Step 3.5 (max 2 JD reads/run, four
gates, own digest section, logged even at zero). Visibility only: the tiers above and the
2026-07-09 FDE demotion stand. He is separately working a qualification pathway toward
both titles. As of 2026-09-14 the lane also takes AI-titled engineer/architect/developer
roles carrying an operating word (poller output `ai_engineer_stretch`, config
`tier2b_ai_wildcard → engineer_stretch_route`), which used to go unreviewed (kept off the AI wildcard, then cut by the 20-slot
borderline cap).
Same 2-read cap, same strict coding gate; the domain gate widens to internal AI automation
for those titles only.

## Supplemental WebSearch Sources (Atlanta + Startup Discovery)

The `_websearch_sources` block in `pipeline/watchlist_companies.json` defines additional sources to run each daily pipeline pass. These catch companies NOT on the ATS watchlist — Atlanta startups plus, as of 2026-06-25, broader ATS-host and AI-vertical discovery.

**These sources are ROTATED, not run exhaustively.** Run
`.venv/bin/python pipeline/websearch_rotation.py` after ATS board polling: it selects the
`rotation_per_run` daily sources with the oldest `last_run` and prints their queries, then
`--mark` records the ones that actually ran. Full spec and rationale:
`pipeline/daily_task_prompt.md` Step 1c. The JSON block is the source of truth for which sources
are active and for the queries themselves; don't list or count them here (it drifts).
[D18](DECISIONS.md#d18-websearch-rotation-and-the-builtin-sources)

- **BuiltIn Remote is disabled**, superseded by `pipeline/poll_builtin.py`, which walks BuiltIn's
  company directory (see `daily_task_prompt.md` Step 1d). **BuiltIn Atlanta stays on
  deliberately:** a live Atlanta role at a company whose board never resolves reaches the
  pipeline only through that role-level dork. That was a judgment call made without data; once a
  few weeks of `source` strings accumulate on `enrolled`/`rejected` entries in
  `enrollment_candidates.json`, re-test whether it earns its rotation slot.
- The `poll_builtin.py` feeder carries two company-level gates: `TARGET_FUNCTIONS` (is it hiring
  in a support-ops function?) and `INDUSTRY_ALLOW` (is it a technology company at all?).
  `--no-fit-gate` turns off `INDUSTRY_ALLOW` to re-measure recall; it's not for daily runs.

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

## User-Surfaced Finds Protocol (LinkedIn/Indeed alerts, word of mouth)

When Aneesh mentions a job or company he found outside the pipeline, do all four steps:
1. **Assess** — find the posting at its source ATS (not the aggregator), score it, give an
   honest fit verdict. Tailor only if he asks.
2. **Diagnose the miss** — determine specifically why the pipeline didn't surface it
   (off-watchlist? ATS host uncovered? query term gap? title filter gap?).
3. **Patch the gap** — fix the config/query/filter so that *class* of miss can't recur,
   and enroll the company on the watchlist if it has a pollable board.
4. **Log the tally** — record the miss + root cause in memory (`project_job_pipeline.md`,
   "discovery miss tally").

**The 2026-07-02 standing decision here is SPENT, not open. Don't re-raise it.** It said a third
WitnessAI-class miss triggers building the ATS directory-harvest layer; that fired, and the layer
is `pipeline/harvest_ats.py`. Treat any memory entry describing that build as un-greenlit as
stale on that point. [D19](DECISIONS.md#d19-harvest-layer-and-ats-coverage)

### Poller and harvester invariants

Rules to hold when editing `poll_ats.py`, `harvest_ats.py`, or the location gates. Each links to
the incident that set it.

- **The poller and the harvester keep separate ATS lists and nothing syncs them. When adding an
  ATS adapter to `poll_ats.py`, check whether `harvest_ats.py` can discover it too.** A company
  on a poller-supported but harvester-unknown ATS gets written to `rejected` with
  `unpollable: true`, which is wrong and also stops it being re-checked. Paylocity is still
  uncovered and unfixable by name (GUID-addressed).
  [D19](DECISIONS.md#d19-harvest-layer-and-ats-coverage)
- **The SmartRecruiters probe returns `None`, never `[]`, on an empty result.** That API answers
  200 with `totalFound: 0` for a slug that doesn't exist, and `[]` would route into
  `_confirm_empty`, which would confirm a slug collision onto a company's permanent record. It
  probes last among the cheap ATSes for the same reason, and `prune()` skips SmartRecruiters on
  purpose. [D19](DECISIONS.md#d19-harvest-layer-and-ats-coverage)
- **Comeet** boards resolve from the company's own careers page (`probe_comeet`); the JS-API
  embed (`COMEET.init`) is read from inside the init object only, so a stray analytics `token:`
  can't pair with anything. `pipeline/test_comeet_credentials.py` covers all three embed shapes.
  **Rippling** falls back to `_endpoints.rippling_board_api` when, and only when, the listing
  lands off ats.rippling.com, with both files sharing `poll_ats.rippling_api_items`. That API is
  undocumented, so it stays the fallback, not the primary path.
  [D20](DECISIONS.md#d20-comeet-and-rippling-adapter-variants)
- **A duplicate record in `enrollment_candidates.json` is a correctness bug, not clutter.**
  `with_provenance()` retires any older record for the same name in the bucket it writes to and
  folds `PROVENANCE_FIELDS` and `CARRY_FIELDS` forward; `weekly_report_surfaced` carries forward
  only onto another unpollable record. Three dispositions:
  1. **Within a bucket, REPLACE.** One company, one record per bucket; the newer probe's fields
     win and the old one's fill the gaps.
  2. **An enrollment NEUTRALIZES that company's rejections in place, never deletes them.**
     `unpollable` and `recheck_if_resurfaced` go false, the reason gets a `SUPERSEDED <date>`
     preamble, and `superseded_by_enrollment` is stamped.
  3. **A rejection for a company already enrolled or on the watchlist is SUPPRESSED and
     printed.** `harvest_ats.py` never removes a watchlist entry (`--prune` owns de-enrollment and
     is report-only).

  `validate_config.py` warns on both duplicate shapes; that's the guard for the other writers
  and for hand edits. [D21](DECISIONS.md#d21-duplicate-enrollment-records)
- **`poll_ats.py` location matching is boundary-based.** `_boundary_pattern()` matches each list
  at non-alphanumeric boundaries using lookarounds rather than `\b`, so a period counts as a
  separator on both sides. `LOCATION_LOOKALIKES` blanks out "New Mexico" before the exclusion
  scan and only there. Genuinely ambiguous city names (Dublin, Paris, Berlin, Toronto) are
  deliberately NOT exempted. "remotely" is an explicit `LOCATION_INCLUDE` entry.
  `harvest_linkedin.py`'s `has_us` still carries the trailing-period bug. Cases live in
  `test_tier3_gate.py → POLL_CASES`.
  [D22](DECISIONS.md#d22-boundary-based-location-matching)
- **The unlisted-US-city gap is scoped out (Aneesh, 2026-09-11).** `LOCATION_INCLUDE` is a
  curated city list with a default-exclude behind it, so an on-site role in an unlisted US city
  drops. Adding state names and USPS codes is the fix whenever it becomes worth the wider
  intake; don't do it unasked.
- **Per-posting country stamps** (`pipeline/countries.py`): when an ATS returns a structured
  country and it resolves to a non-US one, `parse_location` and the harvest probes append
  `(non-US: <Country>)`, and `us_reachable`, `tier3_location_ok`, and `location_relevant` check
  that tag first and answer False outright, dual-region rescue included. A US, absent, or
  unrecognised country stamps nothing, and `GE`/`GS` stamp as the bare code because "Georgia" is
  an Atlanta hint. Property checks at the bottom of `test_tier3_gate.py` re-derive both rules.
  [D23](DECISIONS.md#d23-per-posting-country-stamps)
- **Rippling's country field stays unread, by decision**, and Greenhouse, JazzHR, Workday, and
  Pinpoint return no usable one, so `NON_US_MARKERS` is still the only signal for those and for
  the LinkedIn grader. The stamp shrinks what the blocklist has to cover; it doesn't retire it.
  Leave "montreal" where it is.
- **Workday "N Locations" postings** resolve from the detail endpoint (`jobPostingInfo`, after
  the title gate, one cached request shared with the start-date resolver). Primary +
  `additionalLocations` are joined and the primary's country is stamped unless an alternate
  names the US. On a failed detail read the externalPath segment is used to exclude, never to
  include. `harvest_ats.py`'s Workday probe still scores "N Locations" as not US-reachable
  (under-admits rather than leaks; not fixed).
  [D24](DECISIONS.md#d24-workday-locations-and-pagination)
- **Workday pagination:** read `total` once from the offset-0 response and treat a short page
  as the last page. The cap is `WORKDAY_MAX_POSTINGS` (1000).
  `pipeline/test_workday_pagination.py` covers both with a fake session, no network.

## Job Search Dashboard (built 2026-09-19)

`pipeline/build_dashboard.py` writes one self-contained page, `~/Downloads/job_dashboard.html`,
at `daily_task_prompt.md` Step 6.6: the apply queue (`stage=surfaced`, days left against the
45-day retirement), manual checks (the blind-spot and unpollable-backlog companies), and
applications gone quiet (post-epoch only, blank and `pending` outcomes alike). HTML Shelf tracks
that file (its Track Source File feature) and refreshes the page in place under Career, so the
"I checked this site" ticks survive each rebuild. Spec and the decisions behind it:
`pipeline/DASHBOARD_SPEC.md`.

- **Read-only, and it stays that way.** It never imports or calls `mark_applied.py`,
  `mark_outcome.py`, `update_tracking.py`, or `repair_outcomes.py`. The ticks live in the Shelf
  and the pipeline never reads them. No write-back from the page: a second source of truth next
  to `outcomes.csv` is the thing this repo keeps getting burned by.
- It always exits 0 and prints one line; `dashboard: FAILED ...` means yesterday's page is still
  up, and the page shows its own stale strip when a weekday run should have replaced it.
- The script is committed to a public repo: no company names or sample rows in it or its tests
  (`pipeline/test_build_dashboard.py`, fixtures are made up).
- Manual-check links come from an optional `careers_url` on the watchlist entries, falling back
  to a search link built from `query`.
- An off-schedule rebuild is the same one command. It redraws from the tracker only; it does not
  read Gmail, so new confirmations still wait for Step 0.5.
- **Open:** Phase two is an Interviews section fed by a small
  `pipeline/interviews.json` cache written by the interview scan; not started. Deferred on
  purpose: adapters for the Jobvite and Gem boards a few manual-check companies use, and the
  queue rows that report "N PDFs match" instead of one resume path.

**Queue-vs-Gmail checks.** Aneesh applies only through the `+jobs` alias, so **no change to
Step 0.5 is wanted** for mail that reached his other address. Before calling a queued role
already sent, compare against the tracker row's URL and notes, not the company alone.
[D25](DECISIONS.md#d25-queue-vs-gmail-check)

## JD Screen Fan-out + Rate-Limit Recheck (built 2026-09-25)

The daily run reads every shortlist JD, not only the few it used to pick from listing data.
[D26](DECISIONS.md#d26-why-the-jd-screen-fans-out)
Spec: `daily_task_prompt.md` Step 2-JD and Step 6.7.

- `pipeline/jd_prefetch.py` fetches all shortlist + ai_wildcard + plausible near-window JDs in
  parallel into `jobs/jd_cache/<date>/` (gitignored) with one `batch_NN.json` per 8.
- One Sonnet worker per batch follows `pipeline/jd_screen_worker.md`, writes
  `cards_batch_NN.json` (quoted facts only, never scores), answers in one line.
- `pipeline/jd_screen_table.py` joins cards to one PASS/CHECK/FAIL line per role on location,
  pay midpoint, and hard red flags; the orchestrator scores PASS/CHECK with the normal rubric.
- Tailoring cap is 5; every other role at or above the light threshold goes to the digest's
  "Cleared, not tailored" section and `jobs/screened_<date>.json`, which
  `build_dashboard.py` shows on the Shelf (last 7 days, dropped once in `outcomes.csv`).
- Workable gives this machine a fixed request allowance per window (~26-45 requests), not a
  rate, so `harvest_ats.py` probes it with only the first 4 slug spellings
  (`WORKABLE_MAX_VARIANTS`), and Step 6.7 re-probes the 10 oldest `throttled` rejections late
  in the run via `throttle_recheck_pick.py`. Dry run: 10 of 10 resolved, 0 throttled.
- Cost: ~150K Sonnet tokens per worker, ~10 workers a run.
- It works inside scheduled sessions (first scheduled run 2026-09-28, no fallback needed). If
  the Agent tool is ever unavailable, the documented fallback reads the cached JDs for the top
  8 inline.

## Assisted Apply (on-demand skill)

`assisted-apply` (`.claude/skills/assisted-apply/SKILL.md`, local-only) fills a job
application form in the browser up to but never including submit. **Explicit invocation
only** — "assisted apply", "help me apply to X", "fill out this application". Never
triggered by the daily pipeline, never inferred from a role being tailored.

It's aimed at the high-effort ATSes (Workday, Paylocity, Taleo, iCIMS) that make him retype his
whole work history after an upload. [D27](DECISIONS.md#d27-why-assisted-apply-exists)

Claude never creates accounts, enters passwords, clicks submit, answers EEO or
self-identification questions, answers screening questions (work authorization, salary,
start date, "why this company"), or invents a field value. Aneesh signs in, Claude types
the work history, Aneesh reviews and sends.

Reusable field values live in `pipeline/application_profile.json` (**gitignored** — it
holds a home address and exact employment months, same reasoning as `local_config.json`).
Anything reading `NEEDS_ANEESH` has never been supplied; the skill collects those once,
writes them back, and never asks again. This exists because `master_resume.md` carries a
month only for iApartments while every Workday form demands month and year.

Known constraint: the Chrome extension runs in its own isolated tab group and cannot
drive a tab Aneesh already has open, so he signs in on Claude's tab. The no-browser
fallback is a paste-ready field sheet in the form's own section order (example:
`tailored/Aneesh_Khan_BrownBrown_AIAdoption_workday_fields.md`), which is often the
better option anyway.

## Weekly Work Harvest (built 2026-09-24, local-only)

Keeps `master_resume.md` current with the week's real work.

- **Friday sweep:** scheduled task `friday-work-harvest` (Fri 4 PM, `model: opus`) runs
  `pipeline/harvest_work_log.py`, which boils the week's Claude Code transcripts down to
  `work_log/digest_<date>.md`. It keeps the user's typed messages and each turn's final
  summary, and skips scratch dirs, ModelBaseline, headless runs, and job-pipeline
  sessions. Scheduled runs are counted in a census line, not excerpted. The task then
  drafts 3-8 bullets to `work_log/candidates_<date>.md`, each citing its session and
  flagging its gaps, and sends a Discord nag.
- **Interview:** user-level skill `~/.claude/skills/work-interview/` ("work interview")
  asks only about the flagged gaps plus one question about non-Claude work, then writes
  `work_log/master_diff_<date>.md`. It edits `master_resume.md` only on "update master".
- **Nothing here is committed.** `work_log/` is gitignored and also carries its own `*`
  `.gitignore`, because transcripts hold CRM and customer data. Only the script and its
  fabricated-fixture tests (`pipeline/test_harvest_work_log.py`) are in the repo.
- **Sources:** this machine plus the worker Mac, via `--remote worker` over the existing
  ssh host (the script is sent on stdin; nothing is installed or written there). Worktree
  sessions are kept on purpose: they're distinct sessions, not copies. Wispr Flow is a
  possible future source, low priority.

## LinkedIn Browser Sweep (on-demand skill)

`linkedin-sweep` (`.claude/skills/linkedin-sweep/SKILL.md`, local-only) drives a logged-in
Claude-in-Chrome session to resolve LinkedIn job-alert emails to real roles, sweep the Jobs
recommendation feed, and run a small tier-title search pack. Tested procedure + constraints:
`pipeline/linkedin_browser_harvest.md` (gitignored). Deliberately NOT part of the scheduled
daily run — it needs Chrome open and connected, so Aneesh triggers it by name ("linkedin
sweep"). It feeds `enrollment_candidates.json` through the same pending-queue rules as Step
1d-2 and never scores, tailors, or clicks anything on LinkedIn. Separately (2026-08-16,
explicitly approved), the LinkedIn alert subscriptions themselves were tier-aligned — 18 daily
email alerts mirroring the scoring tiers — so the email channel Step 1d-2 consumes is now
tuned to the same title set; the live alert list and write mechanics are in the harvest doc.
Open to Work visibility stays recruiters-only; never change it without Aneesh's direct ask.

## Quick Commands
- "Tailor for [JD]" — Full tailoring workflow above
- "Compare [company]" — Show diff between tailored version and master
- "List versions" — Show all tailored versions created so far
- "Prep for [Company] round [N]" — Create round-specific interview prep doc
- "Post-mortem [Company] round [N]" — Walk through post-mortem and update lessons learned
