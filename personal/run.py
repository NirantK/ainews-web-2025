#!/usr/bin/env python3
"""Build a private, reviewable HTML edition from the fork's X collector."""

import argparse
import datetime as dt
import html
import json
import math
import sys
import re
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
RUNS = ROOT / "tools" / "scrapers" / "runs"
OUT = HERE / "output"
EDITORIAL = HERE / "editorial"
ACCOUNTS = HERE / "x_accounts.json"
UPSTREAM_LIST = "list:1585430245762441216"

KEYWORDS = {
    "launch": 5, "released": 5, "introducing": 5, "open weights": 5,
    "paper": 4, "benchmark": 4, "training": 4, "inference": 4,
    "model": 3, "agent": 3, "eval": 4, "kernel": 4,
    "latency": 4, "throughput": 4, "reasoning": 3, "rl": 3,
    "token": 3, "coding": 2, "gpu": 3, "robot": 3,
    "jev": 5, "clm": 5, "laya": 4,
}
LOW_SIGNAL = re.compile(r"\b(fomo|vibe|hot take|drama|doom|hype|insane)\b", re.I)
NO_NEWS = re.compile(r"^(i'm getting ready|the top ai papers|it's not a fad|against his better judgment|would be cool if|this is a bigger deal|ok i think i finally figured out)", re.I)


def score(tweet):
    text = tweet.get("text", "")
    if len(text) < 75 or text.lstrip().startswith("RT ") or NO_NEWS.search(text.strip()):
        return -1
    lower = text.lower()
    matches = [weight for word, weight in KEYWORDS.items() if re.search(r"\b" + re.escape(word) + r"\b", lower)]
    if len(matches) < 2:
        return -1
    stats = tweet.get("stats") or {}
    engagement = (stats.get("likes") or 0) + 3 * (stats.get("retweets") or 0) + (stats.get("replies") or 0)
    return sum(matches) + math.log1p(engagement) - (5 if LOW_SIGNAL.search(text) else 0)


def x_url(tweet):
    user = tweet.get("user") or {}
    handle = (user.get("username") or "").lstrip("@")
    return f"https://x.com/{handle}/status/{tweet['id']}"


def latest_run():
    candidates = []
    for raw in RUNS.glob("*/twitter/raw.json"):
        try:
            data = json.loads(raw.read_text())
            if (data.get("tweets") and data.get("diagnostics", {}).get("listId") == UPSTREAM_LIST
                    and not data.get("diagnostics", {}).get("wasPartial")):
                candidates.append((raw.stat().st_mtime, raw, data))
        except (OSError, json.JSONDecodeError):
            continue
    if not candidates:
        raise SystemExit("No complete X collection exists. Run the fork's collector first.")
    return max(candidates)


def accounts():
    return json.loads(ACCOUNTS.read_text())


def collect():
    end = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    start = end - dt.timedelta(days=1)
    window = ["--start", start.isoformat().replace("+00:00", "Z"),
              "--end", end.isoformat().replace("+00:00", "Z")]
    errors = []
    for target in ["1585430245762441216", *("@" + a["handle"] for a in accounts())]:
        try:
            subprocess.run(["node", "--import", "tsx", "cli.ts", "run", "twitter",
                            "--target", target, *window, "--scrape-only"],
                           cwd=ROOT / "tools" / "scrapers", check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"{target}: {exc}")
    return errors


def merge_accounts(data):
    diagnostics = data["diagnostics"]
    window = (diagnostics.get("startParam"), diagnostics.get("endParam"))
    by_id = {str(tweet["id"]): tweet for tweet in data["tweets"]}
    counts, missing = {}, []
    for account in accounts():
        handle = account["handle"]
        matches = []
        for raw in RUNS.glob("*/twitter/raw.json"):
            try:
                candidate = json.loads(raw.read_text())
                diag = candidate["diagnostics"]
                if (diag.get("listId") == f"profile:{handle}"
                        and (diag.get("startParam"), diag.get("endParam")) == window
                        and not diag.get("wasPartial")):
                    matches.append((raw.stat().st_mtime, candidate))
            except (OSError, KeyError, json.JSONDecodeError):
                continue
        if not matches:
            missing.append("@" + handle)
            continue
        profile = max(matches, key=lambda entry: entry[0])[1]
        counts[handle] = len(profile["tweets"])
        for tweet in profile["tweets"]:
            by_id.setdefault(str(tweet["id"]), tweet)
    merged = {**data, "tweets": list(by_id.values()),
              "diagnostics": {**diagnostics, "profileCounts": counts, "missingProfiles": missing}}
    return merged


def make_items(tweets, date):
    by_id = {str(t["id"]): t for t in tweets}
    edited = EDITORIAL / f"{date}.json"
    items = []
    used = set()
    suppress_terms = []
    if edited.exists():
        for entry in json.loads(edited.read_text()):
            sources = [by_id[str(i)] for i in entry["tweet_ids"] if str(i) in by_id]
            if not sources and not entry.get("extra_sources"):
                continue
            used.update(str(t["id"]) for t in sources)
            suppress_terms.extend(entry.get("suppress_terms", []))
            items.append({
                "id": entry["id"], "title": entry["title"],
                "summary": entry["summary"], "why": entry["why"],
                "broken": entry.get("broken"), "fix": entry.get("fix"),
                "evidence": entry.get("evidence"),
                "topic": entry.get("topic", "Engineering"),
                "sources": [x_url(t) for t in sources] + entry.get("extra_sources", []), "editorial": True,
            })
    ranked = sorted((t for t in tweets if str(t["id"]) not in used and not any(term.lower() in t.get("text", "").lower() for term in suppress_terms)), key=score, reverse=True)
    for t in ranked:
        if len(items) >= 11:
            break
        if score(t) < 12:
            break
        text = " ".join(t["text"].split())
        items.append({
            "id": "x-" + str(t["id"]),
            "title": text[:105].rsplit(" ", 1)[0] + ("…" if len(text) > 105 else ""),
            "summary": text[:360] + ("…" if len(text) > 360 else ""),
            "why": "Candidate from the monitored X list; needs your judgment and source verification.",
            "broken": {"text": "The underlying engineering problem needs source verification.", "url": x_url(t), "label": "original post"},
            "fix": {"text": text[:360] + ("…" if len(text) > 360 else ""), "url": x_url(t), "label": "claim"},
            "evidence": {"text": "No independent result has been checked for this candidate.", "url": x_url(t), "label": "original post"},
            "topic": "Scanner candidate",
            "sources": [x_url(t)], "editorial": False,
        })
    return items


def render(date, data, raw_path, items, collection_error, live_server):
    diag = data.get("diagnostics", {})
    start = diag.get("startParam", "unknown")
    end = diag.get("endParam", "unknown")
    profiles = diag.get("profileCounts", {})
    additions = " · " + ", ".join(f"@{html.escape(k)}: {v}" for k, v in profiles.items()) if profiles else ""
    coverage = f"{len(data['tweets'])} X posts · {diag.get('pagesFetched', '?')} list pages{additions} · {html.escape(start)} to {html.escape(end)}"
    if diag.get("missingProfiles"):
        missing = ", ".join(html.escape(handle) for handle in diag["missingProfiles"])
        coverage += f" · Profile scan unavailable: {missing}"
    warning = "" if not collection_error else f'<p class="warning">New collection failed: {html.escape(collection_error)}. This edition uses the last complete saved run.</p>'
    cards = []
    def claim(label, content, fallback_url):
        content = content or {"text": "Not established yet.", "url": fallback_url, "label": "original post"}
        url = content.get("url") or fallback_url
        if not url.startswith("https://"):
            raise ValueError(f"Claim source must be an HTTPS URL: {url}")
        source_label = content.get("label") or "source"
        related = ""
        for source in content.get("related", []):
            related_url = source["url"]
            if not related_url.startswith("https://"):
                raise ValueError(f"Claim source must be an HTTPS URL: {related_url}")
            related += (f' <a class="inline-source" href="{html.escape(related_url, quote=True)}" '
                        f'target="_blank" rel="noopener noreferrer">{html.escape(source["label"])} ↗</a>')
        return (f'<div class="claim"><div class="claim-label">{html.escape(label)}</div>'
                f'<p>{html.escape(content["text"])} '
                f'<a class="inline-source" href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">'
                f'{html.escape(source_label)} ↗</a>{related}</p></div>')
    for i, item in enumerate(items, 1):
        badge = item["topic"] + (" · Edited selection" if item["editorial"] else "")
        fallback_url = item["sources"][0]
        cards.append(f'''<article class="card" data-id="{html.escape(item['id'])}">
          <div class="eyebrow">{i:02d} · {badge}</div>
          <h2>{html.escape(item['title'])}</h2>
          <div class="claims">{claim('What was broken', item.get('broken'), fallback_url)}
          {claim('What changed', item.get('fix'), fallback_url)}
          {claim('Evidence and limits', item.get('evidence'), fallback_url)}</div>
          <p class="why"><strong>Why it may matter</strong> · {html.escape(item['why'])}</p>
          <div class="vote" role="group" aria-label="Review {html.escape(item['title'])}">
            <button data-vote="post">Good to post</button><button data-vote="watch">Watch</button><button data-vote="skip">Skip</button>
          </div>
          <label>Reason or angle <input class="reason" placeholder="What makes this useful or weak?" /></label>
        </article>''')
    payload = json.dumps({"date": date, "items": items}, ensure_ascii=False).replace("</", "<\\/")
    redirect = (f'''<script>if(location.protocol==='file:'){{let prior='';try{{prior=localStorage.getItem('ai-engineering-review:{date}')||''}}catch(e){{}}location.replace('http://127.0.0.1:8765/{date}.html'+(prior?'#migrate='+encodeURIComponent(prior):''))}}</script>''' if live_server else "")
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">{redirect}
    <title>AI Engineering · {date}</title><style>
    :root{{--ink:#13252b;--muted:#557079;--line:#cddcdb;--paper:#f5f8f6;--accent:#087a66}}
    *{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 system-ui,-apple-system,sans-serif}}
    main{{max-width:930px;margin:auto;padding:42px 22px 100px}}header{{border-bottom:2px solid var(--ink);padding-bottom:28px}}
    .eyebrow{{text-transform:uppercase;letter-spacing:.12em;font-size:12px;font-weight:750;color:var(--accent)}}h1{{font-size:clamp(42px,7vw,76px);line-height:1.02;letter-spacing:-.055em;margin:14px 0}}
    h2{{font-size:25px;line-height:1.2;letter-spacing:-.025em;margin:8px 0 12px}}.dek{{font-size:19px;max-width:680px}}
    .meta,.note{{color:var(--muted);font-size:14px}}.warning{{background:#fff2d6;padding:14px;border-radius:7px}}.card{{background:white;border:1px solid var(--line);border-radius:12px;margin:18px 0;padding:24px;box-shadow:0 3px 14px #13252b08}}
    .claims{{border-top:1px solid var(--line);margin-top:17px}}.claim{{display:grid;grid-template-columns:145px 1fr;gap:17px;border-bottom:1px solid var(--line);padding:11px 0}}.claim p{{margin:0}}.claim-label{{font-size:12px;text-transform:uppercase;letter-spacing:.08em;font-weight:750;color:var(--muted);padding-top:4px}}
    .why{{background:#eff7f3;padding:12px 15px;border-left:3px solid var(--accent)}}a{{color:#075f79}}.inline-source{{font-size:13px;font-weight:700;white-space:nowrap;margin-left:4px}}.vote{{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0 12px}}
    @media(max-width:600px){{.claim{{grid-template-columns:1fr;gap:3px}}}}
    button{{border:1px solid #a7c6c0;background:white;border-radius:7px;padding:9px 13px;cursor:pointer;font-weight:650;color:var(--ink)}}button:hover,button.selected{{background:var(--accent);color:white;border-color:var(--accent)}}
    label{{display:block;font-size:13px;color:var(--muted)}}input{{display:block;width:100%;margin-top:5px;padding:10px;border:1px solid var(--line);border-radius:6px;font:inherit}}.actions{{position:sticky;bottom:0;background:#f5f8f6eb;padding:13px 0;border-top:1px solid var(--line);display:flex;gap:10px;align-items:center;flex-wrap:wrap}}.actions button{{background:var(--ink);color:white}}
    </style></head><body><main><header><div class="eyebrow">Private morning review · {date}</div><h1>AI Engineering</h1>
    <p class="dek">Technically interesting launches, methods, and shifts from the AINews monitored list. Mark what belongs on your channel; nothing here is posted automatically.</p>
    <div class="meta">{coverage}</div>{warning}</header>
    <p class="note">This edition combines the fork’s X scan with selected primary research and release posts. Reddit still needs a session. Sources sit beside the claims they support.</p>
    {''.join(cards)}<div class="actions"><button id="copy">Copy review for chat</button><button id="download">Download taste dataset</button><span id="count" class="meta"></span><span id="save-status" class="meta">Loading saved feedback…</span></div>
    <script id="edition" type="application/json">{payload}</script><script>
    const edition=JSON.parse(document.getElementById('edition').textContent);const key='ai-engineering-review:'+edition.date;
    const state={{}},timers={{}},pending=JSON.parse(localStorage.getItem(key+':pending')||'{{}}');let queue=Promise.resolve();const status=document.getElementById('save-status');
    function count(){{let n=Object.values(state).filter(v=>v.vote).length;document.getElementById('count').textContent=n+'/'+edition.items.length+' classified'}}
    function render(){{document.querySelectorAll('.card').forEach(card=>{{let id=card.dataset.id,v=state[id]||{{}};card.querySelectorAll('[data-vote]').forEach(b=>b.classList.toggle('selected',b.dataset.vote===v.vote));card.querySelector('.reason').value=v.reason||''}});count()}}
    function stage(id){{pending[id]={{...(state[id]||{{}})}};localStorage.setItem(key+':pending',JSON.stringify(pending));status.textContent='Saving…'}}
    function persist(id){{stage(id);const value={{...pending[id]}};queue=queue.catch(()=>{{}}).then(async()=>{{const r=await fetch('/api/feedback',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{date:edition.date,id,...value}})}});if(!r.ok)throw Error('Save failed: '+r.status);if(JSON.stringify(pending[id])===JSON.stringify(value)){{delete pending[id];localStorage.setItem(key+':pending',JSON.stringify(pending))}}status.textContent=Object.keys(pending).length?'Saving…':'Saved automatically'}}).catch(e=>{{status.textContent='Saved in this browser; local file sync failed — '+e.message;throw e}})}}
    document.querySelectorAll('.card').forEach(card=>{{let id=card.dataset.id;card.querySelectorAll('[data-vote]').forEach(b=>b.onclick=()=>{{state[id]={{...(state[id]||{{}}),vote:b.dataset.vote}};render();persist(id)}});card.querySelector('.reason').oninput=e=>{{state[id]={{...(state[id]||{{}}),reason:e.target.value}};stage(id);clearTimeout(timers[id]);timers[id]=setTimeout(()=>persist(id),450)}}}});
    async function loadSaved(){{try{{const r=await fetch('/api/feedback?date='+edition.date,{{cache:'no-store'}});if(!r.ok)throw Error('Could not read saved feedback');const data=await r.json();for(const d of data.decisions||[])state[d.id]={{vote:d.vote,reason:d.reason||''}};for(const [id,v] of Object.entries(pending)){{state[id]=v;persist(id)}}if(location.hash.startsWith('#migrate=')){{try{{const prior=JSON.parse(decodeURIComponent(location.hash.slice(9)));for(const [id,v] of Object.entries(prior)){{if(!state[id]&&(v.vote||v.reason)){{state[id]=v;persist(id)}}}}history.replaceState(null,'',location.pathname)}}catch(e){{}}}}render();if(!Object.keys(pending).length)status.textContent='Saved feedback loaded'}}catch(e){{for(const [id,v] of Object.entries(pending))state[id]=v;render();status.textContent='Saved in this browser; local file unavailable — '+e.message}}}}
    const exportData=()=>({{date:edition.date,decisions:edition.items.filter(i=>state[i.id]?.vote).map(i=>({{id:i.id,title:i.title,vote:state[i.id].vote,reason:state[i.id].reason||'',sources:i.sources}}))}});
    document.getElementById('copy').onclick=async()=>{{const d=exportData();await navigator.clipboard.writeText(JSON.stringify(d,null,2));document.getElementById('count').textContent='Copied '+d.decisions.length+' decisions. Paste them in chat.'}};
    document.getElementById('download').onclick=()=>{{const blob=new Blob([JSON.stringify(exportData(),null,2)],{{type:'application/json'}});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='ai-engineering-review-'+edition.date+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}};loadSaved();
    </script></main></body></html>'''


def ensure_server():
    url = "http://127.0.0.1:8765/api/health"
    try:
        with urlopen(url, timeout=0.5) as response:
            return response.status == 200
    except OSError:
        pass
    log = (OUT / "review-server.log").open("ab")
    subprocess.Popen([sys.executable, str(HERE / "server.py")], cwd=ROOT,
                     stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    log.close()
    for _ in range(15):
        time.sleep(0.1)
        try:
            with urlopen(url, timeout=0.3) as response:
                return response.status == 200
        except OSError:
            continue
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-latest", action="store_true", help="Reuse latest complete collection")
    args = parser.parse_args()
    errors = []
    if not args.from_latest:
        errors = collect()
    _, raw_path, data = latest_run()
    data = merge_accounts(data)
    date = dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30))).date().isoformat()
    items = make_items(data["tweets"], date)
    OUT.mkdir(parents=True, exist_ok=True)
    live_server = ensure_server()
    path = OUT / f"{date}.html"
    path.write_text(render(date, data, raw_path, items, "; ".join(errors), live_server))
    print(f"http://127.0.0.1:8765/{date}.html" if live_server else path)
    print(f"{len(items)} candidates from {len(data['tweets'])} collected posts; source: {raw_path}")


if __name__ == "__main__":
    main()
