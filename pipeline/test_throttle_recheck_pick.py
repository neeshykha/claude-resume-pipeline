"""Unit-check the rate-limit recheck's rotation. No network, no real data files.

Added 2026-11-12. The pick was "the ten oldest by rejected_date", which only
rotated while the re-probe rewrote that date. The re-probe became a dry run on
2026-10-12 and the same ten names were picked on each of the next 22 runs. The
rotation now reads the earlier pick files.

What is pinned here:
  - a name that was picked on an earlier day waits behind every name that has
    never been picked, so consecutive days pick different names;
  - once every name has had a turn, the one picked longest ago goes first;
  - today's own pick file is ignored, so a second call on the same day returns
    the same names;
  - a pick file that is unreadable or not a list is skipped, not fatal;
  - enrolled and non-throttled records never enter the backlog.

Every company name below is made up. Pick files are written to a temp folder.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import throttle_recheck_pick as T

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def _parked(count):
    """`count` throttled records, oldest first: Zzq Fixture 00, 01, ..."""
    return [{"name": f"Zzq Fixture {i:02d}", "throttled": True,
             "rejected_date": f"2026-01-{i + 1:02d}"} for i in range(count)]


def _write(folder, day, names):
    with open(os.path.join(folder, f"{T.PREFIX}{day}.json"), "w", encoding="utf-8") as f:
        json.dump(names, f)


@case
def first_pick_is_the_oldest_rejections():
    got = T.pick(_parked(6), {}, 3)
    return got == ["Zzq Fixture 00", "Zzq Fixture 01", "Zzq Fixture 02"], got


@case
def next_day_moves_on_when_nothing_was_written():
    """The dry run changes no rejected_date; the pick still has to advance."""
    parked = _parked(6)
    with tempfile.TemporaryDirectory() as d:
        _write(d, "2026-03-02", T.pick(parked, {}, 3))
        got = T.pick(parked, T.last_picked(d, "2026-03-03"), 3)
    return got == ["Zzq Fixture 03", "Zzq Fixture 04", "Zzq Fixture 05"], got


@case
def full_cycle_then_longest_since_a_pick_goes_first():
    parked = _parked(4)
    with tempfile.TemporaryDirectory() as d:
        _write(d, "2026-03-02", ["Zzq Fixture 00", "Zzq Fixture 01"])
        _write(d, "2026-03-03", ["Zzq Fixture 02", "Zzq Fixture 03"])
        got = T.pick(parked, T.last_picked(d, "2026-03-04"), 2)
    return got == ["Zzq Fixture 00", "Zzq Fixture 01"], got


@case
def same_day_rerun_returns_the_same_names():
    parked = _parked(6)
    with tempfile.TemporaryDirectory() as d:
        first = T.pick(parked, T.last_picked(d, "2026-03-02"), 3)
        _write(d, "2026-03-02", first)
        second = T.pick(parked, T.last_picked(d, "2026-03-02"), 3)
    return first == second, (first, second)


@case
def a_name_picked_twice_uses_its_latest_day():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "2026-03-02", ["Zzq Fixture 00"])
        _write(d, "2026-03-05", ["zzq fixture 00"])
        last = T.last_picked(d, "2026-03-06")
    return last == {"zzq fixture 00": "2026-03-05"}, last


@case
def a_broken_pick_file_is_skipped():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, f"{T.PREFIX}2026-03-02.json"), "w", encoding="utf-8") as f:
            f.write("{not json")
        _write(d, "2026-03-03", {"not": "a list"})
        _write(d, "2026-03-04", ["Zzq Fixture 01"])
        last = T.last_picked(d, "2026-03-05")
    return last == {"zzq fixture 01": "2026-03-04"}, last


@case
def only_live_throttled_records_are_parked():
    queue = {"rejected": [
        {"name": "Zzq Fixture 00", "throttled": True},
        {"name": "Zzq Fixture 01", "throttled": True, "superseded_by_enrollment": "2026-02-01"},
        {"name": "Zzq Fixture 02", "timed_out": True},
        {"throttled": True},
    ]}
    got = [r["name"] for r in T.parked_records(queue)]
    return got == ["Zzq Fixture 00"], got


def main():
    passed = 0
    for fn in CASES:
        ok, detail = fn()
        print(f"  [{'ok ' if ok else 'FAIL'}] {fn.__name__}" + (f"   {detail}" if not ok else ""))
        passed += bool(ok)
    print(f"  {passed}/{len(CASES)} passed")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
