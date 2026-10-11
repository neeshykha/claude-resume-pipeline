"""Checks for the lane-only poll, poll_lane.py (2026-10-10). Offline: the board
fetch is faked and every path it touches is a temp one.

What has to hold: the main poll skips lane-marked entries and this poll reads
only those; every title match at them comes out, past the 2-per-company cap and the near-window cap that would
cut them in the main poll; the per-company guard still applies; a board that
never finishes answering costs its own candidates and no one else's; the one
file written is lane_hits_<date>.json; and the watchlist, seen_jobs.json, and
the poller's own settings are left as they were.

Companies, titles, and postings are made up. The titles are injected into the
temp watchlist, so nothing here depends on the live title lists.
"""
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poll_ats
import poll_lane

RUN = date(2026, 1, 15)
POSTED = RUN - timedelta(days=3)
TIER_TITLES = ["Quokka Desk Lead", "Quokka Bench Lead", "Quokka Yard Lead",
               "Quokka Dock Lead", "Quokka Vault Lead"]
REVIEW_TITLE = "Quokka Review Lead"


def posting(jid, title, location):
    return {"id": jid, "title": title, "location": {"name": location},
            "first_published": f"{POSTED.isoformat()}T09:00:00-04:00"}


BOARDS = {
    "northgate": [
        posting(1, "Quokka Desk Lead", "Atlanta, GA"),
        posting(2, "Quokka Bench Lead", "Atlanta, GA"),
        posting(3, "Quokka Yard Lead", "Remote - United States"),
        posting(4, "Quokka Dock Lead", "Denver, CO"),
        posting(5, "Field Quokka Desk Lead", "Atlanta, GA"),   # the entry's guard drops it
        posting(6, REVIEW_TITLE, "Alpharetta, Georgia"),
        posting(7, "Plant Electrician", "Atlanta, GA"),        # no title match
    ],
    "harbor": [posting(8, "Quokka Vault Lead", "Atlanta, GA")],
    "unrelated": [posting(9, "Quokka Desk Lead", "Atlanta, GA")],
}
COMPANIES = [
    {"name": "Northgate Controls", "ats": "greenhouse", "slug": "northgate",
     "priority": "low", "lane": "industrial", "role_exclusions": ["field"]},
    {"name": "Harbor Materials", "ats": "greenhouse", "slug": "harbor",
     "priority": "low", "lane": "industrial"},
    {"name": "Stalled Works", "ats": "greenhouse", "slug": "stalled",
     "priority": "low", "lane": "industrial"},
    {"name": "Unrelated Software", "ats": "greenhouse", "slug": "unrelated",
     "priority": "high"},
]
STALL_S = 30

results = []


def check(ok, what):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {what}")


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


work = tempfile.mkdtemp(prefix="lane_test_")
jobs_dir = os.path.join(work, "jobs")
scratch = os.path.join(work, "tmp")
os.makedirs(scratch)

# The live watchlist supplies the config sections; companies and titles are ours.
with open(poll_ats.WATCHLIST_PATH, encoding="utf-8") as f:
    wl = json.load(f)
wl["companies"] = COMPANIES
pc = wl["_poller_config"]
pc["supplemental_exact_titles"]["titles"] = TIER_TITLES + [REVIEW_TITLE]
pc["function_mismatch_titles"]["titles"] = [REVIEW_TITLE]
wl_path = os.path.join(work, "watchlist.json")
with open(wl_path, "w", encoding="utf-8") as f:
    json.dump(wl, f, ensure_ascii=False)
seen_path = os.path.join(work, "seen_jobs.json")
with open(seen_path, "w") as f:
    json.dump({"jobs": {}}, f)

fetched = []


def fake_fetch(slug, eu=False):
    fetched.append(slug)
    if slug == "stalled":               # a feed that never finishes arriving
        threading.Event().wait(STALL_S)
        return []
    return BOARDS[slug]


real = (poll_ats.fetch_greenhouse, poll_ats.SEEN_JOBS_PATH, poll_ats.time.sleep,
        tempfile.tempdir, poll_ats.NEAR_WINDOW_SIZE, poll_lane.BOARD_DEADLINE_S)
poll_ats.fetch_greenhouse = fake_fetch
poll_ats.SEEN_JOBS_PATH = seen_path
poll_ats.time.sleep = lambda s: None
tempfile.tempdir = scratch          # so the helper's watchlist copy lands where we can look
poll_ats.NEAR_WINDOW_SIZE = 1       # would cut a real match if the helper left it alone
poll_lane.BOARD_DEADLINE_S = 0.5
before = (poll_ats.WATCHLIST_PATH, poll_ats.NEAR_WINDOW_SIZE, poll_ats.BORDERLINE_SIZE)
wl_sha, seen_sha = sha(wl_path), sha(seen_path)
try:
    started = time.monotonic()
    path, payload = poll_lane.run(RUN, "industrial", jobs_dir=jobs_dir, watchlist_path=wl_path)
    took = time.monotonic() - started
    fetched_lane = list(fetched)
    after = (poll_ats.WATCHLIST_PATH, poll_ats.NEAR_WINDOW_SIZE, poll_ats.BORDERLINE_SIZE)
    empty_path, empty = poll_lane.run(RUN + timedelta(days=1), "no_such_lane",
                                      jobs_dir=jobs_dir, watchlist_path=wl_path)
    fetched_empty = fetched[len(fetched_lane):]
    # The main poll, on the same watchlist with its markers intact.
    del fetched[:]
    poll_ats.WATCHLIST_PATH = wl_path
    main_res = poll_ats.poll_all(RUN)
    fetched_main = list(fetched)
    poll_ats.WATCHLIST_PATH = before[0]
finally:
    (poll_ats.fetch_greenhouse, poll_ats.SEEN_JOBS_PATH, poll_ats.time.sleep,
     tempfile.tempdir, poll_ats.NEAR_WINDOW_SIZE, poll_lane.BOARD_DEADLINE_S) = real

cands = payload["candidates"]
by_title = {c["title"]: c for c in cands}
tier = sorted(c["title"] for c in cands if c["source"] == "tier_match")

check(sorted(fetched_lane) == ["harbor", "northgate", "stalled"],
      f"only the lane-marked boards are read: {sorted(fetched_lane)}")
check(tier == sorted(TIER_TITLES),
      f"all 5 tier matches come out, 4 of them at one company: {len(tier)}")
check("Field Quokka Desk Lead" not in by_title,
      "the entry's role_exclusions guard still drops its title")
check(not any(c["company"] == "Unrelated Software" for c in cands),
      "nothing from a company outside the lane")
review = by_title.get(REVIEW_TITLE, {})
check(review.get("source") == "function_mismatch" and review.get("pre_score") is None,
      "a review-only title arrives as function_mismatch, unscored")
check(review.get("posted_date") == POSTED.isoformat(),
      f"its posted_date is rebuilt from the posting age: {review.get('posted_date')}")
check(all(c["pre_score"] is not None and c["url"] and c["posted_date"] == POSTED.isoformat()
          for c in cands if c["source"] == "tier_match"),
      "every tier match carries a pre_score, a url, and a posted_date")
places = [c["place"] for c in cands]
check(places == sorted(places, key=poll_lane.PLACES.index) and places[:1] == ["georgia"]
      and by_title.get("Quokka Dock Lead", {}).get("place") == "elsewhere",
      f"ordered Georgia, remote, elsewhere: {places}")
k = payload["counts"]
check((k["candidates"], k["georgia"], k["remote"], k["elsewhere"]) == (6, 4, 1, 1)
      and (k["tier_match"], k["function_mismatch"]) == (5, 1)
      and [(b["postings_scanned"], b["candidates"]) for b in payload["boards"]]
      == [(7, 5), (1, 1), (0, 0)],
      f"counts add up: {k}")
stalled = payload["boards"][-1]
check(took < STALL_S / 2 and stalled["error"] and "inside" in stalled["error"]
      and [e["company"] for e in payload["errors"]] == ["Stalled Works"],
      f"a board that never finishes is cut off and named, in {took:.1f} s: {stalled['error']}")
check(sorted(os.listdir(jobs_dir)) == [f"lane_hits_{RUN.isoformat()}.json",
                                       f"lane_hits_{(RUN + timedelta(days=1)).isoformat()}.json"],
      f"the only files written are lane_hits files: {sorted(os.listdir(jobs_dir))}")
with open(path, encoding="utf-8") as f:
    check(json.load(f) == payload, "the file on disk is the payload returned")
check(after == before, f"poller settings restored after the poll: {after}")
check(os.listdir(scratch) == [], "the temporary watchlist copy is removed")
check(sha(wl_path) == wl_sha and sha(seen_path) == seen_sha,
      "the watchlist and seen_jobs.json are byte-for-byte unchanged")
check(fetched_empty == [] and empty["counts"]["candidates"] == 0
      and empty["boards"] == [] and os.path.exists(empty_path),
      "an unmarked lane polls nothing and still writes a zero-candidate file")

main_rows = (main_res["matched"] + main_res["near_window"] + main_res["borderline"]
             + main_res["function_mismatch"])
check(fetched_main == ["unrelated"] and main_res["stats"]["lane_skipped"] == 3
      and {j["company"] for j in main_rows} == {"Unrelated Software"},
      f"the main poll skips the lane-marked entries: read {fetched_main}, "
      f"lane_skipped={main_res['stats']['lane_skipped']}")

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
