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
- Coverage checks via `check_coverage.py` on the `_data.json` — never hand-rolled bash loops
- Tailored packages are drafted by writer subagents (Step 4-W) and gated by ONE command,
  `fit_check.py`: coverage, voice, em-dashes, both renders, and both page counts in a single
  report — never a separate call for each, and never a page count improvised with `mdls`
  or a throwaway script
- LinkedIn alert bodies via `harvest_linkedin.py` (Step 1d-2) — a Haiku helper fetches them,
  you never fetch or read them
- Full JDs via `fetch_jd.py` (Step 3) — never WebFetch an Ashby/Workday/Comeet posting, they
  are JS-rendered or templated and return the title only, which costs retries and search budget
- Tracking updates via `update_tracking.py` — never hand-edit `seen_jobs.json`
- Application-confirmation promotions via `mark_applied.py` (Step 0.5) — never hand-edit
  `outcomes.csv`'s `stage`/`applied_date` columns
- Read `master_resume.md` ONCE, for scoring and for briefing the writers; each Step 4-W
  writer reads its own copy
- JD reading for the shortlist is FANNED OUT at Step 2-JD: Python fetches, parallel Sonnet
  workers read and write compact cards, you read one table. Never pull 40+ raw JDs into
  this context.
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
   over em-dashes; max 2 em-dashes per document. For tailored packages `fit_check.py`
   (Step 4-W) counts them in the text that renders and fails the package when over. For
   anything else the run writes, `grep -c '—' <file>` is allow-listed, but it counts
   LINES containing a dash, not dashes: a paragraph is one line, so read the hits.
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
   `deliveredto:{{CONFIRM_ALIAS}} -from:linkedin.com -from:donotreply@jobalert.indeed.com -from:donotreply@match.indeed.com newer_than:3d` (the 3-day window
   gives safe overlap across runs; already-promoted rows won't match again since matching
   only looks at `stage=surfaced` rows).

   **The `-from:linkedin.com` exclusion is load-bearing.** LinkedIn job alerts are forwarded
   to this same alias on purpose (one verified forwarding address instead of two) and are
   consumed by Step 1d-2 as company discovery. Without the exclusion they would flow into
   this step's confirmation matcher, which is looking for "did he apply" evidence and would
   find dozens of roles he has never applied to.

   **The two Indeed exclusions exist for the same reason (added 2026-09-30).** Aneesh set a
   filter forwarding Indeed's job-alert and "Match" emails to this alias so their cards can be
   read as company discovery. They are alerts, not receipts. The exclusion names the two alert
   senders exactly rather than all of indeed.com, because an Indeed Apply confirmation from any
   other Indeed address is a real receipt and must still reach this step. Nothing in the daily
   run parses the Indeed alerts yet; whether it should is the Oct 26 freeze decision.

   **Use `deliveredto:`, not `to:`.** Gmail forwarding preserves the original `To:` header,
   so a forwarded confirmation still reads `to:{{APPLY_ACCOUNT}}` and the old
   `to:{{CONFIRM_ALIAS}}` query silently returns nothing. `deliveredto:` was verified
   working against this inbox on 2026-07-28.

   **Do NOT fall back to `label:{{CONFIRMATIONS_LABEL_ID}}` on its own.** Verified 2026-07-30:
   the `JobConfirmations` filter also matches forwarded LinkedIn job alerts, so every LinkedIn
   email currently carries BOTH the JobLeads and JobConfirmations labels. A label-only query
   would pull ~20 job alerts a day into the confirmation matcher, which is looking for evidence
   that Aneesh applied. If `deliveredto:` ever breaks, the safe fallback is
   `label:{{CONFIRMATIONS_LABEL_ID}} -from:linkedin.com -from:donotreply@jobalert.indeed.com -from:donotreply@match.indeed.com`.
   The sender exclusions are what keep the alert streams apart from receipts, whichever
   selector is used.
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
a scoring tier rather than tailoring from this section. As of 2026-10-10 the list is
complete (`stats.function_mismatch` equals its length; it used to be the first 40 by
company name) and ordered Georgia, then remote, then on-site elsewhere, newest posting
first within each, so the top of the list is the part he could act on.

**Lane companies are not in this file (2026-10-10).** The poller skips every watchlist
entry that carries a `lane` marker and counts them in `stats.lane_skipped`, so their roles
cannot take a shortlist slot. Step 3.6 polls those boards itself, the six review-only
titles included.

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
  past (or missing). **Read the company's own careers page first**: fetch it and look for
  the ATS host its job links or embed point at. If the listing shows none, fetch one job
  page and read its apply link. A redirect to another company's careers site means an
  acquisition: set `board_status: "404_permanent_acquired"` and
  `board_status_permanent: true`, name the acquirer in `board_status_note`, and check the
  acquirer is enrolled. Only when the page settles nothing, run one recovery WebSearch
  (`"[Company]" jobs site:greenhouse.io OR site:lever.co OR site:ashbyhq.com`). Log the
  result, then set `recheck_after` 7 days out. **Do not re-investigate confirmed-dead
  boards every run** — that burned time on Moveworks/Forethought for a week straight.
  The page comes first because on 2026-10-10 the search had been returning only cached
  Greenhouse pages for Hightouch, Postman, Arcadia, and Aisera for weeks, and each
  company's careers page answered in one or two fetches.
- If a live board is found: fix the slug/ats in the watchlist and poll just that company.
  Take the slug from a link on the company's own site, never from a guess:
  `ashby/hightouch` answers 200 with a single 2021 posting, and the real board is
  `ashby/hightouch-inc`.

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
- `.venv/bin/python pipeline/poll_builtin.py --apply` — daily; BuiltIn's COMPANY
  directory (added 2026-09-03). Walks three configured slices — Atlanta 51-500, US
  fully-remote 51-500, US fully-remote 501-1000, all restricted to companies with open
  roles — and keeps only companies hiring in "Customer Success & Experience" or
  "Operations & Support". Every lead is name-only: BuiltIn hosts its own apply flow and
  exposes no source ATS (verified on `/company/rethinkfirst/jobs`, zero outbound
  greenhouse/lever/ashby/workday links), so leads carry `needs_ats_resolution` and wait
  for `harvest_ats.py` exactly like the LinkedIn ones. Capped at 15 new leads per run,
  same cap and same reasoning as Step 1d-2.

  **Cadence: daily, but it walks 4 pages per slice per run, not the whole directory.**
  The slices total ~42 pages; a persisted cursor in `pipeline/builtin_state.json`
  advances 4 pages per slice each run and wraps at the end, so full coverage lands every
  ~3-7 days depending on the slice. This is the Step 1c rotation argument applied to
  pagination: these are COMPANIES, not perishable reqs, so a company two pages further
  in is still there on Thursday. Do not "catch up" by raising `--max-pages`; the run
  prints its cursor position every time, and a slice that has never wrapped shows
  `cycles 0`. `--all-pages` walks a slice whole without touching the cursor, for
  interactive use only.

  **Read the `ambiguous` count in its output, it is a known recall hole.** BuiltIn
  truncates the per-company function breakdown at four functions, descending by count
  (6 of 20 companies on Atlanta page 1 listed fewer roles than their own total, worst
  case 44 open with 30 attributed). A company hiring one support-ops role behind four
  larger functions is invisible to the filter, and the miss is biased toward large,
  engineering-heavy employers. Those companies are reported as `ambiguous` and NOT
  queued; `--include-ambiguous` queues them when recall matters more than queue noise.
  There is no cheap fix — `/company/<slug>/jobs` is client-rendered, and BuiltIn's
  category-filtered JOB directory returns ~10 companies a page, mostly already enrolled.
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

**Run it Workday-inclusive by default. `--skip-workday` is an option now, not a standing
recommendation (fixed 2026-09-03).** The hang the flag was invented for is gone: `assess()`
enforces a **60s wall-clock cap per company across every probe, Workday included**
(`--budget-seconds` to override, `0` to disable). A name that exhausts its budget is reported
as `[TO] … unresolved` and the run moves to the next one, so no single company can stall a
batch. The batch ceiling is therefore 60s × the pending count rather than open-ended. There
is no cap on the batch itself: `--from-pending` takes every pending name, and with LinkedIn
(Step 1d-2) allowed 30 new names a run and BuiltIn (`poll_builtin.py`) 15, a full queue is
~45 names and a ~45-minute worst case. Typical is far less (most names resolve in 5–20s).
Left uncapped on purpose (Aneesh, 2026-09-03); revisit if the harvest step starts crowding
out the JD reads.

Two things make that ceiling real, and both matter if you touch this code:

- **Progress is printed per company and flushed.** Every line used to inherit Python's block
  buffering, so a run read through a pipe — which is how the scheduled pass runs it — emitted
  nothing at all until the process exited. That is the single reason the 2026-09-02 hang was
  diagnosable only by wall-clock: a stall and slow-but-healthy progress looked identical, and
  nothing named the company that was stuck. The `-> name` line now goes out *before* probing
  starts, so the last line printed is the company in flight.
- **The politeness pause is per SERVICE, not global.** The inner loop walks every cheap ATS
  in a row (eight as of 2026-09-03: Greenhouse, Ashby, Lever, Workable, Pinpoint, Rippling,
  JazzHR, SmartRecruiters), so all but one of each cycle's `DELAY` sleeps were spent being
  polite to a host we were not about to contact. That put a ~40s floor under the cheap phase alone for a 19-variant name
  (114 requests × 0.35s) — two thirds of the budget in `time.sleep()` before a byte moved — and
  a 60s cap would have starved the Workday walk it exists to bound, making the cap a permanent
  `--skip-workday` in disguise. Each ATS still sees at most one request per `DELAY`.
- **Those eight ATSes are probed CONCURRENTLY, one thread each (`probe_cheap`, 2026-09-17).**
  Removing the sleeps left the sleeps' replacement: 16–21 slug variants × 8 ATSes is 130–170
  sequential requests at a median 0.14s (Greenhouse) to 0.83s (JazzHR), which measured **46–69s
  per name in that loop alone** — the whole 60s budget, spent before Comeet or Workday was
  reached, which is why names were being blamed on the Workday walk. The
  eight are independent hosts, so the wall clock is now the slowest single ATS rather than the
  sum of all eight. Six names re-measured, whole-company wall clock, before → after (with the
  connect-timeout fix below): TriNet 57.5→23.8s, M-Files 4.4→1.4s, Remo Health 111.2→33.3s,
  WealthCounsel 76.9→21.5s, Allegis Group 66.7→20.7s, Unit21 51.0→46.3s. The **answers are
  still read back in `CHEAP_ATSES` order**, which is what
  keeps every collision rule intact: first board with fit-titles wins, a no-fit board on the
  company's own full name is still trusted immediately, and SmartRecruiters is still considered
  last. The one behaviour change is that a slug whose winner is an early ATS now also costs the
  later probes in that round — at most seven extra one-shot calls per resolved company.

**A scalar `timeout` is not a wall-clock bound, and that is the second thing that was breaking
the cap.** `requests` applies the value to the connection and then to each socket read, and
urllib3 tries *every* address a hostname resolves to, so one dead host with two A records costs
`2 × TIMEOUT`. Measured 2026-09-17: `https://remohealth.com/careers` spent **40.1s reaching a
ConnectionError** against `TIMEOUT=20` — two thirds of that name's budget burnt by a single
request that never reached a server — and `Budget.expired()` only gates *between* requests.
Every probe now passes `(CONNECT_TIMEOUT, read)` = `(5, 20)`, shrunk to fit the remaining budget.
5s is well clear of a real handshake: the slowest request that actually answered in that
827-request sample took 3.3s end to end. DNS is still unbounded — no `requests` timeout covers
`getaddrinfo`.

**A rate-limited probe is UNKNOWN, not "no board" (fixed 2026-09-17).** In the same sample
`apply.workable.com` answered **429 to 55 of 94 requests**, before and after the fan-out alike.
`_get` used to turn any non-200 into `None` and `assess()` reads `None` as "no board", so a
throttled Workable board read exactly like a company with none, and a name whose only
unresolved signal was a 429 was written `unpollable: true`, which stops it ever being re-checked.
Same false-negative class as the Comeet and SmartRecruiters gaps. Now:
- Probes have a **third answer, `THROTTLED`** (a sentinel that raises on `bool()`/`len()`, so a
  caller that forgets to check for it crashes instead of misreading it). It flows through
  `probe()`, `probe_cheap()`, `_confirm_empty`, `probe_workday`, `probe_comeet`, and `--prune`.
- A walk that finds nothing while any probe was throttled returns a **`throttled` result**,
  written like a timeout: `unpollable: false`, `throttled: true`, `recheck_if_resurfaced: true`,
  and `throttled_probes` listing the refused `ats/slug` pairs. It never reaches the unpollable
  punch list. The cheap next step is a later `--names "<name>"` re-run, not a manual search.
  `assess()` returns `None` (the only path to `unpollable: true`) only when every probe answered.
- **One retry per request**, after `Retry-After` or 2s, capped at 10s and never past the
  per-company budget. Once a service fails its retry, later requests to it in that company's
  walk are still sent but not retried again, which caps a whole-walk throttle at one wait.
- **Dotted slug variants (`unit21.ai`) are no longer sent to JazzHR, Pinpoint, or
  SmartRecruiters.** In the same study they cost 15 SSL errors each on the first two
  (subdomain-addressed) and 15 HTTP 400s on the third. Ashby and Lever keep them because real
  boards use them (`ashby/ambient.ai`, `lever/regal.ai`). Saves 9 requests per name.

Measured 2026-09-03 on the exact names that hung: `--names "Palo Alto Networks" "RSA Security"
"Forescout"` with Workday enabled finishes in **92s, no timeouts**, versus a SIGKILL at 10
minutes and silence past 40 before. `--prune` returns byte-identical results to the pre-change
code (live=289, dead=6, empty=7) in 1:43 against its 3:13.

Use `--skip-workday` deliberately: to trim a run you already know is Workday-free, or when you
want the cheap slug-addressed ATSes only. Names it leaves unresolved still get the manual
`site:myworkdayjobs.com` fallback. A company that times out is recorded with
`unpollable: false` and `timed_out: true` — it is **not** a finding that the company has no
board, so it must never reach the weekly unpollable punch list; the cheap next step is a
targeted `--names "<name>" --budget-seconds 300`, not a manual search.

Why this was worth fixing rather than living with the flag: the 2026-09-02 hang cost more than
its 50 minutes. While the script held the two config files, every other write in the run
(blind-spot write-back, dork queueing, the Cloudbeds enrollment) had to wait or become a
one-off script, and the Step 1c-3 monthly sweep was deferred out of the scheduled pass
entirely.

For each pending name the layer generates deterministic slug variants, probes
Greenhouse/Ashby/Lever/Workable/Pinpoint/Rippling/JazzHR/SmartRecruiters directly, then the
Comeet careers-page walk, then Workday, and scores the resulting board with the **same
`TitleMatcher` the poller uses**, so a company is judged on real US-reachable fit-titles rather
than keyword guessing.

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

**Neither predicate reads a bare "remote" as evidence of the US (fixed 2026-09-11).**
`us_reachable()` used to return True on any string containing "remote" or "anywhere" and never
consulted `NON_US_MARKERS`, so Trustonic was enrollable on three tier2 TAM titles that were all
Bangkok or Mexico City — SmartRecruiters folds its remote flag into the location string, which
makes that ATS the likeliest place to hit it. A non-US marker now disqualifies a string unless it
also names the US outright ("Remote - US or Canada"), the dual-region rescue
`poll_ats.location_relevant()` already applied. Two traps to know before editing the lists: the
markers are matched as SUBSTRINGS, so `US_LOOKALIKES` has to blank out US places that contain one
("india" inside "Indiana", "mexico" inside "New Mexico"), and `poll_ats.LOCATION_EXCLUDE` is a
SEPARATE list that nothing syncs — it had the same hole and needed the same countries added by
hand. Cases for all three gates live in `pipeline/test_tier3_gate.py`; run it after any edit here.
Two follow-ups landed later on 2026-09-11: `poll_ats` now matches its lists at word boundaries
(the harvest markers are still substrings, so `US_LOOKALIKES` stays), and where an ATS returns a
structured per-posting country, `pipeline/countries.py` stamps `(non-US: Canada)` onto the string
and all three gates read that tag before any marker scan. Details in CLAUDE.md.
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

   **A flagged entry parked on a rate limit or a timeout is surfaced too (added
   2026-10-05).** `throttled` and `timed_out` rejections are not "no board" findings, so the
   rule above skipped them, and a tier1 Atlanta card at a company whose lookup was merely
   rate-limited (Arclin) reached nobody. If such an entry carries `manual_review: true`,
   give it one line in the same section, say the lookup is unresolved rather than that no
   board exists, and set `manual_review_surfaced: true`. Step 1d-3 will usually have read
   its JD by then; use that read for the line.

   **Probable name collisions get the same treatment (added 2026-09-10).** `harvest_ats.py` now
   writes a `collision_suspected: true` reject, printed as `[??]`, when a LinkedIn-sourced
   company resolves to a board that has jobs but none matching the card's title (`card_title`,
   stored on the pending entry by `harvest_linkedin.py`; older entries are parsed from `why`).
   Those entries carry `manual_review`, `unpollable: true`, and `collision_board`. Surface each
   one in the same "Manual channel" section, name the board it wrongly resolved to, and set
   `manual_review_surfaced: true`. Found via Bark Technologies: "Bark" resolved to an unrelated
   `greenhouse/bark` board, so a tier1 remote Head of AI Support Operations on
   `rippling/bark-technologies-inc` would have been rejected as a routine no-fit, invisible to
   both the Manual channel and the weekly punch list. The same fix also stops a no-fit answer on
   a REDUCED name form ("bark" from "Bark Technologies") from ending the slug walk, which is
   what kept the resolver from ever reaching `bark-technologies-inc`.
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
   **Either way, copy `source` and `first_seen` across verbatim from the `pending` entry.**
   `harvest_ats.py` does this automatically; a hand-processed entry that drops them becomes
   permanently unattributable, because discovery and enrollment are different runs and
   nothing else records which channel found the company. This is what
   `weekly_channel_report.py`'s enrollment-attribution section reads — see Step 6.5.
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
(case-sensitive slug), Workable, Pinpoint, Rippling, Comeet, **Paylocity** (added
2026-08-28), and **JazzHR** (added 2026-09-03; slug is the `applytojob.com` subdomain, often
not derivable from the company name, see `_jazzhr_notes`). **Paylocity boards CANNOT be auto-resolved by `harvest_ats.py` and must be
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

**The audit is per MESSAGE as of 2026-09-17, not per thread.** A Gmail thread can hold several
stacked alert messages — LinkedIn sends several alerts at the same timestamp and Gmail threads
them — and on 2026-09-16 one real thread held 4 separate alert messages, each a different saved
search with different job cards. `bodies_read == job_alert_threads_seen` only asked whether a
thread had gotten ANY body, so fetching just the first stacked message satisfied it while the
other 3 alerts' cards silently never got graded: that run logged 38/38 threads read while 6 alert
messages had no body, caught only by a hand check of message ids. The script now also reports
`job_alert_messages_seen`, `job_alert_messages_with_body`, and `missing_body_message_ids`; keep
recording the thread-level pair too (unchanged, still useful context), but treat the message-level
pair as the actual gate and fetch exactly the ids `missing_body_message_ids` names.

**HOW TO RUN THIS STEP (script-first as of 2026-09-02). The numbered list below it is the
MANUAL FALLBACK, used only when the script fails, and the fallback is what the history in
that list is about.**

a. Window, unchanged: `.venv/bin/python pipeline/linkedin_window.py`.
b. **Hand the fetch to ONE Haiku helper (Agent tool, `model: haiku`), and do not fetch the
   bodies yourself (changed 2026-09-28).** Give it the resolved Step 1d-2 query and this
   brief: run it with `search_messages`; call `get_message` (`messageFormat: PLAIN_TEXT`) on
   EVERY message from `jobalerts-noreply@` or `jobs-noreply@`, newest first, including every
   stacked message inside a thread; do not extract, grade, or summarize anything; answer in
   ONE line: `threads=N messages_fetched=M` plus any ids that errored. The records land in
   the helper's own log under `<session>/subagents/`, which `harvest_linkedin.py` reads the
   same as the main transcript. Why: every body fetched here used to sit in this run's
   context and get re-read on every later turn (42 bodies, ~8k tokens each, on 2026-09-28,
   when the main context peaked at 817k). The helper pays each body once.
   **Fallback:** if the Agent tool is unavailable, or step c then reports records missing,
   fetch the missing ids yourself exactly as before (search, then `get_message` each, never
   reading the result), and note `linkedin_fetch: inline fallback` in the run record. The
   message-level SHORTFALL line in step c is the check either way.

   **Split the fetch when the search returns more than ~15 job-alert messages (changed
   2026-10-05).** One helper ran out of context ("Prompt is too long") on 09-30, 10-02, and
   10-05, the last time after 20 of 56 bodies. Run the search yourself first (subjects and
   ids only, it is small), then hand each helper a list of at most **12 message ids** and
   the same no-reading brief, all helpers in one message so they run together. Three
   helpers of 12 fetched 36 bodies with no errors on 10-05. `M` in step c is the TOTAL
   across this session's helpers; the script sums helper logs per session.
c. Grade, dedupe, and queue, passing the helpers' total `messages_fetched=M` as the expectation:

   ```bash
   .venv/bin/python pipeline/harvest_linkedin.py --from-transcripts --expect-messages M
   ```

   **A `SHORTFALL` naming the helper is a hard stop for this step (added 2026-09-29).** It
   means the helper fetched the bodies but its log is not reaching the script, which the
   script's own message-level check cannot see: that check only counts messages the input
   mentions, and records it never read are not "missing" from its point of view. That is
   exactly how 2026-09-29 went wrong: the pre-filter matched only the unescaped
   `"sender":"..."` form, a helper's log stores it escaped, so the first pass graded 25
   bodies left over from the previous day's session, reported no shortfall, and dropped
   today's 35. Fixed the same day, but the guard stays. Also read the `bodies by source`
   line: today's helper log should appear in it by name.

   Read its stdout (the card block and the UNKNOWN list are short), then re-run with
   `--apply` to append the UNKNOWN companies to `pending`. `--apply` is the only write to
   a tracked file; it caps at 30 (flagged cards first, then order of appearance), carries
   `manual_review` / `manual_review_why` per item 2, and runs `validate_config.py` after.
   The dry run is idempotent and only writes `pipeline/jobs/linkedin_cards_[date].json`
   plus its `.txt` (every card as graded) and `.html` (the digest block) twins.
d. Record: copy the script's `counters` object into `run_[date].json ->
   step_1d_2_linkedin_harvest` verbatim; it carries every field required above
   (`job_alert_threads_seen`, `bodies_read`, `companies_extracted`, `newly_queued`,
   `cap_deferred`, the legacy pair, the aggregators dropped, the review and blind-spot
   lists), plus the message-level trio (`job_alert_messages_seen`,
   `job_alert_messages_with_body`, `missing_body_message_ids`) that is the real shortfall
   gate as of 2026-09-17. If it prints `SHORTFALL`, name the shortfall in the digest and
   fetch the ids it lists.
e. Digest: the `.html` block (`linkedin_cards_[date].html`) goes in verbatim as its own
   section, **"LinkedIn cards to check by hand"** (Step 5). **Changed 2026-10-10, Aneesh's
   call.** The block used to be every graded card, 130 to 290 lines a day, and he asked for
   it cut to the ones worth opening by hand. The script now writes only the review-flagged
   cards that are not aggregator reposts, not at a watchlist company (the poller reads
   those boards daily), and not already listed on an earlier day, under one sentence that
   counts what was left out. On the 10-09 cards that is 7 lines where the old block had
   161. Do not add lines to it and do not rebuild the long list from the `.txt`: the `.txt`
   is the full graded record for grep and for handoff, not digest content.
f. Item 3b below still applies by hand: the script lists the qualifying cards under
   `blind_spot_qualifying`; you decide which of them (max 3) get a verification search.

**Fallback trigger:** a traceback, or `job_alert_threads_seen: 0` while the search returned
job-alert threads (that means the records did not reach the transcript the script scans;
`--transcript-dir` overrides the derived path). Then run the numbered list by hand and say
in the run record that the fallback was used. Other inputs the script accepts:
`--input-dir <dir>` for saved records / `.eml` exports / bare bodies, and `--gmail` for the
credential-backed path that is written but unverified and cannot run until a token exists.

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
   become a lead, and the hard cap of 30 new companies per run still bounds the downstream work. **Read snippets/subjects, not full bodies** —
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

   **BUILT 2026-09-02 (from the retro, Aneesh's call): `pipeline/harvest_linkedin.py` reads
   the bodies and GRADES every card.** The manual body-read rule in this list is now the
   fallback; the routine is in "How to run this step" above the list. Why it was built: the
   2026-09-02 run read 13 of 29 bodies at ~8k tokens each, ~100k tokens for one real find
   (Cloudbeds), and ~80% of every body is tracking URLs. The cards have a fixed shape
   (`title / company / location` blocks split by a `---------` rule), so a script emits
   `company, title, location, title_tier, location_verdict` per card and covers every thread
   instead of 13. It produces both outputs the step needs: the deduped UNKNOWN company list,
   and a **graded card list** rendered in the digest one line per card, e.g.
   `[tier1 | Atlanta] Cloudbeds: Director of Customer Support | 4461060231 | watchlist`, so
   Aneesh can see what the alerts contained and how each was scored. His observation
   prompting this: the roles inside the alerts read better than what the pipeline exports
   from them, and the company-only design discards the role signal that `manual_review`
   only partially recovers. **What the script did NOT remove:** the body still passes
   through context once, because the script cannot call the claude.ai Gmail connector and
   no Gmail API credential exists on the machine (docstring has the details). Re-running it
   on the 2026-09-02 transcript recovered all 14 bodies that run had opened, 64 cards, 43
   companies; the by-hand pass had logged three flagged roles from the same bodies.

   **Aggregators appear far more often in bodies than in subjects** (Swooped, Hired,
   RemoteHunter, Jobot, Dice, ZipRecruiter, Talentify, Lensa). Drop them at extraction per 2b
   below; they are reposters, not employers. The list lives in `watchlist_companies.json ->
   _poller_config.linkedin_aggregator_blocklist` as of 2026-09-02; the script reads it and
   the fallback should too. Add a name there, not here.

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

4. **Hard cap: append at most 30 new companies per run.** If more survive dedupe, take them
   in the order they appeared and leave the rest; they are queued only if LinkedIn alerts on
   them again. The cap keeps the step's cost bounded no matter how noisy the alerts get.

   **Raised 15 -> 30 on 2026-09-17, Aneesh's call.** At 15 the cap, not the inbox, was the
   channel's real leak: the four runs 09-14..09-17 deferred 94, 60, 40, and 74 unknown
   companies, and the "tomorrow's run will catch them" claim this item used to make only holds
   for a company that alerts again. Cost of the raise: up to 15 more names through
   `harvest_ats.py` per run, ~15 more minutes worst case. Keep reporting `cap_deferred`; if it
   still runs in the dozens at 30, that is the number to bring back to him, not a reason to
   raise the cap silently again.
5. Append each to `enrollment_candidates.json → pending` using the standard `_schema` shape,
   with `needs_ats_resolution: true`, `source: "LinkedIn alert"`, `first_seen` = today, and a
   `why` naming the alert it came from. Carry `manual_review` / `manual_review_why` from step 2
   when set. Step 1d resolves the ATS and enrolls or rejects them on this or a later run at its
   own pace.
6. Note the harvested/capped counts in `run_[date].json → pipeline_notes`. Digest mention
   only if something notable enrolled — routine harvesting is housekeeping.

**Do NOT** score, fetch JDs for, or tailor anything from this step, except the narrow
blind-spot auto-trigger in step 3b, which does one verification WebSearch and stops at a
digest line, never a tailored pick. Role-level follow-through is Step 1d-3 below, which has
its own selection and its own cap.

**Aggregator reposts keep their role (changed 2026-10-05).** An aggregator is still never
queued or enrolled, but a strong-title card in a qualifying location is no longer discarded
with the reposter's name: `harvest_linkedin.py` prints those under `aggregator roles worth a
look` and keeps them in `aggregator_cards` and the `.txt` record with the status
`aggregator repost, employer unknown`, one line per distinct title. TalentHop's "AI
Operations Manager (Remote)" alerted six times in four days and appeared nowhere; it was a
watchlist company's role. **Since 2026-10-10 they are not in the digest block** (Aneesh's
call): with the employer unknown there is nothing for him to open. Step 1d-3 still reads
their JDs, and a repost that clears the screen reaches the digest under "LinkedIn roles
followed up" with the employer the body names.

### 1d-3. LinkedIn role follow-through (added 2026-10-05, from Aneesh's audit of one day's alerts)

Step 1d-2 harvests companies and, by design, drops the role. That is right when the poller
can then watch the company and wrong everywhere else. Auditing the 10-05 alerts card by card
found a remote Technical Account Manager at a 35-person security-tooling company (Echo) that
three separate faults had hidden: it arrived under an aggregator's alert, its name matched a
different company's old rejection, and its location read "New York, NY" because **LinkedIn's
plain-text alert body omits the Remote/Hybrid tag that the app and the HTML email show.**
Verified against the raw bodies: "United States (Remote)" in the app is "United States" in
the text, and the public job page omits the tag too. No parser can recover it.

What can be read without a login is LinkedIn's guest posting endpoint, which returns the
full JD for any job id. So, after `harvest_linkedin.py --apply`:

```bash
.venv/bin/python pipeline/linkedin_followup.py
```

It selects up to 24 cards (strong tier or AI wildcard; not non-US, demoted, or VP-level;
not at a watchlist company, since the poller reads those boards; not already in
`outcomes.csv`; never fetched before), ordered never-resolved companies first, then
aggregator reposts, then rejected and manual-rotation companies. It fetches each JD once
and writes them to `pipeline/jobs/jd_cache/<date>_linkedin/` in the Step 2-JD shape, with
`batch_NN.json` files. It drops closed postings and US-city cards whose own JD says on-site
or hybrid without saying remote, and prints both. Ids cut by the cap are not marked seen, so
they roll to the next run. A 429 stops the walk and says so.

Then dispatch **one Sonnet worker per batch file with the exact Step 2-JD worker prompt**
(paths under `<date>_linkedin/`), in the same message as the Step 2-JD workers when the
timing allows, and read the result with:

```bash
.venv/bin/python pipeline/jd_screen_table.py --date <date>_linkedin
```

Treat the rows like any other screened role, with three differences:

- **`loc?` is the normal state here, not a warning.** The JD body often states no work
  arrangement. For a PASS or CHECK row you would otherwise pick, find the source posting
  (the company's own board; at most 6 WebSearches for this step) and read the location
  there before scoring. The source posting is also the apply link: never send him to the
  LinkedIn URL when the ATS URL is known.
- **An aggregator row's employer is whoever the body describes.** Check that company with
  `check_company.py`; if it is on the watchlist the role belongs to the poller, and the
  useful output is why the poller is not showing it.
- **A company that turns out to have a pollable board gets enrolled by hand** with the
  board you actually read, not by re-running the resolver on its name: on 10-05 the
  resolver given `echo.ai` returned an unrelated `greenhouse/echo`.

Rows that clear go through normal Step 2c scoring and compete for the five tailoring slots;
the rest that score at or above the light threshold go on "Cleared, not tailored". Digest:
a short section, **"LinkedIn roles followed up"**, one line per PASS/CHECK row with the gate
result and the best link found, plus the dropped and deferred counts. Record
`run_[date].json → linkedin_followup`: selected, fetched, dropped, deferred, pass, check,
fail, source postings found, zeros included.

Cost: about 40 seconds of fetching and three Sonnet workers. First run, 10-05: 24 selected,
21 fetched, PASS 6 / CHECK 12 / FAIL 3.

**Two gaps this step does not close, on purpose.** A card at a WATCHLIST company whose
title the poller's matcher misses is skipped here and missed there (phData's "AI Services
Lead - Client Services" and Elastic-style bare "Support Manager" titles match no tier);
that is a title-config question and needs the measure-before-adding rule in
`tier2b_ai_wildcard`. And a "Remote" header that the JD body contradicts still reads as
remote until a worker reads the body.

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

Combine ATS hits + promoted borderline titles + WebSearch finds. **Roles at a company
marked `"lane": "industrial"` are not part of this step**: the main poll skips those
entries, and anything found at one another way (a Step 1c-2 or 1c-3 hit) is scored and
surfaced only at Step 3.6.

### 2a-pre. AI-wildcard borderline review (mandatory, not optional)

`poll_ats.py` now computes a real `pre_score` for every borderline entry flagged
`ai_wildcard: true` (fixed 2026-07-10 — previously these carried no score at all, only a
low-fidelity fragment-count `borderline_score`, so they sorted alongside noise and were
easy to skim past). The poller's console output prints the top 5 by `pre_score` under
"Top AI-wildcard borderline hits" — **read every entry in `borderline` with
`ai_wildcard: true` before finalizing the picks** (Step 2-JD reads them all; score every one
that clears), not just the printed top 5, and not
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

### 2-JD. JD screen fan-out (added 2026-09-24/25, Aneesh's "make the changes you think are best")

**Every shortlist JD gets read now, not just the 3-4 already picked from listing data.** On
2026-09-24 the run went 924 title matches -> 49 shortlisted -> 4 tailored, and most of the 49
were never read: JD text is the most expensive thing that can enter this context, so Step 3
only ever fetched the picks. Re-screening that same day's shortlist this way produced 35 roles
that cleared location, pay, and red-flag gates on the JD body itself, including an Atlanta
hybrid and several remote roles the listing-only pass never opened, plus the correct
disqualifiers for roles that had looked fine on the listing (two turned out on-site, two paid
under the salary floor).

The split: **Python fetches, Sonnet reads, you decide.** Workers extract quoted facts and never
score; the rubric at 2b/2c stays yours.

1. **Prefetch** (one command, nothing chained):

   ```bash
   .venv/bin/python pipeline/jd_prefetch.py
   ```

   Fetches every `matched` entry, every `ai_wildcard` borderline entry (2a-pre still applies:
   they are all in here), and the `near_window` entries whose listing location could be
   Atlanta or remote US, through `fetch_jd.fetch()` in parallel. Writes each JD to
   `pipeline/jobs/jd_cache/<date>/NN_*.txt`, one `batch_NN.json` per 8 JDs (highest pre_score
   first), and `manifest.json`. Skips URLs already `applied`/`rejected`/`closed` in
   `outcomes.csv`. Copy its first line into `run_[date].json → jd_screen.prefetch`.

2. **Dispatch one worker per batch, ALL IN ONE MESSAGE** so they run concurrently: the Agent
   tool, `subagent_type: "general-purpose"`, `model: "sonnet"`, and exactly this prompt with
   NN and the date filled in (absolute paths):

   > You are a JD screen worker. Read /Users/aneesh/Documents/resume_project/pipeline/jd_screen_worker.md and follow it exactly. Batch file: /Users/aneesh/Documents/resume_project/pipeline/jobs/jd_cache/<date>/batch_NN.json. Resume: /Users/aneesh/Documents/resume_project/master_resume.md. Output path: /Users/aneesh/Documents/resume_project/pipeline/jobs/jd_cache/<date>/cards_batch_NN.json

   Each worker writes its cards to that file and answers with one line. Do not ask a worker to
   return the cards inline: 80 full cards is ~120K tokens, which is the problem this step
   exists to remove. Measured 2026-09-25: 10 batches of 8, ~1.5-2 min wall clock, ~150K
   Sonnet tokens per worker (mostly the brief, the resume, and eight JDs).

3. **Read the table** (one command):

   ```bash
   .venv/bin/python pipeline/jd_screen_table.py
   ```

   One line per role: `PASS` / `CHECK` / `FAIL`, pre_score, location class, pay range, IC vs
   manages, the worker's advisory overlap, and the years-of-experience bar quoted from the JD.
   `FAIL` carries the gate that failed. If it prints `RE-DISPATCH`, send those batches ONCE
   more (same prompt), then re-run the table. Anything still uncarded, plus the `MISSING` rows
   (Rippling/Pinpoint have no fetcher; some fetches fail), is handled the old way: judge from
   the listing, and fetch the JD at Step 3 only if it would make the picks. To read one role's
   full card: `.venv/bin/python pipeline/jd_screen_table.py --show "<company>"`.

4. **What the gates mean, so you do not re-derive them.** Location passes on `atlanta_ok: yes`
   or `work_mode: remote_us`, read from the JD body (not the listing string). Salary compares
   the MIDPOINT to `salary_floor_usd`; between `near_miss_salary_floor_usd` and the floor the
   role FAILs as a salary near-miss, which still belongs on the digest's near-miss list. An IC
   role under the IC non-interest floor shows as `CHECK`: you make the interest-category call
   (Step 2b). Crypto, clearance, VP-and-above, non-US-only, staffing-agency, and closed
   postings FAIL on the worker's flag. The table only applies facts; it never scores.

5. **Then run 2b and 2c on the PASS and CHECK rows** with the cards as your JD evidence. The
   worker's `resume_overlap.estimate_0_30` is advisory: set keyword overlap yourself (open the
   card for any role within ~10 points of a tier threshold). `years_required_verbatim` is what
   the HARD-REQUIREMENT TIER CAP needs, already quoted.

**Fallback when the Agent tool is unavailable or every worker fails:** read the cached JD
files for the top 8 rows by pre_score directly (they are already on disk; do NOT refetch),
score those, note `jd_screen.fallback: true` with the reason, and continue. That is the
pre-2026-09-24 behaviour with the fetches already done, so a failed fan-out can cost coverage
but never the run.

Record in `run_[date].json → jd_screen`: `prefetch` line, `workers_dispatched`,
`redispatched`, `cards`, `pass`, `check`, `fail`, `missing`, `fallback`.

### 2b. Hard filters

Eliminate: crypto/web3/blockchain; VP/Head-of/Staff/Principal (EXCEPT exact Tier-1 titles
like Head of Support / Director of Support Operations — those are true matches);
clearance-required; postings older than `poll_ats.py → MAX_POSTING_AGE_DAYS` (**40 days**);
salary below `_scoring_config → salary_floor_usd`.

**This line said 21 days until 2026-09-07 and had been stale since 2026-07-27**, when the funnel
audit raised the poller's limit to 40. It was dead prose rather than a live second filter — the
poller had already dropped everything over 40 before you ever saw it, and roles between 21 and 40
were reaching full tailoring anyway (ApartmentIQ at 32 days on 08-23, Cato Networks at 32 on
08-31). Corrected so a future run doesn't start enforcing the 21 for real and silently undo the
widening. **The 21-day mark survives only as a provenance tag**
(`age_Nd_over_old_21d_limit`), which is the point: those roles are meant to be visible and
attributable, so that if Aneesh consistently ignores them the widening can be rolled back on
evidence. Age still costs points at Step 2c — −3 source quality past 14 days, and no freshness
bonus past 7 — so a stale role competes on a worse score rather than being hidden.

**Salary comparison basis (deterministic, never eyeball):** range → compare the
**midpoint**; single figure → that figure; OTE-only → estimate base (80% for
variable/sales roles, 100% otherwise) then midpoint; no salary listed → do NOT filter,
treat as neutral.

**IC-scope salary floor (added 2026-09-07, Aneesh's rule — `_scoring_config →
ic_scope_rule`).** A role that manages nobody is NOT eliminated for that, and it takes NO
scoring penalty. What changes is which floor it has to clear:

- **IC in an interest category → the normal `salary_floor_usd` ($100K).** It competes like
  anything else.
- **IC outside one → `non_interest_floor_usd` ($125K).** The premium is what buys the scope
  change from managing 8 people.
- Below `absolute_floor_usd` ($90K = `near_miss_salary_floor_usd`) nothing clears either way,
  which the existing near-miss floor already handles.

**Interest categories are `passion_domains`, AI-native, and developer/infra tooling.** Tooling
counts — confirmed by Aneesh 2026-09-07 — because the career-narrative skill records tool
creation as his primary interest and this config already pays tooling and AI an identical +20.
Apply the test semantically, the same way `passion_domains` is: a watchlist `score_bonus` whose
`bonus_reason` names AI or tooling settles it, and a non-watchlist company can qualify on its
product.

**Do not confuse this with the narrow-administration anti-signal**, which is about ALTITUDE and
still eliminates a platform-administrator role at any salary. Collapsing the two on 2026-09-07
nearly dropped Linear's "Customer Success Manager, Growth" — ~94 uncapped, remote US, 3 days
old, no hard-req cap, at a developer-tooling company — purely for having no reports. A role
that fails only this floor is a **salary near-miss**, not a silent drop.

**IC + non-interest + no salary listed does not resolve here — it goes to Step 3.** The $125K
bar cannot be evaluated against a missing number, and the general "no salary listed → treat as
neutral" rule stays intact. Read the JD body for comp; if it genuinely discloses none, cap the
role at **light tier** and flag it in the digest as IC scope with unverified comp.

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
- Freshness: `_scoring_config → freshness_bonus_2d` (+10, top band) / `freshness_bonus_7d`
  (+2, ≤7 days)

  **The top band is not a fixed 2 days (changed 2026-09-07).** It is
  **`max(freshness_top_band_days, days since the PREVIOUS run)`** — so **3 on a Monday**, 2 on
  Tue–Fri, and automatically wider after a holiday or a skipped run. Compute it from the run
  dates, not from the weekday name: the previous run is the newest
  `pipeline/jobs/ats_hits_*.json` dated before today, which is also what `poll_ats.py` now uses
  for its own pre-score term.

  Why: the task runs `0 3 * * 1-5`, and a posting is scored **once**, on the first run that sees
  it (`poll_ats.py` dedups against `seen_jobs.json` for 30 days). So a Friday posting's only
  shot at the +10 is Monday's run, where the calendar has already made it 3 days old. That
  charges a pipeline fact to a role — the same objection already recorded against the Outreach
  miss in `poll_ats.py`'s pre-score comment. Measured on 2026-09-07, a Monday: of 45 shortlist
  entries exactly **one** was ≤2d, and **seven were exactly 3d** — an entire Friday cohort,
  Linear's CSM Growth among them, one day past a line drawn by the calendar rather than by the
  posting.

  Two alternatives were considered and rejected. **Raising the +10** would push roles across the
  88/110 tailoring thresholds and silently redefine what "Priority" means — the same argument
  that chose `MIN_TIER1_SLOTS` over a title-score bump on 2026-08-02 — and freshness is urgency,
  not fit, so it should not buy a deeper resume rewrite. **Reserving shortlist slots for fresh
  roles** solves a problem the data says doesn't exist: on 09-07 all eight ≤7d roles were
  already on the shortlist, so the reservation would reserve what was already there.

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
- **Passion-domain +10** (`_scoring_config → passion_domains`; that JSON is the only list of
  domains, don't restate it here). Apply SEMANTICALLY to the company's mission/product,
  once per job even if multiple domains hit; ignore keyword accidents ("patient rollout").
  Poller entries may carry a `passion_domain` tag as a hint — confirm it, don't trust it.

**No IC penalty. Ever (added 2026-09-07).** A role with no direct reports takes zero points
off (`_scoring_config → ic_scope_rule.scoring_penalty` is 0 and stays 0). IC scope is handled
entirely by the salary floor at Step 2b and by a plain statement in the digest — never by the
score. Do not improvise a "scope step down" deduction under the title-gap or seniority-mismatch
penalties either; neither one is about headcount.

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

**Pick up to 5 jobs to tailor** (was 3-4 until 2026-09-25; the Step 2-JD fan-out took JD
reading out of this context, which is what the lower number was protecting). Tailoring tiers
come from `_scoring_config`:
≥`company_cap_threshold` priority/full · ≥`full_tailoring_threshold` full ·
≥`light_tailoring_threshold` light (summary rewrite + skills reorder only, no cover
letter) · below that, skip. If fewer than 3 clear the light threshold, send what you
have — never pad. The cap is on tailoring, not on surfacing: see the next paragraph.

**Cleared, not tailored (added 2026-09-25).** Every Step 2-JD role that you scored at or
above `light_tailoring_threshold` but did not tailor (it ranked below the 5, or lost a
same-company tiebreak) goes on the digest's "Cleared, not tailored" list with its score, one
line on why it cleared, and its apply link, and into `jobs/screened_[date].json` at Step 6
so the Shelf dashboard shows it. These are real, JD-checked candidates: the whole point of
reading 70+ JDs is that Aneesh sees every one that clears, not just the ones there was time
to tailor. If he asks for one to be tailored, it is a normal interactive tailoring.

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

**Read `master_resume.md` NOW** — once. You need it to judge gaps and to brief the Step 4-W
writers; they read it themselves before they draft.

## Step 3: Fetch full JDs

**For every role that went through Step 2-JD, the full JD is already on disk** at the
`file` path in its card (`jd_cache/<date>/NN_*.txt`). Read that file for each pick before
tailoring; do not refetch it. The card is a screen, not a substitute: tailoring needs the
whole text. Everything below applies to roles WITHOUT a cached file (the `MISSING` rows,
WebSearch finds, promoted near-window roles the prefetch location gate skipped).

**Use `fetch_jd.py` FIRST, not WebFetch (changed 2026-08-21).**

```bash
.venv/bin/python pipeline/fetch_jd.py --from-hits pipeline/jobs/ats_hits_[date].json --match "<title fragment>"
```

It hits the ATS's own JSON API (Ashby, Workday, Greenhouse, Lever, SmartRecruiters, **Comeet**,
**Workable**) —
or, for **Paylocity**, scrapes its server-rendered detail page — and prints title, location,
remote flag, posting date, compensation, and the **full description text** for you to read
directly. Accepts bare URLs as positional args too, and `--match` is repeatable. Only fall back to
WebFetch for an ATS it does not cover (Pinpoint and Rippling have no per-posting JSON endpoint),
then to WebSearch for a cached or mirrored copy. If the JD is
unreachable two runs in a row, drop it to the near-miss list with a note rather than stalling.

**Workable got a fetcher on 2026-09-08 (user-surfaced: Seeq, Technical Account Manager).** Same
gap shape as Paylocity's below and Comeet's before it: `poll_ats.py` has read Workable boards since
2026-07-27 and `harvest_ats.py` probes Workable slugs, so a Workable req could reach the shortlist
with nothing here able to read it. `fetch_workable` uses the public per-posting account API. Two
things it does that a WebFetch summary would not: it takes **Description and Requirements as
separate fields** (the years-of-experience bar lives in Requirements, and a Description-only read
returns a JD with no requirements in it, silently, looking complete), and it appends **`benefits`**,
because Workable postings routinely state comp as prose in a perks list rather than in a structured
field. Seeq's $130,000 exists nowhere else, which matters because `poll_ats.py` treats every
Workable hit as salary-neutral.

**Paylocity got a fetcher on 2026-09-03; do not WebFetch it any more.** The poller gained its
Paylocity adapter on 2026-08-28, so reqs reached the shortlist for six days with no fetcher to
read them, and every Paylocity hit cost a WebFetch (Paylocity's own "Lead Technical Support Ops",
2026-09-03). `fetch_paylocity` now covers both host forms — the shared `recruiting.paylocity.com`
and the tenant-prefixed `<id>recruiting.paylocity.com` — and returns the requirements verbatim.
Two things it does that WebFetch could not, both found while verifying it against live reqs:

- **It takes every section, not just Description.** Some tenants split the posting into a
  `Description` block *and* a separate `Requirements` block (Momentus Technologies). A
  Description-only read returns a JD with no requirements in it, silently, looking complete.
- **It reads the location line by shape, not by position.** That line is bullet-separated and its
  segments vary: Paylocity's own board renders `Fully Remote / Remote, US / Operations`, Momentus
  renders `Fully Remote / Brisbane, Queensland, AUS` with no department. Reading by index called
  the Brisbane role remote-US and dropped the country — a hard-filter miss.

Posting date comes from the board listing (the detail page has none), and salary is scraped out of
the prose because Paylocity states it nowhere structured, which is why `poll_ats.py` treats every
Paylocity hit as salary-neutral. A closed req 302s to `/Recruiting/Jobs/JobNotFound` with HTTP 200
and is reported as closed. The `www.paylocity.com/company/careers/*.job.<id>/` URLs are useless —
they redirect to a department index — and the fetcher says so instead of failing generically.

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

**Read every JD for IC-vs-manages-people, and record it (added 2026-09-07).** The listing
never says this and the title routinely lies about it — "Customer Success Manager" is usually a
book of accounts, not a team. Decide from the JD body: direct reports, hiring/coaching/performance
language, or "sole point of contact" and "you will own this account end to end" for the IC read.
Linear's CSM Growth is the reference case: pure IC, sole point of contact, no reports, and only a
human noticed on 2026-09-07.

This is **not** a disqualifier and **not** a penalty — see Step 2b's IC-scope salary floor for
what it actually changes. Two things follow from the read:

1. If the role is IC and the company is **not** in an interest category (`passion_domains`,
   AI-native, developer/infra tooling), the floor is $125K, so **pull the comp out of the JD
   body**. `fetch_jd.py` already returns compensation, and on 2026-09-07 the body — not the
   listing — is what killed Lob, Motorola R68440, and Paylocity 46546 on salary. If the body
   discloses nothing, cap the role at **light tier** and say so in the digest; do not guess a
   number and do not silently drop it.
2. Carry the answer into Step 5 and Step 6 either way. An IC role that clears its floor is a
   normal pick — it just gets told plainly that it carries no reports.

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

## Step 3.5: Stretch lane — FDE / Solutions Engineer / AI engineer conditional review (added 2026-08-30; AI engineer titles 2026-09-14)

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
   **AI engineer titles (added 2026-09-14, Aneesh's call).** Also collect every entry in the
   poller's `ai_engineer_stretch` list: AI-titled engineer/architect/developer roles that
   carry an operating word (config: `tier2b_ai_wildcard → engineer_stretch_route`), which never
   reached review: the AI wildcard excludes them, and the ones matching enough borderline
   fragments lost the 20-slot borderline cap. FullStory's "AI Automation Engineer" (2 fragments,
   140-entry pool, 2026-09-14) is the miss that prompted it. He wanted these judged case by case,
   knowing many will be more technical than he's used to. They carry a `pre_score` at tier4
   title weight (+8, the same as FDE) and are never shortlisted, whatever they score.
2. Take up to 2 across both sources, highest pre-score first, and read the full JD (`fetch_jd.py`, verbatim
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
     For `ai_engineer_stretch` entries only, internal AI automation or business-systems
     work also counts (AI workflows built for an internal team such as Finance, Support,
     or Ops), since tool building is his primary interest. The coding gate does NOT loosen
     for these titles (his 2026-09-14 call): data-pipeline or ETL-grade programming fails
     closed like any other production-code bar, and lands as a housekeeping line quoting it.
   A failed gate costs at most one digest housekeeping line ("checked, disqualified by
   <quoted requirement>") and no further budget.
3. A passing role goes in its own digest section, **"Stretch lane (FDE/SE) — risk
   accepted"**: title, company, salary, apply link (the no-exceptions link rule applies),
   which gates it passed, and the gap that remains. LIGHT tailoring at most, and only when
   its honest score independently clears the light threshold; never a cover letter from
   this lane. The HARD-REQUIREMENT TIER CAP applies with no special pleading; the lane's
   gates overlap with the cap on purpose, so a role that passes them usually escapes the
   cap honestly. If Aneesh wants a full package for one, he'll ask for it by name.
4. Log `stretch_lane: {candidates_seen, ai_engineer_candidates, jds_read, passed, surfaced_titles}` in
   `run_[date].json` every run, zeros included: a logged zero is verifiable, while an
   absent section is indistinguishable from a skipped step (the Step 1d-2 lesson).

## Step 3.6: Industrial lane — non-software Atlanta employers, trial (added 2026-10-10)

Aneesh's call, 2026-10-10, after a one-off sweep of 40 non-software metro-Atlanta employers
(2026-10-09) found roles in his line at building-technology and materials companies that
this pipeline had never shown him. The lane makes a short list of those employers VISIBLE
without letting them into the main shortlist, where the rubric would over-rank them:
Atlanta location, pay, and company bonuses put a wrong-function title near 75 before role
fit is read at all, and on these boards 39 of 65 title-gate hits were different jobs
(field engineers, sales support, controls and fire systems, general managers). So here the
JD read is the control, not the score. No new bonus and no tier change. **This is a trial
with a review date of 2026-11-09.** What was measured before any of it was added:
`DECISIONS.md` D31.

**Who is in the lane.** Watchlist entries carrying `"lane": "industrial"`: the polled ones
in `companies` (each with a `role_exclusions` guard list, which the poller applies before
anything else) and the manual ones in `_blind_spot_companies` and
`_unpollable_backlog_companies`, whose boards no adapter reads. The JSON is the list;
don't restate the names here. The main poll skips the polled ones; `poll_lane.py` (item 1)
is the only thing that reads their boards.

Mechanics:

1. **Poll the lane on its own.** The main poll skips lane entries, so the candidate
   list is the lane file and nothing else. If `pipeline/jobs/lane_hits_{today}.json`
   does not exist yet, run this as one plain command (about two minutes, no tokens;
   give the Bash call a 10-minute timeout, since the helper allows each board 150
   seconds):

   ```bash
   .venv/bin/python pipeline/poll_lane.py
   ```

   It runs the real `poll_all()` on each polled lane entry alone, with the two list
   caps lifted, and writes `counts`, one line per board, and one flat `candidates`
   list: every title match that passes the poller's gates, with the same `pre_score`
   the main poll would give it, as `source` `tier_match` (what the main poll files
   under `matched` or `near_window`), `borderline`, `function_mismatch`, or
   `ai_engineer_stretch`. It writes no hits file and never touches `seen_jobs.json`.
   Copy its first line into `industrial_lane.poll`. A board that errors or runs out
   of time is named in `errors`: say so under housekeeping and carry on, since its
   candidates will be there on the next run. A failed lane poll never stops the run.

   Lane candidates are that list plus any Step 1c-2 or 1c-3 hit at a manual lane
   entry. They are NOT scored in Step 2 and never appear in the picks, "Cleared, not
   tailored", the near-misses, "Below the cutoff", or "also live (FYI)", and they
   never take one of the five tailoring slots. An `ai_engineer_stretch` candidate is
   judged here under this step's gates, not at Step 3.5. (The six review-only titles
   in `function_mismatch_titles._industrial_lane_review_only_2026_10_10` arrive as
   `function_mismatch` candidates at a lane company. At any other company they stay
   plain FYI lines.)
2. **Location gate first, at no cost.** Keep metro Atlanta, and remote US where Georgia
   qualifies; drop the rest without reading anything. The poller's location gate is
   US-wide, so most hits from these boards are other states. One lane employer files
   remote roles under a single home state: treat "Remote, <one state>" as unconfirmed
   until the JD body says Georgia is eligible. Gate on the listing `location`. The lane
   file's `place` (georgia, remote, elsewhere) is the poller's reading of that same
   string. It orders the list; the gate is still your read of `location`.
3. **Function gate, from the JD.** No lane candidate has a Step 2-JD card:
   `jd_prefetch.py` reads the main hits file, which holds no lane entries. Each candidate
   that passes the location gate needs a direct `fetch_jd.py`
   read: **hard cap of 2 direct reads per run**, newest posting first. A body under 400
   characters is not a read (until a fix on 2026-10-10, the SuccessFactors lane board
   returned its section headings and nothing else): don't judge from it, don't count it against the
   cap, don't add the candidate to `disposed`, and carry it in item 5's count line as
   waiting on the fetcher. Skip any candidate
   a prior run already disposed of (the `disposed` list in recent `run_*.json →
   industrial_lane`): the poller does not mark an untailored role seen, so the same
   titles come back daily, and re-reading them is the waste the repeat-near-miss rule
   exists to stop. A candidate passes ONLY if both hold:
   - **It runs or builds a function he works in**: support, customer experience, contact
     center, or the business systems behind them. People leadership counts, and so does
     owning the tooling, the automation, or an AI rollout.
   - **Nothing required is a trade or a number he can't claim.** A trade licence or stated
     years in a trade (HVAC, controls, fire, electrical), a sales quota, or P&L ownership
     fails closed.
   A failed gate costs one housekeeping line ("checked, disqualified by <quoted
   requirement>") and no further budget.
4. **Score a passing role on the normal Step 2c rubric, with nothing added.** A
   review-only title has no tier: score it as the nearest real tier by function, the
   existing rule for `supplemental` hits. The watchlist +10 applies only to the polled
   entries; a manual entry's line carries the unpollable note from CLAUDE.md's Scoring
   Guardrails ("about 10 of that gap is the unearnable watchlist bonus"). IoT +15 applies
   to the connected-building employers the way it does to the smart-building companies
   already on the watchlist. The +30 company cap, the IC-scope floor, and the
   HARD-REQUIREMENT TIER CAP apply as written.
5. **Digest: its own section, "Industrial lane (trial)", at most 3 lines per run**,
   highest score first: `[score] Company: Title | location | pay | manages or IC | AI and
   systems content | gap | apply link`. "AI and systems content" is one honest clause on
   how much hands-on AI, automation, or tooling work the JD holds. It is what he said he
   would judge this lane on, so write "none stated" when that is the answer. When more
   passed than fit, or candidates are still waiting behind the read cap, end the section
   with one count line ("4 more lane titles waiting, oldest posted <date>"). Omit the
   section when nothing passed.
6. **Tailoring: at most ONE lane package per run, outside the five.** Only for a role
   that passed both gates and honestly clears `light_tailoring_threshold`, at the tier
   its score earns. It goes through Step 4 like any pick (already-applied guard, writer,
   fit check) and into the Step 6 track file with **`lane:industrial` in `notes`**, which
   is how the review finds these rows. If two clear on one run, tailor the higher score
   and list the other in the section; he can ask for it by name.
7. Log `industrial_lane: {poll, candidates_seen, location_dropped, direct_reads,
   passed, surfaced_titles, tailored, disposed: [{company, title, why}]}` in
   `run_[date].json` every run, zeros included. `poll` is `poll_lane.py`'s first line.
   `disposed` is what item 3's skip check reads, so it has to name every candidate the
   run finished with, passed or failed.

**Judging it on 2026-11-09.** `his_verdict` on the `lane:industrial` rows (did he send
any; mostly `skip_fit` points at the gate or the employers, mostly `skip_materials` at
the resume), the `industrial_lane` counters (fewer than about 3 passes in four weeks is
too thin to keep polling for), and how many surfaced lines held real AI work. The sample
will be single digits: the call is keep, narrow, or drop on the roles themselves, not on
a rate.

**Known limits.** Until the lane poll (added 2026-10-10, hours after the lane itself) a
tier-matched lane role reached this step only if it cleared the main poll's shortlist
cutoff or sat in the 40-entry window under it. The helper's first dry run that evening
found 32 candidates on the three polled boards, 14 of them in Georgia or remote. Of the
10 tier matches among those 14, one pre-scored at or above the 2026-10-09 cutoff of 54
and one more fell in the window that ran down to 50, so the main hits file would have
carried two. The lane file carries all of them. What it does not fix:

- **JD reads are the constraint now.** No lane candidate gets a card, so every one
  waits on the cap of 2 direct reads: about a week to work through the first backlog,
  then new postings only. Item 5's count line is where that shows.
- **The main poll skips lane entries on purpose** (`poll_ats.py`, counted in
  `stats.lane_skipped`; Aneesh's call, 2026-10-10). Do not remove the skip to get cards.
  On the dry-run day's pre-scores, a cutoff of 54 would have put about 4 lane roles in
  the main `matched` list (6 at a cutoff of 48), 3 of them in other states, each holding
  a shortlist slot and a JD card for a role this step then drops on location. Do not
  move the entries off `companies` either: `check_company.py`, `harvest_ats.py`,
  `audit_scores.py`, and the watchlist +10 all read that list as "enrolled".
- **The lane poll uses the poller's gates as they stand**, the description filter in
  D31 included, so a posting the main poll would drop is dropped here too.
- A non-fit that keeps coming back costs nothing after its first read (`disposed`). A
  whole class of them is another term in that entry's `role_exclusions`, not a rule
  here.
- Two of the polled boards are larger than the adapter's read (the newest 1,000 of a
  Workday board), which a daily poll tolerates. The manual entries are only as good as
  the rotation's WebSearch and his own look from the dashboard.

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

### 4-W. Writers: one subagent per job, one fit check per round (added 2026-10-09)

**A writer subagent drafts each package. You brief it and gate it; you never edit its
prose.** The global model router sends writing that goes out under Aneesh's name to Fable,
and runs had been doing that with a prompt improvised each morning. Measured on 2026-10-09:
five writers were 54% of the run's cost. Each made 46 to 101 tool calls across 14 to 28
requests, and every request re-reads the writer's whole conversation (88K tokens before it
has opened a file, 212K-256K by the end). The words were 2-3% of that. The rest was three
things this section removes:

- **Hunting for context.** No paths were given, so each writer listed `tailored/` (2,100+
  files), read 8 to 13 files from earlier packages, and read all 59 KB of the opener log
  for its last five lines. Three also read the source of `check_voice.py`.
- **A fit loop with no measure of distance.** All five first-draft resumes rendered to three
  pages and every first-draft letter ran 400 to 460 words. Nothing said how far over a draft
  was, so one writer trimmed its resume five times, and each round was four to eight
  separate commands.
- **No page count anywhere.** Nothing in `pipeline/` counted pages. Two writers never
  checked, and both of those resumes reached `tailored/apply_now/` at three pages.

The split: **you choose the angle and the files, the writer writes every word,
`fit_check.py` measures.**

1. **Collect what the writers share** (two commands, once per run, nothing chained):

   ```bash
   tail -n 8 tailored/_cover_openers.md
   ```
   ```bash
   .venv/bin/python pipeline/fit_check.py --recent 5
   ```

   The first is the opener lines every writer must steer clear of. The second is the five
   most recently written letters, as absolute paths, which CLAUDE.md's ramp-sentence rule
   checks a new letter against. Never list `tailored/` to find them.

2. **Decide the angle for each job before dispatching**, from the Step 0 reads and the JD
   card: the one framework, the lead story, and which projects are worth the space. **Give
   every writer in the run a different lead story.** The writers cannot see each other, and
   on 2026-10-09 two of them opened on the same story in nearly the same sentence. Also pick
   ONE calibration package per job: the most recent package for the nearest title family
   that Aneesh sent or that is still in `tailored/apply_now/`. It shows shape and length; it
   is not a source of sentences. Pick it from this, once per run, never from a listing of
   `tailored/` (2,100+ files):

   ```bash
   .venv/bin/python pipeline/fit_check.py --recent 15 --resumes
   ```

   One line per package, newest first: the date, the tracker stage, `letter` when it has
   one, `apply_now` when its PDF is still in the apply folder, and the path. The role is in
   the stem.

   **Then claim every stem before any writer is dispatched** (one command, all stems):

   ```bash
   .venv/bin/python pipeline/fit_check.py --claim Aneesh_Khan_[Company]_[Role] Aneesh_Khan_[Company2]_[Role2]
   ```

   It reads the tracker and `tailored/` and writes nothing. Exit 1 means a stem already
   belongs to an earlier package: a repost with the same company and role abbreviation
   derives the same stem, and a writer handed it would overwrite that package's files
   before any gate could object, sent or not. Each `TAKEN` line names the first free
   suffix (`Aneesh_Khan_[Company]_[Role]_2`). Use that stem everywhere from here on: the
   writer's prompt, the final gate, and the Step 6 tracking row. Exit 2 with the message
   `cannot read pipeline/outcomes.csv` means nothing can be told apart: dispatch no
   writers and say so at the top of the digest. (Any other exit 2 is a usage message;
   fix the command and run it again.) The `--recent 15 --resumes` listing stops the same
   way, for the same reason.

3. **Dispatch one writer per job, ALL IN ONE MESSAGE**: the Agent tool, `subagent_type:
   "general-purpose"`, `model: "fable"`, and exactly this prompt with the slots filled in
   (absolute paths; drop a line whose slot is empty):

   > You are a tailoring writer. Your instructions are /Users/aneesh/Documents/resume_project/pipeline/tailor_worker.md; follow them exactly. In ONE first message, Read that file and all of these: /Users/aneesh/.claude/projects/-Users-aneesh/memory/user_writing_style.md, /Users/aneesh/Documents/resume_project/.claude/skills/career-narrative/SKILL.md, /Users/aneesh/Documents/resume_project/master_resume.md, /Users/aneesh/Documents/resume_project/portfolio_projects.md, the JD at [absolute path under pipeline/jobs/jd_cache/[date]/], the calibration package [tailored/[stem]_data.json and tailored/[stem]_cover.md], the sibling package [same two files, or drop this clause], the last five letters [the five paths from fit_check.py --recent 5], and /Users/aneesh/.claude/skills/avoid-ai-writing/SKILL.md, /Users/aneesh/.claude/skills/avoid-ai-writing/references/voice-profile.md, /Users/aneesh/.claude/skills/avoid-ai-writing/references/pattern-catalog.md.
   > Package stem: Aneesh_Khan_[Company]_[Role]. Tier: [full | light]. ATS variant: [yes | no].
   > Role: [company], "[title]", [location], [pay], posted [date], [apply URL]. [Manages a team | IC].
   > Sibling package, already sent, never edit: [stem, with one line on what must differ].
   > Known gaps, already judged from the JD: [each gap, with the JD's own wording]. Hard-requirement cap trigger: [verbatim | none].
   > Angle: framework [n]; lead story [name]. Other writers today are leading with [stories]; do not lead with those. Projects worth considering: [names].
   > Recent openers, do not reuse the structure of the last five: [the eight lines from the opener log].

   The file list is in the prompt, not only in the brief, so the writer can read everything
   in its first message instead of spending one to find out what to read. Fill the slots
   with facts and names only. **Never put a sample sentence in a writer's prompt**: a quoted
   example becomes the sentence every letter uses (CLAUDE.md's ramp rule exists because of
   exactly that). A light-tier job drops the letters, the three avoid-ai-writing files, the
   sibling line, and the openers line.

4. **While they run**, carry on with the steps that do not depend on them (Step 6.7 fits
   here). Each writer answers once, in the fixed fields `tailor_worker.md` lists.

5. **Final gate: one command for every package this run wrote.** This, not the writer's
   own report, is where the gates are enforced:

   ```bash
   .venv/bin/python pipeline/fit_check.py --drafted-now Aneesh_Khan_[Company]_[Role]:full Aneesh_Khan_[Company2]_[Role2]:light
   ```

   **Every stem carries the tier you dispatched it at, `:full` or `:light`.** The script
   cannot tell a light-tier package from a full-tier one whose writer died before the
   letter (both are a resume with no cover files), so you tell it: a `:full` stem with no
   letter is a FAIL, and the command refuses to run (exit 2) when a stem has no marker.

   It re-renders both PDFs for each package into `tailored/apply_now/` and prints, per
   package: schema, JD coverage, em-dash count, the `check_voice.py` gate, whether the
   letter's `.md` and JSON carry the same prose, and both page counts, then one
   `FIT CHECK: N pass, M fail` line. Exit 1 means at least one package failed a gate. For
   Workday, Paylocity, Taleo, and iCIMS roles, run it once more for those stems with
   `--ats` added.

   - `[FAIL ]` is a gate: resume over two pages (a hard limit, Aneesh's call 2026-10-09),
     letter over one, more than two em-dashes, the voice gate, a letter whose two files
     disagree, a full-tier package with no letter, a schema error, a missing phrases file
     (`coverage`), an ATS variant that would not render (`ats`), or a check that broke
     partway (`crash`; the line carries the error). **A package with a FAIL line is not
     ready.**
   - `[FAIL ] claim` is different in kind: the tracker already has a row for that stem
     from an earlier day, so the script rendered nothing and the package on disk may be
     one Aneesh already sent, now overwritten. That is not a wording problem and not yours
     to repair: put it at the top of the digest and leave the files alone. The item 2
     claim check exists so this line never prints.
   - `[CHECK]` is coverage under 80%. That is allowed when the missing phrases are genuine
     gaps the writer named; it is not allowed when the writer never looked.
   - `[note ]` is size. Read it, do not act on it.

6. **Read the run's letters side by side, once.** They are about 400 words each. The
   per-letter gates cannot see two letters built on the same story or the same construction,
   and you are the only one who sees all of them. **Then run the Step 4.5 item 2 detect
   pass on each letter**, so that everything a writer has to hear arrives in one message.

7. **Anything that changes wording goes back to its writer.** Use SendMessage to the same
   agent with the failing `fit_check.py` lines verbatim, the problem you found at item 6
   described in a sentence, and the detect-pass findings, all in ONE message. Describe the
   problem; do not supply the replacement
   words. One round per package, then re-run item 5 for that stem. **Never edit a
   `_data.json`, `_cover.md`, or `_cover_data.json` yourself, not even one phrase.** On
   2026-10-09 two resume summaries were reworded by the orchestrator after the writers
   returned and re-rendered with no page count. If the writer cannot be resumed, dispatch
   one fresh writer for that package with the same prompt plus the failing lines.

   A package still failing after its round stays where it is, and the digest says so at the
   top: the role, the failing line, and "not ready to send". Do not quietly ship it and do
   not delete it.

8. **Append the opener log yourself**, after the final gate, one line per letter from the
   first sentence each writer reported (Step 4-spec item 5). Writers never touch that file:
   five of them appending at once would overwrite each other.

**Fallback when the Agent tool or the Fable model is unavailable, or a writer returns
nothing:** write that package yourself from Step 4-spec, gate it with the same
`fit_check.py` command, and say in the digest that the orchestrator wrote it rather than a
writer. A failed dispatch can cost the voice, but never the gates and never the run.

Record in `run_[date].json → tailor`: `writers_dispatched`, per package the writer's
`fit_rounds` and whether it was sent back, any stem the claim check renamed, how many
letters the detect pass ran on, the final `FIT CHECK` line, and `fallback`.

### 4-spec. What a package is

What a writer produces, and what you follow yourself in the fallback: the CLAUDE.md
tailoring workflow for each top job (JD analysis → top-15 phrases → ATS optimization →
tailor → verify). Per job:

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

1. Resume JSON → `tailored/Aneesh_Khan_[Company]_[Role]_data.json` (schema:
   `pipeline/pdf_helpers.py` docstring). **This is the single source of truth for the
   resume as of 2026-09-02. Do not also write a `.md` twin.** Until then every resume was
   authored twice (markdown for the coverage check, JSON for the PDF) and every coverage fix
   was applied twice: Cresta on 2026-09-02 took 4 fixes as 8 edits, and the two copies had
   already drifted apart on the same phrase list (the JSON that rendered the PDF scored
   11/15 where the markdown scored 14/15). The check now reads the JSON, so what is
   measured is what ships. Write a markdown copy only if Aneesh asks for one.
2. (retired 2026-09-02; see item 1. Older tailored versions keep their `.md` files and
   `check_coverage.py` still reads those.)
3. **Render and fit, one command (changed 2026-10-09):**
   ```bash
   .venv/bin/python pipeline/fit_check.py --drafted-now Aneesh_Khan_[Company]_[Role]:full
   ```
   (`:light` on the light tier; the marker is required, see Step 4-W item 5.)
   It renders the resume (and the letter, when there is one) into `tailored/apply_now/` with
   the same code `render_pdf.py` runs, then checks everything in items 4, 5, and 7 and the
   Step 4.5 mechanical gate. **The resume is two pages at most and the letter is one.** The
   letter's limit is CLAUDE.md Step 8. The resume's was never written down: 137 of the 150
   most recent resumes are two pages, writers had been inferring the limit by counting pages
   on old PDFs, and 13 slipped through at three, at least four of them already sent. `render_pdf.py`
   still works on its own for a one-off render.

   **Also render an ATS variant for high-effort ATSes (added 2026-08-28):** add `--ats` to
   that command, or run
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
4. **Coverage check, against the JSON:** write the JD's top-15 phrases to
   `tailored/Aneesh_Khan_[Company]_[Role]_phrases.json`. `fit_check.py` runs
   `check_coverage.py`'s match on it (summary, competencies, titles, bullets, projects,
   education, skills, and community, with the renderer's markup stripped) and prints the
   missing phrases. Target ≥80% (12/15). Below that it prints `[CHECK]`: apply the
   second-pass rule (CLAUDE.md Step 6), edit the JSON, run it again. One file, one edit per
   fix. Never fabricate to close a gap — flag genuine gaps honestly. A missing phrases file
   is a `[FAIL ]`, because the gate did not run.
5. Cover letter (full-tailoring tier only) → `_cover.md` + `_cover_data.json`, rendered to
   `tailored/apply_now/<name>_cover.pdf` by the item 3 command
   - Apply ALL voice rules from CLAUDE.md Step 8 (opener, structure variety, banned
     phrases, specific close, honesty moments)
   - **The two files carry the same prose, word for word.** The PDF renders from the JSON
     and the voice gate reads the `.md`; `fit_check.py` fails the package when they differ.
   - **Opener anti-template check:** the new letter's first sentence must not reuse the
     structure of the last 5 openers logged in `tailored/_cover_openers.md` (create if
     missing). Take them with `tail -n 8`; the file is 59 KB and only its end matters.
     After the final gate, append one line: `- [date] [Company]: "first sentence"`
6. **Tailoring diff** (for the digest): summary changes, bullet reorders/drops, terminology
   swaps, skills reorder, coverage N/15; cover letter hook + achievements featured +
   JD language mirrored + which career-narrative framework/story was used (so Aneesh can
   spot-check the framework fits the role before applying). Bullets, no prose.

7. **Style check:** the document must comply with the writing style guide read in Step 0.
   The mechanical half is `fit_check.py`'s em-dash line, which must read ≤2 for the resume
   and for the letter (it counts characters in the text that renders; `grep -c` counted
   lines, so three dashes in one paragraph read as 1). The other half is the guide's Gut
   Check ("does this sound like a real person wrote it?"), which no script runs: it is the
   writer's job before it hands back and yours at Step 4-W item 6.

**NEVER fabricate experience, certifications, or skills.**

## Step 4.5: AI-writing pass on the cover letters (added 2026-09-01, Aneesh's request)

Runs **after all tailoring, before the digest**, so fixes land before the PDFs are final.

**Where each part lands since Step 4-W (2026-10-09).** The mechanical gate (item 1) runs
inside `fit_check.py`, once in the writer's own loop and once more in your final gate. The
judgment pass (item 2) is still yours to RUN, as an independent check on each letter after
the writers return; what moved is who applies it, because the writer is the one allowed to
change words. Re-rendering (item 3) is the same `fit_check.py` command. Item 0 binds
everyone, and `fit_check.py` enforces it for PDFs too: it will not re-render a package
whose row is in a sent stage, or whose row was surfaced on an earlier day. What stays with
you is the detect pass, the side-by-side read (Step 4-W item 6), and the report (item 4).

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

`fit_check.py --drafted-now` calls this check for every package it is given and prints its
result on the `voice` line, so the Step 4-W final gate already covers it. The standalone
form, for a letter outside a package check:

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

**You run this, on every letter written this run, after the writers return** (Step 4-W
item 6). Invoke the **`avoid-ai-writing`** skill in **detect mode**; it defaults to Aneesh's
voice profile. Load it once and audit all of the run's letters in that one pass. Each writer
has already held its letter against the same catalog while drafting (`tailor_worker.md` has
it read the catalog first, so most tells never get written) and reports what it flagged,
but a writer's "clean" is a self-report and not this check. The pass did not run at all on
2026-10-08 or 2026-10-09, which is why it stays an independent step (Aneesh, 2026-10-09).

**You find; the writer fixes.** Send the clear problems back to that letter's writer in the
Step 4-W item 7 message, described and not rewritten, and leave the judgment calls out
unless one is obviously right. A letter with nothing clear gets no send-back. Never apply a
finding to a letter file yourself. In the fallback, where you wrote the letter, you apply
them. **The item 0 stage gate binds here too**: audit a sent letter if it is useful, but
the output is a lesson for the next letter, not an edit.

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

Any letter whose text changed needs its PDF rebuilt, and the ATS variant too if one exists.
That is the Step 4-W item 5 command again for that stem:

```bash
.venv/bin/python pipeline/fit_check.py --drafted-now Aneesh_Khan_[Company]_[Role]:full
```
Remember the `_cover_data.json` carries the prose separately from the `.md`. **Both get the
edit**, or the PDF silently keeps the old text. This was the easiest way for this step to
appear to work while changing nothing; the `twin` line in the report is what catches it now.

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
- **Say plainly when a role carries no reports (added 2026-09-07, Aneesh's rule).** Every IC
  role in the picks table gets an explicit "IC — no direct reports" note; do not leave him to
  infer scope from the title. Where the IC-scope floor at Step 2b was the deciding factor, say
  which branch applied ("IC, developer tooling → $100K floor" / "IC, non-interest → $125K
  floor"). If comp was unverifiable and the role was capped at light tier for it, that goes in
  the same line. This is a statement of fact, not a warning: the point of the rule is that IC
  scope is his call to make, and he can only make it if the digest tells him.
- Per-job tailoring diff below the table
- **"Cleared, not tailored" section (added 2026-09-25), directly under the tailoring diffs.**
  Every role from Step 2c's cleared-not-tailored list, highest score first, one line each:
  `[score] Company: Title | remote/ATL | pay | IC or manages | why it cleared | gap | apply
  link`. This is the section that answers "the pipeline feels limited": these roles were
  read in full and cleared every gate; they simply were not tailored today. Omit only when
  the list is empty, and then say "none cleared beyond the picks" in housekeeping so an
  empty day is distinguishable from a skipped step.
- **"Below the cutoff (ranks 41+)" section (added 2026-09-01):** the poller's `near_window`
  list as one-liners — `[pre_score] Company: Title | location | link`. Collapse obvious
  sibling duplicates to one line ("also NYC, SLC"). This section is FYI parity with the
  LinkedIn alert inbox; no scoring, no tailoring diffs. If an entry was promoted to full
  scoring under the Step 1a exception, say so where it appears in the main table instead.
  Report `stats.tier1_guaranteed` alongside the other provenance counts in housekeeping.
- **"LinkedIn cards to check by hand"** section (called "LinkedIn alert cards, graded" and
  carrying every card from 2026-09-02 to 2026-10-09; cut down 2026-10-10, see Step 1d-2
  item e): the `.html` block written by `harvest_linkedin.py`, verbatim. It opens with the
  script's one-sentence count, then one line per card in the script's order:
  `[tier | location] Company: Title | linkedin job id | status  (flags)`, job ids tappable.
  Status is `new` or the surface the company already sits on (pending, rejected,
  blind_spot); flags are a seniority term or `loose:tierN`. Each line is a target title in
  Atlanta or remote at a company the poller does not read, in the alerts for the first
  time today. Nothing here is scored or tailored, and a tier1 line at a `rejected` company
  is information, not a pick. The block is short now, so it goes inside the digest and
  does not get an email of its own. Include it whenever cards parsed, even on a day the
  sentence says nothing is new; omit it only when zero cards parsed, and then say why.
- "Also live (FYI)" lines for same-company extras; near-misses section at the bottom
  (one line each with reason tag, e.g. "scored 74" / "pay $92K midpoint"); omit if none
- **"Manual channel — no pollable board"** section: companies rejected at Step 1d that carried
  `manual_review: true`. One line each (company, the flagged title and location, careers-page
  link if found). Omit the section entirely if none. These are NOT scored or tailored; they are
  roles the automated layer structurally cannot watch, surfaced once so Aneesh can decide.
- **"Stretch lane (FDE/SE) — risk accepted"** section (Step 3.5): at most 2 lines, each
  with apply link, gates passed, and the remaining gap. Omit the section entirely when
  nothing passed; a "checked, disqualified by X" line goes in housekeeping instead.
- **"Industrial lane (trial)"** section (Step 3.6): at most 3 lines, each with its apply
  link, the AI-and-systems clause, and the gap, plus one count line when more are waiting.
  Omit the section when nothing passed; a "checked, disqualified by X" line goes in
  housekeeping. Lane roles appear here and nowhere else in the digest.
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
  - JD screen (Step 2-JD): JDs fetched, carded, PASS/CHECK/FAIL, missing, re-dispatches,
    and whether the fallback ran
  - Rate-limit recheck (Step 6.7): backlog size, names re-probed, and what they resolved to
  - WebSearch discovery: which sources the Step 1c rotation selected and ran, **which ones it
    deferred to the next run**, and a compressed list of what surfaced (mostly-known vs.
    genuinely new). Carry `websearch_rotation.py`'s staleness alarm here verbatim when it
    fires — a rotation is only honest if nothing rots at the back of it.
  - Discovery feeders: poll_remotive/poll_80k/poll_builtin/harvest_hn_hiring status
    (including DEGRADED/skipped). For `poll_builtin`, report leads, the `ambiguous`
    count, and each slice's cursor position — a slice stuck at the same page across
    runs means the cursor is not being saved (it advances only under `--apply`).
  - Blind-spot rotation: which named employers were checked this run
  - Industrial lane (Step 3.6): the lane poll's summary line, candidates seen, dropped on
    location, direct reads, passed, tailored. Print it with zeros; an absent line reads as
    a skipped step.
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
     "unmet_hard_reqs": 0, "vendor_tool_named_in_jd": "", "ic_scope": ""}]}
   ```
   (tailored picks only, not near-misses or the cleared-not-tailored list; a Step 3.6
   lane package is a tailored pick and goes in with `lane:industrial` in its `notes`)

   **`notes` always names the package's PDFs** (written down 2026-10-09; runs had been
   doing it by habit): somewhere in it, `tailored/apply_now/[stem].pdf + _cover.pdf`, with
   `+ _ATS.pdf` when there is one, using the stem the Step 4-W claim check settled on.
   That filename is the only link between a tracker row and a package:
   `fit_check.py`, `check_voice.py`, and `rotate_apply_folder.py` all find the row by it,
   so a row without it is a package nothing can recognise as sent.

   **Also write `pipeline/jobs/screened_[date].json` (added 2026-09-25)** with the Write
   tool, for the Shelf dashboard's "Cleared, not tailored" section:
   ```json
   {"run_date": "YYYY-MM-DD", "roles": [{"company": "...", "title": "...", "url": "...",
     "score": 0, "loc": "remote|ATL", "pay": "$130K-$195K|no pay", "scope": "ic|manages|unclear",
     "why": "one line: what cleared it", "gap": "one line: the main gap, or empty"}]}
   ```
   Only roles scored at or above `light_tailoring_threshold` and not tailored this run. Write
   the file with an empty `roles` list when there are none, so the dashboard can tell "none
   cleared" from "the step did not run". These rows do NOT go into `outcomes.csv`: stage
   `surfaced` means tailored, and a screened role has no resume behind it.

   **`unmet_hard_reqs`, `vendor_tool_named_in_jd`, `hard_req_cap_trigger`, and `ic_scope`
   are all required.** You already identify each during tailoring; these fields just stop them
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
   - `ic_scope` (added 2026-09-07, a real column as of the same day): `ic` or `manages`,
     from the Step 3 JD read. Empty means **not recorded** and is the correct value only for
     the 266 rows that predate the column — do not backfill it by assumption, because "nobody
     checked" and "checked, has no reports" are different facts. Same three-state rule as
     `hard_req_cap_trigger` and `furthest_stage`. When the IC-scope salary floor decided the
     outcome, put the branch in `notes` alongside it, e.g.
     `IC, developer tooling -> $100K floor`.
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
   outcome,notes,source_channel,surfaced_date,unmet_hard_reqs,vendor_tool_named_in_jd,
   hard_req_cap_trigger,furthest_stage,ic_scope,his_verdict` — 17 columns as of 2026-09-30;
   `his_verdict` is always written empty here, only Aneesh sets it)
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
   poll_80k_leads, poll_builtin_leads, poll_builtin_ambiguous,
   harvest_hn_hiring_status, harvest_hn_hiring_leads), plus a top-level
   `tailored_count`. The two `poll_builtin_*` keys were added 2026-09-03 with that
   feeder; `weekly_channel_report.py` tolerates absent keys, so runs before that date
   simply lack them — do not backfill. Every run must write it, in this exact shape, or that day
   silently drops out of the weekly rollup. It is not the report's only input: the report
   also reads `enrollment_candidates.json` for the unpollable punch list and, since
   2026-09-07, for enrollment attribution by discovery channel. The `enrolled` counters
   inside `channel_stats` are SAME-RUN counts and are near-zero by construction — a company
   found today is enrolled tomorrow at the earliest — so write them honestly and read the
   attribution section for conversion, not these. Do not backfill historical runs by guessing; the source data isn't
   consistently structured that far back (checked 2026-08-10: zero of ~45 prior run files
   had usable per-channel data in a common shape).

## Step 6.6: Rebuild the job dashboard (added 2026-09-19)

Runs here, before Step 6.5, so tracking is final and a failure in the weekly rollup cannot skip
it. Run `.venv/bin/python pipeline/build_dashboard.py`. One command, no arguments, nothing
chained. It is read-only against the tracking files and always exits 0. It overwrites
`~/Downloads/job_dashboard.html` (HTML Shelf tracks that file and refreshes its page in place)
and keeps a dated copy in `pipeline/jobs/`. Copy its single output line into the run summary. If
that line starts with `dashboard: FAILED`, note it in SESSION_STATE and continue; do not retry,
do not debug it inside the run, and do not mention it in the digest. Never hand-edit the HTML,
and never write a replacement dashboard inline. Spec: `pipeline/DASHBOARD_SPEC.md`.

## Step 6.7: Rate-limit recheck (added 2026-09-25)

Runs here, late, on purpose. Workable's widget API gives this machine a fixed allowance per
window rather than a rate: measured 2026-09-24, about 26 requests at 0.35s spacing and about
45 at 2.0s, then HTTP 429 for everything, so slowing down does not help. The Step 1d harvest
spends that allowance early in the run and every later name comes back throttled (21 of 44 on
2026-09-24). Those companies are parked as `throttled` rejections, and nothing re-checked them
unless they happened to resurface in a LinkedIn alert: 94 had piled up by 2026-09-25. By this
point in the run the window has reset, and `harvest_ats.py` now probes Workable with only the 4
likeliest slug spellings per name (`WORKABLE_MAX_VARIANTS`), which is what makes a batch of 10
fit: the 2026-09-25 dry run resolved 10 of 10 parked names with zero throttling, where the same
walk that morning had 3 of 5 refused.

Two commands, nothing chained onto either:

```bash
.venv/bin/python pipeline/throttle_recheck_pick.py
```

It prints the backlog size and the path of a names file (the 10 oldest parked names). Then:

```bash
.venv/bin/python pipeline/harvest_ats.py --names-file pipeline/jobs/throttle_recheck_[date].json --apply
```

`harvest_ats.py` supersedes each old record with whatever it finds now: an enrollment, a real
rejection, or a fresh throttled record dated today (which sends that name to the back of the
queue). Run `validate_config.py` afterwards, as after any harvest. Record
`run_[date].json → throttle_recheck`: backlog before, picked, enrolled, no_board, empty,
still throttled. Enrollments made here are polled from tomorrow's run; nothing is perishable,
because these steps find companies, not reqs. If the backlog is 0, skip the harvest command
and record that.

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

   It then prints an **"Enrollment attribution"** section (added 2026-09-07). The `enrolled`
   counters inside `channel_stats` are same-run counts and they undercount, but NOT because
   same-run enrollment is impossible — Step 1d appends to `pending` and `harvest_ats.py`
   drains it in the same pass, and 28% of enrollments do resolve that day (measured 09-07
   over the 39 backfilled entries carrying both dates; the other 72% lag by a median of 1
   day, max 11). The zero came from ATTRIBUTION, not timing: until 2026-09-07 nothing
   recorded which channel fed an enrollment, so LinkedIn could self-report at Step 1d-2
   while WebSearch, whose dorks feed the same undifferentiated queue, could not. That is why
   the report spent weeks saying **"0 enrollments off 19 WebSearch source-runs"** about a
   channel that was in fact converting. The new
   section counts `enrollment_candidates.json → enrolled` entries whose `enrolled_date` falls
   in the window, grouped by the `source` carried over from `pending`, and reports the
   discovery-to-enrollment lag alongside. **Do not divide one by the other** — the companies
   enrolled this week were mostly found last week, so the window's discovery counts are not
   that population's denominator. Entries filed before 2026-09-07 carry no `source` and are
   reported as unattributed rather than guessed at; that backlog drains on its own.

   It then prints **"LinkedIn alerts: what was in them and where it went"** (added
   2026-09-10, from Aneesh: *"I'm seeing a lot of cool stuff that isn't seeming to make the
   cut. That job leads pull, I kind of want that validated."*). **The `linkedin_harvest`
   counters in `channel_stats` are volume, not validation** — threads seen, companies
   extracted, same-run enrollments — and none of them can say whether a good role reached
   him. This section reads the daily `pipeline/jobs/linkedin_cards_<date>.json` files,
   dedupes by LinkedIn job id (the same role recurs across days and saved searches, roughly
   doubling the raw count), isolates the STRONG roles — tier1/tier2/tier2c/tier2d **and** a
   qualifying Atlanta or remote-US location — and gives each one a disposition by joining
   against `outcomes.csv` and the card's own `company_status`.

   tier3 is excluded from "strong" on purpose: it is a stretch title that only earns
   tailoring above 88, so a tier3 card going nowhere is the rubric working, not a leak.

   **The first run answered the question, and the answer is uncomfortable.** Window
   2026-09-04..09-10: 568 cards, 304 unique roles, 60 strong. Of those 60, **47% were at
   companies the poller structurally cannot reach** (no ATS board, or a named blind-spot
   employer), 20% were at companies not yet enrolled when the alert landed, 13% were at
   pollable companies and still never scored in, and 20% converted (12% this exact role
   tailored, 8% a sibling role at the same company). So the harvester is grading correctly
   and the loss is almost entirely reachability. Do not "fix" this by loosening the grading.

   Two lists are printed, and they mean different things:
   - **Unreachable strong roles**, with LinkedIn links, capped at
     `LINKEDIN_PUNCHLIST_CAP` (20) oldest-first. Each needs a hand decision: chase the
     company's own careers page, or let it drop. Expect overlap with the unpollable punch
     list below; that one is company-level and drains a standing backlog, this one is
     role-level and windowed, so a company can honestly appear in both.
   - **Pollable but never picked.** Smaller and more diagnostic: the board WAS scanned and
     the role still lost, usually on location scoring or the shortlist rank cutoff. If
     Aneesh consistently likes these better than what did surface, that is a scoring
     signal, not a discovery one.

   No state is written and nothing needs a surfaced-flag: the window advances on its own,
   so a role cannot repeat across reports the way an unpollable company can.

   **A bug this section exposed, fixed 2026-09-10:** `tailored_count` is a TOP-LEVEL key of
   `run_*.json`, not part of `channel_stats` (Step 6 item 7 says so), but `sum_field` only
   walks inside `channel_stats`. The report had printed `Tailored applications this window:
   0` every week since the schema landed. It now reads the right key; the 09-04..09-10
   window shows 10.

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
   - **Include a "Pipeline quality" section (added 2026-09-30).** Run
     `.venv/bin/python pipeline/pipeline_quality.py` (read-only) and include its output, with
     one interpretive line per numbered question using the actual numbers. Say plainly when
     `his_verdict` is still mostly unrecorded, because questions 1 and 2 can't be answered
     without it; don't guess verdicts from `stage`. The framing (aim high, interview rate is not
     the measure, don't cut the tailoring cap) is in CLAUDE.md "Measuring pipeline quality".
   - **Include the LinkedIn disposition section in full, links and all.** It is the answer to
     a question he asked directly, and the unreachable list is the actionable half. Keep the
     LinkedIn job links live in the HTML; a punch list he cannot click is a punch list he
     will not work.
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
git commit -m "pipeline: daily run 2026-09-04"
```
```bash
git push
```

**Substitute today's literal date in that commit message.** This step used to
read `git diff --cached --quiet || git commit -m "pipeline: daily run $(date
+%F)"`, and both halves of that line are now denied by `check_bash_safety.py`
(widened 2026-09-04): `||` because chained commands can't be allow-listed, and
`$(date +%F)` because command substitution raises a live permission prompt
("Contains command_substitution") that hangs an unattended run. Nothing is lost.
The `||` guard existed to skip the commit when nothing was staged, and a bare
`git commit` against an empty index simply exits non-zero with "nothing to
commit," which is an informative error rather than a hang.

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

## Step 8: Handoff file and final message (added 2026-10-09)

**The run's last act is to write a small handoff file and tell Aneesh to take his
follow-ups to a new session.** He uses each run as the day's job-search workspace and
comes back hours apart: "what are the eight", a screenshot of a role for a second look,
"score these two properly", "tailor that one", "commit". By then this session holds
440K-760K tokens and its cache has expired, so each return re-reads all of it at full
price before it answers. On 2026-10-05 he came back five times, and those returns were
3.5M of that session's 13.3M weighted tokens. A new session in this repo starts near 100K,
with CLAUDE.md already loaded, and needs only to be told what happened today.

Almost all of that is already on disk: `screened_[date].json` is the cleared list,
`track_[date].json` the picks, `run_[date].json` the stats and near-misses, and today's
`SESSION_STATE.md` entry the open items. What was missing is one short file that says where
they are, so the handoff is an index, not a second copy. **Point at files; paste nothing a
file already holds.**

1. **Write `pipeline/jobs/handoff.md`** with the Write tool, overwriting yesterday's. One
   stable name, so the line he pastes never changes; the date inside it says which run it
   describes. `pipeline/jobs/` is gitignored, and it has to stay there: a handoff names
   companies, scores, and what he has and hasn't sent, and anything tracked in this repo is
   published at Step 7. Never write it to `pipeline/` itself or to the repo root.

   Copy this skeleton exactly and fill in the bracketed parts. Keep the whole file under
   about 80 lines. The lower half is the same every day on purpose: a follow-up session
   should not have to guess a command.

   ````markdown
   # Job search handoff: [YYYY-MM-DD] ([weekday]) run

   Run finished [HH:MM local]. Digest sent (Gmail message [id]). Repo [pushed | NOT pushed: why].
   If that date is not today's, say so before answering anything: a newer run may have failed.

   ## For the session reading this
   You are a follow-up session, not the run. CLAUDE.md is already loaded and has the
   tailoring workflow, the scoring tiers, the user-surfaced finds protocol, and which script
   owns which tracking file. What it does not tell you:
   - Never read `pipeline/daily_task_prompt.md` whole (180 KB) or `pipeline/SESSION_STATE.md`
     whole (750 KB+). Grep for the heading you need and Read that range.
   - The files below are today's evidence. Answer from them before re-deriving anything.
   - Before you finish, add what you did under "Since the run" (two lines an item). The next
     session starts from this file, not from your conversation.

   ## Tailored today
   | Score | Role | Tier, scope | Package stem | Confirm before sending |
   |---|---|---|---|---|
   | [n] | [Company: Title] | [full, IC] | [Aneesh_Khan_Company_Role] | [each commitment the letter makes, in a few words] |

   Files are `tailored/[stem]_*`; the PDFs to upload are in `tailored/apply_now/`.
   Not ready to send: [package and the reason, or "none"].

   ## Cleared, not tailored: [N]
   `pipeline/jobs/screened_[date].json` has all [N]: score, pay, scope, why it cleared, the
   main gap, and the apply link. "What are the [N]" is answered from that file.

   ## Waiting on him
   - [still-live packages he has not sent, outcomes since the last run, anything the run could
     not finish; the same lines as today's SESSION_STATE entry, one each]

   ## Where today's evidence is
   - The run in prose: the first entry of `pipeline/SESSION_STATE.md` (Read with limit 40).
   - Stats, near-misses, run notes: `pipeline/jobs/run_[date].json`.
   - Each pick's score breakdown: `pipeline/jobs/track_[date].json`.
   - Every JD read today: `pipeline/jobs/jd_cache/[date]/`. One role's card:
     `.venv/bin/python pipeline/jd_screen_table.py --show "<company>"`. The whole table: the
     same script with no arguments.
   - LinkedIn alert cards as graded: `pipeline/jobs/linkedin_cards_[date].txt`. Grep the
     company. No line can mean an aggregator posted it; `run_[date].json` lists the
     aggregators dropped.
   - Poll hits: `pipeline/jobs/ats_hits_[date].json`. Grep it; do not read it.
   - Apply queue and applications gone quiet: `~/Downloads/job_dashboard.html`.

   ## One more role
   - Seen before? `grep -i "<company>" pipeline/outcomes.csv`, then
     `.venv/bin/python pipeline/check_company.py "<Company>"`.
   - Get the JD: `.venv/bin/python pipeline/fetch_jd.py <url>`. Never WebFetch an Ashby,
     Workday, or Comeet posting.
   - Score it: the rubric runs from `### 2b. Hard filters` to `## Step 3` in
     `pipeline/daily_task_prompt.md`; the numbers are in
     `pipeline/watchlist_companies.json` under `_scoring_config`.
   - Tailor it: CLAUDE.md "Default Behavior", Steps 0 to 9. Step 9 emails him the package.
   - Track it: write `pipeline/jobs/track_[date]b.json` in the Step 6 shape, then
     `.venv/bin/python pipeline/update_tracking.py pipeline/jobs/track_[date]b.json`.
   - Commit: a local commit on `main` is as good as published. Show him what is staged first.

   ## Since the run
   (nothing yet)
   ````

2. **End the final message with the handoff line, set apart, worded like this:**

   > **For follow-ups today, start a new session in `/Users/aneesh/Documents/resume_project` and paste:** `Read pipeline/jobs/handoff.md, then answer: `
   > This session is at [N]K tokens. A reply here after an hour re-reads all of it before it answers; a new session starts near 100K.

   Fill in [N] from this session's size. Keep the rest of the final message as it is, and
   keep it short: he reads the digest for detail.

3. **If he replies in this session anyway, answer.** The whole context was re-read the
   moment his message arrived, so refusing saves nothing. Answer, add what you did under
   "Since the run" in the handoff, and say once, in one line, that the next question is
   cheaper in a new session. Do not repeat it on every reply.

4. **Write the handoff on quiet days too.** Zero matches still leaves a cleared list, open
   items, and the "one more role" commands. The only run that skips it is one stopped by
   the Step 0 duplicate-trigger guard, which leaves the earlier run's handoff in place.

A follow-up session that tailors, scores, or changes a pipeline rule still records it the
way an interactive session always has (tracking through the owner scripts, a dated entry
in `SESSION_STATE.md`). The "Since the run" lines are the short version for the next
session to start from, not a replacement for either.

## Important rules

- NEVER fabricate experience, certifications, or skills
- NEVER modify `master_resume.md` or `generate_pdf.py`
- Zero matches → brief email: "No strong matches today"
- Watchlist companies: auto-surface CSM/TAM/Solutions roles even below threshold
- Unknown posting date → assume ≤7 days for direct ATS sources; skeptical for aggregators
- NEVER WebFetch ATS boards inline — always `poll_ats.py`
