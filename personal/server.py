#!/usr/bin/env python3
"""Loopback review server: serves HTML and persists each vote/note locally."""

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "output"
FEEDBACK = HERE / "feedback"
HOST = "127.0.0.1"
PORT = 8765
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STORY = re.compile(r"^[a-zA-Z0-9_-]{1,120}$")
WRITE_LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, data, content_type="application/json; charset=utf-8"):
        body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            return self.reply(200, {"ok": True})
        if parsed.path == "/api/feedback":
            date = parse_qs(parsed.query).get("date", [""])[0]
            if not DATE.fullmatch(date):
                return self.reply(400, {"error": "invalid date"})
            path = FEEDBACK / f"{date}.json"
            return self.reply(200, json.loads(path.read_text()) if path.exists() else {"date": date, "decisions": []})
        name = parsed.path.lstrip("/")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.html", name):
            return self.reply(404, {"error": "not found"})
        path = OUTPUT / name
        if not path.exists():
            return self.reply(404, {"error": "edition not found"})
        return self.reply(200, path.read_bytes(), "text/html; charset=utf-8")

    def do_POST(self):
        if self.path != "/api/feedback":
            return self.reply(404, {"error": "not found"})
        origin = self.headers.get("Origin", "")
        if origin != f"http://{HOST}:{PORT}":
            return self.reply(403, {"error": "invalid origin"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 16_384:
                raise ValueError("invalid request length")
            item = json.loads(self.rfile.read(length))
            date, story_id = item["date"], item["id"]
            if not DATE.fullmatch(date) or not STORY.fullmatch(story_id):
                raise ValueError("invalid date or story")
            if item.get("vote") not in (None, "post", "watch", "skip"):
                raise ValueError("invalid vote")
            reason = item.get("reason", "")
            if not isinstance(reason, str) or len(reason) > 2_000:
                raise ValueError("invalid reason")
        except (ValueError, KeyError, json.JSONDecodeError, TypeError) as exc:
            return self.reply(400, {"error": str(exc)})
        FEEDBACK.mkdir(parents=True, exist_ok=True)
        path = FEEDBACK / f"{date}.json"
        with WRITE_LOCK:
            saved = json.loads(path.read_text()) if path.exists() else {"date": date, "decisions": []}
            decisions = {d["id"]: d for d in saved["decisions"]}
            decisions[story_id] = {"id": story_id, "vote": item.get("vote"), "reason": reason}
            saved["decisions"] = list(decisions.values())
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(saved, indent=2, ensure_ascii=False) + "\n")
            temporary.replace(path)
        return self.reply(200, {"ok": True, "saved": story_id})


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
