#!/usr/bin/env python3
"""Tests for mark_verdict.py and pipeline_quality.py. Fixtures are invented.

Run: .venv/bin/python pipeline/test_measurement.py
"""
import csv
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mark_verdict  # noqa: E402
import pipeline_quality as pq  # noqa: E402
from repair_outcomes import CANONICAL  # noqa: E402

FAILS = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


def row(**kw):
    base = dict.fromkeys(CANONICAL, "")
    base.update(stage="surfaced", surfaced_date="2026-09-01", source_channel="pipeline")
    base.update(kw)
    return [base[c] for c in CANONICAL]


def write(rows):
    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CANONICAL)
        w.writerows(rows)
    return path


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# --- mark_verdict ---------------------------------------------------------
p = write([row(company="Acme Widgets", title="Support Ops Manager"),
           row(company="Globex", title="Technical Account Manager"),
           row(company="Globex", title="Implementation Manager")])

check("unique company match writes the verdict",
      mark_verdict.main(["Acme Widgets", "sent_as_is"], p) == 0
      and read(p)[0]["his_verdict"] == "sent_as_is")
check("backup is written before the change", os.path.exists(p + ".bak"))
check("ambiguous company writes nothing",
      mark_verdict.main(["Globex", "skip_fit"], p) == 1
      and all(r["his_verdict"] == "" for r in read(p)[1:]))
check("--title narrows to one row",
      mark_verdict.main(["Globex", "skip_materials", "--title", "implementation"], p) == 0
      and read(p)[2]["his_verdict"] == "skip_materials" and read(p)[1]["his_verdict"] == "")
check("--note is appended to notes",
      mark_verdict.main(["Acme", "sent_edited", "--note", "fixed the summary"], p) == 0
      and "verdict: fixed the summary" in read(p)[0]["notes"])
try:
    mark_verdict.main(["Acme Widgets", "maybe"], p)
    check("unknown verdict is rejected", False)
except SystemExit:
    check("unknown verdict is rejected", True)
check("no match writes nothing", mark_verdict.main(["Initech", "skip_time"], p) == 1)

# --- pipeline_quality -----------------------------------------------------
check("stretch: cap fired is reach", pq.stretch({"unmet_hard_reqs": "1", "hard_req_cap_trigger": "5+ years in X"}) == "reach")
check("stretch: 2 unmet is reach", pq.stretch({"unmet_hard_reqs": "2", "hard_req_cap_trigger": "none"}) == "reach")
check("stretch: 1 unmet, no cap is fit", pq.stretch({"unmet_hard_reqs": "1", "hard_req_cap_trigger": "none"}) == "fit")
check("stretch: both blank is unrecorded", pq.stretch({"unmet_hard_reqs": "", "hard_req_cap_trigger": ""}) == "unrecorded")
check("pay_mid reads a K range", pq.pay_mid("Remote US, $130K-$160K, posted") == 145)
check("pay_mid reads a comma range", pq.pay_mid("$172,000-$215,000 base") == 193.5)
check("pay_mid returns None without a range", pq.pay_mid("no pay listed") is None)

p2 = write([row(stage="applied", furthest_stage="interview", unmet_hard_reqs="0", hard_req_cap_trigger="none"),
            row(stage="rejected", unmet_hard_reqs="3", hard_req_cap_trigger="none"),
            row(stage="surfaced", his_verdict="skip_fit"),
            row(stage="applied", surfaced_date="2026-07-01")])
rep = pq.report(pq.load(p2, pq.EPOCH))
check("pre-epoch rows are excluded", "Tailored: 3" in rep)
check("fit advance counted", "fit         advanced 1/1" in rep)
check("reach send counted", "reach       advanced 0/1" in rep)
check("skip verdict shows in breakdown", "skip_fit" in rep)

for f in (p, p + ".bak", p2):
    if os.path.exists(f):
        os.remove(f)
print(f"\n{'ALL PASS' if not FAILS else str(len(FAILS)) + ' FAILED'}")
sys.exit(1 if FAILS else 0)
