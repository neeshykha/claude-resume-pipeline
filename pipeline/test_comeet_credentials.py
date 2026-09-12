"""Regression check for the Comeet credential scrape in harvest_ats.py (2026-09-11).

alice.io/careers embeds Comeet through the JS API, `COMEET.init({ token: '...',
'company-uid': '...' })`, a third embed shape next to the WordPress `comeetvar`
block and the careers-api URL. Before this fix the page failed twice over:
looks_like_comeet() found none of its markers, and the quoted 'company-uid' key
slipped past the loose uid pattern. No network: every fixture carries its
credentials inline, so comeet_credentials() never follows a script.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harvest_ats

ALICE_TOKEN = "5D51D29347D2EA828D3347DBAA2EA85D522FE"

# Trimmed from https://alice.io/careers as served 2026-09-11, structure kept
# as-is, including the commented-out css line inside the init object.
ALICE = """
<script data-ot-ignore>
  window.comeetInit = function () {
    COMEET.init({
      token: '5D51D29347D2EA828D3347DBAA2EA85D522FE',
      'company-uid': 'D5.005',
      'company-name': 'ActiveFence',
      // 'https://cdn.example.com/styles.txt',
      'css-url': 'https://cdn.example.com/comeet-styles.txt',
      'css-cache': false,
    });
  };
  (function (d, s, id) {
    var js, fjs = d.getElementsByTagName(s)[0];
    if (d.getElementById(id)) { return; }
    js = d.createElement(s); js.id = id;
    js.src = '//www.comeet.co/careers-api/api.js';
    fjs.parentNode.insertBefore(js, fjs);
  })(document, 'script', 'comeet-jsapi');
</script>
"""

DOUBLE_QUOTED = """
<script src="https://www.comeet.co/careers-api/api.js"></script>
<script>COMEET.init({"company-uid": "49.004", "token": "ABCDEF0123456789AB"});</script>
"""

# uid after token, and a nested object ahead of the close: the block must run
# to the outer `})`, not stop at the inner `},`.
NESTED = """
<script>
COMEET.init({
  'css-options': {'font': 'Inter', 'size': 14},
  token: 'FEDCBA9876543210FE',
  'company-uid': 'F6.007'
});
</script>
"""

# Analytics noise near an init call that carries no uid. The stray token must
# not be picked up and paired with anything.
INIT_NO_UID = """
<script>var cfg = {token: 'DEADBEEFDEADBEEF0000', uid: 'x'};</script>
<script>COMEET.init({ token: '0123456789ABCDEF01' });</script>
"""

WORDPRESS = """
<div class="comeet-outer-wrapper"></div>
<script>var comeetvar = {"comeet_token":"AAAABBBBCCCCDDDD11","comeet_uid":"49.004"};</script>
"""

API_URL = """
<div class="comeet-groups-list"></div>
<script src="https://www.comeet.co/careers-api/2.0/company/F6.007/positions?details=true&token=1234567890ABCDEF12"></script>
"""

NOT_COMEET = """
<div id="greenhouse-board"></div>
<script>window.analytics = {token: 'CAFEBABECAFEBABE1234', uid: 'ab.cde'};</script>
"""

CASES = [
    # (html, expected looks_like_comeet, expected credentials, why)
    (ALICE, True, ("D5.005", ALICE_TOKEN), "Alice: JS API embed, bare token + quoted company-uid"),
    (DOUBLE_QUOTED, True, ("49.004", "ABCDEF0123456789AB"), "JS API with double-quoted keys, uid first"),
    (NESTED, True, ("F6.007", "FEDCBA9876543210FE"), "JS API with a nested object before the close"),
    (INIT_NO_UID, True, None, "init without company-uid: no half-pair, no analytics token"),
    (WORDPRESS, True, ("49.004", "AAAABBBBCCCCDDDD11"), "WordPress comeetvar block still resolves"),
    (API_URL, True, ("F6.007", "1234567890ABCDEF12"), "careers-api URL embed still resolves"),
    (NOT_COMEET, False, None, "non-Comeet page: no markers"),
]

fails = 0
for html, want_looks, want_creds, why in CASES:
    looks = harvest_ats.looks_like_comeet(html)
    # Same gate probe_comeet applies: the scrape only runs on a page the
    # markers have already identified. The loose uid/token fallback relies on
    # that, since on its own it would pair NOT_COMEET's analytics values.
    creds = (harvest_ats.comeet_credentials(html, "https://example.com/careers")
             if looks else None)
    ok = looks == want_looks and creds == want_creds
    if not ok:
        fails += 1
    print(f"{'PASS' if ok else 'FAIL'}  looks={looks!s:<5} (want {want_looks!s:<5})  "
          f"creds={creds} (want {want_creds})  {why}")

print(f"\n{len(CASES) - fails}/{len(CASES)} passed")
sys.exit(1 if fails else 0)
