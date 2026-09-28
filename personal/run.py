#!/usr/bin/env python3
"""Build a private, reviewable HTML edition from the fork's X collector."""

import argparse
import datetime as dt
import html
import json
import math
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
RUNS = ROOT / "tools" / "scrapers" / "runs"
OUT = HERE / "output"
EDITORIAL = HERE / "editorial"

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
            if data.get("tweets") and not data.get("diagnostics", {}).get("wasPartial"):
                candidates.append((raw.stat().st_mtime, raw, data))
        except (OSError, json.JSONDecodeError):
            continue
    if not candidates:
        raise SystemExit("No complete X collection exists. Run the fork's collector first.")
    return max(candidates)


def collect():
    subprocess.run(
        ["node", "--import", "tsx", "cli.ts", "run", "twitter", "--scrape-only"],
        cwd=ROOT / "tools" / "scrapers", check=True,
    )


def make_items(tweets, date):
    by_id = {str(t["id"]): t for t in tweets}
    edited = EDITORIAL / f"{date}.json"
    items = []
    used = set()
    suppress_terms = []
    if edited.exists():
        for entry in json.loads(edited.read_text()):
            sources = [by_id[str(i)] for i in entry["tweet_ids"] if str(i) in by_id]
            if not sources:
                continue
            used.update(str(t["id"]) for t in sources)
            suppress_terms.extend(entry.get("suppress_terms", []))
            items.append({
                "id": entry["id"], "title": entry["title"],
                "summary": entry["summary"], "why": entry["why"],
                "sources": [x_url(t) for t in sources] + entry.get("extra_sources", []), "editorial": True,
            })
    ranked = sorted((t for t in tweets if str(t["id"]) not in used and not any(term.lower() in t.get("text", "").lower() for term in suppress_terms)), key=score, reverse=True)
    for t in ranked:
        if len(items) >= 12:
            break
        if score(t) < 12:
            break
        text = " ".join(t["text"].split())
        items.append({
            "id": "x-" + str(t["id"]),
            "title": text[:105].rsplit(" ", 1)[0] + ("…" if len(text) > 105 else ""),
            "summary": text[:360] + ("…" if len(text) > 360 else ""),
            "why": "Candidate from the monitored X list; needs your judgment and source verification.",
            "sources": [x_url(t)], "editorial": False,
        })
    return items


def render(date, data, raw_path, items, collection_error):
    diag = data.get("diagnostics", {})
    start = diag.get("startParam", "unknown")
    end = diag.get("endParam", "unknown")
    coverage = f"{len(data['tweets'])} X posts · {diag.get('pagesFetched', '?')} pages · {html.escape(start)} to {html.escape(end)}"
    warning = "" if not collection_error else f'<p class="warning">New collection failed: {html.escape(collection_error)}. This edition uses the last complete saved run.</p>'
    cards = []
    for i, item in enumerate(items, 1):
        links = " ".join(f'<a href="{html.escape(url)}" target="_blank" rel="noopener">Source {n}</a>' for n, url in enumerate(item["sources"], 1))
        badge = "Edited selection" if item["editorial"] else "Scanner candidate"
        cards.append(f'''<article class="card" data-id="{html.escape(item['id'])}">
          <div class="eyebrow">{i:02d} · {badge}</div>
          <h2>{html.escape(item['title'])}</h2>
          <p>{html.escape(item['summary'])}</p>
          <p class="why"><strong>Why it may matter</strong> · {html.escape(item['why'])}</p>
          <div class="sources">{links}</div>
          <div class="vote" role="group" aria-label="Review {html.escape(item['title'])}">
            <button data-vote="post">Good to post</button><button data-vote="watch">Watch</button><button data-vote="skip">Skip</button>
          </div>
          <label>Reason or angle <input class="reason" placeholder="What makes this useful or weak?" /></label>
        </article>''')
    payload = json.dumps({"date": date, "items": items}, ensure_ascii=False).replace("</", "<\\/")
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>AI Engineering · {date}</title><style>
    :root{{--ink:#13252b;--muted:#557079;--line:#cddcdb;--paper:#f5f8f6;--accent:#087a66}}
    *{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 system-ui,-apple-system,sans-serif}}
    main{{max-width:930px;margin:auto;padding:42px 22px 100px}}header{{border-bottom:2px solid var(--ink);padding-bottom:28px}}
    .eyebrow{{text-transform:uppercase;letter-spacing:.12em;font-size:12px;font-weight:750;color:var(--accent)}}h1{{font-size:clamp(42px,7vw,76px);line-height:1.02;letter-spacing:-.055em;margin:14px 0}}
    h2{{font-size:25px;line-height:1.2;letter-spacing:-.025em;margin:8px 0 12px}}.dek{{font-size:19px;max-width:680px}}
    .meta,.note{{color:var(--muted);font-size:14px}}.warning{{background:#fff2d6;padding:14px;border-radius:7px}}.card{{background:white;border:1px solid var(--line);border-radius:12px;margin:18px 0;padding:24px;box-shadow:0 3px 14px #13252b08}}
    .why{{background:#eff7f3;padding:12px 15px;border-left:3px solid var(--accent)}}a{{color:#075f79;margin-right:14px}}.sources{{font-size:14px;margin:15px 0}}.vote{{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0 12px}}
    button{{border:1px solid #a7c6c0;background:white;border-radius:7px;padding:9px 13px;cursor:pointer;font-weight:650;color:var(--ink)}}button:hover,button.selected{{background:var(--accent);color:white;border-color:var(--accent)}}
    label{{display:block;font-size:13px;color:var(--muted)}}input{{display:block;width:100%;margin-top:5px;padding:10px;border:1px solid var(--line);border-radius:6px;font:inherit}}.actions{{position:sticky;bottom:0;background:#f5f8f6eb;padding:13px 0;border-top:1px solid var(--line);display:flex;gap:10px;align-items:center;flex-wrap:wrap}}.actions button{{background:var(--ink);color:white}}
    </style></head><body><main><header><div class="eyebrow">Private morning review · {date}</div><h1>AI Engineering</h1>
    <p class="dek">Technically interesting launches, methods, and shifts from the AINews monitored list. Mark what belongs on your channel; nothing here is posted automatically.</p>
    <div class="meta">{coverage}</div>{warning}</header>
    <p class="note">This first edition uses the fork’s X collector. Reddit needs a session, and the archive and deeper primary-source checks are not yet part of the daily collector. Claims in scanner candidates are attributed to their linked posts.</p>
    {''.join(cards)}<div class="actions"><button id="copy">Copy review for chat</button><button id="download">Download taste dataset</button><span id="count" class="meta"></span></div>
    <script id="edition" type="application/json">{payload}</script><script>
    const edition=JSON.parse(document.getElementById('edition').textContent);const key='ai-engineering-review:'+edition.date;
    const state=JSON.parse(localStorage.getItem(key)||'{{}}');
    function save(){{localStorage.setItem(key,JSON.stringify(state));render()}}
    function render(){{let n=0;document.querySelectorAll('.card').forEach(card=>{{let id=card.dataset.id,v=state[id]||{{}};card.querySelectorAll('[data-vote]').forEach(b=>b.classList.toggle('selected',b.dataset.vote===v.vote));card.querySelector('.reason').value=v.reason||'';if(v.vote)n++}});document.getElementById('count').textContent=n+'/'+edition.items.length+' classified'}}
    document.querySelectorAll('.card').forEach(card=>{{let id=card.dataset.id;card.querySelectorAll('[data-vote]').forEach(b=>b.onclick=()=>{{state[id]={{...(state[id]||{{}}),vote:b.dataset.vote}};save()}});card.querySelector('.reason').onchange=e=>{{state[id]={{...(state[id]||{{}}),reason:e.target.value}};save()}}}});
    const exportData=()=>({{date:edition.date,decisions:edition.items.filter(i=>state[i.id]?.vote).map(i=>({{id:i.id,title:i.title,vote:state[i.id].vote,reason:state[i.id].reason||'',sources:i.sources}}))}});
    document.getElementById('copy').onclick=async()=>{{const d=exportData();await navigator.clipboard.writeText(JSON.stringify(d,null,2));document.getElementById('count').textContent='Copied '+d.decisions.length+' decisions. Paste them in chat.'}};
    document.getElementById('download').onclick=()=>{{const blob=new Blob([JSON.stringify(exportData(),null,2)],{{type:'application/json'}});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='ai-engineering-review-'+edition.date+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}};render();
    </script></main></body></html>'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-latest", action="store_true", help="Reuse latest complete collection")
    args = parser.parse_args()
    error = None
    if not args.from_latest:
        try:
            collect()
        except (OSError, subprocess.CalledProcessError) as exc:
            error = str(exc)
    _, raw_path, data = latest_run()
    date = dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30))).date().isoformat()
    items = make_items(data["tweets"], date)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{date}.html"
    path.write_text(render(date, data, raw_path, items, error))
    print(path)
    print(f"{len(items)} candidates from {len(data['tweets'])} collected posts; source: {raw_path}")


if __name__ == "__main__":
    main()
