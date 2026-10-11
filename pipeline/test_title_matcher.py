"""Unit-check three false title matches (fixed 2026-10-09) against the live config.

  generalist         "Operations Generalist" must not match on a bare "General"
  sales support      a sales-support title must not ride tier1 "Technical Support Manager"
  operations support "X Operations Support Manager" is not "Support Operations Manager"

The first is a tokenizer fix (_TOKEN_ALIASES keeps "generalist" whole). The other
two are _poller_config.hard_exclude_title_terms entries, because an exact tier1
match overrides TITLE_EXCLUDE and tier1 is protected from function_mismatch_titles,
so the hard list is the only config that reaches a tier1 match. Controls matter as
much as the targets: each fix has a real title sitting right next to it.
"""
import json, os, sys
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import poll_ats

# _init_config (not a bare TitleMatcher) so the hard-exclude terms load too.
with open(os.path.join(BASE, "watchlist_companies.json"), encoding="utf-8") as f:
    poll_ats._init_config(json.load(f))
MATCHER = poll_ats.MATCHER


def gate(title, band=None):
    """Mirror of the poll loop's title gate, in the loop's order."""
    exact = MATCHER.match_exact(title)
    if poll_ats.title_hard_excluded(title):
        return "hard_excluded"
    if (poll_ats.title_excluded_for_company(title, band)
            and not (exact and MATCHER.is_tier1(title))):
        return "title_excluded"
    if exact:
        return exact[0]
    if MATCHER.fragment_count(title) >= MATCHER.min_fragments:
        return "borderline"
    return "dropped"


T1 = "tier1_true_match"
T2D = "tier2d_generalist_ops"

CASES = [
    # (title, expected, why)
    ("General Manager, DC Operations", "dropped", "the sweep title: 'general' is not 'generalist'"),
    ("General Manager, Operations", "dropped", "same shape"),
    ("Operations General Manager", "dropped", "same shape, reversed"),
    ("Operations Generalist", T2D, "the title the tier exists for"),
    ("People Operations Generalist", T2D, "RevenueCat, CopilotIQ: must keep matching"),
    ("People Ops Generalist", T2D, "Clutch: ops alias plus generalist"),
    ("Operations Generalists", T2D, "plural folds to the same token"),
    ("BizOps Generalist", T2D, "config title"),
    ("General Manager, Customer Support", T1, "a GM who runs support is still a target"),

    ("Technical Sales Support Manager", "hard_excluded", "the sweep title: sales support, not tech support"),
    ("Field Sales Support Systems Engineering Mgr - L5", "hard_excluded", "Lockheed card, graded tier1 in Sept"),
    ("Technical Support Manager", T1, "control"),
    ("Manager, Technical Support", T1, "control, reordered"),
    ("Technical Support Manager, Sales Tools", T1, "control: 'sales' present, phrase absent"),

    ("Director, Engineering & Operations Support", "hard_excluded", "the sweep title: plant engineering"),
    ("Traveling Community Operations Support Manager", "hard_excluded", "AIR Communities, shortlisted 8 runs"),
    ("Foreign Exchange Operations Support Leader", "hard_excluded", "US Bank, shortlisted 4 runs"),
    ("Operations Support Manager", "hard_excluded", "EthosEnergy and Amentum cards"),
    ("Support Operations Manager", T1, "control"),
    ("Senior Manager, Support Operations", T1, "control, reordered"),
    ("Customer Support Operations Manager", T1, "control"),
    ("Manager, Support & Operations", T1, "control"),
    ("Customer Operations & Support Manager", T1, "control: the ampersand breaks the phrase"),
    ("Senior Field Ops Support Manager", T1, "'Ops' spelling is left alone on purpose"),
    ("Customer Operations Support Manager", "hard_excluded", "known cost: a plausible real target dies"),
]

fails = 0
for title, want, why in CASES:
    got = gate(title)
    ok = got == want
    fails += not ok
    print(f"  [{'ok ' if ok else 'FAIL'}] {got:22s} (want {want:22s})  {title!r:52s} {why}")
print(f"  {len(CASES) - fails}/{len(CASES)} passed\n")

# A hard-exclude term that is a substring of a configured title would kill that
# title outright, with no digest trace.
with open(os.path.join(BASE, "watchlist_companies.json"), encoding="utf-8") as f:
    wl = json.load(f)
configured = []
for name, spec in wl["_title_scoring_tiers"].items():
    if isinstance(spec, dict):
        configured += spec.get("titles", []) + spec.get("explicit_titles", [])
configured += wl["_poller_config"]["supplemental_exact_titles"]["titles"]
clash = [(term, t) for term in ("operations support", "sales support")
         for t in configured if term in t.lower()]
print("new terms hit no configured title:", "yes" if not clash else f"NO -> {clash}")

sys.exit(1 if fails or clash else 0)
