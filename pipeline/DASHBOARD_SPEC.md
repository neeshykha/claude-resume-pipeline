# Job Search Dashboard: build spec (2026-09-19)

Follows `DASHBOARD_HANDOFF.md`. Nothing is built. This file verifies the handoff against the real
files, corrects it where it was wrong, and specs phase one. No company names in here on purpose;
the repo is public.

## The short version

The handoff's shape holds: one read-only generator, one self-contained HTML file, ticks stored in
the Shelf. Three things change.

1. **The Shelf will not pick up a regenerated file.** Same path in Downloads is skipped outright.
   Phase one needs a small, opt-in Shelf change (about 40 lines of Swift) before the daily
   regeneration means anything. This is the "afternoon vs weekend" answer: closer to a long
   afternoon, split across two repos.
2. **The apply queue is 85 rows, not a dozen.** Sorting by "dies soonest" would put the deadest
   postings on top. Default view should be fresh roles by score; expiring is a filter.
3. **Manual-check entries carry no URL.** Only a search `query`. The generator needs a
   `careers_url` added to 29 watchlist entries, with a search link as the fallback.

## Handoff claims, checked

| Claim | Verdict | What's true |
|---|---|---|
| `outcomes.csv` has 16 columns | Correct | Header matches the handoff's list exactly. Zero rows with a drifted column count. The repo `CLAUDE.md` still says 15; `ic_scope` landed 2026-09-07 and that doc is stale. |
| 280+ rows | Low | 309 rows. |
| "40 to 50 rows in surfaced or applied" | Wrong | 85 surfaced, 81 applied. Also 104 expired, 29 rejected, 8 closed. |
| Stage vocabulary is clean | Not quite | Two rows carry `assessment` and `interview` as a **stage**, which is off-vocabulary (those belong in `furthest_stage`). The generator has to tolerate unknown stages rather than drop them. |
| Queue = `stage = surfaced` | Correct | 77 dated, 8 with no `surfaced_date`. |
| 45-day expiry | Correct | `age_report.py`, `DEFAULT_DAYS = 45`, ages from `surfaced_date` only, never retires an undated row. No importable per-row function; the logic lives inside `main()`. Reimplement the five lines, and import `DEFAULT_DAYS` so the number has one home. |
| Gone quiet = applied + `outcome = pending` | Incomplete | Of 81 applied rows, 67 have a **blank** outcome and only 13 say `pending`. Blank and pending have to be treated the same or the list shows a sixth of reality. |
| PDF paths are in `notes` | Unreliable | 32 of 85 surfaced rows mention a `.pdf`; 25 mention `apply_now`. And `rotate_apply_folder.py` evicts from `apply_now/` after 7 days, so a path in notes goes stale by design. |
| Blind-spot list is ~6, backlog ~18 | Wrong | 16 and 13. Both are dicts with the entries under a `companies` key, not bare lists. |
| Watchlist entries may carry a URL | No | Fields are `name, why, query, last_checked, last_hit` (one entry also has `query_needs_repair`). No URL, no id. 11 of 16 blind-spot queries contain a `site:` domain; 2 of 13 backlog queries do. |
| Pending enrollment entries with `manual_review` | Empty today | `pending` has 0 entries. The flags live in `rejected` (73 manual_review, 39 not yet surfaced; 237 unpollable, 153 not yet in a weekly report) and `enrolled` (4, 2 unsurfaced). |
| `manual_review_surfaced` might be in the CSV | No | It's in `enrollment_candidates.json` only. It means "already shown once in the digest," nothing about whether he looked. |
| `interviews.json` doesn't exist | Correct | Five company folders under `interview_prep/`; filenames match the handoff's pattern. `interview-scan` runs Mon and Thu and posts to Discord; it writes no structured file today. |
| `.venv/bin/python pipeline/build_dashboard.py` will run unattended | Yes | `Bash(.venv/bin/python *)` is already allowlisted in the project settings. |
| Dated copies in `pipeline/jobs/` stay private | Yes | That directory is gitignored. `build_dashboard.py` itself would be committed, so it must contain no company names or sample data. |

## The Shelf question, answered

Read `Library.swift:205-249`. `autoImportFromDownloads()` filters out every path already in
`seen_sources.json` before it does anything else, and the ledger key is the absolute path alone:
no mtime, no hash. So `~/Downloads/job_dashboard.html` imports once and is never looked at again.
A second guard would stop it even if the ledger didn't: any file whose name matches an existing
page's `originalName` is skipped.

Everything else the handoff hoped for is true. Page storage is keyed by the document UUID
(`Data/<uuid>.json`), `updateFromSource()` overwrites the stored HTML and keeps the id, so ticks
survive an update. It's only ever called from the right-click menu. An in-place update leaves
`dateAdded` alone, so there's no daily "New" badge and no nightly #shelf ping. The iCloud mirror
copies on size or mtime change, so the phone gets each day's page; ticks made on the Mac seed the
phone, and phone-side ticks stay on the phone (existing behavior, fine here).

### Options

| | Route | Verdict |
|---|---|---|
| A | **Opt-in source tracking in the Shelf.** A page remembers its source path; the watcher refreshes it when the source changes. | Recommended |
| B | Generator writes straight into `~/Library/Application Support/HTMLShelf/Files/<uuid>.html` | Works today with no Swift, but couples the pipeline to Shelf internals, needs a new write permission for the scheduled run, and the iCloud mirror doesn't fire on it, so the phone goes stale. No. |
| C | Live-URL entry against a local web server | Native `localStorage` would hold the ticks, but it needs a server running forever and the phone can't reach it. No. |
| D | Dated filenames, new page daily | Ticks reset every morning, 30 pages a month of clutter. No. |
| E | He right-clicks Update from Source each morning | Zero code, and it will last four days. |

### Option A, specced (HTMLShelf repo, separate small build)

- `HTMLDocument` gains `trackedSource: String?` (optional, so `library.json` migrates itself, the
  same trick as `pinned` and `folderPinned`).
- Row context menu: **Track Source File** / **Stop Tracking**, shown for stored pages only. Turning
  it on records the path of the file it was imported from when that still exists, else opens the
  same panel Update from Source uses.
- `autoImportFromDownloads()` gets a second pass that runs even when there are no new paths: for
  each doc with a `trackedSource` that exists, compare MD5 of source against the stored copy; on a
  difference, call the existing `updateFromSource()`. That reuses the atomic write, the ledger
  insert, and `save()`, which triggers the mirror. The early `guard !newURLs.isEmpty` return has to
  move below this pass.
- If the page is open when its file changes, bump the reload token so the pane shows today's data.
  Nice to have; without it he hits Reload.
- **Opt-in is the point.** Podcast Shelf's notes say the shelf copy is the source of truth and
  Downloads is only where it came from. A blanket "same name means update" rule would let a stray
  re-download overwrite a tool he's been using. Tracking is per page and off by default.
- Bonus: the weekly regenerated reports could use the same switch later. Not in scope.
- The running app picks the change up through the existing FSEvents watcher (2 s debounce), and the
  nudge LaunchAgent covers the app being closed.

**First-day sequence:** generate once, let the Shelf import it, right-click → Track Source File,
file it under Career, pin to top of folder. From then on it's hands-off. No auto-file rule needed,
since the file only ever imports once.

## Generator: `pipeline/build_dashboard.py`

Read-only. Standard library only. Reads `outcomes.csv`, `watchlist_companies.json`,
`enrollment_candidates.json`, and lists `tailored/` and `tailored/apply_now/`. Never imports or
calls `mark_applied.py`, `mark_outcome.py`, `update_tracking.py`, or `repair_outcomes.py`.

```
.venv/bin/python pipeline/build_dashboard.py            # writes both outputs
.venv/bin/python pipeline/build_dashboard.py --out DIR  # write somewhere disposable (first run, tests)
.venv/bin/python pipeline/build_dashboard.py --today 2026-09-19   # pin the clock for tests
```

- Outputs: `~/Downloads/job_dashboard.html` (stable name, overwritten) and
  `pipeline/jobs/dashboard_YYYY-MM-DD.html` (gitignored history).
- Writes to a temp file in the target directory, then `os.replace`, so the Shelf watcher never
  reads half a file.
- **Exit 0 always** unless called with `--strict`. On any exception it prints one line
  (`dashboard: FAILED <reason>`) and leaves yesterday's file in place. The daily run reports that
  line and moves on; the digest stays the primary output.
- On success prints one line for the run log:
  `dashboard: 85 queue (12 expiring), 29 manual, 31 quiet -> ~/Downloads/job_dashboard.html`
- CSV parsed with `csv.reader`, columns by header name, never by index. Rows with a drifted column
  count are counted and reported on the page as a warning strip ("3 rows unreadable; run
  repair_outcomes.py"), since `mark_applied.py` silently skips the same rows and he'd want to know.
- All values HTML-escaped; the data block is `json.dumps` with `</` escaped so a stray tag in
  `notes` can't break the script element.
- First run goes to `--out` in a scratch directory and gets opened in a browser before it's ever
  pointed at Downloads.

### Embedded data shape

```
{ "generated": "2026-09-19T07:41", "today": "2026-09-19", "expiry_days": 45,
  "queue":  [{company, title, url, score, tier, coverage, unmet, cap_trigger, ic_scope,
              channel, surfaced, age_days, days_left, resume_pdf, cover_pdf, in_apply_now}],
  "quiet":  [{company, title, url, score, applied, days_since, furthest_stage, channel}],
  "manual": [{key, name, group, why, link, link_kind, last_checked, last_hit, hit_is_live}],
  "counts": {in_process, enrollment_manual_review_unsurfaced, unpollable_not_reported, bad_rows} }
```

### Rules per list

**Apply queue** (`stage == surfaced`)
- `age_days = today - surfaced_date`; `days_left = 45 - age_days`. Undated rows get no countdown and
  sort last with a "no date" chip. They are not hidden: `age_report.py` never retires them, so
  they'd otherwise sit forever unseen.
- `tier` from `fit_score` against `_scoring_config` thresholds read from the watchlist (110 / 88 /
  78), not hardcoded.
- `coverage` renders as a pass/fail chip at 80%, never a sortable number. `unmet` is the readiness
  column. That's the repo's standing rule about `jd_coverage_pct` and the page should respect it.
- `ic_scope` lowercased on read (two rows say `IC`).
- PDFs: don't parse `notes`. Build a slug from the company name (alphanumerics only, lowercased)
  and match it against filenames in `tailored/apply_now/` first, then `tailored/`. Pick the
  non-cover PDF and the `_cover.pdf`. Ambiguous or missing renders as "no PDF matched," never a
  guess. Paths render as click-to-copy text: the Shelf opens http links in the browser, and a
  `file://` link from a stored page isn't something I've confirmed works.

**Gone quiet** (`stage == applied`, outcome blank or `pending`)
- **Post-epoch only**: `surfaced_date`, else `applied_date`, on or after 2026-07-28. That's the
  standing decision in `CLAUDE.md`; pre-epoch applied rows are unfalsifiable and stay off the page.
  42 rows qualify today; 31 of them are 10+ days old.
- `days_since = today - applied_date`. Sorted oldest first. Shows `furthest_stage` when set, so a
  role that reached an interview and then went silent reads differently from a cold apply.
- The two off-vocabulary stage rows surface as an "In process" count on the quiet tile, not as
  list rows. Phase two's interview section is their real home.

**Manual checks** (29 entries)
- Source: `_blind_spot_companies.companies` (16) and `_unpollable_backlog_companies.companies` (13).
- `key` = lowercased alphanumeric company name. No id exists; names in these lists are stable.
- `link`: `careers_url` when present, else a Google search URL built from `query`
  (`link_kind: search`, rendered with a small "search" label so he knows it isn't the board).
- `hit_is_live`: true when `last_hit` starts with the same date as `last_checked` and doesn't
  contain "no " / "null". Crude on purpose; it only drives a highlight, and the full `last_hit`
  text is on the row either way.
- Stale thresholds: blind-spot ticks go stale after 7 days, backlog ticks after 30, matching how
  often the pipeline itself looks at each list.
- **Enrollment-queue items stay off the tick list in v1.** 41 unsurfaced manual-review entries and
  153 unreported unpollables already drain through the digest and the weekly punch list at a capped
  rate; putting them on the page creates a second queue for the same items. The page shows them as
  two counts in the footer so the size of that backlog is visible.

### One config change: `careers_url`

Add an optional `careers_url` string to the 29 entries. It's additive; the entries already carry
one ad-hoc field (`query_needs_repair`), and both watchlist writers round-trip unknown keys. The
file is stored RAW (`ensure_ascii=False`, single trailing newline), so the backfill goes through a
`pipeline/_backfill_careers_url.py` temp script that matches that, then `validate_config.py`.
Thirteen URLs fall out of the existing `site:` queries; the other sixteen need a lookup, which is
a good Sonnet handoff with me checking the list before it's written. Copy the watchlist aside
first.

The alternative is a separate `dashboard_links.json`. I'd rather not: a second file keyed by
company name is exactly the drift the handoff argues against.

## Page spec

Plain HTML, inline CSS and JS, no CDN, data in one `<script type="application/json">` block.
`<title>Job Search Dashboard</title>` (stable, since the Shelf took its title on first import).
Light and dark via CSS variables and `prefers-color-scheme`. Has a viewport meta so the phone
doesn't need the Shelf's injected one. Steward patterns reused: status-colored tiles that filter,
relative wording over the absolute date, dense rows, mono numerals, storage in try/catch.

**Header:** "Generated Sat Sep 19, 7:41 AM." If `today` in the page is more than 36 hours past
`generated`, a strip says the data is stale and the run may have failed. This matters more than it
looks: a failed build leaves yesterday's file, and without the strip it's indistinguishable from a
quiet day.

**Tiles** (each filters or scrolls to its list)
1. Ready to apply: surfaced, 14 days old or less
2. Expiring: 7 days or fewer left
3. Manual checks due: unticked or stale
4. Quiet 10+ days
5. (phase two) Interviews

**Apply queue.** Default filter **Fresh** (14 days or less), sorted by score descending. Filter
chips: Fresh, Expiring, All, Full tier only. The handoff said sort by days left; with 85 rows and
`age_report.py`'s own finding that an old surfaced row is usually a dead posting, that sort leads
with the least useful rows. Days-left is a column and a chip, not the default order.
Columns: company, title (linked to the posting), score + tier, unmet hard reqs (with the cap
trigger as a tooltip when it isn't `none`), coverage chip, IC/manages, channel, "surfaced 5 days
ago" over the date, days left, PDF paths. On a phone the row collapses to company, title, score,
days left, with the rest behind a tap.

**Manual checks.** Two groups (Blind spot, Backlog), unticked and stale first, then by oldest
tick. Row: tick, company (linked), why it's manual, last pipeline hit (highlighted when live),
"you checked 3 days ago." A pipeline hit newer than his tick un-dims the row: the pipeline saw
something after he last looked.

**Gone quiet.** Company, title, applied date, days since, furthest stage, channel.

**Footer.** Counts of what isn't on the page and why: pre-epoch applied rows, enrollment backlog,
unreadable rows.

### Tick storage

One `localStorage` key, `jobdash.ticks.v1`, holding `{ "<key>": "2026-09-19" }`. The Shelf's shim
persists it per page. All access in try/catch; if storage throws, ticks work for the session and a
note says they won't persist. Re-ticking updates the date; clearing removes the key. Keys for
companies that left the list are pruned on load. The pipeline never reads this, by design.

Copy on the page follows the repo voice rules: no em-dash clutter, no "genuinely," plain labels.

## Daily prompt wiring

New **Step 6.6**, directly after Step 6 and before 6.5, so tracking is final and a failure in the
weekly rollup can't skip it. Per the handoff, the actual diff gets shown for approval before the
edit. Draft text:

> ## Step 6.6: Rebuild the job dashboard (added 2026-09-XX)
> Run `.venv/bin/python pipeline/build_dashboard.py`. One command, no arguments, nothing chained.
> It is read-only against the tracking files and always exits 0. Copy its single output line into
> the run summary. If that line starts with `dashboard: FAILED`, note it in SESSION_STATE and
> continue; do not retry, do not debug it inside the run, and do not mention it in the digest.
> Never hand-edit the HTML, and never write a replacement dashboard inline.

Nothing goes in the scheduled task's `SKILL.md`. The Step 5 digest is unchanged in v1; a one-line
"Dashboard updated on the Shelf" footer can come later if he wants the reminder.

**Verification** after the first scheduled run: `~/Downloads/job_dashboard.html` mtime matches the
run, then the Shelf page shows the new "Generated" stamp, then a tick made the day before is still
there. Mtime first, per the scheduled-task rules; the run's own report doesn't count.

## Tests

`pipeline/test_build_dashboard.py`, plain asserts like the repo's other tests, fixtures built
in-memory with fake company names, `--today` pinned:
- days-left math at 0, 44, 45, 46 days, and an undated row
- blank and `pending` outcomes both land in quiet; a pre-epoch row doesn't
- an unknown stage value doesn't crash and is counted
- a row with 15 columns is counted as unreadable, not dropped silently
- `notes` containing `</script>` and quotes produces valid embedded JSON
- watchlist entry with and without `careers_url`
- a missing input file yields exit 0 and the FAILED line

## Build order

1. Shelf: `trackedSource` + the second pass + menu item; build, install, verify against a scratch
   HTML file regenerated twice with a tick in between. (HTMLShelf repo; check no other session is
   in it first.)
2. `build_dashboard.py` + tests, first output to a scratch dir, reviewed in a browser and at phone
   width.
3. `careers_url` backfill: list reviewed by him, then written.
4. Point it at Downloads, import, Track Source, file under Career.
5. Show the Step 6.6 diff, get a yes, make the edit.
6. Verify by mtime after the next scheduled run; update both repos' `CLAUDE.md`.

Steps 1 and 2 don't depend on each other. If the Shelf change slips, step 2 still ships and he
uses Update from Source by hand for a few days.

## Phase two (interviews), unchanged from the handoff with one note

Built 2026-10-15 in a different shape; see the last section of this file.

`interview-scan` only runs Monday and Thursday and writes nothing structured today. The plan
stands: have `interview-loop`'s scan write `pipeline/interviews.json` as a cache (company, role,
round, datetime, has_prep, has_postmortem), gitignored, and the generator reads it if present. The
note: the dashboard rebuilds daily but that cache would refresh twice a week, so the section needs
its own "as of" stamp. The generator can compute `has_prep` and `has_postmortem` itself from
`interview_prep/` on every build, which keeps the twice-weekly part down to dates only.

## Decisions (locked 2026-09-19, all four as recommended)

1. Shelf route A: opt-in source tracking.
2. Default queue view is Fresh by score; days-left is a column and the Expiring chip.
3. `careers_url` goes in the watchlist entries, search link as the fallback.
4. Enrollment backlog shows as footer counts only.

## Build status (2026-09-19)

- **Done:** `build_dashboard.py` and `test_build_dashboard.py` (9 tests pass). First output went to
  a scratch directory and was checked in a browser at desktop and phone width: no console errors,
  no horizontal scroll, ticks persist and move the tile count.
- **Update, same evening:** everything below marked waiting is now done. Shelf build installed and
  verified with a throwaway tracked page (rewritten while the app ran: stored copy refreshed in
  ~5 s, same id, `dateAdded` unchanged, seeded tick kept, iCloud mirror updated). The dashboard is
  on the shelf under Career, folder-pinned, tracking `~/Downloads/job_dashboard.html`. All 29
  `careers_url` values written (20 high confidence, 7 medium, 2 low; watchlist backup in
  `pipeline/jobs/`), `validate_config.py` clean. Step 6.6 is in `daily_task_prompt.md`. The stale
  strip is schedule-aware now (weekday runs, ready by 8 AM) instead of a flat 36 hours, which
  would have fired every weekend. Left: commit before Monday's 3 AM run, then check the mtime.
- **Done, not installed (superseded by the line above):** the Shelf change (`trackedSource`, `refreshTrackedSources()`, the menu
  item, per-page reload). `swift build` passes. `./build.sh` replaces the installed app, so it
  waits for a yes. Notes are in `~/HTMLShelf/CLAUDE.md`.
- **Waiting on review:** the `careers_url` list, then the backfill script.
- **Waiting on review:** the Step 6.6 edit to `daily_task_prompt.md`.
- **Not started:** first real write to `~/Downloads`, Track Source on the imported page, mtime
  check after the next scheduled run.
- Two deviations from the text above, both small: PDF tags read "resume PDF" / "cover PDF" with the
  path on hover and click-to-copy (full filenames clipped on a phone), and PDF matching
  uses `notes` only as a tiebreak when one company has several PDFs. 70 of 86 queue rows resolve to
  one resume; 13 say "N PDFs match this company" (several roles there and the row's notes name no
  file) and 3 match nothing. Those say so on the page rather than guessing.

## 2026-10-12: marks inbox, the last run on top, and the digest's long tail

His go-ahead, after a review of the whole handoff. What it found, in numbers from that day: the
apply queue held 98 rows because nothing but the 45-day retirement ever removed one; the weekly
send rate had gone from about half to 15%; `his_verdict` was blank on 197 of 230 post-epoch rows;
the page's tick storage held one tick, from the day after it was built; and the digest ran about
80 role lines to deliver 5 picks. On 2026-10-02 he had asked whether he could add notes on the
dashboard itself.

**What changed.**
- Every queue row carries Sent, Skip (not a fit, no time, materials, other), and Later. One click
  each, with undo until the next run.
- "New from the last run" sits above the queue: that run's picks, each with the run's read on
  it, what its cover letter promises, phrasing to confirm, and the tailoring diff behind a
  disclosure.
- "More from the last run" holds what the digest used to carry after the picks, collapsed.
- A package with a paste sheet (`field_sheet.py`) shows its form fields with click-to-copy
  values. Sections that sheet marks personal are never embedded.
- The `_ATS` PDF is recognized as a variant of its package and gets its own chip. A row whose
  notes name its PDFs is matched by that filename before the company-slug guess.

**This revisits decision "no write-back from the page" (2026-09-19), and keeps what it was
protecting.** The objection was a second source of truth beside `outcomes.csv`. There still
isn't one. The page's marks are an inbox in the Shelf's storage (`jobdash.inbox.v1`);
`pipeline/shelf_inbox.py` drains it at the start of the next run (Step 0 item 4b) through
`mark_applied.py` and `mark_verdict.py`, the scripts that already own those columns. The
generator still writes nothing but the page and still imports nothing from the writers. A
recorded row leaves the queue on the next build, and the page drops a mark once its row is gone
and the page is newer than the mark.

Considered and not taken: replying to the digest with "sent 1, 3; skip 2" (no new UI, but free
text to parse and nothing to click); a published Claude page with its own database (works from
the phone, but moves the queue onto claude.ai and puts a connector in the path of an unattended
run); leaving the page read-only and pointing him at `mark_verdict.py`, which had been there
since 2026-09-30 and was used once.

**Contracts to keep in step.**
- The storage key and the mark shape `{a, r, e, d, ts, u, c, t}` are shared by the page script
  and `shelf_inbox.py`. `test_mark_key_and_inbox_contract_with_shelf_inbox` pins the key and the
  skip reasons.
- `norm_url` is the same three-line function in `build_dashboard.py`, `shelf_inbox.py`,
  `mark_verdict.py`, and `mark_applied.py`. A mark is stored under it and matched by it.
- A row with a skip verdict stays `stage=surfaced` and is hidden here, evicted by
  `rotate_apply_folder.py`, and never listed as unsent by the run.
- `brief_[date].json` is model output. `read_brief()` type-checks and caps every field and
  falls back to the previous day's brief rather than blanking the page.

**Known limits.** Marks made on the phone stay on the phone: the iOS app is read-only and never
writes back. A Sent mark is his word; the row's notes say so until a confirmation email agrees.
Undo works until the next run has recorded the mark; after that a wrong mark is fixed with
`mark_outcome.py` or by hand, the same as any other tracker mistake.

## 2026-10-15: the weekly report moved onto the page

The Thursday "Weekly Channel Report" email is gone; its content is the "This week's leads"
section, between "Cleared, not tailored" and "More from the last run". Story and choices:
[D41](../DECISIONS.md#d41-the-weekly-report-became-a-page).

- **Source:** the newest `jobs/weekly_leads_<date>.json` from the last 13 days, written by
  `weekly_channel_report.py --page` at Step 6.5 (now ahead of the 6.6 build). Leads with any
  entry in `jobs/lead_marks.json` are left off; the generator reads that file and never writes it.
- **Rows:** three groups (unreachable, never picked, no board), one row per LinkedIn job id,
  the first 20 unreachable shown with a "Show N more". Each row: company, title linked to the
  posting, what the company does (added the same day, below), tier, location, how many alerts
  it was in, why it's there, first seen.
- **What the company does:** a line or two from the company's About section on LinkedIn, then
  its industry and headcount, under the company and title. `company_about.py` (Step 6.5 item 5,
  every run) fetches them into `jobs/company_about.json`, and the generator joins that file on
  the normalized company name at build time, reading it and never writing it. A company it
  hasn't reached yet shows no line; nothing else on the row changes.
- **Marks:** Tailor it / Pass, with undo, under `jobdash.leads.v1` as
  `{a, d, ts, u, c, t, l, tier, loc}` keyed by job id. Pruned the same way as queue marks: once
  the lead is gone from the data and the page is newer than the mark.
- **Above and below the list:** a warn strip per flag; a collapsed "Channel health" panel with
  the channel lines, the LinkedIn funnel, and `pipeline_quality.py`'s report as preformatted text.
- **Tile:** "weekly leads to answer", the unmarked count, links to the section.

## 2026-10-15: Progress, the phase two section ([D42](../DECISIONS.md#d42-the-dashboard-got-a-progress-section))

He expects to ramp to 6-7 applications a day and asked to see it, then interviews and the funnel
after them. The section sits at the top of the page, under the tiles.

- **Data:** `read_progress()` in the generator, embedded as `progress`. A send is a row in one of
  `SENT_STAGES` (the stages `mark_applied.py` and `shelf_inbox.py` treat as sent), dated by
  `applied_date`; a `closed` row counts only with a sent verdict or a confirmation file in
  `jobs/` that names it. Sends count from the epoch. A row with no `applied_date` falls back to
  `surfaced_date` and the page says how many did. A failure here sets `progress.error` and the
  rest of the page still builds.
- **Rounds:** `jobs/interviews.json` (gitignored), written only by `log_interview.py`, which the
  interview-loop skill runs at its Step 5 when a round has happened. Kinds: screen, interview,
  onsite, assessment. Each round attaches to its send by posting URL, else to the company's
  latest send on or before the round. The old plan above (a twice-weekly cache with prep and
  post-mortem flags) was dropped: the log records what happened, and nothing needs an "as of".
- **Tiles:** sent today against the target, the last 7 days with a per-day average, and rounds
  in the last 30 days with the latest one named.
- **Applications sent per day:** columns since the epoch, the last 30 or 90 days. Today's Sent
  clicks that no run has recorded yet are counted from the page's own marks and drawn as a
  lighter segment, so the number is live. A 7-day trailing average line and a shaded 6-7 target
  band share the one axis.
- **Interview rounds per week:** stacked columns, first conversation and later rounds, over the
  same range. Assessments are left off the columns and named in the tooltip.
- **What came of each send:** sent, reached a screen, reached a later round, offer, as bars with
  counts and shares; a line saying where every send stands (waiting, no reply after 30 days,
  rejected without an interview, closed, at an assessment, interviewed); a table by send week.
- **Charts:** inline SVG, no library. Hover or arrow keys move a tooltip; every chart has a table
  underneath with the same numbers. Colors are the dataviz reference blue and orange, checked
  with its validator against the card color in both modes.

## 2026-11-07: who he knows at each company

He holds every referral ping until a role worth applying to turns up, then pings before he
applies so the referral attaches. Nothing paired a surfaced role with a person, so a row now
says when he has a first-degree LinkedIn connection at its company.

- **Source:** the warm-path kit, outside this repo (`WARM_PATH_KIT`): its `export/Connections.csv`,
  its `scripts/wpm_names.py` matcher (loaded by path, so nothing in the kit can shadow a pipeline
  module), and `data/reviewed_matches.json`. Read fresh at each build and never copied anywhere
  but the page. Only the first name, last name, company, title, and connected-on columns are
  read; email and profile URL are not.
- **Matching:** exact under the kit's `exact_keys()` (case, punctuation, legal form, and a name
  the string itself declares, like "X, formerly Y"), plus the pairs he confirmed, in the
  direction he confirmed them ([company as LinkedIn writes it, company on his lists]). A
  look-alike never counts; the kit's check list is the only place those go.
- **Rows:** the apply queue (and the last run's picks), cleared-not-tailored, weekly leads, and
  manual checks. Not applications gone quiet: they're sent, and a ping rides on a role before
  it goes out. The line reads "You know: name, title · connected Mon YYYY", newest connection
  first, three shown and the rest in a "+N more" tooltip. "at <company>" when the person's
  company is written differently (a declared name or a confirmed pair). A "same company?" tag
  when the match is exact on a short or ordinary-word name (the kit's `common_name_risk`).
  The line's tooltip dates the export file, since titles are as of then.
- **When it can't read the kit:** no lines, one footer item saying why, and the run's summary
  line says "no contacts (...)". Any other fault in the lookup does the same; the page builds.
- **Never:** a name in a tracked file or a test fixture (fixtures are made up;
  `test_no_real_connection_name_is_in_a_tracked_file` checks every tracked file against the real
  export when it's on the machine), a drafted or sent message, or a LinkedIn page opened.

## 2026-11-12: the letter view

His ask: "a quick view at a cover letter and see if I want to make swift edits." Until now a
queue row carried a chip that copied the cover PDF's path and never showed the letter, and
changing one sentence meant the same edit in two files and a re-render. Tried on copies of the
real files before it touched one. The nightly run needs no new command: `shelf_inbox.py
--apply` at Step 0 item 4b now applies saved edits too.

**On the page** (`build_dashboard.py`). A queue row whose tracker row has no `his_verdict` and
whose package has a letter gets a second, full-width line:

- **Why this job, from the letter:** the one sentence where he says which job he wants and why,
  when the finder is sure of it. The run's "The letter promises" line stays as it was.
- **Letter**, a disclosure. Inside: the lines the `.md` has above the body (date, recipient),
  the paragraphs, and the sign-off. Up to three sentences are marked, with a legend: why this
  job, the tie-back, the promise. A sentence the finder isn't sure of gets no mark.
- **Copy letter** puts the `.md` paste format on the clipboard, with his edit when one is saved.
- **Edit** turns the paragraphs into one text box, a blank line between each. Save edit stores
  `{text, base_sha, saved_at}` under `jobdash.letters.v1`, keyed by the row's key like a mark;
  `base_sha` is the hash of the body the generator embedded. Discard edit removes it. The page
  refuses to save fewer than two paragraphs, an empty one, or anything outside 150 to 600 words.
- **States on the row:** "edit saved" with what happens next (and that the PDF has the earlier
  text until then); "Edited by you, <date>" once an edit is applied and the files still hold
  it; "edit not applied" with the reason and that his text is still saved. The last also shows
  with no run involved when the letter was rewritten under a saved edit. On load the page drops
  a saved edit whose text is the letter now embedded, and one whose row has left the queue.
- A row marked Sent on the page, a row that can't take marks, and a row whose notes don't
  name its package show the letter and Copy, and no Edit. A letter whose `.md` and JSON
  disagree isn't shown; the row says why.

**The finder** (`find_letter_sentences`). Each rule finds exactly one sentence or nothing.

- *Why:* the only sentence in the letter that says "I'm applying", "why I want the ... role",
  or "drew me to the ... role", and it's in the first or second paragraph.
- *Tie-back:* the last sentence of the paragraph before the last, in a letter of three or more
  paragraphs, when it ends in a full stop and isn't the why sentence. Positional, as he
  defined it; in a letter that ends on a question it marks the end of the gap paragraph.
- *Promise:* the only sentence in the last paragraph with a time he can be held to (a month or
  weekday, this or next week or month, "before we talk", "my first ...", "before I" and a
  present-tense verb), a verb that commits ("I'll", "I'd", "I'm ...ing", "we'd", "would
  have"), and no sign of being a closing question ("depending on the answer", "I'd rather").

Measured on the 319 letters in `tailored/` whose two files agree (of 374 `.md` files; 32 have
no JSON and 23 disagree): tie-back 319, why 57, promise 35. On the 60 dated 2026-10-13 or
later, the ones the current rules produce: tie-back 60, why 47, promise 35, all three 31.
Every promise it found in those 60 was read and is one. Letters from before the closing
question came out (2026-10-22) end on a question and have no promise to find.

**Applying an edit** (`letter_edits.py`, new). `shelf_inbox.py --apply` calls it from the
nightly inbox step and prints a `letters:` clause on its line; `letter_edits.py --apply` is the
same thing on demand, and both are report-only without `--apply`. For each saved edit:

- **Refused unless** exactly one tracker row has the URL, its stage is exactly `surfaced`
  (any other stage is refused; the ones in `stages.ASSUME_SENT_FOR_SAFETY` with the reason
  that the letter may have gone out), `his_verdict` is empty, no Sent mark for the row is
  waiting in the page's inbox, the row's notes name one package, no other row naming that
  package has left `surfaced` or carries a verdict, its `_cover.md` and `_cover_data.json`
  both exist and agree, and the hash of the body on disk equals `base_sha`. His text must
  also be a letter: two or more paragraphs, none empty, 150 to 600 words.
- **Already applied** when the body on disk equals his text: nothing is touched.
- **Keeps the old version** in `tailored/_letter_versions/<stem>/<timestamp>/` (the `.md`, the
  JSON, and each copy of the cover PDF) before anything changes. A row that reads unsent may
  still have gone out.
- **Writes both files from one function** (`compose`): his paragraphs between the head and
  tail the `.md` already had, the JSON's other keys untouched. A paragraph he left alone keeps
  each file's own spelling (bold, entities). Before any write the result is read back in
  memory with the page's own reader and must give exactly his paragraphs.
- **Renders** with `render_pdf.py cover` into a staging folder, and only then moves the three
  files into place, so a failed render leaves the package as it was. The PDF replaces the copy
  that exists (`apply_now/`, or `tailored/` after rotation, both when both exist).
- **Runs `check_voice.py`** on the result and records its line. Information only.
- **Logs** each edit to `jobs/letter_edits.jsonl` (a refused edit's text is in its line) and
  writes `jobs/letter_edit_results.json`, which the next build reads for the row states. An
  edit whose result hasn't changed since the last run is not logged again.
- Says so when the first sentence or the promise sentence changed, and changes nothing because
  of it: not `_cover_openers.md`, not the brief file, not the tracker, not the Shelf's files.

**Contracts to keep in step.**
- The storage key and the edit shape are shared by the page script (`EKEY`) and
  `letter_edits.py` (`LETTERS_KEY`); `test_contracts_with_the_page_and_the_generator` pins both.
- What a letter's body is, its hash, and how his text splits into paragraphs live in
  `build_dashboard.py` (`parse_letter`, `letter_sha`, `edit_paragraphs`) and `letter_edits.py`
  imports them. The page's `lparas()` mirrors `edit_paragraphs()`, and a test runs both.
- The generator still writes nothing but the page and imports nothing from a writer.
  `letter_edits.py` imports the generator, not the other way round.
- `LETTER_LIMITS` is the one home of the paragraph and word limits, for the page and the applier.

**Known limits.** An edit saved on the phone stays on the phone, like a mark. Copy letter
uses his saved edit, so he can paste an edit into a form before any run has applied it; the
PDF still has the earlier text until then, and the row says so. If he then marks the row Sent,
the edit is refused and the files keep the earlier text, with his text in the log. Bold in a
paragraph he edits is not carried into the new text. An edited letter's files get a new
modified time, so listings sorted by time treat it as recent.
