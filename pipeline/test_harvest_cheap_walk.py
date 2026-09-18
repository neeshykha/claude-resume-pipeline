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
    def __init__(self, status=200, payload=None, text="", url="", headers=None):
        self.status_code = status
        self._payload = payload
        self.text = text
        self.url = url
        self.headers = headers or {}

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

    def __init__(self, boards, throttle=None):
        self.boards = boards
        self.log = []          # (ats, slug, monotonic)
        # (ats, slug) -> "always", or a list consumed one entry per request:
        # a dict of 429 headers means "answer 429 with these", None means
        # "answer normally". An exhausted list answers normally.
        self.throttle = {k: (v if v == "always" else list(v))
                         for k, v in (throttle or {}).items()}

    def _throttled(self, ats, slug, url):
        plan = self.throttle.get((ats, slug))
        if plan == "always":
            return FakeResponse(429, url=url)
        if plan:
            step = plan.pop(0)
            if step is not None:
                return FakeResponse(429, url=url, headers=step)
        return None

    def get(self, url, **_kw):
        ats, slug = _route(url)
        assert ats, f"unrouted URL in test fake: {url}"
        time.sleep(FAKE_LATENCY)
        self.log.append((ats, slug, time.monotonic()))
        refused = self._throttled(ats, slug, url)
        if refused is not None:
            return refused
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


def run(name, boards, known_pairs=frozenset(), skip_workday=True, skip_comeet=True,
        throttle=None, budget_seconds=0):
    fake = FakeRequests(boards, throttle)
    real = H.requests
    H.requests = fake
    H._SERVICE_LAST_HIT.clear()
    try:
        t0 = time.monotonic()
        res = H.assess(name, FakeMatcher(), never_excluded, set(known_pairs),
                       skip_workday=skip_workday, skip_comeet=skip_comeet,
                       budget_seconds=budget_seconds)
        return res, fake, time.monotonic() - t0
    finally:
        H.requests = real


class tuned:
    """Temporarily override module constants (DELAY, retry waits) for speed."""

    def __init__(self, **attrs):
        self.attrs = attrs
        self.saved = {}

    def __enter__(self):
        for k, v in self.attrs.items():
            self.saved[k] = getattr(H, k)
            setattr(H, k, v)
        return self

    def __exit__(self, *_exc):
        for k, v in self.saved.items():
            setattr(H, k, v)
        return False


# Fast-but-real settings for the throttle cases: the retry path still sleeps
# and still paces, just not for seconds at a time.
FAST = dict(DELAY=0.005, RETRY_FALLBACK_WAIT=0.05)


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
    SmartRecruiters request per UNDOTTED slug variant and not one more (dotted
    variants are never sent there since 2026-09-17; see NO_DOTTED_SLUG_ATSES).
    Also checked directly on probe(), which is the layer that owns the rule.
    """
    res, fake, _ = run("Acme", {})
    sr = [e for e in fake.log if e[0] == "smartrecruiters"]
    undotted = [s for s in H.slug_variants("Acme") if "." not in s]
    direct = _with_fake_requests(FakeRequests({}),
                                 lambda: H.probe("smartrecruiters", "Acme"))
    return (res is None and len(sr) == len(undotted) and direct is None,
            (res, len(sr), len(undotted), direct))


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


# ---------------------------------------------------------------------------
# Rate limiting (added 2026-09-17)
# ---------------------------------------------------------------------------
# apply.workable.com answered HTTP 429 to 55 of 94 requests in that day's timing
# study, and each 429 was read as "no Workable board". A company where that was
# the only unresolved signal was written unpollable=true, which stops it ever
# being re-checked. These cases pin the third state (THROTTLED), the one-retry
# policy, and the dotted-variant skip found in the same study.


@case
def a_429_is_unknown_not_no_board():
    """probe() answers THROTTLED, and THROTTLED refuses to act like None or []."""
    with tuned(**FAST):
        got = _with_fake_requests(
            FakeRequests({}, {("workable", "acme"): "always"}),
            lambda: H.probe("workable", "acme"))
    try:
        bool(got)
        loud = False
    except TypeError:
        loud = True
    return got is H.THROTTLED and loud, (got, loud)


@case
def a_throttle_only_company_is_unresolved_not_no_board():
    """Nothing resolves, Workable refused: the result is `throttled`, never None."""
    with tuned(**FAST):
        res, _, _ = run("Acme", {}, throttle={("workable", "acme"): "always"})
    ok = (res is not None and res.get("throttled") is True
          and ("workable", "acme") in res["throttled_probes"]
          and not res.get("empty_board") and not res.get("timed_out"))
    return ok, res


def _main_writes(name, assess_result):
    """Run main() --apply for one name against TEMP copies of both data files.

    assess() is replaced with one returning `assess_result`, so this exercises
    exactly the writer that turns a result into a rejected record. The real
    watchlist and queue are copied, never opened for writing.
    """
    import contextlib
    import io
    import json
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="harvest_throttle_test_")
    saved = (H.WATCHLIST, H.QUEUE, H.assess, sys.argv)
    try:
        wl = os.path.join(tmp, "watchlist_companies.json")
        qu = os.path.join(tmp, "enrollment_candidates.json")
        shutil.copyfile(saved[0], wl)
        shutil.copyfile(saved[1], qu)
        H.WATCHLIST, H.QUEUE = wl, qu
        H.assess = lambda *_a, **_k: assess_result
        sys.argv = ["harvest_ats.py", "--names", name, "--apply"]
        with contextlib.redirect_stdout(io.StringIO()):
            H.main()
        with open(qu, encoding="utf-8") as f:
            q = json.load(f)
        return [r for r in q.get("rejected", []) if r.get("name") == name]
    finally:
        H.WATCHLIST, H.QUEUE, H.assess, sys.argv = saved
        shutil.rmtree(tmp, ignore_errors=True)


@case
def a_throttled_company_is_never_written_unpollable():
    """End to end: 429 -> assess() -> main()'s writer -> unpollable is False.

    The contrast run feeds the same writer a genuine no-board result (None) and
    must still produce unpollable=true, which proves this case would have
    caught the bug rather than passing because the writer changed shape.
    """
    name = "Zzq Throttle Fixture Co"
    with tuned(**FAST):
        res, _, _ = run(name, {}, throttle={("workable", s): "always"
                                            for s in H.slug_variants(name)})
    written = _main_writes(name, res)
    contrast = _main_writes(name, None)
    ok = (len(written) == 1 and written[0].get("unpollable") is False
          and written[0].get("throttled") is True
          and written[0].get("recheck_if_resurfaced") is True
          and len(contrast) == 1 and contrast[0].get("unpollable") is True)
    return ok, ([{k: r.get(k) for k in ("unpollable", "throttled")} for r in written],
                [{k: r.get(k) for k in ("unpollable",)} for r in contrast])


@case
def the_retry_happens_at_most_once():
    """A persistent 429 costs exactly two requests, and a cleared one resolves."""
    with tuned(**FAST):
        fake = FakeRequests({}, {("workable", "acme"): "always"})
        got = _with_fake_requests(fake, lambda: H.probe("workable", "acme"))
        cleared = FakeRequests({("workable", "acme"): [(FIT, "Remote - USA")]},
                               {("workable", "acme"): [{}]})
        got2 = _with_fake_requests(cleared, lambda: H.probe("workable", "acme"))
    ok = (got is H.THROTTLED and len(fake.log) == 2
          and isinstance(got2, list) and len(got2) == 1 and len(cleared.log) == 2)
    return ok, (got, len(fake.log), got2, len(cleared.log))


@case
def retry_after_is_honored():
    """The retry waits at least Retry-After, not the fallback."""
    with tuned(**FAST):
        fake = FakeRequests({("workable", "acme"): [(FIT, "Remote - USA")]},
                            {("workable", "acme"): [{"Retry-After": "0.3"}]})
        got = _with_fake_requests(fake, lambda: H.probe("workable", "acme"))
    gap = fake.log[1][2] - fake.log[0][2] if len(fake.log) == 2 else 0
    # Each log stamp is taken after FAKE_LATENCY, so the gap is wait + latency.
    return isinstance(got, list) and gap >= 0.3, f"gap {gap:.3f}s"


@case
def the_retry_never_outlives_the_budget():
    """A Retry-After past the budget is not waited out: one request, THROTTLED, fast."""
    with tuned(**FAST):
        fake = FakeRequests({}, {("workable", "acme"): [{"Retry-After": "5"}]})
        budget = H.Budget(1.0)
        t0 = time.monotonic()
        got = _with_fake_requests(fake, lambda: H.probe("workable", "acme", budget))
        took = time.monotonic() - t0
        # And one inside the budget IS retried.
        fake2 = FakeRequests({}, {("workable", "acme"): [{"Retry-After": "0.1"}]})
        _with_fake_requests(fake2, lambda: H.probe("workable", "acme", H.Budget(5.0)))
    ok = got is H.THROTTLED and len(fake.log) == 1 and took < 0.5 and len(fake2.log) == 2
    return ok, (got, len(fake.log), f"{took:.2f}s", len(fake2.log))


@case
def a_service_that_fails_its_retry_is_not_retried_again_this_walk():
    """Bounds a whole-walk throttle to one wait: every variant is still SENT,
    but only the first one is retried."""
    name = "Acme"
    variants = [s for s in H.slug_variants(name)]
    with tuned(**FAST):
        res, fake, _ = run(name, {}, throttle={("workable", s): "always" for s in variants},
                           budget_seconds=30)
    wk = [e for e in fake.log if e[0] == "workable"]
    ok = res.get("throttled") is True and len(wk) == len(variants) + 1
    return ok, (len(wk), len(variants))


@case
def a_throttled_empty_confirm_is_unknown():
    """Board answers [] then the confirming re-probe is refused: unknown, not no-board."""
    with tuned(**FAST):
        res, _, _ = run("Acme", {("greenhouse", "acme"): []},
                        throttle={("greenhouse", "acme"): [None, {}, {}]})
    ok = (res is not None and res.get("throttled") is True
          and ("greenhouse", "acme") in res["throttled_probes"])
    return ok, res


@case
def a_throttled_workday_host_is_unknown():
    """probe_workday: a host answering 429 yields (THROTTLED, None), not (None, None)."""

    class WorkdayFake:
        def __init__(self):
            self.n = 0

        def post(self, url, **_kw):
            self.n += 1
            if ".wd1." in url:
                return FakeResponse(429, url=url)
            return FakeResponse(422, url=url)

        def get(self, url, **_kw):
            raise AssertionError(url)

    fake = WorkdayFake()
    with tuned(**FAST):
        got = _with_fake_requests(fake, lambda: H.probe_workday("acme"))
    return got[0] is H.THROTTLED and got[1] is None, (got, fake.n)


@case
def dotted_variants_skip_subdomain_atses():
    """No dotted slug reaches JazzHR, Pinpoint, or SmartRecruiters; Ashby and
    Lever still get them, because ambient.ai and regal.ai are real boards."""
    with tuned(**FAST):
        _, fake, _ = run("Acme", {})
    dotted = {(a, s) for a, s, _ in fake.log if "." in s}
    leaked = {p for p in dotted if p[0] in H.NO_DOTTED_SLUG_ATSES}
    kept = {a for a, _ in dotted}
    ok = not leaked and {"ashby", "lever"} <= kept and any("." in s for s in H.slug_variants("Acme"))
    return ok, (sorted(leaked), sorted(kept))


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
