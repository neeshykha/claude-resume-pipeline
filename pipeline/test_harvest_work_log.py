#!/usr/bin/env python3
"""Tests for harvest_work_log.py. Transcripts are fabricated in a temp dir; nothing
here reads ~/.claude/projects or touches the network.

    .venv/bin/python pipeline/test_harvest_work_log.py
"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harvest_work_log as hw  # noqa: E402

NOW = time.time()


def iso(days_ago):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(NOW - days_ago * 86400))


def user(text, days_ago=1, **kw):
    o = {"type": "user", "timestamp": iso(days_ago), "entrypoint": "claude-desktop",
         "message": {"role": "user", "content": text}}
    o.update(kw)
    return o


def tool_result(days_ago=1):
    return {"type": "user", "timestamp": iso(days_ago),
            "message": {"content": [{"type": "tool_result", "content": "SECRET TOOL OUTPUT"}]}}


def assistant(text, days_ago=1, tool=False):
    blocks = [{"type": "tool_use", "name": "Bash", "input": {}}] if tool else \
        [{"type": "text", "text": text}]
    return {"type": "assistant", "timestamp": iso(days_ago), "message": {"content": blocks}}


def write(root, project, name, entries, mtime_days_ago=1):
    d = os.path.join(root, project)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name + ".jsonl")
    with open(p, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    t = NOW - mtime_days_ago * 86400
    os.utime(p, (t, t))
    return p


def build():
    root = tempfile.mkdtemp(prefix="harvest_test_")
    write(root, "-Users-demo-Projects-widget", "aaaaaaaa-1", [
        {"type": "ai-title", "aiTitle": "Widget queue rebuild"},
        user("Old message from last month", days_ago=30),
        assistant("Old answer", days_ago=30),
        user("<system-reminder>ignore me</system-reminder>Rebuild the widget queue router"),
        assistant("", tool=True),
        tool_result(),
        assistant("Interim note"),
        assistant("Router rebuilt; 12 rules collapsed to 4."),
        user("Now add the audit report"),
        assistant("Audit report added."),
    ])
    write(root, "-Users-demo", "bbbbbbbb-2", [
        user('<scheduled-task name="nightly-digest" file="x">run it</scheduled-task>'),
        assistant("done"),
    ])
    write(root, "-Users-demo", "bbbbbbbb-3", [
        user('<scheduled-task name="nightly-digest" file="x">run it</scheduled-task>'),
    ])
    write(root, "-Users-demo", "cccccccc-4", [
        user('<scheduled-task name="daily-job-pipeline" file="x">run</scheduled-task>'),
    ])
    write(root, "-Users-demo-Documents-resume-project", "dddddddd-5", [
        {"type": "custom-title", "customTitle": "Daily job pipeline"},
        user("run the pipeline by hand"),
    ])
    write(root, "-private-tmp-claude-501-scratchpad", "eeeeeeee-6", [user("scratch work")])
    write(root, "-Users-demo-ModelBaseline-runs-x", "ffffffff-7", [user("baseline run")])
    write(root, "-", "gggggggg-8", [user("headless job", entrypoint="sdk-cli")])
    write(root, "-Users-demo-Chat", "hhhhhhhh-9", [
        user('<channel source="discord" chat_id="1">\nShip the intake form today\n</channel>',
             isMeta=True),
        user("hook injected context", isMeta=True),
    ])
    write(root, "-Users-demo", "iiiiiiii-10", [user("stale file")], mtime_days_ago=20)
    write(root, "-Users-demo", "jjjjjjjj-11", [user("only old", days_ago=12)])
    return root


def test_collect():
    root = build()
    c = hw.collect(root, 7, now=NOW)
    by_id = {s["id"]: s for s in c["sessions"]}
    assert set(by_id) == {"aaaaaaaa", "hhhhhhhh"}, by_id.keys()

    w = by_id["aaaaaaaa"]
    assert w["title"] == "Widget queue rebuild"
    assert w["user_msgs"] == ["Rebuild the widget queue router", "Now add the audit report"]
    # last assistant text of each turn, not the interim note, not tool output
    assert w["summaries"] == ["Router rebuilt; 12 rules collapsed to 4.", "Audit report added."]
    blob = json.dumps(w)
    assert "SECRET TOOL OUTPUT" not in blob and "Old message" not in blob
    assert "ignore me" not in blob

    assert by_id["hhhhhhhh"]["user_msgs"] == ["Ship the intake form today"]

    assert c["census"] == {"nightly-digest": 2}
    assert c["skipped"] == {"pipeline": 2, "scratch": 2, "headless": 1, "empty": 1}, c["skipped"]


def test_worktrees_kept_by_default():
    root = tempfile.mkdtemp(prefix="harvest_wt_")
    write(root, "-Users-demo-repo--claude-worktrees-brave-otter-1a2b3c", "kkkkkkkk-1",
          [user("feature work in a worktree")])
    assert [s["id"] for s in hw.collect(root, 7, now=NOW)["sessions"]] == ["kkkkkkkk"]


def test_caps():
    root = tempfile.mkdtemp(prefix="harvest_cap_")
    entries = []
    for i in range(hw.MSGS_KEPT + 5):
        entries += [user("msg %d " % i + "x" * 2000), assistant("reply %d" % i)]
    write(root, "-Users-demo", "llllllll-1", entries)
    s = hw.collect(root, 7, now=NOW)["sessions"][0]
    assert len(s["user_msgs"]) == hw.MSGS_KEPT and s["dropped_msgs"] == 5
    assert s["user_msgs"][0].startswith("msg 5 ")
    assert all(len(m) <= hw.MSG_CAP + 10 for m in s["user_msgs"])
    assert len(s["summaries"]) == hw.SUMMARIES_KEPT


def test_render_and_main():
    root = build()
    out = tempfile.mkdtemp(prefix="harvest_out_")
    c = hw.collect(root, 7, now=NOW)
    text, total = hw.render([("laptop", c)], 7, "2026-01-02", notes=["worker unreachable (x)"])
    assert total == 2
    assert "## [S01] laptop" in text and "## [S02] laptop" in text
    assert "nightly-digest x2" in text and "worker unreachable" in text
    assert "`aaaaaaaa`" in text

    assert hw.main(["--projects-dir", root, "--out-dir", out]) == 0
    files = sorted(os.listdir(out))
    assert len(files) == 2 and files[1].startswith("digest_"), files
    with open(os.path.join(out, ".gitignore")) as f:
        assert f.read().rstrip().endswith("*")
    # an unreachable remote is reported, never fatal
    assert hw.main(["--projects-dir", root, "--out-dir", out, "--dry-run",
                    "--remote", "no-such-host.invalid"]) == 0


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok   " + name)
            except AssertionError as e:
                fails += 1
                print("FAIL %s: %s" % (name, e))
    sys.exit(1 if fails else 0)
