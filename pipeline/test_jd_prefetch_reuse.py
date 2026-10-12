#!/usr/bin/env python3
"""Tests for card reuse in jd_prefetch.py. Everything runs in a temp dir with
made-up postings: the fetch is stubbed (no network), the screen workers are a
stand-in that writes one card per batched JD, and nothing here reads the real
jd_cache.

    .venv/bin/python pipeline/test_jd_prefetch_reuse.py
"""
import contextlib
import glob
import io
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jd_prefetch as jp  # noqa: E402

# The age tests below count exact days, so they pin the per-URL spread to zero.
# test_max_age_is_stable_per_url_and_spread_across_urls covers the spread itself.
jp.REUSE_JITTER_DAYS = 0
import jd_screen_table as jst  # noqa: E402

A = "https://example.com/jobs/acme"
B = "https://example.com/jobs/bolt"
C = "https://example.com/jobs/cask"
D = "https://example.com/jobs/dray"
D1, D2, D3 = "2026-09-01", "2026-09-02", "2026-09-03"
PAGES = {}   # url -> the record the stubbed fetch returns


def body(seed):
    return f"{seed}. " + "Own the support queue, its tooling, and the team that runs it. " * 12


def fixture(*urls):
    d = tempfile.mkdtemp(prefix="jd_reuse_test_")
    jp.JOBS = os.path.join(d, "jobs")
    jp.OUTCOMES = os.path.join(d, "outcomes.csv")   # absent: nothing is already known
    jp.fetch_jd.fetch = lambda url: dict(PAGES[url]) if url in PAGES else {"error": "no such page"}
    os.makedirs(jp.JOBS)
    PAGES.clear()
    for u in urls:
        PAGES[u] = {"title": "Support Operations Manager", "ats": "fake", "location": "Remote, US",
                    "remote": True, "posted": "2026-08-20", "salary": "$120,000 - $140,000",
                    "body": body(u)}
    return d


def cache(day):
    return os.path.join(jp.JOBS, "jd_cache", day)


def run(day, urls, *flags):
    """Write the day's hits file and run prefetch. Returns (stdout lines, manifest)."""
    hits = {"matched": [{"company": u.rstrip("/").rsplit("/", 1)[-1].title(),
                         "title": "Support Operations Manager", "location": "Remote",
                         "url": u, "ats": "fake", "pre_score": 90 - i}
                        for i, u in enumerate(urls)]}
    with open(os.path.join(jp.JOBS, f"ats_hits_{day}.json"), "w", encoding="utf-8") as f:
        json.dump(hits, f)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert jp.main(["--date", day, *flags]) == 0
    with open(os.path.join(cache(day), "manifest.json"), encoding="utf-8") as f:
        return buf.getvalue().splitlines(), json.load(f)


def work(day, unreadable=()):
    """Stand in for the screen workers: one card per JD in each batch file."""
    with open(os.path.join(cache(day), "manifest.json"), encoding="utf-8") as f:
        url = {e["file"]: e["url"] for e in json.load(f)["entries"] if e.get("file")}
    for p in glob.glob(os.path.join(cache(day), "batch_*.json")):
        with open(p, encoding="utf-8") as f:
            files = json.load(f)
        cards = [{"file": x, "read_ok": url[x] not in unreadable, "url": url[x],
                  "work_mode": "remote_us", "atlanta_ok": "no", "salary_min_usd": 120000,
                  "salary_max_usd": 140000, "manages_people": "manages",
                  "read_on": day}   # not a real card field: marks which read a copy carries
                 for x in files]
        with open(os.path.join(cache(day), "cards_" + os.path.basename(p)), "w", encoding="utf-8") as f:
            json.dump(cards, f)


def cached(day):
    with open(os.path.join(cache(day), jp.REUSED_CARDS), encoding="utf-8") as f:
        return {c["url"]: c for c in json.load(f)}


def to_read(manifest):
    by_file = {e["file"]: e["url"] for e in manifest["entries"] if e.get("file")}
    return sorted(by_file[x] for b in manifest["batches"] for x in b)


def table(day):
    """Run the real jd_screen_table.py over the fixture cache. Returns its stdout lines."""
    jst.HERE = os.path.dirname(jp.JOBS)
    jst.cfg = lambda: (100000, 90000, None)   # salary floors only; the fixture has no watchlist
    argv, sys.argv = sys.argv, ["jd_screen_table.py", "--date", day]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            assert jst.main() == 0
    finally:
        sys.argv = argv
    return buf.getvalue().splitlines()


def test_same_url_same_text_reuses():
    fixture(A, B)
    _, m = run(D1, [A, B])
    assert m["counts"]["reused"] == 0 and m["counts"]["to_read"] == 2, "nothing earlier to reuse"
    work(D1)
    _, m = run(D2, [A, B])
    assert m["counts"]["reused"] == 2 and m["counts"]["to_read"] == 0, m["counts"]
    got = cached(D2)
    assert set(got) == {A, B}
    assert all(c["reused_from"] == D1 and c["read_on"] == D1 and c["read_ok"] is True
               for c in got.values()), got
    # Reused JDs stay in the manifest for the table to join, just not in a batch.
    assert [e["url"] for e in m["entries"]] == [A, B]
    assert all(e["status"] == "ok" and e["reused_from"] == D1 and "batch" not in e
               for e in m["entries"])
    assert m["counts"]["fetched"] == 2, "a reused JD was still fetched"


def test_first_line_keeps_its_wording_and_appends_the_counts():
    fixture(A, B, C)
    run(D1, [A, B])
    work(D1)
    out, _ = run(D2, [A, B, C])
    assert out[0] == ("jd_prefetch: 3 candidates (3 matched, 0 ai_wildcard, 0 near_window); "
                      "fetched 3, thin 0, errors 0, already-known 0; 1 batches; "
                      "reused 2, to read 1"), out[0]
    assert out[1].startswith("manifest: ")


def test_changed_text_rereads():
    fixture(A, B)
    run(D1, [A, B])
    work(D1)
    PAGES[A]["body"] = body("rewritten, now with an on-site requirement")
    _, m = run(D2, [A, B])
    assert to_read(m) == [A] and set(cached(D2)) == {B}, m["counts"]
    work(D2)
    _, m = run(D3, [A, B])
    got = cached(D3)
    assert got[A]["reused_from"] == D2 and got[A]["read_on"] == D2, "the newer read is the one reused"
    assert got[B]["reused_from"] == D1


def test_hash_ignores_restamp_and_spacing_but_not_quoted_facts():
    fixture(A, B, C, D)
    run(D1, [A, B, C, D])
    work(D1)
    PAGES[A]["posted"] = "2026-09-02"                               # re-stamped, same posting
    PAGES[B]["body"] = PAGES[B]["body"].replace(". ", ".\n\n")      # re-wrapped, same words
    PAGES[C]["salary"] = "$90,000 - $100,000"                       # header facts a card quotes
    PAGES[D]["location"] = "Austin, TX"
    _, m = run(D2, [A, B, C, D])
    assert set(cached(D2)) == {A, B} and to_read(m) == [C, D], m["counts"]


def test_url_match_ignores_case_and_trailing_slash():
    fixture(A)
    run(D1, [A])
    work(D1)
    variant = "https://EXAMPLE.com/jobs/acme/"
    PAGES[variant] = PAGES[A]
    _, m = run(D2, [variant])
    assert m["counts"]["reused"] == 1, m["counts"]


def test_read_ok_false_rereads():
    fixture(A, B, C)
    run(D1, [A, B, C])
    work(D1, unreadable={A})
    # A card with no read_ok at all is not proof of a good read either.
    p = os.path.join(cache(D1), "cards_batch_01.json")
    with open(p, encoding="utf-8") as f:
        cards = json.load(f)
    for c in cards:
        if c["url"] == B:
            del c["read_ok"]
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cards, f)
    _, m = run(D2, [A, B, C])
    assert to_read(m) == [A, B] and set(cached(D2)) == {C}, m["counts"]


def test_old_read_expires_even_through_a_chain_of_reuses():
    fixture(A)
    run("2026-09-01", [A])
    work("2026-09-01")
    for day in ("2026-09-08", "2026-09-14", "2026-09-15"):   # 7, 13, and 14 days on
        _, m = run(day, [A])
        assert m["counts"]["reused"] == 1, day
        assert cached(day)[A]["reused_from"] == "2026-09-01", "a reuse must not reset the clock"
    # Day 15. Yesterday's copy is one day old, but the worker's read is not.
    _, m = run("2026-09-16", [A])
    assert m["counts"]["reused"] == 0 and to_read(m) == [A], m["counts"]
    work("2026-09-16")
    _, m = run("2026-09-17", [A])
    got = cached("2026-09-17")[A]
    assert got["reused_from"] == "2026-09-16" and got["read_on"] == "2026-09-16"


def test_no_reuse_flag_reads_everything():
    fixture(A, B)
    run(D1, [A, B])
    work(D1)
    out, m = run(D2, [A, B], "--no-reuse")
    assert m["counts"]["reused"] == 0 and to_read(m) == [A, B]
    assert out[0].endswith("; 1 batches; reused 0, to read 2 (--no-reuse)"), out[0]
    assert cached(D2) == {}
    # Same date, run twice: the second run's --no-reuse clears the first run's copies.
    _, m = run(D3, [A, B])
    assert len(cached(D3)) == 2
    _, m = run(D3, [A, B], "--no-reuse")
    assert cached(D3) == {} and to_read(m) == [A, B]
    assert not any("reused_from" in e for e in m["entries"])


def test_all_reused_yields_zero_batches():
    fixture(A, B)
    run(D1, [A, B])
    work(D1)
    out, m = run(D2, [A, B])
    assert m["batches"] == [] and m["counts"]["batches"] == 0
    assert glob.glob(os.path.join(cache(D2), "batch_*.json")) == []
    assert out[0].endswith("; 0 batches; reused 2, to read 0"), out[0]
    # No worker ran, and the table still has every row.
    lines = table(D2)
    assert lines[0].startswith("jd_screen: 2 cards") and lines[0].endswith("missing 0"), lines[0]
    assert not any(ln.startswith(("RE-DISPATCH", "MISSING")) for ln in lines), lines


def test_table_joins_reused_and_fresh_cards():
    fixture(A, B)
    run(D1, [A])
    work(D1)
    _, m = run(D2, [A, B])
    assert set(cached(D2)) == {A} and to_read(m) == [B]
    lines = table(D2)
    assert lines[0].startswith("jd_screen: 1 cards") and "missing 1" in lines[0], "B has no card yet"
    work(D2)
    lines = table(D2)
    assert lines[0] == "jd_screen: 2 cards -> PASS 2, CHECK 0, FAIL 0; missing 0", lines[0]
    with open(os.path.join(cache(D2), "screen_table.json"), encoding="utf-8") as f:
        rows = json.load(f)["rows"]
    assert {r["url"]: r["status"] for r in rows} == {A: "PASS", B: "PASS"}


def test_corrupt_or_misshapen_old_cards_are_skipped():
    d = fixture(A, B, C)
    assert jp.reuse_index(os.path.join(d, "no_such_dir"), D3) == {}
    run(D1, [A, B, C], "--batch-size", "1")   # one card file per JD
    work(D1)
    files = {os.path.basename(p) for p in glob.glob(os.path.join(cache(D1), "cards_batch_0*.json"))}
    assert files == {"cards_batch_01.json", "cards_batch_02.json", "cards_batch_03.json"}
    with open(os.path.join(cache(D1), "cards_batch_01.json"), "w", encoding="utf-8") as f:
        f.write('[{"file": "/x/01_acme.txt", "read_ok": tr')   # A's cards, cut off mid-write
    # A newer dir full of things that are not usable cards. C's entry there has
    # a bad reused_from; it must be dropped, not dated by its dir.
    os.makedirs(cache(D2))
    c_txt = [p for p in glob.glob(os.path.join(cache(D1), "*.txt")) if "cask" in p][0]
    shutil.copy(c_txt, cache(D2))
    with open(os.path.join(cache(D2), "cards_batch_01.json"), "w", encoding="utf-8") as f:
        json.dump([7, "text", None, {"url": B}, {"file": 5, "url": B},
                   {"file": "gone.txt", "url": B, "read_ok": True},
                   {"file": os.path.basename(c_txt), "url": C, "read_ok": True,
                    "reused_from": "last week"}], f)
    with open(os.path.join(cache(D2), "cards_batch_02.json"), "w", encoding="utf-8") as f:
        json.dump({"cards": "not a list"}, f)
    os.makedirs(os.path.join(jp.JOBS, "jd_cache", "2026-13-45"))          # date-shaped, not a date
    open(os.path.join(jp.JOBS, "jd_cache", "2026-08-31"), "w").close()   # a file, not a dir
    out, m = run(D3, [A, B, C])
    assert to_read(m) == [A], m["counts"]
    got = cached(D3)
    assert got[B]["reused_from"] == D1 and got[C]["reused_from"] == D1, got
    assert not any("REUSE OFF" in ln for ln in out), out


def test_a_failure_inside_reuse_reads_everything():
    fixture(A)
    run(D1, [A])
    work(D1)
    real = jp.reuse_index

    def boom(*a, **k):
        raise RuntimeError("index fell over")
    jp.reuse_index = boom
    try:
        out, m = run(D2, [A])
    finally:
        jp.reuse_index = real
    assert m["counts"]["reused"] == 0 and to_read(m) == [A]
    assert out[0].startswith("jd_prefetch: 1 candidates") and out[0].endswith("reused 0, to read 1")
    assert any("REUSE OFF" in ln and "index fell over" in ln for ln in out[1:]), out


def test_reused_card_file_points_at_todays_txt():
    fixture(A, B, C)
    _, m1 = run(D1, [A, B])
    work(D1)
    old = {e["url"]: e["file"] for e in m1["entries"]}
    _, m = run(D2, [C, A, B])   # a new posting on top: A and B each move down a rank
    today = {e["url"]: e["file"] for e in m["entries"]}
    got = cached(D2)
    for u in (A, B):
        assert got[u]["file"] == today[u], "the table joins on this path"
        assert os.path.dirname(got[u]["file"]) == cache(D2) and os.path.isfile(got[u]["file"])
        assert os.path.basename(today[u]) != os.path.basename(old[u]), "the rank is in the name"
    assert m["batches"] == [[today[C]]]
    with open(os.path.join(cache(D2), "batch_01.json"), encoding="utf-8") as f:
        assert json.load(f) == [today[C]]


def test_only_earlier_main_run_dirs_within_the_lookback_count():
    fixture(A)
    run(D2, [A])
    work(D2)
    root = os.path.join(jp.JOBS, "jd_cache")
    assert list(jp.reuse_index(root, D3)) == [A]
    assert list(jp.reuse_index(root, "2026-09-23")) == [A], "21 days back is inside the window"
    assert jp.reuse_index(root, "2026-09-24") == {}, "22 days back is not"
    assert jp.reuse_index(root, D2) == {}, "a run never reuses from its own dir"
    assert jp.reuse_index(root, D1) == {}, "or from a later one"
    # The same cards under a suffixed dir (a LinkedIn or ad-hoc read) are not a main run.
    os.rename(cache(D2), cache(D2) + "_linkedin")
    assert jp.reuse_index(root, D3) == {}
    _, m = run(D3, [A])
    assert m["counts"]["reused"] == 0 and to_read(m) == [A]


def test_same_day_rerun_keeps_todays_fresh_cards_and_leaves_no_ghost_batches():
    # The day --no-reuse exists for: the worker brief changed, so every JD is re-read, and then
    # prefetch runs once more on the same date. The fresh cards must win, and the batch files
    # of the first run must not survive to be re-dispatched.
    fixture(A, B)
    run(D1, [A, B])
    work(D1)
    jp_batch = 1
    lines, m = run(D2, [A, B], "--no-reuse", "--batch-size", str(jp_batch))
    assert m["counts"]["to_read"] == 2 and len(m["batches"]) == 2
    work(D2)
    assert sorted(os.path.basename(x) for x in glob.glob(os.path.join(cache(D2), "batch_*.json"))) == \
        ["batch_01.json", "batch_02.json"]
    lines, m = run(D2, [A, B])            # plain rerun, same date, default batch size
    assert m["counts"]["reused"] == 0, "a URL a worker carded today is never handed an older copy"
    assert cached(D2) == {}
    assert [os.path.basename(x) for x in glob.glob(os.path.join(cache(D2), "batch_*.json"))] == ["batch_01.json"], \
        "the first run's second batch file is gone"
    assert len(glob.glob(os.path.join(cache(D2), "cards_batch_0*.json"))) == 2, "the workers' cards are never removed"
    rows = [ln for ln in table(D2) if "Support Operations Manager" in ln]
    assert len(rows) == 2 and not any("RE-DISPATCH batch_02" in ln for ln in table(D2)), table(D2)


def test_table_lets_a_worker_card_beat_a_reused_copy_of_the_same_jd():
    fixture(A)
    run(D1, [A])
    work(D1)
    run(D2, [A])                           # reused: cards_batch_cached.json holds D1's read
    assert cached(D2)[A]["read_on"] == D1
    txt = cached(D2)[A]["file"]
    with open(os.path.join(cache(D2), "cards_batch_01.json"), "w", encoding="utf-8") as f:
        json.dump([{"file": txt, "read_ok": True, "url": A, "work_mode": "onsite", "atlanta_ok": "no",
                    "salary_min_usd": 120000, "salary_max_usd": 140000, "manages_people": "manages",
                    "read_on": D2}], f)
    out = "\n".join(table(D2))
    assert "FAIL" in out and "PASS" not in out.split("jd_screen:")[1].split("\n")[1], \
        "the on-site card written today decides the row, not the remote copy from yesterday: " + out


def test_max_age_is_stable_per_url_and_spread_across_urls():
    keep = jp.REUSE_JITTER_DAYS
    jp.REUSE_JITTER_DAYS = 6
    try:
        ages = [jp.max_age_days(f"https://example.com/jobs/{i}") for i in range(200)]
        assert min(ages) == jp.REUSE_MAX_AGE_DAYS and max(ages) == jp.REUSE_MAX_AGE_DAYS + 6, (min(ages), max(ages))
        assert len(set(ages)) == 7, "every day in the spread gets some URLs"
        assert jp.max_age_days("https://Example.com/jobs/7/") == jp.max_age_days("https://example.com/jobs/7")
        assert max(ages) < jp.REUSE_LOOKBACK_DAYS, "the lookback has to reach the oldest read that can still stand"
    finally:
        jp.REUSE_JITTER_DAYS = keep


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
