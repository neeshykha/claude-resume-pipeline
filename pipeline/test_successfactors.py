"""Test bar for the SuccessFactors adapter (docs/ats_contract.md section 8).

Four parts, each printing its own PASS/FAIL summary; the script exits 1 if any
part fails:

  1. OFFLINE CASES -- feed-shape parsing and no-board classification against
     synthetic, safe fixtures (no real company data): looks_like_rmk_feed,
     parse_feed (both shapes), parse_detail_page, and resolve_board's status
     classification (no_board / real-empty -> [] / real -> list / throttled).
  2. LIVE single-requisition integration -- resolves a real board (CRH, the
     "rss" feed shape) and parses a real, named requisition's title, location,
     and apply URL. Written to fail before ats_successfactors.py existed (see
     the run captured before implementation, kept in the adapter's notes).
  3. LIVE pagination past page 1 -- Avanos (urlset shape, full board < cap,
     proves completeness) and Wipro (urlset shape, board >> cap, proves the
     cap stops it) against docs/ats_contract.md section 8 item 3.
  4. Budget under a simulated hang -- a local socket that accepts and never
     answers, probed with a 3s Budget; must return within budget + ~1s with no
     exception, never a hang. docs/ats_contract.md section 8 item 4.

Live parts (2, 3) need network and hit real company career sites; they are
read-only GETs against public job boards, same as verify_workday.py.
"""
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ats_successfactors as sf
import harvest_ats

fails_total = 0


def section(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


# ─────────────────────────────────────────────────────────────────────────
# 1. OFFLINE CASES -- synthetic fixtures, safe for this public repo
# ─────────────────────────────────────────────────────────────────────────
section("1. OFFLINE CASES: feed-shape parsing + no-board classification")

# A tiny, fully synthetic RSS-shape feed (two postings, fake company).
FAKE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0"><channel>
<title>Example Corp Jobs</title>
<item>
  <title>Support Operations Manager (Springfield, IL, US, 62701)</title>
  <description><![CDATA[<p>Job ID: 1001</p><p>Own the support queue.</p>]]></description>
  <link>https://jobs.example-corp.test/job/Springfield-Support-Operations-Manager/9001001/</link>
  <guid isPermaLink="false">9001001</guid>
  <g:id>9001001</g:id>
  <g:expiration_date>2026-12-01</g:expiration_date>
  <g:employer>Example Corp Jobs</g:employer>
  <g:location>Springfield, IL, US, 62701</g:location>
</item>
<item>
  <title>Field Technician (Contract)</title>
  <description><![CDATA[<p>Job ID: 1002</p>]]></description>
  <link>https://jobs.example-corp.test/job/Remote-Field-Technician/9001002/</link>
  <g:id>9001002</g:id>
  <g:location>Remote</g:location>
</item>
</channel></rss>"""

FAKE_RSS_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0"><channel>
<title>rmkcdn.successfactors.com Example Corp Jobs (no reqs open)</title>
</channel></rss>"""

FAKE_URLSET = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.google.com/schemas/sitemap/0.9">
<url><loc>https://jobs.example-corp.test/job/Denver-Warehouse-Lead-CO-80202/8801/</loc><lastmod>2026-09-12</lastmod></url>
<url><loc>https://jobs.example-corp.test/job/Austin-Warehouse-Lead-TX-78701/8802/</loc><lastmod>2026-09-12</lastmod></url>
</urlset>"""

NOT_RMK_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.google.com/schemas/sitemap/0.9">
<url><loc>https://www.example-blog.test/2026/09/hello-world/</loc></url>
<url><loc>https://www.example-blog.test/about/</loc></url>
</urlset>"""

NOT_XML_AT_ALL = "<html><body>404 Not Found</body></html>"

FAKE_DETAIL_PAGE = """<html><head>
<title>Warehouse Lead - Denver, CO Job Details | examplecorp</title>
<meta property="og:title" content="Warehouse Lead - Denver, CO" />
<link rel="canonical" href="https://jobs.example-corp.test/job/Denver-Warehouse-Lead/8801-en_US/" />
</head><body>
<div class="jobDisplayShell" itemscope itemtype="http://schema.org/JobPosting">
<span itemprop="description">Requisition ID: 8801</span>
<span itemprop="description">Own the regional warehouse team.</span>
</div></body></html>"""

FAKE_DETAIL_PAGE_NOT_SF = """<html><head><title>Warehouse Lead</title></head>
<body>Some unrelated careers page with a coincidental /job/x/8801/ URL shape.</body></html>"""


class FakeResp:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


offline_cases = [
    # (name, get_fn, expected_status, expected_count_or_None, why)
    ("real rss board, 2 postings",
     lambda url: FakeResp(FAKE_RSS), "ok", 2,
     "the CRH-shape feed: title/location/link all inline"),
    ("real rss board, confirmed empty",
     lambda url: FakeResp(FAKE_RSS_EMPTY), "ok", 0,
     "board resolves, zero <item> -> [] (real empty board, section 2's rule)"),
    ("real urlset board (detail pages fetched)",
     lambda url: (FakeResp(FAKE_URLSET) if url.endswith("/sitemap.xml")
                  else FakeResp(FAKE_DETAIL_PAGE)),
     "ok", 2,
     "the Wipro/Avanos-shape feed: title/location resolved per-posting"),
    ("host with no sitemap.xml at all (404)",
     lambda url: FakeResp("Not Found", status_code=404), "no_board", None,
     "nonexistent identifier -> None, per contract item 2"),
    ("host with an unrelated, non-RMK sitemap.xml",
     lambda url: FakeResp(NOT_RMK_SITEMAP), "no_board", None,
     "a bare sitemap.xml exists on countless sites; 200 alone is not proof of a board"),
    ("host whose /sitemap.xml isn't XML at all",
     lambda url: FakeResp(NOT_XML_AT_ALL), "no_board", None,
     "malformed/HTML body must not raise, must read as no-board"),
    ("network failure (get_fn returns None)",
     lambda url: None, "no_board", None,
     "connection refused / DNS failure -> no board, not an exception"),
    ("throttled on the very first request",
     lambda url: sf.THROTTLED, "throttled", None,
     "a 429 must read as unknown, never as no_board (section 6's THROTTLED rule)"),
]

fails = 0
for name, get_fn, want_status, want_count, why in offline_cases:
    try:
        status, postings, total = sf.resolve_board("host.example.test", get_fn)
        ok = status == want_status and (want_count is None or len(postings) == want_count)
    except Exception as e:
        status, ok = f"EXCEPTION {type(e).__name__}: {e}", False
    if not ok:
        fails += 1
    got_desc = status if not ok or want_count is None else f"{status} ({len(postings)} postings)"
    print(f"[{'ok ' if ok else 'FAIL'}] {name:<45s} got={got_desc!r:<25} why={why}")
print(f"{len(offline_cases) - fails}/{len(offline_cases)} passed")
fails_total += fails

# looks_like_rmk_feed and parse_detail_page, in CASES form too.
parse_cases = [
    (sf.looks_like_rmk_feed(FAKE_RSS), True, "rss shape with g: fields -> True"),
    (sf.looks_like_rmk_feed(NOT_RMK_SITEMAP), False, "generic blog sitemap -> False"),
    (sf.looks_like_rmk_feed(NOT_XML_AT_ALL), False, "not XML at all -> False"),
    (sf.parse_detail_page(FAKE_DETAIL_PAGE, "fallback")["title"], "Warehouse Lead",
     "og:title split on ' - ', location dropped"),
    (sf.parse_detail_page(FAKE_DETAIL_PAGE, "fallback")["location"], "Denver, CO",
     "og:title's second half"),
    (sf.parse_detail_page(FAKE_DETAIL_PAGE, "fallback")["url"],
     "https://jobs.example-corp.test/job/Denver-Warehouse-Lead/8801-en_US/",
     "canonical link preferred over the fallback sitemap URL"),
    (sf.parse_detail_page(FAKE_DETAIL_PAGE_NOT_SF, "fallback"), None,
     "no schema.org/JobPosting markup -> None, not a false-positive parse"),
    (sf._strip_location_suffix("Contracts Administrator (Lunenburg, MA, US, 01462)",
                               "Lunenburg, MA, US, 01462"),
     "Contracts Administrator", "exact-match parenthetical suffix stripped"),
    (sf._strip_location_suffix("Field Technician (Contract)", "Remote"),
     "Field Technician (Contract)",
     "parenthetical that does NOT match location is left alone"),
]
fails2 = 0
for got, want, why in parse_cases:
    ok = got == want
    if not ok:
        fails2 += 1
    print(f"[{'ok ' if ok else 'FAIL'}] got={got!r:<60} want={want!r:<35} {why}")
print(f"{len(parse_cases) - fails2}/{len(parse_cases)} passed")
fails_total += fails2


# ─────────────────────────────────────────────────────────────────────────
# 2. LIVE: single real requisition (contract section 8, item 1)
# ─────────────────────────────────────────────────────────────────────────
section("2. LIVE: resolve a real board, parse one real requisition (CRH)")


def _plain_get(url):
    import requests
    return requests.get(url, timeout=30,
                        headers={"User-Agent": sf.SF_UA})


live2_ok = False
try:
    t0 = time.monotonic()
    status, postings, total = sf.resolve_board("jobs.crh.com", _plain_get)
    elapsed = time.monotonic() - t0
    print(f"status={status}  total_in_feed={total}  postings_returned={len(postings or [])}"
         f"  elapsed={elapsed:.1f}s")
    if status == "ok" and postings:
        req = postings[0]
        title_ok = bool(req.get("title"))
        loc_ok = bool(req.get("location")) and req["location"] != "Unknown"
        url_ok = req.get("url", "").startswith("https://jobs.crh.com/job/")
        live2_ok = title_ok and loc_ok and url_ok
        print(f"  named requisition:")
        print(f"    title    = {req['title']!r}")
        print(f"    location = {req['location']!r}")
        print(f"    apply_url= {req['url']!r}")
        print(f"  [{'ok ' if title_ok else 'FAIL'}] title parsed")
        print(f"  [{'ok ' if loc_ok else 'FAIL'}] location parsed (not 'Unknown')")
        print(f"  [{'ok ' if url_ok else 'FAIL'}] apply URL is a real jobs.crh.com job link")
    else:
        print("  FAIL: board did not resolve with postings")
except Exception as e:
    print(f"  FAIL: {type(e).__name__}: {e}")
print(f"[{'ok ' if live2_ok else 'FAIL'}] live single-requisition integration")
if not live2_ok:
    fails_total += 1


# ─────────────────────────────────────────────────────────────────────────
# 3. LIVE: pagination past page 1 (contract section 8, item 3)
# ─────────────────────────────────────────────────────────────────────────
section("3. LIVE: pagination past page 1 (Avanos full read, Wipro capped read)")

live3_ok = True

# 3a. Avanos: urlset shape, small enough board that the detail-page walk
# should read EVERY posting the sitemap reports -- proves completeness past
# whatever a single "page" would have been (25, per the background note).
try:
    t0 = time.monotonic()
    status, postings, total = sf.resolve_board("careers.avanos.com", _plain_get)
    elapsed = time.monotonic() - t0
    read = len(postings or [])
    ok_a = status == "ok" and total is not None and total > 25 and read == total
    print(f"Avanos: status={status}  sitemap_total={total}  read={read}  "
         f"cap={sf.SUCCESSFACTORS_URLSET_DETAIL_CAP}  elapsed={elapsed:.1f}s")
    print(f"  [{'ok ' if (total and total > 25) else 'FAIL'}] total exceeds one 25-item page")
    print(f"  [{'ok ' if read == total else 'FAIL'}] read count ({read}) == sitemap total ({total})")
    live3_ok &= ok_a
except Exception as e:
    print(f"Avanos: FAIL {type(e).__name__}: {e}")
    live3_ok = False

# 3b. Wipro: urlset shape, 5290+ postings -- far larger than the cap. Proves
# the cap stops the walk rather than reading (or hanging on) the whole board.
try:
    t0 = time.monotonic()
    status, postings, total = sf.resolve_board("careers.wipro.com", _plain_get)
    elapsed = time.monotonic() - t0
    read = len(postings or [])
    cap = sf.SUCCESSFACTORS_URLSET_DETAIL_CAP
    # read <= cap, not necessarily == cap: the walk ATTEMPTS exactly `cap`
    # detail-page fetches (items[:cap]), but a sitemap can list a posting
    # whose detail page has since 404'd (stale entry) -- resolve_board skips
    # that one rather than failing the whole board (see its urlset branch),
    # so `read` can land a little under `cap`. What matters for the cap proof
    # is that it never reads anywhere near the 5000+ total.
    ok_w = status == "ok" and total is not None and total > cap and read <= cap
    print(f"Wipro: status={status}  sitemap_total={total}  read={read}  cap={cap}  "
         f"elapsed={elapsed:.1f}s")
    print(f"  [{'ok ' if (total and total > cap) else 'FAIL'}] "
         f"sitemap total ({total}) far exceeds the cap ({cap})")
    print(f"  [{'ok ' if read <= cap else 'FAIL'}] read ({read}) capped at/under {cap}, "
         f"nowhere near the {total} total")
    live3_ok &= ok_w
except Exception as e:
    print(f"Wipro: FAIL {type(e).__name__}: {e}")
    live3_ok = False

# 3c. CRH: rss shape, 1897 postings in ONE response (no per-item request at
# all) -- proves the OTHER cap, SUCCESSFACTORS_MAX_POSTINGS, same way: total
# from the feed exceeds the cap, and what's returned is capped at it.
try:
    t0 = time.monotonic()
    status, postings, total = sf.resolve_board("jobs.crh.com", _plain_get)
    elapsed = time.monotonic() - t0
    read = len(postings or [])
    cap = sf.SUCCESSFACTORS_MAX_POSTINGS
    ok_c = status == "ok" and total is not None and total > cap and read == cap
    print(f"CRH (rss shape): status={status}  feed_total={total}  read={read}  cap={cap}  "
         f"elapsed={elapsed:.1f}s")
    print(f"  [{'ok ' if (total and total > cap) else 'FAIL'}] "
         f"feed total ({total}) exceeds SUCCESSFACTORS_MAX_POSTINGS ({cap})")
    print(f"  [{'ok ' if read == cap else 'FAIL'}] read capped at exactly {cap}, not {total}")
    live3_ok &= ok_c
except Exception as e:
    print(f"CRH: FAIL {type(e).__name__}: {e}")
    live3_ok = False

print(f"[{'ok ' if live3_ok else 'FAIL'}] live pagination proof")
if not live3_ok:
    fails_total += 1


# ─────────────────────────────────────────────────────────────────────────
# 4. Budget under a simulated hang (contract section 8, item 4)
# ─────────────────────────────────────────────────────────────────────────
section("4. Budget under a simulated hang (stdlib socket, no real network)")


def _hang_forever(server_sock, stop_event):
    while not stop_event.is_set():
        try:
            server_sock.settimeout(0.5)
            conn, _ = server_sock.accept()
        except socket.timeout:
            continue
        # Accept the connection, read the client's TLS ClientHello, and then
        # hold the socket open WITHOUT closing or answering -- the client
        # blocks on its next read (waiting for ServerHello bytes that never
        # come) until ITS OWN timeout fires. Closing the socket here instead
        # would deliver an immediate SSLEOFError, which is a fast failure,
        # not the hang this test needs to prove the budget against.
        try:
            conn.settimeout(30)
            conn.recv(65536)
            while not stop_event.is_set():
                time.sleep(0.2)
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass


srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 0))
srv.listen(5)
port = srv.getsockname()[1]
stop_event = threading.Event()
t = threading.Thread(target=_hang_forever, args=(srv, stop_event), daemon=True)
t.start()

budget = harvest_ats.Budget(seconds=3)
host = f"127.0.0.1:{port}"
t0 = time.monotonic()
result = None
exc = None
try:
    result = harvest_ats.probe_successfactors(host, budget=budget)
except Exception as e:
    exc = e
elapsed = time.monotonic() - t0

stop_event.set()
srv.close()

no_exception = exc is None
within_budget = elapsed <= (budget.seconds + 1.5)  # budget + ~1s floor slack
# Budget.tripped is set BY calling .expired(), not just by time passing (see
# Budget's docstring and harvest_ats.py's "after the loops, budget.tripped is
# re-checked" convention) -- probe_successfactors made its one request and
# returned without polling the clock again once that request's own timeout
# fired, so the caller (this test, standing in for assess()) re-checks here,
# exactly as assess() does after its own walk.
tripped = budget.expired()
returned_none = result is None or result is harvest_ats.THROTTLED

print(f"budget.seconds={budget.seconds}  elapsed={elapsed:.2f}s  "
     f"result={result!r}  exception={exc!r}  budget.tripped={tripped}")
print(f"  [{'ok ' if no_exception else 'FAIL'}] no exception raised")
print(f"  [{'ok ' if within_budget else 'FAIL'}] returned within budget+~1s "
     f"({elapsed:.2f}s <= {budget.seconds + 1.5}s)")
print(f"  [{'ok ' if tripped else 'FAIL'}] budget.tripped is True")
print(f"  [{'ok ' if returned_none else 'FAIL'}] result is None/THROTTLED, not a fabricated board")

live4_ok = no_exception and within_budget and tripped and returned_none
print(f"[{'ok ' if live4_ok else 'FAIL'}] budget-under-hang proof")
if not live4_ok:
    fails_total += 1


# ─────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 78)
print(f"TOTAL FAILURES: {fails_total}")
sys.exit(1 if fails_total else 0)
