#!/usr/bin/env python3
"""Weekly work harvest, step one: boil a week of Claude Code transcripts down to a
small digest a model can read in one pass and draft resume bullets from.

    .venv/bin/python pipeline/harvest_work_log.py
    .venv/bin/python pipeline/harvest_work_log.py --dry-run
    .venv/bin/python pipeline/harvest_work_log.py --remote worker

Reads ~/.claude/projects/*/*.jsonl modified in the last --days days and keeps only
two things per session: the user's own typed messages, and the final assistant
text of each turn (the end-of-turn summary). Tool calls, tool results, thinking,
and attachments are dropped, which is what takes a 5 MB transcript to a few KB.

Skipped as noise, and counted in the digest header instead of excerpted:
  - scheduled-task runs (first message is a <scheduled-task> wrapper). Their
    names and run counts go in an "automation census" line, because the fleet
    itself is resume evidence even when no single run is.
  - headless SDK runs (entrypoint sdk-*), which are launchd jobs, not work.
  - scratch and temp project dirs (/private/tmp, /private/var, scratchpad).
  - ModelBaseline runs.
  - daily job-pipeline sessions, even when started by hand.
  - worktree sessions, only when SKIP_WORKTREES is True. It is False: a worktree
    transcript is its own session, not a copy of one in the main checkout.

--remote HOST runs this same file on HOST over ssh (source fed on stdin, so
nothing is installed or written there) and merges its sessions into the digest,
tagged with the host name. Needs key-based ssh that works with BatchMode.

The digest goes to work_log/ in the MAIN checkout, which is gitignored: these
transcripts carry customer and CRM data and this repo is public. Stdlib only,
and Python 3.9-compatible because the remote side runs the system python3.

Always exits 0 and prints one line, so a scheduled run never stalls on it.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime

PROJECTS_DIR = os.path.expanduser("~/.claude/projects")
OUT_DIR = os.path.expanduser("~/Documents/resume_project/work_log")
SKIP_WORKTREES = False

SKIP_DIR_MARKERS = ("-private-tmp", "-private-var", "scratchpad", "ModelBaseline")
PIPELINE_TITLES = ("daily job pipeline", "daily-job-pipeline")
MSG_CAP = 700          # chars kept per user message
SUMMARY_CAP = 1400     # chars kept per end-of-turn assistant summary
SUMMARIES_KEPT = 3     # last N turn summaries per session
MSGS_KEPT = 25         # last N user messages per session

TAG_BLOCK = re.compile(
    r"<(system-reminder|local-command-stdout|local-command-stderr|command-message|"
    r"command-args|task-notification)\b[^>]*>.*?</\1>", re.S)
CHANNEL_TAG = re.compile(r"</?channel\b[^>]*>")
NOISE_PREFIXES = ("<command-name>", "Caveat:", "[Request interrupted")


def clean_user_text(text):
    text = TAG_BLOCK.sub("", text)
    text = CHANNEL_TAG.sub("", text)
    return text.strip()


def text_of(content):
    """Plain text of a message content field; tool_use/tool_result/thinking dropped."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def is_tool_result(content):
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


def clip(s, n):
    s = s.strip()
    return s if len(s) <= n else s[:n].rstrip() + " [...]"


def parse_ts(ts):
    try:
        return datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").timestamp()
    except (TypeError, ValueError):
        return None


def read_session(path, cutoff):
    """One transcript -> dict, or a skip reason string."""
    project = os.path.basename(os.path.dirname(path))
    if any(m in project for m in SKIP_DIR_MARKERS):
        return "scratch"
    if SKIP_WORKTREES and "-claude-worktrees-" in project:
        return "worktree"

    title = ""
    first = None
    entrypoint = ""
    user_msgs = []
    summaries = []
    last_assistant_text = ""
    first_ts = last_ts = None

    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return "unreadable"
    with fh:
        for line in fh:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            t = o.get("type")
            if t == "custom-title":
                title = o.get("customTitle") or title
                continue
            if t == "ai-title" and not title:
                title = o.get("aiTitle") or o.get("title") or ""
                continue
            if t not in ("user", "assistant") or o.get("isSidechain"):
                continue
            content = (o.get("message") or {}).get("content")

            if t == "user":
                if is_tool_result(content):
                    continue
                raw = text_of(content)
                # Discord channel messages arrive flagged isMeta but are typed by the user
                if o.get("isMeta") and not raw.lstrip().startswith("<channel"):
                    continue
                if first is None and raw.strip():
                    first = raw.lstrip()
                    entrypoint = o.get("entrypoint") or ""
                    if first.startswith("<scheduled-task"):
                        m = re.search(r'name="([^"]+)"', first)
                        return "scheduled:" + (m.group(1) if m else "unknown")
                    if entrypoint.startswith("sdk"):
                        return "headless"
                ts = parse_ts(o.get("timestamp"))
                if ts is not None and ts < cutoff:
                    continue
                msg = clean_user_text(raw)
                if not msg or msg.startswith(NOISE_PREFIXES):
                    continue
                # a new real prompt closes the previous turn
                if last_assistant_text:
                    summaries.append(last_assistant_text)
                    last_assistant_text = ""
                user_msgs.append(clip(msg, MSG_CAP))
                if ts is not None:
                    first_ts = first_ts or ts
                    last_ts = ts
            else:
                txt = text_of(content).strip()
                ts = parse_ts(o.get("timestamp"))
                if txt and (ts is None or ts >= cutoff):
                    last_assistant_text = txt
                    if ts is not None:
                        last_ts = ts

    if last_assistant_text:
        summaries.append(last_assistant_text)
    if any(p in title.lower() for p in PIPELINE_TITLES) and "resume-project" in project:
        return "pipeline"
    if not user_msgs:
        return "empty"
    return {
        "id": os.path.basename(path)[:8],
        "project": project,
        "title": title,
        "start": first_ts,
        "end": last_ts,
        "user_msgs": user_msgs[-MSGS_KEPT:],
        "dropped_msgs": max(0, len(user_msgs) - MSGS_KEPT),
        "summaries": [clip(s, SUMMARY_CAP) for s in summaries[-SUMMARIES_KEPT:]],
    }


def collect(projects_dir, days, now=None):
    now = now or time.time()
    cutoff = now - days * 86400
    sessions, skipped, census = [], Counter(), Counter()
    for path in glob.glob(os.path.join(projects_dir, "*", "*.jsonl")):
        try:
            if os.path.getmtime(path) < cutoff:
                continue
        except OSError:
            continue
        r = read_session(path, cutoff)
        if isinstance(r, dict):
            sessions.append(r)
        elif r.startswith("scheduled:"):
            name = r.split(":", 1)[1]
            if name == "daily-job-pipeline":
                skipped["pipeline"] += 1
            else:
                census[name] += 1
        else:
            skipped[r] += 1
    sessions.sort(key=lambda s: s["start"] or 0)
    return {"sessions": sessions, "skipped": dict(skipped), "census": dict(census)}


HOME_SLUG = "-" + os.path.expanduser("~").strip("/").replace("/", "-")


def short_project(project):
    p = project.replace(HOME_SLUG + "-", "").replace(HOME_SLUG, "home")
    p = re.sub(r"^Documents-", "", p)
    return p.strip("-") or "root"


def fmt_day(ts):
    return datetime.fromtimestamp(ts).strftime("%a %m-%d") if ts else "?"


def render(results, days, today, notes=()):
    """results: list of (machine, collected) pairs."""
    total = sum(len(c["sessions"]) for _, c in results)
    out = ["# Work harvest digest, week ending %s" % today, "",
           "Source material for candidate resume bullets. Local only; never commit.", ""]
    for note in notes:
        out.append("- **remote**: " + note)
    for machine, c in results:
        skipped = ", ".join("%s %d" % kv for kv in sorted(c["skipped"].items())) or "none"
        census = ", ".join("%s x%d" % kv for kv in sorted(c["census"].items(),
                                                           key=lambda kv: -kv[1]))
        out.append("- **%s**: %d sessions kept over %d days; skipped: %s" %
                   (machine, len(c["sessions"]), days, skipped))
        out.append("  - automation census (scheduled runs, not excerpted): %s" %
                   (census or "none"))
    out.append("")
    n = 0
    for machine, c in results:
        for s in c["sessions"]:
            n += 1
            label = "S%02d" % n
            head = "## [%s] %s · %s · %s" % (label, machine, short_project(s["project"]),
                                             fmt_day(s["start"]))
            if fmt_day(s["end"]) != fmt_day(s["start"]):
                head += " to " + fmt_day(s["end"])
            out.append(head)
            out.append("session `%s`%s" % (s["id"], (" · title: " + s["title"]) if s["title"] else ""))
            out.append("")
            out.append("**User messages**" + (" (first %d omitted)" % s["dropped_msgs"]
                                              if s["dropped_msgs"] else ""))
            for i, m in enumerate(s["user_msgs"], 1):
                out.append("%d. %s" % (i, m.replace("\n", " ")))
            if s["summaries"]:
                out.append("")
                out.append("**End-of-turn summaries (last %d)**" % len(s["summaries"]))
                for sm in s["summaries"]:
                    out.append("> " + sm.replace("\n", "\n> "))
            out.append("")
    return "\n".join(out) + "\n", total


def ensure_private_dir(path):
    """Create the output dir with its own catch-all .gitignore, so its contents stay
    out of git even in a checkout whose root .gitignore lacks the work_log/ rule
    (and the daily run's `git add -A` cannot sweep them up)."""
    os.makedirs(path, exist_ok=True)
    marker = os.path.join(path, ".gitignore")
    if not os.path.exists(marker):
        with open(marker, "w", encoding="utf-8") as f:
            f.write("# written by harvest_work_log.py: nothing in here is ever committed\n*\n")


def run_remote(host, days, timeout=180):
    """Run this file on host with --json; source goes over stdin, nothing lands there."""
    with open(os.path.abspath(__file__), encoding="utf-8") as f:
        src = f.read()
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host,
           "python3", "-", "--json", "--days", str(days)]
    p = subprocess.run(cmd, input=src, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or "exit %d" % p.returncode).strip()[:200])
    return json.loads(p.stdout)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--projects-dir", default=PROJECTS_DIR)
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--remote", action="append", default=[],
                    help="also harvest HOST's transcripts over ssh (repeatable)")
    ap.add_argument("--json", action="store_true", help="print collected sessions as JSON")
    ap.add_argument("--dry-run", action="store_true", help="summarize, write nothing")
    a = ap.parse_args(argv)

    local = collect(a.projects_dir, a.days)
    if a.json:
        json.dump(local, sys.stdout)
        return 0

    results = [("laptop", local)]
    notes = []
    for host in a.remote:
        try:
            results.append((host, run_remote(host, a.days)))
        except Exception as e:  # remote trouble must never sink the local harvest
            notes.append("%s unreachable (%s)" % (host, e))

    today = datetime.now().strftime("%Y-%m-%d")
    text, total = render(results, a.days, today, notes)
    if a.dry_run:
        print("harvest: dry run, %d sessions, %d chars%s" %
              (total, len(text), (" [" + "; ".join(notes) + "]") if notes else ""))
        return 0
    try:
        ensure_private_dir(a.out_dir)
        path = os.path.join(a.out_dir, "digest_%s.md" % today)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as e:
        print("harvest: FAILED writing digest (%s)" % e)
        return 0
    print("harvest: %d sessions, %d chars -> %s%s" %
          (total, len(text), path, (" [" + "; ".join(notes) + "]") if notes else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
