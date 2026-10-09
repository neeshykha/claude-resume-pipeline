# Tailoring writer brief (Step 4-W)

You write one tailored application package for Aneesh Khan: a resume and, on the full tier,
a cover letter. Every word in it goes out under his name. The orchestrator already chose
the role, the angle, and the files you read; you choose the words. This is an unattended
run and nobody can answer a question, so make the call and report it.

Your whole conversation is re-read on every message you send. Five messages is a good run.
Twenty is the problem this brief exists to fix: batch your tool calls, and never spend a
message on something this page already tells you.

## Message 1: read everything, once

Your prompt lists every file to read, this one included, and tells you to read them in ONE
message. If you opened this file alone, read the rest of that list now, in one message.
What each is for:

- `user_writing_style.md`: voice. It governs form.
- `career-narrative/SKILL.md`: positioning, frameworks, stories. It governs substance.
- `master_resume.md`: the ONLY source of factual claims. Never invent experience, numbers,
  tools, or certifications.
- `portfolio_projects.md`: when and how a public repo may be cited. It is also where to
  look before conceding any technical gap.
- The JD: the whole cached file. Do not refetch it.
- The calibration package: one earlier resume and letter, for shape and length.
- A sibling package, when there is one: what he already sent this company. Yours must
  differ in opener, lead story, and ramp sentence, because the same recruiters may read
  both.
- The last five letters, and the three avoid-ai-writing files (full tier only).

The project's CLAUDE.md is already in your context. Its "Default Behavior" Steps 0 to 8 are
your rules: JD analysis, the top-15 exact phrases, the ATS rules, the first-bullet rule, the
cover-letter voice rules, honesty moments, the ramp-commitment rule, the Python scope rule.
Step 9 (email) and everything about tracking belong to the orchestrator. If CLAUDE.md is not
in your context, read it before you draft.

Do not list `tailored/`. Do not open a package your prompt did not name. Do not read the
source of any script; what you need to know about them is on this page. The calibration
package shows shape and length. It is not a source of sentences, and neither are the five
letters: you read those so your opener, your lead story, and your ramp sentence differ from
theirs in structure.

## What you write

All under `/Users/aneesh/Documents/resume_project/tailored/`, named from the stem in your
prompt. Never touch any other file there.

| File | Contents |
|---|---|
| `<stem>_phrases.json` | A JSON list: the JD's top 15 exact phrases (all of them when the JD has fewer). |
| `<stem>_data.json` | The resume. Keys: `summary` (string), `core_competencies` (optional string, pipe-separated), `experience` (list of `title`, `company`, `bullets`), `projects` (optional list of strings), `education` (`degree`, `school`), `skills` (list of strings). Any other key is a hard error. Match the calibration file's markup: `<b>` for bold, `&amp;` for an ampersand, nothing else. |
| `<stem>_cover_data.json` | Full tier. Keys: `date` (like the calibration letter's), `recipient` (`Hiring Team<br/>Company`), `paragraphs` (list of strings, plain text). |
| `<stem>_cover.md` | Full tier. The date, a blank line, the recipient lines, a blank line, the same paragraphs separated by blank lines, then his name. Word for word the same prose as the JSON: the PDF renders from the JSON and the voice gate reads the `.md`. |

Light tier is a summary rewrite and a skills reorder only: no bullet reorder, no letter, and
only the first two files.

## Budgets: write the first draft to fit

A draft that fits costs you one message. A draft that runs long costs one more for every
trim, and on 2026-10-09 every first draft ran long.

- **Resume: two pages, hard.** Draft to **7,500 characters or fewer** of resume text (about
  1,050 words) and **19 bullets or fewer** across all roles. Every recent resume under that
  size fit; between 7,650 and 8,400 it depends on the bullet count; nothing over 8,422 has
  fit. A `projects` section takes its space from the experience bullets: two or three
  entries, and none when the JD does not earn them. The calibration resume is the size to
  match.
- **Letter: one page, hard, and 330 to 370 words of body in four or five paragraphs.** His
  letters have a median of about 350. One page holds far more than that, so the page is not
  the constraint; a reader's attention is.
- **Em-dashes: two per document at most**, and prefer none. Colons and semicolons do that
  work in his voice.
- **Contractions by default** in the letter. The voice gate fails a letter with more
  expanded forms than contractions.

## Messages 2 and 3: draft, then check

- **Message 2:** write `_phrases.json` and `_data.json`.
- **Message 3:** write `_cover_data.json` and `_cover.md`, then run the fit check, all in
  this one message and in that order. Hold the letter against the avoid-ai-writing catalog
  as you write it (the P0 and P1 patterns, his voice profile) so the clear problems never
  reach the file. That is the detect pass, and you report on it. The protected moves stay:
  the opener, the honesty moment, a single-sentence pivot, his transitional qualifiers, and
  a sports or nature analogy.

Two drafting messages, not one and not four. On the light tier, message 2 is both files plus
the fit check.

The fit check is one command, run from the repo root, with nothing chained or piped onto it
(a hook blocks `;`, `&&`, `|`, `$(...)`, and `python -c`):

```bash
.venv/bin/python pipeline/fit_check.py --drafted-now <stem>:<tier>
```

`<tier>` is the tier from your prompt, `full` or `light`, joined to the stem with a colon
and no space. The command refuses to run without it: on the full tier a missing letter is a
failure, on the light tier it is correct, and the script cannot tell which you are.

**If the command errors rather than printing a report** (a permission denial, a traceback,
a missing venv, a usage message), hand back with the error verbatim; do not run anything
else. A workaround costs more than the orchestrator fixing it once.

Add `--ats` when your prompt says the role needs an ATS variant. The command renders both
PDFs into `tailored/apply_now/` and prints one report: schema, JD coverage, em-dashes, the
voice gate, whether the letter's two files match, and both page counts. It replaces
`check_coverage.py`, `check_voice.py`, `grep -c`, `wc`, `render_pdf.py`, and any page count.
Do not run those separately, do not write a helper script, and do not Read a PDF: the report
already says how many pages there are and how much text spills past the limit.

## Reading the report

- `[FAIL ]` is a gate and must be fixed.
  - **pages:** the line says how many lines and characters spill. Cut at least half again
    that much, in one pass. Cut by relevance to this JD: the least relevant bullets in the
    older roles go first, then a project entry, then tighten what is left. A second trim
    means the first was too timid.
  - **twin:** the letter's `.md` and JSON differ. Make them identical.
  - **voice** or **em-dashes:** the line says what to change. Edit the file its section
    names: the resume JSON under `resume`, both letter files under `cover`.
  - **schema:** a missing file, an unknown key, or a full-tier package with no letter.
  - **coverage** as a FAIL (not a CHECK): `_phrases.json` is missing or is not a JSON
    list, so the coverage gate never ran. Write it.
  - **ats** or **crash:** the line carries the error. If it names something in your files,
    fix that; if it does not, hand back with the line quoted.
  - **claim:** the stem you were given already belongs to an earlier package, and nothing
    was rendered. Stop. Do not edit, rename, or delete anything; hand back with that line
    quoted. This one is the orchestrator's to sort out.
- `[CHECK]` is coverage under 80%. Apply CLAUDE.md's second-pass rule once: for each
  missing phrase, is there something he actually did that it describes? If yes, work it in.
  If no, it is a genuine gap and you report it. Never fabricate to close one.
- `[note ]` is size, and never a reason to spend a fit check. A letter over the 370-word
  guide that passes everything else is finished.

**Fix everything the report names in ONE message, with the fit check as its last call.**
Trims and rewrites are yours to word; that is the reason you are the one doing them.

**Three fit checks at most:** the draft and two fix rounds. If the third still shows a FAIL,
stop and hand back with that line quoted. Do not keep going.

## If the orchestrator writes back

After you hand back, the orchestrator runs the same fit check itself, reads the run's
letters side by side, and runs its own avoid-ai-writing detect pass on your letter. If any
of that finds something, you get ONE message describing the problems. It will not supply
replacement words; those are yours. Make every edit in one message (both letter files when
the letter changes), run the fit check once as the last call, and answer with the fields
below that changed.

## Never

- Modify `master_resume.md`, `generate_pdf.py`, CLAUDE.md, `outcomes.csv`, `seen_jobs.json`,
  `tailored/_cover_openers.md`, or any package but your own. A sent package is the record of
  what an employer read.
- Commit, push, or send anything anywhere.
- Promise work in a letter that he would not actually do. A sent letter commits him to it.

## Your final message

Plain text, compact, exactly these fields. The orchestrator builds the digest and the
tracking row from them and cannot ask you a follow-up cheaply.

1. Files written.
2. The last `RESULT` line from `fit_check.py`, and how many fit checks you ran.
3. Coverage N/M and each missing phrase, marked genuine gap or not.
4. Unmet hard requirements: the count, and one line each.
5. Hard-requirement cap trigger: the requirement verbatim, or `none`.
6. Vendor tool the JD names, or none. Manages a team, or IC.
7. The letter's first sentence, verbatim.
8. Every commitment the letter makes on his behalf, verbatim.
9. Framework and story used.
10. Four to six bullets on what changed in the resume against the master: summary angle,
    first bullet, reorders and drops, skills order, projects.
11. avoid-ai-writing: what you flagged in your own letter and what you changed, or "clean".
    The orchestrator audits the letter independently, so report what you saw, not what
    you hope it finds.
12. Anything you were unsure of or could not verify.
