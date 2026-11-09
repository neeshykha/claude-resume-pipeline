#!/usr/bin/env python3
"""Tests for job_mail.py (queries, classification, the shadow compare, the verdict),
the inbox filter in harvest_linkedin.py, and the LinkedIn URL rule in mark_applied.py
and mark_outcome.py. Everything is made up: the inboxes are example.com addresses and
the companies are invented, so nothing here names Aneesh's accounts.

    .venv/bin/python pipeline/test_job_mail.py
"""
import datetime as dt
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harvest_linkedin as HL  # noqa: E402
import job_mail as JM  # noqa: E402
import mark_applied  # noqa: E402
import mark_outcome  # noqa: E402

MAIN = "main.inbox@example.com"
JOB = "job.inbox@example.com"
CFG = {"MAIN_ACCOUNT": MAIN, "APPLY_ACCOUNT": JOB, "JOB_MAIL_SOURCE": "forwarded"}
TERMS = JM.load_terms()
T0 = dt.datetime(2026, 11, 9, 8, 0, tzinfo=dt.timezone.utc)

fails = 0


def check(cond, msg):
    global fails
    if not cond:
        print(f"FAIL {msg}")
        fails += 1


def rec(account, sender, subject, minutes, to=None, rid=None):
    return {"id": rid or f"{account[:3]}-{sender}-{minutes}", "account": account,
            "sender": sender, "subject": subject, "date": T0 + dt.timedelta(minutes=minutes),
            "to": [to or JOB]}


def view(account):
    return f"https://mail.google.com/mail/?authuser={account}#all/thread-f:1|msg-f:1"


# ── queries ──
q = JM.queries(TERMS, 4)
jr = q["receipts"]["job_account"]
for s in TERMS["receipt_senders"]:
    check(s in jr, f"job-account receipts query lost sender {s}")
for p in TERMS["receipt_subjects"]:
    check((f'"{p}"' if " " in p else p) in jr, f"job-account receipts query lost subject {p}")
check("-in:sent" in jr and "-from:linkedin.com" in jr, "receipts query must skip sent mail and LinkedIn")
for s in TERMS["indeed_alert_senders"]:
    check(f"-from:{s}" in jr and f"-from:{s}" in q["receipts"]["forwarded"],
          f"both receipts queries must skip {s}")
check(q["receipts"]["forwarded"].startswith("deliveredto:{{CONFIRM_ALIAS}}"),
      "forwarded queries keep the alias placeholder")
check("newer_than:4d" in q["linkedin_alerts"]["job_account"]
      and "newer_than:4d" in q["linkedin_alerts"]["forwarded"], "LinkedIn window not applied")
check("viewed" not in q["easy_apply"]["job_account"], "the 'viewed' notice is not a receipt")
check(q["lapse_check"]["job_account"] == "newer_than:2d", "lapse check query changed")

# ── classify ──
cases = [
    ("no-reply@us.greenhouse-mail.io", "Thanks for applying", "receipts"),
    ("no-reply@hire.lever.co", "Thanks for your interest", "receipts"),
    ("noreply+jobs@google.com", "Invitation from a Googler", "receipts"),
    ("recruiter@bigco.example", "Following up on your recent application", "receipts"),
    ("no-reply@pagerduty.example", "Important information about your application", "receipts"),
    ("jobs-noreply@linkedin.com", "Aneesh, your application was sent to Acme", "easy_apply"),
    ("jobs-noreply@linkedin.com", "Your application to Support Lead at Acme", "easy_apply"),
    ("jobs-noreply@linkedin.com", "Your application was viewed by Acme", "linkedin_alerts"),
    ("jobalerts-noreply@linkedin.com", "Support Manager at Acme", "linkedin_alerts"),
    ("donotreply@jobalert.indeed.com", "Technical Account Manager at Acme", "indeed_alerts"),
    ("pm@contractor.example", "Shed pad quote", None),
    ("someone@notgreenhouse.io.example", "Lunch", None),
]
for sender, subject, want in cases:
    got = JM.classify(sender, subject, TERMS)
    check(got == want, f"classify({sender!r}, {subject!r}) = {got!r}, want {want!r}")

# ── account_of / records_from_text ──
check(JM.account_of({"viewUrl": view(JOB)}) == JOB, "account from a message viewUrl")
check(JM.account_of({}, {"viewUrl": view(MAIN)}) == MAIN, "account falls back to the thread")
check(JM.account_of({}) is None, "no viewUrl means no account")
listing = {"threads": [{"id": "t1", "viewUrl": view(MAIN), "messages": [
    {"id": "m1", "sender": "No-Reply@AshbyHQ.com", "subject": "Thanks for applying to Acme",
     "date": "2026-11-09T08:00:00Z", "toRecipients": [JOB.upper()]}]}]}
thread = {"id": "t2", "viewUrl": view(JOB), "messages": [
    {"id": "m2", "sender": "no-reply@ashbyhq.com", "subject": "Thanks for applying to Acme",
     "date": "2026-11-09T08:00:02Z", "toRecipients": [JOB]}]}
recs = JM.records_from_text(json.dumps(listing)) + JM.records_from_text(json.dumps(thread))
check(len(recs) == 2, f"records_from_text found {len(recs)} messages, want 2")
check(recs and recs[0]["account"] == MAIN and recs[0]["sender"] == "no-reply@ashbyhq.com"
      and recs[0]["to"] == [JOB], "listing record fields (account, lowercased sender and to)")
check(JM.records_from_text("not json") == [], "non-JSON text yields nothing")

# ── compare ──
records = [
    # a receipt in both inboxes, two seconds apart: matched
    rec(MAIN, "no-reply@ashbyhq.com", "Thanks for applying to Acme", 60),
    rec(JOB, "no-reply@ashbyhq.com", "Thanks for applying to  Acme", 60),
    # forwarded but missing from the job account: the failure the shadow week hunts for
    rec(MAIN, "no-reply@greenhouse-mail.io", "Your application to Beta Corp", 90),
    # only in the job account (a sender the filters missed would look like this)
    rec(JOB, "noreply+jobs@google.com", "Invitation to apply", 120),
    # an Easy Apply notice in both
    rec(MAIN, "jobs-noreply@linkedin.com", "Your application was sent to Gamma", 30),
    rec(JOB, "jobs-noreply@linkedin.com", "Your application was sent to Gamma", 31),
    # LinkedIn alert in both
    rec(MAIN, "jobalerts-noreply@linkedin.com", "Support Manager at Delta", 10),
    rec(JOB, "jobalerts-noreply@linkedin.com", "Support Manager at Delta", 10),
    # forwarded non-job mail (another filter): listed, never compared
    rec(MAIN, "pm@contractor.example", "Shed pad quote", 50),
    # main-inbox mail not addressed to the job account is not a forwarded copy
    rec(MAIN, "no-reply@ashbyhq.com", "Thanks for applying to Omega", 70, to=MAIN),
    # his own reply in the job account is not incoming mail
    rec(JOB, JOB, "Re: Your application to Beta Corp", 95),
    # older than the window's first 3 hours on either side: outside the overlap
    rec(JOB, "no-reply@lever.co", "Thank you for applying to Old Co", -3 * 24 * 60 + 300),
    rec(MAIN, "no-reply@lever.co", "Thank you for applying to Older Co", -3 * 24 * 60 + 200),
]
NOW = T0 + dt.timedelta(hours=4)
WINDOWS = {"receipts": 3, "easy_apply": 3, "linkedin_alerts": 2}
r = JM.compare(records, CFG, TERMS, WINDOWS, NOW)
rc = r["classes"]["receipts"]
check(rc["matched"] == 1, f"receipts matched {rc['matched']}, want 1")
check([m["subject"] for m in rc["missed"]] == ["Your application to Beta Corp"],
      f"receipts missed {rc['missed']}")
check([m["subject"] for m in rc["only_in_job_account"]] == ["Invitation to apply"],
      f"receipts extras {rc['only_in_job_account']} (the old Lever one is outside the overlap)")
check(rc["outside_overlap"] == 1, f"the old forwarded one is outside, not missed: {rc}")
check(r["classes"]["easy_apply"]["matched"] == 1, "Easy Apply twin within 15 minutes not matched")
check(r["classes"]["linkedin_alerts"]["matched"] == 1, "LinkedIn alert twin not matched")
check(r["forwarded_not_job_mail"] == ["contractor.example"], f"ignored {r['forwarded_not_job_mail']}")
check(r["missed_total"] == 1 and r["extras_total"] == 1, "totals")
check(not r["job_account_silent"], "job account answered, so it is not silent")

silent = JM.compare([rec(MAIN, "no-reply@ashbyhq.com", "Thanks for applying", 5)],
                    CFG, TERMS, WINDOWS, NOW)
check(silent["job_account_silent"] and silent["missed_total"] == 1,
      "forwarded mail with nothing from the job account is a silent job account")
far = JM.compare([rec(MAIN, "no-reply@ashbyhq.com", "Thanks for applying", 5),
                  rec(JOB, "no-reply@ashbyhq.com", "Thanks for applying", 5 + 20)],
                 CFG, TERMS, WINDOWS, NOW)
check(far["classes"]["receipts"]["matched"] == 0 and far["missed_total"] == 1
      and far["extras_total"] == 1, "a twin 20 minutes off is not a twin")
# A side whose listing had more pages only reached its newest mail, so older mail on
# the other side is left out instead of being called missed.
paged = [dict(rec(JOB, "no-reply@ashbyhq.com", "Thanks for applying to Acme", 60), truncated=True),
         rec(MAIN, "no-reply@ashbyhq.com", "Thanks for applying to Acme", 60),
         rec(MAIN, "no-reply@ashbyhq.com", "Thanks for applying to Zeta", 10)]
pr = JM.compare(paged, CFG, TERMS, WINDOWS, NOW)["classes"]["receipts"]
check(pr["matched"] == 1 and not pr["missed"] and pr["outside_overlap"] == 1,
      f"a paged-out side must not produce misses: {pr}")
# Paged to the end: the first page carried a token, the last didn't, so a forwarded
# alert older than anything in the job account is a real miss (Fable review, Nov 7).
full = [dict(rec(JOB, "jobalerts-noreply@linkedin.com", "TAM at Acme", -60), truncated=True),
        rec(JOB, "jobalerts-noreply@linkedin.com", "TAM at Beta", -3600),
        rec(MAIN, "jobalerts-noreply@linkedin.com", "TAM at Acme", -60),
        rec(MAIN, "jobalerts-noreply@linkedin.com", "TAM at Beta", -3600),
        rec(MAIN, "jobalerts-noreply@linkedin.com", "TAM at Gamma", -6000)]
fr = JM.compare(full, CFG, TERMS, dict(WINDOWS, linkedin_alerts=7), NOW)["classes"]["linkedin_alerts"]
check(fr["matched"] == 2 and [m["subject"] for m in fr["missed"]] == ["TAM at Gamma"],
      f"a listing paged to the end must still report the older miss: {fr}")
# The run lists forwarded alerts with the metadata-only view, which has no subject: on
# 2026-11-09 that matched 0 of 70. A body fetch of the same id fills the subject, and
# one no helper fetched pairs on sender and time.
LI = "jobalerts-noreply@linkedin.com"
nosub = [rec(MAIN, LI, "", 10, rid="f1"),                  # the listing
         rec(MAIN, LI, "TAM at Acme", 10, rid="f1"),       # the helper's body fetch
         rec(MAIN, LI, "", 130, rid="f2"),                 # listed, never fetched
         rec(JOB, LI, "TAM at Acme", 10, rid="j1"),
         rec(JOB, LI, "CSM at Beta", 130, rid="j2")]
nr = JM.compare(nosub, CFG, TERMS, WINDOWS, NOW)
nl = nr["classes"]["linkedin_alerts"]
check(nl["forwarded"] == 2 and nl["matched"] == 2 and nl["matched_by_time"] == 1
      and not nl["missed"] and not nl["only_in_job_account"],
      f"an alert listed without its subject must still find its twin: {nl}")
check(any("1 on sender and time alone" in line for line in JM.summary_lines(nr)),
      "the summary says how many matched without a subject")
# Two alerts in the same second: the one with no subject must not take the copy the
# subject match needs.
same_sec = [rec(MAIN, LI, "", 200, rid="f3"),
            rec(MAIN, LI, "TAM at Acme", 200, rid="f4"),
            rec(JOB, LI, "TAM at Acme", 200, rid="j3"),
            rec(JOB, LI, "CSM at Beta", 200, rid="j4")]
sl = JM.compare(same_sec, CFG, TERMS, WINDOWS, NOW)["classes"]["linkedin_alerts"]
check(sl["matched"] == 2 and sl["matched_by_time"] == 1 and not sl["missed"],
      f"subject twins pair first: {sl}")
# Two known subjects that differ are never twins, however close in time.
diff = [rec(MAIN, LI, "TAM at Acme", 220, rid="f5"), rec(JOB, LI, "CSM at Gamma", 220, rid="j5")]
dl = JM.compare(diff, CFG, TERMS, WINDOWS, NOW)["classes"]["linkedin_alerts"]
check(dl["matched"] == 0 and len(dl["missed"]) == 1 and len(dl["only_in_job_account"]) == 1,
      f"a different subject in the same second is a miss and an extra: {dl}")
silent_lines = JM.summary_lines(silent)
check(not any(line.startswith("SHADOW MISS") for line in silent_lines)
      and any("RETURNED NOTHING" in line for line in silent_lines),
      f"a silent job account prints one line, not a miss per message: {silent_lines}")
try:
    JM.compare([], {"MAIN_ACCOUNT": MAIN}, TERMS, WINDOWS, NOW)
    check(False, "compare without APPLY_ACCOUNT must refuse")
except ValueError:
    pass

# ── verdict ──
def shadow_file(d, day, missed=0, silent_flag=False, forwarded=1):
    body = {"classes": {c: {"matched": forwarded, "forwarded": forwarded} for c in JM.CLASSES},
            "missed_total": missed, "extras_total": 0, "job_account_silent": silent_flag}
    with open(os.path.join(d, f"mail_shadow_2026-11-{day:02d}.json"), "w") as f:
        json.dump(body, f)


with tempfile.TemporaryDirectory() as d:
    for day in (9, 10, 11):
        shadow_file(d, day)
    check(not JM.verdict(d)[0], "3 runs is not a pass")
    shadow_file(d, 12)
    shadow_file(d, 13, forwarded=0)
    ok, lines = JM.verdict(d)
    check(not ok and any("not counted" in line for line in lines),
          "a run that read no forwarded mail proves nothing and doesn't count")
    shadow_file(d, 14)
    ok, lines = JM.verdict(d)
    check(ok and lines[-1].startswith("VERDICT: PASS"), f"5 clean runs should pass: {lines[-1]}")
    shadow_file(d, 16, missed=1)
    check(not JM.verdict(d)[0], "a miss in the last 5 runs is not a pass")
    shadow_file(d, 17, silent_flag=True)
    check(not JM.verdict(d)[0], "a silent run is not a pass")

# ── source config ──
check(JM.source({}) == "forwarded", "no setting means the forwarded copy")
check(JM.source_account(CFG) == MAIN, "forwarded source acts on the main inbox")
check(JM.source_account(dict(CFG, JOB_MAIL_SOURCE="job_account")) == JOB,
      "job_account source acts on the job account")
check(JM.source_account({}) is None, "an old config filters nothing")
try:
    JM.source({"JOB_MAIL_SOURCE": "job-account"})
    check(False, "a misspelled JOB_MAIL_SOURCE must stop the run")
except ValueError:
    pass

# ── harvest_linkedin inbox filter ──
body_rec = HL._norm_record({"id": "m1", "sender": "jobalerts-noreply@linkedin.com",
                            "plaintextBody": "x", "viewUrl": view(MAIN)}, "t")
list_recs = HL._from_listing({"threads": [{"id": "t", "viewUrl": view(JOB), "messages": [
    {"id": "m2", "sender": "jobalerts-noreply@linkedin.com"}]}]}, "t")
check(body_rec["account"] == MAIN and list_recs[0]["account"] == JOB,
      "harvest records carry their inbox")
eml = {"id": "e", "sender": "jobalerts-noreply@linkedin.com", "account": None}
kept, dropped = HL.drop_other_inbox([body_rec] + list_recs + [eml], MAIN)
check([k["id"] for k in kept] == ["m1", "e"] and dropped == 1,
      f"inbox filter kept {[k['id'] for k in kept]}, dropped {dropped}")
check(HL.drop_other_inbox(list_recs, None) == (list_recs, 0), "no inbox set keeps everything")

# ── LinkedIn URL rule ──
row = "https://www.linkedin.com/jobs/view/4400000001/"
notice = ("https://www.linkedin.com/comm/jobs/view/4400000001/?trackingId=abc%3D%3D"
          "&refId=def&lipi=urn%3Ali%3Apage%3Aemail_email_application_confirmation_with_nba_01")
for mod in (mark_applied, mark_outcome):
    check(mod.norm_url(row) == mod.norm_url(notice),
          f"{mod.__name__}: a LinkedIn notice link must match the row's link")
    check(mod.norm_url("https://Boards.Greenhouse.io/acme/jobs/1/") ==
          "https://boards.greenhouse.io/acme/jobs/1", f"{mod.__name__}: other URLs unchanged")
    check(mod.norm_url(row) != mod.norm_url("https://www.linkedin.com/jobs/view/4400000002/"),
          f"{mod.__name__}: different job ids must not match")
    check(mod.norm_url("https://www.linkedin.com/jobs/view/support-lead-at-acme-4400000001") ==
          mod.norm_url(notice), f"{mod.__name__}: a slug-form row link must match too")

print(f"test_job_mail: {'ALL PASS' if not fails else str(fails) + ' FAIL'}")
sys.exit(1 if fails else 0)
