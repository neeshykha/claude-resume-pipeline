#!/usr/bin/env python3
"""Builds the job-search dashboard: one self-contained HTML page for HTML Shelf.

Usage:
    .venv/bin/python pipeline/build_dashboard.py                # Downloads + dated copy in jobs/
    .venv/bin/python pipeline/build_dashboard.py --out DIR      # write only into DIR (first runs, tests)
    .venv/bin/python pipeline/build_dashboard.py --today 2026-09-19
    .venv/bin/python pipeline/build_dashboard.py --strict       # exit 1 on failure (tests only)

Added 2026-09-19. Spec: pipeline/DASHBOARD_SPEC.md.

READ-ONLY against every tracking file. It shows state and never sets it: marking
a role applied stays with mark_applied.py, outcomes with mark_outcome.py. It
imports nothing from the writers and must stay that way. The only state the page
keeps is "I checked this site" ticks, which live in the Shelf's per-page storage
and which the pipeline never reads, so they cannot drift against anything.

Three lists, the ones where Aneesh is the bottleneck rather than the pipeline:

  queue   stage=surfaced, with a days-left countdown against age_report.py's
          45-day retirement. Default view is fresh roles by score, NOT "dies
          soonest": age_report.py's own finding is that an old surfaced row is
          usually a dead posting, so that sort leads with the least useful rows.
  manual  _blind_spot_companies + _unpollable_backlog_companies. last_checked is
          when the PIPELINE searched, not when he opened the site; the ticks
          fill that gap.
  quiet   stage=applied with outcome blank OR pending (most rows are blank, so
          reading only `pending` shows a sixth of reality), and only from the
          2026-07-28 outcome-data epoch on. Pre-epoch applied rows are
          unfalsifiable by standing decision (CLAUDE.md) and stay off the page.

jd_coverage_pct renders as a pass/fail chip at 80 and is never sortable, per the
standing rule that it is a gate and not a ranking signal.

A failed build must never fail the daily run: every failure prints one
`dashboard: FAILED ...` line, leaves yesterday's file in place, and exits 0. The
page itself shows a stale strip when a weekday run should have replaced it and
didn't (schedule-aware, so weekends don't cry wolf), because a failed build is otherwise indistinguishable from a quiet day.

This file is committed to a public repo. No company names, no sample rows.
"""
import csv
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime
from urllib.parse import quote_plus

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SCRIPT_DIR)
OUTCOMES = os.path.join(SCRIPT_DIR, "outcomes.csv")
WATCHLIST = os.path.join(SCRIPT_DIR, "watchlist_companies.json")
QUEUE = os.path.join(SCRIPT_DIR, "enrollment_candidates.json")
TAILORED = os.path.join(REPO, "tailored")
APPLY_NOW = os.path.join(TAILORED, "apply_now")
JOBS_DIR = os.path.join(SCRIPT_DIR, "jobs")
DOWNLOADS = os.path.expanduser("~/Downloads")
OUT_NAME = "job_dashboard.html"

EPOCH = date(2026, 7, 28)
COVERAGE_GATE = 80
PDF_PREFIX = "Aneesh_Khan_"
KNOWN_STAGES = {"surfaced", "applied", "rejected", "closed", "expired", "tailored", ""}
MANUAL_GROUPS = (
    # (watchlist key, label, days before a tick goes stale). The stale windows
    # match how often the pipeline itself looks: daily rotation vs monthly.
    ("_blind_spot_companies", "Blind spot", 7),
    ("_unpollable_backlog_companies", "Backlog", 30),
)

try:
    from age_report import DEFAULT_DAYS as EXPIRY_DAYS
except Exception:  # the number has one home, but a broken import can't sink the build
    EXPIRY_DAYS = 45


def parse_date(s):
    try:
        return date(*map(int, (s or "").strip().split("-")))
    except Exception:
        return None


def slug(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def to_num(s):
    try:
        return float((s or "").strip())
    except ValueError:
        return None


def tier_of(score, cfg):
    if score is None:
        return ""
    if score >= cfg.get("company_cap_threshold", 110):
        return "priority"
    if score >= cfg.get("full_tailoring_threshold", 88):
        return "full"
    if score >= cfg.get("light_tailoring_threshold", 78):
        return "light"
    return "below"


def list_pdfs():
    """[(filename slug after the name prefix, relative path, is_cover)], apply_now first."""
    found = []
    for folder in (APPLY_NOW, TAILORED):
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for n in names:
            if not n.lower().endswith(".pdf") or not n.startswith(PDF_PREFIX):
                continue
            stem = n[len(PDF_PREFIX):-4]
            cover = stem.lower().endswith("_cover")
            found.append((slug(stem[:-6] if cover else stem),
                          os.path.relpath(os.path.join(folder, n), REPO), cover,
                          folder == APPLY_NOW))
    return found


def match_pdfs(company, pdfs, notes=""):
    """Match by company slug at the start of the filename. Ambiguous is reported, never guessed."""
    keys = [slug(company)]
    first = slug((company or "").split(" ")[0])
    if len(first) >= 4 and first not in keys:
        keys.append(first)
    for key in keys:
        if not key:
            continue
        hits = [p for p in pdfs if p[0].startswith(key)]
        if not hits:
            continue
        if any(p[3] for p in hits):  # prefer what's staged in apply_now
            hits = [p for p in hits if p[3]]
        resumes = [p for p in hits if not p[2]]
        covers = [p for p in hits if p[2]]
        if len(resumes) > 1 and notes:
            # Several roles at one company: the row's own notes usually name its file.
            named = [p for p in resumes if os.path.basename(p[1]) in notes]
            if len(named) == 1:
                stem = named[0][0]
                resumes, covers = named, [c for c in covers if c[0] == stem]
        if len(resumes) > 1:
            return {"note": f"{len(resumes)} PDFs match this company", "in_apply_now": hits[0][3]}
        return {"resume": resumes[0][1] if resumes else "",
                "cover": covers[0][1] if len(covers) == 1 else "",
                "in_apply_now": hits[0][3]}
    return {"note": "no PDF matched"}


def read_outcomes(today, cfg):
    with open(OUTCOMES, newline="", encoding="utf-8") as f:
        raw = list(csv.reader(f))
    header, rows = raw[0], raw[1:]
    ci = {n: i for i, n in enumerate(header)}
    need = ("company", "title", "url", "fit_score", "stage", "outcome", "surfaced_date", "applied_date")
    missing = [n for n in need if n not in ci]
    if missing:
        raise ValueError(f"outcomes.csv is missing columns {missing}; run repair_outcomes.py")

    def col(r, name):
        return r[ci[name]].strip() if name in ci else ""

    pdfs = list_pdfs()
    queue, quiet = [], []
    counts = {"bad_rows": 0, "in_process": 0, "pre_epoch_quiet": 0, "unknown_stages": []}
    for r in rows:
        if len(r) != len(header):
            counts["bad_rows"] += 1  # mark_applied.py silently skips these too
            continue
        stage = col(r, "stage")
        score = to_num(col(r, "fit_score"))
        base = {"company": col(r, "company"), "title": col(r, "title"), "url": col(r, "url"),
                "score": score, "channel": col(r, "source_channel")}
        if stage == "surfaced":
            unmet_raw = col(r, "unmet_hard_reqs")
            unmet = to_num(unmet_raw)
            cov = to_num(col(r, "jd_coverage_pct"))
            trig = col(r, "hard_req_cap_trigger")
            item = dict(base,
                        tier=tier_of(score, cfg),
                        coverage_ok=None if cov is None else cov >= COVERAGE_GATE,
                        unmet=None if unmet_raw == "" else (int(unmet) if unmet is not None else -1),
                        unmet_text="" if unmet is not None else unmet_raw,
                        cap_trigger="" if trig in ("", "none") else trig,
                        cap_checked=trig != "",
                        ic_scope=col(r, "ic_scope").lower(),
                        surfaced=col(r, "surfaced_date") if parse_date(col(r, "surfaced_date")) else "")
            item.update(match_pdfs(item["company"], pdfs, col(r, "notes")))
            queue.append(item)
        elif stage == "applied" and col(r, "outcome") in ("", "pending"):
            sd, ad = parse_date(col(r, "surfaced_date")), parse_date(col(r, "applied_date"))
            anchor = sd or ad
            if not anchor or anchor < EPOCH:
                counts["pre_epoch_quiet"] += 1
                continue
            sent = ad or sd  # some applied rows carry no applied_date
            quiet.append(dict(base, applied=sent.isoformat(), applied_is_exact=bool(ad),
                              furthest_stage=col(r, "furthest_stage")))
        elif stage not in KNOWN_STAGES:
            counts["in_process"] += 1
            if stage not in counts["unknown_stages"]:
                counts["unknown_stages"].append(stage)
    return queue, quiet, counts


def read_manual(watch):
    out = []
    for key, label, stale_days in MANUAL_GROUPS:
        block = watch.get(key) or {}
        entries = block.get("companies", []) if isinstance(block, dict) else block
        for e in entries:
            if not isinstance(e, dict) or not e.get("name"):
                continue
            query = e.get("query", "")
            url = (e.get("careers_url") or "").strip()
            if url:
                link, kind = url, "careers"
            elif query:
                link, kind = "https://www.google.com/search?q=" + quote_plus(query), "search"
            else:
                link, kind = "", ""
            checked = e.get("last_checked") or ""
            hit = e.get("last_hit") or ""
            # Crude on purpose: it only drives a highlight, and the full text is on the row.
            live = bool(checked and hit.startswith(checked)
                        and not re.search(r"\b(no|null|none|nothing)\b", hit[:90], re.I))
            out.append({"key": slug(e["name"]), "name": e["name"], "group": label,
                        "stale_days": stale_days, "why": e.get("why", ""), "link": link,
                        "link_kind": kind, "last_checked": checked, "last_hit": hit,
                        "hit_is_live": live})
    return out


def read_backlog_counts():
    try:
        with open(QUEUE, encoding="utf-8") as f:
            q = json.load(f)
    except Exception:
        return {}
    entries = [e for b in ("pending", "enrolled", "rejected") for e in q.get(b, []) if isinstance(e, dict)]
    return {"manual_review_unsurfaced": sum(1 for e in entries
                                            if e.get("manual_review") and not e.get("manual_review_surfaced")),
            "unpollable_unreported": sum(1 for e in entries
                                         if e.get("unpollable") and not e.get("weekly_report_surfaced"))}


def build_data(today, now):
    with open(WATCHLIST, encoding="utf-8") as f:
        watch = json.load(f)
    queue, quiet, counts = read_outcomes(today, watch.get("_scoring_config", {}))
    counts.update(read_backlog_counts())
    return {"generated": now.strftime("%Y-%m-%dT%H:%M"), "expiry_days": EXPIRY_DAYS,
            "fresh_days": 14, "expiring_days": 7, "quiet_days": 10,
            # The task runs `0 3 * * 1-5`; by 8 AM a weekday's page should exist. JS weekday numbers.
            "run_weekdays": [1, 2, 3, 4, 5], "run_ready_hour": 8,
            "queue": queue, "quiet": quiet, "manual": read_manual(watch), "counts": counts}


def render(data):
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\u0021--")
    return PAGE.replace("/*__DATA__*/", blob)


def write_atomic(path, text):
    # The temp name must not end in .html, or the Shelf's Downloads scan could import it.
    fd, tmp = tempfile.mkstemp(prefix=".job_dashboard.", suffix=".tmp", dir=os.path.dirname(path))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def summary(data, today):
    def left(i):
        d = parse_date(i["surfaced"])
        return None if not d else data["expiry_days"] - (today - d).days
    expiring = sum(1 for i in data["queue"] if left(i) is not None and left(i) <= data["expiring_days"])
    return (f"{len(data['queue'])} queue ({expiring} expiring), "
            f"{len(data['manual'])} manual, {len(data['quiet'])} quiet")


def main(argv):
    strict = "--strict" in argv
    try:
        today = parse_date(argv[argv.index("--today") + 1]) if "--today" in argv else date.today()
        if today is None:
            raise ValueError("--today needs YYYY-MM-DD")
        now = datetime.now() if "--today" not in argv else datetime(today.year, today.month, today.day, 7, 0)
        data = build_data(today, now)
        html = render(data)
        if "--out" in argv:
            targets = [os.path.join(argv[argv.index("--out") + 1], OUT_NAME)]
        else:
            targets = [os.path.join(DOWNLOADS, OUT_NAME),
                       os.path.join(JOBS_DIR, f"dashboard_{today.isoformat()}.html")]
        for t in targets:
            os.makedirs(os.path.dirname(t), exist_ok=True)
            write_atomic(t, html)
        print(f"dashboard: {summary(data, today)} -> {targets[0]}")
        return 0
    except Exception as e:  # noqa: BLE001 - a dashboard failure must never fail the run
        print(f"dashboard: FAILED {type(e).__name__}: {e}")
        return 1 if strict else 0


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job Search Dashboard</title>
<style>
:root{--bg:#f6f5f1;--card:#fff;--ink:#1d1f23;--mute:#6b7078;--line:#e3e1da;--accent:#3d4fc4;
--good:#1f7a4d;--warn:#b26a00;--bad:#b3261e;--goodbg:#e6f3ec;--warnbg:#fbf0dc;--badbg:#fae6e4;--chip:#eeece6}
@media (prefers-color-scheme:dark){:root{--bg:#15171b;--card:#1e2126;--ink:#e8e6e1;--mute:#9a9ea6;--line:#2e3239;
--accent:#8f9cf5;--good:#6fcf9b;--warn:#e7b25c;--bad:#f08b83;--goodbg:#1b3328;--warnbg:#3a2e17;--badbg:#3d2220;--chip:#2a2e35}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1080px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:22px;margin:0}
h2{font-size:16px;margin:32px 0 4px}
.sub{color:var(--mute);font-size:13px}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-variant-numeric:tabular-nums}
.strip{margin:12px 0;padding:10px 12px;border-radius:8px;font-size:14px}
.strip.bad{background:var(--badbg);color:var(--bad)}.strip.warn{background:var(--warnbg);color:var(--warn)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0 6px}
.tile{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--mute);border-radius:10px;
padding:12px;text-align:left;color:inherit;font:inherit;cursor:pointer}
.tile b{display:block;font-size:26px;line-height:1.1}
.tile span{font-size:13px;color:var(--mute)}
.tile.good{border-left-color:var(--good)}.tile.warn{border-left-color:var(--warn)}.tile.bad{border-left-color:var(--bad)}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.chipbtn{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;padding:5px 12px;
font:inherit;font-size:13px;cursor:pointer}
.chipbtn[aria-pressed=true]{background:var(--accent);border-color:var(--accent);color:#fff}
.list{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.row{display:flex;gap:12px;align-items:flex-start;padding:10px 12px;border-top:1px solid var(--line)}
.row:first-child{border-top:0}
.row.dim{opacity:.55}
.body{flex:1;min-width:0}
.top{display:flex;flex-wrap:wrap;gap:4px 10px;align-items:baseline}
.co{font-weight:600}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.meta{display:flex;flex-wrap:wrap;gap:5px;margin-top:5px;font-size:12.5px;color:var(--mute);align-items:center}
.tag{background:var(--chip);border-radius:5px;padding:1px 7px;white-space:nowrap}
.tag.good{background:var(--goodbg);color:var(--good)}.tag.warn{background:var(--warnbg);color:var(--warn)}
.tag.bad{background:var(--badbg);color:var(--bad)}
.right{text-align:right;white-space:nowrap;min-width:84px}
.right b{display:block;font-size:15px}
.right small{color:var(--mute);font-size:12px}
.path{cursor:pointer;border-bottom:1px dotted var(--mute)}
.why{font-size:13px;color:var(--mute);margin-top:3px}
.hit{font-size:13px;margin-top:3px}
.hit.live{color:var(--good)}
input[type=checkbox]{width:20px;height:20px;margin-top:2px;accent-color:var(--accent);flex:none}
.group{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute);padding:10px 12px 4px;
background:var(--bg);border-top:1px solid var(--line)}
.empty{padding:18px 12px;color:var(--mute)}
footer{margin-top:34px;font-size:13px;color:var(--mute)}
footer li{margin:3px 0}
</style>
</head>
<body>
<main>
<h1>Job Search Dashboard</h1>
<div class="sub" id="stamp"></div>
<div id="strips"></div>
<div class="tiles" id="tiles"></div>

<h2 id="h-queue">Apply queue</h2>
<div class="sub">Tailored, not confirmed sent. Rows retire at <span id="exp"></span> days. Marking a role applied still happens through the confirmation email, not here.</div>
<div class="chips" id="qchips"></div>
<div class="list" id="queue"></div>

<h2 id="h-manual">Manual checks</h2>
<div class="sub">Career sites the pipeline can't read. Tick one when you've looked; ticks are yours and the pipeline never sees them.</div>
<div class="list" id="manual"></div>

<h2 id="h-quiet">Gone quiet</h2>
<div class="sub">Applied, nothing recorded since. Only applications from Jul 28 on, where a send can be confirmed.</div>
<div class="chips" id="zchips"></div>
<div class="list" id="quiet"></div>

<footer><b>Not on this page</b><ul id="foot"></ul></footer>
</main>
<script id="data" type="application/json">/*__DATA__*/</script>
<script>
(function(){
var D=JSON.parse(document.getElementById('data').textContent);
var DAY=86400000, KEY='jobdash.ticks.v1';
function el(id){return document.getElementById(id)}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function day(s){var p=String(s||'').slice(0,10).split('-');return p.length===3?new Date(+p[0],+p[1]-1,+p[2]):null}
var now=new Date(), today=new Date(now.getFullYear(),now.getMonth(),now.getDate());
function since(s){var d=day(s);return d?Math.round((today-d)/DAY):null}
function iso(d){return d.getFullYear()+'-'+('0'+(d.getMonth()+1)).slice(-2)+'-'+('0'+d.getDate()).slice(-2)}
function ago(n){if(n==null)return'';if(n<=0)return'today';if(n===1)return'yesterday';if(n<14)return n+' days ago';if(n<60)return Math.round(n/7)+' wks ago';return Math.round(n/30)+' mos ago'}
function nice(s){var d=day(s);return d?d.toLocaleDateString(undefined,{month:'short',day:'numeric'}):''}
function safeUrl(u){return /^https?:\/\//i.test(u||'')?u:''}

// Ticks. Storage can throw (private window, blocked site data); the page still works without it.
var ticks={}, storageOK=true;
try{ticks=JSON.parse(localStorage.getItem(KEY)||'{}')||{}}catch(e){storageOK=false}
function saveTicks(){try{localStorage.setItem(KEY,JSON.stringify(ticks))}catch(e){storageOK=false;strips()}}
(function prune(){var live={},changed=false;D.manual.forEach(function(m){live[m.key]=1});
  Object.keys(ticks).forEach(function(k){if(!live[k]){delete ticks[k];changed=true}});if(changed)saveTicks()})();

D.queue.forEach(function(q){q.age=since(q.surfaced);q.left=q.age==null?null:D.expiry_days-q.age});
D.quiet.forEach(function(z){z.days=since(z.applied)});
function tickState(m){var t=ticks[m.key],n=t?since(t):null;
  var stale=n!=null&&n>m.stale_days, newer=t&&m.hit_is_live&&m.last_checked>t;
  return {date:t,days:n,due:!t||stale||newer,stale:stale,newer:newer}}

var qFilter='fresh', zFilter='old';
var QF={fresh:['Fresh',function(q){return q.age!=null&&q.age<=D.fresh_days}],
  expiring:['Expiring',function(q){return q.left!=null&&q.left<=D.expiring_days}],
  full:['Full tier',function(q){return q.tier==='full'||q.tier==='priority'}],
  all:['All',function(){return true}]};
var ZF={old:[D.quiet_days+'+ days',function(z){return z.days!=null&&z.days>=D.quiet_days}],all:['All',function(){return true}]};

function strips(){var h='';
  // Stale = a scheduled run should have rebuilt this page since it was generated. The run is
  // weekdays only, so a flat hour count would cry wolf every weekend.
  var gen=new Date(D.generated), due=new Date(now.getFullYear(),now.getMonth(),now.getDate(),D.run_ready_hour);
  for(var i=0;i<8&&(due>now||D.run_weekdays.indexOf(due.getDay())<0);i++)due=new Date(due.getTime()-DAY);
  var dueDay=new Date(due.getFullYear(),due.getMonth(),due.getDate());
  if(gen<dueDay)h+='<div class="strip bad">This page is from '+esc(nice(D.generated))+' and the '+esc(due.toLocaleDateString(undefined,{weekday:'long'}))+' run should have replaced it. The daily build may have failed.</div>';
  if(D.counts.bad_rows)h+='<div class="strip warn">'+D.counts.bad_rows+' tracker rows are unreadable (column drift) and are missing from every list. Run repair_outcomes.py.</div>';
  if(!storageOK)h+='<div class="strip warn">Storage is unavailable here, so ticks last only until this page closes.</div>';
  el('strips').innerHTML=h}

function tiles(){
  var fresh=D.queue.filter(QF.fresh[1]).length, exp=D.queue.filter(QF.expiring[1]).length;
  var due=D.manual.filter(function(m){return tickState(m).due}).length, old=D.quiet.filter(ZF.old[1]).length;
  var t=[['good',fresh,'ready to apply, '+D.fresh_days+' days or newer','queue','fresh'],
    [exp?'warn':'',exp,'expiring within '+D.expiring_days+' days','queue','expiring'],
    [due?'bad':'good',due,'manual checks due','manual',null],
    ['',old,'applied and quiet '+D.quiet_days+'+ days'+(D.counts.in_process?' ('+D.counts.in_process+' in process)':''),'quiet','old']];
  el('tiles').innerHTML=t.map(function(x,i){return '<button class="tile '+x[0]+'" data-i="'+i+'"><b class="mono">'+x[1]+'</b><span>'+esc(x[2])+'</span></button>'}).join('');
  Array.prototype.forEach.call(el('tiles').children,function(b,i){b.onclick=function(){
    if(t[i][3]==='queue'){qFilter=t[i][4];queue()} if(t[i][3]==='quiet'){zFilter=t[i][4];quiet()}
    el('h-'+t[i][3]).scrollIntoView({behavior:'smooth'})}})}

function chips(id,defs,cur,set){el(id).innerHTML=Object.keys(defs).map(function(k){
  return '<button class="chipbtn" aria-pressed="'+(k===cur)+'" data-k="'+k+'">'+esc(defs[k][0])+'</button>'}).join('');
  Array.prototype.forEach.call(el(id).children,function(b){b.onclick=function(){set(b.getAttribute('data-k'))}})}

function titleLink(x){var u=safeUrl(x.url);return u?'<a href="'+esc(u)+'" target="_blank" rel="noopener">'+esc(x.title)+'</a>':esc(x.title)}
function pathTag(label,p){return p?'<span class="tag path mono" data-copy="'+esc(p)+'" title="'+esc(p)+' (click to copy the path)">'+label+' PDF</span>':''}

function queue(){
  chips('qchips',QF,qFilter,function(k){qFilter=k;queue()});
  var rows=D.queue.filter(QF[qFilter][1]).slice();
  rows.sort(qFilter==='expiring'?function(a,b){return a.left-b.left}:function(a,b){
    if((a.age==null)!==(b.age==null))return a.age==null?1:-1; return (b.score||0)-(a.score||0)});
  el('queue').innerHTML=rows.length?rows.map(function(q){
    var m=[];
    if(q.tier)m.push('<span class="tag">'+esc(q.tier)+'</span>');
    if(q.unmet!=null)m.push('<span class="tag '+(q.unmet===0?'good':q.unmet>=2||q.unmet<0?'warn':'')+'" title="'+esc(q.unmet_text)+'">'+(q.unmet<0?'unmet: see note':q.unmet+' unmet hard req'+(q.unmet===1?'':'s'))+'</span>');
    if(q.cap_trigger)m.push('<span class="tag bad" title="'+esc(q.cap_trigger)+'">hard-req cap</span>');
    if(q.coverage_ok!=null)m.push('<span class="tag '+(q.coverage_ok?'':'warn')+'">ATS gate '+(q.coverage_ok?'pass':'below 80')+'</span>');
    if(q.ic_scope)m.push('<span class="tag">'+esc(q.ic_scope==='ic'?'IC':q.ic_scope)+'</span>');
    if(q.channel&&q.channel!=='pipeline')m.push('<span class="tag">'+esc(q.channel.replace('_',' '))+'</span>');
    m.push(pathTag('resume',q.resume)); m.push(pathTag('cover',q.cover));
    if(q.note)m.push('<span>'+esc(q.note)+'</span>');
    var left=q.left==null?'<b>no date</b><small>never retires</small>':
      '<b class="mono" style="color:var(--'+(q.left<=D.expiring_days?'bad':q.left<=21?'warn':'ink')+')">'+Math.max(q.left,0)+'d left</b><small>surfaced '+esc(ago(q.age))+'<br>'+esc(nice(q.surfaced))+'</small>';
    return '<div class="row"><div class="right mono" style="min-width:42px;text-align:left"><b>'+(q.score==null?'':Math.round(q.score))+'</b></div><div class="body"><div class="top"><span class="co">'+esc(q.company)+'</span><span>'+titleLink(q)+'</span></div><div class="meta">'+m.join('')+'</div></div><div class="right">'+left+'</div></div>'
  }).join(''):'<div class="empty">Nothing in this view.</div>';
  Array.prototype.forEach.call(el('queue').querySelectorAll('[data-copy]'),function(s){s.onclick=function(){
    var p=s.getAttribute('data-copy'),old=s.textContent;
    try{navigator.clipboard.writeText(p).then(function(){s.textContent='copied';setTimeout(function(){s.textContent=old},900)})}catch(e){window.prompt('Path',p)}}})}

function manual(){
  var groups={},order=[];
  D.manual.forEach(function(m){if(!groups[m.group]){groups[m.group]=[];order.push(m.group)}groups[m.group].push(m)});
  var h='';
  order.forEach(function(g){
    var rows=groups[g].slice().sort(function(a,b){var A=tickState(a),B=tickState(b);
      if(A.due!==B.due)return A.due?-1:1; return (A.date||'')<(B.date||'')?-1:1});
    h+='<div class="group">'+esc(g)+' · '+rows.filter(function(m){return tickState(m).due}).length+' due of '+rows.length+'</div>';
    rows.forEach(function(m){var s=tickState(m),u=safeUrl(m.link);
      var mine=!s.date?'not checked yet':(s.newer?'pipeline found something after your last look · ':s.stale?'stale · ':'')+'you checked '+ago(s.days);
      h+='<div class="row'+(s.due?'':' dim')+'"><input type="checkbox" data-k="'+esc(m.key)+'"'+(s.date&&!s.stale&&!s.newer?' checked':'')+' aria-label="Checked '+esc(m.name)+'"><div class="body"><div class="top"><span class="co">'+(u?'<a href="'+esc(u)+'" target="_blank" rel="noopener">'+esc(m.name)+'</a>':esc(m.name))+'</span>'+(m.link_kind==='search'?'<span class="tag">search link</span>':'')+'</div><div class="why">'+esc(m.why)+'</div>'+(m.last_hit?'<div class="hit'+(m.hit_is_live?' live':'')+'">Pipeline: '+esc(m.last_hit)+'</div>':'')+'</div><div class="right"><small>'+esc(mine)+(s.date?'<br>'+esc(nice(s.date)):'')+'</small></div></div>'})});
  el('manual').innerHTML=h||'<div class="empty">No manual-check companies in the watchlist.</div>';
  Array.prototype.forEach.call(el('manual').querySelectorAll('input'),function(c){c.onchange=function(){
    var k=c.getAttribute('data-k'); if(c.checked)ticks[k]=iso(today); else delete ticks[k];
    saveTicks(); manual(); tiles()}})}

function quiet(){
  chips('zchips',ZF,zFilter,function(k){zFilter=k;quiet()});
  var rows=D.quiet.filter(ZF[zFilter][1]).slice().sort(function(a,b){return (b.days||0)-(a.days||0)});
  el('quiet').innerHTML=rows.length?rows.map(function(z){var m=[];
    if(z.furthest_stage&&z.furthest_stage!=='applied')m.push('<span class="tag good">reached '+esc(z.furthest_stage)+'</span>');
    if(z.channel&&z.channel!=='pipeline')m.push('<span class="tag">'+esc(z.channel.replace('_',' '))+'</span>');
    if(!z.applied_is_exact)m.push('<span>send date not recorded; counting from surfaced</span>');
    return '<div class="row"><div class="body"><div class="top"><span class="co">'+esc(z.company)+'</span><span>'+titleLink(z)+'</span></div><div class="meta">'+m.join('')+'</div></div><div class="right"><b class="mono">'+z.days+'d</b><small>applied '+esc(nice(z.applied))+'</small></div></div>'
  }).join(''):'<div class="empty">Nothing in this view.</div>'}

function foot(){var c=D.counts,f=[];
  if(c.pre_epoch_quiet)f.push(c.pre_epoch_quiet+' applied rows from before Jul 28, where a send was never confirmable.');
  if(c.manual_review_unsurfaced)f.push(c.manual_review_unsurfaced+' discovery-queue companies flagged for manual review. They arrive through the digest a few at a time.');
  if(c.unpollable_unreported)f.push(c.unpollable_unreported+' unpollable companies waiting their turn in the weekly report.');
  if(c.in_process)f.push(c.in_process+' rows with an in-process stage ('+esc((c.unknown_stages||[]).join(', '))+'). Interviews get their own section in phase two.');
  el('foot').innerHTML=f.map(function(x){return '<li>'+x+'</li>'}).join('')}

el('stamp').textContent='Generated '+new Date(D.generated).toLocaleString(undefined,{weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
el('exp').textContent=D.expiry_days;
strips();tiles();queue();manual();quiet();foot();
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
