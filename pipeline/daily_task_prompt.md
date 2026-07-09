# Daily Job Pipeline — Canonical Routine (single source of truth)

**This file is the ONE executable spec for the daily pipeline.** The scheduled task's
SKILL.md (`~/.claude/scheduled-tasks/daily-job-pipeline/SKILL.md`) is a thin loader that
reads and executes this file — it must never carry its own copy of any step, threshold,
or query list. Scoring numbers live in `watchlist_companies.json → _scoring_config` and
`CLAUDE.md`; when they conflict, the JSON wins. (History: three drifting copies of this
routine were the #1 cause of stalled runs — see memory `project_job_pipeline.md`.)

**Token budget:** the run must fit one context window.
- ATS polling is Python (`poll_ats.py`) — read its small output, never WebFetch boards inline
- PDFs via `render_pdf.py` + JSON data files — never copy/edit `generate_pdf.py`
- Coverage checks via `check_coverage.py` — never hand-rolled bash loops
- Tracking updates via `update_tracking.py` — never hand-edit `seen_jobs.json`
- Read `master_resume.md` ONCE, reuse for all tailorings
- WebSearch limited to the active `_websearch_sources` entries + recovery searches

**Permission-safety rules (violating these hangs the autonomous run):**
- NEVER use `python3 -c "..."` inline scripts
- NEVER use bash arrays or shell control flow (`for`/`while`/`if`, `$(...)` loops)
- NEVER chain multiple commands in one Bash call with `;`, `&&`, `||`, `|`, or subshells
  `(...)` — even "safe" building blocks like `ls | grep` or `ls; echo; ls | tail`. The
  permission matcher approves single commands against durable wildcard entries
  (`Bash(ls:*)`, `Bash(grep:*)`) but treats a chained/piped command as one unmatched shape
  needing its own literal-string approval — and that literal string usually embeds
  something that changes daily (a date, a filename), so it can never be pre-approved for
  future runs even after being approved once. For existence/content checks on a single
  file (e.g. "does `run_{today}.json` exist and what does it contain"), use the **Read
  tool**, not Bash — Read isn't gated by this at all, and reading a nonexistent file just
  returns a clean error instead of hanging. If you need real multi-step shell logic, put it
  in a `pipeline/_taskname.py` script and run that one plain command instead of chaining.
- Temp scripts go to `pipeline/_taskname.py` (the `_*.py` pattern is allow-listed), NOT `/tmp/`
- Use `Read`/`Write` tools for small file edits; use the helper scripts for big/structured ones

## Step 0: Duplicate-trigger guard, pre-run notes, style guide

1. **Duplicate-trigger guard.** The scheduler has double-fired on the same day before
   (2026-04-14, 2026-04-17, 2026-06-10, 2026-07-02). Use the **Read tool** directly on
   `pipeline/jobs/run_{today}.json` (do not check existence via a chained/piped Bash
   command — see the permission-safety rule above). If the Read errors because the file
   doesn't exist, there's no duplicate; proceed. If it returns content and that content
   records a completed run (has stats and an email draft ID): verify the Gmail draft still
   exists, log one line to `pipeline/SESSION_STATE.md` ("duplicate trigger [time], no
   action"), and **STOP — do not re-poll, re-tailor, re-draft, or touch tracking files.**
   A second run on the same day double-counts tracking and creates duplicate digest drafts.
2. Use the **Read tool** directly on `pipeline/NEXT_RUN_NOTES.md` (same reasoning: no
   chained Bash check). If it errors because the file doesn't exist, proceed normally. If
   it returns content: incorporate it, delete the file, then proceed.
3. **Read `/Users/aneesh/.claude/projects/-Users-aneesh/memory/user_writing_style.md` in
   full, every run, before any drafting.** It governs all resume, cover letter, and digest
   prose, and it changes over time. Standing hard rule from it: prefer colons/semicolons
   over em-dashes; max 2 em-dashes per document. Verify before rendering any PDF with
   `grep -c '—' <file>` (allow-listed) and rewrite if over.

## Step 1: ATS polling

Check whether `pipeline/jobs/ats_hits_{today}.json` already exists. If yes, read it and
continue. If not:

```bash
.venv/bin/python pipeline/poll_ats.py
```

Then read the output. It contains: top-25 `matched` (pre-scored, deduped, diversity-capped
at 2/company, and **balanced**: ≥10 slots each reserved for sub-500 companies and for
larger/unknown-size companies, remainder by score), up to 20 `borderline` titles for
semantic review, `reseen_keys`, `errors`, `stats`, and `capped_companies`. Entries flagged `new_req_of_applied_title: true` are
reposts of a title Aneesh already applied to under a new requisition — treat as new but
mention the prior application in the digest.

### 1b. Board 404 alerts

For each company in the `errors` array with a 404:
- First-time 404 (no `board_status` in `watchlist_companies.json`): log it in
  `run_[date].json → pipeline_notes`, set `board_status: "404_seen_[date]"`, move on.
- `board_status: "404_confirmed"`: only re-check if its `recheck_after` date is today or
  past (or missing). Run one recovery WebSearch
  (`"[Company]" jobs site:greenhouse.io OR site:lever.co OR site:ashbyhq.com`), log the
  result, then set `recheck_after` 7 days out. **Do not re-investigate confirmed-dead
  boards every run** — that burned time on Moveworks/Forethought for a week straight.
- If a live board is found: fix the slug/ats in the watchlist and poll just that company.

### 1c. Supplemental WebSearch (discovery beyond the watchlist)

Read `pipeline/watchlist_companies.json → _websearch_sources.sources` and run every entry
whose `status` is `"active"`. That block is the single source of truth — never hardcode
query lists anywhere else. Each entry's `notes` explain what it catches and how to score
hits.

Known access quirks (do not retry once failed): Wellfound/Glassdoor/Remoterocketship 403
on WebFetch — snippets only. Ashby/Workday/NICE careers pages are JS-rendered — use API
endpoints. LinkedIn redirects to login — snippets only.

### 1d. Discovery feeders + enrollment queue

`pipeline/enrollment_candidates.json` is the standing queue that stops off-watchlist
sightings from dead-ending. Run the feeders:
- `.venv/bin/python pipeline/poll_remotive.py` — daily; appends name-only leads
- `.venv/bin/python pipeline/harvest_hn_hiring.py` — only on/after the 1st of the month
- Board dorks (from 1c) — append any UNFAMILIAR company to `pending`

Process every `pending` entry:
1. `needs_ats_resolution: true` → resolve the ATS
   (`site:greenhouse.io OR site:jobs.ashbyhq.com OR site:jobs.lever.co <company>`); no
   board found → reject with reason.
2. Verify the board is live (direct API check; `verify_workday.py` for Workday) with
   US-reachable fit-space roles. Europe/APAC-only → reject.
3. Pass → add full watchlist entry **including `headcount_band`** (verify via web, don't
   guess), `enrolled_date`, `enrolled_via`, any `score_bonus`; move to `enrolled`.
   Fail → move to `rejected` with a one-line reason.
4. Bias toward sub-500 companies — this layer exists to catch the long tail.

ATS providers the poller speaks: Greenhouse, Ashby, Lever, Workday, SmartRecruiters
(case-sensitive slug). Workable is unsupported — note Workable-only companies in the digest.

### 1e. Housekeeping: headcount_band backfill (max 3/run)

Most watchlist companies are missing `headcount_band`, which makes the small-company bonus
inert for them (both in the poller pre-score and in full scoring). Each run, pick up to 3
watchlist companies without a band, verify headcount via one WebSearch each (LinkedIn
"company size" snippet is fine), and set `headcount_band` (`1-50`, `51-200`, `201-500`,
`501-2000`, `2000+`). Note them in `run_[date].json → pipeline_notes`. Stop once all
companies have bands.

## Step 2: Filter and score

Combine ATS hits + promoted borderline titles + WebSearch finds.

### 2a. Dedup (WebSearch-sourced candidates only — ATS hits are already deduped)

`dedup_key` = `{ats_or_company_slug}::{kebab-case-title-slug}` (match `poll_ats.py`
`slugify`: lowercase, non-alphanumeric stripped, spaces→hyphens). Skip candidates whose
key is in `seen_jobs.json` with `first_seen_date` within 30 days, or whose exact URL is in
`seen_urls.json`.

### 2b. Hard filters

Eliminate: crypto/web3/blockchain; VP/Head-of/Staff/Principal; clearance-required;
postings >21 days old; salary below the $100K floor.

**Salary comparison basis (deterministic, never eyeball):** range → compare the
**midpoint**; single figure → that figure; OTE-only → estimate base (80% for
variable/sales roles, 100% otherwise) then midpoint; no salary listed → do NOT filter,
treat as neutral.

**Company cap:** companies with ≥3 entries where `applied=true AND outcome=null` need a
score >110 to surface. Queued/unapplied roles do NOT count. Trust the poller's
`capped_companies` output for ATS hits.

### 2c. Score (absolute points — canonical rubric)

- Title match: T1 +30 / T2 +22 / T3 +15 / T4 +8 (tiers in `_title_scoring_tiers`)
- Keyword overlap with master resume: up to +30
- Location: Atlanta in-office +20 / hybrid +18 / remote US +16 / NYC-NJ +12 / other 0
- Salary (midpoint basis): ≥$140K +10 / ≥$120K +8 / ≥$100K or unlisted +5 / below 0
- Source quality: Greenhouse·Lever +10 / Ashby·BuiltIn +8 / aggregator +5; −3 if >14 days old
- Freshness: ≤2 days +10 / ≤7 days +2

**Company-level bonuses — capped at +30 combined (Scoring Guardrails in CLAUDE.md):**
- AI/ML: a company's config `score_bonus` IS its AI bonus — count once, never stack a
  generic +20 on top. Non-watchlist AI-native company: +20 once.
- Watchlist +10 · Atlanta-startup +20 · Atlanta-enterprise +10 · IoT +15
- Small-company (requires `headcount_band`): ≤200 +15 / 201-500 +8 / absent 0 (never guess)
- **Passion-domain +10** (`_scoring_config → passion_domains`: electrification/EV, health
  tech, agriculture/gardening/food). Apply SEMANTICALLY to the company's mission/product,
  once per job even if multiple domains hit; ignore keyword accidents ("patient rollout").
  Poller entries may carry a `passion_domain` tag as a hint — confirm it, don't trust it.

**Penalties (small — reach is fine):** title gap −5 (named IC function Aneesh never held
by exact title, once per job); seniority mismatch −5 (JD explicitly requires 6+ years in
that specific function AND no prior title in it). Max −10 combined. Do not penalize reach
beyond these two.

**Diversity cap:** surface ≤2 roles per company per run; fully tailor only the single
best-scoring one — additional same-company roles are "also live (FYI)" digest lines.

**Pick the top 3-4 jobs.** Tiers (thresholds in `_scoring_config`): 110+ priority/full ·
88–109 full · 78–87 light (summary rewrite + skills reorder only, no cover letter) ·
<78 skip. If fewer than 3 clear 78, send what you have — never pad.

**Capture near-misses (do NOT tailor):** (A) score near-miss — passed every hard filter
but scored <78 (no lower bound); (B) salary near-miss — passed everything except the
salary floor, midpoint $90K–$100K. Collect title, company, location, salary, score, URL
for the digest. Stale/capped/crypto/VP roles are NOT near-misses.

**Read `master_resume.md` NOW** — once, reused for all tailorings below.

## Step 3: Fetch full JDs

WebFetch each top job's apply URL. On failure (403/JS), WebSearch for a cached or mirrored
copy (BuiltIn, ZipRecruiter, Greenhouse cache). If the JD is unreachable two runs in a
row, drop it to the near-miss list with a note rather than stalling.

**If the top-scored role at a company fails the JD read** (real skill mismatch — e.g. a
Forward Deployed Engineer listing that turns out to require production coding), don't just
drop the company. Pull that company's other live postings (direct ATS API call, same
pattern as `pipeline/verify_workday.py`'s target-title scan) and check whether a
lower-pre-scored role there is actually the better fit. This is how Confido's Implementation
Manager got found on 2026-07-09 — it wasn't in the poller's top-25 at all because the
diversity cap only kept the top 2 pre-scored roles (CSM + FDE) per company, and Implementation
Manager's raw pre-score ranked below both. Only worth the extra API call when the top pick's
JD genuinely disqualifies it — not a step to run for every company by default.

## Step 4: Tailor resumes and cover letters

Follow the CLAUDE.md tailoring workflow for each top job (JD analysis → top-15 phrases →
ATS optimization → tailor → verify). Per job:

1. Tailored resume markdown → `tailored/Aneesh_Khan_[Company]_[Role].md`
2. Resume JSON → `tailored/..._data.json` (schema: `pipeline/pdf_helpers.py` docstring)
3. `.venv/bin/python pipeline/render_pdf.py resume <data.json> <out.pdf>`
4. **Coverage check:** write the JD's top-15 phrases to
   `tailored/Aneesh_Khan_[Company]_[Role]_phrases.json`, then
   `.venv/bin/python pipeline/check_coverage.py <resume.md> <phrases.json>`
   Target ≥80% (12/15). Below that: apply the second-pass rule (CLAUDE.md Step 6), revise,
   re-run. Never fabricate to close a gap — flag genuine gaps honestly.
5. Cover letter (full-tailoring tier only) → `_cover.md` + `_cover_data.json` +
   `.venv/bin/python pipeline/render_pdf.py cover <cover_data.json> <out.pdf>`
   - Apply ALL voice rules from CLAUDE.md Step 8 (opener, structure variety, banned
     phrases, specific close, honesty moments)
   - **Opener anti-template check:** read `tailored/_cover_openers.md` (create if missing);
     the new letter's first sentence must not reuse the structure of the last 5 openers
     logged there. After writing the letter, append one line:
     `- [date] [Company]: "first sentence"`
6. **Tailoring diff** (for the digest): summary changes, bullet reorders/drops, terminology
   swaps, skills reorder, coverage N/15; cover letter hook + achievements featured +
   JD language mirrored. Bullets, no prose.

7. **Style check (before rendering each PDF):** the document must comply with the writing
   style guide read in Step 0. Minimum mechanical check: `grep -c '—' <file>` must be ≤2;
   then apply the guide's Gut Check ("does this sound like a real person wrote it?").

**NEVER fabricate experience, certifications, or skills.**

## Step 5: Email digest

Gmail MCP `create_draft` (drafts only — no send, no attachments) to **aneeshk10@gmail.com**:

- Subject: `Daily Job Matches — [date] ([N] jobs)`
- Top note: "Open this draft, attach the PDFs listed at the bottom, and send."
- HTML table: title, company, location, salary, score, JD coverage %, apply link
- Per-job tailoring diff below the table
- "Also live (FYI)" lines for same-company extras; near-misses section at the bottom
  (one line each with reason tag, e.g. "scored 74" / "pay $92K midpoint"); omit if none
- Note any ATS errors, capped companies, enrollments/rejections, and skill gaps observed

## Step 6: Update tracking

1. Write `pipeline/jobs/track_[date].json`:
   ```json
   {"run_date": "YYYY-MM-DD", "jobs": [{"dedup_key": "...", "company": "...",
     "title": "...", "url": "...", "score": 0, "jd_coverage_pct": 0, "notes": ""}]}
   ```
   (surfaced top 3-4 only, not near-misses)
2. Run:
   ```bash
   .venv/bin/python pipeline/update_tracking.py pipeline/jobs/track_[date].json --touch-reseen pipeline/jobs/ats_hits_[date].json
   ```
   This updates `seen_jobs.json`, `seen_urls.json`, and `pipeline/outcomes.csv`
   (canonical header: `applied_date,company,title,url,fit_score,jd_coverage_pct,stage,outcome,notes`)
   atomically. **Never hand-edit `seen_jobs.json`** — hand edits corrupted it on
   2026-06-30. NOTE: `pipeline/jobs/outcomes.csv` is a stale orphan — never write to it.
3. Write `pipeline/jobs/jobs_[date].json` (full structured records) and
   `pipeline/jobs/run_[date].json` (run metadata: searches run, stats, capped companies,
   pipeline_notes, near_misses array, email draft ID).
4. Update `pipeline/SESSION_STATE.md`: today's output, near-misses, housekeeping, action
   queue. Session state never goes in `CLAUDE.md`.

## Step 7: Sync the public repo

Framework lives in the public repo `neeshykha/claude-resume-pipeline`. Personal data
(`master_resume.md`, `tailored/`, `pipeline/jobs/`, `outcomes.csv`, `SESSION_STATE.md`) is
gitignored — never `git add -f`, never restore run state into `CLAUDE.md`.

```bash
git add -A
git diff --cached --quiet || git commit -m "pipeline: daily run $(date +%F)"
git push
```

If push is rejected: `git pull --rebase` once, push again; still failing → note in digest
and move on. Never force-push.

## Important rules

- NEVER fabricate experience, certifications, or skills
- NEVER modify `master_resume.md` or `generate_pdf.py`
- Zero matches → brief email: "No strong matches today"
- Watchlist companies: auto-surface CSM/TAM/Solutions roles even below threshold
- Unknown posting date → assume ≤7 days for direct ATS sources; skeptical for aggregators
- NEVER WebFetch ATS boards inline — always `poll_ats.py`
