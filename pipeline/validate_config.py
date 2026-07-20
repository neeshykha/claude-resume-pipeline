#!/usr/bin/env python3
"""Config validation for the daily pipeline (syntax + schema sanity).

Hand-edits to structured JSON have silently broken daily feeders at least three
times (trailing commas in enrollment_candidates.json twice, mis-nested entries
in seen_jobs.json once). update_tracking.py protects seen_jobs.json writes;
this script is the equivalent guard for READS of all three files, run before
anything consumes them.

Usage:
    .venv/bin/python pipeline/validate_config.py            # validate all three files
    .venv/bin/python pipeline/validate_config.py --quiet    # only print problems

Exit codes: 0 = clean (warnings allowed), 1 = errors found, 2 = a file failed
to parse at all (syntax error; message includes line/column).

Also imported by poll_ats.py, which calls validate_watchlist() at startup and
refuses to poll against a malformed watchlist.

Run this after ANY hand edit to watchlist_companies.json or
enrollment_candidates.json, and at the start of every daily pipeline pass
(daily_task_prompt.md Step 1).
"""
import argparse
import json
import os
import sys
from datetime import date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_PATH = os.path.join(SCRIPT_DIR, "watchlist_companies.json")
QUEUE_PATH = os.path.join(SCRIPT_DIR, "enrollment_candidates.json")
SEEN_JOBS_PATH = os.path.join(SCRIPT_DIR, "jobs", "seen_jobs.json")

SUPPORTED_ATS = {"greenhouse", "greenhouse_eu", "ashby", "lever", "workday", "smartrecruiters"}
VALID_BANDS = {"1-50", "51-200", "201-500", "501-2000", "2000+"}
QUEUE_BUCKETS = ("pending", "enrolled", "rejected")


def _is_iso_date(s) -> bool:
    try:
        date.fromisoformat(s)
        return True
    except (TypeError, ValueError):
        return False


def validate_watchlist(data) -> tuple[list, list]:
    """Return (errors, warnings) for a parsed watchlist_companies.json."""
    errors, warnings = [], []

    for key in ("companies", "_scoring_config", "_title_scoring_tiers",
                "_poller_config", "_websearch_sources", "_endpoints"):
        if key not in data:
            errors.append(f"watchlist: missing top-level key '{key}'")
    if errors:
        return errors, warnings  # structure too broken for deeper checks

    sc = data["_scoring_config"]
    for key in ("salary_floor_usd", "company_cap_max_applied_pending",
                "company_cap_threshold", "full_tailoring_threshold",
                "light_tailoring_threshold"):
        if not isinstance(sc.get(key), (int, float)):
            errors.append(f"watchlist: _scoring_config.{key} missing or not a number")
    scb = sc.get("small_company_bonus", {})
    if not isinstance(scb, dict) or not set(scb) == VALID_BANDS:
        errors.append(f"watchlist: _scoring_config.small_company_bonus must map exactly the bands {sorted(VALID_BANDS)}")

    tiers = data["_title_scoring_tiers"]
    for tier in ("tier1_true_match", "tier2_strong_overlap",
                 "tier3_reasonable_stretch", "tier4_weak_stretch"):
        spec = tiers.get(tier)
        if not isinstance(spec, dict):
            errors.append(f"watchlist: _title_scoring_tiers.{tier} missing")
            continue
        if not isinstance(spec.get("title_match_score"), (int, float)):
            errors.append(f"watchlist: {tier}.title_match_score missing or not a number")
        titles = spec.get("titles")
        if not isinstance(titles, list) or not titles or not all(isinstance(t, str) and t.strip() for t in titles):
            errors.append(f"watchlist: {tier}.titles must be a non-empty list of strings")
    wc = tiers.get("tier2b_ai_wildcard", {})
    for key in ("signal_words", "exclude_if_contains", "explicit_titles"):
        if not isinstance(wc.get(key), list) or not wc.get(key):
            errors.append(f"watchlist: tier2b_ai_wildcard.{key} must be a non-empty list")

    pc = data["_poller_config"]
    supp = pc.get("supplemental_exact_titles", {})
    if not isinstance(supp.get("title_match_prescore"), (int, float)):
        errors.append("watchlist: _poller_config.supplemental_exact_titles.title_match_prescore missing or not a number")
    if not isinstance(supp.get("titles"), list) or not supp.get("titles"):
        errors.append("watchlist: _poller_config.supplemental_exact_titles.titles must be a non-empty list")
    frag = pc.get("borderline_fragments", {})
    if not isinstance(frag.get("min_fragments"), int):
        errors.append("watchlist: _poller_config.borderline_fragments.min_fragments missing or not an int")
    if not isinstance(frag.get("fragments"), list) or not frag.get("fragments"):
        errors.append("watchlist: _poller_config.borderline_fragments.fragments must be a non-empty list")
    risky = pc.get("jd_verification_required_titles", {})
    if not isinstance(risky.get("titles"), list):
        errors.append("watchlist: _poller_config.jd_verification_required_titles.titles must be a list")
    fm = pc.get("function_mismatch_titles")
    if fm is not None:
        if not isinstance(fm.get("titles"), list) or not fm.get("titles"):
            errors.append("watchlist: _poller_config.function_mismatch_titles.titles must be a non-empty list")
        tier_names = set(data.get("_title_scoring_tiers", {}).keys())
        protected = fm.get("protected_tiers", [])
        if not isinstance(protected, list):
            errors.append("watchlist: _poller_config.function_mismatch_titles.protected_tiers must be a list")
        else:
            for t in protected:
                if t not in tier_names:
                    errors.append(f"watchlist: function_mismatch_titles.protected_tiers names unknown tier '{t}'")

    for name, url in data["_endpoints"].items():
        if not isinstance(url, str) or "{" not in url:
            errors.append(f"watchlist: _endpoints.{name} doesn't look like a URL template")

    sources = data["_websearch_sources"].get("sources", [])
    if not isinstance(sources, list) or not sources:
        errors.append("watchlist: _websearch_sources.sources must be a non-empty list")
    else:
        for i, src in enumerate(sources):
            label = src.get("name", f"#{i}")
            if src.get("status") not in ("active", "disabled"):
                errors.append(f"watchlist: _websearch_sources '{label}': status must be 'active' or 'disabled'")
            if src.get("status") == "active" and not src.get("query"):
                errors.append(f"watchlist: _websearch_sources '{label}': active source has no query")

    companies = data["companies"]
    if not isinstance(companies, list) or not companies:
        errors.append("watchlist: companies must be a non-empty list")
        return errors, warnings
    seen_slugs = {}
    for i, c in enumerate(companies):
        label = c.get("name") or f"companies[{i}]"
        for key in ("name", "ats", "slug"):
            if not c.get(key):
                errors.append(f"watchlist: {label}: missing '{key}'")
        ats = c.get("ats")
        if ats and ats not in SUPPORTED_ATS:
            errors.append(f"watchlist: {label}: unsupported ats '{ats}' (must be one of {sorted(SUPPORTED_ATS)})")
        if ats == "workday":
            for key in ("wd_host", "wd_tenant", "wd_site"):
                if not c.get(key):
                    errors.append(f"watchlist: {label}: workday entry missing '{key}'")
        band = c.get("headcount_band")
        if band is not None and band not in VALID_BANDS:
            errors.append(f"watchlist: {label}: headcount_band '{band}' not in {sorted(VALID_BANDS)} (or null)")
        if "score_bonus" in c and not isinstance(c["score_bonus"], (int, float)):
            errors.append(f"watchlist: {label}: score_bonus must be a number")
        if "recheck_after" in c and not _is_iso_date(c["recheck_after"]):
            errors.append(f"watchlist: {label}: recheck_after '{c['recheck_after']}' is not YYYY-MM-DD")
        key = (ats, (c.get("slug") or "").lower())
        if key in seen_slugs and c.get("slug"):
            warnings.append(f"watchlist: duplicate board {key} ({seen_slugs[key]} and {label}) — poller will poll it twice")
        seen_slugs[key] = label
    return errors, warnings


def validate_enrollment(data) -> tuple[list, list]:
    """Return (errors, warnings) for a parsed enrollment_candidates.json."""
    errors, warnings = [], []
    for bucket in QUEUE_BUCKETS:
        entries = data.get(bucket)
        if not isinstance(entries, list):
            errors.append(f"enrollment: '{bucket}' missing or not a list")
            continue
        for i, e in enumerate(entries):
            if not isinstance(e, dict):
                errors.append(f"enrollment: {bucket}[{i}] is not an object")
                continue
            label = e.get("name") or f"{bucket}[{i}]"
            if not e.get("name"):
                errors.append(f"enrollment: {bucket}[{i}]: missing 'name'")
            ats = e.get("ats")
            if ats is not None and ats not in SUPPORTED_ATS | {"workable"}:
                errors.append(f"enrollment: {label}: unknown ats '{ats}'")
            if bucket == "pending" and not e.get("needs_ats_resolution") and not (ats and e.get("slug")):
                warnings.append(f"enrollment: pending '{label}' has no ats/slug and no needs_ats_resolution flag — enrollment step can't act on it")
            if bucket == "rejected" and not e.get("reason"):
                warnings.append(f"enrollment: rejected '{label}' has no reason — it may get re-evaluated")
    return errors, warnings


def validate_seen_jobs(data) -> tuple[list, list]:
    """Return (errors, warnings) for a parsed seen_jobs.json."""
    errors, warnings = [], []
    jobs = data.get("jobs")
    if not isinstance(jobs, dict):
        errors.append("seen_jobs: missing top-level 'jobs' object")
        return errors, warnings
    strays = [k for k in data if k not in ("jobs", "schema_version", "description")]
    if strays:
        # The 2026-06-30 corruption class: entries written outside "jobs" break dedup.
        errors.append(f"seen_jobs: stray top-level keys {strays} — entries outside the 'jobs' object are invisible to dedup")
    for key, entry in jobs.items():
        if not isinstance(entry, dict):
            errors.append(f"seen_jobs: entry '{key}' is not an object")
            continue
        fs = entry.get("first_seen_date")
        if fs and not _is_iso_date(fs):
            errors.append(f"seen_jobs: entry '{key}': first_seen_date '{fs}' is not YYYY-MM-DD (breaks the dedup window)")
    return errors, warnings


def _load(path):
    """Parse a JSON file. Returns (data, error_string)."""
    if not os.path.exists(path):
        return None, f"{os.path.basename(path)}: file not found at {path}"
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except json.JSONDecodeError as e:
        return None, (f"{os.path.basename(path)}: JSON SYNTAX ERROR at line {e.lineno}, "
                      f"column {e.colno}: {e.msg} (this is the trailing-comma / hand-edit bug class)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate pipeline config files")
    ap.add_argument("--quiet", action="store_true", help="only print problems")
    args = ap.parse_args()

    targets = [
        (WATCHLIST_PATH, validate_watchlist),
        (QUEUE_PATH, validate_enrollment),
        (SEEN_JOBS_PATH, validate_seen_jobs),
    ]
    any_errors = False
    syntax_failure = False
    for path, checker in targets:
        name = os.path.basename(path)
        data, parse_err = _load(path)
        if parse_err:
            print(f"ERROR  {parse_err}")
            any_errors = True
            syntax_failure = True
            continue
        errors, warnings = checker(data)
        for e in errors:
            print(f"ERROR  {e}")
        for w in warnings:
            print(f"WARN   {w}")
        if errors:
            any_errors = True
        elif not args.quiet:
            suffix = f" ({len(warnings)} warning{'s' if len(warnings) != 1 else ''})" if warnings else ""
            print(f"OK     {name}{suffix}")

    if syntax_failure:
        return 2
    return 1 if any_errors else 0


if __name__ == "__main__":
    sys.exit(main())
