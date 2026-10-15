# Decisions and Incidents

The stories behind the rules in `CLAUDE.md`. Each rule there that came out of an incident or a
standing call links to its entry here. Nothing in this file is an instruction: the rule in
`CLAUDE.md` is what governs, and a number here is what was true on the date it names.

Every entry was moved verbatim from `CLAUDE.md` on 2026-09-27. "Above" and "below" inside an entry
point at the old layout; commit `292e4a8` has it.

Add new entries at the bottom with the next D number, and put the one-line rule in `CLAUDE.md`.

## D1. A local commit reached origin within the hour

_From CLAUDE.md, Current Session State._

**A local commit on `main` here is as good as published.** Other sessions commit and push this
branch (the daily run at Step 7, the portfolio routine), so "committed locally, not pushed" lasts
about as long as the next session's push: on 2026-09-19 a local commit reached `origin` within
the hour, carried by an unrelated push. Decide whether something is fit for a public repo when
you commit it, not when you push.

## D2. The tailored JSON became the only resume copy

_From CLAUDE.md, Step 4._

- Save the tailored resume as `tailored/Aneesh_Khan_[Company]_[Role]_data.json` (schema: see `pipeline/pdf_helpers.py` docstring; e.g., `tailored/Aneesh_Khan_Datadog_TAM_data.json`). **The JSON is the single source of truth as of 2026-09-02**: the PDF renders from it and the coverage check reads it. Do not also write a markdown twin; every resume used to be authored twice and every coverage fix applied twice, and the two copies drifted (Cresta, 2026-09-02: 4 fixes as 8 edits, JSON at 11/15 where the markdown read 14/15 on the same phrases). Write a `.md` only if Aneesh asks for one.

## D3. Cover letter opened on a schedule accommodation

_From CLAUDE.md, Step 8._

**OPENER — never lead with a schedule/location accommodation.** Added 2026-08-13 after a rejection for a Technical Support Manager role came back same-day with the letter opening on shifting hours to cover Pacific time. Even when the accommodation is real and easy, putting it in the first sentence means a fast resume-screen reads the gap before it reads any qualification. Make the fit case first; if a JD states a timezone/location requirement Aneesh can meet but doesn't natively satisfy, address it later in the letter (middle paragraph or close) and frame it as a settled fact of how he already works ("My team already spans three time zones; covering Pacific hours is the same muscle, not a new one") rather than a hypothetical adjustment ("Shifting my hours... is a small adjustment"). Not confirmed as the actual cause of that rejection, but the opener structure was wrong on its own terms regardless.

## D4. Python stopped being a conceded gap

_From CLAUDE.md, Step 8._

**Python is no longer one of these (corrected 2026-09-07).** This section previously quoted "Python is a growing area for me" and "I am not a software developer" as the model sentences, and five letters duly reproduced the first one, sent between 2026-04-30 and 2026-07-23. Every one predates the public repos. `skill-regression-harness` and `deflection-audit` are unit-tested Python tools, and `sf-caseops-mcp` is a working MCP server running daily against a live Salesforce org. Their current sizes and test counts live in `portfolio_projects.md` and each repo's README; quote numbers from there, never from this file. "Not a strength yet" over that isn't modesty, it's an inaccurate claim about an artifact the reader can click and check.

## D5. Ramp commitments converged on one sentence

_From CLAUDE.md, Step 8._

- **Name when he'll start, and make it early.** A dated, checkable claim about behavior (he has already begun, or begins before the first conversation) beats any adjective about learning speed. **Do not reuse a fixed sentence for this.** On 2026-09-02 all four letters in one run landed on the identical construction "now rather than after an offer" because this section used to supply that exact phrasing as its example; a mandated move plus a quoted sentence becomes a template across documents, and the per-letter voice gate cannot see it. Vary the construction every time: a start date, a named resource already opened, a first concrete step taken.

Worked example, described rather than quoted (Framer, Engineering Support Lead, 2026-08-20): the letter named the coding gap, committed to starting on Framer's stack before any interview, then re-read the JD's own bar ("enough to read our code and dig in from day one") as a reading bar rather than a writing one and argued that reading a codebase well enough to reproduce and route an issue is clearable. The move is: gap, dated commitment, re-read the requirement, aim at what it actually asks. The sentences that carried it are deliberately not reproduced here; see the bullet above for why.

## D6. Voice gate and the contraction slip

_From CLAUDE.md, Step 8._

**Mechanical voice gate (added 2026-09-01):** run
`.venv/bin/python pipeline/check_voice.py --drafted-now <cover.md>` before rendering.
**Never edit a letter that has already been sent** — the file is the record of what the
employer read, and editing it makes the archive disagree with the submission. The script
labels each letter's stage. Note `surfaced` does NOT mean unsent: it means no confirmation
was matched, and two letters read `surfaced` on 2026-09-01 while already sent.
Only `--drafted-now` (letters the current run authored) is safe to edit without asking. It checks the
contraction ratio, the em-dash cap, and sentence-length uniformity, and exits 1 on failure.
**Contractions are the one that keeps slipping.** Aneesh's own letters run 5–15 contractions
with zero expanded forms; every letter written on 2026-08-28 inverted that, Brown & Brown
worst at 0 against 13 ("I have never", "I did not", "does not make me", "is not a logistics
problem"). No single sentence looks wrong, so it survived six letters undetected — the tell
is only visible in aggregate, which is why it is a script and not a habit. The daily pipeline
runs this plus an `avoid-ai-writing` detect pass at Step 4.5.

## D7. furthest_stage and the lost interviews

_From CLAUDE.md, Tracking files._

**`furthest_stage` landed 2026-08-27, and the bug it fixes had been silently destroying data
since the file existed.** `outcome` is a single TERMINAL-state column, so a role that reached an
interview and was then rejected ends up reading `rejected` and the interview is gone. Aneesh said
he was sure he'd had more interviews than the tracker showed; he was right. An audit that day
found **six interview-stage events, of which only two appeared in `outcome`** — the other four
survived only as free text in `notes` and had to be recovered by regex. Interview rate was
therefore uncomputable from the schema, which meant the pipeline was systematically understating
its own conversion. This is a strictly worse failure than the `jd_coverage_pct` problem below:
that metric merely has no variance, this one erased its own history.

**Empty means NOT RECORDED, not "never interviewed"** — the same three-state discipline as
`hard_req_cap_trigger`. The 233 rows that predate the column stay blank on purpose. Do NOT
backfill them to "no interview": "nobody checked" and "checked, never interviewed" are different
facts, and conflating them is precisely what made `outcome` useless here. Populate it going
forward whenever a stage is confirmed, and set it alongside any `mark_outcome.py` run that records
an interview, assessment, or offer.

## D8. Conversion audit columns

_From CLAUDE.md, Tracking files._

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

## D9. hard_req_cap_trigger

_From CLAUDE.md, Tracking files._

**`hard_req_cap_trigger`** landed 2026-08-21, from a finding by `audit_scores.py`. The
HARD-REQUIREMENT TIER CAP demotes a role to light tier on a stated years-minimum in a function
Aneesh has zero years in, or a requirement the JD calls non-negotiable. `unmet_hard_reqs` cannot
express that — it counts *every* disclosed gap, and most are soft ("no fintech domain") — so
nothing could tell a correctly-capped row from a missed one, and 10 rows were stuck as an
unresolved review queue. One role from 2026-08-21 is the clean case: 2 unmet hard reqs *and* full
tailoring, entirely correct, because that JD states no years minimum at all.

Three states, and the distinction is load-bearing — `outcome=null` already taught this tracker
what happens when one value means both "no" and "never recorded":

**Empty is not "no cap."** Populate it at Step 6 whenever you set `unmet_hard_reqs`; write `none`
rather than leaving it blank, because blank is what an unrecorded row looks like. The 219
pre-existing rows stay empty (backfilling means re-reading 219 JDs) and `audit_scores.py` falls
back to reading their notes, labelling that inference as a guess.

## D10. Outcome-data epoch

_From CLAUDE.md, Tracking files._

**2026-07-28 is the outcome-data epoch. Do not audit, reconcile, or reason about `applied` rows
that predate it.** The Gmail `+jobs` forwarding filter (Step 0.5) went live 2026-07-28; before
that date nothing could confirm a send, so `stage=applied` on an older row is self-reported and
often just means "tailored." Established the hard way 2026-08-20: one role sat at
`stage=applied` since 07-20 with `applied_date == first_seen_date == the tailoring date`, and
Aneesh confirmed he had never submitted it. Other pre-epoch rows are likely wrong the same way.

## D11. source_channel and schema drift

_From CLAUDE.md, Tracking files._

`source_channel` is `pipeline`, `user_surfaced`, `referral`, or `linkedin`. It exists because an
application submitted through an employee referral was indistinguishable from a cold
ATS apply, and those convert at very different rates. Vocabulary lives in `KNOWN_CHANNELS`
(`repair_outcomes.py`); add there first or the migration will treat the row as drifted.

**This schema is duplicated in two places on purpose** (`OUTCOMES_HEADER` in
`update_tracking.py`, `CANONICAL` in `repair_outcomes.py`). Change both together, then run
`.venv/bin/python pipeline/repair_outcomes.py --apply` to migrate. Schema drift here is not
cosmetic: `mark_applied.py` silently skips any row whose column count differs from the header, and
a 2026-07-28 audit found 32% of the file invisible to promotion for exactly that reason.

## D12. jd_coverage_pct has no variance

_From CLAUDE.md, Tracking files._

whether Aneesh clears the hiring manager's bar. An AI Optimization Specialist role scored
~111 with 15/15 coverage and was rejected at the recruiter screen over unlisted Intercom/Fin
experience.

The 2026-08-01 audit established that this is a **variance** problem, not a small-sample problem,
which is a stronger claim than the earlier caution made: **22 of 26 applied rows with coverage
recorded (85%) sit at >=93%, and 15 of 26 (58%) are exactly 100%.** The metric is
range-restricted by construction, because Step 6 targets >=80% and the second-pass rule pushes it
higher. A number the process optimizes to a target cannot explain variation in outcomes at ANY
sample size, so no amount of additional outcome data will rehabilitate it. That role at 15/15 was not
an anomaly needing explanation; it was the modal value.

## D13. Config-driven title matching

_From CLAUDE.md, Pipeline Routine._

Title matching is config-driven as of 2026-07-09: `poll_ats.py` builds its matcher at runtime from `watchlist_companies.json → _title_scoring_tiers` + `_poller_config` (stemmed-token matching, so word-form and word-order variants match automatically). To teach the poller a new title, edit the JSON; `poll_ats.py` carries no title lists, endpoints, or scoring numbers of its own. Whole TIERS are also discovered dynamically: any `_title_scoring_tiers` key starting with `tier` (except the specially-handled `tier2b_ai_wildcard`) is loaded automatically. That was a hardcoded 4-tuple until 2026-07-28, which silently made the newly added `tier2c_tooling_systems` match nothing despite this paragraph promising otherwise. After ANY hand edit to `watchlist_companies.json` or `enrollment_candidates.json`, run `.venv/bin/python pipeline/validate_config.py` (syntax + schema check). The daily run also runs it at Step 1-pre, and `poll_ats.py` refuses to poll against a malformed watchlist.

## D14. Score audit and rule changes that raise scores

_From CLAUDE.md, Scoring Guardrails._

**These guardrails are checked mechanically after the fact.** `pipeline/audit_scores.py`
re-derives every recorded score from this rubric and flags ones the rubric could not have
produced, plus rows still carrying a bonus a later rule change retired. It runs report-only
at `daily_task_prompt.md` Step 6 item 4 — the spec for it lives there, not here. Relevant when
editing anything below: **changing a rule does not rescore the rows already recorded under
it**, so a guardrail edit strands the existing queue until `--sweep-drift` reconciles it.
**But `--sweep-drift` only ever SUBTRACTS a retired bonus** (see `sweep_drift()`), so a rule
change that RAISES scores leaves the queue under-scored with nothing to reconcile it. The
2026-09-07 freshness-band change is the first of that kind; it happened to strand zero rows,
but only because just 6 of 265 rows record a parseable posting age in `notes` at all. Measure
the affected rows by hand when a rule moves scores upward.

## D15. Vertical bonus and the hand-curated tooling list

_From CLAUDE.md, Scoring Guardrails._

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

   **This rule is about free text, not about publisher-assigned taxonomies.**
   `poll_builtin.py -> INDUSTRY_ALLOW` (added 2026-09-04) does classify companies, but it
   reads BuiltIn's own closed 94-tag industry vocabulary with set membership — no substring
   matching, no inference from company names, and the tag split itself was curated by hand
   exactly as this guardrail asks. Measured on the 771 companies in the configured slices:
   0% false negatives against the 33 that are already hand-curated onto the watchlist, and
   ~10% false positives on the blocked set. That is a different mechanism from the 2026-07-28
   keyword pass, and its numbers are recorded on the constant. It does NOT feed scoring — it
   gates queue admission only, so a miss costs a lead, never a wrong score.

## D16. Unpollable companies score low

_From CLAUDE.md, Scoring Guardrails._

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
   2026-08-20 after a self-hosted company's Engineering Support Lead role scored 94 against an enrolled company's 98 while
   matching its JD responsibilities more closely; 7 of those points were watchlist, salary
   disclosure, and source quality rather than anything about the work.

## D17. Tier 2c and the narrow-admin demotion

_From CLAUDE.md, Target Roles for Reference._

Added 2026-07-28. Aneesh's stated PRIMARY interest is building and maintaining tools, with AI
co-equal secondary. Backed by real resume content: 25+ Salesforce Flow automations, Service Cloud
admin, the Maven AGI deployment, and the CES/QA tooling he built.

**Narrow platform-administration variants are DEMOTED as of 2026-08-28.** The governing rule is
Aneesh's own: *"it's the narrow admin work I don't want."* **The line is ALTITUDE, not domain:**
own a function (build the tooling, run adoption, decide what the system does) versus be someone's
platform administrator (configure the tool, work the queue, hold the cert). Use that test on
titles the list has not seen yet; full statement lives in the career-narrative skill's
Target-Role Criteria. Analyst level is fine and this is not a seniority rule — he applied to
a "Sr. Business Systems Analyst" role (106) unprompted; the *administrator* rung is the one he
declines. A "Manager" in the title does not rescue a role either: check the responsibilities.

The demoted titles stay in the tier2c list so they still match and surface, but `_poller_config →
function_mismatch_titles` now demotes them to digest FYI lines: `GTM Systems`, `Go-to-Market`,
`Revenue Systems`, `Sales Systems`, `Salesforce Administrator`, `Salesforce Business Systems`,
`CRM Administrator`, `Applications Administrator`.
Aneesh prompted the review by reading the Baseten GTM Systems Manager JD and saying it looked
very different from what he does. He was right, and his own history said so: **every
GTM-qualified or Salesforce-admin-titled systems role the pipeline ever surfaced went unsent
(0 of 5), and every systems role he did send lacked that qualifier (3 of 3)** — including
a security company's "Sr. Business Systems Analyst, Go-to-Market" role at 116, the second-highest score in
the tracker. Four of the five unsent ones got full tailoring *with a cover letter*, so this was
burning the pipeline's most expensive artifact about once a week.

Two things that make this a real finding rather than a small sample: the discriminator is NOT
the hard-requirement cap (the Business Systems Analyst role was capped to light tier and he applied anyway;
the Go-to-Market one carried `hard_req_cap_trigger: none` at priority tier and he did not), and the original tier2c
note assumed **the salary floor would screen the Salesforce-admin end out on its own**, which
fails at AI-native companies paying $160K–$200K for that work. The distinction underneath:
Service Cloud and Sales Cloud are the same platform and different jobs. Verified against the
live matcher (5/5 demoted, 0/3 sent roles affected, 0/7 controls affected); reverting is a
one-line delete per pattern.

## D18. WebSearch rotation and the BuiltIn sources

_From CLAUDE.md, Supplemental WebSearch Sources._

**These sources are ROTATED as of 2026-08-23, not run exhaustively.** Run
`.venv/bin/python pipeline/websearch_rotation.py` after ATS board polling: it selects the
`rotation_per_run` daily sources with the oldest `last_run` and prints their queries, then
`--mark` records the ones that actually ran. Full spec and rationale:
`pipeline/daily_task_prompt.md` Step 1c. The short version: 16 sources a day competed with JD
retrieval and kept getting skipped wholesale (zero ran on 2026-08-21, four on 2026-08-23), and
these sources discover *companies* rather than perishable reqs, so a ~3-day cycle costs almost
nothing. The JSON block is still the source of truth for the queries themselves — don't
hardcode a query count here (it drifts). As of 2026-06-25 the active set is:
1. **BuiltIn Atlanta** — Atlanta mid-size tech (title terms broadened). **BuiltIn Remote was
   disabled 2026-09-03**, superseded by `pipeline/poll_builtin.py`, which walks BuiltIn's
   COMPANY directory instead of dorking `site:builtin.com/job` for individual roles (see
   `daily_task_prompt.md` Step 1d). BuiltIn Atlanta stays active because it is not fully
   subsumed: the feeder yields companies that still need a resolvable board, so a live
   Atlanta role at a company whose board never resolves reaches the pipeline only through
   the role-level dork. This was a judgement call made without data: `channel_stats.websearch`
   aggregates every dork into one counter. As of 2026-09-07 the raw `source` string is carried
   from `pending` onto `enrolled`/`rejected`, so per-source yield becomes measurable off
   `enrollment_candidates.json` once a few weeks of entries accumulate — re-test then whether
   this dork earns its rotation slot. The feeder carries TWO
   company-level gates as of 2026-09-04: `TARGET_FUNCTIONS` (is it hiring in a support-ops
   function?) and `INDUSTRY_ALLOW` (is it a technology company at all?). The second was added
   after the first, alone, queued a car wash, an animal shelter, a bubble tea chain, and a
   real-estate operator. `--no-fit-gate` turns it off to re-measure recall.
2. **Wellfound** — early-stage startups nationally, filter to Atlanta
3. **AI-Titled Roles** — novel AI-prefixed titles (tier2b wildcard)
4. **Ashby / Greenhouse / Lever Boards - Target Roles** — discover companies off the watchlist on each ATS host
5. **AI-Native & AI-Safety Orgs** — vertical/company discovery (catches FAR.AI-type orgs whose fitting roles may be titled differently)
(Hypepotamus remains `disabled` — JS-rendered, not pollable.)

## D19. Harvest layer and ATS coverage

_From CLAUDE.md, User-Surfaced Finds Protocol._

**The 2026-07-02 standing decision here is SPENT, not open.** It said a third WitnessAI-class
miss triggers building the ATS directory-harvest layer. That fired, and the layer was built:
it is `pipeline/harvest_ats.py` (name → slug candidates → live board → fit-space scoring →
auto-enroll at low priority, plus `--prune` for dead boards). Do not re-raise it, and treat
any memory entry describing that build as un-greenlit as stale on that point.

The successor question, live as of 2026-09-03: **does the harvest layer reach every ATS the
poller does?** It does not, and the gap hides itself — a company on a poller-supported but
harvester-unknown ATS gets written to `rejected` with `unpollable: true`, which is both wrong
and self-suppressing, since that flag is what stops it being re-checked. Upwind Security sat
there on Comeet, an ATS `poll_ats.py` had read since 2026-08-20; fixed 2026-09-03 by
`probe_comeet`, which resolves a Comeet board from the company's own careers page because
Comeet has no slug to guess. **SmartRecruiters closed 2026-09-03** the same way: slug-addressable,
so it needed only a `probe()` branch, but the branch has one non-obvious requirement. That API
answers 200 with `totalFound: 0` for a slug that does not exist rather than 404ing, so the probe
returns `None` (no board) and never `[]` on an empty result. Returning `[]` would route into
`_confirm_empty`, whose re-probe gets the same confident 200 and would therefore *confirm* a slug
collision and write a wrong ats/slug onto a company's permanent record; that is the failure a
2026-08-28 sweep hit when it reported ten resolved companies that were all collisions. It probes
last among the cheap ATSes for the same reason. Paylocity is still uncovered and unfixable by
name (GUID-addressed). `prune()` still skips SmartRecruiters on purpose: that audit splits
dead-404 from resolved-empty, and this probe collapses both into `None`. **When adding an ATS
adapter to `poll_ats.py`, check whether `harvest_ats.py` can discover it too — the two keep
separate ATS lists and nothing syncs them.**

## D20. Comeet and Rippling adapter variants

_From CLAUDE.md, User-Surfaced Finds Protocol._

**Two 2026-09-11 fixes share a shape worth recognizing: the adapter was already there, and one
company's variation on the ATS defeated it.** Comeet has a third embed shape, the JS API
(`COMEET.init({ token: '...', 'company-uid': '...' })`, found on alice.io), and it failed twice
over: none of `COMEET_MARKERS` appeared on that page, and the quoted, hyphenated `company-uid` key
is unreachable by the loose `\buid\s*[:=]` pattern. `harvest_ats.py` now reads that shape from
inside the init object only, so a stray analytics `token:` cannot pair with anything, and
`pipeline/test_comeet_credentials.py` covers all three shapes plus the marker gate the loose
patterns depend on. Rippling boards can point at the company's own domain, which redirects
`ats.rippling.com/{slug}/jobs` away and leaves no `__NEXT_DATA__` to scrape (Nutrient); both files
now fall back to `_endpoints.rippling_board_api` when, and only when, the listing lands off
ats.rippling.com, sharing `poll_ats.rippling_api_items` so a multi-location posting collapses to
one item identically on both sides. The fallback is deliberately not the primary path: that API is
undocumented, and an unknown slug still 404s on the listing, so the harvest slug walk never reaches
it.

## D21. Duplicate enrollment records

_From CLAUDE.md, User-Surfaced Finds Protocol._

**A duplicate record in `enrollment_candidates.json` is a correctness bug, not clutter (fixed
2026-09-11).** `harvest_ats.py` superseded a stale `rejected` record only when it carried
`timed_out`; every other rejection path appended, so re-probing a company that already had a
rejection left two records with nothing to arbitrate between them. The stale one can carry
`unpollable: true`, which is both the flag that stops a company being re-checked and the input to
the weekly punch list, so a re-probe that RESOLVED the board left the company still reading as
unpollable: Nutrient, 2026-09-11, whose Rippling board became reachable the same day the
custom-domain fallback landed. `with_provenance()` now retires any older record for the same name
in the bucket it is writing to, folds `PROVENANCE_FIELDS` and `CARRY_FIELDS` forward, and writes a
`superseded_note` that names a falsified `unpollable: true` explicitly rather than summarising it
away. `weekly_report_surfaced` carries forward only onto another unpollable record, since
suppressing a repeat punch-list entry is the only thing it does.

Three dispositions, and the differences are load-bearing:

1. **Within a bucket, REPLACE.** One company, one record in `rejected`; one in `enrolled`. The
   newer probe is the better evidence, so its fields win and the old one's fill the gaps.
2. **An enrolment NEUTRALIZES that company's rejections in place, never deletes them.** The
   rejection is the only account of why the company was ever turned away and the `enrolled` entry
   has no field to hold it, so `unpollable` and `recheck_if_resurfaced` go false, the reason gets
   a `SUPERSEDED <date>` preamble, and `superseded_by_enrollment` is stamped. This is exactly the
   disposition Aneesh applied by hand to Affirm, Brown & Brown, and Reputation; it is automatic now.
3. **A rejection for a company already enrolled or on the watchlist is SUPPRESSED and printed.**
   This script never removes a watchlist entry (`--prune` owns de-enrolment and is report-only), so
   such a record can only misdescribe the live state. Bluehost spent 2026-09-08 to 09-11 enrolled
   at workday/web while carrying a timed-out rejection with `recheck_if_resurfaced: true`: an
   instruction to re-probe a company already polled daily. Reachable only via `--names`, which
   bypasses the already-known skip.

`validate_config.py` warns on both duplicate shapes. That is the guard for the other writers of
this file and for hand edits, neither of which the `harvest_ats.py` fix reaches.

## D22. Boundary-based location matching

_From CLAUDE.md, User-Surfaced Finds Protocol._

**Location matching in `poll_ats.py` is boundary-based as of 2026-09-11.** It was plain substring
matching, and that was wrong in both directions: `LOCATION_EXCLUDE` killed "Remote - Indiana"
("india"), Milwaukee/Waukesha/Waukegan ("uk"), and "Remote - New Mexico" ("mexico"), while
`LOCATION_INCLUDE` passed "Minsk, Belarus", Cyprus, and Mauritius on the "us" inside the country
name and `US_SPECIFIC_INCLUDE` rescued "Jerusalem, Israel" on the "usa" inside Jerusalem.
`_boundary_pattern()` compiles each list into one alternation matched at non-alphanumeric
boundaries; it uses lookarounds rather than `\b` because a period has to count as a separator on
both sides, which `\bu\.s\.\b` cannot do at the end of "Remote U.S." (`harvest_linkedin.py`'s
`has_us` still carries that bug). Boundaries alone do not save "New Mexico", so
`LOCATION_LOOKALIKES` blanks it out before the exclusion scan and only there, since the include
scan still needs the real string; that mirrors `harvest_ats.US_LOOKALIKES`. Genuinely ambiguous
city names are deliberately NOT exempted: Dublin, Paris, Berlin, and Toronto each name a real US
town AND the non-US city the exclude list is aimed at, and this filter cannot read state context
to tell them apart. Measured over 373 generated location strings the change flips exactly four,
all of them non-US locations that used to read as US. Cases live in `test_tier3_gate.py →
POLL_CASES`.

Two consequences worth knowing. "remotely" is now an explicit `LOCATION_INCLUDE` entry, because a
trailing suffix is the one form the "remote" term no longer reaches. And a bare "Milwaukee, WI"
still returns False, as do Minneapolis, Columbus, and Phoenix: `LOCATION_INCLUDE` is a curated
18-city list with a default-exclude behind it, so an on-site role in any unlisted US city is
dropped. That is a coverage gap, not the substring bug, and Aneesh scoped it out on 2026-09-11.
Adding state names and USPS codes is the fix whenever it becomes worth the wider intake.

## D23. Per-posting country stamps

_From CLAUDE.md, User-Surfaced Finds Protocol._

**Per-posting country fields are read and stamped as of 2026-09-11 (`pipeline/countries.py`).**
The three location gates read one string, and until now the only way that string could say
"not the US" was `NON_US_MARKERS`, a hand-kept list of countries, regions, and cities. Several
ATSes return a structured country per posting (Comeet `location.country`, SmartRecruiters
`location.country`, Ashby `address.postalAddress.addressCountry`, Lever `country`, Workable
`country`, Paylocity `JobLocation.Country`), and ignoring it is what made Dot Compliance's Canadian
role read "Montreal, Remote" and forced "montreal" onto the marker list by hand. `parse_location`
and the harvest probes now append a `(non-US: Canada)` tag when the field resolves to a non-US
country, and `us_reachable`, `tier3_location_ok`, and `location_relevant` check for that tag first
and answer False outright, dual-region rescue included. Two rules keep it safe: a US, absent, or
unrecognised country stamps nothing (Upwind returns `country: ""` on real Chicago and Dallas
postings, and appending "United States" to a US string would move every on-site role into the
+20 scoring bucket), and `GE`/`GS` stamp as the bare code because "Georgia" is an Atlanta hint.
Property checks at the bottom of `test_tier3_gate.py` re-derive both rules.

**Rippling is the one adapter left with a country field it does not read, and that is a
decision rather than an oversight.** Its two paths disagree in shape: the listing page carries
`locations[].country`/`countryCode`, the board API carries it inside `workLocation`, and
`rippling_api_items` collapses both to a name-only list because one posting can hold six
locations (Nutrient's Workflow Support Engineer across six LatAm countries). Stamping it needs
the country carried through that collapse plus an all-locations-non-US rule, which is a
different change from the one-line stamp the other six took. Greenhouse, JazzHR, and Workday
return no country at all, and Pinpoint's `location.province` merely sometimes holds one
("United Kingdom"), which is free text, not a field. So `NON_US_MARKERS` is still the only
signal for those and for the LinkedIn grader: the stamp shrinks what the blocklist has to
cover, it does not retire it. Leave "montreal" where it is.

## D24. Workday locations and pagination

_From CLAUDE.md, User-Surfaced Finds Protocol._

**Workday "N Locations" postings are resolved from the detail endpoint (fixed 2026-09-14).**
The list view gives no city for multi-site roles, and `fetch_workday` stashed those as
"Unknown", which `location_relevant` keeps as neutral; NVIDIA's UK, Munich, and Bengaluru
architect roles leaked into `ai_engineer_stretch` that way, and the same path fed matched and
borderline. A census of 46 boards found 25% of postings in that shape. `parse_location` now
reads `jobPostingInfo` for them (after the title gate, one cached request shared with the
start-date resolver), joins primary + `additionalLocations`, and stamps the primary's country
unless an alternate names the US, since Workday's country field describes the primary only.
On a failed detail read the externalPath segment is used to exclude, never to include: a US
segment the gate can't read ("Louisville KY") stays Unknown. One consequence: a multi-location
US posting whose every location is an unlisted city now drops, same as its single-location twin
under the curated-city gap below. `harvest_ats.py`'s Workday probe still scores "N Locations" as
not US-reachable, which under-admits rather than leaks; not fixed.

**Workday boards were read 40 deep, not 200 (fixed 2026-09-11).** Workday reports the board's
real `total` only on the offset-0 response; later pages answer `total: 0`, and `fetch_workday`
re-read it every page, so the loop ended after page two on every board (JLL 40 of 2000, Stord 40
of 98). It reads `total` once now and treats a short page as the last page. The cap is
`WORKDAY_MAX_POSTINGS`, raised 200 to 1000 on the same day from a measurement across all 46 live
boards: 200 left about 230 fresh title+location matches unread, including a tier1 at Salesforce
#400; 1000 leaves about 18 for 641 requests a run. `pipeline/test_workday_pagination.py` simulates
both the total-once behaviour and the cap with a fake session, no network.

## D25. Queue-vs-Gmail check

_From CLAUDE.md, Job Search Dashboard._

**Queue-vs-Gmail check, 2026-09-19.** Aneesh asked whether queued roles had already been sent.
All surfaced rows were checked against employer and ATS email since 2026-06-01. Result: the
confirmation sync was wrong on ONE row. One employer's Workday rejection went to his
other address rather than the `+jobs` alias, so Step 0.5 never saw it; recorded via
`mark_outcome.py`. He applies only through the aliased address from here on and called the
miss a one-off, so **no change to Step 0.5 was made or is wanted.** Two other apparent misses
were false alarms that came from matching on company alone: a second, unsent req at a company
where a similarly titled req was already `applied`, and a new req at a company whose earlier
same-title req was already `rejected` (the row's own notes said so). Lesson for the next check
of this kind: compare against the tracker row's URL and notes before calling anything a miss.
Two rows stayed unresolved because the employer emails never name the role; left alone at his
call.

## D26. Why the JD screen fans out

_From CLAUDE.md, JD Screen Fan-out._

The daily run now reads every shortlist JD instead of only the 3-4 it picked from listing
data (924 matches -> 49 shortlisted -> 4 tailored on 2026-09-24, most of the 49 never read).

## D27. Why assisted apply exists

_From CLAUDE.md, Assisted Apply._

Built 2026-08-28 after a Workday application form was abandoned mid-way. Aimed at the
high-effort ATSes (Workday, Paylocity, Taleo, iCIMS) that make him retype his whole work
history after an upload, which is a plausible contributor to the 38% send rate and
31-day median at `stage=surfaced`.

## D28. The ramp line converged again

_Added 2026-09-29._

Of the letters written in the first two days after the 2026-09-27 restructure, five carried a
ramp commitment, and four used the same construction: "I'll [work through a named resource]
before a first conversation" (or "before a first interview"). Only one varied it ("This week I'm working
through..."). That's the 2026-09-02 failure from D5 again, and the likely seed was the rule's own
parenthetical, "(he has already begun, or begins before the first conversation)": a quoted
example turned into the default sentence. The rule now lists kinds of commitment without an
example phrase and asks for a check against the last five letters. The four promises also named
specific training or reading, which a sent letter holds him to, so the rule now says to promise only work
he'll actually do.

## D29. Why tailoring got a fixed brief and one fit check

_Added 2026-10-09._

On the 2026-10-09 run the five Fable writers were 54% of the run's cost. Each sent 14 to 28
requests and made 46 to 101 tool calls, re-reading its whole conversation every time; the
writing was a few percent of that. No prompt named the files to read, so each writer listed
`tailored/` and read 8 to 13 earlier files. Nothing in `pipeline/` counted pages: all five
first-draft resumes rendered to three pages, two writers never checked, and both of those
reached `tailored/apply_now/` at three. Two writers opened on the same story, and the
orchestrator reworded two summaries after the writers returned and re-rendered with no page
count. The `avoid-ai-writing` pass didn't run on 2026-10-08 or 2026-10-09.

The fix kept Fable writing every word and removed the hunting and the loop: a fixed brief,
budgets up front, and `fit_check.py`. A Fable review before install found that a full-tier
package with no letter passed as light tier and that a reused stem could overwrite a sent
package before any guard ran; the tier marker and `--claim` came from that. Only about 150
of 377 tracker rows named a PDF at the time, which is why `--claim` also looks at
`tailored/` and why Step 6 now requires the filename in `notes`.

## D30. Three false title matches

_Added 2026-10-09._

A one-off sweep of non-software Atlanta employers ran its titles through the live matcher, and
three matched that shouldn't have: "General Manager, DC Operations" (tier2d, because `_stem`
cut "generalist" down to "general"), "Technical Sales Support Manager" (tier 1 through
"Technical Support Manager"), and "Director, Engineering & Operations Support" (tier 1 through
"Director of Support Operations"). Each was measured against all 85 hit files, the LinkedIn
card files, and the enrollment queue before anything changed. The first had never fired in
pipeline data. The second had graded one LinkedIn card tier 1. The third's shape, "X Operations
Support", had put two roles on the shortlist for 12 run-days through the tier-1 guarantee and
graded four card titles tier 1, three of which queued a board probe.

The fixes: "generalist" is kept whole in `_TOKEN_ALIASES`, and "operations support" and "sales
support" joined the hard-exclude list, since the softer lists can't reach a tier-1 match. Two
things were left alone on purpose: the "Ops Support" spelling, where the title doesn't say
whether the role is wrong, and the "ist" suffix rule itself, because dropping it would also
undo the strategist/strategy collapse.

The same scan showed a larger class this didn't touch. Tier 1's override of the "product
manager" exclusion put four PM roles on the shortlist about 60 times in four weeks.

## D31. The industrial lane and what was measured first

_Added 2026-10-10._

The 2026-10-09 sweep in D30 found roles in Aneesh's line at building-technology and materials
employers the pipeline had never shown him, and he picked a narrow lane of eight employers over a
broad one. Before anything was enrolled, each board was tested against the adapters the poller
already has, and each proposed title and guard term was measured on the lane boards and on the
595 watchlist boards that answered that night (50,092 postings).

The measuring changed the plan in three ways. Only three of the eight boards were readable as
they stood: two Workday boards, and a SuccessFactors rss feed whose 1,813 postings had outgrown
a 1,000 cap in no date order, so the cap was reading a fixed 55% of it. A fourth, a
SuccessFactors urlset board, reads 60 of 283 at its cap and stayed on the manual list with the
four that have no adapter. The six "missing" titles turned out to matter little: as review-only
entries they would have surfaced one lane role and four watchlist lines that day. The guard
mattered more. The three polled boards produce 75 title-gate hits, 31 of them field engineers,
and five per-company `role_exclusions` terms cut 41 without touching any of the 14 roles a hand
read of the same boards had kept. Applied to the whole watchlist, the same terms would have cut
63, 27, and 39 titles that surface today, tier 1 and tier 2 matches among them, which is why the
guard is per company.

Why a lane of its own rather than plain enrollment: the rubric already pays these employers
well. Atlanta location, pay, and 20 to 25 company points put a wrong-function title near 75 on
structure alone, three points under light tailoring. Step 3.6 therefore gates on location and
on a JD read, caps its own digest section, and keeps lane roles out of Step 2.

Left alone on purpose: adapters for the four manual boards and the urlset cap, field-service
and shop-service titles, any new bonus, and a second stem collision the sweep exposed. One lane
employer's subsidiary is named "Automated Logic", which stems to the same token as "Automation",
so any of its titles that also says Manager matches tier 2c "Automation Manager". The guard
catches most of them by other words; the stem rule itself was not touched.

Two things the measuring missed, found the same day by running the real `poll_all()` on the
three lane entries instead of replaying its title gate. First, counting title-gate hits is not
counting what a run sees: the shortlist cutoff sat at a pre-score of 54, and low-priority
enterprise entries mostly pre-score under it, so only one of ten lane title matches in metro
Atlanta or remote cleared it. Step 3.6 reads `near_window` for that reason and names the limit.
Second, the replay had skipped the poller's description filter as negligible. It is not: the
filter is a substring match that includes "defi", so a posting whose description says "define"
or "defined" is dropped as crypto on any board whose feed carries descriptions. That removed 104
of 1,805 postings on the SuccessFactors board, three lane title matches among them. The filter
was left as it was and flagged for its own fix.

The lane-only poll followed that evening: `pipeline/poll_lane.py` runs the same `poll_all()` on
each lane entry alone and writes its own file. Its first clean dry run found 32 candidates on
the three boards, 14 of them in Georgia or remote, where the main hits file would have carried
two. Building it turned up three more things. The SuccessFactors feed is one 31 MB response, and
twice in an hour it dripped for 11 and 27 minutes before failing, because the adapters' timeouts
bound the gap between bytes and not the whole read; the helper gives each board 150 seconds of
wall clock for that reason, and the main poll has no such bound. `fetch_jd.py` returns only
section headings for that same board, so its candidates can be found but not yet read. And the
low-priority lane entries were not quiet in the main poll: on that day's pre-scores about four
lane roles would have sat in the main shortlist at a cutoff of 54, three of them in other
states, each taking a slot and a JD card for a role the lane's location gate then drops. Aneesh's
call the same evening: the main poll skips any entry carrying a `lane` marker, and the lane poll
is the only reader of those boards. The entries stay in `companies`, because that list is what
`check_company.py`, `harvest_ats.py`, `audit_scores.py`, and the watchlist +10 read as enrolled.
The price is that no lane role gets a Step 2-JD card; every lane JD is a direct read, two a run.

## D32. The industry filter matched inside ordinary words

_Added 2026-10-10._

The poller's industry filter was a substring test over five terms, and one of them was "defi".
It fired inside define, defined, defining, redefining, definition, and deficiencies, and a hit
drops the posting with a bump to `stats["excluded"]` and no line anywhere in the digest. D31's
dry run is what exposed it.

Measured before anything changed, by re-reading every board whose payload hands the filter a
description (Lever, Workable, Comeet, Pinpoint, and SuccessFactors: 77 boards that day, and the
other 553 never reach it). 559 of 4,376 descriptions tripped it, on 50 boards. Every one was a
"defi" word. None was a crypto posting, and no description held "crypto", "web3", "blockchain",
or "nft" in any form, "cryptography" included. One board lost 70 of its 76 postings to a single
boilerplate sentence with "redefining" in it, and four boards lost every posting they had. Most
of the 559 would have died at the title gate anyway: 50 passed it, and 15 cleared every gate and
were dropped by this one, a tier-1 title among them. Replayed through the real `poll_all()`,
those 15 were 12 title matches, 2 borderline, and 1 FYI line.

The fix: `EXCLUDED_TERMS` is a list of whole words matched through `_boundary_pattern()`, the
helper the location lists already use. Each spelling is listed, so "cryptocurrency" and
"cryptoassets" are named and "cryptography" stays out on purpose. The control was seven real
crypto employers' boards: the old rule excluded 154 of 183 descriptions and the new one 149, and
the five it lets go had been caught only by "redefine" and "tradefi". A review of the patch found
that an empty term list would have compiled to a pattern matching at every separator, so
`_boundary_pattern([])` now matches nothing. Cases live in `test_industry_filter.py`.

Left alone on purpose. The bare word "crypto" still excludes, which will misread security
shorthand ("crypto libraries") if a board ever uses it; 80 of the 149 control exclusions rest on
that word alone. The filter still reads only `description` or `content`, so Ashby, Greenhouse,
Workday, and most other adapters never reach it, and on Lever it sees the opening section only.
The JD screen's `crypto` flag is the check that covers every shortlisted role. A drop still left
no trace that day. Since 2026-10-11 each one is written to the poller's output and the lane
poll's file under `industry_excluded`, with the word that caused it; the digest is unchanged.

## D33. Frozen boards passed for live ones

_Added 2026-10-11._

The harvester's enrollment test was "the board answers and has fit-titles on it," and a board
keeps answering after its company has moved to another ATS. On 2026-09-29 it enrolled Aircall on
`lever/aircall` with 77 postings and 4 fit-titles. The newest posting was from 2026-07-10, 81 days
earlier: Aircall had moved to Greenhouse and left the Lever board up. Four days before that it
enrolled Progressive Insurance on a SmartRecruiters sandbox whose newest posting was from 2022
(one of its postings is titled "Maria Test Job"). The poller never gets an error from a board like that, so
both sat on the watchlist until a sweep on 2026-10-10 polled all 630 boards and compared each
one's newest posting date.

Measured on that sweep's table before the cutoff was chosen. 569 boards gave a newest posting
date, 39 gave none (Rippling 23, JazzHR 6, Pinpoint 4, iCIMS 3, and one each on Gem,
SuccessFactors, and Workday), 10 were empty, and 12 errored. 23 of the 569 had no posting newer
than 45 days, and 3 of those had moved or died: the two above, and a board with a single 2021
posting whose company had moved to an ATS the poller has no adapter for. The other 20 were the
company's real board, posting slowly. Other cutoffs flag 28 boards at 30 days, 17 at 60, 13 at
75, and 12 at 90, with the same three in each.

The rule only runs at enrollment, so the closer read is what a board looked like on the day it
went in. Of the 275 auto-enrolled boards with dates, 5 had a newest surviving posting more than
45 days older than their enrollment date: the two above, and three real boards at 883, 110, and
51 days. At 60 days it's 4, and at 90 Aircall gets through. Read those as "about," since the
table can't see a posting that has closed since, or what a board that has posted since looked
like that day. One of the three is a company with a role that was applied to the day after the
board went in, which is what a false flag costs: a real board held back until someone looks.

The fix. `probe()` returns a `Postings` list carrying the newest posting date from the response
it already read, on Greenhouse, Ashby, Lever, Workable, and SmartRecruiters; Comeet and Workday
pass theirs in `meta`. Dates come from `poll_ats.extract_posted_date`, so the harvester and the
poller read the same fields, and no probe costs an extra request. `main()` won't enroll a board
whose newest posting is more than `FROZEN_BOARD_DAYS` old (45: the sweep's number, and just past
the poller's 40-day posting cut, so a board over the line has nothing the poller would shortlist
that day). It writes a rejection with `frozen_board: true`, `manual_review: true`, and
`unpollable: false`: the board was found, and the next step is one look at the company's careers
page, not a search for a board. `--skip-freshness` is the hand override for a company whose
careers page still links the slow board. `--names` isn't one, because the run's own rechecks
use it. Cases live in `test_harvest_freshness.py`.

Left alone on purpose. Boards with no dates enroll as before, and iCIMS counts as one of them:
only one of the four iCIMS boards in the sweep showed a date. Workday's list says "30+ days" for
anything older, so a first page of nothing else costs up to three detail reads, and an
unresolved one counts as unknown. Comeet has only `time_updated`, which any edit refreshes. A
date that can't be read never blocks an enrollment. And the check runs at enrollment only: a
board that freezes or empties after it's enrolled is still found only by `--prune` or a sweep.
The 2026-10-10 sweep found three that way (PlayOn, Iterable, and UpGuard), each having left an
empty board behind.

## D34. The dashboard takes marks

_Added 2026-10-12._

On 2026-09-19 the dashboard was built read-only on purpose, and write-back from the page was
turned down: a second source of truth beside `outcomes.csv` was the thing this repo kept
getting burned by. That reasoning was right about the risk and wrong about the cost.

Three weeks later Aneesh said the pipeline felt like it gave him a small portion and that the
loop of email, applying, and tracking on the Shelf was finicky, and asked for it to be looked at
whole. Measured on 2026-10-12:

- The apply queue held 98 rows. Nothing but the 45-day retirement ever removed one, because
  there was no way to say "I'm passing on this."
- By week surfaced, the share of packages sent had gone from about half through mid-September
  to 15% for the week of 2026-10-05 (4 of 26), while output held at 21 to 27 packages a week.
- `his_verdict`, added 2026-09-30 as the only place the pipeline hears his judgment of a pick,
  was blank on 197 of 230 post-epoch rows. Setting it took a terminal command.
- The page's own tick storage held one tick, made the day after the page was built.
- `tailored/apply_now/` held 139 PDFs against a design target near 30. The rotation matched a
  PDF to its row only when the row's notes named that exact file, so older packages and every
  `_ATS` variant were never matched and never left.
- In his own run sessions on 2026-10-02 he had written "I have to get better about using the
  dashboard. That seems like the easier pathway versus these emails," and asked "can i add
  notes in the dashboard html or should i do here."

So the page now takes Sent, Skip, and Later on every queue row. What the 2026-09-19 decision
was protecting is kept: the marks are an inbox in the Shelf's storage, drained once a run by
`shelf_inbox.py` through `mark_applied.py` and `mark_verdict.py`, and the generator still
writes nothing but the page. There is no second record to drift.

Two things about the drain are deliberate. It writes the verdict before it promotes the row,
because the verdict carries the note that a send is on his word alone; a run that dies between
the two leaves a state the next drain finishes, where the other order would lose the note. And
a Skip never changes the stage: the row stays `surfaced` until it retires, and every reader of
the queue (the page, the folder rotation, the run's "still unsent" lines) checks the verdict
instead. A new stage value would have meant a schema migration for a distinction one column
already holds.

Not taken: replying to the digest in free text (nothing to click, and text to parse); a
published page with its own database (works from the phone, but moves the queue off this
machine and puts a connector in an unattended run's path).

The same change cut the digest to the picks, alerts, and what each letter promises, and moved
the rest to the page through `brief_[date].json`. The 2026-10-09 digest had carried about 80
role lines to deliver 5 picks.

## D35. Contact details in published files

_Added 2026-10-12._

The spec keeps Aneesh's mail-routing addresses out of this repo with `{{PLACEHOLDER}}` tokens
filled from `pipeline/local_config.json`. That rule was written about addresses a run sends to,
and it covered them. It didn't cover an address that is only shown. On 2026-08-30 the
ATS-renderer passage in `daily_task_prompt.md` quoted a raw text extraction of the resume's
contact line as its example of the defect, with the phone number and the apply-account address
in it. A quoted tool output reads as evidence, not as a value, and it went in.

Looking for other copies on 2026-10-12 found the same two values as string literals in
`pdf_helpers.py` (the styled contact line, the ATS renderer's plain lines, and a docstring
example) and in `generate_pdf.py`. The renderers need the real values and had always carried
them inline. The sweep covered every tracked file: six lines in three files, no other
phone-shaped string, and no other address except third-party alert senders.

The fix. `pdf_helpers.load_contact()` reads phone and email from
`pipeline/application_profile.json`, which is gitignored and already held both, and all three
builders call it. It raises on a missing file, a missing key, a blank, or `NEEDS_ANEESH`,
because a resume with an empty contact line still looks finished. `generate_pdf.py` reads the
same file; Aneesh waived its never-modify rule for this one change. The spec's example and the
docstring now use `555-555-0100` and `jane.doe@example.com`, and the spec says they're
placeholders so a later session doesn't correct them back. Four renders (styled, ATS, cover,
and the legacy script) were compared before and after: same pages, text, links, and drawn
content.

`pipeline/test_contact_source.py` holds the line. It fails when a tracked `.py` or `.md` file
has a phone-shaped string outside the 555-01xx example block, or an address at a personal
mailbox provider, and it reads no real value to do that. It skips `.json` on purpose: the
candidate queue carries scraped posting text and would trip it.

## D36. The letters went brutalist

_Added 2026-10-12._

An application form made Aneesh paste a letter's text, so he read one closely for the first
time in a while. His words: "a little disjointed and, honestly, kind of harshly written," and
later that he wanted them "not brutalist." It wasn't one bad letter. Five October letters read
side by side had the same build: a cold open on a story and a number, two more paragraphs that
each started over with no bridge, a gap paragraph that told the reader what their own bar was,
and a close that asked a pointed question and ended on a maxim. None said which job it was or
that he wanted it.

What was measured that day. About 2 of 42 October `_cover.md` files carried a sign-off, against
about 75 of 84 in September (by file date); the PDF renderer adds `Best,` on its own, so only
the paste copy lost it. Four of five closes used one construction, "X reads differently
depending on the answer." All 33 sends with a recorded `his_verdict` were `sent_as_is`, so the
drift had gone out unread. Two September letters still had bridges and read warmer; they also
broke the relevance-label ban.

The cause is the shape of the rule set. Step 8 had grown as a list of things to take out: no
company opener, no enthusiasm words, no relevance labels, no thanks-and-welcome close, a
specific question to end on, the gap named with a dated promise. Each came from a real miss.
Nothing asked for warmth back, and the gates count contractions, em-dashes, and sentence
rhythm, none of which can see tone. The writers on a fixed brief since 2026-10-09 follow the
bans more faithfully than the earlier ones did, which is what made it plain.

The fix is six additions, written as requirements: say which job and why, one bridge a
paragraph, don't grade the reader, no hard-guy hook, end inviting, and sign off in the `.md`.
One unsent letter was redone under them the same day; it kept its opener, its gaps, and its
promise, came out at 371 words from 398, and passed the fit check. He read it and said yes
before the rules changed.

Open. No mechanical check reads tone; the orchestrator's side-by-side read (Step 4-W item 6)
is the only place it's looked at. Bridges and closing lines are the next things likely to
converge, the way the ramp line did in D5 and D28. Unsent October letters written before this
date still have the old build.

Left alone on purpose. The name, city, and LinkedIn URL stay in the renderer. A worktree or a
fresh clone has no profile and can't render until it's given one, the same as every other
gitignored input.

## D37. The one-line pivot and two new repeats

_Added 2026-10-13._

The first run under D36's six rules wrote three letters, and Aneesh asked that evening how
they read. The rules had fixed what they named: all three said which job and why by the
second paragraph, signed off, and ended on a line asking for a reply, and none graded the
reader. One still read cold. It had a four-word sentence standing alone as its own paragraph,
two maxims in the body, and a last line phrased as an order.

The cause of the first was in the briefs, not the writer. `tailor_worker.md` and Step 4.5 of
the daily prompt both listed "a single-sentence pivot" among the protected moves, so the
writer kept exactly the thing he had called brutalist the day before. The style guide gives
that move to analytical and longform writing; in a 350-word letter it lands as a terse
fragment.

What was measured that day, reading the last five letters side by side. Three of five closes
asked who owns or carries something, two of them in nearly the same sentence. All three of
the run's letters carried the Maven sentence in one three-part build (the evaluation
checklist, sole integration partner for two months, the deflection figure), and two used the
same phrase for having sat on the buying side. "Having said that" appeared once in five, so
the bridges had not converged yet.

The fix, on his yes to both changes. The single-sentence pivot came off both protected
lists, and Step 8 now says no paragraph is one short sentence standing alone. The last-five
check covers the closing question's shape and the Maven sentence as well as bridges and
closing lines. The orchestrator's side-by-side read (Step 4-W item 6) names both too, because
writers dispatched in one run can't see each other and the last-five check can't catch a
repeat written the same morning. The cold letter was redone that evening by a fresh writer
from a description of the problems and passed the fit check; it hadn't been sent.

Open. No gate reads tone, same as D36. The line saying where he lives and that he already
works remote sat in three of the five closes and isn't covered by any rule. That letter also
described his use of the company's product in a way that sat badly beside an earlier letter
sent to the same company; the run had flagged the sentence for him to confirm, which is what
caught it, but nothing checks a new letter's claims against a sibling's promises.

## D38. Letters with no people in them

_Added 2026-10-13._

The same evening as D37, Aneesh said more about the letters in general: "fairly staccato,"
and "it wasn't an empathetic writing style." His point was that someone applying into support
organizations has to sound like he has a soul. He asked for pushback, and got it: the
complaint was right and the cause wasn't rhythm.

What the letters had instead of people. Read as a set, they were about audits, systems, and
numbers, and humans appeared as things he had measured. No customer appeared as a person with
a problem, and nothing said why he has stayed in support for a decade. D36's six rules add
warmth toward the reader; none of them puts a person in the story.

Why the writers couldn't fix it. They may only use facts from `master_resume.md` and the
career narrative's story bank. Counted that evening, the two files held no use of "felt,"
"frustrated," "worried," or "care about," and nothing in first person about why he does the
work. The two stories with a person at the center were written as audit findings. Telling a
writer to be more empathetic would have produced adjectives, which the voice rules ban for
good reason.

The test. One unsent letter was rewritten two ways by separate writers: one changed only how
the sentences ran, the other was rebuilt around a person, with one gap, three numbers, and a
bracketed placeholder wherever the sources had no human detail. The rhythm-only version came
out longer and denser and no warmer. He picked the other. Its two placeholders asked for a
customer he remembered and a reason he had stayed; he dictated both, plus a third story, and
they went into the story bank as "Human moments," marked as his words with no line in the
master resume. A light-tier package was then given a letter built that way, which passed the
fit check with no new dated promise in it.

The fix, on his yes. Step 8 gains "People first": one story with a person at its center, his
reason for the work in his own words when it fits, one named gap where every gap used to be
named, three numbers at most, and a turn to what he built whenever the story is one where
only he could help. The orchestrator picks the person at Step 4-W item 2 and no two letters
in a run lead with the same one. Nothing about a person is ever invented; when no story fits,
the letter is written the earlier way and the digest says so.

Open. The bank holds three human moments, and a run can write five letters, so the stories
will repeat across letters unless he supplies more. Those three have no line in
`master_resume.md`, so resumes can't use them yet. No gate can tell a person from a number;
the side-by-side read is still the only check. One named gap is a narrowing of his own
2026-08-20 rule and has been tried on two letters, so watch whether an unnamed gap costs him
in a screen.

## D39. A re-tailored posting had no row

_Added 2026-10-13._

On 2026-10-13 Aneesh asked for a fresh package on a posting first tailored in July. The package
was written and gated, and then nothing could record it. `update_tracking.py` skipped it twice
over: its dedup key was already in `seen_jobs.json`, and its URL already had a row, `expired`
since the 45-day retirement. With no row there was no queue entry on the dashboard and no Sent
button, and a confirmation email would have landed in `mark_applied.py`'s "not surfaced and not
sent" pile. Flipping the old row back by hand was off the table, and it wouldn't have held
anyway: `surfaced_date` would still say July, so the next `age_report.py --apply` would have
retired it again.

It wasn't the first time, only the first time anyone saw it. Replaying all 139 track files that
day showed the same silent skip had dropped four packages since 2026-08-14 whose posting
already had a retired row at the same URL, plus three postings tailored as a new requisition
under a dedup key the tracker had seen. The Step 4-pre guard (2026-09-01) ended the same-URL
kind for the daily run, which is why it took an interactive ask to surface.

Two designs were weighed.

- **A second row for the same URL.** It keeps the old row untouched and counts both packages.
  It lost because `mark_verdict.py --url`, `shelf_inbox.py`, and `mark_outcome.py` each write
  nothing when two rows share a URL, `mark_applied.py` classifies a repeat confirmation by
  whichever row comes first, and `pipeline_quality.py` would count one posting twice. Five
  scripts would have had to learn which row is the live one, in the code where a wrong-row
  promotion has already happened once.
- **Reopen the row in place.** Taken. The URL stays on one row, so those scripts work
  unchanged. The cost is that the row's history moves: the earlier package's date, score, and
  verdict leave the tracker for `jobs/reopened_rows.jsonl` and a one-line stamp in the notes,
  and `pipeline_quality.py` prints how many rows that is.

Most of the design is what a reopen refuses. A row that shows any sign of a send is the record
of that application. For post-epoch rows that includes an `applied_date` that moved off its
`surfaced_date` and a `seen_jobs.json` entry flipped to applied, because a `closed` row promoted
before it closed carries nothing else. A `closed` row needs `"never_sent": true`, which is his
word. A row still `surfaced` is refused because dashboard marks are stored under the URL and
the page hides a marked row, so a Skip made on the old package would land on the new one; an
open package gets adjusted under its own stem instead. For the same reason `shelf_inbox.py` now
treats a mark dated before its row's `surfaced_date` as stale. Two Fable review passes found
the same-day-send hole and a crash on null notes, and moved the stale-mark guard from a known
edge to a fix.

Not done: the earlier lost packages were not backfilled. Each is a row that's missing or that
describes an older package, and reconstructing them is his call.

## D40. Reach roles stopped taking the first slots

_Added 2026-10-15._

The 2026-10-15 weekly report showed fit roles advancing 4 of 63 and reach roles 0 of 36, while
October's tailoring had moved to 61% reach (37% in August and September). Two read-only checks
followed, at his ask.

- **Send speed was ruled out.** 93 of 102 post-epoch sends went out within two days of
  tailoring, and all four advances were in that group. The 18-day median age on surfaced rows
  comes from packages that never get sent, not from slow sends.
- **The reach label was somewhat inflated, and the signal survived it.** Of the 36 reach sends,
  11 had the cap fire and 25 were reach only on a count of 2+ unmet. Several of those counted
  items the JD marked preferred, softened itself ("or the ability to quickly get there"), or
  that were location. Recounted, roughly 30 reach sends, still none advanced. All four advances
  had 0 or 1 unmet.

Four options were put to him: fit first with reach filling leftover slots, only tighten the
count, keep aiming high, or cap reach at 2 of 5. He picked fit first. The five slots now fill
from 0-1 unmet roles by score, then reach roles if slots remain, and both the writer brief and
Step 6 count only stated requirements as unmet. Reach roles still surface on "Cleared, not
tailored", so nothing is hidden; this changes which ones get a package by default. The
tailoring cap itself is unchanged, per "Measuring pipeline quality" in CLAUDE.md.

The samples are small. Re-read `pipeline_quality.py` once another ~40 fit sends have verdicts:
if fit roles still advance at around 6%, the bottleneck is somewhere other than the pick.

**Safety slot, added the same day.** He called the search a moonshot he's comfortable with,
and wanted likely-yes roles mixed in for interview practice. Three options: start a reserved
slot now, decide at the four-week review, or only list likely-yes roles without tailoring.
He picked starting now, so the review has four weeks of data. The slot sits outside the five,
at light tier, takes one role a run with a title he has held and 0 unmet requirements, and
has no score floor, because the rubric's company bonuses are exactly what keeps those roles
under the threshold. Rows carry `lane:safety` in `notes`. The 2026-11-12 follow-up was
widened from a check of this rule to a full reassessment comparing fit, reach, and safety.
