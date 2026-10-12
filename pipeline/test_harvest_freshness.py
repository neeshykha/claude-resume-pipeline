"""Unit-check the frozen-board check in harvest_ats. No network.

Added 2026-10-11. The harvester used to enroll any board that answered with
fit-titles on it, and a board keeps answering after its company has moved to
another ATS: one was enrolled on 77 postings whose newest was 81 days old. Now
the probes that can see posting dates report the newest one, and main() will
not enroll a board whose newest posting is older than FROZEN_BOARD_DAYS.

What is pinned here:
  - each dated probe reads the date field the poller reads, and still returns
    the same [(title, location)] list it always did;
  - a probe with no dates to read leaves the answer at None, and None is never
    treated as frozen (those ATSes enroll exactly as before);
  - a frozen board is written as a rejection for manual review, with
    unpollable FALSE, and never reaches the watchlist;
  - --skip-freshness is the only way past the check, --names is not.

Every company and slug below is made up, and every date is built from today's
so the cases do not age. The end-to-end cases run main() against TEMP copies
of the two data files; the real ones are never opened for writing.
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harvest_ats as H
import poll_ats as P

TODAY = date.today()


class PinnedDate(date):
    """`date` whose today() is TODAY, so a run that crosses midnight cannot
    put the fixtures and the code under test on different days. main() swaps
    it in for the `date` name both modules read."""

    @classmethod
    def today(cls):
        return TODAY


FRESH = TODAY - timedelta(days=5)
OLD = TODAY - timedelta(days=200)
AT_CUTOFF = TODAY - timedelta(days=H.FROZEN_BOARD_DAYS)
PAST_CUTOFF = TODAY - timedelta(days=H.FROZEN_BOARD_DAYS + 1)

FIT = "Support Operations Manager"
LOC = "Remote - USA"


class FakeResponse:
    def __init__(self, status=200, payload=None, url=""):
        self.status_code = status
        self._payload = payload
        self.text = ""
        self.url = url
        self.headers = {}

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class OneBoard:
    """`requests` stand-in that answers every GET or POST with one payload."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def get(self, url, **_kw):
        self.calls += 1
        return FakeResponse(200, self.payload, url=url)

    post = get


def _with_fake_requests(fake, fn):
    real = H.requests
    H.requests = fake
    H._SERVICE_LAST_HIT.clear()
    try:
        return fn()
    finally:
        H.requests = real


def _iso(d, hour=12):
    return f"{d.isoformat()}T{hour:02d}:00:00+00:00"


def _dated_payload(ats, dates):
    """One posting per date, in the list shape that ATS really returns."""
    if ats == "greenhouse":
        return {"jobs": [{"title": FIT, "location": {"name": LOC},
                          "first_published": _iso(d), "updated_at": _iso(TODAY)}
                         for d in dates]}
    if ats == "ashby":
        return {"jobs": [{"title": FIT, "location": LOC, "publishedAt": _iso(d)}
                         for d in dates]}
    if ats == "lever":
        return [{"text": FIT, "categories": {"location": LOC},
                 "createdAt": int(datetime(d.year, d.month, d.day, 12).timestamp() * 1000)}
                for d in dates]
    if ats == "workable":
        return {"jobs": [{"title": FIT, "city": "", "state": "",
                          "country": "United States", "telecommuting": True,
                          "published_on": d.isoformat()} for d in dates]}
    if ats == "smartrecruiters":
        return {"totalFound": len(dates),
                "content": [{"name": FIT, "location": {"fullLocation": LOC},
                             "releasedDate": _iso(d).replace("+00:00", "Z")}
                            for d in dates]}
    raise AssertionError(ats)


DATED_ATSES = ("greenhouse", "ashby", "lever", "workable", "smartrecruiters")

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


@case
def each_dated_probe_reports_the_newest_posting():
    """The newest of three dates comes back, whatever order the board lists them in."""
    got = {}
    for ats in DATED_ATSES:
        fake = OneBoard(_dated_payload(ats, [OLD, FRESH, PAST_CUTOFF]))
        jobs = _with_fake_requests(fake, lambda: H.probe(ats, "acme"))
        got[ats] = (getattr(jobs, "newest", "missing"), len(jobs))
    return all(v == (FRESH, 3) for v in got.values()), got


@case
def a_dated_probe_still_reads_as_the_same_plain_list():
    """Postings must not change what any existing caller sees."""
    fake = OneBoard(_dated_payload("greenhouse", [FRESH]))
    jobs = _with_fake_requests(fake, lambda: H.probe("greenhouse", "acme"))
    ok = (isinstance(jobs, list) and jobs == [(FIT, LOC)]
          and [t for t, _ in jobs] == [FIT] and bool(jobs) and len(jobs) == 1)
    return ok, jobs


@case
def greenhouse_prefers_first_published_over_a_recent_edit():
    """updated_at is today on every fixture posting; the date read is the publish date."""
    fake = OneBoard(_dated_payload("greenhouse", [OLD]))
    jobs = _with_fake_requests(fake, lambda: H.probe("greenhouse", "acme"))
    return jobs.newest == OLD, jobs.newest


@case
def postings_without_a_date_field_read_as_unknown():
    """A dated ATS whose payload carries no date answers None, not a guess."""
    payload = {"jobs": [{"title": FIT, "location": {"name": LOC}}]}
    jobs = _with_fake_requests(OneBoard(payload), lambda: H.probe("greenhouse", "acme"))
    return jobs.newest is None and H.board_age_days({"newest_posting": jobs.newest}) is None, None


@case
def a_malformed_date_is_skipped_and_never_raises():
    """A probe that raises aborts the whole harvest, so a bad date must cost nothing.

    Each bad value is one the poller's parser does not catch on its own: a
    number where a string belongs, and a timestamp far outside the platform's
    range. The good posting beside them still dates the board.
    """
    ashby = {"jobs": [{"title": FIT, "location": LOC, "publishedAt": 20260101},
                      {"title": FIT, "location": LOC, "publishedAt": _iso(FRESH)}]}
    lever = [{"text": FIT, "categories": {"location": LOC}, "createdAt": 10 ** 30},
             {"text": FIT, "categories": {"location": LOC}, "createdAt": "soon"}]
    try:
        a = _with_fake_requests(OneBoard(ashby), lambda: H.probe("ashby", "acme"))
        l = _with_fake_requests(OneBoard(lever), lambda: H.probe("lever", "acme"))
    except Exception as e:
        return False, f"raised {type(e).__name__}: {e}"
    return (a.newest, len(a), l.newest, len(l)) == (FRESH, 2, None, 2), (a.newest, l.newest)


@case
def an_undated_ats_leaves_the_answer_unknown():
    """Pinpoint shows no posting date, so its probe must never claim one."""
    payload = {"data": [{"title": FIT, "location": {"name": LOC},
                         "deadline_at": _iso(OLD)}]}
    jobs = _with_fake_requests(OneBoard(payload), lambda: H.probe("pinpoint", "acme"))
    return jobs == [(FIT, LOC)] and getattr(jobs, "newest", None) is None, jobs


@case
def a_smartrecruiters_miss_is_still_none():
    """The None-never-[] rule survives the Postings change: an empty page one is no board."""
    payload = {"totalFound": 0, "content": []}
    got = _with_fake_requests(OneBoard(payload),
                              lambda: H.probe("smartrecruiters", "Acme"))
    return got is None, got


@case
def comeet_reads_time_updated_and_ignores_a_future_one():
    rows = [{"name": FIT, "time_updated": _iso(OLD)},
            {"name": FIT, "time_updated": _iso(FRESH)},
            {"name": FIT, "time_updated": _iso(TODAY + timedelta(days=30))}]
    got = H._newest_posted(rows, "comeet")
    return got == FRESH, got


class patched_resolver:
    """Swap poll_ats._resolve_workday_start_date for one that answers from a dict."""

    def __init__(self, answers):
        self.answers = answers
        self.asked = []

    def __enter__(self):
        self.real = P._resolve_workday_start_date

        def fake(url):
            self.asked.append(url)
            return self.answers.get(url)
        P._resolve_workday_start_date = fake
        return self

    def __exit__(self, *_exc):
        P._resolve_workday_start_date = self.real
        return False


BOARD_URL = "https://acme.wd1.myworkdayjobs.com/wday/cxs/acme/Careers"


@case
def workday_relative_dates_need_no_detail_lookup():
    """Any exact "N Days Ago" settles it; the floors beside it are never resolved."""
    postings = [{"postedOn": "Posted 30+ Days Ago", "externalPath": "/job/a"},
                {"postedOn": "Posted 12 Days Ago", "externalPath": "/job/b"},
                {"postedOn": "Posted Yesterday", "externalPath": "/job/c"}]
    with patched_resolver({}) as r:
        got = H._workday_newest(postings, BOARD_URL)
    return got == TODAY - timedelta(days=1) and r.asked == [], (got, r.asked)


@case
def a_workday_page_of_floors_is_resolved_a_few_postings_deep():
    """All "30+": the first WORKDAY_FLOOR_LOOKUPS are resolved and the newest wins."""
    postings = [{"postedOn": "Posted 30+ Days Ago", "externalPath": f"/job/{i}"}
                for i in range(8)]
    answers = {f"{BOARD_URL}/job/0": OLD, f"{BOARD_URL}/job/1": PAST_CUTOFF,
               f"{BOARD_URL}/job/5": FRESH}
    with patched_resolver(answers) as r:
        got = H._workday_newest(postings, BOARD_URL)
    ok = got == PAST_CUTOFF and len(r.asked) == H.WORKDAY_FLOOR_LOOKUPS
    return ok, (got, r.asked)


@case
def unresolved_workday_floors_are_unknown_not_thirty_days():
    """A failed detail read must not turn the floor into a date."""
    postings = [{"postedOn": "Posted 30+ Days Ago", "externalPath": "/job/a"}]
    with patched_resolver({}):
        got = H._workday_newest(postings, BOARD_URL)
    return got is None, got


@case
def workday_fields_that_are_not_text_do_not_raise():
    """A number where a string belongs, and a day count too large for a date,
    are skipped; the floor beside them is still resolved."""
    postings = [{"postedOn": 12345, "externalPath": "/job/a"},
                {"postedOn": "Posted 99999999999 Days Ago", "externalPath": "/job/b"},
                {"postedOn": "Posted 30+ Days Ago", "externalPath": 7}]
    try:
        with patched_resolver({f"{BOARD_URL}7": OLD}) as r:
            got = H._workday_newest(postings, BOARD_URL)
    except Exception as e:
        return False, f"raised {type(e).__name__}: {e}"
    return got == OLD and r.asked == [f"{BOARD_URL}7"], (got, r.asked)


@case
def probe_workday_hands_the_date_to_assess():
    """The date travels in probe_workday's meta, beside the board's address."""
    payload = {"total": 2, "jobPostings": [
        {"title": FIT, "locationsText": LOC, "postedOn": "Posted 3 Days Ago",
         "externalPath": "/job/a"},
        {"title": FIT, "locationsText": LOC, "postedOn": "Posted 30+ Days Ago",
         "externalPath": "/job/b"}]}
    with patched_resolver({}):
        jobs, meta = _with_fake_requests(OneBoard(payload),
                                         lambda: H.probe_workday("acme"))
    ok = len(jobs) == 2 and meta["newest_posting"] == TODAY - timedelta(days=3)
    return ok, meta


class FakeMatcher:
    """Stands in for poll_ats.TitleMatcher: one tier1 title, nothing else."""

    def match_exact(self, title):
        return ("tier1_true_match",) if FIT.lower() in (title or "").lower() else None


class LeverOnly:
    """`requests` stand-in with one Lever board; every other address 404s."""

    def __init__(self, slug, payload):
        self.slug, self.payload = slug, payload

    def get(self, url, **_kw):
        if f"api.lever.co/v0/postings/{self.slug}?" in url:
            return FakeResponse(200, self.payload, url=url)
        if "smartrecruiters.com" in url:
            return FakeResponse(200, {"totalFound": 0, "content": []}, url=url)
        return FakeResponse(404, url=url)

    def post(self, url, **_kw):
        return FakeResponse(200, [{"data": {"jobBoardExternal": None}}], url=url)


@case
def assess_carries_the_date_on_its_result():
    """The cheap walk copies Postings.newest onto the result main() reads."""
    fake = LeverOnly("acme", _dated_payload("lever", [OLD, PAST_CUTOFF]))
    saved = H.DELAY
    H.DELAY = 0.001
    try:
        res = _with_fake_requests(fake, lambda: H.assess(
            "Acme", FakeMatcher(), lambda _t: False, set(),
            skip_workday=True, skip_comeet=True, budget_seconds=0))
    finally:
        H.DELAY = saved
    ok = ((res["ats"], res["slug"]) == ("lever", "acme")
          and res["newest_posting"] == PAST_CUTOFF
          and H.board_age_days(res) == H.FROZEN_BOARD_DAYS + 1)
    return ok, res


def _result(newest, **extra):
    """An assess() result for a board with one tier1 fit-title."""
    res = {"ats": "lever", "slug": "zzq-freshness-fixture", "total": 7,
           "strong": [(FIT, LOC, "tier1_true_match")], "titles": [FIT]}
    if newest != "absent":
        res["newest_posting"] = newest
    res.update(extra)
    return res


def _run_main(name, assess_result, flags=("--apply",), pending=None, rejected=None):
    """Run main() for one name against TEMP copies of both data files.

    assess() is replaced with one returning `assess_result`, so this exercises
    the check and the writers and nothing else. `pending` and `rejected` seed
    one record each for the name before the run. Returns what main() printed,
    then the name's watchlist entries, `enrolled` records, `rejected` records,
    and `pending` entries, read back from the temp files.
    """
    tmp = tempfile.mkdtemp(prefix="harvest_freshness_test_")
    saved = (H.WATCHLIST, H.QUEUE, H.assess, sys.argv)
    try:
        wl_path = os.path.join(tmp, "watchlist_companies.json")
        q_path = os.path.join(tmp, "enrollment_candidates.json")
        shutil.copyfile(saved[0], wl_path)
        shutil.copyfile(saved[1], q_path)
        if pending or rejected:
            with open(q_path, encoding="utf-8") as f:
                q = json.load(f)
            if pending:
                q.setdefault("pending", []).append(dict(pending, name=name))
            if rejected:
                q.setdefault("rejected", []).append(dict(rejected, name=name))
            with open(q_path, "w", encoding="utf-8") as f:
                json.dump(q, f, indent=2)
                f.write("\n")
        before = (open(wl_path, "rb").read(), open(q_path, "rb").read())
        H.WATCHLIST, H.QUEUE = wl_path, q_path
        H.assess = lambda *_a, **_k: assess_result
        sys.argv = ["harvest_ats.py", "--names", name, *flags]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            H.main()
        unchanged = before == (open(wl_path, "rb").read(), open(q_path, "rb").read())
        with open(wl_path, encoding="utf-8") as f:
            wl = json.load(f)
        with open(q_path, encoding="utf-8") as f:
            q = json.load(f)

        def mine(rows):
            return [r for r in rows if r.get("name") == name]
        return {"out": out.getvalue(), "unchanged": unchanged,
                "watchlist": mine(wl["companies"]), "enrolled": mine(q.get("enrolled", [])),
                "rejected": mine(q.get("rejected", [])), "pending": mine(q.get("pending", []))}
    finally:
        H.WATCHLIST, H.QUEUE, H.assess, sys.argv = saved
        shutil.rmtree(tmp, ignore_errors=True)


NAME = "Zzq Freshness Fixture Co"


@case
def a_frozen_board_is_rejected_for_manual_review_and_never_enrolled():
    """End to end: fit-titles and an old newest posting -> a rejection, not an enrollment.

    unpollable must be False (the board WAS found), manual_review True, and the
    board's address and newest date stay on the record.
    """
    got = _run_main(NAME, _result(OLD))
    rec = got["rejected"][0] if len(got["rejected"]) == 1 else {}
    ok = (not got["watchlist"] and not got["enrolled"]
          and rec.get("frozen_board") is True
          and rec.get("unpollable") is False
          and rec.get("manual_review") is True
          and not rec.get("manual_review_surfaced")
          and rec.get("recheck_if_resurfaced") is True
          and (rec.get("ats"), rec.get("slug")) == ("lever", "zzq-freshness-fixture")
          and rec.get("newest_posting") == OLD.isoformat()
          and rec.get("reason", "").startswith("BOARD LOOKS FROZEN")
          and OLD.isoformat() in rec.get("manual_review_why", "")
          and "[FZ]" in got["out"] and "frozen=1" in got["out"])
    return ok, {k: rec.get(k) for k in ("frozen_board", "unpollable", "manual_review",
                                         "newest_posting", "manual_review_why")}


@case
def the_cutoff_is_exclusive():
    """Exactly FROZEN_BOARD_DAYS old still enrolls; one day older does not."""
    at = _run_main(NAME, _result(AT_CUTOFF))
    past = _run_main(NAME, _result(PAST_CUTOFF))
    ok = (len(at["watchlist"]) == 1 and not at["rejected"]
          and not past["watchlist"] and len(past["rejected"]) == 1)
    return ok, (len(at["watchlist"]), len(past["rejected"]))


@case
def a_fresh_board_enrolls_and_records_its_newest_posting():
    got = _run_main(NAME, _result(FRESH))
    entry = got["watchlist"][0] if len(got["watchlist"]) == 1 else {}
    ok = (len(got["enrolled"]) == 1 and not got["rejected"]
          and f"newest posting {FRESH.isoformat()}" in entry.get("reason", "")
          and "newest_posting" not in entry and "[OK]" in got["out"])
    return ok, entry.get("reason", "")[:120]


@case
def a_board_with_no_dates_enrolls_exactly_as_before():
    """None, and a result with no newest_posting key at all, both pass the check."""
    none = _run_main(NAME, _result(None))
    absent = _run_main(NAME, _result("absent"))
    reason = none["watchlist"][0]["reason"] if none["watchlist"] else ""
    ok = (len(none["watchlist"]) == 1 and len(absent["watchlist"]) == 1
          and not none["rejected"] and not absent["rejected"]
          and "frozen-board check did not run" in reason)
    return ok, reason[:120]


@case
def skip_freshness_enrolls_a_frozen_board_and_says_so():
    """The hand override, and the only one: --names alone was refused above."""
    got = _run_main(NAME, _result(OLD), flags=("--apply", "--skip-freshness"))
    reason = got["watchlist"][0]["reason"] if got["watchlist"] else ""
    ok = (len(got["watchlist"]) == 1 and not got["rejected"]
          and "--skip-freshness" in reason and OLD.isoformat() in reason)
    return ok, reason[:200]


@case
def a_dry_run_reports_the_frozen_board_and_writes_nothing():
    got = _run_main(NAME, _result(OLD), flags=())
    return got["unchanged"] and "[FZ]" in got["out"] and "FROZEN BOARDS" in got["out"], None


@case
def the_linkedin_role_and_provenance_survive_on_a_frozen_record():
    """A queued company keeps its card role, source, and first_seen, and leaves pending."""
    card_why = f"{FIT} [Remote US] -- tier1 title, Remote US; fixture card 1"
    got = _run_main(NAME, _result(OLD), pending={
        "why": "fixture", "source": "fixture_channel", "first_seen": "2026-01-02",
        "manual_review": True, "manual_review_why": card_why,
        "card_title": FIT, "card_job_id": "1"})
    rec = got["rejected"][0] if len(got["rejected"]) == 1 else {}
    why = rec.get("manual_review_why", "")
    ok = (why.startswith(card_why) and "looks frozen" in why
          and rec.get("source") == "fixture_channel"
          and rec.get("first_seen") == "2026-01-02"
          and rec.get("card_title") == FIT and rec.get("card_job_id") == "1"
          and not got["pending"])
    return ok, why


@case
def a_frozen_board_with_a_refused_probe_is_queued_for_recheck():
    """The live board may be behind the probe that was refused, so the record
    must carry the flag Step 6.7 picks on; with nothing refused it must not."""
    got = _run_main(NAME, _result(OLD, throttled_probes=[("workable", "zzq")]))
    contrast = _run_main(NAME, _result(OLD))
    rec = got["rejected"][0] if len(got["rejected"]) == 1 else {}
    plain = contrast["rejected"][0] if len(contrast["rejected"]) == 1 else {}
    ok = (rec.get("throttled") is True and rec.get("throttled_probes") == ["workable/zzq"]
          and "rate-limited" in rec.get("reason", "")
          and rec.get("frozen_board") is True and rec.get("unpollable") is False
          and "throttled" not in plain)
    return ok, ({k: rec.get(k) for k in ("throttled", "throttled_probes")},
                {k: plain.get(k) for k in ("throttled",)})


# A rejection an earlier run wrote and the digest already showed him.
SHOWN = {"ats": None, "slug": None, "rejected_date": "2026-01-02", "reason": "fixture",
         "recheck_if_resurfaced": True, "unpollable": False,
         "manual_review": True, "manual_review_why": "fixture role",
         "manual_review_surfaced": True}


@case
def a_frozen_finding_is_new_even_when_an_older_record_was_shown():
    """Superseding a surfaced rate-limit record must not mark the frozen one shown.

    The contrast is the same board found frozen a second time: that one was
    shown already, and must stay quiet.
    """
    first = _run_main(NAME, _result(OLD), rejected=dict(SHOWN, throttled=True))
    again = _run_main(NAME, _result(OLD), rejected=dict(SHOWN, frozen_board=True))
    a = first["rejected"][0] if len(first["rejected"]) == 1 else {}
    b = again["rejected"][0] if len(again["rejected"]) == 1 else {}
    ok = (a.get("frozen_board") is True and "manual_review_surfaced" not in a
          and "superseded_note" in a
          and b.get("frozen_board") is True and b.get("manual_review_surfaced") is True)
    return ok, (a.get("manual_review_surfaced"), b.get("manual_review_surfaced"))


@case
def enrolling_a_frozen_board_by_hand_closes_its_record():
    """After --skip-freshness the old record stays as history and stops asking."""
    got = _run_main(NAME, _result(OLD), flags=("--apply", "--skip-freshness"),
                    rejected={"ats": "lever", "slug": "zzq-freshness-fixture",
                              "rejected_date": "2026-01-02", "reason": "fixture",
                              "frozen_board": True, "newest_posting": OLD.isoformat(),
                              "recheck_if_resurfaced": True, "unpollable": False,
                              "manual_review": True, "manual_review_why": "fixture"})
    rec = got["rejected"][0] if len(got["rejected"]) == 1 else {}
    ok = (len(got["watchlist"]) == 1 and len(got["enrolled"]) == 1
          and rec.get("superseded_by_enrollment") and rec.get("manual_review_surfaced") is True
          and rec.get("recheck_if_resurfaced") is False and rec.get("unpollable") is False
          and rec.get("frozen_board") is True)
    return ok, {k: rec.get(k) for k in ("superseded_by_enrollment", "manual_review_surfaced")}


def main():
    passed = 0
    real = (H.date, P.date)
    H.date = P.date = PinnedDate
    try:
        for fn in CASES:
            ok, detail = fn()
            print(f"  [{'ok ' if ok else 'FAIL'}] {fn.__name__}"
                  + (f"   {detail}" if not ok or detail else ""))
            passed += bool(ok)
    finally:
        H.date, P.date = real
    print(f"  {passed}/{len(CASES)} passed")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
