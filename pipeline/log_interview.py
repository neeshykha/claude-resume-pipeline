#!/usr/bin/env python3
"""Records interview ROUNDS in pipeline/jobs/interviews.json, the dashboard's interview log.

Usage:
    .venv/bin/python pipeline/log_interview.py <rounds.json>
    .venv/bin/python pipeline/log_interview.py --list

Added 2026-10-15 (D42). outcomes.csv holds one row per application, so it can say a role
reached an interview (`furthest_stage`) but not when, or how many rounds there were; the
interview-loop skill's state.json keeps only each company's latest round. This file keeps
every round with its date, which is what the dashboard's Progress section charts.

Written by the interview-loop skill at its Step 5, alongside mark_outcome.py, whenever a
round is known to have HAPPENED. Never log an invite for a round that hasn't taken place.
The log lives under jobs/, which is gitignored: company names stay out of this public repo.

Input schema:

{
  "rounds": [
    {
      "company": "Example Co",
      "date": "2026-10-20",                  # the day the round happened
      "kind": "screen",                      # screen | interview | onsite | assessment
      "round": 1,                            # optional; numbered by date when omitted
      "label": "R1 recruiter screen",        # optional, shown on the page
      "url": "https://..."                   # optional; the posting, so the round finds its row
    }
  ]
}

`kind`: screen is the first conversation (recruiter or intro call); interview is a later
hiring-manager or team round; onsite is a panel or final, in person or not; assessment is a
take-home or online test, which the page counts apart from conversations and never numbers.

One round per company, date, and round number. Sending the same one again updates its label,
kind, or URL in place instead of adding a second copy, so a rerun is safe.
"""
import json
import os
import re
import shutil
import sys
from datetime import date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(SCRIPT_DIR, "jobs", "interviews.json")
KINDS = ("screen", "interview", "onsite", "assessment")
README = ("Interview rounds, one entry per round that happened. Written by pipeline/log_interview.py "
          "(interview-loop Step 5); read by build_dashboard.py. Don't hand-edit.")


def slug(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def parse_day(s):
    try:
        return date.fromisoformat((s or "").strip()).isoformat()
    except Exception:
        return None


def load():
    if not os.path.exists(LOG):
        return {"_readme": README, "rounds": []}
    with open(LOG, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("rounds"), list):
        raise ValueError(f"{LOG} has no rounds list; fix it by hand before logging more")
    return data


def save(data):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    if os.path.exists(LOG):
        shutil.copy2(LOG, LOG + ".bak")
    tmp = LOG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, LOG)


def clean(r):
    """A validated round, or an error string."""
    if not isinstance(r, dict):
        return "not an object"
    company = (r.get("company") or "").strip() if isinstance(r.get("company"), str) else ""
    day = parse_day(r.get("date") if isinstance(r.get("date"), str) else "")
    kind = r.get("kind")
    if not company:
        return "no company"
    if not day:
        return f"{company}: date must be YYYY-MM-DD"
    if day > date.today().isoformat():
        return f"{company}: {day} is in the future; log a round once it has happened"
    if kind not in KINDS:
        return f"{company}: kind must be one of {', '.join(KINDS)}"
    n = r.get("round")
    if n is not None and (not isinstance(n, int) or isinstance(n, bool) or not 0 < n < 50):
        return f"{company}: round must be a whole number"
    out = {"company": company, "date": day, "kind": kind, "round": None if kind == "assessment" else n}
    for k in ("label", "url"):
        if isinstance(r.get(k), str) and r[k].strip():
            out[k] = r[k].strip()
    return out


def renumber(rounds):
    """Number each conversation that came in without one by its place in its company's order
    by date. Those carry `auto`, so an earlier round logged later moves them along."""
    count = {}
    for r in sorted(rounds, key=lambda r: r["date"]):
        if r["kind"] == "assessment":
            r["round"] = None
            r.pop("auto", None)
            continue
        k = slug(r["company"])
        count[k] = count.get(k, 0) + 1
        if r.get("round") is None or r.get("auto"):
            r["round"], r["auto"] = count[k], True


def find(rounds, r):
    """The logged round this one restates, or None. Without a number, a conversation is the one
    already logged for that company on that day, if there is exactly one."""
    same_day = [x for x in rounds if slug(x["company"]) == slug(r["company"]) and x["date"] == r["date"]
                and (x["kind"] == "assessment") == (r["kind"] == "assessment")]
    if r["kind"] == "assessment" or r["round"] is None:
        return same_day[0] if len(same_day) == 1 else None
    return next((x for x in same_day if x.get("round") == r["round"]), None)


def main(argv):
    if argv == ["--list"]:
        for r in load()["rounds"]:
            n = "" if r.get("round") is None else f"R{r['round']} "
            print(f"{r['date']}  {r['company']}  {n}{r['kind']}  {r.get('label', '')}")
        return 0
    if len(argv) != 1:
        print(__doc__.split("\n\n")[1])
        return 2
    with open(argv[0], encoding="utf-8") as f:
        incoming = json.load(f).get("rounds") or []
    data = load()
    rounds = data["rounds"]
    added = updated = unchanged = 0
    for raw in incoming:
        r = clean(raw)
        if isinstance(r, str):
            print(f"  SKIPPED: {r}")
            continue
        hit = find(rounds, r)
        explicit = r["round"] is not None
        if not explicit:
            del r["round"]  # never let an update erase a number given earlier
        if hit is None:
            rounds.append(r)
            added += 1
            print(f"  logged: {r['company']} {r['date']} {r['kind']}")
        elif any(hit.get(k) != v for k, v in r.items()) or (explicit and hit.get("auto")):
            hit.update(r)
            if explicit:
                hit.pop("auto", None)
            updated += 1
            print(f"  updated: {r['company']} {r['date']} {r['kind']}")
        else:
            unchanged += 1
    renumber(rounds)
    rounds.sort(key=lambda x: (x["date"], slug(x["company"])))
    data["_readme"] = README
    if added or updated:
        save(data)
    print(f"interviews.json: {added} added, {updated} updated, {unchanged} already logged; {len(rounds)} rounds in all")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
