# Pipeline patch audit — recurring one-off fixes, 2026-06-19 through 2026-07-10

Covers roughly the last 9 daily runs plus two interactive sessions. Compiled to identify
structural fixes that would close a whole category of miss at once, instead of continuing
to patch individual instances as they're noticed.

## 1. Title-matching: enumerated-list drift (largest bucket)

Every one of these was the same failure shape: a real, live posting with a title
`poll_ats.py` should have caught, silently dropped because a specific string wasn't in a
hand-maintained list.

- "Customer Operations Manager" and "User Operations Manager" missing from
  `TITLE_KEYWORDS_EXACT` despite "Customer Operations Manager" already being a Tier-1 title
  in `_title_scoring_tiers` (Harvey miss, 2026-07-06)
- "Customer Support Manager" — also a literal Tier-1 title — missing from
  `TITLE_KEYWORDS_EXACT` entirely (Chainguard miss, 2026-07-10)
- "Manager, Technical Account Management" missed because the matcher only recognized
  "Manager," not "Management," as a word form (ClickUp, 2026-07-10)
- "AI Enablement" missing from the AI-titles WebSearch query (Crowe miss, 2026-07-02)
- A slow-drip of individual "AI Success Manager," "AI Outcomes Manager," "AI Transformation
  Lead," etc. additions to `_title_scoring_tiers` over multiple runs, each added by hand
  after being spotted rather than matched generically
- `tier2b_ai_wildcard` — the generalized fix for the above — was fully spec'd in the JSON
  (signal words, exclusions, score) but sat disconnected from `poll_ats.py`'s actual
  matching gate for at least 2+ weeks before being wired in (2026-07-09)
- Forward Deployed Engineer sat mis-scored (Tier 2, +30 pre-score premium) for 7+ runs
  despite a near-100% real-JD miss rate, because nobody revisited the tier assignment
  itself — just kept manually skipping it run after run

**Pattern:** the matching logic is a set of hardcoded substring lists that require a human
to notice a miss before they grow.

## 2. Discovery layer: WebSearch query and ATS-coverage gaps

- Vertical-discovery query had "AI safety" but not "AI security"/"AI governance"
  (WitnessAI miss, 2026-07-02)
- No Workday discovery source existed at all until 2026-07-02 (also part of the Crowe miss)
- Origami Risk's board runs on iCIMS — an ATS type `poll_ats.py` doesn't support (only
  Greenhouse/Ashby/Lever/Workday/SmartRecruiters)
- InVue runs on Jobvite — same unsupported-ATS shape (found 2026-07-09)
- Chainguard and Expel — both fully pollable Greenhouse boards — were invisible to every
  active discovery source simultaneously (BuiltIn, board dorks, AI-vertical search) until
  surfaced by a LinkedIn alert (2026-07-10)
- Wellfound dropped as a source entirely — JS-rendered, ~2/10 real hits, reinvested into
  board dorks (2026-06-30)
- 80,000 Hours job board confirmed under-counting by ~17x (5 org pages found via WebSearch
  vs. ~84 live listings browsing directly) — explicitly deferred, not fixed

**Pattern:** WebSearch-based discovery is inherently a lossy sample. There's now a running
tally of 4 "pollable board, completely invisible" misses (Crowe, WitnessAI, Chainguard,
Expel) — the standing "directory-harvest layer" conversation (bulk slug collection via a
paid data provider) is a structurally different fix than tuning queries further.

## 3. Config/code sync drift — two sources of truth quietly diverging

- The scheduled task's `SKILL.md` had its own hardcoded 8-query WebSearch list that
  silently diverged from `watchlist_companies.json → _websearch_sources`; two new sources
  added to the JSON on 2026-06-25 never ran for a full week because `SKILL.md` wasn't
  updated (fixed 2026-07-01 by making it read the JSON dynamically instead of hand-copying)
- `tier2b_ai_wildcard` (see above) — defined in JSON, never connected to the actual poller
  code
- The company-cap rule (only `applied=true AND outcome=null` should count) was implemented
  incorrectly in code, using unapplied/queued roles instead (fixed 2026-06-19, code caught
  up 2026-06-22)
- The AI/ML bonus was double-counted: poller gave +10 for "ai" appearing in the *company
  name*, and full scoring separately added AI/ML +20 *and* a redundant per-company
  `score_bonus:20` whose own `bonus_reason` said it already *was* the AI bonus — a single
  AI-watchlist company could stack +45-78 before role fit even entered the picture (fixed
  2026-06-23, added the `MAX_PER_COMPANY_PER_RUN` diversity cap and the +30 company-bonus
  cap at the same time)

**Pattern:** every one of these is "the JSON config says X, but some Python or Markdown
file has its own stale copy of X."

## 4. Data integrity / dedup bugs

- `seen_jobs.json` entries got mis-nested outside the top-level `"jobs"` object during a
  manual edit, silently breaking dedup and causing two already-applied roles to resurface
  as "new" (fixed 2026-07-01)
- Dedup window logic let an already-applied job resurface as "new" once it aged past 30
  days, because the applied-check only ran *inside* the window (fixed 2026-07-06)
- Trailing comma in `enrollment_candidates.json` broke `poll_remotive.py` silently — this
  happened **twice**: once before 2026-06-30, and again on 2026-07-10 during a routine
  edit, caught only by an ad hoc JSON-validate pass before it shipped

**Pattern:** hand-editing structured JSON files without a validation step is the direct
cause of at least 3 incidents. `update_tracking.py` already exists specifically to stop
hand-edits to `seen_jobs.json` — the same discipline doesn't yet exist for
`enrollment_candidates.json` or `watchlist_companies.json`.

## 5. Diversity cap / shortlist construction

- The per-company diversity cap only keeps the top 2 pre-scored roles per company. This
  has caused genuinely better-fitting, lower-pre-scored roles at the same company to be
  invisible unless a human manually pulls the company's full board — Confido's
  Implementation Manager was found this way on 2026-07-09, but only because someone
  decided to dig deeper after the top-scored role (an FDE listing) failed a JD read.

## 6. Known, unresolved operational debt (explicitly deferred, not fixed)

- 6 companies (Gainsight, NCR Voyix, ThoughtSpot, Cengage, First Advantage, Availity) have
  been stuck in the Workday enrollment queue for weeks — their CXS jobs APIs are
  Cloudflare-blocked against direct `curl`/`requests` probing, need a browser-based check
  that's been deferred every run
- The scheduler has double-fired on the same day at least 4 times (4/14, 4/17, 6/10, 7/2)
  — mitigated with a duplicate-trigger guard, but the root cause was never investigated
- Moveworks and Forethought have been `404_confirmed` for weeks and go through a 7-day
  recheck cycle indefinitely — likely just dead/migrated, but there's no "give up
  permanently" exit condition, just an endless recheck loop
- `curl` wasn't in the permission allow-list, which stalled an entire unattended overnight
  run until it was noticed manually (fixed 2026-07-06) — same class of thing (a tool
  silently missing from the allow-list) could recur with any other command
