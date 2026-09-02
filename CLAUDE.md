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
POSITIONING: four signature frameworks, STAR story bank, transferable-parallel template.
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
- **First bullet rule**: Apply the 6-second rule (see Step 2). The first iApts bullet must be the single most compelling, metrics-dense achievement relative to this JD. Choose from: Maven AGI 85% deflection, CES system implementation, Salesforce 25+ automations, 100% case volume scale, 8-person global team build. Which one leads depends entirely on what the JD weights most.
- **Portfolio projects**: `portfolio_projects.md` lists public GitHub projects citable in resumes and cover letters, each with a "cite when" trigger and a resume-ready line. Check it during tailoring; when the JD matches a trigger (AI evaluation, deployment rigor, workflow automation), work the project in — a verifiable public repo is stronger evidence than a claim. Never embellish beyond what that file states. The Friday portfolio routine appends new entries after each build.
- **Keep it honest**: Every claim must be backed by actual experience from the master resume

### 4. Save the Tailored Version
- Save the tailored resume as `tailored/Aneesh_Khan_[Company]_[Role]_data.json` (schema: see `pipeline/pdf_helpers.py` docstring; e.g., `tailored/Aneesh_Khan_Datadog_TAM_data.json`). **The JSON is the single source of truth as of 2026-09-02**: the PDF renders from it and the coverage check reads it. Do not also write a markdown twin; every resume used to be authored twice and every coverage fix applied twice, and the two copies drifted (Cresta, 2026-09-02: 4 fixes as 8 edits, JSON at 11/15 where the markdown read 14/15 on the same phrases). Write a `.md` only if Aneesh asks for one.
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

**OPENER — never lead with a schedule/location accommodation.** Added 2026-08-13 after the Precisely rejection (Technical Support Manager) came back same-day with the letter opening on shifting hours to cover Pacific time. Even when the accommodation is real and easy, putting it in the first sentence means a fast resume-screen reads the gap before it reads any qualification. Make the fit case first; if a JD states a timezone/location requirement Aneesh can meet but doesn't natively satisfy, address it later in the letter (middle paragraph or close) and frame it as a settled fact of how he already works ("My team already spans three time zones; covering Pacific hours is the same muscle, not a new one") rather than a hypothetical adjustment ("Shifting my hours... is a small adjustment"). Not confirmed as the actual cause of that rejection, but the opener structure was wrong on its own terms regardless.

**Structure — vary it.** Not every letter needs three bold-header bullets. Sometimes a strong paragraph, sometimes two items, sometimes no bullets. The template is visible when every letter has the same "Three specific things I'd bring:" structure.

**Never use these:**
- "genuinely excited," "genuinely committed," "genuine [anything]" — drop the qualifier, just say it
- "maps directly to," "directly relevant," "translates directly" — trust the reader to see the connection
- "~30% of my weekly time in cross-functional meetings" as a verbatim line — it appears in too many letters; show the cross-functional work through a specific example instead
- "Here's how my experience maps to the role:" — just make the case

**Close — be specific.** "I'd welcome the chance to discuss how my experience translates. Thank you for your consideration." adds nothing. The close must include at least one sentence specific to this role or company — a real question, an observation about the team structure, a practical note. Keep it short.

**Honesty moments — keep them.** When there's a real technical gap, acknowledge it directly and without apology ("Python is a growing area for me," "I am not a software developer"). This is a distinctive voice feature that makes letters feel real. Don't suppress it.

**Always pair a named gap with a concrete ramp commitment (added 2026-08-20, Aneesh's direct ask).** Naming the gap is half the move; the other half is showing he intends to close it and can. A bare admission leaves the reader to decide how much it costs them. Do NOT write generic filler — "I'm a fast learner," "I pick things up quickly," "eager to grow" are exactly the vague fluff the style guide bans, and they read as padding. The commitment has to be specific enough to be checkable, and ideally starts before he's asked:

- **Name when he'll start, and make it early.** A dated, checkable claim about behavior (he has already begun, or begins before the first conversation) beats any adjective about learning speed. **Do not reuse a fixed sentence for this.** On 2026-09-02 all four letters in one run landed on the identical construction "now rather than after an offer" because this section used to supply that exact phrasing as its example; a mandated move plus a quoted sentence becomes a template across documents, and the per-letter voice gate cannot see it. Vary the construction every time: a start date, a named resource already opened, a first concrete step taken.
- **Re-read what the requirement actually demands, then aim at that.** Requirements are often looser than they look. Framer's bar was "enough to read our code and dig in from day one," which is a *reading* bar, not a writing one; naming that distinction turned the weakest paragraph in the letter into an argument. Check for this before conceding a requirement wholesale.
- **Cite evidence he ramps fast rather than asserting it.** Real precedents from `master_resume.md`: sole integration partner on the Maven AGI deployment with no prior AI-vendor experience at the company; trained 24 Resideo agents to absorb an entire support function in six months; scaled a support org from 1 to 18; taught himself the Claude Agent SDK well enough to run 17+ production automations. One concrete precedent beats three claims.
- **Keep it to two or three sentences, in or beside the gap paragraph.** This is a beat inside the honesty moment, not its own section, and it must never turn into a plea.

Worked example, described rather than quoted (Framer, Engineering Support Lead, 2026-08-20): the letter named the coding gap, committed to starting on Framer's stack before any interview, then re-read the JD's own bar ("enough to read our code and dig in from day one") as a reading bar rather than a writing one and argued that reading a codebase well enough to reproduce and route an issue is clearable. The move is: gap, dated commitment, re-read the requirement, aim at what it actually asks. The sentences that carried it are deliberately not reproduced here; see the bullet above for why.

**Three positive framings to use when relevant (from direct voice interview):**
- *Maven story:* The real achievement isn't the 85% deflection number — it's the feedback loop: customer data flowing back in to auto-audit the knowledge base and feed T1 training. Lead with the loop, land on the number. Most companies skip the spec work and get swept up in vendor promises; Aneesh did the spec work. That's the differentiator.
- *People management:* Don't just say "I lead a team of 8." The stronger claim is: he hires well enough that people management becomes the simplest part of his job — which means his attention goes to the harder operational work. Frame it as an outcome, not a credential.
- *Closing angle:* Aneesh has had two jobs in a decade. He stays where he's constantly building and learning. The honest close isn't "I'm excited about your mission" — it's something that gestures toward the building/learning dynamic and signals he's not a short-tenure risk.

**Opener anti-template log:** `tailored/_cover_openers.md` holds one line per letter (`- [date] [Company]: "first sentence"`). Before writing a new letter, read it — the new opener must not reuse the structure of the last 5 logged openers. After saving the letter, append its first sentence to the log. This catches template convergence that the per-letter self-check misses.

**Final self-check before saving:** (1) Read the first sentence — could it have been written by any LLM for any applicant at this company? If yes, rewrite it. (2) Read the close — is it interchangeable with every other letter? If yes, replace with something specific. (3) Check the opener log for structural repetition.

**Mechanical voice gate (added 2026-09-01):** run
`.venv/bin/python pipeline/check_voice.py --drafted-now <cover.md>` before rendering.
**Never edit a letter that has already been sent** — the file is the record of what the
employer read, and editing it makes the archive disagree with the submission. The script
labels each letter's stage. Note `surfaced` does NOT mean unsent: it means no confirmation
was matched, and CodePath and Cursor both read `surfaced` on 2026-09-01 while already sent.
Only `--drafted-now` (letters the current run authored) is safe to edit without asking. It checks the
contraction ratio, the em-dash cap, and sentence-length uniformity, and exits 1 on failure.
**Contractions are the one that keeps slipping.** Aneesh's own letters run 5–15 contractions
with zero expanded forms; every letter written on 2026-08-28 inverted that, Brown & Brown
worst at 0 against 13 ("I have never", "I did not", "does not make me", "is not a logistics
problem"). No single sentence looks wrong, so it survived six letters undetected — the tell
is only visible in aggregate, which is why it is a script and not a habit. The daily pipeline
runs this plus an `avoid-ai-writing` detect pass at Step 4.5.

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

**`outcomes.csv` canonical schema (15 columns as of 2026-08-27):**
`applied_date,company,title,url,fit_score,jd_coverage_pct,stage,outcome,notes,source_channel,surfaced_date,unmet_hard_reqs,vendor_tool_named_in_jd,hard_req_cap_trigger,furthest_stage`

**`furthest_stage` landed 2026-08-27, and the bug it fixes had been silently destroying data
since the file existed.** `outcome` is a single TERMINAL-state column, so a role that reached an
interview and was then rejected ends up reading `rejected` and the interview is gone. Aneesh said
he was sure he'd had more interviews than the tracker showed; he was right. An audit that day
found **six interview-stage events, of which only two appeared in `outcome`** — the other four
survived only as free text in `notes` and had to be recovered by regex. Interview rate was
therefore uncomputable from the schema, which meant the pipeline was systematically understating
its own conversion. This is a strictly worse failure than the `jd_coverage_pct` problem below:
that metric merely has no variance, this one erased its own history.

`furthest_stage` records the furthest point a role ever reached and **only ever moves right**.
Vocabulary, weakest to strongest, in `FURTHEST_STAGES` (`repair_outcomes.py`):
`applied` · `assessment` · `interview` · `onsite` · `offer`.

**Empty means NOT RECORDED, not "never interviewed"** — the same three-state discipline as
`hard_req_cap_trigger`. The 233 rows that predate the column stay blank on purpose. Do NOT
backfill them to "no interview": "nobody checked" and "checked, never interviewed" are different
facts, and conflating them is precisely what made `outcome` useless here. Populate it going
forward whenever a stage is confirmed, and set it alongside any `mark_outcome.py` run that records
an interview, assessment, or offer.

Columns 11–13 landed 2026-08-01 from the conversion audit (SESSION_STATE 2026-08-01):

- **`surfaced_date`** — when the pipeline first surfaced the role, written once by
  `update_tracking.py` and never updated. It exists because `applied_date` meant two different
  things depending on stage, and `mark_applied.py` overwrote it on promotion, destroying the only
  record of how long a role sat unsent. Backfilled from `seen_jobs.json → first_seen_date` by
  `backfill_surfaced_date.py` (147 of 168 rows recovered; the 21 blanks are confirmation-backfill
  rows the poller never saw, left blank rather than guessed). `age_report.py` reads this column.
- **`unmet_hard_reqs`** — count of JD hard requirements that cannot be honestly claimed. This is
  the intended replacement for `jd_coverage_pct` as a readiness signal. Populate it at Step 6
  from the genuine gaps already identified during tailoring.
- **`vendor_tool_named_in_jd`** — the incumbent AI/support tool the JD names, when it names one
  (`Intercom/Fin`, `Forethought AI`, `Zendesk`). Blank when the JD names none. Recorded to test
  whether vendor mismatch is a recurring rejection cause; at n=2 it is a hypothesis, not a finding.

**`hard_req_cap_trigger`** landed 2026-08-21, from a finding by `audit_scores.py`. The
HARD-REQUIREMENT TIER CAP demotes a role to light tier on a stated years-minimum in a function
Aneesh has zero years in, or a requirement the JD calls non-negotiable. `unmet_hard_reqs` cannot
express that — it counts *every* disclosed gap, and most are soft ("no fintech domain") — so
nothing could tell a correctly-capped row from a missed one, and 10 rows were stuck as an
unresolved review queue. Vanta (2026-08-21) is the clean case: 2 unmet hard reqs *and* full
tailoring, entirely correct, because that JD states no years minimum at all.

Three states, and the distinction is load-bearing — `outcome=null` already taught this tracker
what happens when one value means both "no" and "never recorded":

| Value | Meaning |
|-------|---------|
| `""` | not recorded — every row before 2026-08-21, or a run that skipped the check |
| `none` | checked; nothing triggers the cap |
| *verbatim text* | the triggering requirement, quoted (`5+ years in Data Governance or GTM Systems`) |

**Empty is not "no cap."** Populate it at Step 6 whenever you set `unmet_hard_reqs`; write `none`
rather than leaving it blank, because blank is what an unrecorded row looks like. The 219
pre-existing rows stay empty (backfilling means re-reading 219 JDs) and `audit_scores.py` falls
back to reading their notes, labelling that inference as a guess.

**Stage vocabulary:** `surfaced` (tailored, not confirmed sent), `applied`, `rejected`, `closed`,
`expired` (retired by `age_report.py` after 45 days with no confirmation), `tailored` (legacy).

**2026-07-28 is the outcome-data epoch. Do not audit, reconcile, or reason about `applied` rows
that predate it.** The Gmail `+jobs` forwarding filter (Step 0.5) went live 2026-07-28; before
that date nothing could confirm a send, so `stage=applied` on an older row is self-reported and
often just means "tailored." Established the hard way 2026-08-20: Alston Construction sat at
`stage=applied` since 07-20 with `applied_date == first_seen_date == the tailoring date`, and
Aneesh confirmed he had never submitted it. Other pre-epoch rows are likely wrong the same way.

**Standing decision (2026-08-20, Aneesh's call): those historical gaps are out of scope. Do not
spend a run trying to reconcile them, do not surface them in digests, and do not propose bulk
audits of them.** The data is unfalsifiable, so the work has no terminal state. Treat 2026-07-28
as the start of trustworthy outcome data instead: conversion rates, send rates, channel
effectiveness, and any claim about what happened to an application should be computed from
`surfaced_date >= 2026-07-28` and say so. A pre-epoch row is fine to leave sitting in whatever
state it is in; correct one only when Aneesh raises that specific role.

`source_channel` is `pipeline`, `user_surfaced`, `referral`, or `linkedin`. It exists because a
CodeRabbit application submitted through an employee referral was indistinguishable from a cold
ATS apply, and those convert at very different rates. Vocabulary lives in `KNOWN_CHANNELS`
(`repair_outcomes.py`); add there first or the migration will treat the row as drifted.

**This schema is duplicated in two places on purpose** (`OUTCOMES_HEADER` in
`update_tracking.py`, `CANONICAL` in `repair_outcomes.py`). Change both together, then run
`.venv/bin/python pipeline/repair_outcomes.py --apply` to migrate. Schema drift here is not
cosmetic: `mark_applied.py` silently skips any row whose column count differs from the header, and
a 2026-07-28 audit found 32% of the file invisible to promotion for exactly that reason.

**`jd_coverage_pct` is a pass/fail gate, not a ranking signal. Never sort, compare, or
prioritize roles by it.** It measures whether the resume mirrors the posting's language, not
whether Aneesh clears the hiring manager's bar. The Vanta AI Optimization Specialist role scored
~111 with 15/15 coverage and was rejected at the recruiter screen over unlisted Intercom/Fin
experience.

The 2026-08-01 audit established that this is a **variance** problem, not a small-sample problem,
which is a stronger claim than the earlier caution made: **22 of 26 applied rows with coverage
recorded (85%) sit at >=93%, and 15 of 26 (58%) are exactly 100%.** The metric is
range-restricted by construction, because Step 6 targets >=80% and the second-pass rule pushes it
higher. A number the process optimizes to a target cannot explain variation in outcomes at ANY
sample size, so no amount of additional outcome data will rehabilitate it. Vanta at 15/15 was not
an anomaly needing explanation; it was the modal value.

Use it exactly one way: as a gate at 80% during tailoring. For readiness, use `unmet_hard_reqs`.

Title matching is config-driven as of 2026-07-09: `poll_ats.py` builds its matcher at runtime from `watchlist_companies.json → _title_scoring_tiers` + `_poller_config` (stemmed-token matching, so word-form and word-order variants match automatically). To teach the poller a new title, edit the JSON; `poll_ats.py` carries no title lists, endpoints, or scoring numbers of its own. Whole TIERS are also discovered dynamically: any `_title_scoring_tiers` key starting with `tier` (except the specially-handled `tier2b_ai_wildcard`) is loaded automatically. That was a hardcoded 4-tuple until 2026-07-28, which silently made the newly added `tier2c_tooling_systems` match nothing despite this paragraph promising otherwise. After ANY hand edit to `watchlist_companies.json` or `enrollment_candidates.json`, run `.venv/bin/python pipeline/validate_config.py` (syntax + schema check). The daily run also runs it at Step 1-pre, and `poll_ats.py` refuses to poll against a malformed watchlist.

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

1. **Count the vertical bonus ONCE.** A watchlist company's `score_bonus` in
   `watchlist_companies.json` IS that company's complete vertical bonus — do **not** add a
   separate generic "+20 AI/ML" or "+20 tooling" on top. Read `bonus_reason` to see which
   vertical it encodes. As of 2026-07-29 there are three cases:
   - `20` + "AI/ML platform" — AI-native company (55 companies)
   - `20` + "Developer/infra tooling" — the company's product is a tool: devtools, dev infra,
     observability, security tooling, data/API platforms (19 companies). Added after Aneesh
     named tool creation and maintenance as his primary interest, AI co-equal secondary.
   - `30` + both — genuinely both, already pre-clamped at the +30 cap (9 companies)

   For a non-watchlist company with no config bonus: +20 once if AI-native, +20 once if a
   tooling company, +30 if clearly both. Never a config bonus and a manual one together.

   **The tooling list is curated by hand and must stay that way.** A keyword pass over the
   `reason` text was tried on 2026-07-28 and produced ~40% false positives in both directions
   ("deployment" matched every AI-application company; "iam" substring-matched inside "Miami")
   while missing LaunchDarkly, 1Password, Vanta, Expel, LogicGate, and Chainguard entirely.
   To classify a new company, edit its `score_bonus`/`bonus_reason` directly.

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
   bonus, not fit") and use judgment on the tier rather than deferring to the number. Documented
   2026-08-20 after Framer's Engineering Support Lead scored 94 against GitLab's 98 while
   matching its JD responsibilities more closely; 7 of those points were watchlist, salary
   disclosure, and source quality rather than anything about the work.

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
Added 2026-07-28. Aneesh's stated PRIMARY interest is building and maintaining tools, with AI
co-equal secondary. Backed by real resume content: 25+ Salesforce Flow automations, Service Cloud
admin, the Maven AGI deployment, and the CES/QA tooling he built.
- Business Systems Manager / Analyst · Support Systems Manager · Systems Manager
- Platform Operations Manager · Internal Tools Manager · Tooling Manager · Automation Manager
- Applications Manager family (Business / Enterprise / IT Applications Manager)
- Revenue Operations Manager

**Narrow platform-administration variants are DEMOTED as of 2026-08-28.** The governing rule is
Aneesh's own: *"it's the narrow admin work I don't want."* **The line is ALTITUDE, not domain:**
own a function (build the tooling, run adoption, decide what the system does) versus be someone's
platform administrator (configure the tool, work the queue, hold the cert). Use that test on
titles the list has not seen yet; full statement lives in the career-narrative skill's
Target-Role Criteria. Analyst level is fine and this is not a seniority rule — he applied to
Wiz's "Sr. Business Systems Analyst" (106) unprompted; the *administrator* rung is the one he
declines. A "Manager" in the title does not rescue a role either: check the responsibilities.

The demoted titles stay in the tier2c list so they still match and surface, but `_poller_config →
function_mismatch_titles` now demotes them to digest FYI lines: `GTM Systems`, `Go-to-Market`,
`Revenue Systems`, `Sales Systems`, `Salesforce Administrator`, `Salesforce Business Systems`,
`CRM Administrator`, `Applications Administrator`.
Aneesh prompted the review by reading the Baseten GTM Systems Manager JD and saying it looked
very different from what he does. He was right, and his own history said so: **every
GTM-qualified or Salesforce-admin-titled systems role the pipeline ever surfaced went unsent
(0 of 5), and every systems role he did send lacked that qualifier (3 of 3)** — including
CrowdStrike's "Sr. Business Systems Analyst, Go-to-Market" at 116, the second-highest score in
the tracker. Four of the five unsent ones got full tailoring *with a cover letter*, so this was
burning the pipeline's most expensive artifact about once a week.

Two things that make this a real finding rather than a small sample: the discriminator is NOT
the hard-requirement cap (Wiz was capped to light tier and he applied anyway; CrowdStrike
carried `hard_req_cap_trigger: none` at priority tier and he did not), and the original tier2c
note assumed **the salary floor would screen the Salesforce-admin end out on its own**, which
fails at AI-native companies paying $160K–$200K for that work. The distinction underneath:
Service Cloud and Sales Cloud are the same platform and different jobs. Verified against the
live matcher (5/5 demoted, 0/3 sent roles affected, 0/7 controls affected); reverting is a
one-line delete per pattern.

**Tier 4 — Weak stretch (light tailoring only, title match +8):**
- Renewal Manager / Partner Success Manager
- Onboarding Manager / Customer Onboarding
- Product Customer Success

**Stretch lane (added 2026-08-30, Aneesh's explicit risk-accepted ask):** Forward Deployed
Engineer and Solutions Engineer postings that fail the normal bar still get a bounded
conditional review; spec is `daily_task_prompt.md` Step 3.5 (max 2 JD reads/run, four
gates, own digest section, logged even at zero). Visibility only: the tiers above and the
2026-07-09 FDE demotion stand. He is separately working a qualification pathway toward
both titles.

## Supplemental WebSearch Sources (Atlanta + Startup Discovery)

The `_websearch_sources` block in `pipeline/watchlist_companies.json` defines additional sources to run each daily pipeline pass. These catch companies NOT on the ATS watchlist — Atlanta startups plus, as of 2026-06-25, broader ATS-host and AI-vertical discovery.

**These sources are ROTATED as of 2026-08-23, not run exhaustively.** Run
`.venv/bin/python pipeline/websearch_rotation.py` after ATS board polling: it selects the
`rotation_per_run` daily sources with the oldest `last_run` and prints their queries, then
`--mark` records the ones that actually ran. Full spec and rationale:
`pipeline/daily_task_prompt.md` Step 1c. The short version: 16 sources a day competed with JD
retrieval and kept getting skipped wholesale (zero ran on 2026-08-21, four on 2026-08-23), and
these sources discover *companies* rather than perishable reqs, so a ~3-day cycle costs almost
nothing. The JSON block is still the source of truth for the queries themselves — don't
hardcode a query count here (it drifts). As of 2026-06-25 the active set is:
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

## User-Surfaced Finds Protocol (LinkedIn/Indeed alerts, word of mouth)

When Aneesh mentions a job or company he found outside the pipeline, do all four steps:
1. **Assess** — find the posting at its source ATS (not the aggregator), score it, give an
   honest fit verdict. Tailor only if he asks.
2. **Diagnose the miss** — determine specifically why the pipeline didn't surface it
   (off-watchlist? ATS host uncovered? query term gap? title filter gap?).
3. **Patch the gap** — fix the config/query/filter so that *class* of miss can't recur,
   and enroll the company on the watchlist if it has a pollable board.
4. **Log the tally** — record the miss + root cause in memory (`project_job_pipeline.md`,
   "discovery miss tally"). **Standing decision (2026-07-02): a third WitnessAI-class miss
   (good company, pollable board, invisible to discovery) triggers building the ATS
   directory-harvest layer** — bulk-collect Ashby/Greenhouse slugs, auto-vet
   programmatically (board live + ≥1 US fit-title), auto-enroll at low priority, with
   automatic dead-board pruning. Daily poll cost stays flat (poller pre-filters to a fixed
   top-25); the build is an engineering session, not a heavier daily process.

## Assisted Apply (on-demand skill)

`assisted-apply` (`.claude/skills/assisted-apply/SKILL.md`, local-only) fills a job
application form in the browser up to but never including submit. **Explicit invocation
only** — "assisted apply", "help me apply to X", "fill out this application". Never
triggered by the daily pipeline, never inferred from a role being tailored.

Built 2026-08-28 after a Brown & Brown Workday form was abandoned mid-way. Aimed at the
high-effort ATSes (Workday, Paylocity, Taleo, iCIMS) that make him retype his whole work
history after an upload, which is a plausible contributor to the 38% send rate and
31-day median at `stage=surfaced`.

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
