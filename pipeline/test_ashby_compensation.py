"""Unit-check the Ashby pay reader (poll_ats.ashby_salary_range). No network.

Added 2026-11-12. Ashby's posting API puts pay under a `compensation` object
that extract_salary_min never read, so salary_min was null on every Ashby row
(17 of 56 matched on 2026-11-10) and neither the salary floor nor the
pre-score's pay points did anything for them.

What is pinned here:
  - a yearly USD Salary entry reads as (minimum, maximum), structured values
    first, the summary string only when there is no structured entry;
  - hourly, monthly, non-USD, bonus, commission, and equity figures are never
    read as base salary, and neither is a "Salary" a company labelled as
    on-target earnings, a base/variable split, or total cash;
  - hand-typed nonsense (hourly filed as yearly, a dropped K, a zero minimum)
    reads as nothing rather than as a salary;
  - every input the old extract_salary_min handled returns what it did;
  - the floor gate checks the MIDPOINT of the posted range when both ends are
    known and the minimum when only a minimum is (his call, 2026-11-12): a
    range with its minimum under the floor and its midpoint at or over it
    survives, a range with its midpoint under the floor is dropped, and a
    minimum-only posting is judged on its minimum, as before;
  - the maximum reaches the gate for both boards whose pay this file reads
    (Ashby, Pinpoint) and rides along as an optional `salary_max` key;
  - the pre-score's pay points are behind `_scoring_config.pay_points_enabled`:
    nothing with the key absent or false, +5 at the floor and +10 at $130K on
    the posted minimum with it true, which is what they paid before the switch.

Every company and posting below is made up. The Ashby shapes are Ashby's own,
read from live boards on 2026-11-12. The Pinpoint fixture carries only the
fields fetch_pinpoint reads; `compensation_maximum` was not re-read from a live
board when these cases were written.
"""
import copy
import json
import os
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poll_ats as P

CASES = []
NOTHING = (None, None)


def case(fn):
    CASES.append(fn)
    return fn


def part(kind, lo=None, hi=None, interval="1 YEAR", currency="USD", label=None):
    """One pay component. `label` is the free-text `summary` a tier component carries."""
    c = {"compensationType": kind, "interval": interval, "currencyCode": currency,
         "minValue": lo, "maxValue": hi}
    if label is not None:
        c["summary"] = label
    return c


def ashby(summary, parts, tier_title=None, tier_note=None, labels=None, scrape=None):
    """A one-tier `compensation` object in the shape Ashby returns it."""
    labels = labels or {}
    tier_parts = [dict(p, id=f"zzq-{i}", summary=labels.get(p["compensationType"], "zzq summary"))
                  for i, p in enumerate(parts)]
    return {
        "compensationTierSummary": summary,
        "scrapeableCompensationSalarySummary": summary.split(" • ")[0].replace("–", "-") if scrape is None else scrape,
        "compensationTiers": [{"id": "zzq-tier", "tierSummary": summary, "title": tier_title,
                               "additionalInformation": tier_note, "components": tier_parts}],
        "summaryComponents": [dict(p) for p in parts],
    }


def text_only(summary, scrape=""):
    """Only the strings, no structured entries: the fallback path."""
    return {"compensationTierSummary": summary, "scrapeableCompensationSalarySummary": scrape,
            "compensationTiers": [], "summaryComponents": []}


def reads(comp, want):
    """The range reads as `want`, and extract_salary_min agrees on the minimum."""
    got = P.ashby_salary_range(comp)
    return got == want and P.extract_salary_min(comp) == want[0], got


# ── structured values ────────────────────────────────────────────────────────

@case
def structured_yearly_usd_reads_min_and_max():
    comp = ashby("$95.8K – $140K • Offers Bonus",
                 [part("Salary", 95800, 140000), part("Bonus")])
    return reads(comp, (95800, 140000))


@case
def structured_single_figure_is_both_ends():
    comp = ashby("$350K • Offers Equity", [part("Salary", 350000, 350000),
                                          part("EquityPercentage", interval="NONE", currency=None)])
    return reads(comp, (350000, 350000))


@case
def structured_minimum_without_a_maximum():
    comp = ashby("$120K", [part("Salary", 120000, None)])
    return reads(comp, (120000, None))


@case
def bonus_commission_and_equity_figures_are_not_the_salary():
    """The other entries carry yearly USD numbers too, some lower than the base."""
    comp = ashby("$133,868 – $147,960 • $60K – $90K Equity • $37,758 – $41,732 Commission • $10K – $15K Bonus",
                 [part("Salary", 133868, 147960), part("EquityCashValue", 60000, 90000),
                  part("Commission", 37758, 41732), part("Bonus", 10000, 15000)],
                 labels={"Salary": "$133,868 – $147,960", "Commission": "$37,758 – $41,732 Commission",
                         "Bonus": "$10K – $15K Bonus", "EquityCashValue": "$60K – $90K Equity"})
    return reads(comp, (133868, 147960))


@case
def no_salary_entry_reads_nothing_even_with_commission_dollars():
    comp = ashby("$40K – $60K Commission • Offers Equity",
                 [part("Commission", 40000, 60000), part("EquityCashValue")],
                 scrape="")
    return reads(comp, NOTHING)


@case
def a_base_salary_note_does_not_block_the_read():
    """A long company note that says "base salary" and mentions variable pay is still base."""
    note = ("This is the US base salary range for this position. Please note that the range listed "
            "reflects only base salary. The total compensation package includes variable pay "
            "(where applicable), equity, and a range of benefits.")
    comp = ashby("$112K – $151K • Offers Equity • " + note,
                 [part("Salary", 112000, 151000), part("EquityCashValue")],
                 tier_title="Compensation", tier_note=note,
                 labels={"Salary": "Estimated Base Salary $112K – $151K"})
    return reads(comp, (112000, 151000))


@case
def non_usd_rollup_over_us_tiers_reads_the_us_tiers():
    """One made-up posting, three tiers: Canada in CAD (the roll-up), two US tiers in USD."""
    comp = {
        "compensationTierSummary": "CA$175K – CA$385K • Offers Equity • Multiple Ranges",
        "scrapeableCompensationSalarySummary": "CA$175K - CA$385K",
        "summaryComponents": [part("Salary", 175000, 385000, currency="CAD")],
        "compensationTiers": [
            {"title": "Canada", "additionalInformation": None, "tierSummary": "CA$175K – CA$385K",
             "components": [part("Salary", 175000, 385000, currency="CAD", label="CA$175K – CA$385K")]},
            {"title": "USA - coastal", "additionalInformation": None, "tierSummary": "$140K – $325K",
             "components": [part("Salary", 140000, 325000, label="$140K – $325K")]},
            {"title": "USA - all other states", "additionalInformation": None, "tierSummary": "$120K – $275K",
             "components": [part("Salary", 120000, 275000, label="$120K – $275K")]},
        ],
    }
    return reads(comp, (120000, 325000))


# ── summary strings (no structured entry) ────────────────────────────────────

@case
def summary_string_with_k():
    return reads(text_only("$95.8K – $140K • Offers Bonus"), (95800, 140000))


@case
def summary_string_with_commas():
    return reads(text_only("$120,000 - $150,000"), (120000, 150000))


@case
def summary_string_single_figure():
    return reads(text_only("$350K • Offers Equity • Offers Commission"), (350000, 350000))


@case
def summary_string_salary_plus_bonus_plus_equity_reads_the_salary_only():
    comp = text_only("$133,868 – $147,960 • Offers Equity • $37,758 – $41,732 Commission • $10K – $15K Bonus")
    return reads(comp, (133868, 147960))


@case
def scrapeable_summary_is_read_when_the_tier_summary_is_blank():
    return reads(text_only("", scrape="$170.9K - $200K"), (170900, 200000))


@case
def summary_string_that_opens_with_another_pay_type_reads_nothing():
    bad = ["Offers Equity • Offers Bonus", "$40K – $60K Commission • Offers Equity",
           "0.006% – 0.011%", "$15K Bonus", "Competitive"]
    got = [(s, P.ashby_salary_range(text_only(s))) for s in bad]
    return all(g == NOTHING for _, g in got), got


# ── hourly, monthly, weekly ──────────────────────────────────────────────────

@case
def hourly_reads_nothing():
    structured = ashby("$32 – $39 per hour", [part("Salary", 32, 39, interval="1 HOUR")],
                       scrape="$32 - $39")
    string = text_only("$32 – $39 per hour", scrape="$32 - $39")
    got = [P.ashby_salary_range(structured), P.ashby_salary_range(string),
           P.extract_salary_min(structured), P.extract_salary_min(string)]
    return got == [NOTHING, NOTHING, None, None], got


@case
def hourly_rate_filed_as_yearly_reads_nothing():
    """Seen live: interval "1 YEAR" on $23 – $25. The summary string has no "per hour" either."""
    structured = ashby("$23 – $25 • Offers Equity", [part("Salary", 23, 25), part("EquityCashValue")])
    got = [P.ashby_salary_range(structured), P.ashby_salary_range(text_only("$23 – $25 • Offers Equity"))]
    return got == [NOTHING, NOTHING], got


@case
def monthly_and_weekly_read_nothing():
    comps = [ashby("$12.5K per month", [part("Salary", 12500, 12500, interval="1 MONTH")], scrape="$12.5K"),
             ashby("$3K per week", [part("Salary", 3000, 3000, interval="1 WEEK")], scrape="$3K"),
             text_only("$18,750 per month", scrape="$18,750"),
             # structured says monthly; a salary-looking string must not overrule it
             ashby("$150K – $180K", [part("Salary", 150000, 180000, interval="1 MONTH")])]
    got = [P.ashby_salary_range(c) for c in comps]
    return all(g == NOTHING for g in got), got


# ── other currencies ─────────────────────────────────────────────────────────

@case
def non_usd_reads_nothing():
    comps = [ashby("CA$120K – CA$150K • Offers Equity", [part("Salary", 120000, 150000, currency="CAD")],
                   scrape="CA$120K - CA$150K"),
             ashby("€83,336 – €91,729", [part("Salary", 83336, 91729, currency="EUR")], scrape="€83,336 - €91,729"),
             ashby("£110K – £130K", [part("Salary", 110000, 130000, currency="GBP")], scrape="£110K - £130K"),
             ashby("$120K – $150K", [part("Salary", 120000, 150000, currency=None)]),
             text_only("CA$120K – CA$150K • Offers Equity", scrape="CA$120K - CA$150K"),
             text_only("€83,336 – €91,729"), text_only("£110K – £130K"), text_only("A$150K – A$180K"),
             text_only("SGD\xa0150K – SGD\xa0180K"), text_only("MX$900K – MX$1.2M")]
    got = [P.ashby_salary_range(c) for c in comps]
    return all(g == NOTHING for g in got), got


# ── on-target earnings and other totals filed as "Salary" ────────────────────

@case
def ote_label_on_the_salary_component_reads_nothing():
    """Ashby has no OTE type. The only place it shows is the tier component's own label."""
    comps = [ashby("$217K – $298K • Offers Equity • Offers Commission",
                   [part("Salary", 217000, 298000), part("EquityCashValue"), part("Commission")],
                   labels={"Salary": label})
             for label in ("OTE $217K – $298K", "On-Target Earnings $217K – $298K",
                           "On Target Earnings (Base + Commissions) $217K – $298K",
                           "OTE 75/25 Split $217K – $298K", "Base + Commission $217K – $298K",
                           "Total Compensation Base + Bonus $217K – $298K", "TCC $217K – $298K",
                           "Cash Range $217K – $298K")]
    got = [P.ashby_salary_range(c) for c in comps]
    return all(g == NOTHING for g in got), got


@case
def ote_in_the_tier_title_or_note_reads_nothing():
    base = [part("Salary", 180000, 250000), part("EquityCashValue")]
    comps = [ashby("$180K – $250K • Offers Equity", base, tier_title="OTE"),
             ashby("$180K – $250K • Offers Equity • OTE 75/25", base, tier_note="OTE 75/25"),
             ashby("$180K – $250K • Offers Equity • 70/30 split", base, tier_note="70/30 split"),
             ashby("$180K – $250K • Offers Equity • The range above is On-Target Earnings (OTE).", base,
                   tier_note="The range above is On-Target Earnings (OTE)."),
             ashby("$180K – $250K • Offers Equity", base,
                   tier_note="Target total cash compensation, including base salary and bonus or commission")]
    got = [P.ashby_salary_range(c) for c in comps]
    return all(g == NOTHING for g in got), got


@case
def ote_in_the_summary_string_reads_nothing():
    got = [P.ashby_salary_range(text_only(s)) for s in
           ("$200K – $250K • Offers Equity • OTE 50/50", "$200K – $250K • 50/50 split",
            "$200K – $250K • Offers Commission • $300K OTE")]
    return all(g == NOTHING for g in got), got


# ── hand-typed nonsense ──────────────────────────────────────────────────────

@case
def unbelievable_numbers_read_nothing():
    rows = [("zero minimum", part("Salary", 0, 298000)),
            ("dropped K on the minimum", part("Salary", 110, 165000)),
            ("both in thousands", part("Salary", 230, 350)),
            ("maximum under minimum", part("Salary", 150000, 120000)),
            ("minimum over the ceiling", part("Salary", 1800000, 2100000)),
            ("maximum over the ceiling", part("Salary", 180000, 21000000)),
            ("under a minimum-wage year", part("Salary", 7500, 9000)),
            ("no minimum", part("Salary", None, 140000)),
            ("minimum is text", part("Salary", "120000", 140000)),
            ("minimum is a bool", part("Salary", True, 140000))]
    got = [(why, P.ashby_salary_range(ashby("zzq", [p], scrape=""))) for why, p in rows]
    return all(g == NOTHING for _, g in got), got


@case
def malformed_shapes_read_nothing_and_do_not_raise():
    shapes = [None, "", 0, [], {}, {"compensationTiers": None, "summaryComponents": None},
              {"compensationTiers": "zzq", "summaryComponents": {"a": 1}},
              {"compensationTiers": [None, "zzq", {"components": [None, 7]}], "summaryComponents": [None, "x"]},
              {"compensationTierSummary": None, "scrapeableCompensationSalarySummary": 12},
              {"compensationTierSummary": 95, "summaryComponents": []}]
    got = [P.ashby_salary_range(s) for s in shapes]
    return all(g == NOTHING for g in got), got


# ── no compensation at all ───────────────────────────────────────────────────

@case
def no_compensation_key_reads_nothing():
    posting = {"id": "zzq-1", "title": "Zzq Desk Lead", "location": "Atlanta, GA"}
    hidden = {"compensationTierSummary": "", "scrapeableCompensationSalarySummary": "",
              "compensationTiers": [], "summaryComponents": []}      # what Ashby sends when pay is hidden
    comp = posting.get("compensation") or posting.get("salary")       # the lookup poll_all does
    got = [P.extract_salary_min(comp), P.ashby_salary_range(comp),
           P.extract_salary_min(hidden), P.ashby_salary_range(hidden)]
    return got == [None, NOTHING, None, NOTHING], got


# ── inputs the old extract_salary_min already handled ────────────────────────

@case
def flat_min_key_still_reads():
    """fetch_pinpoint's shape."""
    got = [P.extract_salary_min({"min": 120000}), P.extract_salary_min({"minimum": "95000"}),
           P.extract_salary_min({"minValue": 110000.0}), P.extract_salary_min({"floor": 105000})]
    return got == [120000, 95000, 110000, 105000], got


@case
def nested_dict_still_reads():
    got = [P.extract_salary_min({"salary": {"min": 110000, "max": 140000}}),
           P.extract_salary_min({"min": None, "range": {"floor": "90000"}}),
           P.extract_salary_min({"compensation": {"minimum": 101000}})]
    return got == [110000, 90000, 101000], got


@case
def plain_string_still_reads_its_first_number():
    """Unchanged on purpose, the last line included: a top-level string was never Ashby's."""
    got = [P.extract_salary_min("$120,000 - $150,000"), P.extract_salary_min("120000"),
           P.extract_salary_min("USD 98,500 per year"), P.extract_salary_min("$95.8K – $140K")]
    return got == [120000, 120000, 98500, 95], got


@case
def empty_and_unknown_inputs_still_read_nothing():
    got = [P.extract_salary_min(x) for x in
           (None, "", {}, [], 0, {"currency": "USD"}, {"min": "n/a"}, "Competitive", 120000, ["$120,000"])]
    return all(g is None for g in got), got


# ── the top of the range, and the floor rule, without poll_all ───────────────

REAL_WATCHLIST = P.WATCHLIST_PATH
FLOOR = 100_000          # what every fixture below is written against
ABSENT = object()        # the pay_points_enabled key is not in the config at all


def real_watchlist():
    with open(REAL_WATCHLIST, encoding="utf-8") as f:
        return json.load(f)


@case
def the_fixtures_assume_a_100k_floor():
    """If salary_floor_usd moves, the numbers in this file have to move with it."""
    got = real_watchlist()["_scoring_config"]["salary_floor_usd"]
    return got == FLOOR, got


@case
def salary_max_reads_the_shapes_salary_min_reads():
    comp = ashby("$95.8K – $140K • Offers Bonus", [part("Salary", 95800, 140000), part("Bonus")])
    got = [P.extract_salary_max({"min": 95000, "max": 140000}),          # fetch_pinpoint's shape
           P.extract_salary_max({"minimum": "95000", "maximum": "140000"}),
           P.extract_salary_max({"minValue": 110000.0, "maxValue": 150000.0}),
           P.extract_salary_max({"floor": 105000, "ceiling": 125000}),
           P.extract_salary_max({"salary": {"min": 110000, "max": 140000}}),
           P.extract_salary_max({"min": None, "range": {"floor": "90000", "ceiling": "120000"}}),
           P.extract_salary_max(comp)]
    return got == [140000, 140000, 150000, 125000, 140000, 120000, 140000], got


@case
def salary_max_is_nothing_when_only_a_minimum_is_posted():
    got = [P.extract_salary_max({"min": 120000}), P.extract_salary_max({"salary": {"min": 110000}}),
           P.extract_salary_max(ashby("$120K", [part("Salary", 120000, None)])),
           P.extract_salary_max({"min": 120000, "max": "n/a"}), P.extract_salary_max({"min": 120000, "max": None})]
    return all(g is None for g in got), got


@case
def salary_max_is_never_read_from_a_plain_string():
    """extract_salary_min still takes a string's first number; nothing vouches for a second one."""
    strings = ("$120,000 - $150,000", "$32 - $39 per hour", "$120K plus $20K bonus", "Competitive", "120000")
    got = [P.extract_salary_max(s) for s in strings] + [P.extract_salary_max(x) for x in (None, "", 0, [], {}, 150000)]
    return all(g is None for g in got), got


@case
def floor_basis_is_the_midpoint_when_both_ends_are_known():
    got = [P.salary_floor_basis(80000, 130000), P.salary_floor_basis(95800, 140000),
           P.salary_floor_basis(350000, 350000)]
    return got == [105000, 117900, 350000], got


@case
def floor_basis_is_the_minimum_when_only_a_minimum_is_known():
    got = [P.salary_floor_basis(90000), P.salary_floor_basis(120000, None), P.salary_floor_basis(120000, 0)]
    return got == [90000, 120000, 120000], got


@case
def floor_basis_ignores_a_maximum_under_its_minimum():
    got = [P.salary_floor_basis(120000, 90000), P.salary_floor_basis(90000, 80000)]
    return got == [120000, 90000], got


@case
def no_minimum_read_means_no_basis_and_no_drop():
    pairs = [(None, None), (None, 140000), (0, 140000), (0, None)]
    got = [(P.salary_floor_basis(lo, hi), P.under_salary_floor(lo, hi, floor=FLOOR)) for lo, hi in pairs]
    return all(g == (None, False) for g in got), got


@case
def under_the_floor_on_every_branch_of_the_rule():
    rows_ = [("minimum under, midpoint over", 80000, 130000, False),
             ("minimum under, midpoint exactly at the floor", 90000, 110000, False),
             ("midpoint one dollar under", 90000, 109998, True),
             ("midpoint under", 80000, 110000, True),
             ("both ends over", 105000, 125000, False),
             ("both ends under", 70000, 90000, True),
             ("minimum only, under", 90000, None, True),
             ("minimum only, one dollar under", 99999, None, True),
             ("minimum only, at the floor", 100000, None, False),
             ("minimum only, over", 120000, None, False),
             ("maximum under its minimum, judged on the minimum", 90000, 80000, True)]
    got = [(why, P.under_salary_floor(lo, hi, floor=FLOOR)) for why, lo, hi, _ in rows_]
    return [g for _, g in got] == [want for *_, want in rows_], got


@case
def under_the_floor_uses_the_config_floor_when_none_is_passed():
    P._init_config(real_watchlist())
    got = [P.MIN_SALARY, P.under_salary_floor(80000, 130000), P.under_salary_floor(80000, 110000),
           P.under_salary_floor(90000), P.under_salary_floor(120000)]
    return got == [FLOOR, False, True, True, False], got


@case
def the_pay_points_switch_is_on_only_for_a_json_true():
    wl = real_watchlist()
    sc = wl["_scoring_config"]
    got = []
    try:
        for value in (ABSENT, False, True, "true", "false", 1, 0, None):
            sc.pop("pay_points_enabled", None)
            if value is not ABSENT:
                sc["pay_points_enabled"] = value
            P._init_config(wl)
            got.append(("absent" if value is ABSENT else repr(value), P.PAY_POINTS_ENABLED))
    finally:
        sc.pop("pay_points_enabled", None)
        P._init_config(wl)
    return [g for _, g in got] == [False, False, True, False, False, False, False, False], got


# ── through poll_all ─────────────────────────────────────────────────────────

RUN = date(2026, 1, 15)
PUBLISHED = datetime.combine(RUN - timedelta(days=20), datetime.min.time()).isoformat() + "Z"
TITLES = ["Zzq Desk Lead", "Zzq Bench Lead", "Zzq Yard Lead", "Zzq Dock Lead", "Zzq Loft Lead",
          "Zzq Pier Lead", "Zzq Mill Lead", "Zzq Barn Lead", "Zzq Quay Lead", "Zzq Shed Lead",
          "Zzq Cove Lead", "Zzq Glen Lead"]


def posting(n, title, comp):
    return {"id": f"zzq-{n}", "title": title, "location": "Atlanta, GA", "workplaceType": "OnSite",
            "address": {"postalAddress": {"addressCountry": "United States"}},
            "publishedAt": PUBLISHED, "isListed": True, "compensation": comp}


def pinpoint_posting(n, title, lo=None, hi=None, visible=True):
    """A Pinpoint postings.json row, as far as fetch_pinpoint and parse_location read it."""
    return {"id": f"zzq-pp-{n}", "title": title, "url": f"https://zzq-pp-{n}.example.invalid/postings/{n}",
            "location": {"city": "Atlanta", "province": "Georgia"},
            "compensation_visible": visible, "compensation_minimum": lo, "compensation_maximum": hi}


class FakeResponse:
    """What fetch_pinpoint needs from requests.get, and nothing else."""
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def run_board(board, pay_points=ABSENT, ats="ashby"):
    """poll_all over a made-up board: temp watchlist, empty seen_jobs, no network.

    One company per posting, so the two-per-company shortlist cap keeps every
    surviving role in `matched` with its full entry. `pay_points` is what
    _scoring_config.pay_points_enabled holds in the temp watchlist; ABSENT
    leaves the key out, which is how the real file stands. An Ashby board is
    served through fetch_ashby; a Pinpoint board goes through the real
    fetch_pinpoint over a stand-in for requests.get, so its normalization runs.
    Any other request raises.
    """
    work = tempfile.mkdtemp(prefix="ashby_pay_test_")
    wl = real_watchlist()
    wl["companies"] = [{"name": f"Zzq Fixture {p['id']}", "ats": ats, "slug": p["id"], "priority": "high"}
                       for p in board]
    wl["_poller_config"]["supplemental_exact_titles"]["titles"] = TITLES
    wl["_scoring_config"].pop("pay_points_enabled", None)
    if pay_points is not ABSENT:
        wl["_scoring_config"]["pay_points_enabled"] = pay_points
    wl_path, seen_path = os.path.join(work, "watchlist.json"), os.path.join(work, "seen_jobs.json")
    with open(wl_path, "w", encoding="utf-8") as f:
        json.dump(wl, f, ensure_ascii=False)
    with open(seen_path, "w") as f:
        json.dump({"jobs": {}}, f)

    def fake_get(url, **kwargs):
        for p in board:
            if ats == "pinpoint" and url == P.ATS_ENDPOINTS["pinpoint"].format(slug=p["id"]):
                return FakeResponse({"data": [copy.deepcopy(p)]})
        raise AssertionError(f"unexpected network call: {url}")

    real = (P.fetch_ashby, P.requests.get, P.WATCHLIST_PATH, P.SEEN_JOBS_PATH, P.time.sleep)
    P.fetch_ashby = lambda slug: [dict(p) for p in board if p["id"] == slug]
    P.requests.get = fake_get
    P.WATCHLIST_PATH, P.SEEN_JOBS_PATH = wl_path, seen_path
    P.time.sleep = lambda s: None
    try:
        return P.poll_all(RUN, fail_memory=False)
    finally:
        P.fetch_ashby, P.requests.get, P.WATCHLIST_PATH, P.SEEN_JOBS_PATH, P.time.sleep = real
        shutil.rmtree(work, ignore_errors=True)


BOARD = [
    posting(1, "Zzq Desk Lead", {"compensationTierSummary": "", "scrapeableCompensationSalarySummary": "",
                                 "compensationTiers": [], "summaryComponents": []}),
    posting(2, "Zzq Bench Lead", ashby("$105K – $125K", [part("Salary", 105000, 125000)])),
    posting(3, "Zzq Yard Lead", ashby("$135K – $160K • Offers Equity",
                                      [part("Salary", 135000, 160000), part("EquityCashValue")])),
    # minimum under the floor, midpoint $105K over it
    posting(4, "Zzq Dock Lead", ashby("$80K – $130K", [part("Salary", 80000, 130000)])),
    posting(5, "Zzq Loft Lead", ashby("$80K – $130K • Offers Commission",
                                      [part("Salary", 80000, 130000), part("Commission")],
                                      labels={"Salary": "OTE $80K – $130K"})),
    # midpoint $95K, under the floor
    posting(6, "Zzq Pier Lead", ashby("$80K – $110K", [part("Salary", 80000, 110000)])),
    # minimum only, under the floor
    posting(7, "Zzq Mill Lead", ashby("$90K", [part("Salary", 90000, None)])),
    # minimum only, over the floor
    posting(8, "Zzq Barn Lead", ashby("$120K", [part("Salary", 120000, None)])),
    # midpoint exactly at the floor
    posting(9, "Zzq Quay Lead", ashby("$90K – $110K", [part("Salary", 90000, 110000)])),
    # the two pay-point thresholds, and a dollar under the upper one
    posting(10, "Zzq Shed Lead", ashby("$130K", [part("Salary", 130000, None)])),
    posting(11, "Zzq Cove Lead", ashby("$100K", [part("Salary", 100000, None)])),
    posting(12, "Zzq Glen Lead", ashby("$129,999 – $150K", [part("Salary", 129999, 150000)])),
]
DROPPED = {"Zzq Pier Lead", "Zzq Mill Lead"}
SURVIVORS = [p["title"] for p in BOARD if p["title"] not in DROPPED]
_RESULTS = {}


def result(pay_points=ABSENT):
    """One poll_all per setting of the switch, run once."""
    key = "absent" if pay_points is ABSENT else pay_points
    if key not in _RESULTS:
        _RESULTS[key] = run_board(BOARD, pay_points=pay_points)
    return _RESULTS[key]


def rows(pay_points=ABSENT):
    return {j["title"]: j for j in result(pay_points)["matched"]}


def everywhere(res):
    return [j["title"] for key in ("matched", "near_window", "borderline") for j in res[key]]


def over_base(pay_points):
    """Each surviving role's pre-score less the no-pay role's, in SURVIVORS order."""
    r = rows(pay_points)
    base = r["Zzq Desk Lead"]["pre_score"]
    return {t: r[t]["pre_score"] - base for t in SURVIVORS if t != "Zzq Desk Lead"}


@case
def poll_all_fills_salary_min_and_the_optional_salary_max():
    r = rows()
    got = {t: (j.get("salary_min"), j.get("salary_max"), "salary_max" in j) for t, j in r.items()}
    want = {"Zzq Desk Lead": (None, None, False), "Zzq Bench Lead": (105000, 125000, True),
            "Zzq Yard Lead": (135000, 160000, True), "Zzq Dock Lead": (80000, 130000, True),
            "Zzq Loft Lead": (None, None, False), "Zzq Barn Lead": (120000, None, False),
            "Zzq Quay Lead": (90000, 110000, True), "Zzq Shed Lead": (130000, None, False),
            "Zzq Cove Lead": (100000, None, False), "Zzq Glen Lead": (129999, 150000, True)}
    return got == want, got


@case
def poll_all_keeps_a_range_with_its_minimum_under_the_floor_and_midpoint_over():
    """$80K – $130K: minimum under $100K, midpoint $105K. The gate reads the midpoint."""
    j = rows().get("Zzq Dock Lead")
    return j is not None and (j["salary_min"], j.get("salary_max")) == (80000, 130000), j


@case
def poll_all_keeps_a_range_with_its_midpoint_exactly_at_the_floor():
    """$90K – $110K. At the floor is not under it."""
    return "Zzq Quay Lead" in rows(), sorted(rows())


@case
def poll_all_drops_a_range_with_its_midpoint_under_the_floor():
    """$80K – $110K: midpoint $95K."""
    res = result()
    return "Zzq Pier Lead" not in everywhere(res), everywhere(res)


@case
def poll_all_drops_a_minimum_only_posting_under_the_floor():
    """$90K and no maximum: judged on the minimum, as before."""
    res = result()
    return "Zzq Mill Lead" not in everywhere(res), everywhere(res)


@case
def poll_all_keeps_a_minimum_only_posting_over_the_floor():
    """$120K and no maximum."""
    j = rows().get("Zzq Barn Lead")
    return j is not None and j["salary_min"] == 120000 and "salary_max" not in j, j


@case
def poll_all_counts_the_two_drops_and_nothing_else():
    res = result()
    got = (res["stats"]["excluded"], res["stats"]["title_matched"], sorted(rows()))
    return got == (len(DROPPED), len(SURVIVORS), sorted(SURVIVORS)), got


@case
def poll_all_ote_under_the_floor_is_not_dropped():
    """Same numbers as a kept range, labelled OTE: unread, so neutral, as before."""
    j = rows().get("Zzq Loft Lead")
    return j is not None and j["salary_min"] is None, j


@case
def poll_all_pay_points_add_nothing_with_the_switch_absent():
    got = over_base(ABSENT)
    return set(got.values()) == {0} and len(got) == len(SURVIVORS) - 1, got


@case
def poll_all_pay_points_add_nothing_with_the_switch_false():
    got = over_base(False)
    return set(got.values()) == {0} and len(got) == len(SURVIVORS) - 1, got


@case
def poll_all_pay_points_pay_five_at_the_floor_and_ten_at_130k_with_the_switch_true():
    """On the posted MINIMUM, as before the switch: a role kept on its midpoint with a
    minimum under the floor gets nothing."""
    got = over_base(True)
    want = {"Zzq Bench Lead": 5, "Zzq Yard Lead": 10, "Zzq Dock Lead": 0, "Zzq Loft Lead": 0,
            "Zzq Barn Lead": 5, "Zzq Quay Lead": 0, "Zzq Shed Lead": 10, "Zzq Cove Lead": 5,
            "Zzq Glen Lead": 5}
    return got == want, got


@case
def poll_all_the_switch_moves_no_score_but_the_pay_points_and_no_gate():
    off, false, on = rows(ABSENT), rows(False), rows(True)
    same_rows = sorted(off) == sorted(false) == sorted(on) == sorted(SURVIVORS)
    base = {off["Zzq Desk Lead"]["pre_score"], false["Zzq Desk Lead"]["pre_score"],
            on["Zzq Desk Lead"]["pre_score"]}
    excluded = {result(s)["stats"]["excluded"] for s in (ABSENT, False, True)}
    return same_rows and len(base) == 1 and excluded == {len(DROPPED)}, (sorted(on), base, excluded)


# Pinpoint is the other board whose pay this file reads. Same rule, through the
# real fetch_pinpoint.
PINPOINT_BOARD = [
    pinpoint_posting(1, "Zzq Desk Lead", visible=False),
    pinpoint_posting(2, "Zzq Dock Lead", 80000.0, 130000.0),     # minimum under, midpoint over
    pinpoint_posting(3, "Zzq Pier Lead", 80000.0, 110000.0),     # midpoint under
    pinpoint_posting(4, "Zzq Mill Lead", 90000.0),               # minimum only, under
    pinpoint_posting(5, "Zzq Barn Lead", 120000.0),              # minimum only, over
    pinpoint_posting(6, "Zzq Loft Lead", 80000.0, 130000.0, visible=False),   # pay hidden: unread
]


def pinpoint_result():
    if "pinpoint" not in _RESULTS:
        _RESULTS["pinpoint"] = run_board(PINPOINT_BOARD, ats="pinpoint")
    return _RESULTS["pinpoint"]


@case
def fetch_pinpoint_carries_the_maximum_beside_the_minimum():
    P._init_config(real_watchlist())
    board = [pinpoint_posting(1, "Zzq Dock Lead", 80000.0, 130000.0), pinpoint_posting(2, "Zzq Barn Lead", 120000.0),
             pinpoint_posting(3, "Zzq Loft Lead", 80000.0, 130000.0, visible=False)]
    real = P.requests.get
    P.requests.get = lambda url, **kwargs: FakeResponse({"data": copy.deepcopy(board)})
    try:
        jobs = P.fetch_pinpoint("zzq-pp")
    finally:
        P.requests.get = real
    got = [(j.get("compensation"), P.extract_salary_min(j.get("compensation")),
            P.extract_salary_max(j.get("compensation"))) for j in jobs]
    want = [({"min": 80000.0, "max": 130000.0}, 80000, 130000), ({"min": 120000.0}, 120000, None),
            (None, None, None)]
    return got == want, got


@case
def poll_all_applies_the_midpoint_rule_to_pinpoint_too():
    res = pinpoint_result()
    got = {j["title"]: (j.get("salary_min"), j.get("salary_max")) for j in res["matched"]}
    want = {"Zzq Desk Lead": (None, None), "Zzq Dock Lead": (80000, 130000),
            "Zzq Barn Lead": (120000, None), "Zzq Loft Lead": (None, None)}
    return got == want and res["stats"]["excluded"] == 2, (got, res["stats"]["excluded"])


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
