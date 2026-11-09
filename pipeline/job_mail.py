#!/usr/bin/env python3
"""Job-mail queries for both inboxes, and the shadow compare between them.

Usage:
    .venv/bin/python pipeline/job_mail.py                    # print today's queries
    .venv/bin/python pipeline/job_mail.py --compare          # after Step 1d-2's searches
    .venv/bin/python pipeline/job_mail.py --verdict          # the shadow week's result

Why this exists (added 2026-11-07). Aneesh applies from the job account
(`{{APPLY_ACCOUNT}}`), and six Gmail filters there forward job mail to the
`{{CONFIRM_ALIAS}}` alias on the main inbox, which was the only inbox the pipeline
could read. On 2026-11-07 the job account got its own Gmail connector, so the run can
read the mail where it lands. That fixes what forwarding can't: a sender no filter
names (the 2026-10-20 Google referral never forwarded), and LinkedIn Easy Apply
notices, which Step 0.5 skipped with the rest of linkedin.com. Measured that night,
forwarding already delivered every LinkedIn alert and ATS email one to one, so this
adds no discovery volume.

The six filters' terms live in job_mail_terms.json, because the job account has no
job label to search by: the filters were the only thing that knew which mail is job
mail. Every query is built from that file.

The switch runs in shadow first (`JOB_MAIL_SOURCE: "forwarded"` in local_config.json):
each run lists both inboxes, acts on the forwarded copy only, and `--compare` checks
the job account found every forwarded message. `--verdict` passes after 5 shadow runs
with nothing missed; then the source flips to `"job_account"`. The forwarding filters
stay on either way, because the inbox skill and the sent-asks watcher still read the
forwarded copies.

`--compare` reads the current run's transcript (the newest .jsonl in the project's
transcript dir, its helpers' logs, and its spilled tool results). Each listing record
names its inbox in `viewUrl` (`authuser=<address>`), which is how the two sides are
told apart. A forwarded copy keeps the original `To:`, so a main-inbox record counts
as forwarded only when it is addressed to the job account.

A twin is the same sender within 15 minutes with the same subject. The run lists the
forwarded LinkedIn alerts with the metadata-only view, which carries no subject, so a
listed message takes its subject from the run's body fetch of the same id; one no helper
fetched pairs on sender and time alone, and the result counts those. Without this the
2026-11-09 run matched 0 of 70 LinkedIn alerts that were all there.
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import sys
from urllib.parse import parse_qs, urlparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.path.join(SCRIPT_DIR, "jobs")
TERMS = os.path.join(SCRIPT_DIR, "job_mail_terms.json")
LOCAL_CONFIG = os.path.join(SCRIPT_DIR, "local_config.json")

CLASSES = ("receipts", "easy_apply", "linkedin_alerts")
TWIN_TOLERANCE = dt.timedelta(minutes=15)   # a forwarded copy keeps the Date header
# The searches run up to a couple of hours before --compare (Step 0.5 early, Step 1d-2
# later), so the oldest few hours of each window may hold mail one listing caught and
# the other didn't. Those hours are left out; the next run's window covers them.
BOUNDARY_MARGIN = dt.timedelta(hours=3)
SHADOW_RUNS_TO_PASS = 5
LAPSE_QUERY = "newer_than:2d"


# ── Config ───────────────────────────────────────────────────────────────────

def load_terms(path: str = TERMS) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_config(path: str = LOCAL_CONFIG) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


SOURCES = ("forwarded", "job_account")


def source(cfg: dict) -> str:
    """Which copy the run acts on: "forwarded" (the default) or "job_account". Any
    other value stops the run here rather than quietly reading the wrong inbox."""
    value = cfg.get("JOB_MAIL_SOURCE") or "forwarded"
    if value not in SOURCES:
        raise ValueError(f"JOB_MAIL_SOURCE in local_config.json is {value!r}; "
                         f"use one of {', '.join(SOURCES)}")
    return value


def source_account(cfg: dict) -> str | None:
    """The inbox whose records the run acts on, or None when the config predates the
    switch (then nothing is filtered by inbox)."""
    key = "APPLY_ACCOUNT" if source(cfg) == "job_account" else "MAIN_ACCOUNT"
    addr = cfg.get(key)
    return addr.lower() if addr else None


def account_of(rec: dict, parent: dict | None = None) -> str | None:
    """The inbox a Gmail-MCP record came from, read from its viewUrl's authuser."""
    for d in (rec, parent or {}):
        url = d.get("viewUrl") if isinstance(d, dict) else None
        if url:
            user = parse_qs(urlparse(url).query).get("authuser")
            if user:
                return user[0].lower()
    return None


# ── Queries ──────────────────────────────────────────────────────────────────

def _or(items) -> str:
    return " OR ".join(f'"{t}"' if " " in t else t for t in items)


def queries(terms: dict, window_days: int) -> dict:
    """Every search the run makes, for both inboxes. The forwarded ones keep the
    {{CONFIRM_ALIAS}} placeholder; the run resolves it from local_config.json."""
    indeed = " ".join(f"-from:{s}" for s in terms["indeed_alert_senders"])
    app_subjects = _or(terms["linkedin_application_subjects"])
    app_sender = terms["linkedin_application_sender"]
    li = terms["linkedin_alert_domain"]
    fwd = "deliveredto:{{CONFIRM_ALIAS}}"
    return {
        "lapse_check": {"job_account": LAPSE_QUERY},
        "receipts": {
            "forwarded": f"{fwd} -from:{li} {indeed} newer_than:3d",
            "job_account": (f"(from:({_or(terms['receipt_senders'])}) OR "
                            f"subject:({_or(terms['receipt_subjects'])})) "
                            f"-from:{li} {indeed} -in:sent newer_than:3d"),
        },
        "easy_apply": {
            "forwarded": f"{fwd} from:{app_sender} subject:({app_subjects}) newer_than:3d",
            "job_account": f"from:{app_sender} subject:({app_subjects}) -in:sent newer_than:3d",
        },
        "linkedin_alerts": {
            "forwarded": f"{fwd} from:{li} newer_than:{window_days}d",
            "job_account": f"from:{li} -in:sent newer_than:{window_days}d",
        },
    }


# ── Classification (the shadow compare's stand-in for Gmail's matching) ──────

def _sender_matches(sender: str, term: str) -> bool:
    if "@" in term:
        return sender == term
    return sender.endswith("@" + term) or sender.endswith("." + term)


def classify(sender: str, subject: str, terms: dict) -> str | None:
    """Which search a message belongs to, or None when no term names it."""
    s, subj = (sender or "").lower(), (subject or "").lower()
    if _sender_matches(s, terms["linkedin_alert_domain"]):
        if s == terms["linkedin_application_sender"] and any(
                p in subj for p in terms["linkedin_application_subjects"]):
            return "easy_apply"
        return "linkedin_alerts"
    if s in terms["indeed_alert_senders"]:
        return "indeed_alerts"
    if any(_sender_matches(s, t) for t in terms["receipt_senders"]) or any(
            p in subj for p in terms["receipt_subjects"]):
        return "receipts"
    return None


# ── Transcript reading ───────────────────────────────────────────────────────

def default_transcript_dir() -> str:
    root = os.path.dirname(SCRIPT_DIR)
    slug = re.sub(r"[^A-Za-z0-9]", "-", root)
    return os.path.join(os.path.expanduser("~"), ".claude", "projects", slug)


def _parse_date(s: str) -> dt.datetime | None:
    try:
        d = dt.datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def _message(m: dict, parent: dict | None) -> dict | None:
    if not isinstance(m, dict) or not m.get("sender"):
        return None
    to = [a.lower() for a in (m.get("toRecipients") or []) + (m.get("ccRecipients") or [])]
    return {
        "id": m.get("id") or "",
        "account": account_of(m, parent),
        "sender": m["sender"].lower(),
        "subject": m.get("subject") or "",
        "date": _parse_date(m.get("date") or ""),
        "to": to,
        "truncated": False,
    }


def records_from_text(text: str) -> list[dict]:
    """Every message inside one tool result: a search listing, a thread, or a message."""
    stripped = text.lstrip()
    if not stripped.startswith(("{", "[")):
        return []
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return []
    out = []
    for item in data if isinstance(data, list) else [data]:
        if not isinstance(item, dict):
            continue
        if "threads" in item:
            for th in item.get("threads") or []:
                for m in th.get("messages") or []:
                    r = _message(m, th)
                    if r:
                        # A listing with more pages only reached its newest messages.
                        r["truncated"] = bool(item.get("nextPageToken"))
                    out.append(r)
        elif "messages" in item:
            for m in item.get("messages") or []:
                out.append(_message(m, item))
        else:
            out.append(_message(item, None))
    return [r for r in out if r and r["date"]]


def _tool_result_texts(path: str):
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if "authuser" not in line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = (rec.get("message") or {}).get("content", [])
            if isinstance(content, str):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                inner = block.get("content", "")
                if isinstance(inner, list):
                    inner = "\n".join(b.get("text", "") for b in inner if isinstance(b, dict))
                yield inner


def load_session(session_path: str) -> list[dict]:
    """Records from one run: its transcript, its helpers' logs, its spilled results."""
    sdir = session_path[:-len(".jsonl")]
    paths = [session_path] + sorted(glob.glob(os.path.join(sdir, "subagents", "*.jsonl")))
    records = []
    for p in paths:
        for text in _tool_result_texts(p):
            records += records_from_text(text)
    for p in sorted(glob.glob(os.path.join(sdir, "tool-results", "*"))):
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                records += records_from_text(f.read())
    return records


def newest_session(tdir: str) -> str | None:
    paths = glob.glob(os.path.join(tdir, "*.jsonl"))
    return max(paths, key=os.path.getmtime) if paths else None


# ── Compare ──────────────────────────────────────────────────────────────────

def _dedupe(records: list[dict]) -> list[dict]:
    """One record per message. The first copy wins, but a blank subject is filled from a
    later copy of the same id: the run lists the forwarded LinkedIn alerts with the
    metadata-only view, which carries no subject, and its helpers' body fetches do."""
    seen, out = {}, []
    for r in records:
        key = r["id"] or (r["sender"], r["subject"], r["date"])
        if key not in seen:
            seen[key] = dict(r)
            out.append(seen[key])
        elif not seen[key]["subject"] and r["subject"]:
            seen[key]["subject"] = r["subject"]
    return out


def _norm_subject(s: str) -> str:
    return " ".join(s.lower().split())


def _twin(f: dict, pool: list[dict], by_subject: bool) -> dict | None:
    """The closest record in `pool` from f's sender within TWIN_TOLERANCE. With
    `by_subject`, both subjects must be known and equal; without it, only a pair where
    one side has no subject qualifies, so a known different subject never matches."""
    fs = _norm_subject(f["subject"])

    def fits(j):
        js = _norm_subject(j["subject"])
        both = bool(fs and js)
        if by_subject != both or (both and fs != js):
            return False
        return j["sender"] == f["sender"] and abs(j["date"] - f["date"]) <= TWIN_TOLERANCE

    return min((j for j in pool if fits(j)), key=lambda j: abs(j["date"] - f["date"]),
               default=None)


def _brief(r: dict) -> dict:
    return {"date": r["date"].isoformat(), "sender": r["sender"], "subject": r["subject"]}


def compare(records: list[dict], cfg: dict, terms: dict, windows: dict,
            now: dt.datetime | None = None) -> dict:
    """`windows` maps each class to its search window in days (receipts and easy_apply
    use 3, linkedin_alerts the linkedin_window.py value). Mail older than now minus the
    window plus BOUNDARY_MARGIN is left out, and so is mail older than a side's oldest
    message when that message sits on a page that had more pages after it (the run
    stopped paging, so the side never saw further back)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    main, job = (cfg.get("MAIN_ACCOUNT") or "").lower(), (cfg.get("APPLY_ACCOUNT") or "").lower()
    if not main or not job:
        raise ValueError("local_config.json needs MAIN_ACCOUNT and APPLY_ACCOUNT")
    forwarded = _dedupe([r for r in records if r["account"] == main and job in r["to"]])
    direct = _dedupe([r for r in records if r["account"] == job and r["sender"] != job])

    by_class = {c: {"forwarded": [], "job_account": []} for c in CLASSES}
    ignored = []
    for side, recs in (("forwarded", forwarded), ("job_account", direct)):
        for r in recs:
            c = classify(r["sender"], r["subject"], terms)
            if c in by_class:
                by_class[c][side].append(r)
            elif side == "forwarded" and c is None:
                ignored.append(r)

    result = {"classes": {}, "missed_total": 0, "extras_total": 0}
    for c in CLASSES:
        fwd, jac = by_class[c]["forwarded"], by_class[c]["job_account"]
        edge = now - dt.timedelta(days=windows[c]) + BOUNDARY_MARGIN
        for side in (fwd, jac):
            # Only the oldest message's page decides: a listing paged to the end has
            # tokens on its earlier pages and none on its last.
            oldest = min(side, key=lambda r: r["date"], default=None)
            if oldest and oldest.get("truncated"):
                edge = max(edge, oldest["date"])
        unmatched = list(jac)
        inside = sorted((f for f in fwd if f["date"] >= edge), key=lambda r: r["date"])
        outside = len(fwd) - len(inside)
        # Subject twins first, so a message with no subject can't take the copy a
        # subject match needs. What's left pairs on sender and time alone, which shows a
        # copy arrived at that second but not that it's the same alert.
        left = []
        for f in inside:
            twin = _twin(f, unmatched, by_subject=True)
            if twin:
                unmatched.remove(twin)
            else:
                left.append(f)
        by_time, missed = 0, []
        for f in left:
            twin = _twin(f, unmatched, by_subject=False)
            if twin:
                unmatched.remove(twin)
                by_time += 1
            else:
                missed.append(_brief(f))
        extras = [_brief(j) for j in unmatched if j["date"] >= edge]
        result["classes"][c] = {
            "forwarded": len(fwd), "job_account": len(jac),
            "matched": len(inside) - len(missed), "matched_by_time": by_time,
            "outside_overlap": outside, "missed": missed, "only_in_job_account": extras,
        }
        result["missed_total"] += len(missed)
        result["extras_total"] += len(extras)
    result["forwarded_not_job_mail"] = sorted({r["sender"].split("@")[-1] for r in ignored})
    result["job_account_silent"] = bool(forwarded) and not direct
    return result


def summary_lines(result: dict) -> list[str]:
    lines = []
    for c in CLASSES:
        r = result["classes"][c]
        by_time = (f" ({r['matched_by_time']} on sender and time alone)"
                   if r["matched_by_time"] else "")
        lines.append(f"SHADOW {c}: {r['forwarded']} forwarded, {r['job_account']} in the job "
                     f"account, {r['matched']} matched{by_time}, {len(r['missed'])} missed, "
                     f"{len(r['only_in_job_account'])} only in the job account")
        # A silent job account makes every forwarded message a "miss"; the one line
        # below says what happened instead of a hundred alerts on a Monday.
        if result["job_account_silent"]:
            continue
        for m in r["missed"]:
            lines.append(f"SHADOW MISS {c}: {m['date'][:16]} {m['sender']} | {m['subject']}")
    if result["job_account_silent"]:
        lines.append("SHADOW: THE JOB ACCOUNT RETURNED NOTHING while forwarded mail exists. "
                     "Either its searches were skipped or the connector lapsed; say so in "
                     "the digest's alerts.")
    if result["forwarded_not_job_mail"]:
        lines.append("forwarded but matching no job term (not compared): "
                     + ", ".join(result["forwarded_not_job_mail"]))
    return lines


def verdict(out_dir: str, runs: int = SHADOW_RUNS_TO_PASS) -> tuple[bool, list[str]]:
    """PASS when the last `runs` shadow runs that read any forwarded mail missed nothing.
    A run that read no forwarded mail at all (a skipped step, the wrong session read)
    proves nothing, so it is listed and not counted."""
    lines, counted = [], []
    for p in sorted(glob.glob(os.path.join(out_dir, "mail_shadow_*.json"))):
        with open(p, encoding="utf-8") as f:
            r = json.load(f)
        day = os.path.basename(p)[12:22]
        if not sum(r["classes"][c]["forwarded"] for c in CLASSES):
            lines.append(f"{day}: no forwarded mail read; not counted")
            continue
        counted.append(r)
        per = ", ".join(f"{c} {r['classes'][c]['matched']}/{r['classes'][c]['forwarded']}"
                        for c in CLASSES)
        lines.append(f"{day}: matched {per}; missed {r['missed_total']}, only in job "
                     f"account {r['extras_total']}"
                     f"{'; JOB ACCOUNT SILENT' if r['job_account_silent'] else ''}")
    last = counted[-runs:]
    missed = sum(r["missed_total"] for r in last)
    silent = sum(1 for r in last if r["job_account_silent"])
    ok = len(last) >= runs and missed == 0 and silent == 0
    lines.append(f"VERDICT: {'PASS' if ok else 'NOT YET'} ({len(last)} of {runs} counted "
                 f"shadow runs, {missed} missed, {silent} silent)")
    return ok, lines


# ── CLI ──────────────────────────────────────────────────────────────────────

def query_lines(window_days: int, cfg: dict | None = None) -> list[str]:
    cfg = load_config() if cfg is None else cfg
    q = queries(load_terms(), window_days)
    lines = [f"mail source    : {source(cfg)} (act on this copy; list the other in shadow)"]
    lines.append(f"lapse check    : job account  {q['lapse_check']['job_account']}")
    for step, key in (("Step 0.5", "receipts"), ("Step 0.5 EA", "easy_apply"),
                      ("Step 1d-2", "linkedin_alerts")):
        lines.append(f"{step:<15}: forwarded    {q[key]['forwarded']}")
        lines.append(f"{'':<15}  job account  {q[key]['job_account']}")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--compare", action="store_true",
                      help="compare this run's listings of both inboxes")
    mode.add_argument("--verdict", action="store_true",
                      help="pass or not over the last 5 shadow runs")
    ap.add_argument("--session", help="transcript .jsonl to read; default the newest")
    ap.add_argument("--transcript-dir", help="override the derived ~/.claude/projects/<slug>")
    ap.add_argument("--date", help="run date for the output name; default today")
    ap.add_argument("--out-dir", default=JOBS_DIR)
    args = ap.parse_args()

    if args.verdict:
        ok, lines = verdict(args.out_dir)
        print("\n".join(lines))
        return 0

    if args.compare:
        cfg = load_config()
        session = args.session or newest_session(args.transcript_dir or default_transcript_dir())
        if not session:
            print("no transcript found; pass --session", file=sys.stderr)
            return 2
        import linkedin_window as LW
        li_window = LW.compute_window(dt.date.today())["window"]
        windows = {"receipts": 3, "easy_apply": 3, "linkedin_alerts": li_window}
        result = compare(load_session(session), cfg, load_terms(), windows)
        today = args.date or dt.date.today().isoformat()
        result.update({"date": today, "source": source(cfg),
                       "session": os.path.basename(session)})
        os.makedirs(args.out_dir, exist_ok=True)
        path = os.path.join(args.out_dir, f"mail_shadow_{today}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
            f.write("\n")
        print(f"session read   : {os.path.basename(session)}")
        print("\n".join(summary_lines(result)))
        print(f"wrote {os.path.relpath(path, os.path.dirname(SCRIPT_DIR))}")
        return 0

    import linkedin_window as LW
    w = LW.compute_window(dt.date.today())
    print(f"window         : newer_than:{w['window']}d ({w['note']})")
    print("\n".join(query_lines(w["window"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
