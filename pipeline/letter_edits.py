#!/usr/bin/env python3
"""Applies the cover-letter edits he saves on the Shelf dashboard to the letter's files.

Usage:
    .venv/bin/python pipeline/letter_edits.py              # report only, writes nothing
    .venv/bin/python pipeline/letter_edits.py --apply      # apply them
    .venv/bin/python pipeline/letter_edits.py --inbox FILE # read the page's storage from a JSON file (tests)
    .venv/bin/python pipeline/letter_edits.py --strict     # exit 1 on failure (tests only)

Added 2026-11-12. His ask: "a quick view at a cover letter and see if I want to make swift
edits." Until then the dashboard showed a chip that copied the cover PDF's path and never
the letter, and changing one sentence meant editing the .md, making the same change in the
JSON the PDF renders from, and re-rendering, so in practice a letter went out as drafted.

The page (build_dashboard.py) now shows each unsent letter, and Save edit there stores
`{text, base_sha, saved_at}` in the Shelf's storage for the page under `jobdash.letters.v1`,
keyed by posting URL the way a Sent or Skip mark is. That is an inbox, like the marks. This
script reads it, the way shelf_inbox.py reads the marks, and for each saved edit either
applies it or refuses it and says why. shelf_inbox.py calls drain() from the nightly run's
inbox step; the command above is the same thing on demand ("apply my letter edits").

WHEN AN EDIT IS APPLIED
All of these have to hold, and an edit that fails one changes no file:
- Exactly one tracker row carries the URL, its stage is exactly `surfaced`, and its
  his_verdict is empty. Any other stage is refused; the stages in stages.py's
  ASSUME_SENT_FOR_SAFETY get the reason that the letter may have gone out.
- No Sent mark for the row is waiting in the page's inbox. He may have pasted the letter
  into a form and clicked Sent a minute after saving the edit.
- The row's notes name one package, no other row that names the same package has left
  `surfaced` or carries a verdict, and its `_cover.md` and `_cover_data.json` both exist
  and hold the same paragraphs (build_dashboard.read_letter, the reader the page uses).
- The hash of the body on disk equals the edit's base_sha: the letter is still the one he
  edited. A letter rewritten since then is never overwritten by an edit made on the old one.
- His text is a letter: at least two paragraphs, none of them empty, 150 to 600 words
  (build_dashboard.LETTER_LIMITS, which the page checks too). A slip can't wipe a letter.
- Written out and read back in memory, the two files give exactly his paragraphs. Text the
  files can't carry as plain text (a "<" and ">" pair, "**") is refused instead of mangled.
When the body on disk already equals his text the edit is counted as already applied and
nothing is touched, which is what makes a second run, or a retry tomorrow, safe.

WHAT APPLYING DOES
1. Copies the current .md, JSON, and cover PDF into
   `tailored/_letter_versions/<stem>/<timestamp>/`. A row marked unsent may still have gone
   out (a missed confirmation, a Sent click he never made), so the earlier version is the
   record of what an employer may have read and is never destroyed.
2. Builds both text files from one structure in compose(): his paragraphs, between the
   lines the .md already had above them (date, recipient) and below (sign-off), and the
   JSON's other keys untouched. A paragraph he didn't change keeps each file's own spelling
   of it (bold, entities); a changed one is plain text in the .md and escaped for the
   renderer in the JSON.
3. Renders the PDF from the new JSON with `render_pdf.py cover`, into a staging folder.
   Only when that succeeds do the three files move into place, so a failed render leaves
   the package exactly as it was. The PDF replaces the copy that exists (apply_now/, or
   tailored/ once rotate_apply_folder.py has moved it back), both when both exist.
4. Runs check_voice.py on the result and records what it says. INFORMATION ONLY: these
   are his words, and nothing here blocks or changes them over style.
5. Appends a line to jobs/letter_edits.jsonl, applied or refused (a refused edit's text is
   in its line, so his words survive the page forgetting them), and writes the latest
   result per row to jobs/letter_edit_results.json, which the next dashboard build reads
   for "Edited by you" and for a refusal's reason.

It never writes to the Shelf's files, the tracker, or tailored/_cover_openers.md. When an
edit changes the letter's first sentence or its promise sentence it says so, and changes
nothing else because of it. An edit whose result is the same as the last run's is not
logged again, so a refused edit he hasn't discarded yet doesn't grow the log every night.

Like shelf_inbox.py, a failure here must never fail the daily run: it prints one
`letter_edits: FAILED ...` line and exits 0, and the edits stay on the page for next time.

This file is committed to a public repo. No company names, no letter text, no sample rows.
"""
import contextlib
import csv
import html
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime

import build_dashboard as bd  # the letter's shape, hash, and limits have one home; it writes nothing
import shelf_inbox            # finds and reads the page's storage, the same way the marks are read
from stages import ASSUME_SENT_FOR_SAFETY

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SCRIPT_DIR)
OUTCOMES = os.path.join(SCRIPT_DIR, "outcomes.csv")
JOBS_DIR = os.path.join(SCRIPT_DIR, "jobs")
TAILORED = os.path.join(REPO, "tailored")
LETTERS_KEY = "jobdash.letters.v1"   # must match EKEY in build_dashboard.py's page script
LOG_NAME = "letter_edits.jsonl"
RESULTS_NAME = bd.LETTER_RESULTS     # build_dashboard.py reads it under this name
VERSIONS_DIR = "_letter_versions"
LIMITS = bd.LETTER_LIMITS


def read_rows(outcomes):
    with open(outcomes, newline="", encoding="utf-8") as f:
        raw = list(csv.reader(f))
    header = raw[0]
    need = ("company", "title", "url", "stage", "his_verdict", "notes")
    missing = [n for n in need if n not in header]
    if missing:
        raise ValueError(f"outcomes.csv is missing columns {missing}; run repair_outcomes.py --apply")
    ci = {n: header.index(n) for n in need}
    by_url, by_stem = {}, {}
    for r in raw[1:]:
        if len(r) != len(header):
            continue  # drifted rows are skipped everywhere else too
        row = {n: r[i].strip() for n, i in ci.items()}
        by_url.setdefault(shelf_inbox.norm_url(row["url"]), []).append(row)
        for stem in bd.package_stems(row["notes"]):
            by_stem.setdefault(stem, []).append(row)
    return by_url, by_stem


def sent_waiting(marks):
    """Normalized URLs that carry a Sent mark not yet recorded in the tracker."""
    out = set()
    for key, m in marks.items():
        if m.get("a") == "sent":
            u = m.get("u") if isinstance(m.get("u"), str) else ""
            out.update((shelf_inbox.norm_url(u), shelf_inbox.norm_url(str(key))))
    out.discard("")
    return out


def compose(letter, paras):
    """(.md text, JSON text) for `letter` with `paras` as its body.

    The one place both files are produced, from one structure, so they cannot drift:
    everything but the body is carried over as read_letter() found it. A paragraph the edit
    left alone keeps each file's own spelling of it; a changed one is his plain text in the
    .md and the same text escaped for the renderer's markup in the JSON.
    """
    kept = {p: (m, j) for p, m, j in zip(letter["paras"], letter["raw_md"], letter["raw_json"])}
    md_paras, json_paras = [], []
    for p in paras:
        m, j = kept.get(p, (p, html.escape(p, quote=False)))
        md_paras.append(m)
        json_paras.append(j)
    md_text = "\n\n".join(x for x in (letter["head"], "\n\n".join(md_paras), letter["tail"]) if x) + "\n"
    data = dict(letter["data"])       # key order kept; only the paragraphs change
    data["paragraphs"] = json_paras
    return md_text, json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def plan_one(key, edit, by_url, by_stem, sent, tailored):
    """Decide what to do with one saved edit. Reads the tracker rows and the letter's files;
    writes nothing. status is "apply", "already", or "refused" (with a reason he can read)."""
    out = {"key": key, "label": key[:80], "status": "refused", "reason": "", "stem": "",
           "saved_at": edit.get("saved_at") if isinstance(edit.get("saved_at"), str) else "",
           "base_sha": edit.get("base_sha") if isinstance(edit.get("base_sha"), str) else "",
           "text_sha": "", "paras": []}

    def refuse(reason):
        out["reason"] = reason
        return out

    text = edit.get("text")
    if not isinstance(text, str) or len(text) > bd.LETTER_MAX_CHARS or not out["base_sha"]:
        return refuse("The saved edit is malformed: it has no text, or no hash of the letter it was made on.")
    paras = bd.edit_paragraphs(text)
    out["paras"], out["text_sha"] = paras, bd.letter_sha(paras)
    url = shelf_inbox.norm_url(key) if key.startswith("http") else ""
    rows = by_url.get(url, []) if url else []
    if not rows:
        return refuse("No tracker row has this posting link.")
    if len(rows) > 1:
        return refuse("Two tracker rows share this posting link, so the edit can't be matched to one.")
    row = rows[0]
    out["label"] = f"{row['company']}: {row['title']}"[:160]
    stem = out["stem"] = bd.package_stem(row["notes"])
    letter, why = bd.read_letter(tailored, stem) if stem else (None, "")
    if letter and letter["paras"] == paras:
        out["status"] = "already"   # his text is what's on disk; nothing to do, whatever the row says now
        return out

    stage = row["stage"]
    if stage != "surfaced":
        if stage in ASSUME_SENT_FOR_SAFETY:
            return refuse(f"The tracker row is {stage}, so this letter may have gone out, and its files are the record of what was sent.")
        return refuse(f"The tracker row is {stage or 'blank'}, not surfaced.")
    if row["his_verdict"]:
        return refuse(f"The tracker row carries your verdict {row['his_verdict']}, so its letter is closed.")
    if url in sent:
        return refuse("A Sent mark for this row is waiting on the page, so the letter may have gone out.")
    if not stem:
        return refuse("The tracker row's notes don't name one package, so the letter's files can't be found for sure.")
    # The same package under a second row (a repost, a duplicate) may have gone out from there.
    for other in by_stem.get(stem, []):
        if other is not row and (other["stage"] != "surfaced" or other["his_verdict"]):
            state = other["his_verdict"] or other["stage"] or "blank"
            return refuse(f"Another tracker row names this same package and is {state}, so this letter may have gone out from there.")
    if letter is None:
        gone = [s for s in ("_cover.md", "_cover_data.json") if not os.path.exists(os.path.join(tailored, stem + s))]
        if gone:
            return refuse(f"The package has no {' or '.join(gone)}, and a letter is both files.")
        return refuse(f"The letter on disk can't be used: {why}.")
    if letter["sha"] != out["base_sha"]:
        return refuse("The letter on disk isn't the one this edit was made on: it was rewritten after you saved it. "
                      "Discard the edit on the page and make it again on the letter shown there.")

    words = sum(len(p.split()) for p in paras)
    if len(paras) < LIMITS["min_paragraphs"]:
        return refuse(f"The edit is {len(paras)} paragraph{'' if len(paras) == 1 else 's'}; a letter has at least {LIMITS['min_paragraphs']}.")
    if any(not re.search(r"\w", p) for p in paras):
        return refuse("One paragraph of the edit has no words in it.")
    if not LIMITS["min_words"] <= words <= LIMITS["max_words"]:
        return refuse(f"The edit is {words} words; a letter is {LIMITS['min_words']} to {LIMITS['max_words']}.")

    md_text, json_text = compose(letter, paras)
    back, _ = bd.parse_letter(md_text, json.loads(json_text))
    if back is None or back["paras"] != paras or (back["head"], back["tail"]) != (letter["head"], letter["tail"]):
        return refuse("The edit has characters the letter's files can't carry as plain text (a < with a > after it, "
                      "**, or an &entity;). Reword that part and save it again.")
    out.update(status="apply", letter=letter, md_text=md_text, json_text=json_text, words=words)
    return out


def render_cover(json_path, pdf_path):
    """render_pdf.py the documented way, `render_pdf.py cover <json> <pdf>`, in its own
    process. Raises when it fails or leaves no PDF."""
    r = subprocess.run([sys.executable, os.path.join(SCRIPT_DIR, "render_pdf.py"), "cover", json_path, pdf_path],
                       capture_output=True, text=True, timeout=180)
    if r.returncode != 0 or not os.path.exists(pdf_path) or not os.path.getsize(pdf_path):
        tail = (r.stderr or r.stdout or "").strip().splitlines()
        raise RuntimeError((tail[-1] if tail else f"render_pdf.py exited {r.returncode}")[:240])


def voice_report(md_path):
    """(clean, what check_voice.py printed about the letter). Information only."""
    import check_voice
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        clean = check_voice.check(md_path, drafted_now=True)
    lines = [ln.strip() for ln in buf.getvalue().splitlines() if ln.strip()]
    return bool(clean), "  ".join(lines[1:])[:600]


def cover_pdfs(tailored, stem):
    """Every copy of the package's cover PDF, apply_now/ first. Both are replaced when both
    exist, because rotate_apply_folder.py keeps the tailored/ copy when it finds two."""
    name = stem + "_cover.pdf"
    return [p for p in (os.path.join(tailored, "apply_now", name), os.path.join(tailored, name))
            if os.path.exists(p)]


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _rmdir_if_empty(path):
    with contextlib.suppress(OSError):
        os.rmdir(path)


def first_sentence(paras):
    spans = bd.sentence_spans(paras[0]) if paras else []
    return paras[0][spans[0][0]:spans[0][1]] if spans else ""


def apply_one(p, tailored, now, render, voice):
    """Apply one planned edit. Returns a dict with status "applied" or "failed"; on "failed"
    the letter's three files are exactly as they were."""
    stem, letter, paras = p["stem"], p["letter"], p["paras"]
    md_path = os.path.join(tailored, stem + "_cover.md")
    json_path = os.path.join(tailored, stem + "_cover_data.json")
    pdfs = cover_pdfs(tailored, stem)
    targets = pdfs or [os.path.join(tailored, "apply_now", stem + "_cover.pdf")]

    # 1. Keep the old version, before anything changes.
    stamp = now.strftime("%Y%m%dT%H%M%S")
    parent = os.path.join(tailored, VERSIONS_DIR, stem)
    vdir, n = os.path.join(parent, stamp), 1
    while os.path.exists(vdir):
        n += 1
        vdir = os.path.join(parent, f"{stamp}-{n}")
    os.makedirs(vdir)
    staging = ""

    def nothing_moved():
        # Only called while the letter's own files are untouched: drop the copies just made.
        if staging:
            shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(vdir, ignore_errors=True)
        _rmdir_if_empty(parent)
        _rmdir_if_empty(os.path.dirname(parent))

    kept = []   # (the file in place, its copy in the version folder)
    try:
        for src in (md_path, json_path):
            shutil.copy2(src, os.path.join(vdir, os.path.basename(src)))
            kept.append((src, os.path.join(vdir, os.path.basename(src))))
        for i, src in enumerate(pdfs):
            # A second copy can differ from the first, so it is kept under its own folder's name.
            sub = vdir if i == 0 else os.path.join(vdir, "copy_in_" + os.path.basename(os.path.dirname(src)))
            os.makedirs(sub, exist_ok=True)
            shutil.copy2(src, os.path.join(sub, os.path.basename(src)))
            kept.append((src, os.path.join(sub, os.path.basename(src))))
        # 2 and 3. The new files are written and rendered in staging. Nothing is in place yet.
        staging = tempfile.mkdtemp(prefix=".staging-", dir=parent)
        new_md = os.path.join(staging, os.path.basename(md_path))
        new_json = os.path.join(staging, os.path.basename(json_path))
        new_pdf = os.path.join(staging, stem + "_cover.pdf")
        _write(new_md, p["md_text"])
        _write(new_json, p["json_text"])
    except Exception:
        nothing_moved()
        raise
    try:
        render(new_json, new_pdf)
        if not os.path.exists(new_pdf):
            raise RuntimeError("the renderer left no PDF")
    except Exception as e:  # noqa: BLE001 - a failed render is a result, and nothing has moved
        nothing_moved()
        return {"status": "failed", "reason": f"The PDF couldn't be rendered ({type(e).__name__}: {str(e)[:160]}), "
                                              "so the letter's files were left as they were."}
    try:
        for extra in targets[1:]:
            shutil.copy2(new_pdf, extra + ".new")
            os.replace(extra + ".new", extra)
        os.makedirs(os.path.dirname(targets[0]), exist_ok=True)
        os.replace(new_md, md_path)
        os.replace(new_json, json_path)
        os.replace(new_pdf, targets[0])
        back, why = bd.read_letter(tailored, stem)
        if back is None or back["paras"] != paras:
            raise RuntimeError(f"the files didn't read back as the edit ({why or 'different paragraphs'})")
    except Exception as e:  # noqa: BLE001 - put the kept version back; the version folder is never removed here
        put_back = True
        for in_place, copy in kept:
            try:
                shutil.copy2(copy, in_place)
            except OSError:
                put_back = False
        for made in ([] if pdfs else targets[:1]) + [extra + ".new" for extra in targets[1:]]:
            with contextlib.suppress(OSError):
                os.remove(made)   # a PDF where there was none before, or a half-copied second one
        shutil.rmtree(staging, ignore_errors=True)
        where = os.path.relpath(vdir, os.path.dirname(tailored))
        return {"status": "failed",
                "reason": f"Writing the files failed ({type(e).__name__}: {str(e)[:160]}). "
                          + (f"The earlier version was put back; a copy is in {where}." if put_back
                             else f"PUTTING THE EARLIER VERSION BACK ALSO FAILED: it is in {where}.")}
    shutil.rmtree(staging, ignore_errors=True)

    # 4. The voice gate, for information. His words stand whatever it says.
    try:
        clean, detail = voice(md_path)
    except Exception as e:  # noqa: BLE001
        clean, detail = None, f"check_voice.py could not run ({type(e).__name__}: {str(e)[:120]})"

    # What else quotes the letter. Said, never acted on.
    notes = []
    old_promise = bd.find_letter_sentences(letter["paras"]).get("promise")
    new_promise = bd.find_letter_sentences(paras).get("promise")
    first_changed = first_sentence(letter["paras"]) != first_sentence(paras)
    promise_changed = old_promise != new_promise
    if first_changed:
        notes.append("the first sentence changed; tailored/_cover_openers.md still has the old opener and was left alone")
    if promise_changed:
        notes.append("the promise sentence changed" + ("" if new_promise else " and the finder no longer sees one")
                     + "; the commitment line on the dashboard comes from the run's brief file and still has the old wording")
    elif not old_promise and letter["paras"][-1] != paras[-1]:
        notes.append("the last paragraph changed, and the finder saw no promise sentence in it before or after; "
                     "check the commitment line on the dashboard by eye")
    return {"status": "applied", "version": vdir, "new_sha": bd.letter_sha(paras), "pdfs": targets,
            "voice_clean": clean, "voice": detail, "notes": notes,
            "first_sentence_changed": first_changed, "promise_changed": promise_changed}


def load_results(jobs_dir):
    try:
        with open(os.path.join(jobs_dir, RESULTS_NAME), encoding="utf-8") as f:
            rows = json.load(f).get("rows")
    except FileNotFoundError:
        return {}
    return {k: v for k, v in rows.items() if isinstance(v, dict)} if isinstance(rows, dict) else {}


def save_results(jobs_dir, rows, today):
    path = os.path.join(jobs_dir, RESULTS_NAME)
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")   # one copy aside before the rewrite
    fd, tmp = tempfile.mkstemp(prefix=".letter_edit_results.", suffix=".tmp", dir=jobs_dir)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"updated": today.isoformat(), "rows": rows}, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def drain(inbox_path, today, apply, outcomes=None, jobs_dir=None, tailored=None,
          render=None, voice=None, now=None):
    """Plan every saved edit and, with `apply`, carry the plans out.

    Returns {"seen", "summary", "lines", "problems"}; the caller prints. Raises when the
    page's storage or the tracker can't be read, and applies nothing in that case: without
    the waiting Sent marks it can't tell which letters may have gone out.
    """
    outcomes, jobs_dir, tailored = outcomes or OUTCOMES, jobs_dir or JOBS_DIR, tailored or TAILORED
    render, voice, now = render or render_cover, voice or voice_report, now or datetime.now()
    edits, why = shelf_inbox.load_marks(inbox_path, LETTERS_KEY)
    if not edits:
        return {"seen": 0, "summary": f"no letter edits saved ({why or 'none on the page'})", "lines": [], "problems": 0}
    marks, _ = shelf_inbox.load_marks(inbox_path, shelf_inbox.INBOX_KEY)
    (by_url, by_stem), sent = read_rows(outcomes), sent_waiting(marks)
    results = load_results(jobs_dir)   # a results file that won't parse stops the drain; it is never overwritten
    before = json.dumps(results, sort_keys=True)

    counts = dict.fromkeys(("applied", "refused", "failed", "already", "repeat"), 0)
    lines, log = [], []
    for key, edit in sorted(edits.items()):
        key = str(key)
        try:
            p = plan_one(key, edit, by_url, by_stem, sent, tailored)
        except Exception as e:  # noqa: BLE001 - one bad edit must not block the others
            p = {"key": key, "label": key[:80], "status": "refused", "stem": "", "saved_at": "", "base_sha": "",
                 "text_sha": "", "paras": [], "reason": f"The edit couldn't be read ({type(e).__name__}: {str(e)[:120]})."}
        last = (results.get(key) or {}).get("last") or {}
        same_edit = all(last.get(k) == p[k] for k in ("saved_at", "base_sha", "text_sha"))
        entry = {"at": now.isoformat(timespec="seconds"), "url": key, "label": p["label"], "stem": p["stem"],
                 "saved_at": p["saved_at"], "base_sha": p["base_sha"], "text_sha": p["text_sha"]}

        if p["status"] == "already":
            if same_edit and last.get("status") in ("applied", "already"):
                counts["repeat"] += 1   # the page hasn't cleared it yet; nothing new to say
                continue
            counts["already"] += 1
            lines.append(f"already applied: {p['label']}")
            entry.update(status="already", reason="")
        elif p["status"] == "refused":
            if same_edit and last.get("status") == "refused" and last.get("reason") == p["reason"]:
                counts["repeat"] += 1
                continue
            counts["refused"] += 1
            lines.append(f"{'refused' if apply else 'would refuse'}: {p['label']}: {p['reason']}")
            entry.update(status="refused", reason=p["reason"], text="\n\n".join(p["paras"]))
        elif not apply:
            counts["applied"] += 1
            lines.append(f"would apply: {p['label']} ({p['words']} words in {len(p['paras'])} paragraphs)")
            continue
        else:
            try:
                r = apply_one(p, tailored, now, render, voice)
            except Exception as e:  # noqa: BLE001
                r = {"status": "failed", "reason": f"Applying it failed before anything was written ({type(e).__name__}: {str(e)[:160]})."}
            if r["status"] == "failed":
                counts["failed"] += 1
                lines.append(f"FAILED: {p['label']}: {r['reason']}")
                entry.update(status="failed", reason=r["reason"], text="\n\n".join(p["paras"]))
            else:
                counts["applied"] += 1
                lines.append(f"applied: {p['label']} ({p['words']} words in {len(p['paras'])} paragraphs). "
                             f"Earlier version kept in {os.path.relpath(r['version'], os.path.dirname(tailored))}")
                lines.append(f"  check_voice.py, for information only: {r['voice'] or 'nothing to report'}")
                lines.extend(f"  note: {n}" for n in r["notes"])
                entry.update(status="applied", reason="", new_sha=r["new_sha"],
                             version=os.path.relpath(r["version"], os.path.dirname(tailored)),
                             pdfs=[os.path.relpath(x, os.path.dirname(tailored)) for x in r["pdfs"]],
                             words=p["words"], paragraphs=len(p["paras"]), voice_clean=r["voice_clean"], voice=r["voice"],
                             first_sentence_changed=r["first_sentence_changed"], promise_changed=r["promise_changed"])
                results.setdefault(key, {})["applied"] = {
                    "saved_at": p["saved_at"], "at": today.isoformat(), "new_sha": r["new_sha"], "stem": p["stem"]}
        if not apply:
            continue
        results.setdefault(key, {})["last"] = {
            "status": entry["status"], "reason": entry["reason"], "at": today.isoformat(), "stem": p["stem"],
            "saved_at": p["saved_at"], "base_sha": p["base_sha"], "text_sha": p["text_sha"]}
        log.append(entry)

    if apply:
        # A row that has left the queue takes its result with it, unless an edit for it is still saved.
        for key in [k for k in results if k not in edits]:
            rows = by_url.get(key, [])
            if len(rows) != 1 or rows[0]["stage"] != "surfaced" or rows[0]["his_verdict"]:
                del results[key]
        if log:
            os.makedirs(jobs_dir, exist_ok=True)
            with open(os.path.join(jobs_dir, LOG_NAME), "a", encoding="utf-8") as f:
                for entry in log:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if json.dumps(results, sort_keys=True) != before:
            os.makedirs(jobs_dir, exist_ok=True)
            save_results(jobs_dir, results, today)

    did = ("applied", "refused") if apply else ("would apply", "would refuse")
    summary = f"{did[0]} {counts['applied']}, {did[1]} {counts['refused']}"
    if counts["failed"]:
        summary += f", {counts['failed']} FAILED"
    if counts["already"]:
        summary += f", {counts['already']} already applied"
    if counts["repeat"]:
        summary += f", {counts['repeat']} unchanged since an earlier run"
    return {"seen": len(edits), "summary": summary, "lines": lines, "problems": counts["failed"]}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    strict = "--strict" in argv
    try:
        today = shelf_inbox.parse_date(argv[argv.index("--today") + 1]) if "--today" in argv else date.today()
        if today is None:
            raise ValueError("--today needs YYYY-MM-DD")
        inbox = argv[argv.index("--inbox") + 1] if "--inbox" in argv else None
        # A pinned --today pins the clock too (tests), the way build_dashboard.py does it.
        now = datetime(today.year, today.month, today.day, 7, 0) if "--today" in argv else None
        r = drain(inbox, today, "--apply" in argv, now=now)
        for line in r["lines"]:
            print(f"  {line}")
        print(f"letter_edits: {r['summary']}"
              + ("" if "--apply" in argv or not r["seen"] else " (report only; --apply applies them)"))
        return 1 if (strict and r["problems"]) else 0
    except Exception as e:  # noqa: BLE001 - an inbox failure must never fail the run
        print(f"letter_edits: FAILED {type(e).__name__}: {e}")
        return 1 if strict else 0


if __name__ == "__main__":
    sys.exit(main())
