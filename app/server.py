#!/usr/bin/env python3
"""JustMeMedia ContentOS - Local-First Content Engine & Publishing Hub.

Zero third-party dependencies (Python standard library only).
Stores SQLite database in OS application-data directory (never in cloud/git sync).
Dual-host compatible: Windows (ThinkCentre) and macOS (M1 Pro).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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

    # 1. Drafts table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            platform TEXT NOT NULL DEFAULT 'General',
            status TEXT NOT NULL DEFAULT 'Draft',
            image_prompt TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # Schema migration columns for drafts
    cur = conn.execute("PRAGMA table_info(drafts)")
    cols = [row["name"] for row in cur.fetchall()]
    if "image_prompt" not in cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN image_prompt TEXT NOT NULL DEFAULT ''")
    if "source_url" not in cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN source_url TEXT NOT NULL DEFAULT ''")

    # 2. Content items & versions
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
            model_info TEXT,
            UNIQUE (content_id, version)
        )
    """)

    # 3. Sources table (Research intake & provenance)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY,
            url TEXT UNIQUE,
            title TEXT NOT NULL,
            publisher TEXT NOT NULL DEFAULT '',
            retrieved_at TEXT NOT NULL,
            raw_text TEXT,
            summary TEXT NOT NULL DEFAULT ''
        )
    """)

    # 4. Claims table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS claims (
            id TEXT PRIMARY KEY,
            content_id TEXT REFERENCES content_items(id),
            source_id TEXT REFERENCES sources(id),
            claim_text TEXT NOT NULL,
            verified INTEGER NOT NULL DEFAULT 0,
            notes TEXT
        )
    """)

    # 5. Approvals audit trail
    conn.execute("""
        CREATE TABLE IF NOT EXISTS approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            draft_id INTEGER NOT NULL,
            approved_at TEXT NOT NULL,
            platform TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (draft_id) REFERENCES drafts(id) ON DELETE CASCADE
        )
    """)

    conn.commit()
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    """Context manager for database connections with automatic commit/rollback."""
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


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def string_field(payload: dict, name: str) -> str:
    val = payload.get(name, "")
    if val is None:
        return ""
    if not isinstance(val, str):
        raise ApiError(400, f"Field {name!r} must be a string, got {type(val).__name__}.")
    return val.strip()


def ollama_info() -> dict:
    url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    try:
        req = urllib.request.Request(url + "/api/tags", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=2.5) as res:
            payload = json.loads(res.read().decode("utf-8"))
        models = [m.get("name", "unknown") for m in payload.get("models", [])]
        return {"available": True, "url": url, "models": models}
    except Exception as exc:
        return {"available": False, "url": url, "models": [], "error": str(exc)}


def get_available_providers() -> dict:
    providers = []
    ollama = ollama_info()
    if ollama.get("available"):
        for m in ollama.get("models", []):
            providers.append({"id": f"ollama:{m}", "name": f"Local Ollama: {m}", "type": "local"})

    if os.environ.get("GROQ_API_KEY"):
        providers.append({"id": "groq:llama-3.3-70b-versatile", "name": "Groq Cloud: Llama 3.3 70B (Free)", "type": "cloud"})

    if os.environ.get("GEMINI_API_KEY"):
        providers.append({"id": "gemini:gemini-2.5-flash", "name": "Google Gemini 2.5 Flash (Cloud)", "type": "cloud"})

    if not providers:
        providers.append({"id": "none", "name": "No AI Providers Detected (Manual Mode)", "type": "none"})

    return {
        "providers": providers,
        "ollama": ollama,
        "has_groq": bool(os.environ.get("GROQ_API_KEY")),
        "has_gemini": bool(os.environ.get("GEMINI_API_KEY"))
    }


def call_ai(provider_id: str, prompt: str, system_prompt: str = "") -> str:
    if provider_id.startswith("ollama:"):
        model_name = provider_id.split(":", 1)[1]
        url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/generate"
        payload = {
            "model": model_name,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("response", "").strip()

    elif provider_id.startswith("groq:"):
        api_key = os.environ.get("GROQ_API_KEY", "")
        model_name = provider_id.split(":", 1)[1]
        url = "https://api.groq.com/openai/v1/chat/completions"
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()

    elif provider_id.startswith("gemini:"):
        api_key = os.environ.get("GEMINI_API_KEY", "")
        model_name = provider_id.split(":", 1)[1]
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        full_text = f"{system_prompt}\n\nTask: {prompt}" if system_prompt else prompt
        payload = {
            "contents": [{"parts": [{"text": full_text}]}]
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()

    raise ValueError(f"Unknown or unsupported provider: {provider_id}")


def fetch_rss_feed(url: str, limit: int = 8) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; JustMeMediaContentOS/1.0)"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        xml_data = resp.read()
    root = ET.fromstring(xml_data)
    items = []
    for item in root.findall(".//item")[:limit]:
        title = item.findtext("title") or "Untitled"
        link = item.findtext("link") or ""
        desc = item.findtext("description") or ""
        clean_desc = re.sub(r"<[^>]+>", "", desc).strip()[:240]
        items.append({"title": title.strip(), "url": link.strip(), "snippet": clean_desc})
    if not items:
        for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry")[:limit]:
            title = entry.findtext("{http://www.w3.org/2005/Atom}title") or "Untitled"
            link_el = entry.find("{http://www.w3.org/2005/Atom}link")
            link = link_el.attrib.get("href", "") if link_el is not None else ""
            summary = entry.findtext("{http://www.w3.org/2005/Atom}summary") or ""
            items.append({"title": title.strip(), "url": link.strip(), "snippet": summary[:240]})
    return items


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>JustMeMedia ContentOS</title>
<style>
:root{color-scheme:dark;--bg:#0c110e;--panel:#141b16;--panel-alt:#1b251f;--line:#28382e;--accent:#48bb78;--accent-hover:#38a169;--text:#edf3ee;--muted:#9cb0a2;--danger:#e53e3e;--warning:#ecc94b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 system-ui,-apple-system,sans-serif}
header{padding:18px 28px;border-bottom:1px solid var(--line);background:#101712;display:flex;justify-content:space-between;align-items:center}
header .brand{font-size:20px;font-weight:700;letter-spacing:.3px;color:#fff}
header .brand span{color:var(--accent)}
header .tagline{font-size:12px;color:var(--muted);margin-left:12px}
.nav-links{display:flex;gap:10px}
.nav-btn{background:transparent;border:1px solid var(--line);color:var(--text);padding:6px 12px;border-radius:6px;cursor:pointer;font-size:12px}
.nav-btn:hover{background:var(--panel-alt);border-color:var(--accent)}
main{max-width:1440px;margin:22px auto;padding:0 24px;display:grid;grid-template-columns:360px minmax(0,1.2fr) 360px;gap:20px}
@media(max-width:1150px){main{grid-template-columns:1fr 1fr}}
@media(max-width:780px){main{grid-template-columns:1fr}}
section{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px;display:flex;flex-direction:column}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.5px;margin:0 0 14px;color:var(--accent);display:flex;align-items:center;justify-content:space-between}
label{display:block;color:var(--muted);font-size:12px;margin:10px 0 4px;font-weight:600}
input,textarea,select{width:100%;background:#0c120e;color:var(--text);border:1px solid var(--line);border-radius:6px;padding:8px 10px;font:inherit;font-size:13px}
input:focus,textarea:focus,select:focus{border-color:var(--accent);outline:none}
textarea{min-height:160px;resize:vertical;font-family:inherit}
.btn{background:var(--accent);color:#08130b;border:0;border-radius:6px;padding:9px 14px;font-weight:700;font-size:13px;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:6px;transition:.15s}
.btn:hover{background:var(--accent-hover)}
.btn-secondary{background:var(--panel-alt);color:var(--text);border:1px solid var(--line)}
.btn-secondary:hover{background:#233129;border-color:var(--muted)}
.btn-small{padding:5px 9px;font-size:11px;border-radius:4px}
.btn-approve{background:#2b6cb0;color:#fff}
.btn-approve:hover{background:#2c5282}
.btn-danger{background:transparent;border:1px solid #742a2a;color:#feb2b2}
.btn-danger:hover{background:#742a2a;color:#fff}
.status-pill{font-size:10px;text-transform:uppercase;letter-spacing:.5px;padding:2px 7px;border-radius:10px;font-weight:700}
.status-draft{background:#2d3748;color:#cbd5e0}
.status-approved{background:#22543d;color:#9ae6b4}
.status-published{background:#2c5282;color:#bee3f8}
.item-card{background:var(--panel-alt);border:1px solid var(--line);border-radius:8px;padding:12px;margin-bottom:12px;position:relative}
.item-card h3{margin:0 0 6px;font-size:14px;color:#fff;word-break:break-word}
.item-meta{font-size:11px;color:var(--muted);display:flex;align-items:center;gap:8px;margin-bottom:8px}
.item-card p{margin:0 0 10px;font-size:13px;color:#d2ded5;white-space:pre-wrap;max-height:120px;overflow:hidden;text-overflow:ellipsis}
.image-prompt-box{background:#0c120e;border:1px dashed #354a3e;border-radius:6px;padding:10px;margin:8px 0;font-size:12px;color:#9ae6b4}
.char-counter{font-size:11px;color:var(--muted);text-align:right;margin-top:4px}
.char-counter.limit-exceeded{color:var(--danger);font-weight:700}
.toast{min-height:22px;font-size:12px;color:var(--accent);margin-top:8px}
.source-item{padding:10px 0;border-top:1px solid var(--line);font-size:12px}
.source-item:first-child{border-top:0}
.source-item a{color:#9ae6b4;text-decoration:none;font-weight:600}
.source-item a:hover{text-decoration:underline}
.composer-links{display:flex;gap:6px;margin-top:8px}
</style>
</head>
<body>
<header>
  <div>
    <span class="brand">JustMe<span>Media</span> ContentOS</span>
    <span class="tagline">Local-First Content Engine & Multimodal Publishing Hub</span>
  </div>
  <div class="nav-links">
    <button class="nav-btn" onclick="exportDraftsJson()">Export JSON</button>
    <button class="nav-btn" onclick="exportAllMarkdown()">Export All Markdown</button>
  </div>
</header>

<main>
  <!-- COLUMN 1: DISCOVERY & INTAKE -->
  <section>
    <h2>1. Content Discovery <span style="font-size:11px;font-weight:normal;color:var(--muted)">Free RSS Feeds</span></h2>
    <label for="rssPreset">Curated Industry Feeds</label>
    <select id="rssPreset" onchange="fetchFeed(this.value)">
      <option value="https://news.ycombinator.com/rss">Hacker News Top Stories</option>
      <option value="https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml">NYT Technology News</option>
      <option value="https://feeds.arstechnica.com/arstechnica/index">Ars Technica Tech & AI</option>
    </select>
    <div style="display:flex;gap:6px;margin-top:8px">
      <input id="customRss" placeholder="Paste custom RSS/Atom URL">
      <button class="btn btn-secondary btn-small" onclick="fetchFeed(document.getElementById('customRss').value)">Load</button>
    </div>
    
    <label style="margin-top:16px">Top Stories & Trends</label>
    <div id="sourcesList" style="flex:1;overflow-y:auto;max-height:550px">Loading stories…</div>
  </section>

  <!-- COLUMN 2: DRAFTING & AI ENGINE -->
  <section>
    <h2>2. Content Engine & AI Drafting</h2>
    
    <label for="aiProvider">Select Intelligence Provider</label>
    <select id="aiProvider"></select>
    
    <div style="display:grid;grid-template-columns:1fr 140px;gap:10px;margin-top:6px">
      <div>
        <label for="draftTitle">Headline / Working Title</label>
        <input id="draftTitle" required placeholder="e.g. Why Local AI is Winning">
      </div>
      <div>
        <label for="draftPlatform">Platform</label>
        <select id="draftPlatform" onchange="updateCharCount()">
          <option value="LinkedIn">LinkedIn</option>
          <option value="X">X (Twitter)</option>
          <option value="Instagram">Instagram/Threads</option>
          <option value="YouTube">YouTube Brief</option>
          <option value="General">General Draft</option>
        </select>
      </div>
    </div>

    <div style="display:flex;gap:8px;margin-top:10px">
      <button id="btnAiDraft" class="btn btn-secondary" onclick="generateAiDraft()">⚡ Generate Draft with AI</button>
      <button id="btnAiVisual" class="btn btn-secondary" onclick="generateImagePrompt()">🎨 Suggest Image Prompt</button>
    </div>
    
    <label for="draftBody" style="margin-top:12px">Post Body & Formatting</label>
    <textarea id="draftBody" oninput="updateCharCount()" placeholder="Write post or generate with AI..."></textarea>
    <div id="charCounter" class="char-counter">0 characters</div>

    <label for="draftImagePrompt">Generated Visual / Artwork Brief (for Gemini, Groq, FLUX, Grok)</label>
    <textarea id="draftImagePrompt" style="min-height:75px" placeholder="AI visual generation prompt..."></textarea>
    
    <input type="hidden" id="draftSourceUrl">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px">
      <button class="btn" onclick="saveDraft()">💾 Save Draft</button>
      <span id="saveToast" class="toast"></span>
    </div>
  </section>

  <!-- COLUMN 3: STAGING & APPROVAL GATEWAY -->
  <section>
    <h2>3. Approval & Publishing Hub</h2>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
      <label style="margin:0">Saved Drafts & Queue</label>
      <span id="queueCount" style="font-size:11px;color:var(--muted)">0 items</span>
    </div>
    <div id="draftsQueue" style="flex:1;overflow-y:auto;max-height:680px">Loading drafts…</div>
  </section>
</main>

<script>
let currentProviders = [];

async function loadStatus() {
  try {
    const res = await fetch('/api/providers');
    const data = await res.json();
    currentProviders = data.providers;
    const sel = document.getElementById('aiProvider');
    sel.innerHTML = currentProviders.map(p => `<option value="${p.id}">${p.name}</option>`).join('');
  } catch (err) {
    console.error('Failed to load providers', err);
  }
}

async function fetchFeed(url) {
  if (!url) return;
  const listEl = document.getElementById('sourcesList');
  listEl.innerHTML = '<div style="color:var(--muted);padding:10px 0">Fetching feed…</div>';
  try {
    const res = await fetch('/api/intake?url=' + encodeURIComponent(url));
    const items = await res.json();
    if (!items.length) {
      listEl.innerHTML = '<div style="color:var(--muted);padding:10px 0">No stories found in feed.</div>';
      return;
    }
    window._sources = items;
    listEl.innerHTML = items.map((item, idx) => `
      <div class="source-item">
        <a href="${item.url}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a>
        <p style="margin:4px 0 6px;color:var(--muted);font-size:11px">${escapeHtml(item.snippet)}</p>
        <button class="btn btn-secondary btn-small" onclick="useStory(${idx})">
          ⚡ Draft from Story
        </button>
      </div>
    `).join('');
  } catch (err) {
    listEl.innerHTML = '<div style="color:var(--danger);padding:10px 0">Failed to fetch RSS feed.</div>';
  }
}

function useStory(idx) {
  const item = (window._sources || [])[idx];
  if (!item) return;
  document.getElementById('draftTitle').value = item.title;
  document.getElementById('draftBody').value = item.snippet;
  document.getElementById('draftSourceUrl').value = item.url;
  updateCharCount();
  document.getElementById('draftTitle').focus();
}

function updateCharCount() {
  const text = document.getElementById('draftBody').value;
  const platform = document.getElementById('draftPlatform').value;
  const count = text.length;
  const counter = document.getElementById('charCounter');
  let limit = platform === 'X' ? 280 : (platform === 'LinkedIn' ? 3000 : 2200);
  counter.textContent = `${count} / ${limit} characters`;
  if (count > limit) {
    counter.classList.add('limit-exceeded');
  } else {
    counter.classList.remove('limit-exceeded');
  }
}

async function generateAiDraft() {
  const title = document.getElementById('draftTitle').value.trim();
  const context = document.getElementById('draftBody').value.trim();
  const platform = document.getElementById('draftPlatform').value;
  const provider = document.getElementById('aiProvider').value;

  if (!title && !context) {
    alert('Please enter a headline or draft topic first.');
    return;
  }

  const btn = document.getElementById('btnAiDraft');
  btn.disabled = true;
  btn.textContent = 'Generating…';
  
  try {
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        task: 'draft_post',
        title: title || 'Thought Leadership',
        context: context,
        platform: platform,
        provider: provider
      })
    });
    const data = await res.json();
    if (data.ok) {
      document.getElementById('draftBody').value = data.result;
      if (data.image_prompt) {
        document.getElementById('draftImagePrompt').value = data.image_prompt;
      }
      updateCharCount();
    } else {
      alert('Generation error: ' + (data.error || 'Unknown error'));
    }
  } catch (err) {
    alert('Failed to connect to AI engine.');
  } finally {
    btn.disabled = false;
    btn.textContent = '⚡ Generate Draft with AI';
  }
}

async function generateImagePrompt() {
  const title = document.getElementById('draftTitle').value.trim();
  const body = document.getElementById('draftBody').value.trim();
  const provider = document.getElementById('aiProvider').value;

  if (!title && !body) {
    alert('Provide a title or post text first.');
    return;
  }

  const btn = document.getElementById('btnAiVisual');
  btn.disabled = true;
  btn.textContent = 'Thinking…';
  
  try {
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        task: 'image_prompt',
        title: title,
        context: body,
        provider: provider
      })
    });
    const data = await res.json();
    if (data.ok) {
      document.getElementById('draftImagePrompt').value = data.result;
    }
  } catch (err) {
    alert('Error generating visual prompt.');
  } finally {
    btn.disabled = false;
    btn.textContent = '🎨 Suggest Image Prompt';
  }
}

async function saveDraft() {
  const title = document.getElementById('draftTitle').value.trim();
  const body = document.getElementById('draftBody').value;
  const platform = document.getElementById('draftPlatform').value;
  const image_prompt = document.getElementById('draftImagePrompt').value;
  const source_url = document.getElementById('draftSourceUrl').value;

  if (!title) {
    alert('Title is required.');
    return;
  }

  const res = await fetch('/api/drafts', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({title, body, platform, image_prompt, source_url})
  });
  const data = await res.json();
  const toast = document.getElementById('saveToast');
  if (res.ok) {
    toast.textContent = 'Saved to local database!';
    setTimeout(() => { toast.textContent = ''; }, 3000);
    loadDrafts();
  } else {
    toast.textContent = 'Error: ' + data.error;
  }
}

async function loadDrafts() {
  const res = await fetch('/api/drafts');
  const drafts = await res.json();
  const queueEl = document.getElementById('draftsQueue');
  document.getElementById('queueCount').textContent = `${drafts.length} items`;
  
  if (!drafts.length) {
    queueEl.innerHTML = '<div style="color:var(--muted);padding:10px 0">No drafts yet. Create or generate one on the left.</div>';
    return;
  }

  window._drafts = {};
  drafts.forEach(d => { window._drafts[d.id] = d; });

  queueEl.innerHTML = drafts.map(d => {
    const statusClass = d.status === 'Approved' ? 'status-approved' : (d.status === 'Published' ? 'status-published' : 'status-draft');
    return `
      <div class="item-card">
        <div style="display:flex;justify-content:space-between;align-items:flex-start">
          <h3>${escapeHtml(d.title)}</h3>
          <span class="status-pill ${statusClass}">${escapeHtml(d.status)}</span>
        </div>
        <div class="item-meta">
          <span>${escapeHtml(d.platform)}</span> · <span>${escapeHtml(d.updated_at.slice(0,10))}</span>
        </div>
        <p>${escapeHtml(d.body)}</p>
        
        ${d.image_prompt ? `
          <div class="image-prompt-box">
            <strong>🎨 Visual Prompt:</strong> ${escapeHtml(d.image_prompt)}
            <div style="margin-top:4px">
              <button class="btn btn-secondary btn-small" onclick="copyPromptText(${d.id})">Copy Prompt</button>
            </div>
          </div>
        ` : ''}

        <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:10px">
          <button class="btn btn-secondary btn-small" onclick="copyDraftText(${d.id})">📋 Copy Post</button>
          <button class="btn btn-secondary btn-small" onclick="downloadMarkdown(${d.id})">📥 Export .MD</button>
          ${d.status !== 'Approved' ? `
            <button class="btn btn-approve btn-small" onclick="approveDraft(${d.id})">✅ Approve</button>
          ` : `
            <button class="btn btn-secondary btn-small" style="color:#bee3f8" onclick="markPublished(${d.id})">🚀 Mark Published</button>
          `}
          <button class="btn btn-danger btn-small" onclick="deleteDraft(${d.id})">Delete</button>
        </div>

        <div class="composer-links">
          ${d.platform === 'X' ? '<a href="https://x.com/compose/post" target="_blank" class="nav-btn">Open X Composer ↗</a>' : ''}
          ${d.platform === 'LinkedIn' ? '<a href="https://www.linkedin.com/feed/" target="_blank" class="nav-btn">Open LinkedIn ↗</a>' : ''}
        </div>
      </div>
    `;
  }).join('');
}

function copyDraftText(id) {
  const d = (window._drafts || {})[id];
  if (d && d.body) copyText(d.body);
}

function copyPromptText(id) {
  const d = (window._drafts || {})[id];
  if (d && d.image_prompt) copyText(d.image_prompt);
}

async function approveDraft(id) {
  await fetch(`/api/drafts/${id}/approve`, {method: 'POST'});
  loadDrafts();
}

async function markPublished(id) {
  await fetch(`/api/drafts/${id}/publish`, {method: 'POST'});
  loadDrafts();
}

async function deleteDraft(id) {
  if (!confirm('Are you sure you want to delete this draft?')) return;
  await fetch(`/api/drafts/${id}`, {method: 'DELETE'});
  loadDrafts();
}

function copyText(str) {
  navigator.clipboard.writeText(str).then(() => {
    alert('Copied to clipboard!');
  });
}

function downloadMarkdown(id) {
  window.location.href = `/api/export-markdown?id=${id}`;
}

function exportDraftsJson() {
  window.location.href = '/api/export';
}

function exportAllMarkdown() {
  window.location.href = '/api/export-all-markdown';
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// Initial bootstrap
loadStatus();
fetchFeed(document.getElementById('rssPreset').value);
loadDrafts();
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, raw: bytes, status: int = 200, content_type: str = "text/html; charset=utf-8", extra_headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline' 'unsafe-eval' https:; img-src 'self' data: https:;")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def send_json(self, data, status: int = 200, headers: dict | None = None) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send(raw, status=status, content_type="application/json; charset=utf-8", extra_headers=headers)

    def send_error_json(self, status: int, message: str) -> None:
        self.send_json({"error": message}, status=status)

    def _request_hostname(self) -> str:
        host_header = self.headers.get("Host", "").strip()
        if not host_header:
            return ""
        if host_header.startswith("["):
            end = host_header.find("]")
            return host_header[1:end].lower() if end != -1 else host_header.lower()
        return host_header.rsplit(":", 1)[0].strip().lower()

    def _check_host(self) -> None:
        hostname = self._request_hostname()
        if not hostname or hostname not in ALLOWED_HOSTNAMES:
            raise ApiError(403, f"Forbidden: Host header {self.headers.get('Host')!r} is not permitted.")

    def _check_origin(self) -> None:
        origin = self.headers.get("Origin")
        if not origin:
            return
        parsed = urlparse(origin)
        if (parsed.hostname or "").lower() not in ALLOWED_HOSTNAMES:
            raise ApiError(403, f"Forbidden: cross-origin requests from {origin!r} are not allowed.")

    def do_GET(self):
        try:
            self._check_host()
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)

            if path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return

            if path == "/":
                self._send(HTML.encode("utf-8"))
                return

            if path == "/api/status":
                self.send_json({"database": str(DB_PATH), "ollama": ollama_info()})
                return

            if path == "/api/providers":
                self.send_json(get_available_providers())
                return

            if path == "/api/intake":
                feed_url = query.get("url", ["https://news.ycombinator.com/rss"])[0]
                try:
                    stories = fetch_rss_feed(feed_url)
                    self.send_json(stories)
                except Exception as exc:
                    self.send_error_json(500, str(exc))
                return

            if path == "/api/drafts":
                with db() as conn:
                    rows = [dict(r) for r in conn.execute("SELECT * FROM drafts ORDER BY updated_at DESC, id DESC")]
                self.send_json(rows)
                return

            if path == "/api/content-items":
                with db() as conn:
                    rows = [dict(r) for r in conn.execute("SELECT * FROM content_items ORDER BY updated_at DESC")]
                self.send_json(rows)
                return

            if path == "/api/sources":
                with db() as conn:
                    rows = [dict(r) for r in conn.execute("SELECT * FROM sources ORDER BY retrieved_at DESC")]
                self.send_json(rows)
                return

            if path == "/api/claims":
                with db() as conn:
                    rows = [dict(r) for r in conn.execute("SELECT * FROM claims ORDER BY id DESC")]
                self.send_json(rows)
                return

            if path == "/api/export":
                with db() as conn:
                    rows = [dict(r) for r in conn.execute("SELECT * FROM drafts ORDER BY id")]
                raw = json.dumps({"exported_at": now_iso(), "drafts": rows}, ensure_ascii=False, indent=2).encode("utf-8")
                self._send(raw, content_type="application/json; charset=utf-8",
                           extra_headers={"Content-Disposition": 'attachment; filename="contentos-drafts-export.json"'})
                return

            if path == "/api/export-markdown":
                draft_id = query.get("id", [""])[0]
                with db() as conn:
                    cur = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,))
                    row = cur.fetchone()
                if not row:
                    self.send_error_json(404, "Draft not found")
                    return
                d = dict(row)
                md = f"---\ntitle: \"{d['title']}\"\nplatform: \"{d['platform']}\"\nstatus: \"{d['status']}\"\ncreated_at: \"{d['created_at']}\"\n---\n\n# {d['title']}\n\n{d['body']}\n\n---\n### Visual Prompt Brief\n{d['image_prompt']}\n"
                raw = md.encode("utf-8")
                filename = f"draft_{d['id']}_{d['platform'].lower()}.md"
                self._send(raw, content_type="text/markdown; charset=utf-8",
                           extra_headers={"Content-Disposition": f'attachment; filename="{filename}"'})
                return

            if path == "/api/export-all-markdown":
                with db() as conn:
                    rows = [dict(r) for r in conn.execute("SELECT * FROM drafts ORDER BY id")]
                blocks = [f"## {d['title']} ({d['platform']}) - {d['status']}\n\n{d['body']}\n\n**Image Brief:** {d['image_prompt']}\n\n---\n" for d in rows]
                raw = ("# JustMeMedia ContentOS Export\n\n" + "\n".join(blocks)).encode("utf-8")
                self._send(raw, content_type="text/markdown; charset=utf-8",
                           extra_headers={"Content-Disposition": 'attachment; filename="all_contentos_drafts.md"'})
                return

            self.send_error_json(404, "Not found")

        except ApiError as err:
            self.send_error_json(err.status, err.message)
        except Exception:
            self.send_error_json(500, "Internal server error")

    def do_POST(self):
        try:
            self._check_host()
            self._check_origin()
            parsed = urlparse(self.path)
            path = parsed.path

            # Approve draft
            if path.startswith("/api/drafts/") and path.endswith("/approve"):
                draft_id = path.split("/")[3]
                stamp = now_iso()
                with db() as conn:
                    conn.execute("UPDATE drafts SET status = 'Approved', updated_at = ? WHERE id = ?", (stamp, draft_id))
                    conn.execute("INSERT INTO approvals(draft_id, approved_at, platform, notes) VALUES(?,?,?,?)",
                                 (draft_id, stamp, "General", "Approved by human user"))
                self.send_json({"ok": True, "status": "Approved"})
                return

            # Mark draft published
            if path.startswith("/api/drafts/") and path.endswith("/publish"):
                draft_id = path.split("/")[3]
                stamp = now_iso()
                with db() as conn:
                    conn.execute("UPDATE drafts SET status = 'Published', updated_at = ? WHERE id = ?", (stamp, draft_id))
                self.send_json({"ok": True, "status": "Published"})
                return

            # Read request body
            length_hdr = self.headers.get("Content-Length")
            if length_hdr is None:
                raise ApiError(411, "Length Required: Content-Length header is mandatory.")
            try:
                length = int(length_hdr)
            except ValueError:
                raise ApiError(400, f"Invalid Content-Length: {length_hdr!r}.") from None

            if length < 0:
                raise ApiError(400, "Content-Length must be non-negative.")
            if length > MAX_BODY_BYTES:
                raise ApiError(413, f"Payload Too Large: {length} bytes exceeds {MAX_BODY_BYTES} byte limit.")

            raw_body = self.rfile.read(length)
            if len(raw_body) != length:
                raise ApiError(400, "Client closed connection before sending the full payload.")

            try:
                payload = json.loads(raw_body.decode("utf-8")) if length > 0 else {}
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ApiError(400, f"Malformed JSON: {exc}.") from None

            if not isinstance(payload, dict):
                raise ApiError(400, "JSON payload must be an object.")

            # AI Generation
            if path == "/api/generate":
                task = payload.get("task", "draft_post")
                title = payload.get("title", "")
                context = payload.get("context", "")
                platform = payload.get("platform", "LinkedIn")
                provider = payload.get("provider", "ollama")

                system_prompt = (
                    "You are the JustMeMedia Content Engine. Brand voice: professional, credible, "
                    "technology-focused, direct, practical, informed, zero hype. Never invent customer "
                    "claims or fake metrics. Clearly format for the target platform."
                )

                if task == "draft_post":
                    user_prompt = (
                        f"Write a high-engagement, brand-aligned post for {platform}.\n"
                        f"Topic/Title: {title}\n"
                        f"Context/Source facts: {context}\n\n"
                        "Formatting guidelines:\n"
                        "- LinkedIn: Strong hook line, clean double line breaks, bullet points, CTA question, 3-5 hashtags.\n"
                        "- X: Punchy 280-character maximum hook, high-signal, 2-3 hashtags.\n"
                        "- Instagram/Threads: Story hook, clear spacing, engaging question.\n"
                        "- YouTube: Catchy title, 2-paragraph description with keywords.\n\n"
                        "Return ONLY the post content."
                    )
                    draft_text = call_ai(provider, user_prompt, system_prompt)
                    img_prompt_request = (
                        f"Create a photorealistic, modern visual prompt to accompany this post for JustMeMedia.\n"
                        f"Post context: {title} - {draft_text[:200]}\n"
                        "Color palette: dark aesthetic, emerald/forest green accents, clean tech styling.\n"
                        "Return ONLY a 1-2 sentence prompt suitable for Midjourney, FLUX, Gemini, or Grok."
                    )
                    image_prompt = call_ai(provider, img_prompt_request, "You are a creative visual art director.")
                    self.send_json({"ok": True, "result": draft_text, "image_prompt": image_prompt})
                    return

                elif task == "image_prompt":
                    img_prompt_request = (
                        f"Create a photorealistic, modern visual prompt to accompany this post for JustMeMedia.\n"
                        f"Title: {title}\n"
                        f"Content: {context[:250]}\n"
                        "Color palette: dark aesthetic, emerald/forest green accents, clean tech styling.\n"
                        "Return ONLY a 1-2 sentence prompt suitable for Midjourney, FLUX, Gemini, or Grok."
                    )
                    image_prompt = call_ai(provider, img_prompt_request, "You are a creative visual art director.")
                    self.send_json({"ok": True, "result": image_prompt})
                    return

            # Save draft
            if path == "/api/drafts":
                title = string_field(payload, "title")
                if not title:
                    raise ApiError(400, "Title is required and cannot be empty.")
                body = string_field(payload, "body")
                platform = string_field(payload, "platform") or "General"
                image_prompt = string_field(payload, "image_prompt")
                source_url = string_field(payload, "source_url")
                stamp = now_iso()
                with db() as conn:
                    cur = conn.execute(
                        """INSERT INTO drafts(title, body, platform, status, image_prompt, source_url, created_at, updated_at)
                           VALUES(?,?,?,?,?,?,?,?)""",
                        (title[:200], body, platform[:40], "Draft", image_prompt, source_url, stamp, stamp)
                    )
                    draft_id = cur.lastrowid
                self.send_json({"ok": True, "id": draft_id}, 201)
                return

            # Save content items
            if path == "/api/content-items":
                item_id = string_field(payload, "id") or f"ci_{now_iso()[:10]}_{os.urandom(3).hex()}"
                title = string_field(payload, "title")
                if not title:
                    raise ApiError(400, "Title is required.")
                stamp = now_iso()
                with db() as conn:
                    conn.execute(
                        "INSERT INTO content_items(id, title, pillar, status, audience, objective, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
                        (item_id, title, string_field(payload, "pillar"), "IDEA", string_field(payload, "audience"), string_field(payload, "objective"), stamp, stamp)
                    )
                self.send_json({"ok": True, "id": item_id}, 201)
                return

            # Save sources
            if path == "/api/sources":
                src_id = string_field(payload, "id") or f"src_{os.urandom(4).hex()}"
                url = string_field(payload, "url")
                title = string_field(payload, "title")
                if not title:
                    raise ApiError(400, "Title is required.")
                stamp = now_iso()
                with db() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO sources(id, url, title, publisher, retrieved_at, raw_text, summary) VALUES(?,?,?,?,?,?,?)",
                        (src_id, url, title, string_field(payload, "publisher"), stamp, string_field(payload, "raw_text"), string_field(payload, "summary"))
                    )
                self.send_json({"ok": True, "id": src_id}, 201)
                return

            self.send_error_json(404, "Not found")

        except ApiError as err:
            self.send_error_json(err.status, err.message)
        except Exception:
            self.send_error_json(500, "Internal server error")

    def do_DELETE(self):
        try:
            self._check_host()
            self._check_origin()
            parsed = urlparse(self.path)
            path = parsed.path
            if path.startswith("/api/drafts/"):
                draft_id = path.split("/")[3]
                with db() as conn:
                    conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
                self.send_json({"ok": True})
                return
            self.send_error_json(404, "Not found")
        except ApiError as err:
            self.send_error_json(err.status, err.message)
        except Exception:
            self.send_error_json(500, "Internal server error")

    def log_message(self, fmt, *args):
        print("[ContentOS] " + (fmt % args))


def main():
    connect_db().close()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print("============================================================")
    print(f"  JustMeMedia ContentOS Running at http://{HOST}:{PORT}")
    print(f"  Local Database: {DB_PATH}")
    print("  Host Guard: Active (127.0.0.1, localhost only)")
    print("============================================================")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping ContentOS...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
