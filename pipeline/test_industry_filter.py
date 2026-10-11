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

sys.exit(1 if fails or prop_fails or empty_hits else 0)
