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
- Full JDs via `fetch_jd.py` (Step 3) — never WebFetch an Ashby/Workday/Comeet posting, they
  are JS-rendered or templated and return the title only, which costs retries and search budget
- Tracking updates via `update_tracking.py` — never hand-edit `seen_jobs.json`
- Application-confirmation promotions via `mark_applied.py` (Step 0.5) — never hand-edit
  `outcomes.csv`'s `stage`/`applied_date` columns
- Read `master_resume.md` ONCE, reuse for all tailorings
- WebSearch discovery is ROTATED, not exhaustive: `websearch_rotation.py` picks the due
  sources (Step 1c). Beyond those, only recovery searches and the blind-spot rotation.

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
5. **Rotate the apply-now folder (added 2026-08-28, Aneesh's request).** Run:
   ```bash
   .venv/bin/python pipeline/rotate_apply_folder.py --apply
   ```
   `tailored/apply_now/` holds ONLY the PDFs of roles still waiting to be sent, so an ATS
   upload dialog opens on a short list instead of `tailored/`'s 1,500+ files where the `.md`
   sorts next to the `.pdf` of the same name. This step evicts anything whose `outcomes.csv`
   row has left `surfaced`, plus anything still surfaced after 7 days. **It moves files back
   to `tailored/`; it never deletes**, and an unmatched PDF is always kept rather than evicted
   on a guess. Read the `DIGEST LINE:` it prints and carry it into the digest (Step 5) — that
   line is unsent tailoring showing up where it will be seen, rather than only when someone
   runs `age_report.py`. Rationale for the 7-day window and for not giving high scorers a
   longer one is in the script's docstring.

6. **Record the working-tree baseline (added 2026-08-21).** Run this before changing
   anything, so Step 7 can tell your edits from ones that were already sitting there:
   ```bash
   .venv/bin/python pipeline/repo_sync.py --snapshot
   ```
   It writes `pipeline/jobs/repo_baseline.json` (gitignored) listing every already-dirty
   path, and Step 7 consumes and deletes it. If it reports pre-existing dirty paths, that
   means Aneesh has edits in progress right now: leave them alone all run, and carry one
   line into the digest naming them.

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
   {"confirmations": [{"url": "https://...", "company": "...", "title": "...",
                       "applied_date": "2026-MM-DD"}]}
   ```
   (`url` optional if truly not stated; `applied_date` = the date the confirmation email was
   received, not today's date, if they differ.)

   **ALWAYS include `title` when the email states one, even if you also have the URL.**
   Since 2026-08-21 `mark_applied.py` treats a supplied title as a REQUIREMENT on the
   company-name fallback (matching `mark_outcome.py`), so a title is what stops a
   confirmation from landing on the wrong requisition. Add `"title_exact": true` when one
   req's title is a prefix of another's at the same company.

   Why this is not optional: on 2026-08-20 four receipts arrived whose real rows were
   already `applied`. Every one fell through to the company fallback, which matched on
   company alone and promoted two UNRELATED still-surfaced rows (Relay Payments
   "Enterprise Solutions Engineer", Maven AGI "Technical Project Manager"). That was caught
   by hand and reverted from the `.bak`. The code now refuses those matches when a title is
   given, and prints an **UNVERIFIED MATCH** warning when a promotion happens on company
   name alone with no URL and no title. Read that warning if it appears; it means the row
   was chosen only because it was the one still open at that company.
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

Then read the output. It contains: top-40 `matched` (pre-scored, deduped, diversity-capped
at 2/company, and **balanced**: ≥10 slots each reserved for sub-500 companies and for
larger/unknown-size companies, remainder by score), `near_window` (see below), up to 20
`borderline` titles for semantic review, `function_mismatch` (see below), `reseen_keys`,
`errors`, `stats`, and `capped_companies`. Entries flagged `new_req_of_applied_title: true`
are reposts of a title Aneesh already applied to under a new requisition — treat as new but
mention the prior application in the digest.

**TIER1-COMPLETE GUARANTEE (added 2026-09-01, Aneesh's pick):** `matched` can now exceed 40.
Every `tier1_true_match` that passes the gates surfaces regardless of rank, tagged
`tier1_guarantee_over_rank_cutoff` in `provenance` and counted in `stats.tier1_guaranteed`
(~5-10/day; the 2-per-company cap still bounds it). These are FULL shortlist members: score
them like any other entry. Rationale: the 2026-09-01 diagnosis showed ~170 gate-passing jobs
above the cutoff with only 40 shown, and Pinterest's tier1 "Manager II, Technical Support
Engineer" sat at rank 51 for 3.5 weeks of LinkedIn alerts without ever surfacing — the same
class as the point-patched n8n (08-26) and Outreach (08-28) misses. If digest quality drops,
the provenance tag is what makes THIS change attributable and reversible on its own.

**`near_window` section (added 2026-09-01, Aneesh's pick):** the next ~40 gate-passing jobs
below the shortlist cutoff, compressed to company/title/location/pre_score/tier/url. These
exist for visibility parity with Aneesh's LinkedIn alerts, which sample this population with
no rank window. Render them in the digest as ONE-LINE FYIs with apply links (Step 5) — do
NOT score, fetch JDs for, or tailor from this section by default. One exception, used
sparingly: an entry that is obviously exceptional (exact-title match, Atlanta, or a named
passion domain) may be promoted into normal Step 2 scoring, with the promotion named in the
digest. Expect sibling duplicates here (same title, different location reqs); they are
documented and harmless.

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

**ROTATED as of 2026-08-23. Do not go back to running every active daily source.**

```bash
.venv/bin/python pipeline/websearch_rotation.py
```

It reads `pipeline/watchlist_companies.json → _websearch_sources` (still the single source of
truth for queries; never hardcode a query list anywhere else) and prints the
`rotation_per_run` daily sources with the oldest `last_run`, nulls first, along with their
queries. It also reports which monthly sources are due and flags any source that has gone
more than 7 days without running. Run the sources it prints; each entry's `notes` in the JSON
explain what it catches and how to score hits.

Then record **only the sources that actually ran**:

```bash
.venv/bin/python pipeline/websearch_rotation.py --mark "<name>" "<name>" ...
```

**Marking a source you skipped is the one way this mechanism silently loses coverage.** If the
run gets through 4 of the 6, mark 4. The next run will pick the other 2 back up automatically
because they still sort oldest-first.

**Why this replaced "run every active daily source."** That instruction meant 16 WebSearch
calls whose results all land in the run's context, competing directly with JD retrieval and
tailoring — and the way it lost was by being skipped wholesale rather than trimmed:
**2026-08-21 ran zero of them, 2026-08-23 ran four.** A skipped step is invisible in the
digest; a rotation is not. Measured across the 11 runs carrying `channel_stats` (2026-08-10
onward), WebSearch discovery produced 46 new companies and 13 enrollments over 121
source-runs, roughly 9 source-runs per company enrolled, against 21 enrollments for the
LinkedIn harvest at one Gmail call per run. The channel works; the marginal source is
expensive.

At `rotation_per_run: 6` every source is hit about every 3 days for ~40% of the cost. **The
3-day gap is nearly free because these sources discover COMPANIES, not perishable reqs** — an
unfamiliar company on an Ashby dork today is still there on Thursday, and once enrolled the
poller scans its entire roster daily, forever. That is the same argument Step 1d-2 already
makes for harvesting companies rather than roles out of LinkedIn; it simply never got applied
to the dorks. Contrast the ATS poll in 1a, where a fresh req genuinely decays and daily has to
mean daily.

Keep the yield figure honest when reasoning about it later: n=11 runs, and the low-source days
were also thin days generally, so it is directional rather than settled. Revisit once
`weekly_channel_report.py` has more windows — some of these sources may deserve **disabling**
rather than rotating, which is a different decision from how often to run them.

**Frequency gating (added 2026-07-27, unchanged):** `frequency: "monthly"` sources run only
on/after the 1st of the month, same rule as `harvest_hn_hiring.py`, and **never consume a
rotation slot**; `websearch_rotation.py` reports their due state in its own section so they
cannot be forgotten. Monthly sources exist for signals that change on a quarterly scale (e.g.
the AI Support Vendor Consolidation M&A watch); running them daily is wasted budget.

Use `--all` for an interactive full sweep when Aneesh asks for one, and `-n N` to widen the
rotation for a single run. Neither is the default for a scheduled run.

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

### 1c-3. Unpollable-backlog monthly check (confirmed-role companies with NO pollable ATS)

Read `watchlist_companies.json → _unpollable_backlog_companies`. **Monthly frequency**: run
only on/after the 1st of the month, same self-gating pattern as the AI Support Vendor
Consolidation M&A watch in `_websearch_sources` — check whether it already ran this month
(recent `run_*.json` mentioning this step) before spending the calls.

Added 2026-08-18 after a review of the 128-company unpollable backlog in
`enrollment_candidates.json → rejected`. That review split three ways: ~24 large companies
with zero confirmed role signal got a one-time Workday-resolution sweep instead (2 converted
to permanent watchlist enrollments — Coca-Cola, Ascensus — 22 confirmed genuinely dead and
annotated so they're not re-swept); ~86 companies with zero role signal were left alone as
low-value discovery noise; these 18 have a CONFIRMED real fit-space role already on record
and no supported ATS, which is exactly the shape `_blind_spot_companies` already handles for
large employers — this block is the same mechanism for smaller/niche ones.

When due, run every company's `query` in this list (not a rotating subset — 18 WebSearches
once a month is cheap) and check for a currently-open fit-space role. Update `last_checked`
to today and `last_hit` with the result for each. Do NOT score, tailor, or apply from a
hit here — this is visibility only, same treatment as the daily blind-spot rotation. If a
hit is worth surfacing (role still live, or a new one appeared), add a line to that day's
digest under "Manual channel — no pollable board." If a company turns out to have gained a
supported ATS after all, follow the standard enrollment procedure (verify live, add
headcount_band, move to the main watchlist) and remove it from this list.

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

Dry-run by default; re-run with `--apply` to enroll.

**Add `--skip-workday` whenever the pending queue holds more than a handful of names
(added 2026-09-02).** The Workday probe walks 5 hosts × ~15 site names at a 20s timeout per
slug, so a batch containing even a few enterprises whose tenant resolves but matches no site
name will hang the whole run: on 2026-09-02 a 16-name LinkedIn batch (Palo Alto Networks,
RSA Security, Forescout, Worldwide Clinical Trials among them) was SIGKILLed at ~10 minutes,
re-run, and was still silent past 40 minutes, leaving 21 entries unresolved until the flag
existed. With it, the six cheap ATSes run to completion in minutes; names that need Workday
are reported as no-board with the usual manual `site:myworkdayjobs.com` fallback, which is the
same outcome the hung run would have produced for them anyway, minus the hang. Run the
Workday-inclusive form only on a short, deliberate list via `--names`. For each pending name it generates
deterministic slug variants, probes Greenhouse/Ashby/Lever/Workable directly, and scores the
resulting board with the **same `TitleMatcher` the poller uses**, so a company is judged on real
US-reachable fit-titles rather than keyword guessing.

**Qualifying tiers (changed 2026-08-21, Aneesh's call):** tier1/tier2/tier2c anywhere
US-reachable, **plus tier3 in Atlanta or remote-US only**. tier4 and supplemental remain
excluded outright. tier3 used to be lumped in with tier4, which conflated two different
things: the rubric gives `tier3_reasonable_stretch` +15 and CLAUDE.md says "full tailoring if
score >= 88", whereas tier4 really is weak. That cost five companies in three weeks (Evident
ID, Britive, Sonatype, Nylas, Placemakr), each rejected as "no fit-space" while running a live
tier3 role. The proof tier3 is not weak: the Vanta "Sr. Manager, Commercial Customer Success"
role surfaced 2026-08-21 is a tier3 title that scored **96**.

The gate is LOCATION, not tier, because location is what makes a stretch title worth taking:
Atlanta carries +20 in-office and a further +20 Atlanta-startup, remote-US carries +16, and
that swing is the difference between a tier3 role scoring ~80 and ~105. A CSM in Boston is the
stretch title without the premium, so it still does not qualify. `tier3_location_ok()` is
deliberately much narrower than `us_reachable()`; do not "simplify" them into one predicate.
On the first live run it flipped Britive and Sonatype (real remote-US tier3 roles) while
correctly leaving Nylas and Placemakr rejected. Auto-enrolls at LOW
priority (auto-enrollment must never outrank hand-vetted companies), rejects with a specific
reason, and empties the queue as it goes.

**This replaces the per-company WebSearch that used to gate this step**, which is why the floor
below exists at all. Built 2026-07-31 on CLAUDE.md's long-standing trigger. On its first run it
resolved **Outreach** (`lever/outreach` — two tier1 titles: "Manager, Customer Operations" US and
"Manager, Technical Support" Seattle) and **Benchling** (`ashby/benchling` — Implementation Manager
and TAM), both of which had failed manual slug guessing an hour earlier.

**Workday is probed automatically as of 2026-08-28**, after the harvester's five-ATS coverage
was found to be the real bottleneck rather than slug guessing: it had rejected General Motors,
Brown & Brown, and Reputation as unpollable while all three ran large live Workday boards. It
now tries Workday last, once every cheaper ATS has failed, gated on the CXS status code (`422`
= no such tenant, stop; `404` = wrong site name, keep walking; `200` = hit). DNS cannot gate
this — myworkdayjobs.com serves wildcard DNS, so gibberish tenants resolve — and an early
DNS-gated version timed out a three-company run at 600s. Typical cost is ~1.5s for a hit, ~3s
to rule a company out, ~12s worst case where a tenant exists but no site name matches.

Names it still cannot resolve are reported, not guessed at. Two classes remain, and both need
ONE manual `site:myworkdayjobs.com <company>` search:
- **Non-obvious tenant**, which no name variant produces: Brown & Brown is `bbinsurance`.
- **Non-derivable site name**, where the tenant resolves but the site is an abbreviation or
  regional string outside the tried list: General Motors is `Careers_GM`, and Availity is
  `Availity_Careers_US`. The probe tries 11 common names plus four derived from the tenant
  (`{slug}careers`, `{slug}Careers`, `{slug}_careers`, `Careers_{SLUG}`), which covers the
  CrowdStrike/Trimble/Synechron shape but not an abbreviation.
That fallback is also what cracked Red Hat (`Jobs`) and Finastra (`FINC`). **Run it** when a
company matters: an audit on 2026-08-28 found 139 rejected entries whose own reason text asked
for that search and never got it, 13 of them with a confirmed tier-matching role already seen.

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
(case-sensitive slug), Workable, Pinpoint, Rippling, Comeet, and **Paylocity** (added
2026-08-28). **Paylocity boards CANNOT be auto-resolved by `harvest_ats.py` and must be
enrolled by hand**: its identifier is a GUID from the careers URL rather than anything derived
from a company name, so no slug generator will ever produce one. It is multi-tenant, so the
adapter covers Paylocity's customers and not just Paylocity: see `_paylocity_notes` for both
host forms and for why `IsRemote` is ignored in favour of `LocationName`. (This line previously claimed Workable
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
`step_1d_2_linkedin_harvest` object in `run_[date].json` on every run with AT LEAST these fields:
the query used, `window_used`, the count of threads returned, companies extracted, and how many
were newly queued, plus **`job_alert_threads_seen` and `bodies_read` (2026-09-01, replacing the
narrower `jobs_noreply_threads_seen` / `digest_bodies_opened` pair added 2026-08-31)**. Keep
writing the old two as well when the sender split is known; they cost nothing and preserve
continuity with earlier runs.

These exist because the digest-body rule below was previously unauditable: the four original
fields are identical whether every body was read or none were, so a run that captured 1 company
out of 6 looked exactly like a run that captured all 6. That is precisely how the rule came to be
needed in the first place — on 2026-08-21 the step self-reported a plausible non-zero result while
dropping five companies from a single email.

**`bodies_read` should equal `job_alert_threads_seen`**; when it doesn't, name the shortfall in
the digest rather than filling in a number. **The 2026-08-31 pair was scoped too narrowly and
that is exactly how the bug below survived**: it audited body-reading only for `jobs-noreply@`,
the sender the spec already told you to open, and asked nothing about `jobalerts-noreply@`, the
sender the spec wrongly told you to skip. A metric that only measures the part you already
believed was correct cannot catch the part you got wrong. Count every job-alert thread from
either sender. **On 2026-07-30 this
step did not execute at all** — the run record contained zero mentions of LinkedIn and the step
was absent from `searches_run` — while roughly a dozen unprocessed alerts sat in the inbox. It
had run correctly the day before, so the failure mode is silent omission, not breakage. A logged
zero is verifiable; an absent section is indistinguishable from a skipped step.

1. Search Gmail for `deliveredto:{{CONFIRM_ALIAS}} from:linkedin.com newer_than:1d`.
   Zero results is normal and not an error.

   **DO NOT PICK THE WINDOW BY HAND. Run this first (added 2026-08-31):**

   ```bash
   .venv/bin/python pipeline/linkedin_window.py
   ```

   It prints the exact `newer_than:` value to use and the full query line. Use what it says.

   **WIDEN THE WINDOW TO COVER ANY GAP SINCE THE LAST RUN (added 2026-08-28).** The task runs
   `0 3 * * 1-5`, weekdays only, so a `1d` window on a **Monday** reaches back only to Sunday
   03:00 and silently drops Friday, Saturday, and Sunday: roughly **48 alert threads lost every
   week**, which is the pipeline's highest-yield discovery channel per call. Step 0.5's
   confirmation query does not have this problem because its `3d` window already spans Friday to
   Monday, which is likely why that number was chosen; this step was left at `1d` and the
   weekday-only schedule was never reconciled with it.

   **Why that rule became a script.** As prose it read "use `newer_than:4d` on Mondays, and widen
   similarly after any skipped or failed run (check the most recent `run_*.json` date)" — correct,
   and it asks a model mid-run to notice the weekday, locate the last run file, and do arithmetic.
   This step's own documented failure mode is being skipped while self-reporting success
   (2026-07-30: it did not execute at all and the run record contained zero mentions of LinkedIn),
   so a prose rule guarding against silent omission is itself silently omissible. The window is a
   pure function of the gap since the last completed run, so there is no judgment to preserve:
   `window = (today - last_run_date) + 1` day of overlap, capped at 7 days.

   The cap matters. If the gap exceeds 7 days the script says so **loudly** instead of quietly
   truncating: an unbounded window after a long outage would pull hundreds of threads into the
   run's context, which is its own failure. When that alert fires, **say in the digest that alert
   history older than the window was not reachable** rather than letting the run read as full
   coverage.

   Widening is close to free and cannot double-count: these are subject-line reads for
   `jobalerts-noreply@`, every extracted company goes through `check_company.py` before it can
   become a lead, and the hard cap of 15 new companies per run still bounds the downstream work. **Read snippets/subjects, not full bodies** —
   these emails are long and a full read of several will blow the run's context budget. The
   subject line alone carries the company and title (`<Title> at <Company>`), which is all this
   step needs.

   **STOP. READ THE BODY OF EVERY JOB-ALERT EMAIL. Rewritten 2026-09-01 — the previous version
   of this block was FACTUALLY WRONG and cost roughly five companies per email, on every email,
   for five weeks.**

   **BOTH job senders are multi-company digests. There is no single-role sender.**

   - `jobs-noreply@linkedin.com` — "Jobs You Might Be Interested In" digests. Subject names ONE
     company; body carries ~6 roles at ~6 companies.
   - `jobalerts-noreply@linkedin.com` — saved-search alerts. Subject is `<Title> at <Company>`,
     which **looks** like one role per email and is not. The body opens with
     `Your job alert for "<saved search>" in United States` and then lists **~6 roles at ~6
     different companies**, each a clean block of title / company / location separated by a
     `---------` rule. LinkedIn's own page type on these is `email_job_alert_digest_01`. The
     word `digest` is in the markup.

   **So: open the body (`messageFormat: PLAIN_TEXT`) of every message from either sender.** The
   body is strictly MORE structured than the subject and it states the location, which also
   removes the two-stage per-message location fetch described in the 2026-07-30 correction
   below. Ignore the tracking URLs; they are most of the byte count.

   **How this was wrong, and why the wrongness survived so long.** The 2026-08-21 fix caught the
   `jobs-noreply@` half correctly and then wrote down a confident, specific, untested claim about
   the other half ("The subject really is `<Title> at <Company>`, one role per email.
   Subject-only reading is correct here"). Nobody opened a `jobalerts-noreply@` body to check,
   because the rule said not to bother. It read as a finding when it was an assumption, which is
   the same failure mode as the "drafts only — no send" line in Step 5.

   Caught 2026-09-01 when Aneesh opened one in Mail and saw six companies where the pipeline had
   logged one. The email subject-lined "Senior Technical Account Manager at NiCE" contained NiCE,
   Evlo AI, **Vultr**, **Affirm**, Swooped, and RemoteHunter. Vultr was a tier2 Technical Account
   Manager, remote US, at a cloud-infrastructure company that would carry the +20 tooling
   vertical, and it was UNKNOWN to the watchlist and all three enrollment buckets. The Affirm
   card was a **Client Success Lead in Atlanta**, which directly contradicts Affirm's standing
   rejection reason ("Senior TAM is Remote Canada -- not US-reachable. No other fit-space role
   found"). Two more bodies read the same run confirmed the pattern held across unrelated saved
   searches, surfacing OCHIN, Samsung Healthcare USA, Resource Innovations, Zimmer Biomet, and
   Sundayy.

   **Cost, honestly.** This is now one body read per job-alert thread, roughly 15-19 reads a day,
   not "a couple per run." That is a real budget line and it is worth it: this is the highest-
   yield discovery channel in the pipeline and it was running at about 17% of its actual yield.
   If the run cannot afford every body, read them **newest first**, and record
   `bodies_read` vs `job_alert_threads_seen` in `run_[date].json` so the shortfall is visible
   instead of silent. Never go back to reading subjects only.

   **Aggregators appear far more often in bodies than in subjects** (Swooped, Hired,
   RemoteHunter, Jobot, Dice, ZipRecruiter, Talentify, Lensa). Drop them at extraction per 2b
   below; they are reposters, not employers.

   Proven on 2026-08-21, when Aneesh asked directly whether the pipeline was seeing what he saw
   in these emails. It was not. One digest subject-lined "Skydio" contained Skydio, Precisely,
   OpenAI, Drata, Bonterra, and JLL, every title tier1 or tier2, and the harvest had extracted
   only Skydio. **Bonterra and JLL were both UNKNOWN to the watchlist and to all three enrollment
   buckets**, so that single email cost two genuinely new companies on a day this step
   self-reported as having run correctly. Same class of silent failure as the 2026-07-30
   omission: the step logs a plausible non-zero result, so nothing looks broken.

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

### 1e-2. Housekeeping: vertical-bonus classification (max 3/run, added 2026-08-21)

`harvest_ats.py` auto-enrolls companies but **cannot assign a vertical bonus** — `score_bonus`
and `bonus_reason` are hand-curated on purpose, because an automated keyword pass was ~40% wrong
in both directions (CLAUDE.md Scoring Guardrails). So every auto-enrolled company arrives with
no vertical bonus at all and is under-scored by up to 20-30 points until someone classifies it.

Found 2026-08-21: **45 companies had accumulated this way since 2026-07-31**, including Snorkel
AI (AI/ML, fixed that day), Cribl, Drata, and Render (tooling). Cribl and Doppel were both fully
tailored while carrying the handicap, so this was silently suppressing real roles — the same
class of loss as the missing `headcount_band`, and it drains the same way.

Each run, pick up to 3 watchlist companies carrying `needs_vertical_classification: true`,
oldest `enrolled_date` first. For each, decide from the company's actual product:

- AI-native (the product IS an AI/ML system) → `score_bonus: 20`, reason "AI/ML platform (+20)"
- Tooling (devtools, dev infra, observability, security tooling, data/API platforms) →
  `score_bonus: 20`, reason "Developer/infra tooling (+20)"
- Genuinely both → `score_bonus: 30` (already at the cap)
- Neither → `score_bonus: 0` with a reason saying why, so it is not re-examined every run

Then remove the `needs_vertical_classification` flag and note it in
`run_[date].json → pipeline_notes`. **Verify from the company's product, not its name** —
"AI" in a company name is not evidence, and the false-positive rate is exactly why this is a
human-judgment step and not a script. Passion-domain and small-company bonuses are computed at
scoring time from `passion_domains` / `headcount_band` and are NOT set here.

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

**MULTI-BRANCH REQUIREMENTS: do not treat the loosest-sounding branch as an escape hatch
(added 2026-08-28, from a mis-scored role the same day).** When a JD states its years minimum
across several alternative functions ("N+ years in A, B, or C"), read the alternatives *as a
set* before deciding one is met. If every branch names the same domain, the loosest-sounding
one is a synonym, not a general exemption, and the cap should fire.

Baseten's GTM Systems Manager (2026-08-28) is the case. Its bar reads **"4+ years in GTM
systems, RevOps, or sales/business systems"**, and the third branch was read as satisfied by
Aneesh's Salesforce Service Cloud administration, so the cap was recorded as `none` and the
role got priority tier with a cover letter. All three alternatives are GTM-flavored:
"sales/business systems" is one compound category sitting alongside the other two, not a
licence to count any business system anywhere. Aneesh has zero years in any of the three as
that JD means them, so the cap should have fired and the role should have been light tier.

The underlying confusion is worth naming because it will recur: **Service Cloud and Sales
Cloud are the same platform and different jobs.** Cases, Omni-Channel routing, assignment
rules, and CES are what he administers; a GTM systems req expects someone who knows how a
revenue org runs, because those systems encode the sales process. Craft overlap is real,
domain overlap is near zero, and the keyword-overlap score should reflect that split rather
than crediting craft as though it were domain (that run scored it 27/30; ~20 was honest).

Contrast with the branches that ARE genuine exemptions, so this rule does not overcorrect:
Nimble Gravity (2026-08-25) asked for "enablement, training, consulting, organizational
adoption, or a related field", which spans several distinct functions and is honestly met by
support-ops training ownership; 7AI (2026-08-28) asked for "TAM, Customer Success, Solutions
Engineering, Implementation, **or a similar customer-facing role**", where the final clause is
explicitly open-ended. The test is whether the alternatives span different functions or
restate one domain.

**Record the outcome of this judgment every time, in `hard_req_cap_trigger` (Step 6).** Quote
the triggering requirement verbatim when the cap fires; write the literal `none` when you
checked and it does not. Leaving it blank discards the one signal that separates a correctly
capped role from a missed one — which is the state the tracker was in before 2026-08-21, when
`unmet_hard_reqs` was all there was and could not tell those apart.

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

**Use `fetch_jd.py` FIRST, not WebFetch (changed 2026-08-21).**

```bash
.venv/bin/python pipeline/fetch_jd.py --from-hits pipeline/jobs/ats_hits_[date].json --match "<title fragment>"
```

It hits the ATS's own JSON API (Ashby, Workday, Greenhouse, Lever, SmartRecruiters, **Comeet**)
and prints title, location, remote flag, posting date, compensation, and the **full description
text** for you to read directly. Accepts bare URLs as positional args too, and `--match` is
repeatable. Only fall back to WebFetch for an ATS it does not cover (Pinpoint and Rippling have no
per-posting JSON endpoint), then to WebSearch for a cached or mirrored copy. If the JD is
unreachable two runs in a row, drop it to the near-miss list with a note rather than stalling.

**Comeet was wrongly listed as unreachable here until 2026-08-31, and it cost a real read.** The
Comeet *hosted page* is a Spark Hire template, which is true and is why WebFetch fails on it; that
got generalized into "no per-posting JSON endpoint," which is false. Comeet's BOARD endpoint
returns every posting with a `details` array carrying the full Description and Requirements HTML,
the same whole-board-filter-locally shape as Ashby, and `poll_ats.py` had been reading it since
2026-08-20. On 2026-08-31 Stampli's "Implementation Consultant/Onboarding Specialist" took the top
pre-score of the run (74) and went to the near-miss list as "JD unreadable" — when in fact it pays
**$80–95K base**, under both the $100K floor and the $90K near-miss floor, and sits in the Mountain
View office three days a week. It was a hard-filter elimination wearing a near-miss label.
`fetch_jd.py` now resolves the Comeet uid from the URL and the widget token from the watchlist
entry. **Generalize the lesson, not the symptom: a broken rendered page is not evidence about the
API behind it.**

Why this replaced WebFetch as the default: **WebFetch does not work on three of the five ATSes
that actually reach the shortlist.** Ashby and Workday are JS-rendered and return a page
containing only the job title; Comeet serves a Spark Hire template full of `{{position.name}}`
placeholders and the words "no open positions"; `job-boards.greenhouse.io` 302s to company
domains (Wiz does this). The summarizer then reports "the content appears to be empty," which
reads like a transient error rather than a structural one, so the natural response is to retry
and burn more budget. On 2026-08-21 recovering five JDs by hand consumed the run's entire
WebSearch allowance and **Step 1c's ~14 daily board dorks were skipped outright.** This helper
takes JD retrieval off the search budget so discovery and JD-reading stop competing.

It also fixes the summarization problem below at the root: it returns raw JD text, so there is
no small model in the loop deciding which requirements matter.

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

**Do NOT report a poller-vs-JD posting-date difference as drift without checking the field
(added 2026-08-25, after it was reported as a bug twice in two days).** `fetch_jd.py` and
`poll_ats.py` now both read Greenhouse's `first_published`, so their dates agree. They did not
agree before 2026-08-25: `fetch_jd` preferred `updated_at`, and large Greenhouse boards bulk-
refresh every open req daily, so `updated_at` reads "today" on a req published months ago. That
produced two phantom findings — Snorkel AI (`first_published` 2026-07-31 vs `updated_at`
2026-08-24) and Sprout Social (2026-07-23 vs 2026-08-24) — where the poller had been correct all
along. Both are fixed. If a difference still appears, check which field each side read before
calling it drift.

Workday is the real exception, and it is now handled. Its CXS *list* response has no ISO date,
only `postedOn` as a relative string, and `"Posted 30+ Days Ago"` is a **floor, not a value**.
That floor used to be approximated as 31 days, which passed the 40-day filter and let genuinely
stale reqs onto the shortlist — Jackson Healthcare's "Enterprise AI Enablement Lead" reached the
2026-08-25 shortlist as 31 days old when its real `startDate` was 2026-06-02, i.e. 84 days.
`extract_posted_date` now resolves any `N+` floor against the CXS *detail* endpoint, which does
carry a real `startDate`, and falls back to the bare floor if that lookup fails. Exact
`"Posted N Days Ago"` values, `"Today"`, and `"Yesterday"` are unchanged.

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

## Step 3.5: Stretch lane — FDE / Solutions Engineer conditional review (added 2026-08-30)

Aneesh's explicit call, 2026-08-30: he knows Forward Deployed Engineer is a title he is
mostly not qualified for yet, he is actively working on getting qualified for it (and for
Solutions Engineer), and he wants conditionally-viable postings surfaced anyway; his words:
"I can take risks and see if I can get them." This lane makes those postings VISIBLE
without reversing the 2026-07-09 FDE demotion or spending full-tailoring budget on long
shots. It changes visibility, not scoring: do not raise FDE's tier, do not remove it from
`jd_verification_required_titles`, and never let a stretch role displace one of Step 2's
top 3-4 normal-lane picks.

Mechanics; hard cap of 2 JD reads per run for this lane:

1. Collect today's entries (poller `matched` + `borderline`, plus WebSearch finds) whose
   title contains "Forward Deployed", "FDE", "Deployed Engineer", "Solutions Engineer", or
   "Solution Engineer", excluding any that already earned tailoring on the normal path
   (a tier3 SE role scoring ≥88 already gets full treatment; this lane exists for the ones
   that don't). Known limit, accepted at creation: an FDE role pre-scoring +8 that misses
   the top-25 shortlist is invisible to this lane too. If the lane logs zero candidates
   for ~2 weeks while FDE reqs are visibly live at watchlist companies (Cresta, Decagon,
   Baseten, Modal, and LangChain all carry them per their watchlist notes), say so in
   digest housekeeping rather than silently accepting it.
2. Take up to 2, highest pre-score first, and read the full JD (`fetch_jd.py`, verbatim
   requirements; these are exactly the titles the verbatim rule exists for). Surface a
   role ONLY if ALL four gates hold:
   - **Location** qualifies under the standard rules (remote US or metro Atlanta).
   - **No stated years-minimum in software engineering and no non-negotiable CS degree.**
     "Or equivalent experience" / "non-traditional backgrounds welcome" counts in favor.
   - **The coding bar is scripting/API level** ("Python or SQL a plus", "comfortable with
     APIs", "scripting experience"). Kubernetes, Terraform, CI/CD ownership, or
     "write/ship production code" in the requirements → fail closed.
   - **Domain overlap with an SME area**: support/CX AI, IoT/smart building, or the
     Salesforce ecosystem; somewhere the SME-first argument can carry the title gap.
   A failed gate costs at most one digest housekeeping line ("checked, disqualified by
   <quoted requirement>") and no further budget.
3. A passing role goes in its own digest section, **"Stretch lane (FDE/SE) — risk
   accepted"**: title, company, salary, apply link (the no-exceptions link rule applies),
   which gates it passed, and the gap that remains. LIGHT tailoring at most, and only when
   its honest score independently clears the light threshold; never a cover letter from
   this lane. The HARD-REQUIREMENT TIER CAP applies with no special pleading; the lane's
   gates overlap with the cap on purpose, so a role that passes them usually escapes the
   cap honestly. If Aneesh wants a full package for one, he'll ask for it by name.
4. Log `stretch_lane: {candidates_seen, jds_read, passed, surfaced_titles}` in
   `run_[date].json` every run, zeros included: a logged zero is verifiable, while an
   absent section is indistinguishable from a skipped step (the Step 1d-2 lesson).

## Step 4: Tailor resumes and cover letters

### 4-pre. ALREADY-APPLIED GUARD (mandatory, before writing a single line of any resume)

**For every role about to be tailored, grep `outcomes.csv` for its URL and for its company:**

```bash
grep -i "<company>" pipeline/outcomes.csv
```

If a row exists with the same URL, or the same company plus a title that means the same
requisition, **STOP. Do not tailor it.** Report it as already-handled and say what stage
that row is in. Re-applying to a requisition Aneesh already applied to is worse than
surfacing nothing.

**`seen_jobs.json` IS NOT THIS CHECK, and using it as one is how this rule got written**
(2026-09-01). Mid-run I found n8n's "Technical Account Manager (US)" live on a watchlist
board, grepped `seen_jobs.json`, got **zero** n8n keys, and concluded the pipeline had never
seen the role. I re-derived its score from scratch (108, which happened to match exactly),
declared it the pick of the run, and had written most of the tailored resume when Aneesh said
he thought he had already applied. He had. `outcomes.csv` carried
`2026-08-26, n8n, Technical Account Manager (US), <the same Ashby URL>, 108, applied` the
whole time, and the rejection had landed that morning.

**CORRECTED SAME DAY, after a full trace: the "zero n8n keys" result was itself a bug in the
check, and the first version of this section wrote the wrong root cause into the spec.**
`seen_jobs.json` is NOT a flat dict: the top level is `{schema_version, description, jobs}`
and every entry lives under `jobs`. Iterating top-level keys returns three metadata keys and
a clean, plausible zero for any company. The n8n key (`n8n::technical-account-manager-us`)
was present under `jobs` the entire time — written by `update_tracking.py` when the role was
tailored on 08-26 — and the poller had been correctly deduping it as `reseen` on every run
since. There was no poller miss and no coverage gap; there was a mis-shaped query trusted
because its zero looked clean. The original version of this section claimed "n8n arrived
through a recruiter message, not the poll, so it was correctly absent from seen_jobs" —
plausible, load-bearing, and false, which is precisely the failure mode documented for the
`jobalerts-noreply@` rule in Step 1d-2.

Both lessons stand, and they compose:
1. **The applied-check belongs to `outcomes.csv`**, which records every tailored role from
   every channel. `seen_jobs.json` exists for the poller's dedup, whatever its exact contents.
2. **Any query of `seen_jobs.json` must read the `jobs` sub-key.** A top-level grep returns a
   false zero for every company. When a check of a tracking file produces a surprising
   clean zero, verify the file's SHAPE (`grep` the raw file for the literal key) before
   building any conclusion on it.

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

**PDFs render into `tailored/apply_now/`; everything else stays in `tailored/`.** The
markdown and JSON are working files and belong with the rest of the archive; only the two
PDFs Aneesh actually uploads go in the folder his upload dialog opens on. Step 0 item 5
rotates that folder; nothing here needs to clean it up.

1. Tailored resume markdown → `tailored/Aneesh_Khan_[Company]_[Role].md`
2. Resume JSON → `tailored/..._data.json` (schema: `pipeline/pdf_helpers.py` docstring)
3. `.venv/bin/python pipeline/render_pdf.py resume <data.json> tailored/apply_now/<name>.pdf`

   **Also render an ATS variant for high-effort ATSes (added 2026-08-28):**
   ```bash
   .venv/bin/python pipeline/render_pdf.py ats <data.json> tailored/apply_now/<name>_ATS.pdf
   ```
   Same JSON, no extra authoring. Do this whenever the apply path is **Workday, Paylocity,
   Taleo, or iCIMS** — the ones that make Aneesh retype his whole work history after an
   upload. Keep the styled `resume` output as the one a human reads, and for ATSes that parse
   well (Greenhouse, Ashby, Lever).

   The confirmed defect it fixes: in the styled template the centered contact line extracts as
   `' Atlanta, GA | Remote  \x7f  770-402-8907  \x7f  khan.aneesh10@gmail.com  \x7f  LinkedIn'`
   — the `&bull;` separator comes back as **DEL (0x7f)**, so the whole contact block is one
   line delimited by control characters, and the LinkedIn URL is unrecoverable because it
   lives in an `<a href>` rather than in the text layer. Contact fields are the first thing
   autofill populates. The ATS variant emits four plain lines, one field each.

   **Be honest about the limit.** Body text and reading order extract fine in BOTH renders, so
   this is a narrower fix than "the template is why Workday's parse is bad." Whether it
   improves Workday's field MAPPING enough to reduce retyping is still unproven; only running
   it through a real Workday autofill settles that. Don't claim more than the contact-block
   result until someone has.`
4. **Coverage check:** write the JD's top-15 phrases to
   `tailored/Aneesh_Khan_[Company]_[Role]_phrases.json`, then
   `.venv/bin/python pipeline/check_coverage.py <resume.md> <phrases.json>`
   Target ≥80% (12/15). Below that: apply the second-pass rule (CLAUDE.md Step 6), revise,
   re-run. Never fabricate to close a gap — flag genuine gaps honestly.
5. Cover letter (full-tailoring tier only) → `_cover.md` + `_cover_data.json` +
   `.venv/bin/python pipeline/render_pdf.py cover <cover_data.json> tailored/apply_now/<name>_cover.pdf`
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

## Step 4.5: AI-writing pass on the cover letters (added 2026-09-01, Aneesh's request)

Runs **after all tailoring, before the digest**, so fixes land before the PDFs are final.

**Cover letters only.** Do not run this on resumes: resume bullets are deliberately terse,
verb-initial fragments, and the pattern catalog would flag a register that is correct there.

### 0. NEVER EDIT A LETTER THAT HAS ALREADY BEEN SENT

`check_voice.py` resolves each letter to its `outcomes.csv` row and labels it. Act only on
`surfaced` and `drafted today, not yet tracked`:

| Label | Meaning | Action |
|---|---|---|
| `[drafted this run]` | you just wrote it, so it cannot have been sent | **edit freely** |
| `[stage=applied]` and every other sent stage | already went out | **report only, never edit** |
| `[SENT STATUS UNKNOWN, not written by this run]` | anything else, **`surfaced` included** | **ask Aneesh first** |

**`surfaced` is NOT a green light**, and this is the part that bit twice. It means no
confirmation was matched, not that the letter went unsent: confirmations arrive only through
the Gmail `+jobs` filter, which has documented capture gaps (the 2026-08-27 Datadog invitation
came from a personal recruiter domain and missed all three filters) and lags by hours or days
regardless. On 2026-09-01 both **CodePath** and **Cursor** read `surfaced` and Aneesh had
already sent both.

**Pass the run's own letters explicitly with `--drafted-now`.** A file-mtime heuristic was
tried and is also wrong: several runs happen per day, so "modified today" caught letters an
earlier run wrote and Aneesh sent hours later. Only the caller knows what it just authored, so
the script takes that as an assertion rather than guessing. A bare `--today` invocation is a
REPORT and greenlights nothing.

A sent letter is the record of what the employer actually read. Editing it makes the archive
disagree with what was submitted, and later nobody can tell which version went out: the same
class of mistake as a tracker column that means two things. Carry the finding into the next
letter instead. A sent letter never fails the gate, so it cannot block a run.

**This step exists because of a real error on 2026-09-01.** The contraction fix was applied to
all six letters from 2026-08-28 before anyone checked their status. Four had already been
submitted: Outreach (the 116, applied), Baseten (applied), Seven AI (applied), and Paylocity,
which had already come back **rejected**. Only Benchling and Brown & Brown were still editable.
One `grep` on `outcomes.csv` first would have made that obvious. Note the ordering trap that
made it easy to miss: this step runs BEFORE Step 6 writes tracking, so "no row" is the normal
state for the current run's own letters and cannot be used as a proxy for "unsent" on its own.

### 1. Mechanical gate

```bash
.venv/bin/python pipeline/check_voice.py --drafted-now tailored/Aneesh_Khan_[Company]_[Role]_cover.md ...
```
List every letter THIS run wrote. Use `--today` only for a read-only sweep; it greenlights
nothing by design.

Three arithmetic checks that do not need judgment: contraction ratio, em-dash count against
the CLAUDE.md cap of 2, and the share of sentences in the 15-25 word band. Every line also
carries the stage label from item 0. Exit code 1 on any actionable failure; already-sent
letters report their findings without failing. Fix what it reports **on editable letters only**.

**The contraction check is the one that earned this step.** On 2026-09-01 the avoid-ai-writing
skill audited the Brown & Brown letter and found 0 contractions against 13 expansions, against
a personal corpus that runs 5-15 contractions and zero expansions (Vanta AI Optimization 14,
Zocdoc 15, WitnessAI 13). It was not one letter: **all six written on 2026-08-28 had inverted
the ratio.** No individual sentence looks wrong, which is exactly why it survived a whole day
of output. The tell is the aggregate, and only counting finds it.

### 2. Judgment pass

Invoke the **`avoid-ai-writing`** skill in **detect mode** on each letter written this run. It
defaults to Aneesh's voice profile. Read its output and apply the clear problems; leave the
judgment calls unless one is obviously right. **The item 0 stage gate binds here too**: audit
a sent letter if it is useful, but the output is a lesson for the next letter, not an edit.

**Protected — never "fix" these**, they are the voice and the skill's own profile carves them
out: the opening line (the anti-template log in Step 4 item 5 governs it, not this step), the
honesty moment naming a real gap, the single-sentence pivot, transitional qualifiers ("having
said that", "given that"), and sports or nature analogies.

**Targeted edits only, never a wholesale rewrite.** These letters are built from the CLAUDE.md
voice rules plus the career-narrative skill; a full rewrite would sand off the deliberate
honesty moments and the hard-won opener. If a letter trips five or more vocabulary flags across
several categories, that is a signal the draft was wrong to begin with: say so in the digest
rather than laundering it.

### 3. Re-render whatever changed

Any letter whose markdown you edited needs its PDF rebuilt, and the ATS variant too if one
exists:

```bash
.venv/bin/python pipeline/render_pdf.py cover <cover_data.json> tailored/apply_now/<name>_cover.pdf
```
Remember the `_cover_data.json` carries the prose separately from the `.md`. **Edit both**, or
the PDF silently keeps the old text. This is the easiest way for this step to appear to work
while changing nothing.

### 4. Report

One digest line naming what was flagged and what was changed. Report a clean pass too, in one
short clause: a step that only speaks up when it fails is a step nobody can tell ran.

## Step 5: Email digest

Gmail MCP `create_draft` to **{{DIGEST_RECIPIENT}}**.

**Drafting is a CHOICE, not a capability limit. Corrected 2026-08-28.** This file and the
scheduled task's SKILL.md both said "drafts only — no send, no attachments" for weeks, and both
were wrong. `send_message` exists, takes a `draftId`, and sends immediately; `create_draft` and
`send_message` both accept an `attachments` array (base64, 25MB combined). Verified by loading
the schemas and by attaching a PDF to a live draft. Nobody checked, because the instruction read
as a fact about the environment rather than a decision, so the tool was never even loaded —
deferred tools are names until fetched, and searching only for what the instructions imply you
need will confirm whatever they already claim.

**SEND the digest. Aneesh's explicit call, 2026-08-28.** Create it with `create_draft`, then
send it with `send_message` passing that `draftId`. Do not leave it sitting as a draft.

His reasoning, and it overrides the argument this file made first: *"draft is just another step.
I don't care if there are multiple sends if I come back."* The case for drafting was that the
digest gets composed mid-run off numbers still under review, and this one needed two corrections
after creation (three roles turned out hybrid rather than remote; a fifth role was found and
rescored the run). That is real, but the cost it avoids is a tidy inbox, which he does not value,
while the cost it imposes is a manual step on every single run, which he does. **If the digest
needs correcting after it has gone out, send a follow-up rather than trying to suppress the
first.** A superseded email in his inbox is cheaper than a digest he never receives because
nobody opened the draft.

Still create the draft first rather than composing straight into `send_message`: it costs one
extra call and gives a recoverable artifact if the send fails partway.

**Do not spend budget auto-attaching the PDFs** (Aneesh's call, 2026-08-28). It works, but he
applies through each ATS's upload dialog, which reads from the `tailored/` folder directly, so an
email attachment is a detour rather than a shortcut. It also costs roughly 4k tokens per two PDFs
in base64, all of which has to pass through the run's context. The digest's "attach the PDFs
listed at the bottom" line stays as a manifest of what to upload from disk.

General rule this run established, worth carrying to any other routine: **an autonomous run will
not send, post, or delete unless its instructions say so explicitly.** That default is right. It
just has to be a stated decision rather than a claim about what the tools can do, or nobody
re-examines it.

- Subject: `Daily Job Matches — [date] ([N] jobs)`
- Top note: "Open this draft, attach the PDFs listed at the bottom, and send."
- **Pass RAW HTML to `htmlBody`, never HTML-escaped entities.** Write `<p>`, not `&lt;p&gt;`.
  Escaping the markup makes Gmail render every tag as literal visible text and the digest
  arrives as an unreadable wall of angle brackets (happened 2026-07-27). If a draft has
  already been SENT, `update_draft` fails with "Message not a draft" — create a corrected
  replacement draft rather than trying to patch it.
- HTML table: title, company, location, salary, score, unmet hard reqs, apply link.

  **EVERY table that names a role carries its apply link. No exceptions (added 2026-08-28,
  Aneesh's call).** Splitting the picks into "send these" and "your call" is good and should
  continue, but on 2026-08-28 only the first table had an Apply column, so deciding to pursue a
  "your call" role meant going and finding the posting by hand. That inverts the point: the
  roles needing a decision are the ones where friction actually costs a send. Same rule for the
  near-miss and "also live (FYI)" sections, which are lists of real postings even when they are
  not recommendations.

  **Watch the header-row contrast in dark mode.** The 2026-08-28 digest styled `<th>` rows with
  an inline background plus `color:#fff`, and in Aneesh's dark-mode client the header text
  rendered nearly invisible against the background: the column labels were unreadable in both
  tables. Not fully diagnosed (Gmail dark mode rewrites some inline colors and not others), so
  the safe move is to stop depending on a background/foreground pair for legibility. Use plain
  `<th>` with `<b>` and let the client theme it, or pick a combination that reads correctly
  whether or not it gets inverted.
  (JD coverage % was dropped from the table 2026-08-15 — it's a pass/fail build gate with
  no variance (94.6% mean across applied rows), so showing it invited ranking by it.
  `unmet_hard_reqs` is the readiness signal.)
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
- **"Below the cutoff (ranks 41+)" section (added 2026-09-01):** the poller's `near_window`
  list as one-liners — `[pre_score] Company: Title | location | link`. Collapse obvious
  sibling duplicates to one line ("also NYC, SLC"). This section is FYI parity with the
  LinkedIn alert inbox; no scoring, no tailoring diffs. If an entry was promoted to full
  scoring under the Step 1a exception, say so where it appears in the main table instead.
  Report `stats.tier1_guaranteed` alongside the other provenance counts in housekeeping.
- "Also live (FYI)" lines for same-company extras; near-misses section at the bottom
  (one line each with reason tag, e.g. "scored 74" / "pay $92K midpoint"); omit if none
- **"Manual channel — no pollable board"** section: companies rejected at Step 1d that carried
  `manual_review: true`. One line each (company, the flagged title and location, careers-page
  link if found). Omit the section entirely if none. These are NOT scored or tailored; they are
  roles the automated layer structurally cannot watch, surfaced once so Aneesh can decide.
- **"Stretch lane (FDE/SE) — risk accepted"** section (Step 3.5): at most 2 lines, each
  with apply link, gates passed, and the remaining gap. Omit the section entirely when
  nothing passed; a "checked, disqualified by X" line goes in housekeeping instead.
- **Apply-folder line.** Carry the `DIGEST LINE:` printed by `rotate_apply_folder.py` at
  Step 0 whenever it names any evictions, and point the file manifest at
  `tailored/apply_now/`. Omit the line entirely when nothing was evicted for being unsent —
  a role leaving because it was actually applied to is housekeeping, not news.
- Note any ATS errors, capped companies, enrollments/rejections, and skill gaps observed
- **"Full breakdown: what was checked" section (added 2026-08-06, standing requirement).**
  Aneesh asked for this after catching a real discovery-layer miss by hand (Hercules, Philips,
  and Headway all came from him screenshotting the LinkedIn app's own Jobs recommendation feed —
  a product surface none of the automated channels touch, since Step 1d-2 only consumes forwarded
  *job-alert emails*, a different LinkedIn surface entirely). Every digest must end with a
  bulleted, source-by-source account of what ran and what it found, so a miss like that is
  visible immediately rather than discovered by chance:
  - ATS poll: companies polled, jobs scanned, matches, shortlist size
  - WebSearch discovery: which sources the Step 1c rotation selected and ran, **which ones it
    deferred to the next run**, and a compressed list of what surfaced (mostly-known vs.
    genuinely new). Carry `websearch_rotation.py`'s staleness alarm here verbatim when it
    fires — a rotation is only honest if nothing rots at the back of it.
  - Discovery feeders: poll_remotive/poll_80k/harvest_hn_hiring status (including DEGRADED/skipped)
  - Blind-spot rotation: which named employers were checked this run
  - Unpollable-backlog monthly check: due/not-due, and if due, what was found (skip this line
    entirely on a not-due day — silent housekeeping, same as monthly WebSearch sources)
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

   **`unmet_hard_reqs`, `vendor_tool_named_in_jd`, and `hard_req_cap_trigger` are all
   required.** You already identify each during tailoring; these fields just stop them
   from being trapped in prose where nothing can count them.
   - `hard_req_cap_trigger` (added 2026-08-21): the requirement that fires the
     HARD-REQUIREMENT TIER CAP, quoted verbatim from the JD — or the literal string
     `none` when nothing does. **Write `none`; do not leave it blank.** Blank means "never
     recorded" and is reserved for the 219 rows that predate the field. This is a
     *different question* from `unmet_hard_reqs`: that counts every disclosed gap, most of
     which are soft, while this one names only a stated years-minimum in a function with
     zero years, or something the JD calls non-negotiable. A role can honestly carry 2
     unmet hard reqs and still take full tailoring — Vanta on 2026-08-21 did, because its
     JD states no years minimum. Recording both is what lets `audit_scores.py` tell a
     correct call from a missed cap instead of flagging every gap for manual review.
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
4. **Score calibration audit (added 2026-08-21, report-only):** run this AFTER step 2, so
   today's rows are already in `outcomes.csv` and get audited on the same run that scored
   them.
   ```bash
   .venv/bin/python pipeline/audit_scores.py
   ```
   ```bash
   .venv/bin/python pipeline/audit_scores.py --sweep-drift
   ```
   The first re-derives every recorded score from this file's own Step 2c rubric and writes
   `pipeline/logs/score_audit.html`. It does **not** produce "the right score" — half the
   rubric (keyword overlap 0-30, the two reach penalties) is judgment and isn't recoverable
   from stored data — so it reports a legal envelope per row and flags scores that fall
   outside it. Console output lists flagged rows with dates.

   **Carry into the digest only:**
   - Any flagged row dated **today**. That is the whole point of running it here: the
     Chainguard mis-score (2026-08-10, scored 104 and fully tailored against a "5+ years"
     bar it didn't meet) was caught by hand hours later, and catching that class of error
     the same run is cheaper than correcting a sent application.
   - Anything from `--sweep-drift` other than the single line `no queued rows carry a
     retired-rule score.` That line is the normal case and means nothing to report. A table
     instead means a scoring rule changed and left already-recorded scores stranded under
     it, so the queue now disagrees with the rubric: report the row count, the tier changes,
     and that `--apply` is waiting on him.

   **Do not** carry the standing backlog into the digest — `REVIEW` findings and undated
   rows are a known set, not news, and repeating them daily trains you to ignore the step.

   **Never run `--sweep-drift --apply` during an autonomous run.** It rewrites `fit_score`,
   flips rows to `stage=expired`, and edits notes. Same rule as `age_report.py --apply`:
   mutating the tracking file is Aneesh's call, and the preview is what tells him it's
   needed. (The sweep is idempotent and backs up first, but that is a safety net, not a
   licence to run it unattended.)
5. Write `pipeline/jobs/jobs_[date].json` (full structured records) and
   `pipeline/jobs/run_[date].json` (run metadata: searches run, stats, capped companies,
   pipeline_notes, near_misses array, email draft ID).
6. Update `pipeline/SESSION_STATE.md`: today's output, near-misses, housekeeping, action
   queue. Session state never goes in `CLAUDE.md`.
7. Add a `channel_stats` block to `run_[date].json` (schema added 2026-08-10, see any run
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

   It also prints an **"Unpollable companies with a role worth chasing"** section (added
   2026-08-14, from Aneesh asking for a weekly punch list of companies the automated layer
   structurally can't reach): a capped batch (`UNPOLLABLE_WEEKLY_CAP` = 20, oldest
   `rejected_date` first) of `enrollment_candidates.json → rejected` entries tagged
   `unpollable: true` — meaning no ATS board was ever found for them, as opposed to a board
   being found and the company rejected for fit/geo/category reasons — that haven't been
   surfaced in a prior weekly report yet. This runs regardless of whether the channel-stats
   window has data, so it fires even on an early week.

   **GATED ON CONFIRMED ROLE SIGNAL as of 2026-08-31 (Aneesh's call), and the gate is the
   point.** Only entries carrying `manual_review_why` are surfaced: companies where Step 1d-2
   saw an actual tier1/tier2/tier2c title in Atlanta or remote-US. Ungated, this section handed
   him 20 companies a week sorted by nothing but rejection date, and a 30-company dry run of
   that exact population returned **zero enrollable companies** — 23 had no board at all, 3 had
   boards with no fit-titles, and the batch was dominated by AI-policy nonprofits (GovAI, Pax
   Sapiens, CivAI) and mega-enterprises (Microsoft, Wabtec, Epiroc) that will never run a
   supported ATS. It was a standing weekly chore with a measured yield of nothing.

   The premise had also expired. The punch list existed because `harvest_ats.py` could not
   resolve non-obvious slugs, so a human searching by hand genuinely beat the machine. The three
   gaps behind that (TLD stripping, legal-form suffixes, dotted slugs) were fixed 2026-08-31 and
   verified on 18/20 known cases. What still justifies human attention is a company where a REAL
   MATCHING ROLE was seen and the poller structurally cannot reach it — which is exactly what
   `manual_review_why` records, and the same principle behind `_unpollable_backlog_companies`.

   The gate cut the list from 189 to **21**, and every survivor names its role (Engagifii's
   Atlanta Director of Product Support at $93.5–115K, Barracuda's Manager Technical Support in
   Alpharetta, GitHub's Senior Product Operations Manager at $124–329K remote). Include the full
   batch in the report; this is the part Aneesh acts on, so don't compress it away.

   Ungated entries are **not deleted**, only unsurfaced: `--all-unpollable` restores the old
   behaviour for a deliberate one-off sweep. Two known rough edges, both minor and left alone on
   purpose rather than fixed with brittle text matching: an entry whose `manual_review_why`
   records that the role was checked and CLEARED still appears (LP Building Solutions, a Nashville
   hybrid req that fails the location gate), and a company already surfaced once in a daily
   digest's "Manual channel" section can appear again here, since the two use separate
   surfaced-flags. Reading the entry explains both.
3. Create a **separate** Gmail draft (`create_draft`, not `update_draft` on the daily digest),
   **then SEND it with `send_message` passing that `draftId`** — same as Step 5:
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
6. Note the draft ID in `run_[date].json → weekly_channel_report_draft_id`, the sent message id
   in `weekly_channel_report_sent_message_id`, and one line in `SESSION_STATE.md`. Do not mention
   this step in the main digest email at all — it is its own email.

**Send this report; do not leave it as a draft. Aneesh's explicit call, 2026-08-31.** This step
said only "create a draft" and called it "its own send decision" for three weeks, which is why the
2026-08-31 run drafted it and stopped: Step 5 carried an explicit send instruction and this one did
not, so the autonomous run correctly declined to infer one. The reasoning that settled Step 5 on
2026-08-28 applies here unchanged and always did — a draft he has to open and send is just a manual
step, and he does not mind a follow-up email if a report needs correcting after it goes out. The
only reason the two steps disagreed was that nobody carried the decision across.

The general rule this illustrates is worth keeping: **an autonomous run will not send unless its
instructions say so explicitly, and "its own send decision" is not an instruction.** If a future
step should send, write "send it" in that step. Do not rely on a neighbouring step's precedent.

## Step 7: Sync the public repo

Framework lives in the public repo `neeshykha/claude-resume-pipeline`. Personal data
(`master_resume.md`, `tailored/`, `pipeline/jobs/`, `outcomes.csv`, `SESSION_STATE.md`) is
gitignored — never `git add -f`, never restore run state into `CLAUDE.md`.

```bash
.venv/bin/python pipeline/repo_sync.py --stage
```
```bash
git diff --cached --quiet || git commit -m "pipeline: daily run $(date +%F)"
```
```bash
git push
```

**`repo_sync.py --stage` replaced a bare `git add -A` on 2026-08-21, and the reason is a
real incident, not tidiness.** `git add -A` stages the whole working tree, so an unattended
run commits whatever a human happened to have open. That day a run swept an uncommitted
edit to `audit_scores.py` into a commit titled "add Applications Manager family to tier2c",
where it is now permanently mislabeled — and then did it a *second* time during the fix,
committing a scratch line into `check_coverage.py` under a commit about Avalara.

`--stage` diffs the working tree against the Step 0 baseline and stages only paths that
changed **during this run**, so the rule is temporal rather than a path allowlist. A
frozen list of paths would be wrong: runs legitimately commit across
`watchlist_companies.json`, `enrollment_candidates.json`, this file, `harvest_ats.py`,
`README.md`, and `CLAUDE.md`, including same-run fixes to the pipeline's own code.

Read its output. Anything under "left alone" is Aneesh's in-progress work: **do not stage
it, do not `git add -f`, and name it in the digest** so it isn't silently stranded. If it
warns that no baseline was found, Step 0 item 5 was skipped — it falls back to old
`git add -A` behaviour, so say so in the digest rather than letting it pass.

If push is rejected: `git pull --rebase` once, push again; still failing → note in digest
and move on. Never force-push.

## Important rules

- NEVER fabricate experience, certifications, or skills
- NEVER modify `master_resume.md` or `generate_pdf.py`
- Zero matches → brief email: "No strong matches today"
- Watchlist companies: auto-surface CSM/TAM/Solutions roles even below threshold
- Unknown posting date → assume ≤7 days for direct ATS sources; skeptical for aggregators
- NEVER WebFetch ATS boards inline — always `poll_ats.py`
