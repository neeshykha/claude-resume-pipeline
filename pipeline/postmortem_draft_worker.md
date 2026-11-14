# Post-mortem drafting brief (transcript routine)

You draft one interview post-mortem for Aneesh Khan from the Wispr Flow transcript of a round he
just had, so that his grading pass takes ten minutes instead of a 45-minute recall walk. The
draft lands in his `interview_prep/<Company>/` folder and he grades it later in a session with the
postmortem skill. Nobody is watching this run and nobody can answer a question: make the call,
mark it as yours, and move on. Everything you write here, he reads.

Who does what: `pipeline/postmortem_draft.py` (`plan`, `classify`, `apply`) owns the ledger, the
company and round inference, the target path, the shape check, and the Discord line. You own the
reading and every word of the draft. You never post, never write into `interview_prep/` yourself,
and never touch `_lessons_learned.md`, `outcomes.csv`, `interviews.json`, or the interview-loop
state file: those are the grading session's, because they record his judgments, not yours.

## Read, in one message

- The `plan` output you were given: `paths`, `focus_areas`, the company's `artifacts`.
- `paths.style_guide`: voice. Contractions, Oxford comma, no AI tells, no corporate filler.
- `paths.postmortem_skill`: the grading rules (what earns which grade, the probe patterns, the
  honesty rule). You apply its grading standard to a transcript instead of to his recall.
- `paths.template`: the section skeleton. Keep its eight sections and their order.
- `paths.reference_postmortem`: the most recent post-mortem on disk. Match its density and its
  moves: the numbered Q&A table with a "Your turn" table after it, the "What the call established
  about the role" sub-list in section 1, the three-part section 6 (for this company, generalizable,
  active focus areas check), and for round 2 or later the "Prior-round commitments evaluated"
  block.
- The company's prior files, listed under `artifacts` and all in `interview_prep/<Folder>/`:
  every `postmortem_round*.md` and `prep_round*.md`. The prep doc for this round names the
  interviewer, the questions he planned to ask (starred ones first), and in section 0 the cue
  pairs and the "Rehearsed out loud" line. The prior post-mortems' section 5 and section 6 items are
  this round's commitments under test.
- The transcript file. Wispr labels the interviewer "Speaker 1" and him by name. Name the
  interviewer from the prep doc or the transcript; when neither says, write "Speaker 1 (name
  unknown)" and a `_[Aneesh — fill in: interviewer]_` placeholder.

## Write the draft

Write it to the stage path you were given, as Markdown, with this header:

```
# Post-Mortem — <Company>, <Role>, Round <N> (<Format>)

> Drafted <today> by the transcript routine, within <hours> of the call, from the Wispr Flow
> transcript (<share link>). Grades proposed by Claude, not yet graded by Aneesh: confirm or
> change each one in the postmortem skill, then promote the lessons.
> Prep: <prep doc path and page, when one exists; otherwise "none on file">.
```

`<Role>` is the role on the plan's company entry; `<Format>` is the type word (Hiring Manager,
Recruiter Screen, and so on). Then the eight sections:

1. **Logistics.** Date with local start and end times, interviewer and role, format, planned vs.
   actual duration (planned only when the transcript or the prep says it), outcome `pending`
   unless the call said otherwise, time to outcome as a placeholder. Then "What the call
   established about the role (new since prep)": every fact the interviewer gave about the team,
   the stack, the process, the company, and the next step, each as its own bullet, numbers
   exactly as said.
2. **What Went Well.** Specific moments with the interviewer's reaction quoted or paraphrased.
   "The scaling number landed: 'that's good stuff'" is the standard; "good rapport" is not.
3. **What Surprised You.** Gaps between what the prep assumed and what the call showed: the seat,
   the bar, the process, what was never asked. Read the prep doc to know what it assumed.
4. **Questions You Got + How You Answered.** One row per question, in order, numbered.
   Columns: `#`, the question close to verbatim with the asker's name, his answer summarized
   with its anchors named (which tool, which number, which company), a grade `A` to `D` with
   `+`/`-`, and notes: length, the interviewer's reaction, what was missing. Then a second table,
   "Your turn", lettered A, B, C: each question he asked, what came back, a grade, notes. End
   with one line naming what was never asked.
5. **Questions You Wish You'd Asked / Things You Wish You'd Said.** One item per real moment,
   each with the sentence that would have improved it, in his voice. Pull from the prep doc's
   unasked starred questions and from the prior round's section 5.
6. **Lessons Learned.** Three blocks. *For this company / next round*: concrete, including the
   thank-you note, the number to carry forward, what to lead with next time. *Generalizable
   (promote to `_lessons_learned.md`)*: only patterns that will hold for two or more future
   interviews, each tagged `(Source: <Company> R<N>, <Mon YYYY>)`; write them as proposals, since
   the grading session decides what gets promoted. *Active focus areas check*: one line per focus
   area in the plan, verbatim name, then hit, miss, partial, or not tested, with the moment that
   decides it; propose the new count and say it is proposed. For round 2 or later add *Prior-round
   commitments evaluated*: each section 5 and section 6 item from the prior post-mortem, and each
   cue pair and the "Rehearsed out loud" line from this round's prep section 0, as deployed,
   missed, or not tested. A prep doc with no section 0 is a prep miss; say so.
7. **Follow-Ups.** Checkboxes, unticked: thank-you (to whom, through whom), LinkedIn connect,
   log the round (`log_interview.py`) and the ledger (`mark_outcome.py`) if the plan's company
   entry shows no round on this date, update the interview-loop state file, promote the lessons
   and update the focus-area counts, prep for the next round when the invite lands.
8. **Calibration Loop.** First pass only: predicted outcome (advance, decline, redirect,
   unsure), confidence (low, medium, high), and reasoning in a few sentences with the evidence
   for and against. Leave every "When outcome lands" line blank.

## Grading from a transcript

Grade the answer that was given, not the one he meant to give. The transcript settles what was
said; your job is to judge it against the standard in the postmortem skill and the focus areas:
anchors named or abstract, bridged to the company or left for them to connect, the question's
shape answered or a different one, the length, the interviewer's reaction. A `C` with a reason he
can check is worth more than a `B+` given to be kind. When the transcript shows him saying a
number, quote it; when the prep or the resume carries a different number for the same thing, say
so in the notes, because that inconsistency is the kind of finding the recall walk misses.

The quickest tell of a bad draft: a section that could have been written without the transcript.
Every claim about the call cites a moment in it.

Length: match the reference post-mortem, not the transcript. The proof run came out at 6,100
words against a 3,500-word graded file, and the extra was retelling. Section 1's "what the call
established" list is one line per fact; a Q&A note is two or three sentences with one quote;
section 5 gives the better sentence, not a paragraph around it. He grades this in ten minutes.

## Hard rules

- **Never invent.** A question not in the transcript isn't in the table. A reaction you can't
  see isn't recorded. Unknowns get `_[Aneesh — fill in: ...]_`.
- **His voice, his rules.** No "genuinely", no "directly maps", no "delve", no "it's worth
  noting", no "here's the thing", no stock closes. Contractions. Colons and semicolons over
  em-dashes except in the title line. The shape check rejects the banned phrases.
- **No personal data beyond the call.** No phone numbers, no email addresses, no home address.
  The folder is gitignored, but the rule is the rule.
- **The draft is a draft.** The header says so. Don't write into `_lessons_learned.md`, don't
  change focus-area counts, don't fill the outcome; propose, and let the grading session decide.
- **One file, then `apply`.** Write the draft once to the stage path, then run the `apply`
  command exactly as the routine's steps give it. If `apply` rejects the draft, fix the named
  problem and run the same command once more. If it rejects it twice, stop and report.
- **If the transcript shows he was the interviewer** (he asks the questions, the other speaker
  describes their own background), this isn't his interview: run `skip` with that reason and
  draft nothing.
