#!/usr/bin/env python3
"""Calibration loop report: predicted vs actual outcome across every post-mortem. Read-only.

Every post-mortem ends with a Section 8 that is meant to be filled twice: a prediction at
the time of writing, and the actual outcome when it lands. Before 2026-10-23 the second pass
had happened for 2 of 7 files, so self-grading had almost nothing to calibrate against. This
script lists every post-mortem's prediction and actual, suggests the actual from the ledger
where the file is blank (a later round in interviews.json means "advanced"; a terminal outcome
in outcomes.csv or the interview-loop state file means what it says; a long silence is named
as silence), and prints a running tally. It never writes to a post-mortem.

Usage:
    .venv/bin/python pipeline/calibration.py          # table + tally
    .venv/bin/python pipeline/calibration.py --json   # machine-readable
"""
import argparse
import csv
import datetime
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
HERE = ROOT / "interview_prep"
OUTCOMES = ROOT / "pipeline" / "outcomes.csv"
INTERVIEWS = ROOT / "pipeline" / "jobs" / "interviews.json"
STATE = pathlib.Path.home() / ".claude" / "skills" / "interview-loop" / "state.json"

PLACEHOLDER = re.compile(r"_\[.*?\]_")
DATE = re.compile(r"(20\d\d-\d\d-\d\d)")
SILENT_AFTER_DAYS = 21
TERMINAL = ("rejected", "declined", "offer", "withdrawn", "closed", "hired", "accepted")


def field(section, label):
    """First '**Label**: value' in the section; '' when blank, a placeholder, or template text."""
    m = re.search(r"\*\*" + re.escape(label) + r"\*\*:[ \t]*(.*)", section)
    if not m:
        return ""
    v = m.group(1).strip()
    # Blank, a bare placeholder, or the template's own hint text all mean "not filled in".
    # A filled value that carries a trailing _[confirm ...]_ note still counts as filled.
    if not v or v.startswith("_[") or v.startswith("("):
        return ""
    return v


def outcome_date(notes):
    """outcomes.csv has no date column for the outcome; mark_outcome.py appends 'outcome YYYY-MM[-DD]' to notes."""
    m = re.search(r"outcome (20\d\d-\d\d(?:-\d\d)?)", notes or "")
    return m.group(1) if m else "?"


def is_match(predicted, actual, delta):
    """Did the prediction hold? The Delta field decides when filled; otherwise compare the lead words."""
    d = (delta or "").lower()
    if d:
        return "match" in d or d.startswith("none")
    p, a = (predicted or "").lower(), (actual or "").lower()
    for stem in ("advance", "decline", "redirect", "reject", "offer"):
        if p.startswith(stem):
            return stem in a
    return False


def section(text, number):
    """Text of '## N.' up to the next '## ' heading."""
    m = re.search(r"^## " + str(number) + r"\..*?$", text, re.M)
    if not m:
        return ""
    rest = text[m.end():]
    n = re.search(r"^## ", rest, re.M)
    return rest[: n.start()] if n else rest


def round_number(path):
    m = re.search(r"postmortem_round(\d+)", path.name)
    return int(m.group(1)) if m else None


def same_company(a, b):
    a, b = a.lower().strip(), b.lower().strip()
    return a == b or a.startswith(b) or b.startswith(a)


def load_ledger():
    rows = {}
    if OUTCOMES.exists():
        with OUTCOMES.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows.setdefault(r.get("company", ""), []).append(r)
    rounds = []
    if INTERVIEWS.exists():
        data = json.loads(INTERVIEWS.read_text(encoding="utf-8"))
        rounds = data.get("rounds", data) if isinstance(data, dict) else data
    state = {}
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text(encoding="utf-8")).get("companies", {})
        except Exception:
            state = {}
    return rows, rounds, state


def suggest(company, round_date, round_no, ledger, rounds, state, today):
    """What the ledger says happened after this round, as a short string, or ''."""
    hints = []
    later = [r for r in rounds
             if round_date
             and same_company(r.get("company", ""), company)
             and r.get("date", "") > round_date]
    if later:
        nxt = sorted(later, key=lambda r: r.get("date", ""))[0]
        hints.append(f"advanced: later round {nxt.get('date')} ({nxt.get('label', nxt.get('kind', ''))})")
    for name, rs in ledger.items():
        if same_company(name, company):
            for r in rs:
                oc = (r.get("outcome") or "").lower()
                if oc in TERMINAL:
                    hints.append(f"ledger: {oc} ({outcome_date(r.get('notes'))})")
    for name, e in state.items():
        if same_company(name, company):
            lr = e.get("last_round", {})
            if lr.get("result"):
                hints.append("state: " + lr["result"][:90])
            if e.get("closed"):
                hints.append("state: closed")
    if not hints and round_date:
        try:
            days = (today - datetime.date.fromisoformat(round_date)).days
            if days >= SILENT_AFTER_DAYS:
                hints.append(f"silent {days} days since the round (no later round, no terminal outcome on file)")
        except ValueError:
            pass
    return "; ".join(hints)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    today = datetime.date.today()
    ledger, rounds, state = load_ledger()

    entries = []
    for path in sorted(HERE.glob("*/postmortem_*.md")):
        text = path.read_text(encoding="utf-8")
        company = path.parent.name
        s1, s8 = section(text, 1), section(text, 8)
        dm = DATE.search(field(s1, "Date") or s1) or DATE.search(text[:3000])
        round_date = dm.group(1) if dm else ""
        rn = round_number(path)
        predicted = field(s8, "Predicted outcome")
        if predicted.lower().startswith(("n/a", "none")):
            predicted = ""  # "none (late)" or "n/a": written after the outcome was known; nothing to score
        actual = field(s8, "Actual outcome")
        delta = field(s8, "Delta from prediction")
        entries.append({
            "company": company,
            "file": str(path.relative_to(ROOT)),
            "round": rn,
            "date": round_date,
            "predicted": predicted,
            "confidence": field(s8, "Confidence"),
            "actual": actual,
            "date_learned": field(s8, "Date outcome learned"),
            "delta": delta,
            "suggested": "" if actual else suggest(company, round_date, rn, ledger, rounds, state, today),
        })

    # Rounds in the log that have no post-mortem file at all.
    undebriefed = []
    for r in rounds:
        covered = any(
            same_company(e["company"], r.get("company", ""))
            and (e["date"] == r.get("date", "") or (e["round"] is not None and e["round"] == r.get("round")))
            for e in entries
        )
        if not covered:
            undebriefed.append(f"{r.get('company')} {r.get('date')} ({r.get('label', r.get('kind', ''))})")

    made = [e for e in entries if e["predicted"]]
    resolved = [e for e in entries if e["actual"]]
    scored = [e for e in entries if e["predicted"] and e["actual"]]
    matched = [e for e in scored if is_match(e["predicted"], e["actual"], e["delta"])]
    unscored = [e for e in entries if not e["predicted"]]
    open_ = [e for e in entries if not e["actual"]]

    tally = {
        "post_mortems": len(entries),
        "predictions_made": len(made),
        "actuals_recorded": len(resolved),
        "scored": len(scored),
        "matched": len(matched),
        "no_prediction": [e["file"] for e in unscored],
        "open": [e["file"] for e in open_],
        "rounds_without_postmortem": undebriefed,
    }

    if args.json:
        print(json.dumps({"entries": entries, "tally": tally}, indent=2))
        return 0

    def cut(s, n):
        s = s or ""
        return s if len(s) <= n else s[: n - 1] + "…"

    print(f"{'Company / round':<24} {'Date':<11} {'Predicted':<26} {'Actual':<30} {'Delta':<10}")
    print("-" * 104)
    for e in entries:
        label = f"{e['company']} R{e['round'] or '?'}"
        print(f"{cut(label, 24):<24} {e['date'] or '?':<11} {cut(e['predicted'] or 'NONE', 26):<26} "
              f"{cut(e['actual'] or 'OPEN', 30):<30} {cut(e['delta'] or '-', 10):<10}")
        if e["suggested"]:
            print(f"{'':<24} {'':<11} suggested: {e['suggested']}")
    print("-" * 104)
    print(f"{tally['post_mortems']} post-mortems: {tally['predictions_made']} predictions made, "
          f"{tally['actuals_recorded']} actuals recorded, {tally['scored']} scored, {tally['matched']} matched.")
    if unscored:
        print("No prediction (unscorable): " + ", ".join(f"{e['company']} R{e['round']}" for e in unscored))
    if open_:
        print("Open (actual blank): " + ", ".join(f"{e['company']} R{e['round']}" for e in open_))
    if undebriefed:
        print("Rounds in interviews.json with no post-mortem: " + "; ".join(undebriefed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
