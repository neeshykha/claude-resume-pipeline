"""Regression check for fetch_workday pagination (2026-09-11).

Workday's CXS API reports a board's real `total` only on the offset=0 page;
later pages answer total=0. The poller used to re-read `total` every page, so
it stopped after page two and read 40 postings from every board (JLL 40 of
2000, Stord 40 of 98). These cases fake the API and count what gets read.
"""
import sys, os, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poll_ats

COMPANY = {"wd_host": "x.wd1.myworkdayjobs.com", "wd_tenant": "x", "wd_site": "X_Careers"}
CAP = poll_ats.WORKDAY_MAX_POSTINGS


class FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def fake_board(size, later_total):
    """A board of `size` postings. `later_total` is what pages after the first
    report as total: 0 is real Workday behavior, "same" echoes the real count
    (what Palo Alto Networks' tenant happened to do)."""
    calls = []

    def post(url, json=None, headers=None, timeout=None):
        off, lim = json["offset"], json["limit"]
        calls.append(off)
        n = max(0, min(lim, size - off))
        posts = [{"title": f"Job {off + i}", "externalPath": f"/job/{off + i}",
                  "locationsText": "Atlanta, GA", "postedOn": "Posted Today"}
                 for i in range(n)]
        total = size if (off == 0 or later_total == "same") else later_total
        return FakeResp({"total": total, "jobPostings": posts})

    return post, calls


CASES = [
    # (board size, later-page total, expected postings read, expected requests, why)
    (98, 0, 98, 5, "Stord: later pages say total=0; must still read all 98"),
    (50, 0, 50, 3, "RaceTrac SSC: third page is short"),
    (2000, 0, CAP, CAP // 20, "JLL: a large board stops at the cap"),
    (2000, "same", CAP, CAP // 20, "Palo Alto style: total echoed every page, still capped"),
    (12, 0, 12, 1, "CSI: one short page, no second request"),
    (40, 0, 40, 2, "exactly two full pages: must not request a third"),
    (0, 0, 0, 1, "empty board"),
]

real_post, real_time = poll_ats.requests.post, poll_ats.time
poll_ats.time = types.SimpleNamespace(sleep=lambda s: None)
fails = 0
try:
    for size, later, want_read, want_calls, why in CASES:
        post, calls = fake_board(size, later)
        poll_ats.requests.post = post
        got = poll_ats.fetch_workday(COMPANY)
        errs = [j["_error"] for j in got if "_error" in j]
        ok = not errs and len(got) == want_read and len(calls) == want_calls
        if not ok:
            fails += 1
        print(f"{'PASS' if ok else 'FAIL'}  size={size:<5} later={str(later):<5} "
              f"read={len(got):<4} (want {want_read})  requests={len(calls)} "
              f"(want {want_calls})  {why}" + (f"  ERROR {errs[0]}" if errs else ""))
finally:
    poll_ats.requests.post, poll_ats.time = real_post, real_time

print(f"\n{len(CASES) - fails}/{len(CASES)} passed")
sys.exit(1 if fails else 0)
