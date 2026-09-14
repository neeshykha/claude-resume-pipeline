"""Unit-check the AI engineer stretch route (poll_ats, 2026-09-14) against the live config.

  matches_ai_engineer_stretch  AI + engineer/architect/developer + an operating word
  route()                      the poll loop's full decision for one title

FullStory's "AI Automation Engineer" never reached review: it matched two borderline
fragments ("ai", "automation"), landed in a 140-entry borderline pool, and lost the
20-slot cap. The route pulls these titles out ahead of that cap. Two properties
matter more than any single case: exact tier matches keep their normal path, and the
unrouted exclusions (scientist, researcher) never take the route.
"""
import json, os, sys
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from poll_ats import TitleMatcher

# poll_ats builds its module MATCHER only when a run loads config, so build one here.
with open(os.path.join(BASE, "watchlist_companies.json"), encoding="utf-8") as f:
    MATCHER = TitleMatcher(json.load(f))


def route(title):
    """Mirror of the poll loop's title gate, in the loop's order."""
    if MATCHER.match_exact(title):
        return "exact"
    if MATCHER.matches_ai_wildcard(title):
        return "wildcard"
    if MATCHER.matches_ai_engineer_stretch(title):
        return "stretch"
    if MATCHER.fragment_count(title) >= MATCHER.min_fragments:
        return "borderline"
    return "dropped"


VISIBLE = {"exact", "wildcard", "borderline", "stretch"}

CASES = [
    # (title, expected, why); expected is an exact outcome or "visible"
    ("AI Automation Engineer", "stretch", "FullStory 2026-09-14, the miss that prompted this"),
    ("Senior AI Automation Engineer", "stretch", "seniority prefix"),
    ("AI Deployment Engineer", "stretch", "operating word: deployment"),
    ("AI Implementation Engineer", "stretch", "operating word: implementation"),
    ("AI Enablement Developer", "stretch", "developer is routed too"),
    ("AI Solutions Architect", "visible", "exact tier match keeps its normal path"),
    ("AI Support Engineer", "visible", "exact tier match keeps its normal path"),
    ("AI Engineer", "dropped", "bare IC coding title, no operating word"),
    ("Senior AI Engineer, Platform", "dropped", "platform is not an operating word"),
    ("Applied AI Engineer", "dropped", "no operating word"),
    ("AI Research Scientist", "dropped", "scientist is not routed"),
    ("Automation Engineer", "dropped", "no word-bounded AI"),
    ("Chair Operations Engineer", "dropped", "'ai' inside chair must not count"),
]

# Matcher-level checks, independent of what exact matching does to the title first.
DIRECT = [
    ("AI Solutions Researcher", False, "researcher never routes, even with an operating word"),
    ("AI Operations Scientist", False, "scientist never routes, even with an operating word"),
    ("AI Automation Engineer", True, "the FullStory title itself"),
]

fails = 0
print("route:")
for title, want, why in CASES:
    got = route(title)
    ok = (got in VISIBLE) if want == "visible" else (got == want)
    fails += not ok
    print(f"  [{'ok ' if ok else 'FAIL'}] {got:10s} (want {want:8s})  {title!r:34s} {why}")
print(f"  {len(CASES) - fails}/{len(CASES)} passed\n")

direct_fails = 0
print("matches_ai_engineer_stretch:")
for title, want, why in DIRECT:
    got = MATCHER.matches_ai_engineer_stretch(title)
    ok = got == want
    direct_fails += not ok
    print(f"  [{'ok ' if ok else 'FAIL'}] {str(got):5s} (want {str(want):5s})  {title!r:34s} {why}")
print(f"  {len(DIRECT) - direct_fails}/{len(DIRECT)} passed\n")

# The route must never claim a title the wildcard already takes.
overlap = [t for t, _, _ in CASES + DIRECT
           if MATCHER.matches_ai_wildcard(t) and MATCHER.matches_ai_engineer_stretch(t)]
print("no title is both wildcard and stretch:", "yes" if not overlap else f"NO -> {overlap}")

# Every routed word must also be a wildcard exclusion, or the route is dead config.
stray = [w for w in MATCHER.stretch_routed if w not in MATCHER.wc_exclude]
print("routed words are all wildcard exclusions:", "yes" if not stray else f"NO -> {stray}")
print("route configured:", "yes" if MATCHER.stretch_routed and MATCHER.stretch_operating else "NO")

sys.exit(1 if fails or direct_fails or overlap or stray or not MATCHER.stretch_routed else 0)
