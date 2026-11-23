"""Unit-check false title matches against the live config.

  generalist           "Operations Generalist" must not match on a bare "General"
  sales support        a sales-support title must not ride tier1 "Technical Support Manager"
  operations support   "X Operations Support Manager" is not "Support Operations Manager"
  product manager      a PM title must not ride tier1 "Product Support Manager"
  executive support    an executive-assistant org is not "Head of Support"
  technical accounting "accounting" stems to "account", so it rode "Technical Account Manager"
  artificial intelligence  a spelled-out "Artificial Intelligence" title missed every "AI ..." tier
  quality lead         a support-quality lead and an operational excellence lead matched no tier

The first three were fixed 2026-10-09, the last three 2026-10-10. The first is a
tokenizer fix (_TOKEN_ALIASES keeps "generalist" whole). The rest are
_poller_config.hard_exclude_title_terms entries, because an exact tier1
match overrides TITLE_EXCLUDE and tier1 is protected from function_mismatch_titles,
so the hard list is the only config that reaches a tier1 match. Controls matter as
much as the targets: each fix has a real title sitting right next to it.

The last was fixed 2026-11-20 in the tokenizer and the \\bai\\b checks
(poll_ats.normalize_ai), not in config: the cases below pin that the spelled-out
form grades exactly like its "AI" form, whatever that grade is. The same day he
added "AI Platform Lead" (tier2c) and "AI Solutions Lead" (tier2b) and declined
"AI Support Manager", so that title is left out of CASES on purpose.

The quality-lead gap was fixed 2026-11-23 in config (D62): four narrow tier2 titles,
"Product Operations Lead" with its stemming cost pinned below, and "Agentforce" as a
review-only title. The broad forms ("Quality Lead", "Quality Manager") stay out, and
the controls below pin that.
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
T2 = "tier2_strong_overlap"
T2D = "tier2d_generalist_ops"
T3 = "tier3_reasonable_stretch"
T2C = "tier2c_tooling_systems"
T2B = "tier2b_ai_wildcard"

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

    ("Product Manager, Community Support", "hard_excluded", "rode Product Support Manager, one word between"),
    ("Sr. Product Manager (Support Copilot)", "hard_excluded", "adjacent words: no window setting catches it"),
    ("Senior Technical Product Manager, Operations and Data", "hard_excluded", "rode Technical Operations Manager"),
    ("Head of Global Executive Support", "hard_excluded", "rode Head of Support, two words between"),
    ("Executive Support Senior Program Manager, Tech Advisor", "hard_excluded", "rode Technical Support Manager"),
    ("Manager, Lease Operations Technical Accounting", "hard_excluded", "lease accounting, was tier1"),
    ("Senior Manager, Technical Accounting", "hard_excluded", "was tier2 through Technical Account Manager"),
    ("Product Support Manager", T1, "control"),
    ("Manager, Product Support", T1, "control, reordered"),
    ("Product Engagement Manager, User Operations", T1, "control: 'product' and 'manager' not contiguous"),
    ("Head of Technical Support", T1, "control"),
    ("Customer Support Manager, Executive Escalations", T1, "control: 'executive' present, phrase absent"),
    ("Product Operations Manager", T2, "control"),
    ("Technical Account Manager", T2, "control: 'account', not 'accounting'"),
    ("Partner Customer Success Manager (Accounting)", T3, "control: why the term isn't bare 'accounting'"),

    ("Artificial Intelligence Platform Manager", T2C, "spelled out, was dropped before 2026-11-20"),
    ("AI Platform Manager", T2C, "control: the config title"),
    ("Artificial Intelligence & Digital Transformation Manager", T2, "Sept card, was dropped"),
    ("Artificial Intelligence (AI) Program Manager", T2, "the '(AI)' is absorbed, not doubled"),
    ("Artificial-Intelligence Operations Manager", T2, "hyphenated spelling"),
    ("Artificial Intelligence Platform and Service Lead", T2C, "Oct 26 card: normalization plus 'AI Platform Lead'"),
    ("AI Platform Lead", T2C, "config title, added 2026-11-20"),
    ("Artificial Intelligence (AI) Solutions Lead - AI and Automation", T2B, "Oct 19 card, was supp"),
    ("AI Solutions and Adoption Lead", T2B, "Nov 9 card, was supp"),
    ("AI Solutions Specialist", "supplemental", "control: non-Lead 'AI Solutions' titles stay supp"),

    ("Lead, Quality, Elevated Support", T2, "Airbnb, Nov 13: no tier before 2026-11-23"),
    ("Operational Excellence Lead", T2, "Recidiviz, Nov 4: user-surfaced, no tier"),
    ("Senior Operations Manager, Quality Control", T2, "Upstart, Nov 23 probe"),
    ("Operational Excellence Manager", T2, "config title"),
    ("Product Operations Lead", T2, "Athos Commerce, Nov 23 probe"),
    ("Production Operations Lead", T2, "known cost he accepted: 'production' stems to 'product'"),
    ("Support Quality Manager", T2, "control: the older config title"),
    ("Clinical Quality Lead - PsyD/PhD", "dropped", "control: why the entry isn't bare 'Quality Lead'"),
    ("Consumer Ad Quality Lead", "dropped", "control: same"),
    ("Functional Lead, AI & Agentforce Delivery", "supplemental", "NeuraFlash: review-only, FYI line"),
]

# The AI wildcard and engineer route test a word-bounded "ai" on the raw title,
# outside the tokenizer, so they need their own spelled-out cases.
WILDCARD_CASES = [
    # (title, matches_ai_wildcard, matches_ai_engineer_stretch)
    ("Artificial Intelligence Knowledge Lead", True, False),
    ("AI Knowledge Lead", True, False),
    ("Artificial Intelligence Engineer", False, False),
    ("Artificial Intelligence Automation Engineer", False, True),
    ("Artificially Intelligent Knowledge Lead", False, False),
]
assert poll_ats.normalize_ai("Artificial Intelligence (AI) Support Manager") == "AI Support Manager"

fails = 0
for title, want, why in CASES:
    got = gate(title)
    ok = got == want
    fails += not ok
    print(f"  [{'ok ' if ok else 'FAIL'}] {got:22s} (want {want:22s})  {title!r:52s} {why}")
print(f"  {len(CASES) - fails}/{len(CASES)} passed\n")

wfails = 0
for title, want_wc, want_eng in WILDCARD_CASES:
    got = (MATCHER.matches_ai_wildcard(title), MATCHER.matches_ai_engineer_stretch(title))
    ok = got == (want_wc, want_eng)
    wfails += not ok
    print(f"  [{'ok ' if ok else 'FAIL'}] wildcard={got[0]!s:5s} engineer={got[1]!s:5s}  {title!r}")
print(f"  {len(WILDCARD_CASES) - wfails}/{len(WILDCARD_CASES)} wildcard cases passed\n")
fails += wfails

# A hard-exclude term that is a substring of a configured title would kill that
# title outright, with no digest trace.
with open(os.path.join(BASE, "watchlist_companies.json"), encoding="utf-8") as f:
    wl = json.load(f)
configured = []
for name, spec in wl["_title_scoring_tiers"].items():
    if isinstance(spec, dict):
        configured += spec.get("titles", []) + spec.get("explicit_titles", [])
configured += wl["_poller_config"]["supplemental_exact_titles"]["titles"]
clash = [(term, t) for term in ("operations support", "sales support", "product manager",
                                 "executive support", "technical accounting")
         for t in configured if term in t.lower()]
print("new terms hit no configured title:", "yes" if not clash else f"NO -> {clash}")

sys.exit(1 if fails or clash else 0)
