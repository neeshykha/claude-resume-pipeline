"""Unit-check the industry filter (poll_ats.description_excluded), fixed 2026-10-10.

It was a substring test, so "defi" fired inside define / defined / defining /
redefining / definition / deficiencies and dropped the posting with no digest
trace. It now matches whole words at non-alphanumeric boundaries, through the
same _boundary_pattern the location lists use.

Controls matter as much as the targets: a real crypto description has to stay
excluded in every spelling seen on live crypto boards, and markup or punctuation
around a term must not hide it. The cases marked "known cost" and "unchanged"
are not fixes; they pin what the rule still gets wrong so a later edit moves
them on purpose.
"""
import os, sys
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import poll_ats

OUT, KEEP = True, False

CASES = [
    # (description text, excluded?, why)
    ("We're redefining how care teams work.", KEEP, "the boilerplate that hid 70 of 76 postings on one board"),
    ("You'll define the roadmap and own clearly defined SLAs.", KEEP, "define / defined"),
    ("Defining process for a growing support team.", KEEP, "defining, sentence-initial capital"),
    ("A clear definition of done, and definitions the team shares.", KEEP, "definition / definitions"),
    ("Document deficiencies found during plant inspections.", KEEP, "deficiencies: the materials-board case"),
    ("Redefine, predefined, undefined, definitive, definite, deficits, defiance.", KEEP, "every other form seen live"),
    ("Erreichung der definierten Ziele.", KEEP, "German posting, seen live"),
    ("<p>We are <strong>redefining</strong> customer&nbsp;support.</p>", KEEP, "markup around the word changes nothing"),
    ("Experience with cryptography and cryptographic key management (HSM, KMS).", KEEP, "security work, not the industry"),
    ("Our cryptographers review every protocol change.", KEEP, "same stem"),
    ("Gestalte die Zukunft mit uns. Auskunft gibt das Team.", KEEP, "'nft' inside German words"),

    ("Join the leading crypto exchange.", OUT, "control: bare word"),
    ("We work in crypto.", OUT, "control: period is a boundary"),
    ("A crypto-native team.", OUT, "control: hyphen is a boundary"),
    ("Institutional cryptocurrency custody.", OUT, "control: listed spelling"),
    ("Trade 400+ cryptocurrencies.", OUT, "control: listed plural"),
    ("Building the Web3 developer platform.", OUT, "control: case-insensitive"),
    ("The web3.0 stack.", OUT, "control: version suffix"),
    ("Blockchain-based settlement across public blockchains.", OUT, "control: singular and plural"),
    ("BLOCKCHAIN ENGINEERING", OUT, "control: all caps"),
    ("The largest DeFi/NFT marketplace.", OUT, "control: slash between two terms"),
    ("Decentralized finance (DeFi) protocols.", OUT, "control: parentheses"),
    ("Mint and trade NFTs.", OUT, "control: plural"),
    ("<li>Crypto</li>", OUT, "control: tags on both sides"),
    ("<strong>DeFi</strong>&nbsp;lending", OUT, "control: tag, then an entity"),
    ("deploy the crypto_wallet service", OUT, "control: underscore is a boundary"),
    ("redefining finance with blockchain", OUT, "control: a false-positive word beside a real term"),

    ("Custody for cryptoassets under the UK cryptoasset regime.", OUT, "control: the regulator's spelling"),
    ("Support for 30+ cryptos.", OUT, "control: listed plural"),
    ("Apply at https://crypto.com/careers", OUT, "control: a URL host counts, dots are boundaries"),
    ("Questions to jobs@defillama.com", KEEP, "glued inside an address, not a word"),

    ("Maintain our crypto libraries (FIPS 140-3).", OUT, "known cost: security shorthand reads as the industry"),
    ("RELEVER LE DEFI DE LA CROISSANCE", OUT, "known cost: French 'défi' in an unaccented heading"),
    ("Un défi stimulant.", KEEP, "the accented spelling is not the term"),
    ("Tokenomics and cryptoeconomics research.", KEEP, "known cost: an unlisted compound slips through"),
    ("Bridging TradFi and on-chain markets.", KEEP, "unchanged: neither rule names these"),
    ("The Web 3 gaming platform.", KEEP, "unchanged: spaced spelling was never matched"),
    ("", KEEP, "empty description"),
]

fails = 0
for text, want, why in CASES:
    got = poll_ats.description_excluded(text)
    ok = got == want
    fails += not ok
    print(f"  [{'ok ' if ok else 'FAIL'}] {'excluded' if got else 'kept':8s} "
          f"(want {'excluded' if want else 'kept':8s})  {text[:58]!r:62s} {why}")
print(f"  {len(CASES) - fails}/{len(CASES)} passed\n")

# Property: each term matches alone and between separators, and stops matching
# the moment a letter or digit touches either side, unless that longer string is
# itself a listed term. This is what a slide back to substring matching breaks.
terms = set(poll_ats.EXCLUDED_TERMS)
prop_fails = []
for term in sorted(terms):
    for text in (term, term.upper(), f"({term})", f"a {term}. b", f"<b>{term}</b>", f"x/{term}/y"):
        if not poll_ats.description_excluded(text):
            prop_fails.append(f"missed {text!r}")
    for text in (f"x{term}", f"{term}x", f"re{term}ne", f"9{term}", f"{term}9"):
        if poll_ats.description_excluded(text) and text not in terms:
            prop_fails.append(f"glued {text!r}")
print("terms match whole and never glued:", "yes" if not prop_fails else f"NO -> {prop_fails}")

# An empty term list has to mean "exclude nothing". An empty alternation matches
# at every separator, so without the guard in _boundary_pattern, emptying
# EXCLUDED_TERMS to switch the filter off would drop nearly every posting.
empty = poll_ats._boundary_pattern([])
empty_hits = [t for t in ("", "hello world.", "<p>billing software</p>", "crypto") if empty.search(t)]
print("an empty list excludes nothing:", "yes" if not empty_hits else f"NO -> {empty_hits}")

# The drop trace (added 2026-10-11). A posting this filter drops is written to
# the poller's output with the word that caused it, and to the lane poll's file
# the same way. Offline: one made-up Lever board, temp watchlist and seen_jobs.
import json, shutil, tempfile
from datetime import date, datetime, timedelta
import poll_lane

term_cases = [("Join the leading Crypto exchange.", "crypto"), ("<strong>DeFi</strong> lending", "defi"),
              ("Mint NFTs on public blockchains.", "nfts"), ("We're redefining support.", None), ("", None)]
term_fails = [(t, poll_ats.excluded_industry_term(t)) for t, want in term_cases
              if poll_ats.excluded_industry_term(t) != want]
term_fails += [(t, "disagrees with description_excluded") for t, _, _ in CASES
               if (poll_ats.excluded_industry_term(t) is not None) != poll_ats.description_excluded(t)]
print("the matched word is reported, lowercased:", "yes" if not term_fails else f"NO -> {term_fails}")

RUN = date(2026, 1, 15)
CREATED = int(datetime.combine(RUN - timedelta(days=3), datetime.min.time().replace(hour=12)).timestamp() * 1000)
TITLES = ["Quokka Desk Lead", "Quokka Bench Lead", "Quokka Yard Lead"]


def posting(jid, title, description):
    return {"id": jid, "text": title, "categories": {"location": "Remote - United States"},
            "createdAt": CREATED, "hostedUrl": f"https://example.test/{jid}", "description": description}


BOARD = [
    posting("a", "Quokka Desk Lead", "<p>Run the support desk for a billing product.</p>"),
    posting("b", "Quokka Bench Lead", "<p>Join the leading crypto exchange.</p>"),
    posting("c", "Quokka Yard Lead", "<p>We're redefining how yards are run.</p>"),
    posting("d", "Plant Electrician", "<p>Blockchain-based metering.</p>"),   # no title match: never reaches the filter
]

work = tempfile.mkdtemp(prefix="industry_test_")
with open(poll_ats.WATCHLIST_PATH, encoding="utf-8") as f:
    wl = json.load(f)
wl["companies"] = [{"name": "Quokka Works", "ats": "lever", "slug": "quokka", "priority": "high"}]
wl["_poller_config"]["supplemental_exact_titles"]["titles"] = TITLES
wl_path, seen_path = os.path.join(work, "watchlist.json"), os.path.join(work, "seen_jobs.json")
with open(wl_path, "w", encoding="utf-8") as f:
    json.dump(wl, f, ensure_ascii=False)
with open(seen_path, "w") as f:
    json.dump({"jobs": {}}, f)
lane_wl = dict(wl, companies=[dict(wl["companies"][0], lane="testlane")])
lane_wl_path = os.path.join(work, "lane_watchlist.json")
with open(lane_wl_path, "w", encoding="utf-8") as f:
    json.dump(lane_wl, f, ensure_ascii=False)

real = (poll_ats.fetch_lever, poll_ats.WATCHLIST_PATH, poll_ats.SEEN_JOBS_PATH, poll_ats.time.sleep)
poll_ats.fetch_lever = lambda slug: [dict(p) for p in BOARD]
poll_ats.WATCHLIST_PATH, poll_ats.SEEN_JOBS_PATH = wl_path, seen_path
poll_ats.time.sleep = lambda s: None
try:
    res = poll_ats.poll_all(RUN)
    _, lane_payload = poll_lane.run(RUN, "testlane", jobs_dir=os.path.join(work, "jobs"),
                                    watchlist_path=lane_wl_path)
finally:
    poll_ats.fetch_lever, poll_ats.WATCHLIST_PATH, poll_ats.SEEN_JOBS_PATH, poll_ats.time.sleep = real
    shutil.rmtree(work, ignore_errors=True)

dropped = res["industry_excluded"]
kept = sorted(j["title"] for j in res["matched"] + res["near_window"])
trace_checks = [
    (len(dropped) == 1 and dropped[0]["title"] == "Quokka Bench Lead" and dropped[0]["term"] == "crypto"
     and dropped[0]["company"] == "Quokka Works" and dropped[0]["apply_url"] == "https://example.test/b"
     and "location" in dropped[0],
     f"the one drop is listed with its word: {dropped}"),
    (res["stats"]["industry_excluded"] == 1 and res["stats"]["excluded"] >= 1,
     f"counted on its own and still inside `excluded`: {res['stats']['industry_excluded']}, {res['stats']['excluded']}"),
    (kept == ["Quokka Desk Lead", "Quokka Yard Lead"],
     f"the clean posting and the 'redefining' one both surface: {kept}"),
    (lane_payload["industry_excluded"] == dropped,
     "the lane poll's file carries the same row"),
]
for ok, what in trace_checks:
    print(f"  [{'ok ' if ok else 'FAIL'}] {what}")
trace_fails = [what for ok, what in trace_checks if not ok]

sys.exit(1 if fails or prop_fails or empty_hits or term_fails or trace_fails else 0)
