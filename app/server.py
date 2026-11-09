#!/usr/bin/env python3
"""JustMeMedia ContentOS - local-first Phase 1 starter.

Uses only the Python standard library. Each computer stores its SQLite database
in its own OS application-data directory, never in the synchronized project folder.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

APP_NAME = "JustMeMedia"
PRODUCT_NAME = "ContentOS"
HOST = "127.0.0.1"
PORT = int(os.environ.get("CONTENTOS_PORT", "8765"))


def data_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    path = root / APP_NAME / PRODUCT_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


DB_PATH = data_dir() / "contentos.db"


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            platform TEXT NOT NULL DEFAULT 'General',
            status TEXT NOT NULL DEFAULT 'Draft',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ollama_info() -> dict:
    url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    try:
        request = urllib.request.Request(url + "/api/tags", headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=2.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        models = [m.get("name", "unknown") for m in payload.get("models", [])]
        return {"available": True, "url": url, "models": models}
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        return {"available": False, "url": url, "models": [], "error": str(exc)}


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>JustMeMedia ContentOS</title>
<style>
:root{color-scheme:dark;--bg:#101512;--panel:#19221c;--line:#304137;--green:#6da581;--text:#edf3ee;--muted:#a9b8ad}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui, sans-serif}
header{padding:26px max(22px,calc((100vw - 1100px)/2));border-bottom:1px solid var(--line);background:#141c17}
header strong{font-size:22px;letter-spacing:.3px}header span{display:block;color:var(--muted);margin-top:4px}
main{max-width:1100px;margin:28px auto;padding:0 22px;display:grid;grid-template-columns:minmax(0,1.2fr) minmax(280px,.8fr);gap:22px}
section{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px}
h2{font-size:17px;margin:0 0 16px}label{display:block;color:var(--muted);font-size:13px;margin:12px 0 5px}
input,textarea,select{width:100%;background:#101713;color:var(--text);border:1px solid var(--line);border-radius:7px;padding:10px;font:inherit}
textarea{min-height:190px;resize:vertical}button{background:var(--green);color:#0d1710;border:0;border-radius:7px;padding:10px 15px;font-weight:700;cursor:pointer;margin-top:13px}
button.secondary{background:#29382e;color:var(--text);border:1px solid var(--line);margin-left:6px}
.item{border-top:1px solid var(--line);padding:13px 0}.item:first-child{border-top:0}.item strong{display:block}.item small,.muted{color:var(--muted)}
.status{padding:10px;border-radius:8px;background:#101713;margin:10px 0}.good{color:#9ad5a9}.bad{color:#f0aa9d}
#message{color:var(--muted);min-height:22px;margin-top:8px}
@media(max-width:760px){main{grid-template-columns:1fr}}
</style></head>
<body>
<header><strong>JustMeMedia ContentOS</strong><span>Local-first content workspace · Phase 1 foundation</span></header>
<main>
<section>
<h2>Create a content draft</h2>
<form id="draftForm">
<label for="title">Title</label><input id="title" required maxlength="200" placeholder="Working title">
<label for="platform">Platform</label><select id="platform"><option>General</option><option>LinkedIn</option><option>X</option><option>Facebook</option><option>Instagram</option><option>Threads</option><option>YouTube</option></select>
<label for="body">Draft content</label><textarea id="body" placeholder="Write or paste a draft..."></textarea>
<button type="submit">Save draft locally</button><div id="message" role="status"></div>
</form>
</section>
<section>
<h2>Local system status</h2>
<div class="status">Database: <span class="good">Connected</span><br><small id="dbpath"></small></div>
<div class="status">Ollama: <span id="ollamaStatus">Checking…</span><div id="models" class="muted"></div></div>
<button id="refresh" class="secondary">Refresh status</button>
<button id="export" class="secondary">Export drafts JSON</button>
<h2 style="margin-top:26px">Saved drafts</h2><div id="drafts" class="muted">Loading…</div>
</section>
</main>
<script>
async function loadDrafts(){
 const r=await fetch('/api/drafts'); const data=await r.json(); const el=document.getElementById('drafts');
 if(!data.length){el.textContent='No drafts yet. Create your first draft on the left.';return;}
 el.innerHTML=data.map(d=>`<div class="item"><strong>${escapeHtml(d.title)}</strong><small>${escapeHtml(d.platform)} · ${escapeHtml(d.status)} · ${escapeHtml(d.updated_at)}</small><p>${escapeHtml(d.body).slice(0,260)}${d.body.length>260?'…':''}</p></div>`).join('');
}
function escapeHtml(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
async function status(){
 const r=await fetch('/api/status'); const d=await r.json();
 document.getElementById('dbpath').textContent=d.database;
 const s=document.getElementById('ollamaStatus'), m=document.getElementById('models');
 s.textContent=d.ollama.available?'Available':'Not detected';s.className=d.ollama.available?'good':'bad';
 m.textContent=d.ollama.available?(d.ollama.models.length?d.ollama.models.join(', '):'Ollama is running; no models reported.'):(d.ollama.error||'Start Ollama to connect.');
}
document.getElementById('draftForm').addEventListener('submit',async e=>{
 e.preventDefault();const payload={title:document.getElementById('title').value,platform:document.getElementById('platform').value,body:document.getElementById('body').value};
 const r=await fetch('/api/drafts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
 const d=await r.json();document.getElementById('message').textContent=r.ok?'Saved to this computer.':'Could not save: '+(d.error||'unknown error');
 if(r.ok){e.target.reset();loadDrafts();}
});
document.getElementById('refresh').addEventListener('click',status);
document.getElementById('export').addEventListener('click',()=>{window.location.href='/api/export';});
loadDrafts();status();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def send_json(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            raw = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if path == "/api/status":
            self.send_json({"database": str(DB_PATH), "ollama": ollama_info()})
            return
        if path == "/api/drafts":
            with connect_db() as conn:
                rows = [dict(r) for r in conn.execute("SELECT * FROM drafts ORDER BY updated_at DESC, id DESC")]
            self.send_json(rows)
            return
        if path == "/api/export":
            with connect_db() as conn:
                rows = [dict(r) for r in conn.execute("SELECT * FROM drafts ORDER BY id")]
            raw = json.dumps({"exported_at": now_iso(), "drafts": rows}, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="contentos-drafts-export.json"')
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        self.send_json({"error": "Not found"}, 404)

    def do_POST(self):
        if urlparse(self.path).path != "/api/drafts":
            self.send_json({"error": "Not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 2_000_000:
                raise ValueError("Request body is empty or too large.")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            title = str(payload.get("title", "")).strip()
            body = str(payload.get("body", ""))
            platform = str(payload.get("platform", "General")).strip() or "General"
            if not title:
                raise ValueError("Title is required.")
            stamp = now_iso()
            with connect_db() as conn:
                cur = conn.execute(
                    "INSERT INTO drafts(title, body, platform, status, created_at, updated_at) VALUES(?,?,?,?,?,?)",
                    (title[:200], body, platform[:40], "Draft", stamp, stamp)
                )
                draft_id = cur.lastrowid
            self.send_json({"ok": True, "id": draft_id}, 201)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self.send_json({"error": str(exc)}, 400)

    def log_message(self, fmt, *args):
        print("[ContentOS] " + (fmt % args))


def main():
    connect_db().close()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"JustMeMedia ContentOS running at http://{HOST}:{PORT}")
    print(f"Local database: {DB_PATH}")
    print("This server is bound to localhost; it is not exposed to your network.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping ContentOS...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
