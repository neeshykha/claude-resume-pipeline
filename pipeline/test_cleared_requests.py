#!/usr/bin/env python3
"""Tests for cleared_requests.py: Tailor it on "Cleared, not tailored" (D63, 2026-11-26).
Fixtures are made up and live in a temp dir; nothing here reads the real files or touches
the network (the posting read is replaced).

    .venv/bin/python pipeline/test_cleared_requests.py
"""
import contextlib
import csv
import datetime
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cleared_requests as cr  # noqa: E402
import jd_screen_table as jst  # noqa: E402

TODAY = datetime.date(2026, 11, 26)
A = "https://jobs.example.com/acme/0001"
B = "https://jobs.example.com/bolt/0002"
C = "https://jobs.example.com/cove/0003"
D = "https://jobs.example.com/dune/0004"
PAGES = {}   # url -> what the stubbed read returns
REAL_LIVE_READ = cr.live_read   # fresh() swaps in a stub; the routing test needs the real one


def body(seed):
    return f"{seed}. " + "Run the support queue, own its tooling, and coach the team that works it. " * 10


def fresh(outcomes=()):
    d = tempfile.mkdtemp(prefix="cleared_test_")
    cr.JOBS_DIR = os.path.join(d, "jobs")
    cr.PATH = os.path.join(cr.JOBS_DIR, "cleared_requests.json")
    cr.OUTCOMES = os.path.join(d, "outcomes.csv")
    cr.WATCHLIST = os.path.join(d, "watchlist.json")
    os.makedirs(os.path.join(cr.JOBS_DIR, "jd_cache"))
    with open(cr.WATCHLIST, "w", encoding="utf-8") as f:
        json.dump({"_scoring_config": {"company_cap_threshold": 110, "full_tailoring_threshold": 88,
                                       "salary_floor_usd": 100000, "near_miss_salary_floor_usd": 90000}}, f)
    if outcomes:
        with open(cr.OUTCOMES, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["company", "title", "url", "stage"])
            w.writerows(outcomes)
    PAGES.clear()
    cr.live_read = lambda url, session=None: dict(PAGES[url]) if url in PAGES else {"error": "no such page"}
    return d


def mark(url, d="2026-11-25", **kw):
    m = {"a": "tailor", "d": d, "ts": 1, "u": url, "c": "Acme", "t": "Support Operations Manager",
         "s": 96.0, "g": "REACH: five years in a function he hasn't held"}
    m.update(kw)
    return m


def cached_day(day, url, text, card=True, suffix="", card_file="cards_batch_01.json", **card_kw):
    """One earlier run's dir: a txt in the Step 2-JD shape, its manifest entry, and a card."""
    d = os.path.join(cr.JOBS_DIR, "jd_cache", day + suffix)
    os.makedirs(d, exist_ok=True)
    name = f"{len(os.listdir(d)):02d}_{url.rsplit('/', 2)[-2]}.txt"
    txt = os.path.join(d, name)
    with open(txt, "w", encoding="utf-8") as f:
        f.write(f"COMPANY : Acme\nTITLE   : Support Operations Manager\nURL     : {url}\nATS     : fake\n"
                f"LOCATION: Remote   remote=True\nLISTING LOCATION: Remote, US\nPOSTED  : 2026-11-01\n"
                f"SALARY  : $120K-$150K\n{cr.RULE}\n{text}")
    mpath = os.path.join(d, "manifest.json")
    man = {"entries": []}
    if os.path.exists(mpath):
        with open(mpath, encoding="utf-8") as f:
            man = json.load(f)
    man["entries"].append({"source": "matched", "company": "Acme", "title": "x", "url": url, "file": txt,
                           "status": "ok"})
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(man, f)
    if card:
        c = {"file": "/somewhere/else/" + name, "url": url, "company": "Acme", "title": "Support Operations Manager",
             "read_ok": True, "work_mode": "remote_us", "atlanta_ok": "yes", "salary_min_usd": 120000,
             "salary_max_usd": 150000, "manages_people": "manages", "red_flags": []}
        c.update(card_kw)
        cpath = os.path.join(d, card_file)
        cards = []
        if os.path.exists(cpath):
            with open(cpath, encoding="utf-8") as f:
                cards = json.load(f)
        with open(cpath, "w", encoding="utf-8") as f:
            json.dump(cards + [c], f)
    return txt


def read(*flags):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cr.main(["--read", "--date", TODAY.isoformat(), *flags])
    out_dir = os.path.join(cr.JOBS_DIR, "jd_cache", f"{TODAY.isoformat()}_cleared")
    man = None
    if os.path.exists(os.path.join(out_dir, "manifest.json")):
        with open(os.path.join(out_dir, "manifest.json"), encoding="utf-8") as f:
            man = json.load(f)
    return rc, buf.getvalue(), man, out_dir


def entry(man, url):
    return next(e for e in man["entries"] if e["url"] == url)


# --- recording what the page sends ---------------------------------------------------------

def test_record_new_already_bad_and_the_first_answer_wins():
    fresh()
    p, n = cr.record({A: mark(A), "https://jobs.example.com/ACME/0001/": mark("https://jobs.example.com/ACME/0001/"),
                      "not a url": mark("not a url"), B: mark(B, a="pass"), C: "junk"}, TODAY)
    assert n == 1, (n, p)
    got = cr.load()
    assert set(got) == {A}, "two page keys for one posting record one request"
    e = got[A]
    assert e["marked"] == "2026-11-25" and e["recorded"] == "2026-11-26" and e["score"] == 96
    assert e["company"] == "Acme" and e["gap"].startswith("REACH") and e["action"] == "tailor"
    assert any("not a posting URL" in b for b in p["bad"]) and any("unknown action" in b for b in p["bad"])
    assert any("not an object" in b for b in p["bad"])
    # A stale mark from before the drain can't change a recorded request.
    p, n = cr.record({A: mark(A, d="2026-11-20", c="Other")}, TODAY)
    assert n == 0 and p["already"] == [A] and cr.load()[A]["company"] == "Acme"


def test_record_keeps_the_url_as_given_and_checks_the_score():
    fresh()
    url = "https://jobs.example.com/Nash/0005/"
    cr.record({cr.norm_url(url): mark(url, s=True), B: mark(B, s="96"), C: mark(C, s=10 ** 6)}, TODAY)
    got = cr.load()
    assert got[cr.norm_url(url)]["url"] == url, "the fetch needs the URL's own case"
    assert all("score" not in got[k] for k in got), "a bool, a string, or an absurd score is dropped"


def test_report_only_writes_nothing_and_a_bad_file_is_never_overwritten():
    fresh()
    p, n = cr.record({A: mark(A)}, TODAY, apply=False)
    assert n == 1 and not os.path.exists(cr.PATH)
    os.makedirs(os.path.dirname(cr.PATH), exist_ok=True)
    with open(cr.PATH, "w", encoding="utf-8") as f:
        f.write("{broken")
    try:
        cr.record({A: mark(A)}, TODAY)
        raise AssertionError("a malformed file must raise")
    except ValueError:
        pass
    with open(cr.PATH, encoding="utf-8") as f:
        assert f.read() == "{broken"
    assert cr.recorded_keys() == set(), "the dashboard's read never raises"


def test_pending_is_oldest_first_capped_and_skips_what_was_read():
    fresh()
    cr.save({A: {"action": "tailor", "marked": "2026-11-24"}, B: {"action": "tailor", "marked": "2026-11-21"},
             C: {"action": "tailor", "marked": "2026-11-20", "read": "2026-11-21"},
             D: {"action": "tailor", "marked": "2026-11-22"}})
    got, waiting = cr.pending(2)
    assert [g["key"] for g in got] == [B, D] and waiting == 3, (got, waiting)
    assert cr.stamp({B: ("live", ""), C: ("closed", "x"), "https://nope": ("live", "")}, TODAY) == 1
    assert cr.load()[B]["read"] == "2026-11-26" and cr.load()[C]["read"] == "2026-11-21"


def test_tier_is_full_whatever_the_score_and_priority_at_the_cap():
    cfg = {"company_cap_threshold": 110}
    assert cr.tier_for(123, cfg) == "priority" and cr.tier_for(110, cfg) == "priority"
    assert cr.tier_for(96, cfg) == "full" and cr.tier_for(80, cfg) == "full", "never light: he asked for it"
    assert cr.tier_for(None, cfg) == "full" and cr.tier_for(115, {}) == "priority"


# --- finding the earlier read ---------------------------------------------------------------

def test_body_key_ignores_the_header_and_this_modules_notes():
    t1 = f"COMPANY : Acme\nPOSTED  : 1\n{cr.RULE}\nOwn   the queue.\nCoach the team."
    t2 = (f"COMPANY : Acme Inc\nATS     : other\n{cr.RULE}\nOwn the queue. Coach the team.\n"
          "[truncated at 20000 of 25000 chars]\n[cached copy read 2026-11-20; the live read failed: x]\n")
    assert cr.body_key(t1) == cr.body_key(t2) == "Own the queue. Coach the team."


def test_cached_copy_is_the_newest_read_within_the_window_from_any_runs_dir():
    fresh()
    cached_day("2026-11-01", A, body("too old"))
    cached_day("2026-11-20", A, body("main run"))
    newest = cached_day("2026-11-24", A, body("linkedin run"), suffix="_linkedin")
    cached_day("2026-11-26", A, body("today's own dir is never a cached copy"))
    txt, day, card = cr.cached_copy(A.upper(), TODAY)
    assert txt == newest and day == datetime.date(2026, 11, 24) and card["read_ok"] is True
    assert cr.cached_copy("https://jobs.example.com/none/0009", TODAY) is None
    # A card a worker wrote that day wins over the reused copy, as in jd_screen_table.py.
    cached_day("2026-11-25", B, body("b"), card_file=cr.REUSED_CARDS, manages_people="ic")
    with open(os.path.join(cr.JOBS_DIR, "jd_cache", "2026-11-25", "cards_batch_01.json"), "w", encoding="utf-8") as f:
        json.dump([{"file": os.path.basename(cr.cached_copy(B, TODAY)[0]), "url": B, "read_ok": True,
                    "manages_people": "manages"}], f)
    assert cr.cached_copy(B, TODAY)[2]["manages_people"] == "manages"
    # A txt the manifest names but that's gone from disk isn't a copy.
    os.remove(cr.cached_copy(B, TODAY)[0])
    assert cr.cached_copy(B, TODAY) is None


# --- the Step 1d-4 read ---------------------------------------------------------------------

def test_unchanged_text_reuses_the_card_and_needs_no_worker():
    fresh()
    cached_day("2026-11-24", A, body("A"))
    cr.save({A: {"action": "tailor", "marked": "2026-11-25", "url": A, "company": "Acme",
                 "title": "Support Operations Manager", "score": 123}})
    PAGES[A] = {"ats": "fake", "title": "Support Operations Manager", "body": body("A")}
    rc, out, man, out_dir = read()
    assert rc == 0, out
    e = entry(man, A)
    assert e["read_status"] == "live" and e["reused_from"] == "2026-11-24" and e["tier"] == "priority", e
    assert not os.path.exists(os.path.join(out_dir, "batch_01.json")), "nothing for a worker to read"
    with open(os.path.join(out_dir, cr.REUSED_CARDS), encoding="utf-8") as f:
        cards = json.load(f)
    assert len(cards) == 1 and cards[0]["file"] == e["file"] and os.path.isfile(e["file"])
    assert cr.load()[A]["read_status"] == "live" and cr.load()[A]["read"] == "2026-11-26"
    assert "OK       Acme: Support Operations Manager (tier priority, score 123) card reused" in out, out


def test_changed_text_goes_to_a_worker_and_the_screen_table_reads_the_dir():
    d = fresh()
    cached_day("2026-11-24", A, body("A"))
    cached_day("2026-11-24", B, body("B"))
    for u, s in ((A, 96), (B, 84)):
        cr.save(dict(cr.load(), **{u: {"action": "tailor", "marked": "2026-11-25", "url": u,
                                        "company": "Acme", "title": "Support Operations Manager", "score": s}}))
    PAGES[A] = {"ats": "fake", "body": body("A, rewritten since")}
    PAGES[B] = {"ats": "fake", "body": body("B")}
    rc, out, man, out_dir = read()
    a, b = entry(man, A), entry(man, B)
    assert "reused_from" not in a and b["reused_from"] == "2026-11-24" and b["tier"] == "full"
    with open(os.path.join(out_dir, "batch_01.json"), encoding="utf-8") as f:
        assert json.load(f) == [a["file"]]
    assert cr.load()[A]["read_note"] == "text changed since the screen read it"
    # A worker cards the new text; jd_screen_table.py then joins both rows unchanged.
    with open(os.path.join(out_dir, "cards_batch_01.json"), "w", encoding="utf-8") as f:
        json.dump([{"file": a["file"], "url": A, "read_ok": True, "work_mode": "onsite", "atlanta_ok": "no",
                    "location_verbatim": "Elsewhere, on site"}], f)
    with open(os.path.join(d, "watchlist_companies.json"), "w", encoding="utf-8") as f:
        json.dump({"_scoring_config": {"salary_floor_usd": 100000, "near_miss_salary_floor_usd": 90000}}, f)
    here, argv = jst.HERE, sys.argv
    jst.HERE = d   # fresh() put jobs/ under d, the layout jd_screen_table.py expects
    sys.argv = ["jd_screen_table.py", "--date", f"{TODAY.isoformat()}_cleared"]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            assert jst.main() == 0
    finally:
        jst.HERE, sys.argv = here, argv
    with open(os.path.join(out_dir, "screen_table.json"), encoding="utf-8") as f:
        rows = {r["url"]: r for r in json.load(f)["rows"]}
    assert rows[B]["status"] == "PASS" and rows[A]["status"] == "FAIL", rows
    assert rows[A]["fails"][0].startswith("location"), "new text that moved on site fails its screen"


def test_closed_cached_unreadable_and_already_tracked():
    fresh(outcomes=[["Dune", "Support Lead", D + "/", "surfaced"]])
    cached_day("2026-11-23", B, body("B"))
    for u in (A, B, C, D):
        cr.save(dict(cr.load(), **{u: {"action": "tailor", "marked": "2026-11-25", "url": u,
                                        "company": "Acme", "title": "Support Operations Manager", "score": 90}}))
    PAGES[A] = {"error": "fetch_greenhouse: HTTPError: 404 Client Error: Not Found for url"}
    PAGES[B] = {"error": "fetch_ashby: ReadTimeout: read timed out"}
    PAGES[C] = {"error": "no fetcher matched this URL"}
    rc, out, man, out_dir = read("--max", "4")
    got = cr.load()
    assert got[A]["read_status"] == "closed" and "file" not in entry(man, A)
    assert got[B]["read_status"] == "cached" and "2026-11-23" in got[B]["read_note"]
    b = entry(man, B)
    assert b["cached_from"] == "2026-11-23" and b["reused_from"] == "2026-11-23" and "ReadTimeout" in b["live_error"]
    with open(b["file"], encoding="utf-8") as f:
        assert "[cached copy read 2026-11-23; the live read failed: fetch_ashby: ReadTimeout" in f.read()
    assert got[C]["read_status"] == "unreadable" and entry(man, C)["status"] == "error"
    assert got[D]["read_status"] == "already in the tracker (surfaced)"
    assert entry(man, D)["status"].startswith("skipped: already in outcomes.csv")
    for word in ("CLOSED", "CACHED", "UNREAD", "SKIPPED"):
        assert f"  {word} " in out, out


def test_the_cap_leaves_the_rest_waiting_and_a_dry_run_reads_nothing():
    fresh()
    urls = (A, B, C, D, "https://jobs.example.com/eddy/0005", "https://jobs.example.com/fern/0006")
    for i, u in enumerate(urls):
        cr.save(dict(cr.load(), **{u: {"action": "tailor", "marked": f"2026-11-2{i}", "url": u, "score": 90}}))
        PAGES[u] = {"ats": "fake", "body": body(u)}
    rc, out, man, _ = read("--dry-run")
    assert man is None and "6 waiting" in out and not any(v.get("read") for v in cr.load().values())
    rc, out, man, _ = read()
    assert cr.CLEARED_MAX == 5, "his call, 2026-11-26"
    assert man["counts"]["selected"] == 5 and man["counts"]["waiting_before"] == 6
    assert [k for k, v in cr.load().items() if not v.get("read")] == [urls[-1]], "the newest click rolls to the next run"


def test_a_linkedin_posting_url_goes_through_the_guest_endpoint():
    import fetch_jd
    import linkedin_followup as lf
    real_li, real_jd, li = lf.fetch, fetch_jd.fetch, "https://www.linkedin.com/jobs/view/4000000001/"
    try:
        calls = []
        lf.fetch = lambda session, jid: calls.append(jid) or {"body": body("li"), "closed": False}
        fetch_jd.fetch = lambda url: calls.append(url) or {"ats": "fake", "body": body("ats")}
        rec = REAL_LIVE_READ(li)
        assert calls == ["4000000001"] and rec["ats"] == "linkedin-guest"
        assert REAL_LIVE_READ(A)["ats"] == "fake" and calls[-1] == A, "any other URL goes to fetch_jd"
        lf.fetch = lambda session, jid: {"error": "429", "throttled": True}
        assert REAL_LIVE_READ(li) == {"error": "LinkedIn returned 429"}, "a throttle is a failed read, not a closed posting"
        lf.fetch = lambda session, jid: {"body": "x", "closed": True}
        assert REAL_LIVE_READ(li)["closed"] is True
    finally:
        lf.fetch, fetch_jd.fetch = real_li, real_jd


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"{len(fns)} passed")
