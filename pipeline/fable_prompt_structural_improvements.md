# Prompt for Fable: structural improvement pass on the job-search pipeline

Paste everything below into a fresh session in this repo (`resume_project`).

---

You're picking up Aneesh Khan's daily job-search automation pipeline. It polls ~130
companies' ATS boards (Greenhouse/Ashby/Lever/Workday/SmartRecruiters) every day, scores
matches against his background, and tailors resumes/cover letters for the best fits.

**Before touching anything, read these in order:**
1. `CLAUDE.md` — project rules, tailoring workflow, permission-safety constraints
2. `pipeline/daily_task_prompt.md` — the canonical executable spec for the daily run
3. `pipeline/watchlist_companies.json` — the config: company list, title-scoring tiers,
   scoring rubric, WebSearch discovery sources
4. `pipeline/poll_ats.py` — the poller that does ATS fetching, title matching, and
   pre-scoring
5. `pipeline/audit_recurring_fixes_2026-07.md` — a categorized list of ~9 runs' worth of
   one-off fixes. **This is the technical debt you're being asked to address structurally
   instead of continuing to patch case-by-case.** Read it in full before proposing anything.

## The ask

Several categories in the audit share root causes. Don't add more one-off fixes — find and
implement structural solutions that close whole categories at once. In priority order:

### 1. Title-matching drift (highest priority)

`poll_ats.py`'s title matching is hand-maintained substring lists
(`TITLE_KEYWORDS_EXACT`, `TITLE_FRAGMENTS`) plus a partially-wired wildcard tier. This has
caused at least 6 silent misses across recent runs — someone had to notice a specific miss
before the list grew, including one case ("Manager, Technical Account Management") where
the miss was purely a word-form issue ("Management" vs "Manager").

Investigate whether a more robust matching approach would close this category of miss
permanently: fuzzy/stemmed matching (so word-form variants don't need separate handling),
embedding-similarity scoring against the existing Tier 1-4 title lists, or some other
approach you think fits better. Constraint: the routine explicitly documents a "must fit
one context window" token budget for the daily Claude-driven steps — an LLM call per
candidate title is probably too expensive; a cheap algorithmic approach (fuzzy-match
library, local embeddings, etc.) that runs inside `poll_ats.py` itself (pure Python, no
API calls) is likely the right shape. Whatever you build, it needs to reduce false
negatives (missed real matches) without meaningfully increasing false positives (Aneesh
doesn't want a flood of irrelevant titles in his daily review).

### 2. Config/code sync drift

Multiple times, a value has been hardcoded in Python or Markdown that also exists in
`watchlist_companies.json`, and the two silently diverged (the scheduled task's SKILL.md
had its own hardcoded WebSearch query list; `tier2b_ai_wildcard` sat fully defined in the
JSON but disconnected from the poller for weeks). Audit `poll_ats.py`,
`daily_task_prompt.md`, and `~/.claude/scheduled-tasks/daily-job-pipeline/SKILL.md` for
every place a title list, scoring number, or query list is hardcoded that also exists in
`watchlist_companies.json`, and convert it to read from the JSON at runtime.
`watchlist_companies.json` should be the single source of truth — nothing else should have
its own copy of anything it defines.

### 3. Data integrity

Hand-editing `enrollment_candidates.json` and `watchlist_companies.json` has caused JSON
syntax errors (trailing commas) that silently broke daily feeders, at least twice.
`update_tracking.py` already exists to stop hand-edits to `seen_jobs.json` — the same
discipline doesn't exist for the other two files. Add a lightweight validation step (a
`pipeline/validate_config.py` that checks JSON syntax + basic schema sanity, run at the
start of every daily pipeline pass) that catches malformed config before it ships.

### 4. Diversity-cap / shortlist construction

The per-company diversity cap only keeps the top 2 pre-scored roles per company, which has
caused genuinely better-fitting but lower-pre-scored roles at the same company to be
invisible unless a human manually pulls the company's full board. Consider whether
shortlist construction can structurally surface "the best role per company" more
reliably — e.g., exclude roles whose title carries a "known-risky, needs-JD-verification"
tag (Forward Deployed Engineer is the prototype case) from the diversity-cap ranking, so a
risky top pick doesn't crowd out a safer second-best title from the same company.

## Explicitly out of scope — do not attempt

- The Workday Cloudflare-blocking issue (needs a browser-based fix, already deliberately
  deferred)
- The 80,000 Hours JS-rendering undercount (already deliberately deferred)
- The ATS directory-harvest layer for bulk company discovery (needs a paid data provider —
  a bigger decision Aneesh hasn't greenlit; if you think it's now clearly worth it, say so
  and explain why, but don't build it)
- The scheduler double-fire root cause and the Moveworks/Forethought endless-recheck loop
  — flag them if you have a clean idea, but they're not the priority

## Working constraints (violating these breaks the autonomous daily run)

- Never use `python3 -c` inline scripts — write `pipeline/_taskname.py`, run it, delete it
  (or keep it as a permanent named script if it needs to run every day)
- Never use bash arrays, chained `&&`/`||`/`;`/pipes, or subshells in a single Bash call —
  read the "Permission-safety rules" section at the top of `pipeline/daily_task_prompt.md`
  before writing any shell commands
- Do not modify `master_resume.md`, `generate_pdf.py`, or anything gitignored (personal
  run data: `tailored/`, `pipeline/jobs/`, `SESSION_STATE.md`, `outcomes.csv`,
  `seen_jobs.json`, `seen_urls.json`)
- Preserve backward compatibility with the existing JSON schemas — `watchlist_companies.json`
  and `enrollment_candidates.json` are read by multiple scripts; don't rename or restructure
  top-level keys without updating every reader
- Every change must be verified against the real postings that were actually missed
  (they're named in the audit file, e.g. ClickUp's "Manager, Technical Account Management"),
  not just synthetic test cases — write a throwaway test script, run it, show the output,
  then delete the script
- Run `pipeline/poll_ats.py` end-to-end at least once after your changes and confirm it
  completes without errors and the stats look sane

## When done

Summarize exactly what changed and why, what you deliberately left out of scope and why,
and how you verified each change actually fixes the miss it targets.
