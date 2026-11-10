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
import traceback
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

APP_NAME = "JustMeMedia"
PRODUCT_NAME = "ContentOS"
HOST = "127.0.0.1"

# Only these hostnames may appear in the Host header. This blocks DNS-rebinding
# attacks where a public domain resolves to 127.0.0.1 and a browser then treats
# this server as same-origin.
ALLOWED_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1"})

# Documents are plain text; anything larger is a mistake or an attack.
MAX_BODY_BYTES = 2_000_000


def _env_port() -> int:
    raw = os.environ.get("CONTENTOS_PORT", "8765")
    try:
        port = int(raw)
    except ValueError:
        raise SystemExit(f"CONTENTOS_PORT must be an integer, got {raw!r}.") from None
    if not 1 <= port <= 65535:
        raise SystemExit(f"CONTENTOS_PORT must be between 1 and 65535, got {port}.")
    return port


PORT = _env_port()


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
    conn.execute("PRAGMA busy_timeout = 5000")
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS content_items (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            pillar TEXT,
            status TEXT NOT NULL DEFAULT 'IDEA',
            audience TEXT,
            objective TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            current_version INTEGER NOT NULL DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS content_versions (
            id TEXT PRIMARY KEY,
            content_id TEXT NOT NULL REFERENCES content_items(id),
            version INTEGER NOT NULL,
            platform TEXT,
            body TEXT NOT NULL,
            visual_brief TEXT,
            created_at TEXT NOT NULL,
            created_by TEXT,
            UNIQUE(content_id, version, platform)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            title TEXT,
            publisher TEXT,
            published_at TEXT,
            retrieved_at TEXT NOT NULL,
            source_type TEXT,
            notes TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS claims (
            id TEXT PRIMARY KEY,
            content_version_id TEXT NOT NULL REFERENCES content_versions(id),
            claim_text TEXT NOT NULL,
            verification_status TEXT NOT NULL DEFAULT 'UNVERIFIED',
            notes TEXT
        )
    """)
    conn.commit()
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    """Open a short-lived connection, commit on success, and always close it.

    ``with sqlite3.connect(...)`` only commits or rolls back; it does not close
    the connection. This wrapper does both so request handlers cannot leak
    handles or hold transactions open.
    """
    conn = connect_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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


CSP = (
    "default-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'self'"
)


class ApiError(Exception):
    """Expected client error with the HTTP status to return."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def string_field(payload: dict, name: str) -> str:
    value = payload.get(name, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ApiError(400, f"Field '{name}' must be a string.")
    return value


class Handler(BaseHTTPRequestHandler):
    # --- response helpers -------------------------------------------------
    def _send(self, raw: bytes, status: int = 200,
              content_type: str = "application/json; charset=utf-8",
              headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(raw)

    def send_json(self, data, status=200, headers=None):
        self._send(json.dumps(data, ensure_ascii=False).encode("utf-8"), status, headers=headers)

    def send_error_json(self, status: int, message: str) -> None:
        self.send_json({"error": message}, status)

    # --- request guards ---------------------------------------------------
    def _request_hostname(self) -> str:
        host = self.headers.get("Host", "").strip()
        if host.startswith("["):  # bracketed IPv6 literal
            end = host.find("]")
            return host[1:end].lower() if end > 0 else ""
        return host.rsplit(":", 1)[0].strip().lower()

    def _check_host(self) -> None:
        """Reject requests addressed to anything but this machine's loopback names."""
        if self._request_hostname() not in ALLOWED_HOSTNAMES:
            raise ApiError(
                403,
                "Unrecognised Host header. ContentOS only answers on 127.0.0.1 or localhost.",
            )

    def _check_origin(self) -> None:
        """Reject state-changing requests made by another origin.

        Browsers send Origin on cross-origin writes, so this stops a web page
        from posting drafts to the local API even if it bypasses the Host check.
        """
        origin = self.headers.get("Origin")
        if origin is None:
            return
        port = self.server.server_address[1]
        allowed = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
        if origin not in allowed:
            raise ApiError(403, "Cross-origin requests are not allowed.")

    # --- error handling ---------------------------------------------------
    def _unexpected_error(self) -> None:
        traceback.print_exc()
        try:
            self.send_error_json(500, "Internal server error.")
        except Exception:
            # The client may already be gone; never mask the original error.
            pass

    # --- routing ----------------------------------------------------------
    def do_GET(self):
        try:
            self._check_host()
            self._handle_get()
        except ApiError as exc:
            self.send_error_json(exc.status, str(exc))
        except Exception:
            self._unexpected_error()

    def do_POST(self):
        try:
            self._check_host()
            self._check_origin()
            self._handle_post()
        except ApiError as exc:
            self.send_error_json(exc.status, str(exc))
        except Exception:
            self._unexpected_error()

    def _handle_get(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            raw = HTML.encode("utf-8")
            self._send(raw, 200, "text/html; charset=utf-8", {"Content-Security-Policy": CSP})
            return
        if path == "/api/status":
            self.send_json({"database": str(DB_PATH), "ollama": ollama_info()})
            return
        if path == "/api/drafts":
            with db() as conn:
                rows = [dict(r) for r in conn.execute(
                    "SELECT * FROM drafts ORDER BY updated_at DESC, id DESC"
                )]
            self.send_json(rows)
            return
        if path == "/api/export":
            with db() as conn:
                rows = [dict(r) for r in conn.execute("SELECT * FROM drafts ORDER BY id")]
            raw = json.dumps({"exported_at": now_iso(), "drafts": rows},
                             ensure_ascii=False, indent=2).encode("utf-8")
            self._send(raw, 200, headers={
                "Content-Disposition": 'attachment; filename="contentos-drafts-export.json"',
            })
            return
        if path == "/api/import":
            # Expect a JSON payload with "drafts" key (array of draft objects)
            # Support both: { "drafts": [...] } and direct [...]
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length > MAX_BODY_BYTES:
                raise ApiError(413, "Request body is too large.")
            try:
                payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ApiError(400, f"Invalid JSON body: {exc}") from None
            if not isinstance(payload, dict):
                raise ApiError(400, "JSON body must be an object.")
            drafts_data = payload.get("drafts", [])
            if not isinstance(drafts_data, list):
                raise ApiError(400, "'drafts' key must contain an array.")
            imported = 0
            stamp = now_iso()
            with db() as conn:
                for d in drafts_data:
                    if not isinstance(d, dict):
                        continue
                    title = string_field(d, "title").strip()
                    body = string_field(d, "body")
                    platform = string_field(d, "platform").strip() or "General"
                    if not title:
                        continue  # skip items without title
                    conn.execute(
                        "INSERT INTO drafts(title, body, platform, status, created_at, updated_at) "
                        "VALUES(?,?,?,?,?,?)",
                        (title[:200], body, platform, "Draft", stamp, stamp),
                    )
                    imported += 1
            self.send_json({"ok": True, "imported": imported}, 201)
            return
        if path == "/api/content_items":
            with db() as conn:
                rows = [dict(r) for r in conn.execute(
                    "SELECT * FROM content_items ORDER BY id"
                )]
            self.send_json(rows)
            return
        if path == "/api/content_versions":
            with db() as conn:
                rows = [dict(r) for r in conn.execute(
                    "SELECT * FROM content_versions ORDER BY id"
                )]
            self.send_json(rows)
            return
        if path == "/api/sources":
            with db() as conn:
                rows = [dict(r) for r in conn.execute(
                    "SELECT * FROM sources ORDER BY id"
                )]
            self.send_json(rows)
            return
        if path == "/api/claims":
            with db() as conn:
                rows = [dict(r) for r in conn.execute(
                    "SELECT * FROM claims ORDER BY id"
                )]
            self.send_json(rows)
            return
        raise ApiError(404, "Not found")

    def _handle_post(self) -> None:
        path = urlparse(self.path).path

        # --- multi-table POST support ----------------
        if path == "/api/content_items":
            self._post_content_items()
            return
        if path == "/api/content_versions":
            self._post_content_versions()
            return
        if path == "/api/sources":
            self._post_sources()
            return
        if path == "/api/claims":
            self._post_claims()
            return

        if path != "/api/drafts":
            raise ApiError(404, "Not found")

        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise ApiError(
                415,
                "Content-Type must be application/json. Cross-site form posts are refused.",
            )

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError(400, "Invalid Content-Length header.") from None
        if length <= 0:
            raise ApiError(400, "Request body is empty.")
        if length > MAX_BODY_BYTES:
            raise ApiError(413, "Request body is too large.")

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApiError(400, f"Invalid JSON body: {exc}") from None
        if not isinstance(payload, dict):
            raise ApiError(400, "JSON body must be an object.")

        title = string_field(payload, "title").strip()
        body = string_field(payload, "body")
        platform = string_field(payload, "platform").strip() or "General"
        if not title:
            raise ApiError(400, "Title is required.")

        stamp = now_iso()
        with db() as conn:
            cur = conn.execute(
                "INSERT INTO drafts(title, body, platform, status, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?)",
                (title[:200], body, platform[:40], "Draft", stamp, stamp),
            )
            draft_id = cur.lastrowid
        self.send_json({"ok": True, "id": draft_id}, 201)

    # --- POST handlers for synchronized schema tables ---

    def _post_content_items(self) -> None:
        """Create a new content item."""
        try:
            payload = json.loads(self.rfile.read(MAX_BODY_BYTES).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApiError(400, f"Invalid JSON body: {exc}") from None
        if not isinstance(payload, dict):
            raise ApiError(400, "JSON body must be an object.")

        # Required fields per 001_initial.sql
        title = string_field(payload, "title").strip()
        pillar = string_field(payload, "pillar")  # optional, may be None
        status = string_field(payload, "status") or "IDEA"
        audience = string_field(payload, "audience")  # optional
        objective = string_field(payload, "objective")  # optional
        current_version = int(payload.get("current_version", 1))

        if not title:
            raise ApiError(400, "Title is required.")

        stamp = now_iso()
        import uuid
        item_id = str(uuid.uuid4())  # UUID per schema

        with db() as conn:
            conn.execute(
                "INSERT INTO content_items(id, title, pillar, status, audience, objective, created_at, updated_at, current_version) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (item_id, title, pillar, status, audience, objective, stamp, stamp, current_version),
            )
        self.send_json({"ok": True, "id": item_id}, 201)

    def _post_content_versions(self) -> None:
        """Create a new content version."""
        try:
            payload = json.loads(self.rfile.read(MAX_BODY_BYTES).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApiError(400, f"Invalid JSON body: {exc}") from None
        if not isinstance(payload, dict):
            raise ApiError(400, "JSON body must be an object.")

        content_id = string_field(payload, "content_id")
        version = int(payload.get("version", 1))
        platform = string_field(payload, "platform") or ""
        body = string_field(payload, "body")
        visual_brief = string_field(payload, "visual_brief")  # optional
        created_by = string_field(payload, "created_by")  # optional

        if not content_id:
            raise ApiError(400, "content_id is required.")
        if not body:
            raise ApiError(400, "body is required.")

        # Verify content_items exists
        with db() as conn:
            cur = conn.execute("SELECT id FROM content_items WHERE id=?", (content_id,))
            if cur.fetchone() is None:
                raise ApiError(400, f"content_items with id={content_id} not found.")
            if version < 1:
                raise ApiError(400, "version must be >= 1.")

        stamp = now_iso()
        import uuid
        version_id = str(uuid.uuid4())

        with db() as conn:
            conn.execute(
                "INSERT INTO content_versions(id, content_id, version, platform, body, visual_brief, created_at, created_by) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (version_id, content_id, version, platform, body, visual_brief, stamp, created_by),
            )
        self.send_json({"ok": True, "id": version_id}, 201)

    def _post_sources(self) -> None:
        """Create a new source."""
        try:
            payload = json.loads(self.rfile.read(MAX_BODY_BYTES).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApiError(400, f"Invalid JSON body: {exc}") from None
        if not isinstance(payload, dict):
            raise ApiError(400, "JSON body must be an object.")

        url = string_field(payload, "url").strip()
        title = string_field(payload, "title")  # optional
        publisher = string_field(payload, "publisher")  # optional
        published_at = string_field(payload, "published_at")  # optional
        retrieved_at = string_field(payload, "retrieved_at") or now_iso()
        source_type = string_field(payload, "source_type")  # optional
        notes = string_field(payload, "notes")  # optional

        if not url:
            raise ApiError(400, "url is required.")

        stamp = now_iso()
        import uuid
        source_id = str(uuid.uuid4())

        with db() as conn:
            conn.execute(
                "INSERT INTO sources(id, url, title, publisher, published_at, retrieved_at, source_type, notes) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (source_id, url, title, publisher, published_at, retrieved_at, source_type, notes),
            )
        self.send_json({"ok": True, "id": source_id}, 201)

    def _post_claims(self) -> None:
        """Create a new claim."""
        try:
            payload = json.loads(self.rfile.read(MAX_BODY_BYTES).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApiError(400, f"Invalid JSON body: {exc}") from None
        if not isinstance(payload, dict):
            raise ApiError(400, "JSON body must be an object.")

        content_version_id = string_field(payload, "content_version_id").strip()
        claim_text = string_field(payload, "claim_text").strip()
        verification_status = string_field(payload, "verification_status") or "UNVERIFIED"
        notes = string_field(payload, "notes")  # optional

        if not content_version_id:
            raise ApiError(400, "content_version_id is required.")
        if not claim_text:
            raise ApiError(400, "claim_text is required.")

        # Verify content_versions exists
        with db() as conn:
            cur = conn.execute("SELECT id FROM content_versions WHERE id=?", (content_version_id,))
            if cur.fetchone() is None:
                raise ApiError(400, f"content_versions with id={content_version_id} not found.")

        stamp = now_iso()
        import uuid
        claim_id = str(uuid.uuid4())

        with db() as conn:
            conn.execute(
                "INSERT INTO claims(id, content_version_id, claim_text, verification_status, notes) "
                "VALUES(?,?,?,?,?)",
                (claim_id, content_version_id, claim_text, verification_status, notes),
            )
        self.send_json({"ok": True, "id": claim_id}, 201)

    def log_message(self, fmt, *args):
        print("[ContentOS] " + (fmt % args))


def main():
    # Ensure the database and tables exist before starting the server.
    # The connect_db() context manager handles creation and immediate close.
    with connect_db() as _:
        pass
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as exc:
        raise SystemExit(
            f"Could not start ContentOS on {HOST}:{PORT} - {exc}. "
            "Is another copy already running, or is the port in use?"
        ) from None
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
