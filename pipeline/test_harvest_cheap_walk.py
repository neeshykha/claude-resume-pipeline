"""Unit-check the cheap-ATS slug walk in harvest_ats.assess(). No network.

Added 2026-09-17 with probe_cheap(), which turned that walk from eight
sequential probes per slug into eight concurrent ones. The fan-out is only safe
because the ANSWERS are still read back in CHEAP_ATSES order, and every rule
this file has accumulated about which board wins depends on that order -- so the
rules are pinned here rather than left to a live run to discover.

The last two cases cover the same day's second finding, which is unrelated to
the fan-out: a scalar `timeout` bounds neither the request nor the budget, and
one careers page spent 40.1s failing to connect because of it.

Everything below runs against a fake `requests` module, so the file is safe to
run anywhere and fast enough to run on every edit.
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harvest_ats as H

# Per-request latency in the fake. Real probes measured 0.13s (Greenhouse) to
# 0.83s (JazzHR) on 2026-09-17; 40ms keeps the suite quick while leaving the
# sequential-vs-parallel gap large enough to assert on.
FAKE_LATENCY = 0.04

FIT = "Support Operations Manager"
NOFIT = "Line Cook"


class FakeMatcher:
    """Stands in for poll_ats.TitleMatcher: one tier1 title, nothing else."""

    def match_exact(self, title):
        return ("tier1_true_match",) if FIT.lower() in (title or "").lower() else None


def never_excluded(_title):
    return False


class FakeResponse:
    def __init__(self, status=200, payload=None, text="", url=""):
        self.status_code = status
        self._payload = payload
        self.text = text
        self.url = url

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


_ROUTES = (
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/([^/]+)/jobs")),
    ("ashby", re.compile(r"api\.ashbyhq\.com/posting-api/job-board/([^/?]+)")),
    ("lever", re.compile(r"api\.lever\.co/v0/postings/([^/?]+)")),
    ("workable", re.compile(r"apply\.workable\.com/api/v1/widget/accounts/([^/?]+)")),
    ("pinpoint", re.compile(r"https://([^/]+)\.pinpointhq\.com/postings\.json")),
    ("jazzhr", re.compile(r"https://([^/]+)\.applytojob\.com/apply/")),
    ("rippling", re.compile(r"ats\.rippling\.com/([^/]+)/jobs")),
    ("smartrecruiters", re.compile(r"smartrecruiters\.com/v1/companies/([^/]+)/postings")),
)


def _route(url):
    for ats, pat in _ROUTES:
        m = pat.search(url)
        if m:
            return ats, m.group(1)
    return None, None


def _payload(ats, jobs):
    """Wrap [(title, location)] in the shape probe() expects from that ATS."""
    if ats == "greenhouse":
        return {"jobs": [{"title": t, "location": {"name": l}} for t, l in jobs]}
    if ats == "ashby":
        return {"jobs": [{"title": t, "location": l} for t, l in jobs]}
    if ats == "lever":
        return [{"text": t, "categories": {"location": l}} for t, l in jobs]
    if ats == "workable":
        return {"jobs": [{"title": t, "location": l} for t, l in jobs]}
    if ats == "pinpoint":
        return {"data": [{"title": t, "location": {"name": l}} for t, l in jobs]}
    if ats == "smartrecruiters":
        return {"totalFound": len(jobs),
                "content": [{"name": t, "location": {"fullLocation": l}}
                            for t, l in jobs]}
    raise AssertionError(ats)


class FakeRequests:
    """`requests` stand-in. BOARDS maps (ats, slug) -> [(title, location)].

    A slug absent from BOARDS 404s, which is what every real ATS here does for a
    name variant that is not a board -- except SmartRecruiters, which answers 200
    with totalFound 0. That difference is the point of one of the cases below,
    so it is reproduced exactly.
    """

    def __init__(self, boards):
        self.boards = boards
        self.log = []          # (ats, slug, monotonic)

    def get(self, url, **_kw):
        ats, slug = _route(url)
        assert ats, f"unrouted URL in test fake: {url}"
        time.sleep(FAKE_LATENCY)
        self.log.append((ats, slug, time.monotonic()))
        jobs = self.boards.get((ats, slug))
        if ats == "smartrecruiters" and jobs is None:
            return FakeResponse(200, _payload("smartrecruiters", []), url=url)
        if jobs is None:
            return FakeResponse(404, url=url)
        if ats in ("jazzhr", "rippling"):
            raise AssertionError("the fake does not serve HTML boards")
        return FakeResponse(200, _payload(ats, jobs), url=url)

    def post(self, url, **_kw):        # Workday; never reached by these cases
        raise AssertionError(f"unexpected POST in test fake: {url}")


def run(name, boards, known_pairs=frozenset(), skip_workday=True, skip_comeet=True):
    fake = FakeRequests(boards)
    real = H.requests
    H.requests = fake
    H._SERVICE_LAST_HIT.clear()
    try:
        t0 = time.monotonic()
        res = H.assess(name, FakeMatcher(), never_excluded, set(known_pairs),
                       skip_workday=skip_workday, skip_comeet=skip_comeet,
                       budget_seconds=0)
        return res, fake, time.monotonic() - t0
    finally:
        H.requests = real


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


@case
def evaluation_order_is_preserved():
    """Two boards answer on the same slug; the earlier ATS must win."""
    res, _, _ = run("Acme", {("greenhouse", "acme"): [(FIT, "Remote - USA")],
                             ("lever", "acme"): [(FIT, "Remote - USA")]})
    return (res["ats"], res["slug"]) == ("greenhouse", "acme"), res


@case
def full_form_nofit_still_wins_immediately():
    """A no-fit board on the company's OWN full name is trusted, not passed over.

    The fan-out probes Ashby regardless now, so this rule could only survive by
    being applied at evaluation time. It is the rule that keeps a company whose
    board simply has nothing open from being chased across every variant.
    """
    res, _, _ = run("Acme", {("greenhouse", "acme"): [(NOFIT, "Remote - USA")],
                             ("ashby", "acme"): [(FIT, "Remote - USA")]})
    return (res["ats"], res["strong"] == []) == ("greenhouse", True), res


@case
def reduced_form_nofit_is_held_not_returned():
    """The 2026-09-10 name-collision guard: `bark` must not beat the real board."""
    res, _, _ = run("Bark Technologies",
                    {("greenhouse", "bark"): [(NOFIT, "Remote - USA")],
                     ("workable", "bark-technologies-inc"): [(FIT, "Remote - USA")]})
    ok = (res["ats"], res["slug"]) == ("workable", "bark-technologies-inc")
    return ok and res.get("passed_over") == "greenhouse/bark", res


@case
def smartrecruiters_zero_is_no_board_not_empty_board():
    """totalFound 0 must read as None, so _confirm_empty never re-probes it.

    A re-probe would get the same confident 200 and CONFIRM a slug collision
    onto a company's permanent record. Checked by request count: exactly one
    SmartRecruiters request per slug variant and not one more.
    """
    res, fake, _ = run("Acme", {})
    sr = [e for e in fake.log if e[0] == "smartrecruiters"]
    return res is None and len(sr) == len(H.slug_variants("Acme")), (res, len(sr))


@case
def empty_board_is_confirmed_then_reported():
    """A genuinely empty board costs one extra probe and reports as empty."""
    res, fake, _ = run("Acme", {("greenhouse", "acme"): []})
    gh = [e for e in fake.log if e == ("greenhouse", "acme") or
          (e[0], e[1]) == ("greenhouse", "acme")]
    return (res.get("empty_board") is True and res["ats"] == "greenhouse"
            and len(gh) == 2), (res, len(gh))


@case
def known_pairs_are_never_probed():
    """An (ats, slug) already on the watchlist must cost zero requests."""
    _, fake, _ = run("Acme", {("greenhouse", "acme"): [(FIT, "Remote - USA")]},
                     known_pairs={("greenhouse", "acme")})
    return not any(e[0] == "greenhouse" and e[1] == "acme" for e in fake.log), None


@case
def each_service_still_sees_one_request_per_delay():
    """The politeness guarantee, which is the thing concurrency could break."""
    old = H.DELAY
    H.DELAY = 0.05
    try:
        _, fake, _ = run("Acme", {})
    finally:
        H.DELAY = old
    worst = {}
    for ats, _slug, at in fake.log:
        prev = worst.get(ats)
        if prev is not None:
            gap = at - prev
            worst[ats] = at
            if gap < 0.05 - 0.005:
                return False, f"{ats} gap {gap:.3f}s"
        worst[ats] = at
    return True, None


@case
def the_round_is_concurrent():
    """The regression guard for the fix itself: a slug's round must overlap.

    Eight ATSes at FAKE_LATENCY each is 0.32s sequentially. Asserted against
    half that, which no serial implementation can reach and any working fan-out
    clears by a wide margin.
    """
    _, fake, wall = run("Acme", {("greenhouse", "acme"): [(FIT, "Remote - USA")]})
    n = len(fake.log)
    return wall < (n * FAKE_LATENCY) / 2, f"{wall:.2f}s for {n} requests"


class TimeoutRecorder:
    """Captures the `timeout` every probe hands to requests."""

    def __init__(self):
        self.seen = []

    def _r(self, url, **kw):
        self.seen.append(kw.get("timeout"))
        return FakeResponse(404, url=url)

    def get(self, url, **kw):
        return self._r(url, **kw)

    def post(self, url, **kw):
        return self._r(url, **kw)


def _with_fake_requests(fake, fn):
    real = H.requests
    H.requests = fake
    H._SERVICE_LAST_HIT.clear()
    try:
        return fn()
    finally:
        H.requests = real


@case
def connect_and_read_timeouts_are_separate():
    """Every probe must pass (connect, read), never a scalar.

    A scalar is applied to the connect AND to each read, and urllib3 tries every
    address a hostname resolves to, so one dead host with two A records costs
    2 x TIMEOUT. That is what spent 40.1s on https://remohealth.com/careers.
    """
    rec = TimeoutRecorder()
    _with_fake_requests(rec, lambda: (
        H._get("https://api.lever.co/v0/postings/x?mode=json"),
        H._raw_get("https://x.example/careers"),
        H.probe_workday("x"),
    ))
    ok = rec.seen and all(t == (H.CONNECT_TIMEOUT, H.TIMEOUT) for t in rec.seen)
    return ok, f"{len(rec.seen)} requests, timeouts={set(rec.seen)}"


@case
def a_short_budget_shrinks_both_halves():
    """Neither half of the timeout may outlive the budget it is spending."""
    rec = TimeoutRecorder()
    budget = H.Budget(2.0)
    _with_fake_requests(rec, lambda: H._get("https://api.lever.co/v0/postings/x",
                                            budget))
    connect, read = rec.seen[0]
    return connect <= read <= 2.0 and connect <= H.CONNECT_TIMEOUT, rec.seen[0]


def main():
    passed = 0
    for fn in CASES:
        ok, detail = fn()
        print(f"  [{'ok ' if ok else 'FAIL'}] {fn.__name__}"
              + (f"   {detail}" if not ok or detail else ""))
        passed += bool(ok)
    print(f"  {passed}/{len(CASES)} passed")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
