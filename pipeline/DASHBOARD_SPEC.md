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
