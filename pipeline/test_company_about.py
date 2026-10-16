#!/usr/bin/env python3
"""Tests for company_about.py (2026-10-15). Fixtures are made up and live in a temp dir;
nothing here touches the network (the fetch, the clock, and the sleeps are replaced).

    .venv/bin/python pipeline/test_company_about.py
"""
import datetime
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import company_about as ca  # noqa: E402
import build_dashboard as bd  # noqa: E402

TODAY = datetime.date(2026, 10, 15)

POSTING = ('<a class="topcard__org-name-link topcard__flavor--black-link" '
           'href="https://www.linkedin.com/company/brevik-labs?trk=public_jobs_topcard-org-name">Brevik</a>'
           '<a href="https://www.linkedin.com/company/linkedin?trk=footer">LinkedIn</a>')
SCHOOL_POSTING = ('<a class="topcard__org-name-link" href="https://www.linkedin.com/school/'
                  'north-ridge-university/?trk=public_jobs_topcard-org-name">North Ridge</a>')
COMPANY = """
<p class="break-words" data-test-id="about-us__description">
    Brevik keeps field crews moving. &amp; nothing else.

We help service teams plan, dispatch, and close work orders in one system, with AI in the loop.

For the people doing the work, that means fewer trips.
</p>
<div data-test-id="about-us__industry"><dt>Industry</dt><dd>
      Software Development
</dd></div>
<div data-test-id="about-us__size"><dt>Company size</dt><dd>

        201-500 employees
</dd></div>
"""
META_ONLY = ('<meta name="description" content="North Ridge | 9,876 followers on LinkedIn. '
             'Learn here | North Ridge is a public research university in a mid-sized city.">')


def fake_fetch(pages):
    calls = []

    def fetch(url):
        calls.append(url)
        v = pages.get(url, "")
        if isinstance(v, Exception):
            raise v
        return v
    return fetch, calls


def lead(jid, company="Brevik"):
    return {"id": jid, "company": company, "title": "Head of Support"}


def cache_path():
    return os.path.join(tempfile.mkdtemp(prefix="about_test_"), "jobs", ca.CACHE_NAME)


def test_slug_comes_from_the_top_card_only():
    assert ca.company_slug(POSTING) == "company/brevik-labs"
    assert ca.company_slug(SCHOOL_POSTING) == "school/north-ridge-university"
    assert ca.company_slug('<a href="https://www.linkedin.com/company/linkedin?trk=footer">') is None
    assert ca.company_slug("") is None and ca.company_slug(None) is None


def test_parse_company_and_blurb():
    info = ca.parse_company(COMPANY)
    assert info["about"] == ("Brevik keeps field crews moving. & nothing else. We help service teams "
                             "plan, dispatch, and close work orders in one system, with AI in the loop."), info
    assert info["industry"] == "Software Development" and info["size"] == "201-500 employees"
    meta = ca.parse_company(META_ONLY)
    assert meta["about"] == "North Ridge is a public research university in a mid-sized city.", meta
    assert ca.parse_company("<html></html>") == {"about": "", "industry": "", "size": ""}


def test_blurb_caps_long_text_at_a_word():
    long = "Brevik " + "builds very useful things " * 20 + "for everyone."
    b = ca.blurb(long)
    assert len(b) <= ca.BLURB_MAX + 1 and b.endswith("…") and not b.endswith(" …"), b
    assert ca.blurb("Short one. Another short one. A third.") == "Short one. Another short one. A third."
    assert ca.blurb("Rocket \U0001F680 maker.") == "Rocket maker."


def test_fill_hits_misses_and_skips_fresh():
    path = cache_path()
    fetch, calls = fake_fetch({
        ca.POSTING_URL.format(id="1000001"): POSTING,
        ca.COMPANY_URL.format(slug="company/brevik-labs"): COMPANY,
        ca.POSTING_URL.format(id="1000002"): None,             # closed posting
        ca.POSTING_URL.format(id="1000003"): "<html>no org</html>",
    })
    leads = [lead("1000001"), lead("1000009"),                # same company twice: one lookup
             lead("1000002", "Gone Co"), lead("1000003", "Linkless"),
             lead("abc", "Bad Id"), "junk", lead("1000004", "")]
    s = ca.fill(leads, path, TODAY, fetch=fetch, sleep=lambda s: None)
    assert s == {"looked_up": 3, "hits": 1, "misses": 2, "cached": 0, "left": 0, "stopped": ""}, s
    with open(path, encoding="utf-8") as f:
        comps = json.load(f)["companies"]
    assert comps["brevik"]["slug"] == "company/brevik-labs" and comps["brevik"]["size"] == "201-500 employees"
    assert comps["goneco"]["miss"] == "posting closed" and comps["goneco"]["retry"] == "2026-10-29"
    assert comps["linkless"]["miss"] == "no company link on the posting"
    n = len(calls)
    s = ca.fill(leads, path, TODAY, fetch=fetch, sleep=lambda s: None)
    assert s["looked_up"] == 0 and s["cached"] == 3 and len(calls) == n, "fresh entries are not fetched again"
    later = TODAY + datetime.timedelta(days=ca.MISS_DAYS)
    s = ca.fill(leads, path, later, fetch=fetch, sleep=lambda s: None)
    assert s["looked_up"] == 2, "a miss is retried after MISS_DAYS; a hit is kept"


def test_network_error_is_a_one_day_miss():
    path = cache_path()
    fetch, _ = fake_fetch({ca.POSTING_URL.format(id="1000001"): ca.requests.ConnectionError("down")})
    ca.fill([lead("1000001")], path, TODAY, fetch=fetch, sleep=lambda s: None)
    e = ca.load_cache(path)["companies"]["brevik"]
    assert e["miss"] == "error: ConnectionError" and e["retry"] == "2026-10-16"


def test_throttle_backs_off_then_stops():
    path = cache_path()
    state = {"n": 0}
    slept = []

    def fetch(url):
        if url.startswith(ca.POSTING_URL.format(id="1000002")):
            raise ca.Throttled("HTTP 429")
        if "jobPosting" in url:
            return POSTING.replace("brevik-labs", "co-" + url[-7:])
        state["n"] += 1
        return COMPANY

    leads = [lead("1000001", "Alpha"), lead("1000002", "Beta"), lead("1000003", "Gamma")]
    s = ca.fill(leads, path, TODAY, fetch=fetch, sleep=slept.append, backoff=7)
    assert s["looked_up"] == 1 and s["left"] == 2 and s["stopped"].startswith("throttled"), s
    assert slept.count(7) == ca.RETRIES - 1, slept
    assert "beta" not in ca.load_cache(path)["companies"], "a throttled lookup leaves no entry"


def test_throttle_that_clears_carries_on():
    path = cache_path()
    tries = {"n": 0}

    def fetch(url):
        if "jobPosting/1000002" in url and tries["n"] < 1:
            tries["n"] += 1
            raise ca.Throttled("HTTP 429")
        return POSTING if "jobPosting" in url else COMPANY

    leads = [lead("1000001", "Alpha"), lead("1000002", "Beta"), lead("1000003", "Gamma")]
    s = ca.fill(leads, path, TODAY, fetch=fetch, sleep=lambda s: None)
    assert s["looked_up"] == 3 and s["left"] == 0 and not s["stopped"], s


def test_refused_pages_school_is_a_miss_two_companies_stop():
    path = cache_path()

    def fetch(url):
        if "jobPosting/1000001" in url:
            return SCHOOL_POSTING
        if "jobPosting" in url:
            return POSTING.replace("brevik-labs", "co-" + url[-7:])
        raise ca.Throttled("HTTP 999")

    leads = [lead("1000001", "North Ridge"), lead("1000002", "Alpha"), lead("1000003", "Beta"),
             lead("1000004", "Gamma")]
    s = ca.fill(leads, path, TODAY, fetch=fetch, sleep=lambda s: None)
    assert s["looked_up"] == 3 and s["left"] == 1 and s["stopped"] == "2 company pages refused in a row", s
    comps = ca.load_cache(path)["companies"]
    assert comps["northridge"]["retry"] == "2026-10-29" and not comps["northridge"]["refused"]
    assert comps["alpha"]["refused"] and comps["alpha"]["retry"] == "2026-10-16"


def test_budget_stops_and_counts_what_is_left():
    path = cache_path()
    fetch, _ = fake_fetch({})
    ticks = iter([0, 0, 50, 200])
    s = ca.fill([lead("1000001", "A"), lead("1000002", "B"), lead("1000003", "C")], path, TODAY,
                budget=100, fetch=fetch, sleep=lambda s: None, clock=lambda: next(ticks))
    assert s["looked_up"] == 2 and s["left"] == 1 and s["stopped"] == "budget of 100s", s


def test_dashboard_key_matches_and_lead_gets_its_line():
    for name in ("Brevik", "NWD (Northwind Data Sciences)", "7G", "Brevik Group AG", "Ünder.io", ""):
        assert bd.company_key(name) == ca.norm(name), name
    d = tempfile.mkdtemp(prefix="about_dash_")
    bd.JOBS_DIR = os.path.join(d, "jobs")
    os.makedirs(bd.JOBS_DIR)
    with open(os.path.join(bd.JOBS_DIR, ca.CACHE_NAME), "w", encoding="utf-8") as f:
        json.dump({"companies": {
            "brevik": {"about": "Makes <b>field</b> software.", "industry": "Software", "size": "11-50 employees",
                       "checked": "2026-10-15"},
            "goneco": {"miss": "posting closed", "checked": "2026-10-15", "retry": "2026-10-29"},
            "junk": "not a dict"}}, f)
    about = bd.read_company_about()
    assert set(about) == {"brevik"} and about["brevik"]["size"] == "11-50 employees", about
    with open(os.path.join(bd.JOBS_DIR, "weekly_leads_2026-10-15.json"), "w", encoding="utf-8") as f:
        json.dump({"leads": [dict(lead("4000001"), list="unreachable"),
                             dict(lead("4000002", "Gone Co"), list="unreachable")]}, f)
    rows = bd.read_leads(TODAY)["rows"]
    assert rows[0]["about"] == "Makes <b>field</b> software." and rows[0]["industry"] == "Software"
    assert "about" not in rows[1], "a miss adds nothing to its row"
    with open(os.path.join(bd.JOBS_DIR, ca.CACHE_NAME), "w", encoding="utf-8") as f:
        f.write("{broken")
    assert bd.read_company_about() == {}, "a malformed cache hides nothing and breaks nothing"
    assert len(bd.read_leads(TODAY)["rows"]) == 2


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
