# Decisions and Incidents

The stories behind the rules in `CLAUDE.md`. Each rule there that came out of an incident or a
standing call links to its entry here. Nothing in this file is an instruction: the rule in
`CLAUDE.md` is what governs, and a number here is what was true on the date it names.

Every entry was moved verbatim from `CLAUDE.md` on 2026-09-27. "Above" and "below" inside an entry
point at the old layout; commit `8e0e352` has it.

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
