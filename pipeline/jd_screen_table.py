#!/usr/bin/env python3
"""Merge the Step 2-JD screen cards into one compact line per role.

Usage:
    .venv/bin/python pipeline/jd_screen_table.py                  # today
    .venv/bin/python pipeline/jd_screen_table.py --date 2026-09-24
    .venv/bin/python pipeline/jd_screen_table.py --show "<company>"   # full card(s)

Reads pipeline/jobs/jd_cache/<date>/manifest.json plus every cards_batch_*.json
the screen workers wrote, joins them on the JD file path, and prints:

  1. PASS lines: roles whose card clears the objective gates below, by pre_score.
  2. CHECK lines: a gate could not be decided from the card (location or pay
     unclear). The orchestrator decides these; they are not failures.
  3. FAIL lines, one each, with the gate that failed.
  4. MISSING: manifest entries with no card (worker failed, fetch error, or a
     rippling/pinpoint URL with no fetcher). The orchestrator handles these the
     old way, from the listing plus fetch_jd/WebFetch if they look strong.

Gates are the mechanical half of Step 2b, applied to facts the worker QUOTED:
  location  atlanta_ok == yes, or work_mode == remote_us. Anything else = FAIL
            unless the card says unclear (-> CHECK).
  salary    midpoint >= salary_floor_usd; between near_miss floor and floor =
            FAIL(salary near-miss) so it still reaches the near-miss list;
            IC roles get the IC floor note but the orchestrator applies the
            interest-category branch. No salary = neutral, never a fail.
  red flags crypto / clearance_required / vp_or_above / non_us_only /
            staffing_agency / posting_closed are FAILs; the rest are shown.
Nothing here scores. Scoring stays with Step 2c, on the orchestrator.

Also writes jd_cache/<date>/screen_table.json (the same rows, machine-readable)
so Step 6 can record screened roles without re-deriving them.
"""
import argparse
import glob
import json
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
HARD_FLAGS = {"crypto", "clearance_required", "vp_or_above", "non_us_only",
              "staffing_agency", "posting_closed"}


def cfg():
    with open(os.path.join(HERE, "watchlist_companies.json"), encoding="utf-8") as f:
        sc = json.load(f)["_scoring_config"]
    return (sc["salary_floor_usd"], sc["near_miss_salary_floor_usd"],
            sc.get("ic_scope_rule", {}).get("non_interest_floor_usd"))


def money(n):
    return f"${round(n / 1000)}K" if n else "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--show", help="print the full card(s) for this company and exit")
    args = ap.parse_args()

    cache = os.path.join(HERE, "jobs", "jd_cache", args.date)
    try:
        with open(os.path.join(cache, "manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)
    except OSError as exc:
        print(f"jd_screen_table: FAILED, no manifest for {args.date}: {exc}")
        return 1

    cards = {}
    bad_batches = []
    for p in sorted(glob.glob(os.path.join(cache, "cards_batch_*.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                for c in json.load(f):
                    if isinstance(c, dict) and c.get("file"):
                        cards[os.path.abspath(c["file"])] = c
        except (OSError, ValueError) as exc:
            bad_batches.append(f"{os.path.basename(p)}: {exc}")

    if args.show:
        needle = args.show.lower()
        for c in cards.values():
            if needle in (c.get("company") or "").lower():
                print(json.dumps(c, indent=1))
        return 0

    floor, nm_floor, ic_floor = cfg()
    rows, missing = [], []
    for e in manifest["entries"]:
        card = cards.get(os.path.abspath(e["file"])) if e.get("file") else None
        if not card or not card.get("read_ok", True):
            if not e.get("status", "").startswith("skipped"):
                missing.append(e)
            continue
        fails, checks = [], []
        if card.get("atlanta_ok") == "yes" or card.get("work_mode") == "remote_us":
            loc = "ATL" if card.get("atlanta_ok") == "yes" and card.get("work_mode") != "remote_us" else "remote"
        elif card.get("atlanta_ok") == "unclear" or card.get("work_mode") == "unclear":
            loc = "loc?"
            checks.append("location unclear")
        else:
            loc = card.get("work_mode") or "?"
            fails.append(f"location ({card.get('location_verbatim', '')[:60]})")
        lo, hi = card.get("salary_min_usd"), card.get("salary_max_usd")
        mid = (lo + hi) / 2 if lo and hi else (lo or hi)
        pay = f"{money(lo)}-{money(hi)}" if lo and hi else (money(mid) if mid else "no pay")
        if mid:
            if mid < nm_floor:
                fails.append(f"salary mid {money(mid)}")
            elif mid < floor:
                fails.append(f"salary near-miss mid {money(mid)}")
            elif card.get("manages_people") == "ic" and ic_floor and mid < ic_floor:
                checks.append(f"IC under {money(ic_floor)}: interest-category call")
        flags = card.get("red_flags") or []
        fails += [f"flag:{x}" for x in flags if x in HARD_FLAGS]
        soft = [x for x in flags if x not in HARD_FLAGS]
        years = card.get("years_required_verbatim") or []
        status = "FAIL" if fails else ("CHECK" if checks else "PASS")
        rows.append({
            "status": status, "fails": fails, "checks": checks,
            "pre_score": e.get("pre_score"), "source": e["source"],
            "company": card.get("company") or e["company"],
            "title": card.get("title") or e["title"], "url": e["url"],
            "loc": loc, "pay": pay, "mid": mid,
            "scope": card.get("manages_people"), "function": card.get("function"),
            "years": years, "soft_flags": soft,
            "overlap": (card.get("resume_overlap") or {}).get("estimate_0_30"),
            "vendor_tools": card.get("vendor_tools_named") or [],
            "jd_verification_required": e.get("jd_verification_required"),
            "file": e["file"],
        })

    rows.sort(key=lambda r: (["PASS", "CHECK", "FAIL"].index(r["status"]),
                             -(r["pre_score"] or 0)))
    with open(os.path.join(cache, "screen_table.json"), "w", encoding="utf-8") as f:
        json.dump({"date": args.date, "rows": rows,
                   "missing": [{k: m.get(k) for k in ("company", "title", "url", "ats",
                                                      "pre_score", "status", "error")}
                               for m in missing]}, f, indent=1)
        f.write("\n")

    # Batches with at least one uncarded JD: the orchestrator re-dispatches each
    # ONCE, then treats whatever is still missing the old way.
    redispatch = []
    for p in sorted(glob.glob(os.path.join(cache, "batch_*.json"))):
        with open(p, encoding="utf-8") as f:
            files = [os.path.abspath(x) for x in json.load(f)]
        if any(x not in cards for x in files):
            redispatch.append(os.path.basename(p))

    n = {s: sum(1 for r in rows if r["status"] == s) for s in ("PASS", "CHECK", "FAIL")}
    print(f"jd_screen: {len(rows)} cards -> PASS {n['PASS']}, CHECK {n['CHECK']}, "
          f"FAIL {n['FAIL']}; missing {len(missing)}")
    if redispatch:
        print("RE-DISPATCH (uncarded JDs): " + ", ".join(redispatch))
    for b in bad_batches:
        print(f"  UNREADABLE CARD FILE {b}")
    for r in rows:
        yrs = "; ".join(y[:70] for y in r["years"][:2]) or "no years bar"
        tail = []
        if r["jd_verification_required"]:
            tail.append("JD-VERIFY")
        if r["soft_flags"]:
            tail.append("flags " + ",".join(r["soft_flags"]))
        if r["checks"]:
            tail.append("check: " + "; ".join(r["checks"]))
        if r["fails"]:
            tail.append("fail: " + "; ".join(r["fails"]))
        print(f"{r['status']:5} [{r['pre_score'] or '-':>3}] {r['company']}: {r['title'][:60]} | "
              f"{r['loc']} | {r['pay']} | {r['scope']} | ovl~{r['overlap']} | {yrs}"
              + (f" | {' | '.join(tail)}" if tail else ""))
    for m in missing:
        print(f"MISSING [{m.get('pre_score') or '-':>3}] {m['company']}: {m['title'][:60]} "
              f"({m.get('ats')}, {m.get('status')}) {m['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
