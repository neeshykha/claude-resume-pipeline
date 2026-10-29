#!/usr/bin/env python3
"""Tests for the screen-FAIL memory in poll_ats.py (load_fail_memory,
hold_screen_failed, and poll_all's use of them). Everything runs in a temp dir
with made-up postings and screen tables; nothing reads the real jd_cache, and
the one poll_all run uses a stubbed board.

    .venv/bin/python pipeline/test_fail_memory.py
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jd_prefetch  # noqa: E402
import poll_ats  # noqa: E402

# The hold counts exact days, so the per-URL spread is pinned to zero, as in
# test_jd_prefetch_reuse.py. The memory reads the number from jd_prefetch.
jd_prefetch.REUSE_JITTER_DAYS = 0
AGE = jd_prefetch.REUSE_MAX_AGE_DAYS

A = "https://example.com/jobs/acme"
B = "https://example.com/jobs/bolt"
C = "https://example.com/jobs/cask"
RUN = date(2026, 3, 20)


def ago(n):
    return (RUN - timedelta(days=n)).isoformat()


def row(url, status="PASS", fails=()):
    return {"status": status, "fails": list(fails), "checks": [], "url": url,
            "company": "Acme", "title": "Support Operations Manager", "pre_score": 60}


PAY = ("salary mid $70K",)
NEAR_PAY = ("salary near-miss mid $95K",)
LOC = ("location (Austin, TX)",)
FLAG = ("flag:clearance_required",)


def screen_day(root, day, rows, copies=(), texts=None):
    """One run's dir: its screen table, the JD text each row was read from, worker
    cards for every row not in `copies`, and a reused-cards file for the ones that are.
    `texts` maps a url to a JD body other than the default one."""
    d = os.path.join(root, day)
    os.makedirs(d)
    for i, r in enumerate(rows):
        r["file"] = os.path.join("/elsewhere", f"{i:02d}.txt")   # looked up by name, beside the table
        with open(os.path.join(d, f"{i:02d}.txt"), "w", encoding="utf-8") as f:
            f.write((texts or {}).get(r["url"], f"The posting at {r['url']}."))
    with open(os.path.join(d, "screen_table.json"), "w", encoding="utf-8") as f:
        json.dump({"date": day, "rows": rows, "missing": []}, f)
    worker = [{"file": f"{i:02d}.txt", "url": r["url"], "read_ok": True}
              for i, r in enumerate(rows) if r["url"] not in copies]
    with open(os.path.join(d, "cards_batch_01.json"), "w", encoding="utf-8") as f:
        json.dump(worker, f)
    with open(os.path.join(d, jd_prefetch.REUSED_CARDS), "w", encoding="utf-8") as f:
        json.dump([{"file": "x.txt", "url": u, "read_ok": True, "reused_from": "earlier"}
                   for u in copies], f)


def fresh():
    return tempfile.mkdtemp(prefix="fail_memory_test_")


def test_one_pay_fail_holds():
    root = fresh()
    screen_day(root, ago(3), [row(A, "FAIL", PAY), row(B, "FAIL", NEAR_PAY), row(C)])
    held = poll_ats.load_fail_memory(RUN, root)
    assert set(held) == {A, B}, held
    assert held[A]["reason"] == "pay" and held[A]["failed_on"] == ago(3)
    assert held[A]["fails"] == list(PAY)
    assert held[A]["returns_on"] == (RUN + timedelta(days=AGE - 3 + 1)).isoformat()
    assert held[B]["reason"] == "pay", "a near-miss on pay is a pay FAIL"


def test_one_location_fail_does_not_hold_two_do():
    root = fresh()
    screen_day(root, ago(5), [row(A, "FAIL", LOC), row(B, "FAIL", LOC)])
    screen_day(root, ago(2), [row(A, "FAIL", LOC)])
    held = poll_ats.load_fail_memory(RUN, root)
    assert set(held) == {A}, held
    assert held[A]["reason"] == "location" and held[A]["failed_on"] == ago(2)


def test_location_fails_on_different_text_do_not_hold():
    root = fresh()
    screen_day(root, ago(5), [row(A, "FAIL", LOC), row(B, "FAIL", LOC)])
    screen_day(root, ago(2), [row(A, "FAIL", LOC), row(B, "FAIL", LOC)],
               texts={A: "The posting, rewritten."})
    assert set(poll_ats.load_fail_memory(RUN, root)) == {B}
    os.remove(os.path.join(root, ago(5), "01.txt"))   # B's first text is gone: nothing to compare
    assert poll_ats.load_fail_memory(RUN, root) == {}


def test_a_copy_is_not_a_second_read():
    root = fresh()
    screen_day(root, ago(5), [row(A, "FAIL", LOC)])
    screen_day(root, ago(4), [row(A, "FAIL", LOC)], copies={A})   # reused card
    assert poll_ats.load_fail_memory(RUN, root) == {}
    # A copy of a pay FAIL doesn't move the hold either: it ends from the read.
    root = fresh()
    screen_day(root, ago(AGE), [row(A, "FAIL", PAY)])
    screen_day(root, ago(1), [row(A, "FAIL", PAY)], copies={A})
    assert poll_ats.load_fail_memory(RUN, root)[A]["failed_on"] == ago(AGE)


def test_a_flag_alone_never_holds():
    root = fresh()
    screen_day(root, ago(5), [row(A, "FAIL", FLAG), row(B, "FAIL", FLAG + LOC)])
    screen_day(root, ago(2), [row(A, "FAIL", FLAG), row(B, "FAIL", FLAG + LOC)])
    held = poll_ats.load_fail_memory(RUN, root)
    assert set(held) == {B} and held[B]["reason"] == "location", "the flag doesn't block a location hold"


def test_the_latest_read_decides():
    root = fresh()
    screen_day(root, ago(6), [row(A, "FAIL", PAY), row(B, "CHECK")])
    screen_day(root, ago(3), [row(A, "PASS"), row(B, "FAIL", LOC)])
    assert poll_ats.load_fail_memory(RUN, root) == {}, "pay then PASS, and CHECK then one location FAIL"
    # Two location FAILs in a row hold even after a CHECK; FAIL, CHECK, FAIL does not.
    screen_day(root, ago(1), [row(B, "FAIL", LOC)])
    assert set(poll_ats.load_fail_memory(RUN, root)) == {B}
    root = fresh()
    screen_day(root, ago(6), [row(B, "FAIL", LOC)])
    screen_day(root, ago(4), [row(B, "CHECK")])
    screen_day(root, ago(1), [row(B, "FAIL", LOC)])
    assert poll_ats.load_fail_memory(RUN, root) == {}


def test_the_hold_ends_when_prefetch_would_read_again():
    root = fresh()
    screen_day(root, ago(AGE), [row(A, "FAIL", PAY)])
    screen_day(root, ago(AGE + 1), [row(B, "FAIL", PAY)])
    assert set(poll_ats.load_fail_memory(RUN, root)) == {A}
    # The same boundary jd_prefetch.reuse_card() uses, read from the same function.
    assert AGE == jd_prefetch.max_age_days(A)


def test_only_earlier_main_run_dirs_count():
    root = fresh()
    screen_day(root, RUN.isoformat(), [row(A, "FAIL", PAY)])          # today's own dir
    screen_day(root, ago(2) + "_linkedin", [row(B, "FAIL", PAY)])     # not a main run
    os.makedirs(os.path.join(root, ago(1)))                           # no table: screen didn't finish
    assert poll_ats.load_fail_memory(RUN, root) == {}
    assert poll_ats.load_fail_memory(RUN, os.path.join(root, "absent")) == {}


def job(url, title="Support Operations Manager"):
    return {"company": "Acme", "title": title, "location": "Remote", "apply_url": url,
            "pre_score": 50, "title_tier": "tier1_true_match"}


def test_hold_moves_roles_out_of_both_lists():
    root = fresh()
    screen_day(root, ago(2), [row(A, "FAIL", PAY), row(C, "FAIL", PAY)])
    matched = [job("https://EXAMPLE.com/jobs/acme/"), job(B)]
    borderline = [job(C, "AI Operations Lead")]
    m, b, held, status = poll_ats.hold_screen_failed(matched, borderline, RUN, root)
    assert status == "on"
    assert [j["apply_url"] for j in m] == [B] and b == []
    assert [(h["url"], h["section"], h["reason"]) for h in held] == [
        ("https://EXAMPLE.com/jobs/acme/", "matched", "pay"), (C, "borderline", "pay")]
    assert all(h["failed_on"] == ago(2) and h["company"] == "Acme" for h in held)


def test_an_unreadable_table_holds_nothing_back():
    root = fresh()
    screen_day(root, ago(3), [row(A, "FAIL", PAY)])
    screen_day(root, ago(1), [row(B, "FAIL", PAY)])
    with open(os.path.join(root, ago(1), "screen_table.json"), "w", encoding="utf-8") as f:
        f.write('{"rows": [{"status": "FA')
    matched = [job(A), job(B)]
    m, b, held, status = poll_ats.hold_screen_failed(matched, [], RUN, root)
    assert m == matched and held == [] and status.startswith("off: "), status


def test_poll_all_holds_a_failed_role_and_writes_nothing():
    work = fresh()
    created = int(datetime.combine(RUN - timedelta(days=3), datetime.min.time()).timestamp() * 1000)
    titles = ["Quokka Desk Lead", "Quokka Bench Lead"]
    board = [{"id": jid, "text": t, "categories": {"location": "Remote - United States"},
              "createdAt": created, "hostedUrl": f"https://example.test/{jid}",
              "description": "<p>Run the support desk.</p>"}
             for jid, t in (("a", titles[0]), ("b", titles[1]))]
    with open(poll_ats.WATCHLIST_PATH, encoding="utf-8") as f:
        wl = json.load(f)
    wl["companies"] = [{"name": "Quokka Works", "ats": "lever", "slug": "quokka", "priority": "high"}]
    wl["_poller_config"]["supplemental_exact_titles"]["titles"] = titles
    wl_path, seen_path = os.path.join(work, "watchlist.json"), os.path.join(work, "seen_jobs.json")
    with open(wl_path, "w", encoding="utf-8") as f:
        json.dump(wl, f, ensure_ascii=False)
    with open(seen_path, "w") as f:
        json.dump({"jobs": {}}, f)
    root = os.path.join(work, "jd_cache")
    os.makedirs(root)
    screen_day(root, ago(2), [row("https://example.test/b", "FAIL", PAY)])
    before = {p: open(os.path.join(root, ago(2), p), "rb").read()
              for p in os.listdir(os.path.join(root, ago(2)))}

    real = (poll_ats.fetch_lever, poll_ats.WATCHLIST_PATH, poll_ats.SEEN_JOBS_PATH,
            poll_ats.JD_CACHE_DIR, poll_ats.time.sleep)
    poll_ats.fetch_lever = lambda slug: [dict(p) for p in board]
    poll_ats.WATCHLIST_PATH, poll_ats.SEEN_JOBS_PATH = wl_path, seen_path
    poll_ats.JD_CACHE_DIR = root
    poll_ats.time.sleep = lambda s: None
    try:
        on = poll_ats.poll_all(RUN)
        off = poll_ats.poll_all(RUN, fail_memory=False)
    finally:
        (poll_ats.fetch_lever, poll_ats.WATCHLIST_PATH, poll_ats.SEEN_JOBS_PATH,
         poll_ats.JD_CACHE_DIR, poll_ats.time.sleep) = real

    shown = lambda res: sorted(j["title"] for j in res["matched"]) + sorted(
        j["title"] for j in res["near_window"])
    assert shown(on) == ["Quokka Desk Lead"], shown(on)
    assert [(h["title"], h["reason"], h["section"]) for h in on["screen_failed"]] == [
        ("Quokka Bench Lead", "pay", "matched")], on["screen_failed"]
    assert on["stats"]["screen_failed"] == 1 and on["stats"]["fail_memory"] == "on"
    assert on["stats"]["screen_failed_by_reason"] == {"pay": 1, "location": 0}
    assert shown(off) == sorted(titles) and off["screen_failed"] == [], shown(off)
    assert off["stats"]["fail_memory"] == "off: --no-fail-memory"
    with open(seen_path) as f:
        assert json.load(f) == {"jobs": {}}, "nothing goes to seen_jobs.json"
    assert {p: open(os.path.join(root, ago(2), p), "rb").read()
            for p in os.listdir(os.path.join(root, ago(2)))} == before, "the cache is read-only"
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
