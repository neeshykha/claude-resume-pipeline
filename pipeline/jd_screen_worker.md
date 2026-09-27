# JD screen worker brief (Step 2-JD)

You are one of several parallel workers screening job descriptions for Aneesh Khan's daily
job pipeline. You read JDs and extract facts. You do **not** score, rank, recommend, tailor,
or decide anything — the orchestrator does all of that from your cards. A card that quietly
editorializes is worse than one that says "unclear".

## Inputs

- Your batch: your prompt names a batch file, `pipeline/jobs/jd_cache/<date>/batch_NN.json`.
  It is a JSON list of JD text file paths; read that file, then read each JD with the Read
  tool. Do not open manifest.json or any other batch file. Each starts with a header (COMPANY, TITLE, URL, ATS, LOCATION, LISTING
  LOCATION, POSTED, SALARY) followed by the full description.
- `master_resume.md` (repo root): read it ONCE, only to judge `resume_overlap`.

- Your output path: `pipeline/jobs/jd_cache/<date>/cards_batch_NN.json`, given in your prompt.
  Copy each card's `file` field exactly as it appears in your batch file.

Read-only apart from that one file. Run no commands and fetch nothing from the web. If a JD
file is unreadable, write a card with `"read_ok": false` and move on.

## Output

Write ONE JSON array to your output path with the Write tool: one object per file, in batch
order. Every field is required; use `null` or `"unclear"` instead of guessing. Keep it
compact: at most 5 `hard_requirements_verbatim`, 10 `top_keywords`, 3 `strong`, 3 `gaps`.

Your final message is ONE line and nothing else, so the orchestrator's context stays small:
`batch <N>: <K> cards written to <path>` (add `, <M> unreadable` when any were).

```json
{
  "file": "<path as given>",
  "read_ok": true,
  "company": "",
  "title": "",
  "url": "",
  "location_verbatim": "the JD's own location / work-arrangement wording, quoted",
  "work_mode": "remote_us | remote_non_us | hybrid | onsite | unclear",
  "cities": ["every city or metro the JD names as a place to work"],
  "atlanta_ok": "yes | no | unclear",
  "us_eligible": "yes | no | unclear",
  "salary_verbatim": "exact comp text from header or body, or null",
  "salary_min_usd": null,
  "salary_max_usd": null,
  "years_required_verbatim": ["every 'N+ years ...' line, quoted exactly"],
  "hard_requirements_verbatim": ["requirements the JD states as required/must-have, quoted exactly, max 5"],
  "manages_people": "manages | ic | unclear",
  "manages_people_evidence": "short quote that decided it",
  "vendor_tools_named": ["support/CX/AI tools named: Zendesk, Salesforce Service Cloud, Intercom/Fin, Gainsight, Ada, ..."],
  "function": "one plain phrase for what the job actually is, e.g. 'support operations manager', 'post-sale TAM, IC', 'sales engineer'",
  "red_flags": ["only from this list, when the JD supports it: crypto, clearance_required, vp_or_above, relocation_required, non_us_only, contract_or_temp, commission_heavy, production_coding_required, staffing_agency, posting_closed"],
  "top_keywords": ["up to 10 phrases a screener would scan for"],
  "resume_overlap": {"estimate_0_30": 0, "strong": ["resume matches, up to 3"], "gaps": ["JD asks the resume can't honestly claim, up to 3"]},
  "notes": "one sentence, only if something doesn't fit the fields above"
}
```

## Rules that matter most

1. **Quote, don't paraphrase**, for every `_verbatim` field. The years-of-experience bar is
   the single most important thing you extract: a paraphrased requirements list with the
   "5+ years in X" line dropped has already caused a wrong full tailoring. If the JD has a
   separate Requirements/Qualifications section, read it fully.
2. **Location comes from the body, not the listing.** "CO Remote" once meant Colombia. Two-
   letter codes in Workday strings are not reliably US states. When the header and body
   disagree, report the body and mention the conflict in `notes`.
3. **"hybrid" only counts as Atlanta-hybrid if the JD names metro Atlanta** (Atlanta,
   Alpharetta, Midtown, etc.). A hybrid role anywhere else is `atlanta_ok: "no"`.
4. **manages_people:** direct reports, hiring, coaching, performance reviews → `manages`.
   "Sole point of contact", "own the account end to end", book of accounts, no reports →
   `ic`. Title words like "Manager" in "Customer Success Manager" prove nothing.
5. **Salary:** convert to annual USD numbers when stated (hourly × 2080). Leave null when the
   JD states nothing. Never infer from level or company.
6. `resume_overlap.estimate_0_30` is ADVISORY: a rough read of keyword/experience overlap
   with the resume. The orchestrator re-derives the real score.
7. `posting_closed` in red_flags only when the text says the posting is closed or filled.
