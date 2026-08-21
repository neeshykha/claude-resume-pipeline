"""Recompute pipeline job scores from the rubric and flag disagreements.

The rubric has two halves. One is mechanical — title tier, source quality,
company bonuses, salary band, freshness — and can be recomputed exactly from
`watchlist_companies.json` plus the recorded URL and title. The other is
judgment — keyword overlap (0-30) and the two reach penalties (-10..0) — and
cannot be recomputed at all.

So this does not try to produce "the right score". It bounds the score the
rubric could legally have produced given the mechanical half, and reports the
recorded score against that envelope. A score outside the envelope is provably
wrong under the rubric; a score inside it is unfalsifiable from data alone, and
gets reported as the judgment call it requires ("this needs keyword overlap of
29/30") so Aneesh can eyeball whether that's plausible.

Alongside the envelope are the structural checks, which are exact: the
hard-requirement tier cap, the tailoring thresholds, and the skip floor. Those
catch the class of error that has actually happened.

Output is a static HTML report in pipeline/logs/ (gitignored — it carries
company names and scores, which CLAUDE.md forbids committing to this public repo).

A rubric edit strands every score already recorded under it, so the audit also
detects RUBRIC DRIFT: queued rows still carrying a bonus a later rule change
retired. `--sweep-drift` re-tiers those and retires the ones that no longer
clear the skip floor.

Usage:
    .venv/bin/python pipeline/audit_scores.py
    .venv/bin/python pipeline/audit_scores.py --since 2026-08-01
    .venv/bin/python pipeline/audit_scores.py --validate            # self-check only
    .venv/bin/python pipeline/audit_scores.py --sweep-drift         # preview re-tier
    .venv/bin/python pipeline/audit_scores.py --sweep-drift --apply # write it
"""

import argparse
import csv
import html
import json
import os
import re
import shutil
import sys
from collections import Counter
from datetime import date, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from poll_ats import TitleMatcher

OUTCOMES = os.path.join(BASE, "outcomes.csv")
WATCHLIST = os.path.join(BASE, "watchlist_companies.json")
REPORT = os.path.join(BASE, "logs", "score_audit.html")

# Judgment components the rubric leaves to Claude. These are the only two, and
# their bounds are what make the envelope meaningful: everything else is pinned.
KEYWORD_OVERLAP = (0, 30)      # daily_task_prompt.md: "Keyword overlap with master resume: up to +30"
PENALTIES = (-10, 0)           # title gap -5, seniority mismatch -5, "Max -10 combined"


def load_watchlist():
    with open(WATCHLIST) as f:
        return json.load(f)


def company_index(watchlist):
    """Name -> entry. Also indexes the ATS slug, since outcomes.csv company
    names drift from watchlist names ('CSI (Computer Services, Inc.)')."""
    idx = {}
    for c in watchlist["companies"]:
        idx[c["name"].strip().lower()] = c
        idx.setdefault(c["slug"].strip().lower(), c)
    return idx


def lookup_company(idx, name):
    if not name:
        return None
    key = name.strip().lower()
    if key in idx:
        return idx[key]
    # Company names in outcomes.csv carry parentheticals and suffixes the
    # watchlist doesn't ("Weights & Biases (CoreWeave)").
    bare = re.sub(r"\s*\(.*?\)\s*", " ", key).strip()
    if bare in idx:
        return idx[bare]
    for k, v in idx.items():
        if k and (k == bare or k.startswith(bare + " ") or bare.startswith(k + " ")):
            return v
    return None


# ---------------------------------------------------------------- components

def title_component(matcher, title):
    """Exact when the matcher recognizes the title; a range when it doesn't.

    An unmatched title means the run scored it by judgment ('nearest real tier
    by function'), so the legal span is the full tier ladder.
    """
    hit = matcher.match_exact(title or "")
    if hit:
        tier, score = hit
        return (score, score), tier, True
    if matcher.matches_ai_wildcard(title or ""):
        s = matcher.ai_wildcard_score
        return (s, s), "tier2b_ai_wildcard", True
    return (8, 30), "unmatched", False


def source_component(url):
    """daily_task_prompt.md: Greenhouse/Lever +10, Ashby/BuiltIn +8, aggregator +5."""
    u = (url or "").lower()
    if "greenhouse" in u or "lever.co" in u:
        return (10, 10), "greenhouse/lever"
    if "ashbyhq" in u or "builtin" in u:
        return (8, 8), "ashby/builtin"
    if "linkedin" in u or "indeed" in u or "to.indeed" in u:
        return (5, 5), "aggregator"
    if "myworkdayjobs" in u:
        # Workday is a direct ATS but the rubric names only GH/Lever and
        # Ashby/BuiltIn. Left as a range rather than guessing which it lands in.
        return (8, 10), "workday (unspecified in rubric)"
    if u:
        return (5, 10), "other/unrecognized host"
    return (5, 10), "no url"


def company_bonus_component(entry, notes):
    """Company-level bonuses, hard-capped at +30 combined.

    Floor = what the config proves. Ceiling = 30, because Atlanta / IoT /
    passion-domain are semantic calls this can't make from data. When the
    provable floor already reaches 30 the clamp pins both ends.
    """
    known = 0
    parts = []
    if entry:
        sb = entry.get("score_bonus")
        if sb:
            known += sb
            parts.append(f"config score_bonus +{sb}")
        known += 10
        parts.append("watchlist +10")
        band = entry.get("headcount_band")
        if band:
            small = {"1-50": 15, "51-200": 15, "201-500": 8}.get(band, 0)
            if small:
                known += small
                parts.append(f"small-company +{small} ({band})")
            else:
                parts.append(f"small-company +0 ({band})")
        else:
            parts.append("small-company n/a (no headcount_band)")
        pen = entry.get("score_penalty")
        if pen:
            known += pen
            parts.append(f"config score_penalty {pen}")
    else:
        parts.append("not on watchlist (no +10, no config bonus)")

    # Atlanta is stated plainly enough in the notes to pin the floor upward.
    if re.search(r"\batlanta\b", notes or "", re.I):
        parts.append("Atlanta named in notes (+10/+20, not pinned)")

    lo = min(known, 30)
    hi = 30
    if known >= 30:
        lo = hi = 30
        parts.append("clamped at +30")
    return (lo, hi), parts


# Handles $120K, $87.2K, $99,280, and $146,000 alike.
MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*([KkMm])?")
# Everything from these words on is commission/variable, not base pay. Splitting
# here matters: Maven AGI's "$120K-$170K base + $40K-$60K commission" otherwise
# parses as a $105K midpoint instead of the correct $145K, which cost a full
# scoring band and manufactured a false envelope violation.
NOT_BASE = re.compile(r"\+\s*\$|commission|variable|bonus\b|equity", re.I)


def _money(text):
    out = []
    for raw, suf in MONEY.findall(text):
        try:
            v = float(raw.replace(",", ""))
        except ValueError:
            continue
        if suf and suf.lower() == "k":
            v *= 1_000
        elif suf and suf.lower() == "m":
            v *= 1_000_000
        elif v < 1_000:          # bare "$120" in a salary note means $120K
            v *= 1_000
        if 20_000 <= v <= 1_000_000:
            out.append(v)
    return out


def salary_component(notes):
    """Rubric: >=$140K +10 / >=$120K +8 / >=floor or unlisted +5 / below 0.

    Compares the MIDPOINT of the BASE range (never bottom or top), per
    _scoring_config.notes_salary. OTE-only figures are discounted to 80% for
    variable/sales roles, which is the basis the notes themselves use.
    """
    n = notes or ""
    m = re.search(r"midpoint[^)]{0,24}?\$\s?(\d[\d,]*(?:\.\d+)?)\s*([KkMm])?", n, re.I)
    mid, basis = None, ""
    if m:
        vals = _money(m.group(0))
        if vals:
            mid, basis = vals[0], "stated midpoint"
    if mid is None:
        head = NOT_BASE.split(n, 1)[0]
        vals = _money(head)
        if len(vals) >= 2:
            mid, basis = (min(vals) + max(vals)) / 2, "base range midpoint"
        elif len(vals) == 1:
            mid, basis = vals[0], "single figure"
        else:
            vals = _money(n)
            if len(vals) >= 2:
                mid, basis = (min(vals) + max(vals)) / 2, "range midpoint"
            elif len(vals) == 1:
                mid, basis = vals[0], "single figure"
    if mid is not None and re.search(r"\bOTE\b", n) and not re.search(r"\bbase\b", n, re.I):
        mid, basis = mid * 0.8, basis + ", OTE discounted to 80% base"
    if mid is None:
        if re.search(r"salary (not stated|unlisted|undisclosed|not listed)|no salary", n, re.I):
            return (5, 5), "unlisted (+5)"
        return (0, 10), "not parseable from notes"
    if mid >= 140_000:
        return (10, 10), f"${mid/1000:.0f}K {basis} (+10)"
    if mid >= 120_000:
        return (8, 8), f"${mid/1000:.0f}K {basis} (+8)"
    if mid >= 100_000:
        return (5, 5), f"${mid/1000:.0f}K {basis} (+5)"
    return (0, 0), f"${mid/1000:.0f}K {basis} (below floor, +0)"


def location_component(notes):
    """Atlanta in-office +20 / Atlanta hybrid +18 / remote US +16 / else 0.

    'hybrid' means Atlanta hybrid only as of 2026-08-02.
    """
    n = notes or ""
    atl = re.search(r"\batlanta\b|\bATL\b", n, re.I)
    if atl and re.search(r"hybrid", n, re.I):
        return (18, 18), "Atlanta hybrid (+18)"
    if atl:
        return (16, 20), "Atlanta named; in-office vs remote not pinned"
    if re.search(r"remote (u\.?s\.?|usa|us\b)|\bus remote\b|fully remote", n, re.I):
        return (16, 16), "remote US (+16)"
    if re.search(r"\bremote\b", n, re.I):
        return (0, 16), "remote, region unclear"
    return (0, 20), "not parseable from notes"


def freshness_component(notes):
    """+10 if <=2 days old, +2 if <=7. Also the -3 staleness hit past 14 days."""
    n = notes or ""
    m = re.search(r"posted (?:~)?(\d+)\s*days? ago", n, re.I)
    if not m:
        m = re.search(r"posted (\d+)d\b", n, re.I)
    if re.search(r"posted (yesterday|today|same day)|posted 1 day", n, re.I):
        return (10, 10), (0, 0), "posted <=2 days (+10)"
    if m:
        d = int(m.group(1))
        fresh = 10 if d <= 2 else (2 if d <= 7 else 0)
        stale = -3 if d > 14 else 0
        return (fresh, fresh), (stale, stale), f"posted {d}d ago (+{fresh}, staleness {stale})"
    return (0, 10), (-3, 0), "posting age not parseable from notes"


# ------------------------------------------------------------------- parsing

def parse_tier(notes):
    """What tailoring tier the run actually applied, per the notes prose."""
    n = (notes or "").lower()
    if not n.strip():
        return None
    head = n[:200]
    if "priority" in head:
        return "priority"
    if re.search(r"\blight\b", head):
        return "light"
    if "full tailoring" in head or "full tier" in head:
        return "full"
    return None


def expected_tier(score, cfg):
    if score >= cfg["company_cap_threshold"]:
        return "priority"
    if score >= cfg["full_tailoring_threshold"]:
        return "full"
    if score >= cfg["light_tailoring_threshold"]:
        return "light"
    return "skip"


def user_directed(notes):
    """Aneesh can override the tier by asking directly. Framer 2026-08-20 is
    the precedent: 2 unmet hard reqs, full tailoring, explicitly requested.
    Those are accepted exceptions, not findings."""
    return bool(re.search(r"user-directed|user-surfaced|user-pasted|"
                          r"interactive follow-up|aneesh asked|at aneesh's request",
                          notes or "", re.I))


def documented_override(notes):
    """A run that names the deviation and its reason has already done the
    thinking. LaunchDarkly 2026-07-08 ('Below normal light-tier score floor but
    surfaced anyway for exceptional salary') is a deliberate, argued exception;
    reporting it back as a finding is noise."""
    # A drift-swept row records the tailoring actually performed under the OLD
    # rubric alongside a score corrected to the new one, so the two disagree by
    # construction. That is the sweep working, not a finding -- and the row's
    # own note already states the tier change.
    if SWEPT.search(notes or ""):
        return True
    return bool(re.search(r"below (the )?(normal )?(light[- ]tier )?score floor|"
                          r"surfaced anyway|demoted to light|hard[- ]?cap|"
                          r"caps? base score|tier cap does not fire|"
                          r"despite .{0,40}coverage", notes or "", re.I))


# Language that shows the cap genuinely applies, versus language that shows it
# was considered and correctly declined.
CAP_FIRES = re.compile(
    r"(requires?|required|must have|non-?negotiable|bar is)\b[^.]{0,120}?"
    r"\b\d+\+?\s*years?|"
    r"\b\d+\+?\s*years?[^.]{0,120}?\b(required|require|minimum|bar)\b|"
    r"zero years|no years .{0,30}\bin that function\b|"
    r"required, not preferred", re.I)
CAP_DECLINED = re.compile(
    r"no years-of-experience minimum|cap does not fire|"
    r"stated as preferred, not required|counted as preferred|"
    r"not counted as a (third )?gap|arguably met", re.I)


# The location rule changed on 2026-08-02: NYC-NJ (+12) was removed and
# "hybrid" narrowed to mean ATLANTA hybrid only. Before that, a bare "hybrid"
# read as +18 regardless of city. Scores recorded under the old rule are not
# comparable to scores recorded under the new one, and any still-surfaced row
# carries a tier that today's rubric would not grant.
LOCATION_RULE_CHANGE = "2026-08-02"
# Written into a row's notes by --sweep-drift --apply, and read back by
# rubric_drift() so the sweep is idempotent. Keep the two in sync.
SWEPT = re.compile(r"drift sweep\]", re.I)
NON_ATL_ONSITE = re.compile(
    r"hybrid|on-?site|in-?office|in-?person|\bNYC\b|new york|\bNJ\b|\bSF\b|"
    r"san francisco|san jose|bellevue|seattle|boston|austin|chicago|sunnyvale",
    re.I)


def rubric_drift(notes, row_date, stage):
    """Does this row's score depend on the retired location rule?

    The two retired cases are disjoint and each pins an exact value, so this
    returns a number rather than a range:

      non-Atlanta "hybrid"  old +18 (bare "hybrid" scored +18 regardless of
                            city), new 0  ->  -18
      NYC/NJ, not hybrid    old +12 (the removed NYC-NJ band), new 0  ->  -12

    Anything else is unaffected. A non-Atlanta ONSITE role in a city that isn't
    NYC/NJ scored 0 under both rules and has no drift at all -- an earlier
    version of this flagged those too, which put Weights & Biases ("5 named hub
    cities, no remote option stated") on the list for a bonus it never received.

    Returns (applies, points_lost, still_actionable).
    """
    n = notes or ""
    # A swept row still has its old surfaced_date and still says "hybrid", so
    # nothing about the row itself stops a second pass from deducting the same
    # bonus twice. Re-running would have taken Harvey 99 -> 87 -> 75 and retired
    # six rows that had already been correctly re-tiered. The sweep stamps this
    # marker; honoring it is what makes the operation idempotent.
    if SWEPT.search(n):
        return False, 0, False
    if not row_date or row_date >= LOCATION_RULE_CHANGE:
        return False, 0, False
    if re.search(r"\batlanta\b|\bATL\b", n, re.I):
        return False, 0, False
    live = (stage or "").strip() == "surfaced"
    if re.search(r"hybrid", n, re.I):
        return True, 18, live
    if re.search(r"\bNYC\b|new york|\bNJ\b", n, re.I):
        return True, 12, live
    return False, 0, False


def hardreq_signal(notes, unmet_n):
    """Does the hard-requirement tier cap apply?

    `unmet_hard_reqs` alone cannot answer this, and that is the single biggest
    limit on this audit. The field counts every disclosed gap -- most of them
    soft ("no fintech domain", "no Stripe billing experience") -- while the cap
    fires only on a stated years-minimum in a function with zero years, or a
    requirement the JD marks non-negotiable. Nothing in the schema separates
    the two, so this reads the notes and returns "unknown" when they don't say.
    """
    n = notes or ""
    if CAP_DECLINED.search(n):
        return "declined"
    if unmet_n < 1:
        return "none"
    if CAP_FIRES.search(n):
        return "fires"
    return "unknown"


# -------------------------------------------------------------------- audit

def audit_row(row, matcher, idx, cfg):
    notes = row.get("notes") or ""
    title = row.get("title") or ""
    try:
        score = float(row.get("fit_score") or 0)
    except ValueError:
        score = 0
    if not score:
        return None

    t_rng, tier_name, t_exact = title_component(matcher, title)
    s_rng, s_label = source_component(row.get("url"))
    entry = lookup_company(idx, row.get("company"))
    c_rng, c_parts = company_bonus_component(entry, notes)
    sal_rng, sal_label = salary_component(notes)
    loc_rng, loc_label = location_component(notes)
    fr_rng, st_rng, fr_label = freshness_component(notes)

    pinned = [t_rng, s_rng, c_rng, sal_rng, loc_rng, fr_rng, st_rng]
    lo = sum(a for a, _ in pinned) + KEYWORD_OVERLAP[0] + PENALTIES[0]
    hi = sum(b for _, b in pinned) + KEYWORD_OVERLAP[1] + PENALTIES[1]

    # What keyword overlap the recorded score demands if every other component
    # sits at its most favourable legal value and no penalty was taken.
    best_other = sum(b for _, b in pinned)
    required_kw = score - best_other
    n_pinned = sum(1 for a, b in pinned if a == b)

    findings = []
    if score < lo:
        findings.append(("ENVELOPE", "high",
                         f"Recorded {score:.0f} is below the rubric minimum of {lo:.0f}. "
                         f"No judgment call produces this."))
    elif score > hi:
        findings.append(("ENVELOPE", "high",
                         f"Recorded {score:.0f} exceeds the rubric maximum of {hi:.0f}. "
                         f"No judgment call produces this."))
    elif required_kw > KEYWORD_OVERLAP[1]:
        findings.append(("ENVELOPE", "high",
                         f"Recorded {score:.0f} requires keyword overlap of "
                         f"{required_kw:.0f}, above the +30 ceiling."))
    elif required_kw > 26 and n_pinned >= 5:
        findings.append(("STRAINED", "medium",
                         f"Recorded {score:.0f} needs keyword overlap of {required_kw:.0f}/30 "
                         f"with every other component at its maximum and zero penalties. "
                         f"Possible, but it leaves no room."))

    applied = parse_tier(notes)
    want = expected_tier(score, cfg)
    unmet = (row.get("unmet_hard_reqs") or "").strip()
    unmet_n = int(unmet) if unmet.isdigit() else 0
    override = user_directed(notes)
    documented = documented_override(notes)

    # Priority and full prescribe identical tailoring steps -- priority only
    # marks "required for company-capped roles". Treating them as distinct tiers
    # generated six findings that described a labelling habit, not an error.
    def klass(t):
        return "full" if t in ("full", "priority") else t

    if applied:
        cap = hardreq_signal(notes, unmet_n)
        if cap == "fires" and klass(applied) == "full" and not override:
            findings.append(("HARDREQ_CAP", "high",
                             f"The notes describe an explicit years-minimum or a "
                             f"JD-stated non-negotiable, but {applied} tailoring was "
                             f"applied. The hard-requirement cap should have demoted "
                             f"this to light."))
        elif cap == "unknown" and klass(applied) == "full" and not override:
            findings.append(("REVIEW", "low",
                             f"{unmet_n} unmet hard requirement(s) recorded alongside "
                             f"{applied} tailoring. Whether the cap should fire depends "
                             f"on a years-minimum the recorded data doesn't capture — "
                             f"eyeball, not an error."))
        if klass(applied) != klass(want) and not override and not documented:
            if not (unmet_n >= 1 and applied == "light"):
                findings.append(("TIER", "medium",
                                 f"Score {score:.0f} maps to {want} tier, but "
                                 f"{applied} tailoring was applied."))
        if want == "skip" and applied in ("light", "full", "priority") \
                and not override and not documented:
            findings.append(("BELOW_FLOOR", "medium",
                             f"Score {score:.0f} is below the {cfg['light_tailoring_threshold']} "
                             f"skip floor, but {applied} tailoring was applied."))

    if not t_exact and score >= cfg["full_tailoring_threshold"]:
        findings.append(("TITLE", "low",
                         f"Title matches no configured tier, so its +8..+30 was a "
                         f"judgment call on a role that reached {want} tier."))

    drift, lost, live = rubric_drift(notes, row.get("surfaced_date")
                                     or row.get("applied_date"), row.get("stage"))
    corrected = score - lost if drift else score
    if drift:
        new_tier = expected_tier(corrected, cfg)
        changed = klass(new_tier) != klass(want)
        kind = "non-Atlanta hybrid (+18)" if lost == 18 else "NYC/NJ band (+12)"
        if live:
            findings.append((
                "RUBRIC_DRIFT", "high" if changed else "medium",
                f"Scored {score:.0f} before the {LOCATION_RULE_CHANGE} location rule "
                f"change. The {kind} it was given is worth 0 today, so the "
                f"current-rubric score is {corrected:.0f}"
                + (f", moving it from {want} to {new_tier} tier. Still in "
                   f"'surfaced' stage, so that tier is live." if changed
                   else ". Tier is unchanged.")))
        elif changed:
            findings.append((
                "RUBRIC_DRIFT", "low",
                f"Historical only ({(row.get('stage') or '').strip()}): scored "
                f"{score:.0f} under the retired {kind}; would be "
                f"{corrected:.0f} today."))

    return {
        "company": row.get("company", ""),
        "title": title,
        "url": row.get("url", ""),
        "date": row.get("surfaced_date") or row.get("applied_date") or "",
        "score": score,
        "lo": lo, "hi": hi,
        "required_kw": required_kw,
        "n_pinned": n_pinned, "n_total": len(pinned),
        "tier_name": tier_name,
        "applied_tier": applied, "expected_tier": want,
        "unmet": unmet_n, "override": override,
        "components": [
            ("Title match", t_rng, tier_name),
            ("Source quality", s_rng, s_label),
            ("Company bonuses", c_rng, "; ".join(c_parts)),
            ("Salary", sal_rng, sal_label),
            ("Location", loc_rng, loc_label),
            ("Freshness", fr_rng, fr_label),
            ("Staleness", st_rng, ""),
            ("Keyword overlap", KEYWORD_OVERLAP, "judgment — not recomputable"),
            ("Penalties", PENALTIES, "judgment — not recomputable"),
        ],
        "findings": findings,
    }


# --------------------------------------------------------------- validation

# Ground truth from cases already adjudicated by hand, recorded in the ledger
# and session log. The auditor is scored against these before its output is
# trusted -- same two-layer discipline as deflection-audit.
#
# All live rows here are NEGATIVE cases, and that is a property of the data
# rather than a choice: this audits the current recorded state, so any error
# already corrected by hand no longer exists to be caught. Chainguard is the
# clearest example -- it was mis-scored at 104/full, caught the same day, and
# the row now reads 94/light. Auditing it today correctly finds nothing.
#
# So the one known POSITIVE case is reconstructed below from what the
# correction note itself records about the pre-correction state, and run as a
# regression fixture. Without it every validation case would be a negative,
# and an auditor that never fires would score 4/4.
GROUND_TRUTH = [
    ("Cambium Learning Group", False,
     "2026-08-21: scored 91 (full tier) and correctly demoted to light by the cap."),
    ("Scandit", False,
     "2026-08-13: raw ~92 correctly overridden to light tier on the coding requirement."),
    ("Mercury", False,
     "2026-08-13: correctly hard-capped on the 7+ years fintech-ops requirement."),
    ("Framer", False,
     "2026-08-20: 2 unmet hard reqs and full tailoring, but user-directed. An "
     "accepted exception, not a miss -- the auditor must not flag this."),
]

# Two reconstructions of the Chainguard mis-score, quoted from its own
# correction note ("Originally scored 104 and fully tailored with a cover
# letter"). They differ only in whether the JD's requirements block had been
# captured, and together they bound what this audit can actually do.
FIXTURES = [
    ({
        "company": "Chainguard (pre-correction, requirements captured)",
        "title": "Senior Data Governance and Tooling Manager",
        "url": "https://job-boards.greenhouse.io/chainguard/jobs/4701660006",
        "fit_score": "104", "jd_coverage_pct": "73",
        "surfaced_date": "2026-08-10", "applied_date": "2026-08-10",
        "unmet_hard_reqs": "4",
        "notes": ("Full tailoring + cover letter. Remote US, $174K-$205K. JD requires "
                  "\"5+ years of experience in Data Governance or GTM Systems roles\"."),
    }, "HARDREQ_CAP", True,
     "The detector's regression test. When the requirements block IS captured, a "
     "104 with full tailoring against a 5+ years bar must be caught."),
    ({
        "company": "Chainguard (pre-correction, as actually recorded)",
        "title": "Senior Data Governance and Tooling Manager",
        "url": "https://job-boards.greenhouse.io/chainguard/jobs/4701660006",
        "fit_score": "104", "jd_coverage_pct": "73",
        "surfaced_date": "2026-08-10", "applied_date": "2026-08-10",
        "unmet_hard_reqs": "4",
        "notes": "Full tailoring + cover letter. Remote US, $174K-$205K.",
    }, "HARDREQ_CAP", False,
     "The honest limit. Chainguard's root cause was that Step 3's WebFetch never "
     "retrieved the requirements block, so the surfacing note had no years language "
     "to read. This audit downgrades it to REVIEW and cannot prove the error. Fixing "
     "that belongs upstream in what Step 3 captures, not here."),
]


def validate(results, matcher=None, idx=None, cfg=None):
    by_company = {}
    for r in results:
        by_company.setdefault(r["company"].strip().lower(), []).append(r)

    def fired(entries):
        return any(
            any(f[0] in ("HARDREQ_CAP", "TIER", "BELOW_FLOOR") for f in e["findings"])
            for e in entries
        )

    rows = []
    for company, should_flag, why in GROUND_TRUTH:
        matches = by_company.get(company.strip().lower(), [])
        flagged = fired(matches)
        if not matches:
            verdict, ok = "no row found", None
        elif flagged == should_flag:
            verdict, ok = "correct", True
        else:
            verdict, ok = ("missed" if should_flag else "false positive"), False
        rows.append({"company": company, "expected": should_flag, "flagged": flagged,
                     "verdict": verdict, "ok": ok, "why": why, "fixture": False})

    for raw, kind, should_flag, why in FIXTURES:
        res = audit_row(raw, matcher, idx, cfg)
        flagged = bool(res) and any(f[0] == kind for f in res["findings"])
        if flagged == should_flag:
            verdict, ok = "correct", True
        else:
            verdict, ok = ("missed" if should_flag else "false positive"), False
        rows.append({"company": raw["company"], "expected": should_flag, "flagged": flagged,
                     "verdict": verdict, "ok": ok, "why": why, "fixture": True})
    return rows


# ------------------------------------------------------------------- report

CSS = """
:root{--bg:#fff;--fg:#16181d;--mut:#5c6370;--line:#e3e6ea;--card:#fff;
--hi:#b42318;--hibg:#fef3f2;--med:#b54708;--medbg:#fffaeb;--low:#475467;--lowbg:#f8f9fa;
--ok:#067647;--okbg:#ecfdf3;--accent:#0b5cad}
:root:not([data-theme=light]){}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
--bg:#15171c;--fg:#e8eaed;--mut:#9aa2ae;--line:#2b2f38;--card:#1b1e25;
--hi:#ff9b8f;--hibg:#2d1614;--med:#f5c26b;--medbg:#2c2113;--low:#aab2c0;--lowbg:#20242c;
--ok:#6ee7a8;--okbg:#0f2a1c;--accent:#7cb8f5}}
:root[data-theme=dark]{--bg:#15171c;--fg:#e8eaed;--mut:#9aa2ae;--line:#2b2f38;--card:#1b1e25;
--hi:#ff9b8f;--hibg:#2d1614;--med:#f5c26b;--medbg:#2c2113;--low:#aab2c0;--lowbg:#20242c;
--ok:#6ee7a8;--okbg:#0f2a1c;--accent:#7cb8f5}
*{box-sizing:border-box}
body{margin:0;padding:2rem 1.25rem 4rem;background:var(--bg);color:var(--fg);
font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
.wrap{max-width:1020px;margin:0 auto}
h1{font-size:1.5rem;margin:0 0 .3rem}
h2{font-size:1.05rem;margin:2.2rem 0 .7rem;padding-bottom:.35rem;border-bottom:1px solid var(--line)}
.sub{color:var(--mut);margin:0 0 1.6rem;font-size:.92rem}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.7rem;margin:1.2rem 0 .4rem}
.tile{background:var(--card);border:1px solid var(--line);border-radius:9px;padding:.8rem .9rem}
.tile .n{font-size:1.5rem;font-weight:650;letter-spacing:-.01em}
.tile .l{color:var(--mut);font-size:.78rem;text-transform:uppercase;letter-spacing:.04em;margin-top:.15rem}
.card{background:var(--card);border:1px solid var(--line);border-left-width:3px;
border-radius:9px;padding:.9rem 1rem;margin-bottom:.75rem}
.card.high{border-left-color:var(--hi)}.card.medium{border-left-color:var(--med)}
.card.low{border-left-color:var(--low)}
.hd{display:flex;justify-content:space-between;gap:1rem;align-items:baseline;flex-wrap:wrap}
.co{font-weight:640}
.ti{color:var(--mut);font-size:.9rem}
.sc{font-variant-numeric:tabular-nums;font-weight:640;white-space:nowrap}
.tag{display:inline-block;font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;
padding:.12rem .45rem;border-radius:4px;margin-right:.35rem;font-weight:600}
.tag.high{background:var(--hibg);color:var(--hi)}.tag.medium{background:var(--medbg);color:var(--med)}
.tag.low{background:var(--lowbg);color:var(--low)}.tag.ok{background:var(--okbg);color:var(--ok)}
.f{margin:.55rem 0 0;font-size:.92rem}
.tblwrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;font-size:.87rem;min-width:520px}
th,td{text-align:left;padding:.4rem .6rem;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mut);font-weight:600;font-size:.76rem;text-transform:uppercase;letter-spacing:.04em}
td.num{font-variant-numeric:tabular-nums;white-space:nowrap}
details{margin-top:.55rem}
summary{cursor:pointer;color:var(--accent);font-size:.85rem}
a{color:var(--accent)}
.note{background:var(--lowbg);border:1px solid var(--line);border-radius:9px;
padding:.85rem 1rem;font-size:.9rem;color:var(--mut);margin:1rem 0}
.note strong{color:var(--fg)}
"""


def esc(s):
    return html.escape(str(s), quote=True)


def render(results, val_rows, meta):
    # The unmatched-title findings are one config gap wearing eleven hats.
    # Grouped below as a recommendation instead of eleven row cards.
    title_gaps = {}
    for r in results:
        if any(k == "TITLE" for k, _, _ in r["findings"]):
            title_gaps.setdefault(r["title"], []).append(r)

    def non_title(r):
        return [f for f in r["findings"] if f[0] != "TITLE"]

    flagged = [r for r in results if non_title(r)]
    high = [r for r in flagged if any(f[1] == "high" for f in non_title(r))]
    med = [r for r in flagged if r not in high and any(f[1] == "medium" for f in non_title(r))]
    low = [r for r in flagged if r not in high and r not in med]

    def sev(r):
        return "high" if r in high else ("medium" if r in med else "low")

    p = []
    p.append("<!doctype html><html><head><meta charset='utf-8'>")
    p.append("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    p.append("<title>Job Score Calibration Audit</title>")
    p.append(f"<style>{CSS}</style></head><body><div class='wrap'>")
    p.append("<h1>Job Score Calibration Audit</h1>")
    p.append(f"<p class='sub'>Recomputed {meta['n']} scored rows against the rubric in "
             f"<code>watchlist_companies.json</code> and <code>daily_task_prompt.md</code>. "
             f"Generated {esc(meta['when'])}{meta['since_label']}.</p>")

    p.append("<div class='tiles'>")
    for n, l in [(meta["n"], "rows audited"), (len(high), "act on these"),
                 (len(med), "worth a look"), (len(low), "notes"),
                 (len(title_gaps), "title config gaps"),
                 (meta["n"] - len(flagged), "clean")]:
        p.append(f"<div class='tile'><div class='n'>{n}</div><div class='l'>{esc(l)}</div></div>")
    p.append("</div>")

    # -- validation first: the auditor gets scored before its output is trusted
    p.append("<h2>Auditor accuracy against known cases</h2>")
    ok = sum(1 for v in val_rows if v["ok"] is True)
    tot = sum(1 for v in val_rows if v["ok"] is not None)
    p.append(f"<p class='sub'>{ok}/{tot} adjudicated cases called correctly. "
             f"These are scores already corrected or confirmed by hand; if the auditor "
             f"can't reproduce those calls, nothing below is trustworthy.</p>")
    p.append("<div class='tblwrap'><table><tr><th>Company</th><th>Should flag</th>"
             "<th>Did flag</th><th>Verdict</th><th>Case</th></tr>")
    for v in val_rows:
        cls = "ok" if v["ok"] else ("high" if v["ok"] is False else "low")
        p.append(f"<tr><td>{esc(v['company'])}</td>"
                 f"<td>{'yes' if v['expected'] else 'no'}</td>"
                 f"<td>{'yes' if v['flagged'] else 'no'}</td>"
                 f"<td><span class='tag {cls}'>{esc(v['verdict'])}</span></td>"
                 f"<td style='color:var(--mut)'>{esc(v['why'])}</td></tr>")
    p.append("</table></div>")

    p.append("<div class='note'><strong>What this can and cannot prove.</strong> "
             "Title tier, source quality, company bonuses, salary band, and freshness are "
             "recomputed exactly. Keyword overlap (0–30) and the two reach penalties (−10–0) "
             "are judgment and are <em>not</em> recomputable, so each row reports a legal "
             "envelope rather than a single right answer. A score outside its envelope is "
             "provably wrong. A score inside it is reported with the judgment it requires, "
             "for eyeballing — not as a finding.</div>")

    for label, group in [("Act on these", high),
                         ("Worth a look", med),
                         ("Notes", low)]:
        if not group:
            continue
        p.append(f"<h2>{esc(label)} ({len(group)})</h2>")
        for r in sorted(group, key=lambda x: x["date"], reverse=True):
            s = sev(r)
            p.append(f"<div class='card {s}'><div class='hd'><div>"
                     f"<span class='co'>{esc(r['company'])}</span> "
                     f"<span class='ti'>— {esc(r['title'])}</span></div>"
                     f"<div class='sc'>{r['score']:.0f} "
                     f"<span style='color:var(--mut);font-weight:400'>"
                     f"(legal {r['lo']:.0f}–{r['hi']:.0f})</span></div></div>")
            p.append(f"<div style='color:var(--mut);font-size:.82rem;margin-top:.2rem'>"
                     f"{esc(r['date'])} · {esc(r['tier_name'])} · "
                     f"{r['n_pinned']}/{r['n_total']} components pinned"
                     + (f" · <a href='{esc(r['url'])}'>posting</a>" if r["url"] else "")
                     + "</div>")
            for kind, s2, msg in non_title(r):
                p.append(f"<p class='f'><span class='tag {s2}'>{esc(kind)}</span>{esc(msg)}</p>")
            p.append("<details><summary>Component breakdown</summary>"
                     "<div class='tblwrap'><table><tr><th>Component</th><th>Range</th><th>Basis</th></tr>")
            for name, (a, b), basis in r["components"]:
                rng = f"{a:+d}" if a == b else f"{a:+d} … {b:+d}"
                p.append(f"<tr><td>{esc(name)}</td><td class='num'>{esc(rng)}</td>"
                         f"<td style='color:var(--mut)'>{esc(basis)}</td></tr>")
            p.append(f"<tr><td><strong>Recorded</strong></td><td class='num'>"
                     f"<strong>{r['score']:.0f}</strong></td>"
                     f"<td style='color:var(--mut)'>needs keyword overlap of "
                     f"{r['required_kw']:.0f}/30 with all else maxed</td></tr>")
            p.append("</table></div></details></div>")

    if title_gaps:
        p.append(f"<h2>Title config gaps ({len(title_gaps)})</h2>")
        p.append("<p class='sub'>These titles reached full or priority tier but match no "
                 "entry in <code>_title_scoring_tiers</code>, so their +8…+30 title component "
                 "was assigned by judgment each time rather than read from config. Adding a "
                 "matching title to the right tier makes them deterministic — and the matcher "
                 "is token-based, so one entry covers every word-order and seniority variant.</p>")
        p.append("<div class='tblwrap'><table><tr><th>Title</th><th>Seen</th>"
                 "<th>Scores</th><th>Companies</th></tr>")
        for t, rs in sorted(title_gaps.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            scores = ", ".join(f"{x['score']:.0f}" for x in sorted(rs, key=lambda x: -x["score"]))
            cos = ", ".join(sorted({x["company"] for x in rs}))
            p.append(f"<tr><td>{esc(t)}</td><td class='num'>{len(rs)}</td>"
                     f"<td class='num'>{esc(scores)}</td>"
                     f"<td style='color:var(--mut)'>{esc(cos)}</td></tr>")
        p.append("</table></div>")

    p.append("<h2>Coverage</h2>")
    p.append("<div class='tblwrap'><table><tr><th>Measure</th><th>Count</th><th>Meaning</th></tr>")
    for k, v, why in meta["coverage"]:
        p.append(f"<tr><td>{esc(k)}</td><td class='num'>{esc(v)}</td>"
                 f"<td style='color:var(--mut)'>{esc(why)}</td></tr>")
    p.append("</table></div>")
    p.append("</div></body></html>")
    return "".join(p)


def sweep_drift(cfg, apply=False):
    """Re-tier still-queued rows whose score came from a retired rubric rule.

    A rubric edit silently strands every score already recorded under it. The
    2026-08-02 location change is the case in hand, and nothing in the pipeline
    reconciles the queue afterward, so rows keep the tier the old rule bought
    them. This recomputes those scores and retires anything that no longer
    clears the skip floor.

    Only touches stage=surfaced rows with an exactly-pinned drift. Follows
    age_report.py's conventions: backup first, write via tmp + atomic replace,
    and never touch applied/rejected/closed rows. The original score is written
    into the note, so the correction is reversible by reading the row.
    """
    with open(OUTCOMES, newline="", encoding="utf-8") as f:
        raw = list(csv.reader(f))
    header, rows = raw[0], raw[1:]
    ci = {n: header.index(n) for n in
          ("company", "title", "fit_score", "stage", "surfaced_date",
           "applied_date", "notes")}

    planned = []
    for r in rows:
        if len(r) != len(header) or r[ci["stage"]].strip() != "surfaced":
            continue
        drift, lost, live = rubric_drift(
            r[ci["notes"]], r[ci["surfaced_date"]] or r[ci["applied_date"]],
            r[ci["stage"]])
        if not (drift and live):
            continue
        try:
            score = float(r[ci["fit_score"]])
        except ValueError:
            continue
        corrected = score - lost
        old_tier, new_tier = expected_tier(score, cfg), expected_tier(corrected, cfg)
        retire = new_tier == "skip"
        planned.append({"company": r[ci["company"]], "title": r[ci["title"]],
                        "score": score, "lost": lost, "corrected": corrected,
                        "old_tier": old_tier, "new_tier": new_tier, "retire": retire,
                        "row": r})

    if not apply:
        return planned, False

    stamp = date.today().isoformat()
    for p in planned:
        r = p["row"]
        r[ci["fit_score"]] = f"{p['corrected']:.0f}"
        if p["retire"]:
            r[ci["stage"]] = "expired"
        note = (f"[{stamp} drift sweep] score {p['score']:.0f} -> "
                f"{p['corrected']:.0f}: recorded before the {LOCATION_RULE_CHANGE} "
                f"location rule change and carried a +{p['lost']} bonus that rule "
                f"retired. Tier {p['old_tier']} -> {p['new_tier']}."
                + (" Retired to expired: no longer clears the skip floor."
                   if p["retire"] else ""))
        r[ci["notes"]] = (r[ci["notes"]] + "; " + note) if r[ci["notes"]].strip() else note

    shutil.copy2(OUTCOMES, OUTCOMES + ".predrift.bak")
    tmp = OUTCOMES + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    os.replace(tmp, OUTCOMES)
    return planned, True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="only audit rows surfaced on/after YYYY-MM-DD")
    ap.add_argument("--validate", action="store_true",
                    help="print the self-check against known cases and exit")
    ap.add_argument("--sweep-drift", action="store_true",
                    help="preview re-tiering of queued rows scored under a retired rule")
    ap.add_argument("--apply", action="store_true",
                    help="with --sweep-drift, write the corrections to outcomes.csv")
    args = ap.parse_args()

    watchlist = load_watchlist()
    cfg = watchlist["_scoring_config"]
    matcher = TitleMatcher(watchlist)
    idx = company_index(watchlist)

    with open(OUTCOMES) as f:
        rows = list(csv.DictReader(f))

    scoped = rows
    since_label = ""
    if args.since:
        scoped = [r for r in rows
                  if (r.get("surfaced_date") or r.get("applied_date") or "") >= args.since]
        since_label = f", scoped to rows since {args.since}"

    results = [x for x in (audit_row(r, matcher, idx, cfg) for r in scoped) if x]
    val_rows = validate([x for x in (audit_row(r, matcher, idx, cfg) for r in rows) if x],
                        matcher, idx, cfg)

    if args.sweep_drift:
        planned, written = sweep_drift(cfg, apply=args.apply)
        if not planned:
            print("no queued rows carry a retired-rule score.")
            return 0
        print(f"{'was':>4} {'-':>3} {'now':>4}  {'tier':<16} {'company':<18} title")
        print("-" * 92)
        for p in sorted(planned, key=lambda x: -x["score"]):
            ch = (f"{p['old_tier']} -> {p['new_tier']}"
                  if p["old_tier"] != p["new_tier"] else f"{p['old_tier']} (same)")
            print(f"{p['score']:>4.0f} {p['lost']:>3} {p['corrected']:>4.0f}  {ch:<16} "
                  f"{p['company'][:18]:<18} {p['title'][:36]}"
                  + ("   [RETIRE]" if p["retire"] else ""))
        n_ret = sum(1 for p in planned if p["retire"])
        print(f"\n{len(planned)} rows re-tiered, {n_ret} retired to expired.")
        if written:
            print(f"written; backup at {os.path.basename(OUTCOMES)}.predrift.bak")
        else:
            print("preview only; re-run with --apply to write")
        return 0

    if args.validate:
        print(f"Auditor self-check ({sum(1 for v in val_rows if v['ok'])}/"
              f"{sum(1 for v in val_rows if v['ok'] is not None)} correct)\n")
        for v in val_rows:
            mark = {True: "PASS", False: "FAIL", None: "SKIP"}[v["ok"]]
            print(f"  [{mark}] {v['company']:<26} expected_flag={v['expected']!s:<5} "
                  f"got={v['flagged']!s:<5} {v['verdict']}")
        return 0 if all(v["ok"] is not False for v in val_rows) else 1

    no_tier = sum(1 for r in results if r["applied_tier"] is None)
    unmatched = sum(1 for r in results if r["tier_name"] == "unmatched")
    skipped = len(scoped) - len(results)
    coverage = [
        ("Rows in outcomes.csv", len(rows), "full recorded history"),
        ("Rows audited", len(results), "had a numeric fit_score" +
         (f"; scoped to since {args.since}" if args.since else "")),
        ("Skipped, no score", skipped,
         "no fit_score recorded — nothing to recompute against"),
        ("Tier not parseable", no_tier,
         "notes were overwritten by a later outcome sweep, so the tailoring tier "
         "checks could not run on these rows; envelope checks still did"),
        ("Title matched no tier", unmatched,
         "title match was a judgment call, so its component is a range not a value"),
    ]

    meta = {
        "n": len(results),
        "when": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "since_label": since_label,
        "coverage": coverage,
    }

    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w") as f:
        f.write(render(results, val_rows, meta))

    flagged = [r for r in results if r["findings"]]
    kinds = Counter(k for r in results for k, _, _ in r["findings"])
    print(f"Audited {len(results)} scored rows; {len(flagged)} flagged.")
    for k, v in kinds.most_common():
        print(f"    {k:<14} {v}")

    # Per-row lines with dates, so a daily run can separate today's findings from
    # the standing backlog without opening the HTML. Counts alone can't do that.
    act = [r for r in flagged
           if any(s == "high" for _, s, _ in r["findings"])]
    look = [r for r in flagged if r not in act
            and any(s == "medium" for _, s, _ in r["findings"])]
    for label, group in (("act on", act), ("worth a look", look)):
        if not group:
            continue
        print(f"\n  {label}:")
        for r in sorted(group, key=lambda x: x["date"], reverse=True)[:12]:
            ks = ",".join(sorted({k for k, s, _ in r["findings"]
                                  if s in ("high", "medium")}))
            print(f"    {r['date'] or '(undated)':<11} {r['score']:>4.0f}  "
                  f"{r['company'][:22]:<22} {ks}")
        if len(group) > 12:
            print(f"    ... and {len(group) - 12} more, see the report")
    print(f"\nSelf-check: {sum(1 for v in val_rows if v['ok'])}/"
          f"{sum(1 for v in val_rows if v['ok'] is not None)} known cases called correctly.")
    print(f"Report: {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
