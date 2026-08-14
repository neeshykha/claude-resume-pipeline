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
- Application-confirmation promotions via `mark_applied.py` (Step 0.5) — never hand-edit
  `outcomes.csv`'s `stage`/`applied_date` columns
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

**Placeholder resolution (do this first, every run).** This file is published in a PUBLIC repo,
so mail-routing details appear as `{{TOKEN}}` placeholders rather than literal values. Read
`pipeline/local_config.json` (gitignored) once at the start of the run and substitute
`{{APPLY_ACCOUNT}}`, `{{CONFIRM_ALIAS}}`, `{{DIGEST_RECIPIENT}}`, and
`{{CONFIRMATIONS_LABEL_ID}}` wherever they appear below. **Never write a resolved value back
into this file or any other tracked file.** If `local_config.json` is missing, STOP and send a
brief digest saying so rather than guessing an address.

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
4. **Read `.claude/skills/career-narrative/SKILL.md` in full, every run, before any
   drafting.** It is the source of truth for Aneesh's POSITIONING: the four signature
   frameworks, STAR story bank, transferable-parallel template, and material style rules.
   Precedence: the style guide (item 3) + CLAUDE.md voice rules govern FORM; the career
   narrative governs SUBSTANCE; `master_resume.md` remains the only source of factual
   claims. Step 4 says how to apply it per document.

## Step 0.5: Application confirmation sync (Gmail `+jobs` alias)

**Added 2026-07-24, closes a real gap found the hard way:** on 2026-07-23 the pipeline
skipped a genuinely fresh Assembled req on the mistaken assumption that an earlier
`stage=surfaced` row in `outcomes.csv` meant Aneesh had actually applied. It didn't —
`stage=surfaced` only ever meant "tailored and drafted," never "confirmed sent," because
Gmail MCP access here is `create_draft`-only. This step closes that gap going forward.

Aneesh applies to jobs using `{{APPLY_ACCOUNT}}` (his system of record). Filters
there forward application-confirmation emails to `{{CONFIRM_ALIAS}}`, which lands
in this pipeline's connected inbox, searchable and untouched by the rest of his mail. A
filter on the receiving side labels those messages `JobConfirmations`.
**Set up 2026-07-28, expanded 2026-08-02, and re-verified in-browser 2026-08-03 (see
SESSION_STATE, "GMAIL OUTCOME-CAPTURE VERIFIED"); this step is live, and a run that
returns zero results now means no new confirmations, not a missing filter.**

**The sending side is THREE overlapping filters, not one — do not "clean up" the older two.**
Alongside the main 15-domain filter (`successfactors.com` and `taleo.net` added 2026-08-09) sit
two older filters that match on subject lines
("thank you for applying", "your application", ...). They look redundant; they are not.
Confirmations sent from company-owned addresses rather than ATS domains reach the alias
only through the subject match: Zocdoc (`careers@`, 2026-08-02) and Datadog
(`no-reply@datadoghq.com`, 2026-08-07) both arrived that way — 2 of the first 8 captures.
Deleting the subject filters would silently drop that class of confirmation.

1. Search Gmail for
   `deliveredto:{{CONFIRM_ALIAS}} -from:linkedin.com newer_than:3d` (the 3-day window
   gives safe overlap across runs; already-promoted rows won't match again since matching
   only looks at `stage=surfaced` rows).

   **The `-from:linkedin.com` exclusion is load-bearing.** LinkedIn job alerts are forwarded
   to this same alias on purpose (one verified forwarding address instead of two) and are
   consumed by Step 1d-2 as company discovery. Without the exclusion they would flow into
   this step's confirmation matcher, which is looking for "did he apply" evidence and would
   find dozens of roles he has never applied to.

   **Use `deliveredto:`, not `to:`.** Gmail forwarding preserves the original `To:` header,
   so a forwarded confirmation still reads `to:{{APPLY_ACCOUNT}}` and the old
   `to:{{CONFIRM_ALIAS}}` query silently returns nothing. `deliveredto:` was verified
   working against this inbox on 2026-07-28.

   **Do NOT fall back to `label:{{CONFIRMATIONS_LABEL_ID}}` on its own.** Verified 2026-07-30:
   the `JobConfirmations` filter also matches forwarded LinkedIn job alerts, so every LinkedIn
   email currently carries BOTH the JobLeads and JobConfirmations labels. A label-only query
   would pull ~20 job alerts a day into the confirmation matcher, which is looking for evidence
   that Aneesh applied. If `deliveredto:` ever breaks, the safe fallback is
   `label:{{CONFIRMATIONS_LABEL_ID}} -from:linkedin.com`. The `-from:linkedin.com` clause is
   what keeps the two streams apart, whichever selector is used.
2. For each result, read the sender/subject/body to identify the company and, if stated, the
   specific requisition URL. **Always try to extract the URL from the email body first** —
   confirmation emails from Greenhouse/Ashby/Lever/Workday usually restate the job link or a
   requisition ID. Only fall back to company-name-only matching when the email genuinely
   doesn't say which requisition it confirms.
3. Write a small `pipeline/jobs/confirmations_[date].json`:
   ```json
   {"confirmations": [{"url": "https://...", "company": "...", "applied_date": "2026-MM-DD"}]}
   ```
   (`url` optional if truly not stated; `applied_date` = the date the confirmation email was
   received, not today's date, if they differ.)
4. Run `.venv/bin/python pipeline/mark_applied.py pipeline/jobs/confirmations_[date].json`.
   It matches by URL first, falls back to company name only among still-`surfaced` rows, and
   **skips and reports (never guesses) any company name that matches more than one surfaced
   row** — read its stdout output and resolve ambiguous ones by hand only if the email body
   gives enough detail to disambiguate confidently; otherwise leave them surfaced.
5. **Record any real OUTCOMES the same pass (added 2026-07-28).** Confirmation forwarding
   catches rejections, interview invitations, and "role filled" notices as well as receipts.
   Those are the only outcome signal this system ever gets: do not let them pass as
   housekeeping. For each such email write `pipeline/jobs/outcomes_[date].json` and run
   `.venv/bin/python pipeline/mark_outcome.py pipeline/jobs/outcomes_[date].json`
   (schema in its docstring). Rules:
   - A supplied `title` is a REQUIREMENT, not a hint. If no row matches it, set
     `append_if_missing` rather than letting it land on a different req at that company.
   - Use `title_exact` when one req's title is a prefix of another's at the same company
     (Talkdesk "CX Manager" vs "CX Manager - Health & Life Sciences").
   - Record only what the email literally says. Never infer an outcome from silence.
   - Set `source_channel` to `referral` or `user_surfaced` when the email establishes it.
6. Note the promoted count and any outcomes in `run_[date].json → pipeline_notes` and
   `SESSION_STATE.md`. Do not mention this step in the digest email unless something
   promoted, an outcome landed, or something was ambiguous — routine zero-result runs are
   silent housekeeping, not digest content. **A rejection or interview always goes in the
   digest**, with the stated reason when one is given.

## Step 1: ATS polling

### 1-pre. Config validation (every run, before anything reads the config files)

```bash
.venv/bin/python pipeline/validate_config.py
```

Checks JSON syntax + schema of `watchlist_companies.json`, `enrollment_candidates.json`,
and `seen_jobs.json` (the trailing-comma / mis-nesting hand-edit bug class broke feeders
silently at least 3 times). On ERROR output: fix exactly what it reports (it prints file,
line, and column for syntax errors), re-run until clean, then proceed. Also re-run it
after ANY edit you make to those files during the run (enrollments, board_status updates,
headcount backfill). `poll_ats.py` independently refuses to run against a malformed
watchlist.

### 1a. Poll

Check whether `pipeline/jobs/ats_hits_{today}.json` already exists. If yes, read it and
continue. If not:

```bash
.venv/bin/python pipeline/poll_ats.py
```

Then read the output. It contains: top-25 `matched` (pre-scored, deduped, diversity-capped
at 2/company, and **balanced**: ≥10 slots each reserved for sub-500 companies and for
larger/unknown-size companies, remainder by score), up to 20 `borderline` titles for
semantic review, `function_mismatch` (see below), `reseen_keys`, `errors`, `stats`, and
`capped_companies`. Entries flagged `new_req_of_applied_title: true` are
reposts of a title Aneesh already applied to under a new requisition — treat as new but
mention the prior application in the digest.

**`function_mismatch` section (added 2026-07-19):** title classes with a documented
poor-function-fit history (Product Manager, TPM, Sales Engineer, Engineering Manager,
Marketing Manager, Corporate Development — list lives in `_poller_config →
function_mismatch_titles`) are demoted out of the shortlist into this section. Do NOT
score or tailor them; carry a compressed "also matched, function mismatch (FYI)" line or
two into the digest only when something is notable (e.g. a role at Maven AGI). If one of
these ever looks like a REAL fit, that's a config bug: move the specific title variant to
a scoring tier rather than tailoring from this section.

Title matching is config-driven (stemmed-token matching against `_title_scoring_tiers` +
`_poller_config` in `watchlist_companies.json`): word-form and word-order variants match
automatically, and each `matched` entry carries `title_tier` + `title_prescore` (which
config tier the title hit) — use that tier at Step 2c instead of re-deriving it. Entries
flagged `jd_verification_required: true` matched a known-risky title
(`_poller_config → jd_verification_required_titles`; FDE is the prototype): NEVER tailor
one without reading the full JD first, whatever its score. To teach the poller a new
title, add it to a tier (or `_poller_config → supplemental_exact_titles`) in the JSON —
never edit `poll_ats.py`.

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
whose `status` is `"active"` **and whose `frequency` is due**. That block is the single
source of truth — never hardcode query lists anywhere else. Each entry's `notes` explain
what it catches and how to score hits.

**Frequency gating (added 2026-07-27):** `frequency: "daily"` runs every run.
`frequency: "monthly"` runs only on/after the 1st of the month, same rule as
`harvest_hn_hiring.py` — check whether it already ran this month before spending the call.
Monthly sources exist for signals that change on a quarterly scale (e.g. the AI Support
Vendor Consolidation M&A watch); running them daily is wasted budget.

Known access quirks (do not retry once failed): Wellfound/Glassdoor/Remoterocketship 403
on WebFetch — snippets only. Ashby/Workday/NICE careers pages are JS-rendered — use API
endpoints. LinkedIn redirects to login — snippets only.

### 1c-2. Blind-spot company rotation (companies with NO pollable ATS)

Read `watchlist_companies.json → _blind_spot_companies`. Take the `rotation_per_run`
companies with the OLDEST `last_checked` (nulls first), run each one's `query` via
WebSearch, and assess any fit-space hit on the normal rubric. Write today's date back to
`last_checked` for exactly those companies.

These are named employers that CANNOT be enrolled because they use custom career sites
(Google, Apple, Amazon, Meta, Microsoft, Delta) or an unresolved Workday tenant. A targeted
search is the only way they ever surface. Every hit here is by definition a role the
automated layer structurally cannot see, so treat them with the same seriousness as an ATS
hit — the 2026-07-27 Google "Product Solutions Manager, Home" find came from exactly this
class and was tailored the same day.

**If a rotation company turns out to have a pollable board after all, ENROLL it on the
watchlist and delete it from `_blind_spot_companies`.** Polling always beats searching. For
the Workday-tenant entries specifically, a `site:myworkdayjobs.com <company>` hit that
reveals the real site name is a promotion opportunity, not just a job listing — same
pattern that unstuck Availity, NCR Voyix, and Cengage (see Step 1d).

### 1d. Discovery feeders + enrollment queue

`pipeline/enrollment_candidates.json` is the standing queue that stops off-watchlist
sightings from dead-ending. Run the feeders:
- `.venv/bin/python pipeline/poll_remotive.py` — daily; appends name-only leads.
  **DEGRADED as of 2026-07-28** and will self-report as such: Remotive's public API now
  ignores `search`/`category`/`limit` and serves the same fixed 36-job window for every
  request, so discovery is impossible and the seed list is inert. The script detects this
  itself and exits without touching the queue. Leave it in the routine: the check is
  self-healing and the feeder resumes automatically if Remotive restores the API. Do not
  spend time debugging a zero-lead Remotive run unless the DEGRADED line is absent.
- `.venv/bin/python pipeline/poll_80k.py` — daily; 80,000 Hours board via its public
  Algolia backend (added 2026-07-13, replaces the old lossy WebSearch dork for this
  source). Leads arrive with (ats, slug) pre-resolved when the apply link is a
  supported ATS; salary floor still applies at enrollment
- `.venv/bin/python pipeline/harvest_hn_hiring.py` — only on/after the 1st of the month
- Board dorks (from 1c) — append any UNFAMILIAR company to `pending`

**Before treating ANY discovery hit as an unfamiliar company**, run
`.venv/bin/python pipeline/check_company.py "<name>"` (accepts several names in one call).
It searches the watchlist AND all three enrollment buckets and prints status + reason.
Only a result of UNKNOWN goes to `pending`. (Added 2026-07-19 after a dork re-surfaced
Nash as "unfamiliar" and it was nearly double-enrolled; Metronome, Lightrun, and Cognite
re-surface regularly too.)

**RUN THE HARVEST LAYER FIRST — it does the expensive part deterministically:**

```bash
.venv/bin/python pipeline/harvest_ats.py --from-pending
```

Dry-run by default; re-run with `--apply` to enroll. For each pending name it generates
deterministic slug variants, probes Greenhouse/Ashby/Lever/Workable directly, and scores the
resulting board with the **same `TitleMatcher` the poller uses**, so a company is judged on real
tier1/tier2/tier2c US-reachable fit-titles rather than keyword guessing. Auto-enrolls at LOW
priority (auto-enrollment must never outrank hand-vetted companies), rejects with a specific
reason, and empties the queue as it goes.

**This replaces the per-company WebSearch that used to gate this step**, which is why the floor
below exists at all. Built 2026-07-31 on CLAUDE.md's long-standing trigger. On its first run it
resolved **Outreach** (`lever/outreach` — two tier1 titles: "Manager, Customer Operations" US and
"Manager, Technical Support" Seattle) and **Benchling** (`ashby/benchling` — Implementation Manager
and TAM), both of which had failed manual slug guessing an hour earlier.

Names it cannot resolve are reported, not guessed at. Those are usually Workday or a non-obvious
slug, and are worth ONE manual `site:myworkdayjobs.com <company>` search each if the company
matters — the same fallback that cracked Red Hat (`Jobs`), CrowdStrike (`crowdstrikecareers`),
Trimble (`TrimbleCareers`), and Finastra (`FINC`).

**Dead-board audit — run `--prune` weekly** (it is a report; it writes nothing):

```bash
.venv/bin/python pipeline/harvest_ats.py --prune
```

First run on 2026-07-31 across 199 pollable companies found 4 dead (404) and 3 empty, including
**Fireworks AI, whose board died within a day of being enrolled**. Set `board_status` by hand on
anything it flags.

**Then process AT LEAST 4 remaining `pending` entries by hand, OLDEST `first_seen` first — a
floor, not a ceiling. Never fewer, never zero.**

Why it is worded as a bounded floor instead of "process every pending entry" (which is what it
said until 2026-07-29): unbounded work gets deferred. An audit on 2026-07-29 found the queue had
silently stopped draining. Gainsight had been pending **26 days**, four more entries 7 days, and
the 2026-07-29 run added four new LinkedIn leads while enrolling and rejecting *nothing* -- its
`enrollments` array was empty. The cost was concrete: Windfall Trust sat unprocessed with a
$150K-$200K tier-2 remote role and an already-resolved Ashby slug, one verification step from
enrollment. A bounded floor is achievable under any budget; "every entry" is not, so it got
skipped entirely rather than partially.

**Staleness alarm.** If any `pending` entry has a `first_seen` more than 7 days old after this
step runs, say so in the digest housekeeping section with the company name and age. Silent
accumulation is the failure mode this is guarding against, so make neglect visible rather than
letting the queue grow unobserved.

For each entry processed:
1. `needs_ats_resolution: true` → resolve the ATS
   (`site:greenhouse.io OR site:jobs.ashbyhq.com OR site:jobs.lever.co <company>`); no
   board found → reject with reason, and set `unpollable: true` on the rejected entry (added
   2026-08-14). This is the tag `weekly_channel_report.py`'s weekly punch-list section reads —
   only set it when the reason is genuinely "no ATS board was ever found," never when a board
   WAS found and the company was rejected for a fit/geo/category reason instead (those don't
   need a manual workaround, so they shouldn't clutter that list).

   **Before rejecting, check `manual_review`.** If the entry carries `manual_review: true`,
   still reject it (no board means the poller can never watch it), but surface it ONCE in the
   digest under "Manual channel — no pollable board" with the company, the
   `manual_review_why` title/location, and a link to the company's own careers page if one
   turned up during resolution. Then set `manual_review_surfaced: true` on the rejected entry
   so it is never re-surfaced. Rationale: the rejection is correct for the pipeline and wrong
   for Aneesh; this is the one path where a strong-title Atlanta/Remote role would otherwise
   vanish silently. Do not tailor it and do not score it: the digest line is the deliverable,
   and he decides whether to pursue it by hand.
2. Verify the board is live (direct API check; `verify_workday.py` for Workday) with
   US-reachable fit-space roles. Europe/APAC-only → reject.
   **Workday-specific fallback (added 2026-07-14):** if `verify_workday.py`'s
   `SITE_GUESSES` list fails to find a working site, do NOT immediately mark the entry
   "needs a browser-based check" — first run one targeted WebSearch
   (`site:myworkdayjobs.com <company>`) to find the real site name directly (real names
   are often non-obvious, e.g. `Availity_Careers_US`, `ext_us`,
   `CengageNorthAmericaCareers` — patterns no guess-list will reliably predict). Retry
   the direct CXS call with that name. This alone resolved 3 of 4 long-stuck Workday
   pendings in one pass (Availity, NCR Voyix, Cengage — all mis-diagnosed as
   "Cloudflare-blocked" in session notes for weeks; they were just wrong site-name
   guesses). Only fall back to "needs a browser-based check, flag for interactive
   session" if the WebSearch-corrected URL still fails (e.g. a genuine outage or
   real block) — do not spend further budget guessing site names by hand.
3. Pass → add full watchlist entry **including `headcount_band`** (verify via web, don't
   guess), `enrolled_date`, `enrolled_via`, any `score_bonus`; move to `enrolled`.
   Fail → move to `rejected` with a one-line reason.
4. Bias toward sub-500 companies — this layer exists to catch the long tail.

**Workday site-name resolution actually works; use it rather than deferring.** On 2026-07-29 all
five Workday-hosted backlog entries resolved in one pass. The guess matrix alone got Motorola
Solutions (`motorolasolutions.wd5`, site `careers`). The documented WebSearch fallback
(`site:myworkdayjobs.com <company>`) got the other four, and none of the real site names were
guessable: Red Hat = `Jobs`, CrowdStrike = `crowdstrikecareers`, Trimble = `TrimbleCareers`,
Finastra = `FINC`. That single search per company is cheap and has a high hit rate, so a Workday
company should not sit in `pending` for weeks. Only Gainsight resisted, and that is a genuine 403
block rather than a wrong site name (rejected 2026-07-29 after 8 rechecks).

ATS providers the poller speaks: Greenhouse, Ashby, Lever, Workday, SmartRecruiters
(case-sensitive slug), Workable, Pinpoint, and Rippling. (This line previously claimed Workable
was unsupported — stale since 2026-07-27, when `fetch_workable` was added; corrected 2026-08-12
alongside adding Pinpoint and Rippling support, prompted by two user-surfaced misses — Napier AI
and Nerdio — that turned out to have real public/scrapeable job data the poller just didn't know
how to read. See `_pinpoint_notes` / `_rippling_notes` in `watchlist_companies.json` for the
specific access patterns and known limits (no posting-date field on either; Rippling pagination
past page 1 is unverified against a live multi-page board).

### 1d-2. LinkedIn lead harvest (COMPANY discovery only, added 2026-07-28)

LinkedIn job alerts and "jobs you may be interested in" emails are forwarded from
`{{APPLY_ACCOUNT}}` to `{{CONFIRM_ALIAS}}`, the same alias as application
confirmations. Step 0.5 excludes them with `-from:linkedin.com`; this step is the only
consumer.

**Harvest COMPANIES, never roles. This is the whole design.** Every link in these emails is
a `linkedin.com/jobs/view/<id>` URL, not the source ATS, and LinkedIn walls those behind a
login, so resolving each role would cost one blocked fetch per role for a snippet. A company
name costs nothing and is worth more: once enrolled, the poller scans that company's ENTIRE
roster every day, forever, which strictly dominates scoring the one role LinkedIn happened
to show. (Nexus Cognitive is the case in point — an Atlanta AI company with four fit-space
roles including a tier-1 Head of Support, invisible to every discovery source until an
unrelated email exposed it.)

**THIS STEP IS MANDATORY AND MUST BE LOGGED, even when it finds nothing.** Record a
`step_1d_2_linkedin_harvest` object in `run_[date].json` on every run: the query used, the count
of threads returned, companies extracted, and how many were newly queued. **On 2026-07-30 this
step did not execute at all** — the run record contained zero mentions of LinkedIn and the step
was absent from `searches_run` — while roughly a dozen unprocessed alerts sat in the inbox. It
had run correctly the day before, so the failure mode is silent omission, not breakage. A logged
zero is verifiable; an absent section is indistinguishable from a skipped step.

1. Search Gmail for `deliveredto:{{CONFIRM_ALIAS}} from:linkedin.com newer_than:1d`.
   Zero results is normal and not an error. **Read snippets/subjects, not full bodies** —
   these emails are long and a full read of several will blow the run's context budget. The
   subject line alone carries the company and title (`<Title> at <Company>`), which is all this
   step needs.

   **Expect non-job LinkedIn mail in the results and skip it silently.** The filter forwards all
   of `from:linkedin.com` by design, so messaging digests (`messaging-digest-noreply@`), Premium
   promotions (`linkedin@em.linkedin.com`), and LinkedIn News (`editors-noreply@`) arrive too:
   about 15% of volume. Job alerts come from `jobalerts-noreply@linkedin.com` and
   `jobs-noreply@linkedin.com`. LinkedIn also re-sends the same alert hours apart under a
   slightly different subject, so dedupe by company, not by message.
2. Extract company names. Ignore salaries and links.

   **One exception (added 2026-07-28, from a real miss).** Also note when a card's title
   matches `tier1_true_match`, `tier2_strong_overlap`, or `tier2c_tooling_systems` AND its
   location is Atlanta or Remote US. When both hold, set `manual_review: true` on that company's
   pending entry plus a one-line `manual_review_why` naming the title and location.

   **Correction, 2026-07-30: the title is in the subject line, the location is NOT.** LinkedIn
   subjects are `<Title> at <Company>`, so a title-tier check is free but a location check is
   not. Do this in two stages rather than reading every body: check the title against the tiers
   from the subject alone, and ONLY for the small number of cards that already match a tier,
   open that one message to read its location. Tier-matching titles are a minority of any day's
   alerts, so this stays cheap. The earlier wording claimed both values were in the subject,
   which was wrong.

   **Match loosely, substring in EITHER direction, and do not tighten this.** A bare
   "Operations Manager" should flag off tier-1's "Support Operations Manager", and a bare
   "Account Manager" off tier-2's "Technical Account Manager". This is deliberately looser
   than the poller's scoring matcher because the cost of a false positive here is one extra
   digest line, seen once, while the cost of a false negative is a strong Atlanta role
   vanishing unseen. The flag is also gated hard by circumstance: it only ever matters for a
   LinkedIn-sourced company that ALSO turns out to have no pollable board, which is a narrow
   intersection.

   This is a FLAG, not a job. Do not fetch the posting, score it, or tailor from it. Its only
   purpose is Step 1d below: a company with no pollable ATS gets rejected, and without this
   flag a strong-title Atlanta or Remote role at such a company disappears with it, unseen.
   Prompting case: "Operations Manager, Evlo AI, Atlanta GA (Remote)" — tier-1-adjacent title
   in the two weakest buckets, at a company with no ATS board, which the company-only design
   would have discarded without Aneesh ever seeing it.
2b. **Drop job-board aggregators at extraction; they are not employers.** Platforms that repost
   other companies' listings (Swooped, Jobot, Dice, ZipRecruiter, Talentify, Lensa, and similar)
   surface in LinkedIn alerts as though they were hiring. Enrolling one pollutes the watchlist
   with duplicated third-party reqs. Swooped was caught and blocklisted on 2026-07-30. If you are
   unsure whether a name is an employer or an aggregator, that uncertainty alone is reason enough
   to skip it: a real employer will resurface.

3. **Dedupe in ONE batched call:** `.venv/bin/python pipeline/check_company.py "A" "B" "C" ...`
   (it accepts many names per call and searches the watchlist plus all three queue buckets).
   Only a result of UNKNOWN is a real lead.

3b. **Auto-trigger a one-off check for tier-matching alerts at ALREADY-known blind-spot
   companies (added 2026-08-07).** Step 2's `manual_review` flag only protects companies
   discovered THIS run that go through the pending → resolve → reject pipeline — it never
   fires for a company already classified blind-spot in a prior session (Google, Amazon,
   Microsoft, Apple, Meta, Delta, etc. — see `_blind_spot_companies`), because those never
   touch the pending queue at all: `check_company.py` just returns "already known" and the
   step stops. That's the right outcome for the COMPANY (nothing new to enroll), but it
   silently discards the ROLE signal sitting in the subject line — the same failure
   `manual_review` was built to prevent, just on the other side of the known/unknown line.
   Caught 2026-08-07 when Aneesh read the raw emails himself: a Google "Technical Account
   Manager, Google Cloud Consulting" (exact tier-2 title), an Amazon "Operations Manager"
   (tier-1 loose match), and a Microsoft "Customer Success Account Manager" (tier-2 loose
   match via "Account Manager") all alerted the same day and were logged as "already known"
   with zero role-level check.

   For each card whose title tier-matched in step 2 (same loose-substring rule) AND whose
   company resolved to an entry in `_blind_spot_companies` specifically — not just any
   already-known company; pollable companies are already covered daily by the poller, so
   this only matters where the poller structurally cannot reach — run ONE WebSearch to try
   to verify/locate the specific posting (the same move the User-Surfaced Finds Protocol
   makes on request). Add one line to the digest's "Manual channel — no pollable board"
   section with whatever was found (title, location if confirmed, a link if one resolved).
   Do NOT tailor or score from it — this is visibility, not a pick; Aneesh decides whether
   to pursue it by hand, same as the rest of that section.

   **Cap: at most 3 auto-triggered checks per run**, oldest-alert-first if more qualify, so
   a noisy day can't run away with WebSearch budget — the intersection of "tier-matching
   title" AND "blind-spot company" should be rare by construction. Log the count (checked,
   found, cap-deferred) in `run_[date].json → step_1d_2_linkedin_harvest`.

4. **Hard cap: append at most 15 new companies per run.** If more survive dedupe, take them
   in the order they appeared and leave the rest; tomorrow's run will catch them, and the
   3-day/1-day windows overlap enough that nothing is lost. This cap is what keeps the step's
   cost flat no matter how noisy the alerts get — do not raise it to "clear the backlog."
5. Append each to `enrollment_candidates.json → pending` using the standard `_schema` shape,
   with `needs_ats_resolution: true`, `source: "LinkedIn alert"`, `first_seen` = today, and a
   `why` naming the alert it came from. Carry `manual_review` / `manual_review_why` from step 2
   when set. Step 1d resolves the ATS and enrolls or rejects them on this or a later run at its
   own pace.
6. Note the harvested/capped counts in `run_[date].json → pipeline_notes`. Digest mention
   only if something notable enrolled — routine harvesting is housekeeping.

**Do NOT** score, fetch JDs for, or tailor anything from this step, except the narrow
blind-spot auto-trigger in step 3b, which does one verification WebSearch and stops at a
digest line, never a tailored pick. Otherwise: if a specific LinkedIn role is worth
assessing, Aneesh pastes it and the User-Surfaced Finds Protocol handles it.

**Setup dependency:** this needs the forwarding filter on `{{APPLY_ACCOUNT}}`
(`from:(linkedin.com)` + job-alert subject terms → forward to `{{CONFIRM_ALIAS}}`).
Until that exists the search returns zero every run, which costs one cheap call and is not
an error. A `JobLeads` label on the receiving side is optional convenience for Aneesh's own
browsing; this step keys off sender, not label, so it does not depend on one.

### 1e. Housekeeping: headcount_band backfill (max 3/run)

Most watchlist companies are missing `headcount_band`, which makes the small-company bonus
inert for them (both in the poller pre-score and in full scoring). Each run, pick up to 3
watchlist companies without a band, verify headcount via one WebSearch each (LinkedIn
"company size" snippet is fine), and set `headcount_band` (`1-50`, `51-200`, `201-500`,
`501-2000`, `2000+`). Note them in `run_[date].json → pipeline_notes`. Stop once all
companies have bands.

## Step 2: Filter and score

Combine ATS hits + promoted borderline titles + WebSearch finds.

### 2a-pre. AI-wildcard borderline review (mandatory, not optional)

`poll_ats.py` now computes a real `pre_score` for every borderline entry flagged
`ai_wildcard: true` (fixed 2026-07-10 — previously these carried no score at all, only a
low-fidelity fragment-count `borderline_score`, so they sorted alongside noise and were
easy to skim past). The poller's console output prints the top 5 by `pre_score` under
"Top AI-wildcard borderline hits" — **read every entry in `borderline` with
`ai_wildcard: true` before finalizing the top 3-4**, not just the printed top 5, and not
just the `matched` top-25. Do not defer to the higher-pre-score `matched` list by default:
ai_wildcard entries exist specifically because their title doesn't fit any exact tier, so
a high `pre_score` here can still mean the single best-fitting role in the whole run (see
Arcadia "AI Operations Lead", 2026-07-10 — borderline, ai_wildcard, real full score ~112,
would have led the shortlist, initially skipped because the daily run treated `matched` as
the primary source and only skimmed `borderline`). Score every ai_wildcard entry with the
full Step 2c rubric same as a matched entry, using `_title_scoring_tiers →
tier2b_ai_wildcard`'s `title_match_score` (+18) for the title-match component.

### 2a. Dedup (WebSearch-sourced candidates only — ATS hits are already deduped)

`dedup_key` = `{ats_or_company_slug}::{kebab-case-title-slug}` (match `poll_ats.py`
`slugify`: lowercase, non-alphanumeric stripped, spaces→hyphens). Skip candidates whose
key is in `seen_jobs.json` with `first_seen_date` within 30 days, or whose exact URL is in
`seen_urls.json`.

**Known collision, documented 2026-07-29 (not fixed, deliberately).** The key carries no
location or requisition discriminator, so two genuinely distinct reqs with the same title at the
same company collapse to one key. Observed live: Dialpad's "Revenue Operations Manager,
Downmarket" appeared twice in the same shortlist as job IDs `8606878002` (Austin) and
`8610614002` (Tempe), consuming two of forty slots for what is effectively one opportunity, and
`seen_jobs.json` can only track one of them.

Adding a discriminator to the key format would invalidate every historical key in
`seen_jobs.json` at once and flood the next run with thousands of falsely-new jobs, which is a far
worse outcome than a few wasted slots. Revisit the key format only alongside a deliberate
`seen_jobs.json` migration.

**ENFORCED IN CODE as of 2026-07-31 — you no longer have to catch this by hand.** This used to be
a prose instruction here ("keep the better-located one, put the other in also-live") and it was
skipped on both the 07-29 and 07-31 runs, so `poll_ats.py`'s `try_take()` now collapses same-key
siblings during shortlist assembly. The dropped sibling is preserved in the poller output's
**`sibling_collapsed`** array (and counted in `stats.sibling_collapsed`).

**Read `sibling_collapsed` and put those roles in the digest's "also live (FYI)" section.** They
are real, distinct requisitions, just at a company/title already represented in the shortlist. On
the 07-31 data this reclaimed 3 slots, not the 1 originally observed: Dialpad "Revenue Operations
Manager, Downmarket", Zip "Senior Customer Success Manager - Technical", and Klaviyo "Sr. Lead
Engineer - Customer Agent".

### 2b. Hard filters

Eliminate: crypto/web3/blockchain; VP/Head-of/Staff/Principal (EXCEPT exact Tier-1 titles
like Head of Support / Director of Support Operations — those are true matches);
clearance-required; postings >21 days old; salary below `_scoring_config →
salary_floor_usd`.

**Salary comparison basis (deterministic, never eyeball):** range → compare the
**midpoint**; single figure → that figure; OTE-only → estimate base (80% for
variable/sales roles, 100% otherwise) then midpoint; no salary listed → do NOT filter,
treat as neutral.

**Company cap:** companies with ≥3 entries where `applied=true AND outcome=null` need a
score >110 to surface. Queued/unapplied roles do NOT count. Trust the poller's
`capped_companies` output for ATS hits.

### 2c. Score (absolute points — canonical rubric; every number that exists in
`watchlist_companies.json` is REFERENCED here, not copied — the JSON always wins)

- Title match: the matched tier's `title_match_score` from `_title_scoring_tiers` (ATS
  hits arrive pre-stamped with `title_tier`; for WebSearch finds, match the title against
  the tiers yourself). `supplemental`-tier hits have no scoring tier — score them as the
  nearest real tier by function, or T4 if none fits.
- Keyword overlap with master resume: up to +30
- Location: Atlanta in-office +20 / Atlanta hybrid +18 / remote US +16 / **everything else 0**

  **Changed 2026-08-02: NYC-NJ (+12) removed, and "hybrid" now means ATLANTA hybrid only.**
  Aneesh is scoping to Atlanta and fully-remote-US while he looks into what renting his house
  would take. A hybrid or on-site role anywhere that is not metro Atlanta requires relocation,
  so it scores the same 0 as any other non-qualifying location: San Jose hybrid, NYC hybrid,
  and Boston on-site are now all 0. Previously the bare word "hybrid" was read as +18 regardless
  of city, which is how PermitFlow (hybrid NYC, in-office Mon/Wed/Fri) and Zscaler (hybrid San
  Jose/Bellevue/Dallas) both reached full tailoring in late July.

  This is a SCORING change, not a hard filter: those roles can still appear as near-misses so
  Aneesh can see what he is passing on, they just lose 16-20 points and will normally fall below
  the 88 full-tailoring threshold. Do not add a location hard-exclude unless he asks. Revisit
  this line if the rent-the-house question resolves.
- Salary (midpoint basis): ≥$140K +10 / ≥$120K +8 / ≥floor or unlisted +5 / below 0
- Source quality: Greenhouse·Lever +10 / Ashby·BuiltIn +8 / aggregator +5; −3 if >14 days old
- Freshness: `_scoring_config → freshness_bonus_2d` (≤2 days) / `freshness_bonus_7d` (≤7 days)

**Company-level bonuses — capped at +30 combined (Scoring Guardrails in CLAUDE.md):**
- **A watchlist company's config `score_bonus` IS its complete vertical bonus. Count it once,
  read `bonus_reason` to see which vertical(s) it represents, and never add anything on top
  of it for AI or tooling.** As of 2026-07-29 that value encodes three cases: `20` for AI/ML,
  `20` for developer/infra tooling, and `30` for a company that is genuinely both (already
  pre-clamped at the cap). Current distribution: 55 AI-only, 19 tooling-only, 9 both.
- Tooling means the company's PRODUCT is a tool: devtools, dev infra, observability,
  security tooling, data/API platforms. Added 2026-07-29 after Aneesh named tool creation and
  maintenance as his primary interest, with AI co-equal secondary. The list is CURATED, not
  keyword-derived: an automated pass was ~40% wrong in both directions and missed LaunchDarkly,
  1Password, Vanta, Expel, LogicGate, and Chainguard outright. To add a company, edit its
  `score_bonus`/`bonus_reason` by hand.
- Non-watchlist company with no config bonus: +20 once if AI-native, +20 once if it is a
  tooling company, +30 if clearly both. Never both a config bonus and a manual one.
- Watchlist +10 · Atlanta-startup +20 · Atlanta-enterprise +10 · IoT +15
- Small-company: per `_scoring_config → small_company_bonus` by `headcount_band`
  (absent band = 0, never guess)
- **Passion-domain +10** (`_scoring_config → passion_domains`: electrification/EV, health
  tech, agriculture/gardening/food). Apply SEMANTICALLY to the company's mission/product,
  once per job even if multiple domains hit; ignore keyword accidents ("patient rollout").
  Poller entries may carry a `passion_domain` tag as a hint — confirm it, don't trust it.

**Penalties (small — reach is fine):** title gap −5 (named IC function Aneesh never held
by exact title, once per job); seniority mismatch −5 (JD explicitly requires **any**
stated years-of-experience minimum in that specific function AND no prior title in it —
originally written as "6+ years", generalized 2026-08-10 because Chainguard's bar was
"5+ years" and the literal 6 meant the penalty never fired). Max −10 combined. Do not
penalize reach beyond these two.

**HARD-REQUIREMENT TIER CAP (added 2026-08-10, overrides the score-based tier).** If the
JD states an explicit minimum years-of-experience in a specific function and Aneesh has
**zero** years in that function by title, the role is capped at **light tier** no matter
what it scored: summary rewrite + skills reorder only, no cover letter, and the gap named
in the digest as a hard requirement rather than a soft gap. Same cap applies to any
requirement the JD marks as non-negotiable in its own words ("required, not preferred",
"must have"). This exists because the penalty system alone (max −10) cannot move a role
that scored 104 below the 88 full-tailoring threshold, so a genuine disqualifier was still
producing full-tier work: Chainguard 2026-08-10 scored 104 with a "5+ years in Data
Governance or GTM Systems" bar Aneesh does not meet at all, and got a cover letter. Meanwhile
LaunchDarkly's comparable coding gap was correctly demoted the same run — the inconsistency,
not the individual call, is what this rule fixes. Judgment still applies to what counts as
"the same function": Service Cloud admin work is not GTM Systems experience, but a Support
Operations Manager req asking for "5+ years in support operations" is squarely met.

**Diversity cap:** surface ≤2 roles per company per run; fully tailor only the single
best-scoring one — additional same-company roles are "also live (FYI)" digest lines.

**Pick the top 3-4 jobs.** Tailoring tiers come from `_scoring_config`:
≥`company_cap_threshold` priority/full · ≥`full_tailoring_threshold` full ·
≥`light_tailoring_threshold` light (summary rewrite + skills reorder only, no cover
letter) · below that, skip. If fewer than 3 clear the light threshold, send what you
have — never pad.

**Capture near-misses (do NOT tailor):** (A) score near-miss — passed every hard filter
but scored below `light_tailoring_threshold` (no lower bound); (B) salary near-miss —
passed everything except the salary floor, midpoint between `near_miss_salary_floor_usd`
and `salary_floor_usd`. Collect title, company, location, salary, score, URL for the
digest. Stale/capped/crypto/VP roles are NOT near-misses.

**Repeat-near-miss suppression (added 2026-07-19):** if the same posting (same dedup_key)
has already appeared as a near-miss with the same conclusion in ~3 or more prior digests
(check recent `run_*.json` near_misses arrays or SESSION_STATE), do NOT re-score or
re-fetch it. Compress it to one digest line: "still live, previously assessed (see
run_[date])". Re-assess only if something changed — new salary, retitled, or a config
change that would plausibly move its score. (Cato Networks' AI Security PSC was re-listed
with the identical conclusion in every digest from 07-15 through 07-19.)

**Read `master_resume.md` NOW** — once, reused for all tailorings below.

## Step 3: Fetch full JDs

WebFetch each top job's apply URL. On failure (403/JS), WebSearch for a cached or mirrored
copy (BuiltIn, ZipRecruiter, Greenhouse cache). If the JD is unreachable two runs in a
row, drop it to the near-miss list with a note rather than stalling.

**Ask for the requirements section VERBATIM, not a summary (added 2026-08-10, from a real
mis-score).** WebFetch answers your prompt with a small summarizing model, so a generic
prompt ("extract the description, salary, and top keywords") gets back a paraphrased
responsibilities list with the hard qualification bar silently dropped. The prompt must
explicitly demand the qualifications/requirements block quoted exactly, especially any
`N+ years of experience in [function]` line. Use wording like:

> "Extract the COMPLETE requirements/qualifications section verbatim, especially any
> years-of-experience requirements. Quote the exact text, don't summarize. Then separately:
> title, salary range, posting date, location/remote policy, top 15 keyword phrases."

What went wrong without it: Chainguard's "Senior Data Governance and Tooling Manager"
(2026-08-10) leads its requirements with **"5+ years of experience in Data Governance or GTM
Systems roles"** — a function Aneesh has zero years in. The generic fetch returned only
responsibilities, that line was never seen, and the role was scored 104 and fully tailored
WITH a cover letter, when the same run correctly demoted LaunchDarkly to light tier for a
comparable hard gap (production coding) that happened to appear in the summarized output.
Disclosing a gap honestly in the cover letter is not a substitute for scoring it correctly:
the tier decision is what allocates Aneesh's limited application effort.

**Ambiguous location shorthand: resolve it from the JD body, never the shortlist string.**
Same run, Automation Anywhere's "Engagement Manager" showed `CO Remote` in the poller
output; the JD body said "Remote role within **Colombia**." Two-letter codes in Workday
location strings are not reliably US state codes. Caught before tailoring, but only by
reading the body.

**If the top-scored role at a company fails the JD read** (real skill mismatch — e.g. a
Forward Deployed Engineer listing that turns out to require production coding), don't just
drop the company. Pull that company's other live postings (direct ATS API call, same
pattern as `pipeline/verify_workday.py`'s target-title scan) and check whether a
lower-pre-scored role there is actually the better fit. This is how Confido's Implementation
Manager got found on 2026-07-09. Since then the poller structurally reduces this failure:
titles in `_poller_config → jd_verification_required_titles` are demoted below a company's
clean titles before the 2-per-company cap picks keepers, so a risky title can no longer
crowd out a safer same-company role. This fallback step still applies when a NON-flagged
top pick fails its JD read — and when that happens because of a title pattern, add the
title to `jd_verification_required_titles` so the class is covered. Only worth the extra
API call when the top pick's JD genuinely disqualifies it — not a step to run for every
company by default.

## Step 4: Tailor resumes and cover letters

Follow the CLAUDE.md tailoring workflow for each top job (JD analysis → top-15 phrases →
ATS optimization → tailor → verify). Per job:

**Career narrative application (from the Step 0 read of
`.claude/skills/career-narrative/SKILL.md`):**
- Pick the ONE framework (max two, never all four) that matches what this JD is actually
  probing — the skill's per-framework "deploy for" notes say which. The framework shapes
  the resume summary's angle and the cover letter's argument; it must sound spontaneous,
  not recited.
- Slot the STAR story that matches the JD's top requirement; use the
  transferable-parallel template for the company-specific connection in the cover letter.
  Two stories carry flagged gaps (email-pipeline metric, adoption anecdote) — do not
  invent the missing specifics; use the documented fallbacks.
- Positioning language ("owns the AI copilot relationship", "designs support systems
  with AI as a first-class participant") belongs early in summaries and letters — but the
  CLAUDE.md opener rules still own the first sentence of every cover letter. Outcomes
  before tools, always; never escape-framing.

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
   JD language mirrored + which career-narrative framework/story was used (so Aneesh can
   spot-check the framework fits the role before applying). Bullets, no prose.

7. **Style check (before rendering each PDF):** the document must comply with the writing
   style guide read in Step 0. Minimum mechanical check: `grep -c '—' <file>` must be ≤2;
   then apply the guide's Gut Check ("does this sound like a real person wrote it?").

**NEVER fabricate experience, certifications, or skills.**

## Step 5: Email digest

Gmail MCP `create_draft` (drafts only — no send, no attachments) to **{{DIGEST_RECIPIENT}}**:

- Subject: `Daily Job Matches — [date] ([N] jobs)`
- Top note: "Open this draft, attach the PDFs listed at the bottom, and send."
- **Pass RAW HTML to `htmlBody`, never HTML-escaped entities.** Write `<p>`, not `&lt;p&gt;`.
  Escaping the markup makes Gmail render every tag as literal visible text and the digest
  arrives as an unreadable wall of angle brackets (happened 2026-07-27). If a draft has
  already been SENT, `update_draft` fails with "Message not a draft" — create a corrected
  replacement draft rather than trying to patch it.
- HTML table: title, company, location, salary, score, JD coverage %, apply link
- **Provenance column/notes (added 2026-07-27).** Every `matched` entry carries a
  `provenance` array from `poll_ats.py`. A non-empty array means the role is visible ONLY
  because of the 2026-07-27 filter widening (`age_*_over_old_21d_limit`,
  `rank_*_over_old_25_cap`, `geo_free_location_was_dropped`, `workable_ats_newly_supported`,
  `director_relaxed_small_company`). Surface these in the digest as a short human-readable
  tag, e.g. "(newly visible: 28 days old, would have been cut at 21)". Purpose: five filters
  were relaxed at once, so without per-role attribution a later quality drop can't be traced
  to the change that caused it, and the widening would be judged on raw volume — which is
  the wrong metric, since relaxing filters raises volume by construction. Report the
  `stats.provenance_counts` summary in the digest housekeeping section too. If Aneesh
  consistently ignores roles carrying one particular tag, roll THAT change back rather than
  reverting the whole widening.
- Per-job tailoring diff below the table
- "Also live (FYI)" lines for same-company extras; near-misses section at the bottom
  (one line each with reason tag, e.g. "scored 74" / "pay $92K midpoint"); omit if none
- **"Manual channel — no pollable board"** section: companies rejected at Step 1d that carried
  `manual_review: true`. One line each (company, the flagged title and location, careers-page
  link if found). Omit the section entirely if none. These are NOT scored or tailored; they are
  roles the automated layer structurally cannot watch, surfaced once so Aneesh can decide.
- Note any ATS errors, capped companies, enrollments/rejections, and skill gaps observed
- **"Full breakdown: what was checked" section (added 2026-08-06, standing requirement).**
  Aneesh asked for this after catching a real discovery-layer miss by hand (Hercules, Philips,
  and Headway all came from him screenshotting the LinkedIn app's own Jobs recommendation feed —
  a product surface none of the automated channels touch, since Step 1d-2 only consumes forwarded
  *job-alert emails*, a different LinkedIn surface entirely). Every digest must end with a
  bulleted, source-by-source account of what ran and what it found, so a miss like that is
  visible immediately rather than discovered by chance:
  - ATS poll: companies polled, jobs scanned, matches, shortlist size
  - WebSearch discovery: which of the active `_websearch_sources` ran, and a compressed list of
    what surfaced (mostly-known vs. genuinely new)
  - Discovery feeders: poll_remotive/poll_80k/harvest_hn_hiring status (including DEGRADED/skipped)
  - Blind-spot rotation: which named employers were checked this run
  - LinkedIn email-alert harvest: threads found, companies extracted, what happened to each
  - Any user-surfaced companies processed this run, and explicitly which channel (if any) would
    have caught them on its own — if none would have, say so plainly, the way this entry does
  - A short "Confirmations & tracking" bullet list: promotions, outcomes, enrollments/rejections,
    headcount backfill, enrollment-queue staleness

## Step 6: Update tracking

1. Write `pipeline/jobs/track_[date].json`:
   ```json
   {"run_date": "YYYY-MM-DD", "jobs": [{"dedup_key": "...", "company": "...",
     "title": "...", "url": "...", "score": 0, "jd_coverage_pct": 0, "notes": "",
     "unmet_hard_reqs": 0, "vendor_tool_named_in_jd": ""}]}
   ```
   (surfaced top 3-4 only, not near-misses)

   **`unmet_hard_reqs` and `vendor_tool_named_in_jd` are required, added 2026-08-01.**
   You already identify both during tailoring; these fields just stop them from being
   trapped in prose where nothing can count them.
   - `unmet_hard_reqs`: integer count of the JD's HARD requirements that cannot be
     honestly claimed from `master_resume.md`. Count the same gaps you disclose in the
     cover letter and report at Step 4. Nice-to-haves don't count; only requirements a
     screener would treat as disqualifying. `0` is a legitimate value, empty is not.
   - `vendor_tool_named_in_jd`: the incumbent AI/support/CX tool the JD names, verbatim
     (`Intercom/Fin`, `Forethought AI`, `Zendesk`, `Ada`). Empty string when the JD names
     none. Record what the JD says, not whether Aneesh has used it.

   Why these exist: `jd_coverage_pct` cannot serve as a readiness signal, and the reason
   is arithmetic rather than sample size. 85% of applied rows sit at >=93% coverage
   because Step 4 optimizes coverage to a target, so it has no variance left to explain
   anything. Vanta scored 15/15 and was rejected at screen for lacking Intercom/Fin.
   See CLAUDE.md's `jd_coverage_pct` note.
2. Run:
   ```bash
   .venv/bin/python pipeline/update_tracking.py pipeline/jobs/track_[date].json --touch-reseen pipeline/jobs/ats_hits_[date].json
   ```
   This updates `seen_jobs.json`, `seen_urls.json`, and `pipeline/outcomes.csv`
   (canonical header: `applied_date,company,title,url,fit_score,jd_coverage_pct,stage,
   outcome,notes,source_channel,surfaced_date,unmet_hard_reqs,vendor_tool_named_in_jd`)
   atomically. `surfaced_date` is written automatically from the run date; never set it
   by hand and never update it on an existing row. **Never hand-edit `seen_jobs.json`** —
   hand edits corrupted it on 2026-06-30. NOTE: `pipeline/jobs/outcomes.csv` is a stale
   orphan — never write to it.
3. **Aging check (added 2026-08-01, report-only):**
   ```bash
   .venv/bin/python pipeline/age_report.py
   ```
   Read the output and carry one line into the digest whenever a role scoring >=100 has
   sat at `stage=surfaced` for more than 30 days. That is tailoring work decaying unsent,
   and it is the single largest measured loss in the system: the 2026-08-01 audit found a
   24% send rate in July and a 22-day median age on surfaced rows. Do NOT run `--apply`
   during an autonomous run; retiring rows is Aneesh's call.
4. Write `pipeline/jobs/jobs_[date].json` (full structured records) and
   `pipeline/jobs/run_[date].json` (run metadata: searches run, stats, capped companies,
   pipeline_notes, near_misses array, email draft ID).
5. Update `pipeline/SESSION_STATE.md`: today's output, near-misses, housekeeping, action
   queue. Session state never goes in `CLAUDE.md`.
6. Add a `channel_stats` block to `run_[date].json` (schema added 2026-08-10, see any run
   from that date onward for the shape). Four sub-objects: `ats_poll` (companies_polled,
   jobs_scanned, title_matched, shortlisted), `websearch` (sources_run, new_companies_found,
   enrolled), `linkedin_harvest` (threads_found, companies_extracted, enrolled,
   blind_spot_real_hits), `feeders` (poll_remotive_status, poll_remotive_leads,
   poll_80k_leads, harvest_hn_hiring_status, harvest_hn_hiring_leads), plus a top-level
   `tailored_count`. This is the ONLY thing `pipeline/weekly_channel_report.py` reads —
   every run must write it, in this exact shape, or that day silently drops out of the
   weekly rollup. Do not backfill historical runs by guessing; the source data isn't
   consistently structured that far back (checked 2026-08-10: zero of ~45 prior run files
   had usable per-channel data in a common shape).

## Step 6.5: Weekly channel-effectiveness rollup (gated, separate Gmail draft)

**Added 2026-08-10, from Aneesh asking for a rundown of which discovery channel (ATS poll,
LinkedIn forwards, WebSearch, discovery feeders) actually produces value.** A per-day answer
is noisy — one day's "4/4 tailored picks came from the ATS poll" doesn't mean LinkedIn/WebSearch
failed, it means ATS-poll is the execution layer that benefits from everything those channels
enrolled over the preceding weeks. This is a weekly-cadence report, sent as its own Gmail draft,
not folded into the daily digest.

1. Use the **Read tool** on `pipeline/jobs/weekly_channel_report_state.json` (gitignored, lives
   in `pipeline/jobs/` alongside the other run-state files). If it errors because the file
   doesn't exist, the report is due. If it returns `{"last_sent": "YYYY-MM-DD"}`, the report is
   due only if that date is 7 or more days before today. Otherwise skip this step entirely —
   do not mention it in the digest, this is silent housekeeping like the monthly-source gating.
2. If due, run:
   ```bash
   .venv/bin/python pipeline/weekly_channel_report.py
   ```
   It aggregates the trailing 7 days of `channel_stats` blocks and prints a per-channel
   breakdown (ATS poll, WebSearch, LinkedIn harvest, feeders) plus how many days in the window
   actually had data. Early on, most of the window will be missing (schema only exists from
   2026-08-10 forward) — the report says so explicitly; don't treat that as an error.

   It also prints an **"Unpollable companies"** section (added 2026-08-14, from Aneesh asking
   for a weekly punch list of companies the automated layer structurally can't reach): a capped
   batch (`UNPOLLABLE_WEEKLY_CAP` = 20, oldest `rejected_date` first) of
   `enrollment_candidates.json → rejected` entries tagged `unpollable: true` — meaning no ATS
   board was ever found for them, as opposed to a board being found and the company rejected
   for fit/geo/category reasons — that haven't been surfaced in a prior weekly report yet. This
   runs regardless of whether the channel-stats window has data, so it fires even on an early
   week. Aneesh reviews the batch by hand (find the real slug/Workday tenant, or let it drop);
   this is a **standing backlog**, not a trailing-week window, so don't be surprised if the
   first several weeks each show a full 20-entry batch with "N more carry over."
3. Create a **separate** Gmail draft (`create_draft`, not `update_draft` on the daily digest):
   - To: `{{DIGEST_RECIPIENT}}`
   - Subject: `Weekly Channel Report — [window start] to [window end]`
   - Body: the script's output, lightly formatted as HTML (same raw-HTML rule as Step 5 —
     never HTML-escape the markup). Add one interpretive line per channel using the actual
     numbers, not template filler — e.g. if `poll_remotive` was degraded every tracked day,
     say that plainly; if a channel enrolled zero companies for two straight weeks, say that
     too. The point of this report is catching a channel that's quietly gone dead (this is
     exactly how `poll_remotive`'s degradation was first noticed) or over-invested (14
     WebSearch calls a day for a handful of already-known companies). Include the full
     unpollable-companies batch as its own section, one line per company (name, rejected date,
     reason) — this is the part Aneesh actually acts on, don't compress it away.
4. **Only after the draft is confirmed created**, re-run with `--apply` to mark the printed
   unpollable batch as surfaced so it doesn't repeat next week:
   ```bash
   .venv/bin/python pipeline/weekly_channel_report.py --apply
   ```
   Do this as a genuinely separate second call, not folded into step 2 — running `--apply`
   before the draft exists would consume the batch on a preview that never got sent. If step 3
   fails (draft creation errors out), skip this step entirely so the same batch is retried next
   run rather than silently lost.
5. Write today's date to `pipeline/jobs/weekly_channel_report_state.json` as
   `{"last_sent": "YYYY-MM-DD"}` (Write tool, overwrite whatever was there).
6. Note the draft ID in `run_[date].json → weekly_channel_report_draft_id` and one line in
   `SESSION_STATE.md`. Do not mention this step in the main digest email at all — it has its
   own draft and its own send decision.

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
