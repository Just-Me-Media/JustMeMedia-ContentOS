#!/usr/bin/env python3
"""JustMeMedia ContentOS - Local-First Content Engine & Publishing Hub.

Zero third-party dependencies (Python standard library only).
Stores SQLite database in OS application-data directory (never in cloud/git sync).
Dual-host compatible: Windows (ThinkCentre) and macOS (M1 Pro).
"""
from __future__ import annotations

import base64
import json
import os
import random
import re
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from html.parser import HTMLParser
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


def _configure_stdio() -> None:
    """Make stdout/stderr tolerate non-ASCII on legacy Windows consoles.

    Windows consoles often default to cp1252, which cannot encode emoji used in
    scheduler and status messages. Without this, a ``print`` raises
    ``UnicodeEncodeError`` and can abort notification logic before it runs.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


_configure_stdio()


def _load_env_fallback() -> None:
    """Auto-load API keys from shell profile or secure keys if not in environment."""
    candidates = [
        Path.home() / ".secure_keys" / ".env",
        Path.home() / ".zshrc",
        Path.home() / ".bashrc",
        Path.home() / ".profile",
    ]
    for p in candidates:
        if p.exists():
            try:
                for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if line.startswith("export GROQ_API_KEY=") and not os.environ.get("GROQ_API_KEY"):
                        val = line.split("=", 1)[1].strip("\"' ")
                        if val:
                            os.environ["GROQ_API_KEY"] = val
                    elif line.startswith("export GEMINI_API_KEY=") and not os.environ.get("GEMINI_API_KEY"):
                        val = line.split("=", 1)[1].strip("\"' ")
                        if val:
                            os.environ["GEMINI_API_KEY"] = val
                    elif line.startswith("export DRAW_THINGS_API_KEY=") and not os.environ.get("DRAW_THINGS_API_KEY"):
                        val = line.split("=", 1)[1].strip("\"' ")
                        if val:
                            os.environ["DRAW_THINGS_API_KEY"] = val
                    elif line.startswith("export DRAW_THINGS_URL=") and not os.environ.get("DRAW_THINGS_URL"):
                        val = line.split("=", 1)[1].strip("\"' ")
                        if val:
                            os.environ["DRAW_THINGS_URL"] = val
            except Exception:
                pass


_load_env_fallback()


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
    if os.environ.get("CONTENTOS_DATA_DIR"):
        p = Path(os.environ["CONTENTOS_DATA_DIR"])
        p.mkdir(parents=True, exist_ok=True)
        return p

    candidates: list[Path] = []
    if sys.platform == "win32":
        candidates.append(Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / APP_NAME / PRODUCT_NAME)
    elif sys.platform == "darwin":
        candidates.append(Path.home() / "Library" / "Application Support" / APP_NAME / PRODUCT_NAME)
    
    candidates.append(Path.home() / f".{APP_NAME.lower()}" / PRODUCT_NAME.lower())
    candidates.append(Path(__file__).resolve().parent.parent / "data")

    for p in candidates:
        try:
            p.mkdir(parents=True, exist_ok=True)
            test_file = p / ".write_test"
            test_file.touch()
            test_file.unlink()
            return p
        except Exception:
            continue

    fallback = Path("/tmp") / APP_NAME / PRODUCT_NAME
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


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
            media_url TEXT NOT NULL DEFAULT '',
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
    if "media_url" not in cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN media_url TEXT NOT NULL DEFAULT ''")
    if "scheduled_for" not in cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN scheduled_for TEXT NOT NULL DEFAULT ''")
    if "live_url" not in cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN live_url TEXT NOT NULL DEFAULT ''")
    if "views" not in cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN views INTEGER NOT NULL DEFAULT 0")
    if "engagements" not in cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN engagements INTEGER NOT NULL DEFAULT 0")
    if "rejection_reason" not in cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN rejection_reason TEXT NOT NULL DEFAULT ''")

    # 2. Content items & versions (ThinkCentre relational schema)
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

    cur = conn.execute("PRAGMA table_info(sources)")
    cols = [row["name"] for row in cur.fetchall()]
    if "status" not in cols:
        conn.execute("ALTER TABLE sources ADD COLUMN status TEXT NOT NULL DEFAULT 'new'")

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


# ─────────────────────────────────────────────────────────────────────────────
# PHASE B: VIRAL HOOK LIBRARY + ANTI-SLOP FILTER
# ─────────────────────────────────────────────────────────────────────────────

VIRAL_HOOK_TEMPLATES = [
    "Most {industry} experts focus on {X}. The top 1% focus on {Y}.",
    "I analyzed {N} {things} so you don't have to. Here's what actually matters:",
    "Unpopular opinion: {contrarian_take}.",
    "Nobody talks about this {topic} problem. But it's costing businesses millions.",
    "The {industry} playbook everyone uses is broken. Here's what actually works:",
    "Stop doing {bad_practice}. Start doing {good_practice}.",
    "{Number} years from now, {prediction}. Here's the data showing why:",
    "Hot take: {bold_claim}. Here's my reasoning:",
    "The {tool/strategy} everyone ignores is the one that changes everything.",
    "If I were starting {endeavor} today, I'd do exactly {action}. Here's why:",
]

AI_SLOP_PATTERNS = re.compile(
    r"\b(delve|delving|tapestry|testament|revolutionize|revolutionizing|game.?changer|"
    r"game.?changing|unleash|unleashing|unprecedented|groundbreaking|leverage|leveraging|"
    r"spearhead|spearheading|synergies|synergy|paradigm|holistic|robust|utilize|utilizing|"
    r"scalable|scalability|transformative|innovative solutions|cutting.?edge solutions|"
    r"best.?in.?class|world.?class|state.?of.?the.?art|next.?generation|thought leader|"
    r"ecosystem|empower|empowering|foster|fostering|seamless|streamline|streamlining|"
    r"exciting opportunities|dive deep|deep dive|circle back|at the end of the day|"
    r"move the needle|low.?hanging fruit|boil the ocean|think outside the box|"
    r"value.?add|value proposition|bleeding edge|disruptive|disruptors|pivot|pivoting)\b",
    re.IGNORECASE
)

SLOP_REPLACEMENTS = {
    r"\bin today's (?:fast-paced|rapidly evolving|digital|modern) world\b": "today",
    r"\bin the modern era\b": "today",
    r"\bdelve\b": "explore", r"\bdelving\b": "exploring",
    r"\btapestry\b": "mix", r"\btestament\b": "proof",
    r"\bunprecedented\b": "new", r"\bgroundbreaking\b": "notable",
    r"\bleverag\w+\b": "use", r"\butiliz\w+\b": "use",
    r"\bsynergi\w+\b": "collaboration", r"\bholistic\b": "complete",
    r"\brobust\b": "strong", r"\bscalabl\w+\b": "scalable",
    r"\btransformative\b": "impactful", r"\bempow\w+\b": "enable",
    r"\bfost\w+\b": "build", r"\bseamless\b": "smooth",
    r"\bstreamlin\w+\b": "simplify", r"\bdisruptiv\w+\b": "new",
    r"\bdoors (?:just )?swung (?:wide )?open\b": "access is now available",
    r"\breshapes? (?:app )?discovery\b": "changes app discovery",
    r"\bgame-?chang(?:er|ing)\b": "significant update",
    r"\bseismic shift\b": "major shift",
    r"\bquantum leap\b": "major step",
    r"\bmind-?blowing\b": "impressive",
    r"\bunleash(?:ing)?\b": "releasing",
}


def strip_ai_slop(text: str) -> str:
    """Remove AI clichés and replace with cleaner alternatives."""
    result = text
    for pattern, replacement in SLOP_REPLACEMENTS.items():
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result


def inject_viral_hook(text: str, title: str) -> str:
    """Prepend a viral hook pattern if the post doesn't already have a strong opener."""
    first_line = text.split("\n")[0].strip()
    # Already has a strong hook if it starts with a question or bold statement
    if first_line.endswith("?") or first_line.startswith(("🔥", "⚡", "💡", "🚀", "❌", "✅")):
        return text
    # Choose a random hook template and inject
    hook = random.choice(VIRAL_HOOK_TEMPLATES[:5])
    # Simple fill with title keywords
    words = title.split()
    topic = " ".join(words[:3]) if words else "this"
    filled = hook.replace("{topic}", topic).replace("{industry}", "tech").replace(
        "{X}", "output").replace("{Y}", "systems").replace(
        "{N}", "100").replace("{things}", "examples").replace(
        "{contrarian_take}", f"{topic} needs rethinking").replace(
        "{Number}", "5").replace("{prediction}", "this changes everything").replace(
        "{bold_claim}", f"{topic} is fundamentally misunderstood").replace(
        "{tool/strategy}", topic).replace("{bad_practice}", "shortcuts").replace(
        "{good_practice}", "fundamentals").replace("{endeavor}", topic).replace(
        "{action}", "focus on the basics")
    return filled + "\n\n" + text


# ─────────────────────────────────────────────────────────────────────────────
# PHASE C: LOCAL IMAGE GENERATION (AUTOMATIC1111-COMPATIBLE API)
# ─────────────────────────────────────────────────────────────────────────────

# Capability layer: local image generation is opt-in and platform-aware.
# macOS defaults to Draw Things (Apple-only companion app); Windows defaults to
# "none" and uses the GIF fallback. Set IMAGE_BACKEND=a1111 to point a Windows
# machine at Forge/AUTOMATIC1111/SD.Next instead.
IMAGE_BACKEND = os.environ.get(
    "IMAGE_BACKEND",
    "drawthings" if sys.platform == "darwin" else "none",
).strip().lower()
if IMAGE_BACKEND not in ("none", "drawthings", "a1111"):
    IMAGE_BACKEND = "none"
LOCAL_IMAGE_ENABLED = IMAGE_BACKEND in ("drawthings", "a1111")
IMAGE_BACKEND_LABEL = {"drawthings": "Draw Things", "a1111": "Local Image API"}.get(IMAGE_BACKEND, "")

DRAW_THINGS_URL = os.environ.get("DRAW_THINGS_URL", "http://127.0.0.1:7860")
DRAW_THINGS_API_KEY = os.environ.get("DRAW_THINGS_API_KEY", "")
MEDIA_DIR = data_dir() / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)


def _draw_things_headers(extra: dict | None = None) -> dict:
    headers = {"Accept": "application/json"}
    key = os.environ.get("DRAW_THINGS_API_KEY", "") or DRAW_THINGS_API_KEY
    if key:
        headers["Authorization"] = f"Bearer {key}"
        headers["X-API-Key"] = key
    if extra:
        headers.update(extra)
    return headers


def draw_things_available() -> bool:
    """Check if the enabled local image backend is running."""
    if not LOCAL_IMAGE_ENABLED:
        return False
    try:
        url = os.environ.get("DRAW_THINGS_URL", DRAW_THINGS_URL).rstrip("/")
        req = urllib.request.Request(url + "/sdapi/v1/options",
                                     headers=_draw_things_headers())
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def generate_local_image(prompt: str, negative_prompt: str = "", width: int = 1024,
                          height: int = 576, steps: int = 20) -> dict:
    """Generate an image via Draw Things local HTTP API (AUTOMATIC1111-compatible).

    Returns {"ok": True, "filename": "...", "b64": "..."} on success,
            {"ok": False, "error": "..."} on failure.
    """
    if not LOCAL_IMAGE_ENABLED:
        return {"ok": False, "error": "Local image generation is disabled on this system (IMAGE_BACKEND=none). Falling back to GIF media."}
    if not draw_things_available():
        return {"ok": False, "error": f"Local image engine ({IMAGE_BACKEND_LABEL}) is not reachable. Start the local image server."}

    payload = {
        "prompt": prompt,
        "negative_prompt": negative_prompt or "blurry, low quality, watermark, text, logo, oversaturated",
        "width": width,
        "height": height,
        "steps": steps,
        "cfg_scale": 7.0,
        "seed": -1,
        "sampler_name": "DPM++ 2M Karras",
    }
    try:
        url = os.environ.get("DRAW_THINGS_URL", DRAW_THINGS_URL).rstrip("/")
        req = urllib.request.Request(
            url + "/sdapi/v1/txt2img",
            data=json.dumps(payload).encode("utf-8"),
            headers=_draw_things_headers({"Content-Type": "application/json"})
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        images = data.get("images", [])
        if not images:
            return {"ok": False, "error": f"{IMAGE_BACKEND_LABEL or 'Local image API'} returned no images."}

        b64_data = images[0]
        import base64
        filename = f"gen_{now_iso()[:19].replace(':', '-').replace('T', '_')}.png"
        filepath = MEDIA_DIR / filename
        filepath.write_bytes(base64.b64decode(b64_data))

        return {"ok": True, "filename": filename, "b64": b64_data}

    except urllib.error.URLError as exc:
        return {"ok": False, "error": f"Cannot connect to local image engine ({IMAGE_BACKEND_LABEL}): {exc}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# PHASE E: WEBHOOK DISPATCHER
# ─────────────────────────────────────────────────────────────────────────────

def send_webhook(webhook_url: str, payload: dict) -> dict:
    """Send a JSON payload to any webhook URL (Discord, Slack, Zapier, Make, n8n)."""
    if not webhook_url or not webhook_url.startswith("http"):
        return {"ok": False, "error": "Invalid webhook URL"}
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "JustMeMediaContentOS/2.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            body = resp.read().decode("utf-8", errors="ignore")
        return {"ok": True, "status": status, "response": body[:200]}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        return {"ok": False, "error": f"HTTP {exc.code}: {body[:200]}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def build_discord_payload(draft: dict) -> dict:
    """Format a draft as a Discord embed message."""
    platform_colors = {"LinkedIn": 0x0A66C2, "X": 0x000000, "Instagram": 0xE1306C,
                        "YouTube": 0xFF0000, "General": 0x48bb78}
    color = platform_colors.get(draft.get("platform", "General"), 0x48bb78)
    body_preview = (draft.get("body", "") or "")[:900]
    if len(draft.get("body", "")) > 900:
        body_preview += "..."

    embed = {
        "title": f"📝 New Draft: {draft.get('title', 'Untitled')[:200]}",
        "description": body_preview,
        "color": color,
        "fields": [
            {"name": "Platform", "value": draft.get("platform", "General"), "inline": True},
            {"name": "Status", "value": draft.get("status", "Draft"), "inline": True},
            {"name": "Created", "value": (draft.get("created_at", "") or "")[:10], "inline": True},
        ],
        "footer": {"text": "JustMeMedia ContentOS · Approve at http://127.0.0.1:8765"}
    }
    if draft.get("image_prompt"):
        embed["fields"].append({"name": "🎨 Visual Brief", "value": draft["image_prompt"][:200], "inline": False})

    return {"embeds": [embed]}


def build_slack_payload(draft: dict) -> dict:
    """Format a draft as a Slack block message."""
    body_preview = (draft.get("body", "") or "")[:700]
    return {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": f"📝 New Draft Ready: {draft.get('title', '')[:60]}"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": body_preview}},
            {"type": "context", "elements": [
                {"type": "mrkdwn", "text": f"*Platform:* {draft.get('platform', 'General')} | *Status:* {draft.get('status', 'Draft')} | <http://127.0.0.1:8765|Open ContentOS>"}
            ]}
        ]
    }


def get_webhook_config() -> dict:
    """Load webhook URLs from environment or config file."""
    config_file = data_dir() / "webhooks.json"
    config = {}
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    # Env vars override file config
    if os.environ.get("DISCORD_WEBHOOK_URL"):
        config["discord"] = os.environ["DISCORD_WEBHOOK_URL"]
    if os.environ.get("SLACK_WEBHOOK_URL"):
        config["slack"] = os.environ["SLACK_WEBHOOK_URL"]
    if os.environ.get("CUSTOM_WEBHOOK_URL"):
        config["custom"] = os.environ["CUSTOM_WEBHOOK_URL"]
    return config


def save_webhook_config(config: dict) -> None:
    """Persist webhook URLs to local config file."""
    config_file = data_dir() / "webhooks.json"
    config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")


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
    # Fast cloud providers first so the default dropdown selection is ultra-fast
    if os.environ.get("GROQ_API_KEY"):
        providers.append({"id": "groq:openai/gpt-oss-120b", "name": "⚡ Groq Cloud: GPT-OSS 120B (Frontier & Ultra-Fast)", "type": "cloud"})
        providers.append({"id": "groq:qwen/qwen3.8-27b", "name": "⚡ Groq Cloud: Qwen 3.8 27B (High-Speed)", "type": "cloud"})

    if os.environ.get("GEMINI_API_KEY"):
        providers.append({"id": "gemini:gemini-3.8-flash", "name": "✨ Google Gemini 3.8 Flash (Cloud)", "type": "cloud"})

    ollama = ollama_info()
    if ollama.get("available"):
        for m in ollama.get("models", []):
            providers.append({"id": f"ollama:{m}", "name": f"🖥️ Local Ollama: {m}", "type": "local"})

    if not providers:
        providers.append({"id": "none", "name": "No AI Providers Detected (Manual Mode)", "type": "none"})

    return {
        "providers": providers,
        "ollama": ollama,
        "has_groq": bool(os.environ.get("GROQ_API_KEY")),
        "has_gemini": bool(os.environ.get("GEMINI_API_KEY"))
    }


def call_ai(provider_id: str, prompt: str, system_prompt: str = "") -> str:
    # If empty or none, select best available provider
    if not provider_id or provider_id in ("auto", "none"):
        if os.environ.get("GROQ_API_KEY"):
            provider_id = "groq:openai/gpt-oss-120b"
        elif os.environ.get("GEMINI_API_KEY"):
            provider_id = "gemini:gemini-3.8-flash"
        else:
            info = ollama_info()
            if info.get("available") and info.get("models"):
                provider_id = f"ollama:{info['models'][0]}"
            else:
                raise ValueError("No AI provider available. Set GROQ_API_KEY, GEMINI_API_KEY, or run Ollama locally.")

    if provider_id.startswith("ollama:"):
        model_name = provider_id.split(":", 1)[1]
        url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/generate"
        payload = {
            "model": model_name,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False
        }
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                raw_resp = data.get("response", "").strip()
                clean_resp = re.sub(r"<think>.*?</think>", "", raw_resp, flags=re.DOTALL).strip()
                return clean_resp if clean_resp else raw_resp
        except TimeoutError:
            raise RuntimeError(f"Local Ollama model '{model_name}' timed out after 180s. Try selecting Groq Cloud or a smaller model.") from None
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Local Ollama model '{model_name}' failed to connect. Is Ollama running? ({exc})") from exc

    elif provider_id.startswith("groq:"):
        api_key = os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            raise ValueError("GROQ_API_KEY is not set. Add it to ~/.zshrc or your environment.")
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
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) JustMeMediaContentOS/1.0"
        }
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")
            if exc.code == 429:
                # Groq free-tier tokens-per-minute throttle: dynamically parse wait time and retry
                wait_sec = 6.0
                match = re.search(r"try again in ([0-9.]+)s", err_body)
                if match:
                    wait_sec = float(match.group(1)) + 0.5
                time.sleep(wait_sec)
                try:
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        return data["choices"][0]["message"]["content"].strip()
                except Exception:
                    pass
            raise RuntimeError(f"Groq API Error {exc.code}: {err_body}") from exc

    elif provider_id.startswith("gemini:"):
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set. Add it to ~/.zshrc or your environment.")
        model_name = provider_id.split(":", 1)[1]
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        full_text = f"{system_prompt}\n\nTask: {prompt}" if system_prompt else prompt
        payload = {
            "contents": [{"parts": [{"text": full_text}]}]
        }
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except urllib.error.HTTPError as exc:
            err_msg = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Google Gemini API Error {exc.code}: {err_msg}") from exc

    raise ValueError(f"Unknown or unsupported provider: {provider_id}")


class CleanTextExtractor(HTMLParser):
    def __init__(self, base_url: str = ""):
        super().__init__()
        self.base_url = base_url
        self.texts = []
        self.links = []
        self.curr_link = None
        self.skip = False

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t in ("script", "style", "nav", "footer", "header", "noscript", "svg", "aside"):
            self.skip = True
        elif t == "a" and not self.skip:
            attr_dict = dict(attrs)
            href = attr_dict.get("href", "").strip()
            if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
                full_url = urllib.parse.urljoin(self.base_url, href) if self.base_url else href
                self.curr_link = {"href": full_url, "text": ""}

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in ("script", "style", "nav", "footer", "header", "noscript", "svg", "aside"):
            self.skip = False
        elif t == "a" and self.curr_link:
            text = self.curr_link["text"].strip()
            href = self.curr_link["href"]
            # Filter out social share icons, terms, privacy, cookie noise
            ignore_keywords = ("privacy", "terms", "cookie", "wechat", "bilibili", "youtube", "linkedin.com/showcase", "agreements", "guidelines", "sign in", "login")
            if len(text) >= 3 and not any(k in text.lower() or k in href.lower() for k in ignore_keywords):
                if not any(l["href"] == href for l in self.links):
                    self.links.append({"text": text, "href": href})
            self.curr_link = None

    def handle_data(self, data):
        if not self.skip:
            s = data.strip()
            if len(s) > 20:
                self.texts.append(s)
            if self.curr_link is not None and s:
                self.curr_link["text"] = (self.curr_link["text"] + " " + s).strip()

    def get_text(self) -> str:
        body = "\n\n".join(self.texts)
        if self.links:
            # Curate top actionable resource links (apply, learn more, docs)
            link_lines = [f"• {l['text']}: {l['href']}" for l in self.links[:4]]
            body += "\n\nActionable Resource & Application Links Found in Source:\n" + "\n".join(link_lines)
        return body


def extract_article_text(url: str, max_chars: int = 4000) -> str:
    """Zero-dependency scraper: fetches full article text and actionable links."""
    if not url or not url.startswith("http"):
        return ""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read(300_000)
            encoding = resp.headers.get_content_charset() or "utf-8"
            html_text = raw.decode(encoding, errors="replace")
        parser = CleanTextExtractor(base_url=url)
        parser.feed(html_text)
        text = parser.get_text()
        return text[:max_chars] if text else ""
    except Exception as exc:
        return f"(Could not scrape full article body: {exc})"



def verify_link_alive(link_url: str, timeout: float = 2.5) -> bool:
    """Verifies that an external link returns an HTTP 2xx or 3xx status code."""
    if not link_url or not link_url.startswith(("http://", "https://")):
        return False
    try:
        req = urllib.request.Request(
            link_url,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
            method="HEAD"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except Exception:
        try:
            req = urllib.request.Request(
                link_url,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return 200 <= resp.status < 400
        except Exception:
            return False


def deep_research_story(url: str, title: str, snippet: str = "") -> dict:
    """Agent 0: The Deep Investigator.
    
    1. Extracts primary article text and gathers outbound resource links.
    2. Verifies link health (HTTP 200 OK) so dead links never enter a post.
    3. Identifies high-value sub-links (documentation, portals, github repos) and shallow-scrapes them.
    4. Compiles a rich Research Dossier with verified live links and publisher credit.
    """
    primary_text = extract_article_text(url) if url else snippet or title
    
    # Identify publisher attribution
    publisher = "Official Source"
    if url:
        domain = urllib.parse.urlparse(url).netloc.replace("www.", "")
        known_publishers = {
            "developer.apple.com": "Apple Developer News",
            "apple.com": "Apple Newsroom",
            "openai.com": "OpenAI",
            "techcrunch.com": "TechCrunch",
            "arstechnica.com": "Ars Technica",
            "technologyreview.com": "MIT Technology Review",
            "blog.google": "Google",
            "ai.googleblog.com": "Google AI",
            "news.ycombinator.com": "Hacker News",
            "deepseek.com": "DeepSeek",
            "x.ai": "xAI"
        }
        publisher = known_publishers.get(domain, domain)
    
    # Extract links from primary page
    links = []
    if url:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                raw = resp.read(250_000)
                parser = CleanTextExtractor(base_url=url)
                parser.feed(raw.decode(resp.headers.get_content_charset() or "utf-8", errors="replace"))
                links = parser.links
        except Exception:
            pass

    # Verify link health: only keep live links (HTTP 200 OK)
    verified_links = []
    for l in links[:12]:
        if verify_link_alive(l["href"]):
            verified_links.append(l)
        if len(verified_links) >= 6:
            break

    # Find high-value sub-links for secondary research
    sub_research_notes = []
    valuable_keywords = ("apply", "student", "challenge", "docs", "documentation", "guide", "learn", "github", "portal", "register", "api")
    researched_count = 0
    for l in (verified_links or links):
        t_low = l["text"].lower()
        h_low = l["href"].lower()
        if any(k in t_low or k in h_low for k in valuable_keywords) and researched_count < 2:
            try:
                sub_text = extract_article_text(l["href"], max_chars=1200)
                if sub_text and len(sub_text) > 100 and not sub_text.startswith("("):
                    sub_research_notes.append(f"--- Sub-Research from [{l['text']}] ({l['href']}) ---\n{sub_text[:800]}")
                    researched_count += 1
            except Exception:
                pass

    # Compile the Research Dossier
    dossier = f"=== SOURCE ARTICLE ({publisher}) ===\n" + primary_text
    if sub_research_notes:
        dossier += "\n\n=== DEEP INVESTIGATION SUB-FINDINGS ===\n" + "\n\n".join(sub_research_notes)
    
    if verified_links:
        dossier += "\n\n=== VERIFIED RESOURCE & ACTION LINKS (HTTP 200 OK) ===\n"
        for l in verified_links[:6]:
            dossier += f"• {l['text']}: {l['href']}\n"
    elif url:
        dossier += f"\n\n=== PRIMARY SOURCE ===\n• Official Announcement ({publisher}): {url}\n"

    return {
        "title": title,
        "source_url": url,
        "publisher": publisher,
        "dossier": dossier,
        "links": verified_links[:6] if verified_links else links[:6]
    }


def run_roundtable(provider_id: str, title: str, context: str, platform: str, tone: str = "thought_leadership", source_url: str = "") -> dict:
    """3-Agent Consensus Pipeline: Drafter -> Fact-Checker -> Hook/Format Optimizer -> Art Director."""
    tone_directives = {
        "thought_leadership": "Style: Authoritative, strategic, data-informed industry insights. Highlight future implications.",
        "viral_story": "Style: Compelling narrative hook, strong pattern interrupt, punchy 1-line pacing, relatable takeaway.",
        "technical_deep_dive": "Style: High engineering rigor, architectural mechanics, technical trade-offs, code/system level precision.",
        "contrarian": "Style: Direct challenge to prevailing conventional wisdom, bold thesis, grounded defense, stimulates thoughtful debate."
    }
    tone_instruction = tone_directives.get(tone, tone_directives["thought_leadership"])

    is_x = platform.lower() in ("x", "twitter")

    # Agent 1: Drafter
    drafter_sys = (
        f"You are Agent 1 (The Drafter) for JustMeMedia. Brand voice: credible, practical, informed, zero hype.\n"
        f"{tone_instruction}"
    )
    if is_x:
        draft_prompt = (
            f"Draft a punchy single post for X (Twitter).\n"
            f"Topic: {title}\n"
            f"Verified facts: {context[:800]}\n"
            f"Source link: {source_url}\n\n"
            f"CRITICAL CONSTRAINT - CHARACTER BUDGET:\n"
            f"- MUST BE STRICTLY UNDER 250 CHARACTERS TOTAL. This is a single tweet.\n"
            f"- 1 compelling hook sentence, 1 key insight, 1 link: {source_url}, and 1-2 hashtags.\n"
            f"- NO markdown headers. NO bullet points. NO multi-paragraph walls of text.\n"
            f"- Return ONLY the tweet text under 250 characters."
        )
    else:
        draft_prompt = (
            f"Draft an engaging, high-signal post for {platform}.\n"
            f"Topic: {title}\n"
            f"Verified facts & source text: {context}\n"
            f"Source URL: {source_url}\n\n"
            f"MANDATORY RESOURCE & APPLICATION LINK:\n"
            f"Always provide an actionable link near the end of the post so readers can learn more, read documentation, or apply directly.\n"
            f"If a specific application/learn-more URL is mentioned in the source facts above, feature it directly.\n"
            f"Otherwise, link the official announcement: {source_url}\n"
            f"Format the link cleanly as '🔗 Learn more / Apply here: <URL>' or '🔗 Official Announcement: <URL>'.\n"
            f"Format strictly for {platform} with double line breaks and clear headers/bullet points."
        )
    initial_draft = call_ai(provider_id, draft_prompt, drafter_sys)
    time.sleep(1.0)

    # Agent 2: Fact-Checker & Anti-Hype Guard
    checker_sys = (
        "You are Agent 2 (The Fact-Checker & Anti-Hype Guard) for JustMeMedia. "
        "Your job is to verify claims against the provided source facts. "
        "Strip out all overclaiming hyperbole ('doors swung wide open', 'reshapes app discovery', 'game-changer', 'delve', 'unleash', 'testament'). "
        "Ensure version numbers, beta labels, and publisher attributions are accurate. No fake customer stories or invented metrics."
    )
    check_prompt = (
        f"Review and refine this draft based strictly on the source facts.\n"
        f"Source Facts: {context[:1800]}\n"
        f"Draft to critique and refine:\n{initial_draft}\n\n"
        "Return the refined, grounded, fact-checked post directly."
    )
    fact_checked_draft = call_ai(provider_id, check_prompt, checker_sys)
    time.sleep(1.0)

    # Agent 3: Social Hook & Formatting Optimizer
    hook_sys = (
        f"You are Agent 3 (The Social Media Strategist). Brand: JustMeMedia.\n"
        f"Your job is to craft a magnetic first line (hook), ensure optimal spacing for mobile reading, "
        f"and append an engaging closing question plus relevant hashtags.\n"
        f"{tone_instruction}"
    )
    if is_x:
        hook_prompt = (
            f"Refine this draft for X (Twitter) to maximize impact and ensure it fits in a single tweet:\n{fact_checked_draft}\n\n"
            f"CRITICAL: Final output MUST BE STRICTLY UNDER 260 CHARACTERS including the link and hashtags.\n"
            f"NO multi-paragraph text. Return ONLY the tweet text."
        )
    else:
        hook_prompt = (
            f"Take this fact-checked draft for {platform} and maximize its reader engagement.\n"
            f"Draft:\n{fact_checked_draft}\n\n"
            f"Ensure there is a clear, actionable resource link at the end (e.g. '🔗 Learn more / Apply here: ...') so readers can click through.\n"
            f"Target platform: {platform}.\n"
            "Return ONLY the final, ready-to-post text."
        )
    final_post_raw = call_ai(provider_id, hook_prompt, hook_sys)
    time.sleep(1.0)

    # Phase B: Apply Anti-Slop filter + Platform formatters
    final_post_clean = strip_ai_slop(final_post_raw)
    if is_x:
        final_post = format_for_x(final_post_clean)
    else:
        final_post = inject_viral_hook(final_post_clean, title)
        if platform.lower() == "linkedin":
            final_post = format_for_linkedin(final_post)

    # Agent 4: Art Director (Image prompt)
    art_sys = (
        "You are an elite Visual Art Director creating photorealistic, modern conceptual artwork. "
        "CRITICAL RULE: NEVER prompt generic stock photos of people staring at laptop screens or sitting in offices. "
        "Always focus on sleek conceptual technology, system architecture, holographic schematics, or clean hardware."
    )
    art_prompt = (
        f"Generate a visual prompt for FLUX/Draw Things to illustrate this tech story.\n"
        f"Topic: {title}\n"
        f"Key facts: {final_post[:250]}\n"
        "Visual style: sleek dark-mode system architecture diagram, holographic UI schematics, glowing system nodes, "
        "minimalist hardware/silicon macro concept, or abstract technological blueprint.\n"
        "Lighting: cinematic studio lighting, dark obsidian palette with vivid emerald-green and cyan accents, 8k photorealistic concept render.\n"
        "Return ONLY the 1-2 sentence image prompt."
    )
    image_prompt = call_ai(provider_id, art_prompt, art_sys)

    return {
        "final_post": final_post,
        "image_prompt": image_prompt,
        "roundtable_log": f"Agent 1 (Drafter - {tone}) ➔ Agent 2 (Fact-Checker) ➔ Agent 3 (Hook+AntiSlop) ➔ Agent 4 (Art Director)"
    }


def calculate_next_optimal_slot() -> str:
    """Calculates the next optimal social posting slot (09:00, 14:00, or 18:30)."""
    now = datetime.now()
    today_9am = now.replace(hour=9, minute=0, second=0, microsecond=0)
    today_2pm = now.replace(hour=14, minute=0, second=0, microsecond=0)
    today_630pm = now.replace(hour=18, minute=30, second=0, microsecond=0)

    if now < today_9am:
        target = today_9am
    elif now < today_2pm:
        target = today_2pm
    elif now < today_630pm:
        target = today_630pm
    else:
        from datetime import timedelta
        target = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)

    return target.strftime("%Y-%m-%d %H:%M")

_NOTIFIED_SCHEDULED_DRAFTS: set[int] = set()

def check_scheduled_drafts() -> list[dict]:
    """Background check for drafts that have reached their scheduled time slot."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    notified = []
    try:
        with db() as conn:
            cur = conn.execute(
                """SELECT id, title, platform, scheduled_for, status 
                   FROM drafts 
                   WHERE scheduled_for != '' 
                     AND scheduled_for <= ? 
                     AND status IN ('Draft', 'Approved')""",
                (now_str,)
            )
            rows = [dict(r) for r in cur.fetchall()]
        
        for r in rows:
            draft_id = r["id"]
            if draft_id not in _NOTIFIED_SCHEDULED_DRAFTS:
                _NOTIFIED_SCHEDULED_DRAFTS.add(draft_id)
                notified.append(r)
                msg = f"Time to publish '{r['title'][:40]}' on {r['platform']}! (Scheduled for {r['scheduled_for']})"
                print(f"[ContentOS Scheduler] Time to publish: {msg}")
                # 1. Native Mac Desktop Notification
                if sys.platform == "darwin":
                    try:
                        safe_title = r['title'][:40].replace('"', '\"').replace("'", "")
                        safe_msg = f"Scheduled for {r['platform']} ({r['scheduled_for']})".replace('"', '\"').replace("'", "")
                        subprocess.run(
                            ["osascript", "-e", f'display notification "{safe_msg}" with title "ContentOS: Time to Post!" subtitle "{safe_title}" sound name "Glass"'],
                            capture_output=True, timeout=2
                        )
                    except Exception:
                        pass
                # 2. Webhook notification if configured
                try:
                    cfg = get_webhook_config()
                    alert_draft = {
                        "title": f"⏰ Time to Post: {r['title']}",
                        "body": f"This post was scheduled for {r['scheduled_for']} on {r['platform']}. Open ContentOS to publish!",
                        "platform": r["platform"],
                        "status": r["status"]
                    }
                    if cfg.get("discord"):
                        send_webhook(cfg["discord"], build_discord_payload(alert_draft))
                    if cfg.get("slack"):
                        send_webhook(cfg["slack"], build_slack_payload(alert_draft))
                except Exception:
                    pass
    except Exception as e:
        print(f"[ContentOS Scheduler Error] {e}")
    return notified

def _scheduler_loop() -> None:
    while True:
        try:
            check_scheduled_drafts()
        except Exception:
            pass
        time.sleep(30)

def start_scheduler_daemon() -> None:
    t = threading.Thread(target=_scheduler_loop, daemon=True, name="ContentOS-Scheduler")
    t.start()


def format_as_thread(post_text: str, max_tweet_len: int = 270) -> list[str]:
    """Split a post into numbered tweet segments for X.
    Guarantees every single tweet in the list is strictly <= max_tweet_len (270 chars).
    """
    if not post_text:
        return []
    
    # Clean markdown headers and bold asterisks first
    cleaned_lines = []
    for line in post_text.split("\n"):
        s = line.strip()
        if s.startswith("### "):
            cleaned_lines.append(s[4:].replace("**", "").strip() + ":")
        elif s.startswith("**") and s.endswith("**") and len(s) > 4:
            cleaned_lines.append(s[2:-2].strip() + ":")
        else:
            cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
            cleaned = re.sub(r"(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)", r"\1", cleaned)
            cleaned_lines.append(cleaned)
    clean_text = "\n".join(cleaned_lines).strip()

    # Split into raw sentence chunks across paragraphs
    raw_blocks = [b.strip() for b in clean_text.split("\n\n") if b.strip()]
    sentences = []
    for block in raw_blocks:
        b_clean = re.sub(r"^\d+/\d+\s*", "", block).strip()
        s_list = re.split(r"(?<=[.!?])\s+", b_clean)
        for s in s_list:
            s_stripped = s.strip()
            if s_stripped:
                if len(s_stripped) > 180:
                    words = s_stripped.split()
                    cur = []
                    for w in words:
                        if len(" ".join(cur + [w])) > 180:
                            sentences.append(" ".join(cur))
                            cur = [w]
                        else:
                            cur.append(w)
                    if cur:
                        sentences.append(" ".join(cur))
                else:
                    sentences.append(s_stripped)

    budget = max_tweet_len - 8
    raw_tweets = []
    current = ""
    for s in sentences:
        if not current:
            current = s
        elif len(current) + len(s) + 1 <= budget:
            current += " " + s
        else:
            raw_tweets.append(current.strip())
            current = s
    if current:
        raw_tweets.append(current.strip())

    total = len(raw_tweets)
    if total <= 1:
        t = raw_tweets[0] if raw_tweets else clean_text
        return [t[:max_tweet_len]]

    final_tweets = []
    for i, tw in enumerate(raw_tweets):
        prefix = f"{i+1}/{total}\n\n"
        tweet_body = tw
        if len(prefix + tweet_body) > max_tweet_len:
            tweet_body = tweet_body[:max_tweet_len - len(prefix) - 1] + "…"
        final_tweets.append(prefix + tweet_body)
    return final_tweets


def format_for_x(text: str, max_chars: int = 280) -> str:
    """Format single post strictly for X (Twitter):
    - Strictly <= max_chars (280 characters).
    - Strips markdown asterisks and ### headers.
    - Preserves core hook, link, and hashtags.
    - Zero corporate filler.
    """
    if not text:
        return ""
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    cleaned = re.sub(r"(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)", r"\1", cleaned)
    cleaned = re.sub(r"^###\s+", "", cleaned, flags=re.MULTILINE)
    
    if len(cleaned.strip()) <= max_chars:
        return cleaned.strip()
    
    urls = re.findall(r"https?://\S+", cleaned)
    primary_url = urls[0].rstrip(".,;)") if urls else ""
    hashtags = re.findall(r"#\w+", cleaned)
    tags_str = " ".join(hashtags[:2]) if hashtags else ""

    prose = cleaned
    for u in urls:
        prose = prose.replace(u, "")
    for h in hashtags:
        prose = prose.replace(h, "")
    prose = re.sub(r"\s+", " ", prose).strip()

    url_len = len(primary_url) if primary_url else 0
    tag_len = len(tags_str) if tags_str else 0
    prose_budget = max_chars - (url_len + 2 if url_len else 0) - (tag_len + 2 if tag_len else 0)
    if prose_budget < 50 and primary_url:
        # X t.co link takes ~23 chars natively, ensure prose has space
        prose_budget = 140

    if len(prose) > prose_budget:
        cut = prose[:prose_budget]
        last_punct = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        if last_punct > 50:
            condensed = cut[:last_punct + 1].strip()
        else:
            last_sp = cut.rfind(" ")
            condensed = (cut[:last_sp] if last_sp > 40 else cut).strip() + "…"
    else:
        condensed = prose

    parts = [condensed]
    if primary_url:
        parts.append(primary_url)
    if tags_str:
        parts.append(tags_str)

    res = "\n\n".join(p for p in parts if p)
    if len(res) > max_chars and not primary_url:
        res = res[:max_chars - 1] + "…"
    return res


def format_as_carousel(title: str, post_text: str) -> list[dict]:
    """Convert post into multi-slide carousel outlines for LinkedIn or Instagram."""
    paragraphs = [p.strip() for p in post_text.split("\n\n") if p.strip()]
    slides = [{"slide": 1, "heading": "HOOK", "body": title}]
    for i, p in enumerate(paragraphs[:5], start=2):
        lines = p.split("\n")
        heading = lines[0][:40] if len(lines) > 1 else f"KEY POINT {i-1}"
        body = "\n".join(lines[1:]) if len(lines) > 1 else p
        slides.append({"slide": i, "heading": heading, "body": body})
    slides.append({"slide": len(slides) + 1, "heading": "TAKEAWAY", "body": "Follow @JustMeMedia for daily cutting-edge insights."})
    return slides


def format_for_linkedin(text: str) -> str:
    """Format post text specifically for LinkedIn:
    - LinkedIn composer does not render raw markdown bold (**text**) or italics (*text*).
    - Convert bold section headers (e.g. **Key Dates** or ### Key Dates) into clean titles with colons.
    - Clean inline asterisks from **bold** and *italic* phrases.
    - Preserve emojis, bullet points, numbering, and URLs.
    """
    if not text:
        return ""
    lines = []
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("### "):
            clean_title = s[4:].strip().replace("**", "").replace("*", "")
            lines.append(f"{clean_title}:" if not clean_title.endswith(":") else clean_title)
        elif s.startswith("**") and s.endswith("**") and len(s) > 4 and "\n" not in s:
            clean_title = s[2:-2].strip()
            lines.append(f"{clean_title}:" if not clean_title.endswith(":") else clean_title)
        else:
            cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
            cleaned = re.sub(r"(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)", r"\1", cleaned)
            lines.append(cleaned)
    return "\n".join(lines)


def search_gifs(query: str, limit: int = 6) -> list[dict]:
    """Search trending GIFs via Giphy public test endpoint."""
    if not query:
        return []
    try:
        q = urllib.parse.quote(query)
        url = f"https://api.giphy.com/v1/gifs/search?api_key=dc6zaTOxFJmzC&q={q}&limit={limit}&rating=g"
        req = urllib.request.Request(url, headers={"User-Agent": "JustMeMediaContentOS/1.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        gifs = []
        for g in data.get("data", []):
            gifs.append({
                "id": g["id"],
                "title": g.get("title", ""),
                "url": g["images"]["fixed_height_small"]["url"],
                "original": g["images"]["original"]["url"]
            })
        return gifs
    except Exception:
        return []


FALLBACK_STORIES = [
    {
        "title": "Why Local-First Software is the Future of Content & AI Workflows",
        "url": "https://justmemedia.local/articles/local-first-future",
        "snippet": "Local-first software combines the collaboration of cloud apps with the speed, data privacy, and offline resilience of local desktop files."
    },
    {
        "title": "Running High-Throughput LLMs Locally on Apple Silicon M-Series",
        "url": "https://justmemedia.local/articles/local-llm-m-series",
        "snippet": "How unified memory architecture and Metal acceleration allow modern Macs to run high-throughput models without cloud latency or recurring fees."
    },
    {
        "title": "The Shift from Cloud Lock-In to Autonomous Open-Source Agent Hubs",
        "url": "https://justmemedia.local/articles/open-agent-hubs",
        "snippet": "Why independent media creators and software teams are replacing monolithic SaaS platforms with localized, modular agent pipelines."
    }
]


def fetch_rss_feed(url: str, limit: int = 8) -> list[dict]:
    try:
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
        return items if items else FALLBACK_STORIES
    except Exception:
        return FALLBACK_STORIES


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>JustMeMedia ContentOS</title>
<style>
:root{color-scheme:dark;--bg:#0c110e;--panel:#141b16;--panel-alt:#1b251f;--line:#28382e;--accent:#48bb78;--accent-hover:#38a169;--text:#edf3ee;--muted:#9cb0a2;--danger:#e53e3e;--warning:#ecc94b;--purple:#9f7aea}
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
.btn-purple{background:var(--purple);color:#fff}
.btn-purple:hover{background:#805ad5}
.btn-small{padding:5px 9px;font-size:11px;border-radius:4px}
.btn-approve{background:#2b6cb0;color:#fff}
.btn-approve:hover{background:#2c5282}
.btn-danger{background:transparent;border:1px solid #742a2a;color:#feb2b2}
.btn-danger:hover{background:#742a2a;color:#fff}
.status-pill{font-size:10px;text-transform:uppercase;letter-spacing:.5px;padding:2px 7px;border-radius:10px;font-weight:700}
.status-draft{background:#2d3748;color:#cbd5e0}
.status-approved{background:#22543d;color:#9ae6b4}
.status-rejected{background:#742a2a;color:#feb2b2}
.status-published{background:#2c5282;color:#bee3f8}
.chip{background:var(--panel-alt);border:1px solid var(--line);color:var(--muted);padding:3px 10px;border-radius:12px;font-size:11px;cursor:pointer;transition:all .15s}
.chip:hover{border-color:#4a5568;color:var(--text)}
.chip-active{background:#22543d;border-color:#2f855a;color:#9ae6b4;font-weight:700}
.scheduled-pill{font-size:10px;background:#1a202c;border:1px solid #4a5568;color:#90cdf4;padding:2px 7px;border-radius:10px;font-weight:600;display:inline-flex;align-items:center;gap:4px}
.slot-select{background:var(--panel);border:1px solid var(--line);color:var(--text);font-size:11px;padding:3px 6px;border-radius:4px;outline:none;cursor:pointer}
.item-card{background:var(--panel-alt);border:1px solid var(--line);border-radius:8px;padding:12px;margin-bottom:12px;position:relative}
.item-card h3{margin:0 0 6px;font-size:14px;color:#fff;word-break:break-word}
.item-meta{font-size:11px;color:var(--muted);display:flex;align-items:center;gap:8px;margin-bottom:8px}
.item-card p{margin:0 0 10px;font-size:13px;color:#d2ded5;white-space:pre-wrap;max-height:120px;overflow:hidden;text-overflow:ellipsis}
.image-prompt-box{background:#0c120e;border:1px dashed #354a3e;border-radius:6px;padding:10px;margin:8px 0;font-size:12px;color:#9ae6b4}
.roundtable-badge{background:#2d1d3a;border:1px solid var(--purple);color:#d6bcfa;padding:3px 8px;border-radius:4px;font-size:11px;margin-bottom:8px;display:inline-block}
.char-counter{font-size:11px;color:var(--muted);text-align:right;margin-top:4px}
.char-counter.limit-exceeded{color:var(--danger);font-weight:700}
.toast{min-height:22px;font-size:12px;color:var(--accent);margin-top:8px}
.source-item{padding:10px 0;border-top:1px solid var(--line);font-size:12px}
.source-item:first-child{border-top:0}
.source-item a{color:#9ae6b4;text-decoration:none;font-weight:600}
.source-item a:hover{text-decoration:underline}
.composer-links{display:flex;gap:6px;margin-top:8px}
.gif-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:8px;max-height:160px;overflow-y:auto}
.gif-grid img{width:100%;height:75px;object-fit:cover;border-radius:4px;cursor:pointer;border:1px solid transparent}
.gif-grid img:hover{border-color:var(--accent)}
.carousel-preview{background:var(--panel-alt);border:1px solid var(--line);border-radius:8px;padding:12px;margin-top:10px}
.carousel-slide{background:#0c120e;border:1px solid var(--accent);border-radius:6px;padding:12px;margin-bottom:8px}
.carousel-slide-num{font-size:10px;color:var(--accent);font-weight:700;text-transform:uppercase;margin-bottom:4px}
.carousel-slide h4{margin:0 0 6px;font-size:14px;color:#fff}
.carousel-slide p{margin:0;font-size:12px;color:var(--muted);white-space:pre-wrap}
.webhook-row{display:flex;gap:8px;margin-top:6px;align-items:center}
.draw-things-status{font-size:11px;padding:3px 8px;border-radius:4px;display:inline-block}
.dt-online{background:#22543d;color:#9ae6b4}
.dt-offline{background:#742a2a;color:#feb2b2}
.omni-bundle{background:var(--panel-alt);border:1px solid var(--purple);border-radius:8px;padding:12px;margin-top:10px}
.omni-platform-tab{padding:6px 12px;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer;border:1px solid var(--line);background:transparent;color:var(--muted)}
.omni-platform-tab.active{background:var(--accent);color:#08130b;border-color:var(--accent)}
.omni-tab-content{background:#0c120e;border:1px solid #354a3e;border-radius:6px;padding:10px;margin-top:6px;font-size:12px;color:#d2ded5;white-space:pre-wrap;max-height:180px;overflow-y:auto}

.pipeline-modal-backdrop {
  position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
  background: rgba(0, 0, 0, 0.78); backdrop-filter: blur(5px);
  display: flex; align-items: center; justify-content: center;
  z-index: 99999;
}
.pipeline-modal {
  background: #111418; border: 1px solid #2d3748; border-radius: 12px;
  width: 90%; max-width: 520px; padding: 24px; box-shadow: 0 20px 45px rgba(0,0,0,0.85);
  color: #fff; font-family: inherit;
}
.modal-step {
  display: flex; align-items: center; gap: 12px; padding: 10px 14px;
  background: #1a202c; border: 1px solid #2d3748; border-radius: 8px; margin-bottom: 8px;
  font-size: 13px; transition: all .2s; color: #a0aec0;
}
.modal-step.active {
  border-color: #319795; background: #17282c; color: #81e6d9; font-weight: 600;
}
.modal-step.done {
  border-color: #276749; background: #14291e; color: #9ae6b4;
}
.action-banner {
  background: #1a365d; border: 1px solid #2b6cb0; border-radius: 6px;
  padding: 8px 12px; margin: 8px 0; display: flex; justify-content: space-between;
  align-items: center; gap: 8px; flex-wrap: wrap;
}

</style>
</head>
<body>
<header>
  <div>
    <span class="brand">JustMe<span>Media</span> ContentOS</span>
    <span class="tagline">Local-First Content Engine & Multimodal Publishing Studio</span>
  </div>
  <div class="nav-links">
    <button class="nav-btn" onclick="exportDraftsJson()">Export JSON</button>
    <button class="nav-btn" onclick="exportAllMarkdown()">Export All Markdown</button>
  </div>
</header>

<main>
  <!-- COLUMN 1: DISCOVERY & INTAKE -->
  <section>
    <h2>1. Content Discovery <span style="font-size:11px;font-weight:normal;color:var(--muted)">Verified Sources + RSS</span></h2>
    <label for="rssPreset">Curated Verified Sources</label>
    <select id="rssPreset" onchange="fetchFeed(this.value)">
      <optgroup label="🍎 Apple (Official)">
        <option value="https://developer.apple.com/news/rss/news.rss">Apple Developer News ✅</option>
        <option value="https://www.apple.com/newsroom/rss-feed.rss">Apple Newsroom ✅</option>
      </optgroup>
      <optgroup label="🔵 Google (Official)">
        <option value="https://blog.google/technology/ai/rss/">Google AI Blog ✅</option>
        <option value="https://blog.google/rss/">Google The Keyword ✅</option>
      </optgroup>
      <optgroup label="🤖 AI Labs">
        <option value="https://openai.com/news/rss.xml">OpenAI News ✅</option>
        <option value="https://techcrunch.com/tag/anthropic/feed/">Anthropic (via TechCrunch) ✅</option>
        <option value="https://techcrunch.com/tag/deepseek/feed/">DeepSeek (via TechCrunch) ✅</option>
        <option value="https://techcrunch.com/tag/xai/feed/">xAI / Grok (via TechCrunch) ✅</option>
        <option value="https://techcrunch.com/tag/meta-ai/feed/">Meta AI (via TechCrunch) ✅</option>
        <option value="https://techcrunch.com/tag/microsoft-ai/feed/">Microsoft AI (via TechCrunch) ✅</option>
      </optgroup>
      <optgroup label="📰 Tech & AI News">
        <option value="https://news.ycombinator.com/rss">Hacker News Top Stories</option>
        <option value="https://hnrss.org/frontpage">Hacker News Frontpage</option>
        <option value="https://feeds.arstechnica.com/arstechnica/index">Ars Technica Tech & AI</option>
        <option value="https://www.technologyreview.com/topic/artificial-intelligence/feed/">MIT Technology Review AI</option>
        <option value="https://techcrunch.com/category/artificial-intelligence/feed/">TechCrunch AI</option>
        <option value="https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml">NYT Technology News</option>
      </optgroup>
    </select>
    <div style="display:flex;gap:6px;margin-top:8px">
      <input id="customRss" placeholder="Paste custom RSS/Atom URL">
      <button class="btn btn-secondary btn-small" onclick="fetchFeed(document.getElementById('customRss').value)">Load</button>
    </div>

    <div style="margin-top:12px;background:var(--panel-alt);padding:10px;border-radius:6px;border:1px solid var(--line)">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <label style="margin:0">⚡ Autopilot Batch</label>
        <button id="btnAutopilot" class="btn btn-purple btn-small" onclick="runAutopilot()">Draft Top 3 Stories</button>
      </div>
      <p style="margin:4px 0 0;font-size:11px;color:var(--muted)">Auto-extracts full articles & runs Roundtable agents on top 3 headlines.</p>
    </div>
    
    <label style="margin-top:16px">Top Stories & Trends</label>
    <div style="display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap" id="topicChips">
      <button class="chip chip-active" onclick="filterTopic('')" id="chip_all">🌐 All</button>
      <button class="chip" onclick="filterTopic('AI')" id="chip_ai">🤖 AI</button>
      <button class="chip" onclick="filterTopic('Apple')" id="chip_apple">🍎 Apple</button>
      <button class="chip" onclick="filterTopic('Google')" id="chip_google">🔵 Google</button>
      <button class="chip" onclick="filterTopic('OpenAI')" id="chip_openai">OpenAI</button>
      <button class="chip" onclick="filterTopic('Claude|Anthropic')" id="chip_anthropic">Anthropic</button>
      <button class="chip" onclick="filterTopic('DeepSeek')" id="chip_deepseek">DeepSeek</button>
      <button class="chip" onclick="filterTopic('Grok|xAI')" id="chip_xai">xAI/Grok</button>
      <button class="chip" onclick="filterTopic('developer|SDK|API')" id="chip_dev">💻 Dev</button>
    </div>
    <input id="keywordFilter" placeholder="🔍 Filter stories by keyword…" oninput="applyFilter()" style="width:100%;margin-bottom:8px">
    <!-- 1-CLICK TARGET PLATFORMS (multi-select) -->
    <div style="background:var(--panel-alt);border:1px solid #2d3748;border-radius:6px;padding:8px 12px;margin-bottom:8px">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
        <label style="margin:0;font-size:12px;font-weight:700;color:#9ae6b4">✨ 1-Click produces for</label>
        <span style="font-size:10px;color:var(--muted)">Pick any combination — one draft per platform</span>
      </div>
      <div id="oneClickPlatforms" style="display:flex;gap:12px;flex-wrap:wrap;margin-top:6px;font-size:12px">
        <label style="margin:0;display:inline-flex;align-items:center;gap:5px;cursor:pointer"><input type="checkbox" class="oc-platform" value="LinkedIn" checked style="accent-color:#2f855a"> LinkedIn</label>
        <label style="margin:0;display:inline-flex;align-items:center;gap:5px;cursor:pointer"><input type="checkbox" class="oc-platform" value="X" style="accent-color:#2f855a"> X / Twitter</label>
        <label style="margin:0;display:inline-flex;align-items:center;gap:5px;cursor:pointer"><input type="checkbox" class="oc-platform" value="YouTube" style="accent-color:#2f855a"> YouTube</label>
        <label style="margin:0;display:inline-flex;align-items:center;gap:5px;cursor:pointer"><input type="checkbox" class="oc-platform" value="Facebook" style="accent-color:#2f855a"> Facebook</label>
        <label style="margin:0;display:inline-flex;align-items:center;gap:5px;cursor:pointer"><input type="checkbox" class="oc-platform" value="Instagram" style="accent-color:#2f855a"> Instagram</label>
      </div>
    </div>
    <div id="sourcesList" style="flex:1;overflow-y:auto;max-height:420px">Loading stories…</div>
    <details style="margin-top:10px">
      <summary style="cursor:pointer;font-size:11px;color:var(--muted);font-weight:600">🚫 Rejected stories (<span id="rejectedSourcesCount">0</span>) — click to restore</summary>
      <div id="rejectedSourcesList" style="margin-top:6px;font-size:11px;color:var(--muted)">Loading…</div>
    </details>
  </section>

  <!-- COLUMN 2: DRAFTING & AI ENGINE -->
  <section>
    <h2>2. Content Engine & AI Studio</h2>
    
    <label for="aiProvider">Select Intelligence Provider</label>
    <select id="aiProvider"></select>
    
    <div style="margin-top:6px">
      <label for="draftTitle">Headline / Working Title</label>
      <input id="draftTitle" required placeholder="e.g. Why Local AI is Winning">
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:6px">
      <div>
        <label for="draftPlatform">Platform</label>
        <select id="draftPlatform" onchange="updateCharCount()">
          <option value="LinkedIn">LinkedIn (Exec Post)</option>
          <option value="X">X (Twitter Thread/Hook)</option>
          <option value="YouTube">YouTube (Hub & Full Brief)</option>
          <option value="Facebook">Facebook (Long-Form Guide)</option>
          <option value="Instagram">Instagram/Threads</option>
          <option value="General">General Draft</option>
        </select>
      </div>
      <div>
        <label for="draftTone">Editorial Tone / Persona</label>
        <select id="draftTone">
          <option value="thought_leadership">🎯 Thought Leadership</option>
          <option value="viral_story">⚡ Viral & Punchy</option>
          <option value="technical_deep_dive">🛠️ Deep Technical</option>
          <option value="contrarian">🔥 Contrarian / Hot Take</option>
        </select>
      </div>
    </div>

    <!-- AGENT 0: DEEP RESEARCH TOGGLE -->
    <div style="background:var(--panel-alt);border:1px solid #2d3748;border-radius:6px;padding:8px 12px;margin-top:10px;display:flex;align-items:center;justify-content:space-between">
      <div>
        <label style="margin:0;font-size:12px;font-weight:700;color:#9ae6b4;display:flex;align-items:center;gap:6px">
          <input type="checkbox" id="deepResearchToggle" checked style="accent-color:#2f855a">
          🔬 Agent 0: Deep Research Enrichment
        </label>
        <div style="font-size:10px;color:var(--muted);margin-top:2px">Scrapes sub-portals, docs & application forms for 360° coverage</div>
      </div>
      <span style="font-size:10px;background:#14291e;border:1px solid #22543d;color:#9ae6b4;padding:2px 6px;border-radius:4px;font-weight:600">Active</span>
    </div>

    <!-- PIPELINE MODE SELECTOR -->
    <div style="display:flex;gap:12px;align-items:center;margin-top:10px;background:var(--panel-alt);padding:8px 12px;border-radius:6px;border:1px solid var(--line)">
      <label style="margin:0;cursor:pointer;display:flex;align-items:center;gap:6px">
        <input type="checkbox" id="chkRoundtable" checked style="width:auto"> 🤖 <strong>Roundtable Mode (3 Agents)</strong>
      </label>
      <span style="font-size:11px;color:var(--muted)">Drafter ➔ Fact-Checker ➔ Hook Optimizer</span>
    </div>

    <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
      <button id="btnAiDraft" class="btn btn-secondary" onclick="generateAiDraft()">⚡ Generate Post</button>
      <button id="btnAiVisual" class="btn btn-secondary" onclick="generateImagePrompt()">🎨 Suggest Image Prompt</button>
      <button id="btnGenImage" class="btn btn-secondary" onclick="generateLocalImage()">🖼️ __IMAGE_LABEL__ (Local AI)</button>
    </div>
    <div id="dtStatus" style="margin-top:4px;font-size:11px;color:var(--muted)">Checking __IMAGE_LABEL__…</div>
    <div id="generatedImagePreview" style="margin-top:8px;display:none">
      <img id="generatedImg" style="width:100%;border-radius:6px;border:1px solid var(--line)" alt="Generated image">
      <button class="btn btn-secondary btn-small" style="margin-top:4px" onclick="attachGeneratedImage()">📎 Attach to Draft</button>
    </div>
    
    <label for="draftBody" style="margin-top:12px">Post Body & Formatting</label>
    <textarea id="draftBody" oninput="updateCharCount()" placeholder="Write post or generate with AI..."></textarea>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-top:4px">
      <div style="display:flex;gap:6px">
        <button class="btn btn-secondary btn-small" onclick="formatThread()">🧵 Split X Thread</button>
        <button class="btn btn-secondary btn-small" onclick="formatCarousel()">📑 Split Carousel</button>
      </div>
      <div id="charCounter" class="char-counter" style="margin-top:0">0 characters</div>
    </div>

    <!-- PHASE D: CAROUSEL VISUAL SLIDE PREVIEW -->
    <div id="carouselPreview" class="carousel-preview" style="display:none">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <label style="margin:0">📑 Carousel Slide Preview</label>
        <button class="btn btn-small btn-secondary" onclick="document.getElementById('carouselPreview').style.display='none'">✕</button>
      </div>
      <div id="carouselSlides"></div>
    </div>

    <!-- PHASE A: OMNI-PLATFORM REPURPOSING BUNDLE -->
    <div class="omni-bundle" style="margin-top:12px">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <label style="margin:0;color:var(--purple)">🚀 Omni-Platform Repurposing</label>
        <button id="btnOmni" class="btn btn-purple btn-small" onclick="generateOmniBundle()">Generate All Platforms</button>
      </div>
      <p style="margin:4px 0 8px;font-size:11px;color:var(--muted)">1 story ➔ LinkedIn post + X Thread + YouTube Brief simultaneously</p>
      <div id="omniBundleTabs" style="display:none">
        <div style="display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap">
          <button class="omni-platform-tab active" onclick="showOmniTab('linkedin', this)">LinkedIn</button>
          <button class="omni-platform-tab" onclick="showOmniTab('x', this)">X Thread</button>
          <button class="omni-platform-tab" onclick="showOmniTab('youtube', this)">YouTube Hub</button>
          <button class="omni-platform-tab" onclick="showOmniTab('facebook', this)">Facebook Guide</button>
        </div>
        <div id="omniLinkedin" class="omni-tab-content"></div>
        <div id="omniX" class="omni-tab-content" style="display:none"></div>
        <div id="omniYoutube" class="omni-tab-content" style="display:none"></div>
        <div id="omniFacebook" class="omni-tab-content" style="display:none"></div>
        <div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">
          <button class="btn btn-small btn-secondary" onclick="loadOmniToDraft('linkedin')">Load LinkedIn</button>
          <button class="btn btn-small btn-secondary" onclick="loadOmniToDraft('x')">Load X</button>
          <button class="btn btn-small btn-secondary" onclick="loadOmniToDraft('youtube')">Load YouTube</button>
          <button class="btn btn-small btn-secondary" onclick="loadOmniToDraft('facebook')">Load Facebook</button>
          <button class="btn btn-small" style="background:#44337a;color:#d6bcfa;border:1px solid #6b46c1;font-weight:700" onclick="saveOmniBundle()">💾 Save All 4 Funnel Drafts</button>
        </div>
      </div>
    </div>

    <!-- MULTIMODAL MEDIA STUDIO (GIF SEARCH & VISUAL PROMPTS) -->
    <div style="background:var(--panel-alt);padding:10px;border-radius:6px;border:1px solid var(--line);margin-top:10px">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <label style="margin:0">🎬 Media Studio & GIF Search</label>
        <span style="font-size:11px;color:var(--muted)">Click a GIF to attach</span>
      </div>
      <div style="display:flex;gap:6px;margin-top:6px">
        <input id="gifSearchQuery" placeholder="Search GIFs (e.g. tech, mind blown, coding)..." onkeydown="if(event.key==='Enter') searchGifs()">
        <button class="btn btn-secondary btn-small" onclick="searchGifs()">Find</button>
      </div>
      <div id="gifResults" class="gif-grid"></div>
      <div id="attachedMediaPreview" style="margin-top:6px;display:none;font-size:11px;color:var(--accent)">
        Attached GIF: <span id="attachedMediaUrl"></span>
        <button class="btn btn-danger btn-small" style="margin-left:8px" onclick="clearAttachedMedia()">Remove</button>
      </div>
    </div>

    <label for="draftImagePrompt" style="margin-top:12px">Generated Artwork Brief (for Gemini, FLUX, Grok, Midjourney)</label>
    <textarea id="draftImagePrompt" style="min-height:65px" placeholder="AI visual generation prompt..."></textarea>
    
    <input type="hidden" id="draftSourceUrl">
    <input type="hidden" id="draftMediaUrl">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;gap:8px;flex-wrap:wrap">
      <div style="display:flex;align-items:center;gap:8px">
        <button class="btn" id="btnSaveDraft" onclick="saveDraft()">💾 Save Draft</button>
        <span id="editingBadge" style="display:none;font-size:11px;color:#9ae6b4;background:#14291e;border:1px solid #22543d;padding:3px 8px;border-radius:10px">
          ✏️ Editing draft #<span id="editingDraftId"></span>
          <button class="btn btn-small btn-secondary" style="margin-left:6px;padding:1px 6px" onclick="cancelDraftEdit()">New draft</button>
        </span>
      </div>
      <span id="saveToast" class="toast"></span>
    </div>
  </section>

  <!-- COLUMN 3: STAGING & APPROVAL GATEWAY -->
  <section>
    <h2>3. Approval & Publishing Hub</h2>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
      <div style="display:flex;gap:6px;align-items:center">
        <label style="margin:0">Saved Drafts & Queue</label>
        <span id="queueCount" style="font-size:11px;color:var(--muted)">0 items</span>
      </div>
      <button class="btn btn-secondary btn-small" onclick="toggleWebhookSettings()">⚙️ Webhooks</button>
    </div>

    <!-- QUEUE TABS: ACTIVE VS REJECTED VS PUBLISHED ARCHIVE -->
    <div style="display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap">
      <button id="tabActive" class="chip chip-active" onclick="switchQueueTab('active')">⚡ Active Queue (<span id="activeCount">0</span>)</button>
      <button id="tabRejected" class="chip" onclick="switchQueueTab('rejected')">🚫 Rejected (<span id="rejectedCount">0</span>)</button>
      <button id="tabArchive" class="chip" onclick="switchQueueTab('published')">📊 Published Archive (<span id="archiveCount">0</span>)</button>
    </div>

    <!-- PHASE E: WEBHOOK SETTINGS PANEL -->
    <div id="webhookSettings" style="display:none;background:var(--panel-alt);border:1px solid var(--line);border-radius:6px;padding:10px;margin-bottom:10px">
      <label style="font-size:11px">Discord Webhook</label>
      <div class="webhook-row">
        <input id="discordWebhook" placeholder="https://discord.com/api/webhooks/...">
        <button class="btn btn-small btn-secondary" onclick="testWebhook('discord')">Test</button>
      </div>
      <label style="font-size:11px;margin-top:6px">Slack Webhook</label>
      <div class="webhook-row">
        <input id="slackWebhook" placeholder="https://hooks.slack.com/services/...">
        <button class="btn btn-small btn-secondary" onclick="testWebhook('slack')">Test</button>
      </div>
      <label style="font-size:11px;margin-top:6px">Custom Webhook (n8n/Zapier)</label>
      <div class="webhook-row">
        <input id="customWebhook" placeholder="https://...">
        <button class="btn btn-small btn-secondary" onclick="testWebhook('custom')">Test</button>
      </div>
      <button class="btn btn-small" style="margin-top:8px" onclick="saveWebhooks()">Save Webhook URLs</button>

      <div style="border-top:1px solid var(--line);margin:12px 0 8px;padding-top:10px">
        <label style="font-size:11px;font-weight:700;color:#9ae6b4">📱 Phone Push Notification (ntfy.sh - 100% Free)</label>
        <p style="font-size:10px;color:var(--muted);margin:2px 0 6px">Get instant alerts on iPhone/Android when a post finishes drafting or hits its schedule.</p>
        <div class="webhook-row">
          <input id="ntfyTopicInput" placeholder="e.g. justme-contentos-alerts" onchange="setNtfyTopic(this.value)">
          <button class="btn btn-small" style="background:#22543d;color:#9ae6b4;border:1px solid #2f855a" onclick="testPhonePush()">Test Alert</button>
        </div>
      </div>
    </div>

    <div id="draftsQueue" style="flex:1;overflow-y:auto;max-height:680px">Loading drafts…</div>
  </section>
</main>

<!-- PIPELINE GUIDANCE MODAL -->
<div id="pipelineModal" class="pipeline-modal-backdrop" style="display:none">
  <div class="pipeline-modal">
    <div id="modalLoadingView">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
        <h3 style="margin:0;font-size:16px;color:#fff">✨ 1-Click Magic Pipeline Active</h3>
        <span style="font-size:10px;background:#2d3748;padding:3px 8px;border-radius:10px;color:#9ae6b4;font-weight:700">AUTONOMOUS</span>
      </div>
      <p id="modalStoryTitle" style="color:#a0aec0;font-size:13px;margin:0 0 16px;font-style:italic;line-height:1.4"></p>
      
      <div id="mStep1" class="modal-step"><span>📖</span> <span>[1/4] Scraping deep article text & facts…</span></div>
      <div id="mStep2" class="modal-step"><span>✍️</span> <span>[2/4] Running 4-Agent Roundtable (Hook & Anti-Slop)…</span></div>
      <div id="mStep3" class="modal-step"><span>🎨</span> <span>[3/4] __IMAGE_STEP3__</span></div>
      <div id="mStep4" class="modal-step"><span>📅</span> <span>[4/4] Auto-scheduling optimal peak posting slot…</span></div>
      
      <p style="font-size:11px;color:#718096;text-align:center;margin-top:14px">Feel free to step away and make tea ☕ — your Mac chime & phone will alert you when complete.</p>
    </div>

    <div id="modalSuccessView" style="display:none">
      <div style="text-align:center;margin-bottom:16px">
        <div style="font-size:36px;margin-bottom:4px">🎉</div>
        <h3 style="margin:0;font-size:18px;color:#9ae6b4">Drafts Staged for Review</h3>
        <p style="font-size:12px;color:#a0aec0;margin:4px 0 0">Nothing is published yet — approval is required.</p>
      </div>

      <div style="background:#1a202c;border:1px solid #2d3748;border-radius:8px;padding:12px;margin-bottom:16px">
        <div style="font-size:11px;color:#9ae6b4;text-transform:uppercase;letter-spacing:1px;font-weight:700">👉 Next step: review &amp; approve</div>
        <div id="modalStagedList" style="margin:8px 0 12px;display:flex;flex-direction:column;gap:6px"></div>
        <div id="modalActionButtons"></div>
        <div style="font-size:11px;color:#a0aec0;margin-top:8px">
          💡 Launch buttons stay locked until you approve a draft in the Publishing Hub. This keeps a human in the loop.
        </div>
      </div>

      <div style="background:#14291e;border:1px solid #22543d;border-radius:8px;padding:10px;margin-bottom:16px;display:flex;justify-content:space-between;align-items:center">
        <div>
          <div style="font-size:11px;color:#9ae6b4;font-weight:700">🖼️ Attached media</div>
          <div style="font-size:11px;color:#cbd5e0;margin-top:2px" id="modalMediaNote">Media is attached to every staged draft.</div>
        </div>
        <button class="btn btn-small" style="background:#22543d;color:#9ae6b4;border:1px solid #2f855a;white-space:nowrap" onclick="openMediaFinder()">📂 Open Folder</button>
      </div>

      <div style="display:flex;justify-content:flex-end;gap:8px">
        <button class="btn btn-secondary btn-small" onclick="closePipelineModal()">Done / Close</button>
      </div>
    </div>

    <div id="modalErrorView" style="display:none">
      <div style="text-align:center;margin-bottom:14px">
        <div style="font-size:36px;margin-bottom:4px">⚠️</div>
        <h3 style="margin:0;font-size:16px;color:#feb2b2">Generation Paused</h3>
        <p id="modalErrorMessage" style="font-size:12px;color:#fc8181;margin:6px 0 0"></p>
      </div>
      <div style="background:#2d3748;border-radius:8px;padding:10px;font-size:12px;color:#e2e8f0;margin-bottom:14px" id="modalErrorAdvice"></div>
      <div style="display:flex;justify-content:flex-end;gap:8px">
        <button class="btn btn-secondary btn-small" onclick="closePipelineModal()">Dismiss</button>
      </div>
    </div>
  </div>
</div>


<script>
let currentProviders = [];

async function loadStatus() {
  const savedTopic = getNtfyTopic();
  if (savedTopic && document.getElementById('ntfyTopicInput')) {
    document.getElementById('ntfyTopicInput').value = savedTopic;
  }
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

// ── KEYWORD FILTER ────────────────────────────────────────────────────────────
let _activeTopicRegex = null;

function filterTopic(pattern) {
  _activeTopicRegex = pattern ? new RegExp(pattern, 'i') : null;
  // Update chip styles
  document.querySelectorAll('.chip').forEach(c => c.classList.remove('chip-active'));
  const chipId = pattern ? 'chip_' + pattern.split('|')[0].toLowerCase().replace(/[^a-z]/g,'') : 'chip_all';
  const activeChip = document.getElementById(chipId);
  if (activeChip) activeChip.classList.add('chip-active');
  else document.getElementById('chip_all').classList.add('chip-active');
  applyFilter();
}

function applyFilter() {
  const kw = (document.getElementById('keywordFilter').value || '').trim().toLowerCase();
  const items = window._sources || [];
  const cards = document.querySelectorAll('#sourcesList .source-item');
  items.forEach((item, idx) => {
    if (idx >= cards.length) return;
    const text = (item.title + ' ' + item.snippet).toLowerCase();
    const kwMatch = !kw || text.includes(kw);
    const topicMatch = !_activeTopicRegex || _activeTopicRegex.test(item.title + ' ' + item.snippet);
    cards[idx].style.display = (kwMatch && topicMatch) ? '' : 'none';
  });
}

// ── NTFY.SH MOBILE PUSH ───────────────────────────────────────────────────────
function getNtfyTopic() {
  return localStorage.getItem('ntfyTopic') || '';
}

function setNtfyTopic(topic) {
  localStorage.setItem('ntfyTopic', topic.trim());
}

async function sendPhonePush(title, body, priority) {
  const topic = getNtfyTopic();
  if (!topic) return;  // silently skip if not configured
  try {
    await fetch('/api/notify/phone', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({topic, title, body, priority: priority || 'default'})
    });
  } catch(e) {}
}

async function testPhonePush() {
  const topic = document.getElementById('ntfyTopicInput').value.trim();
  if (!topic) { alert('Enter a topic name first'); return; }
  setNtfyTopic(topic);
  await sendPhonePush('✅ ContentOS Connected!', 'Your phone notifications are working. Posts will ping you here when ready.', 'high');
  alert('Test push sent! Check your ntfy app.');
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
    // Mark stories already used (a draft exists for that source URL)
    try {
      const dr = await fetch('/api/drafts');
      const drafts = await dr.json();
      window._usedUrls = new Set((drafts || []).map(d => d.source_url).filter(Boolean));
    } catch (e) { window._usedUrls = new Set(); }
    // Re-apply any active keyword/topic filter after feed refresh
    setTimeout(applyFilter, 50);
    listEl.innerHTML = items.map((item, idx) => {
      const used = window._usedUrls && window._usedUrls.has(item.url);
      return `
      <div class="source-item" ${used ? 'style="opacity:.7;border-left:3px solid #2b6cb0"' : ''}>
        <a href="${item.url}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a>
        <p style="margin:4px 0 6px;color:var(--muted);font-size:11px">${escapeHtml(item.snippet)}</p>
        ${used ? '<div style="font-size:10px;color:#90cdf4;font-weight:700;margin-bottom:4px">✓ Already staged as a draft</div>' : ''}
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <button id="btnOneClick_${idx}" class="btn btn-small" style="background:#22543d;color:#9ae6b4;border:1px solid #2f855a;font-weight:700" onclick="oneClickCreate(${idx})">
            ✨ 1-Click Create & Stage
          </button>
          <button class="btn btn-secondary btn-small" onclick="useStory(${idx})">
            ⚡ Deep-Read & Draft
          </button>
          <button class="btn btn-small" style="background:transparent;border:1px solid #742a2a;color:#feb2b2" onclick="rejectSource(${idx})" title="Hide this story and never show it again">
            🚫 Reject
          </button>
        </div>
      </div>
    `;
    }).join('');
  } catch (err) {
    listEl.innerHTML = '<div style="color:var(--danger);padding:10px 0">Failed to fetch RSS feed.</div>';
  }
}


async function rejectSource(idx) {
  const item = (window._sources || [])[idx];
  if (!item) return;
  if (!confirm('Reject this story? It will be hidden and never shown again (you can restore it in the Rejected list).')) return;
  try {
    await fetch('/api/sources/reject', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url: item.url, title: item.title})
    });
  } catch (e) {}
  // Remove from the current list immediately
  window._sources.splice(idx, 1);
  // Re-render
  const listEl = document.getElementById('sourcesList');
  if (!window._sources.length) {
    listEl.innerHTML = '<div style="color:var(--muted);padding:10px 0">No stories left. Fetch a feed to load more.</div>';
    return;
  }
  // Rebuild by re-running fetchFeed's render path is heavy; just reload the feed's cached list via applyFilter
  // Simpler: re-render inline
  listEl.innerHTML = window._sources.map((it, i) => `
    <div class="source-item">
      <a href="${it.url}" target="_blank" rel="noopener">${escapeHtml(it.title)}</a>
      <p style="margin:4px 0 6px;color:var(--muted);font-size:11px">${escapeHtml(it.snippet)}</p>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <button id="btnOneClick_${i}" class="btn btn-small" style="background:#22543d;color:#9ae6b4;border:1px solid #2f855a;font-weight:700" onclick="oneClickCreate(${i})">✨ 1-Click Create & Stage</button>
        <button class="btn btn-secondary btn-small" onclick="useStory(${i})">⚡ Deep-Read & Draft</button>
        <button class="btn btn-small" style="background:transparent;border:1px solid #742a2a;color:#feb2b2" onclick="rejectSource(${i})">🚫 Reject</button>
      </div>
    </div>
  `).join('');
  loadRejectedSources();
}
async function loadRejectedSources() {
  try {
    const res = await fetch('/api/sources/rejected');
    const items = await res.json();
    const el = document.getElementById('rejectedSourcesList');
    const cnt = document.getElementById('rejectedSourcesCount');
    if (cnt) cnt.textContent = items.length;
    if (!items.length) {
      el.innerHTML = '<div style="color:var(--muted)">No rejected stories.</div>';
      return;
    }
    el.innerHTML = items.map(s => `
      <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;padding:4px 0;border-bottom:1px solid #1a2430">
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escapeHtml(s.title)}">${escapeHtml(s.title)}</span>
        <button class="btn btn-small btn-secondary" onclick="restoreRejectedSource('${escapeHtml(s.url)}')">↩️ Restore</button>
      </div>
    `).join('');
  } catch (e) {}
}

async function restoreRejectedSource(url) {
  await fetch('/api/sources/restore', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({url})
  });
  loadRejectedSources();
  fetchFeed(document.getElementById('rssPreset').value);
}
function openPipelineModal(title) {
  document.getElementById('modalLoadingView').style.display = 'block';
  document.getElementById('modalSuccessView').style.display = 'none';
  document.getElementById('modalErrorView').style.display = 'none';
  document.getElementById('modalStoryTitle').textContent = `"${title}"`;
  
  for (let i = 1; i <= 4; i++) {
    const el = document.getElementById('mStep' + i);
    el.className = 'modal-step';
  }
  document.getElementById('mStep1').classList.add('active');
  document.getElementById('pipelineModal').style.display = 'flex';
}

function updateModalStep(stepNum) {
  for (let i = 1; i <= 4; i++) {
    const el = document.getElementById('mStep' + i);
    if (i < stepNum) {
      el.className = 'modal-step done';
    } else if (i === stepNum) {
      el.className = 'modal-step active';
    } else {
      el.className = 'modal-step';
    }
  }
}

function showModalSuccess(data) {
  document.getElementById('modalLoadingView').style.display = 'none';
  document.getElementById('modalSuccessView').style.display = 'block';
  document.getElementById('modalErrorView').style.display = 'none';

  const staged = Array.isArray(data.drafts) && data.drafts.length
    ? data.drafts
    : [{id: data.id, platform: data.platform, body: data.body}];

  const listEl = document.getElementById('modalStagedList');
  listEl.innerHTML = staged.map(d => `
    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;background:#0f1620;border:1px solid #2d3748;border-radius:6px;padding:7px 10px">
      <div style="min-width:0">
        <div style="font-size:12px;font-weight:700;color:#e2e8f0">${escapeHtml(d.platform)}</div>
        <div style="font-size:10px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escapeHtml((d.body || '').slice(0, 70))}…</div>
      </div>
      <span class="status-pill status-draft" style="flex-shrink:0">DRAFT</span>
    </div>
  `).join('');

  document.getElementById('modalMediaNote').textContent = data.media_url
    ? 'Media attached to every staged draft.'
    : 'No local media backend — text-only drafts (add a GIF in the Studio if you want).';

  const btnContainer = document.getElementById('modalActionButtons');
  btnContainer.innerHTML = `
    <button class="btn" style="width:100%;background:#2b6cb0;color:#fff;font-weight:700;padding:12px;font-size:14px" onclick="focusQueueFromModal()">
      👀 Review &amp; Approve in Publishing Hub
    </button>
  `;
}

function focusQueueFromModal() {
  closePipelineModal();
  const hub = document.getElementById('draftsQueue');
  if (hub) {
    hub.scrollIntoView({behavior: 'smooth', block: 'center'});
    hub.style.outline = '2px solid #2b6cb0';
    setTimeout(() => { hub.style.outline = ''; }, 1800);
  }
}

function showModalError(errMessage) {
  document.getElementById('modalLoadingView').style.display = 'none';
  document.getElementById('modalSuccessView').style.display = 'none';
  document.getElementById('modalErrorView').style.display = 'block';
  document.getElementById('modalErrorMessage').textContent = errMessage;
  let advice = 'Click Dismiss and try another story or switch your AI Provider in Column 2.';
  if (errMessage.includes('Rate limit') || errMessage.includes('429')) {
    advice = 'Groq Cloud free tier requests were paced. Wait ~10 seconds and click again.';
  } else if (errMessage.includes('image') || errMessage.includes('Image')) {
    advice = 'The local image engine is not reachable. Media falls back to a GIF.';
  }
  document.getElementById('modalErrorAdvice').textContent = advice;
}

function closePipelineModal() {
  document.getElementById('pipelineModal').style.display = 'none';
}

function copyAndLaunchFromModal(id, url) {
  copyAndLaunch(id, url);
  closePipelineModal();
}

async function openMediaFinder(filename) {
  await fetch('/api/open-media', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({filename: filename || ''})
  });
}

async function oneClickCreate(idx) {
  const item = (window._sources || [])[idx];
  if (!item) return;

  // Multi-platform targets chosen in the Studio panel.
  let platforms = Array.from(document.querySelectorAll('.oc-platform:checked')).map(el => el.value);
  if (!platforms.length) {
    alert('Choose at least one platform under “1-Click produces for” first.');
    return;
  }

  const btn = document.getElementById(`btnOneClick_${idx}`);
  const originalText = btn ? btn.innerHTML : '';

  if (btn) { btn.disabled = true; btn.innerHTML = '⏳ In Progress…'; }

  openPipelineModal(item.title);

  const provider = document.getElementById('aiProvider').value;
  const tone = document.getElementById('draftTone').value;
  const deep = document.getElementById('deepResearchToggle') ? document.getElementById('deepResearchToggle').checked : true;

  try {
    setTimeout(() => { if (btn.disabled) updateModalStep(2); }, 1200);
    setTimeout(() => { if (btn.disabled) updateModalStep(3); }, 3500);
    setTimeout(() => { if (btn.disabled) updateModalStep(4); }, 8000);

    const res = await fetch('/api/one-click-draft', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        title: item.title,
        url: item.url,
        snippet: item.snippet,
        platforms: platforms,
        tone: tone,
        provider: provider,
        deep_research: deep
      })
    });
    const data = await res.json();
    if (data.ok) {
      if (btn) { btn.innerHTML = '✅ Staged!'; btn.style.background = '#276749'; }

      // Pre-fill center editor with the primary platform draft
      document.getElementById('draftTitle').value = data.title;
      document.getElementById('draftBody').value = data.body;
      document.getElementById('draftPlatform').value = data.platform;
      document.getElementById('draftImagePrompt').value = data.image_prompt;
      document.getElementById('draftSourceUrl').value = item.url;
      document.getElementById('draftMediaUrl').value = data.media_url || '';
      if (data.media_url) {
        document.getElementById('attachedMediaUrl').textContent = data.media_url;
        document.getElementById('attachedMediaPreview').style.display = 'block';
      }
      updateCharCount();

      // The primary draft already exists, so Save should update instead of duplicating.
      setEditingDraft(data.id);

      // Mark this story as used so it shows a badge on refresh
      if (item.url) {
        try { await fetch('/api/sources/use', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({url: item.url, title: item.title})}); } catch(e) {}
        if (!window._usedUrls) window._usedUrls = new Set();
        window._usedUrls.add(item.url);
      }

      // Refresh drafts queue
      loadDrafts();

      // Gentle completion chime
      playChime();

      // Show rich modal success (staged drafts, no auto-publish)
      showModalSuccess(data);

      // Phone push notification
      const count = (data.drafts || []).length;
      sendPhonePush(
        '✨ ' + count + ' draft' + (count === 1 ? '' : 's') + ' ready: ' + data.title.slice(0,40),
        'Staged for ' + (data.scheduled_for || 'review') + '. Open ContentOS to review, approve and launch.',
        'high'
      );
    } else {
      showModalError(data.error || 'Unknown error occurred during generation.');
      if (btn) { btn.innerHTML = originalText; btn.disabled = false; }
    }
  } catch (err) {
    showModalError('Network or server connection failed: ' + err);
    if (btn) { btn.innerHTML = originalText; btn.disabled = false; }
  }
}

function playChime() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = 'sine';
    const now = ctx.currentTime;
    osc.frequency.setValueAtTime(523.25, now);
    osc.frequency.setValueAtTime(783.99, now + 0.15);
    gain.gain.setValueAtTime(0.15, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.55);
    osc.start(now);
    osc.stop(now + 0.55);
  } catch(e) {}
}

function getTodaySlot(timeStr) {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd} ${timeStr}`;
}

function getTomorrowSlot(timeStr) {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd} ${timeStr}`;
}

async function updateDraftSchedule(id, slot) {
  if (!slot) return;
  await fetch(`/api/drafts/${id}/schedule`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({scheduled_for: slot})
  });
  loadDrafts();
}

function cleanMarkdownForSocial(str) {
  if (!str) return '';
  return str.split('\n').map(line => {
    let s = line.trim();
    if (s.startsWith('### ')) {
      let t = s.slice(4).replace(/\*\*/g, '').trim();
      return t.endsWith(':') ? t : t + ':';
    }
    if (s.startsWith('**') && s.endsWith('**') && s.length > 4 && !s.slice(2, -2).includes('\n')) {
      let t = s.slice(2, -2).trim();
      return t.endsWith(':') ? t : t + ':';
    }
    return line.replace(/\*\*(.*?)\*\*/g, '$1').replace(/(^|[^*])\*(?!\*)(.*?)\*(?!\*)/g, '$1$2');
  }).join('\n');
}

function cleanForX(str) {
  if (!str) return '';
  if (str.includes('\n\n---\n\n')) {
    const tweets = str.split('\n\n---\n\n');
    return tweets[0].trim();
  }
  let cleaned = str.replace(/\*\*(.*?)\*\*/g, '$1').replace(/^###\s+/gm, '').trim();
  if (cleaned.length <= 280) return cleaned;
  let cut = cleaned.slice(0, 277);
  let lastSpace = cut.lastIndexOf(' ');
  return (lastSpace > 100 ? cut.slice(0, lastSpace) : cut) + '…';
}

const PLATFORM_LAUNCH = {
  LinkedIn: {url: 'https://www.linkedin.com/feed/', label: 'LinkedIn', color: '#0077b5'},
  X: {url: 'https://x.com/compose/post', label: 'X', color: '#1da1f2'},
  Facebook: {url: 'https://www.facebook.com/', label: 'Facebook', color: '#1877f2'},
  Instagram: {url: 'https://www.instagram.com/', label: 'Instagram', color: '#c13584'},
  YouTube: {url: 'https://studio.youtube.com/', label: 'YouTube Studio', color: '#cc0000'},
  General: {url: 'https://www.linkedin.com/feed/', label: 'LinkedIn', color: '#0077b5'}
};
function launchMeta(platform) {
  return PLATFORM_LAUNCH[platform] || {url: 'https://www.linkedin.com/feed/', label: platform || 'Social', color: '#4a5568'};
}

function copyAndLaunch(id, url) {
  const d = (window._drafts || {})[id];
  if (!d) return;
  if (d.status !== 'Approved') {
    alert('This draft is not approved yet. Click ✅ Approve first — ContentOS never publishes without human approval.');
    return;
  }
  let text = d.body;
  if (d.platform === 'LinkedIn') {
    text = cleanMarkdownForSocial(text);
  } else if (d.platform === 'X') {
    text = cleanForX(text);
  }
  copyText(text);
  window.open(url, '_blank');
  markPublished(id);
}

async function useStory(idx) {
  const item = (window._sources || [])[idx];
  if (!item) return;
  cancelDraftEdit(true); // loading a story starts a new draft
  document.getElementById('draftTitle').value = item.title;
  document.getElementById('draftSourceUrl').value = item.url;
  
  // Trigger Deep Article Extraction
  const bodyEl = document.getElementById('draftBody');
  bodyEl.value = 'Extracting full article text from source...';
  
  try {
    const res = await fetch('/api/read-article?url=' + encodeURIComponent(item.url));
    const data = await res.json();
    if (data.text && !data.text.startsWith('(')) {
      bodyEl.value = data.text;
    } else {
      bodyEl.value = item.snippet;
    }
  } catch (e) {
    bodyEl.value = item.snippet;
  }
  
  updateCharCount();
  document.getElementById('draftTitle').focus();

  // Mark this story as used
  if (item.url) {
    try { fetch('/api/sources/use', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({url: item.url, title: item.title})}); } catch(e) {}
    if (!window._usedUrls) window._usedUrls = new Set();
    window._usedUrls.add(item.url);
  }
}

function updateCharCount() {
  const text = document.getElementById('draftBody').value;
  const platform = document.getElementById('draftPlatform').value;
  const count = text.length;
  const counter = document.getElementById('charCounter');
  let limit = 3000;
  if (platform === 'X') limit = 280;
  else if (platform === 'LinkedIn') limit = 3000;
  else if (platform === 'YouTube') limit = 5000;
  else if (platform === 'Facebook') limit = 63200;
  else if (platform === 'Instagram' || platform === 'Threads') limit = 2200;

  if (platform === 'X' && text.includes('\n\n---\n\n')) {
    const tweets = text.split('\n\n---\n\n');
    const maxTweet = Math.max(...tweets.map(t => t.length));
    counter.textContent = `${tweets.length} Tweets in Thread (Longest: ${maxTweet}/280)`;
    if (maxTweet > 280) {
      counter.classList.add('limit-exceeded');
    } else {
      counter.classList.remove('limit-exceeded');
    }
  } else {
    counter.textContent = `${count} / ${limit} characters (${platform})`;
    if (count > limit) {
      counter.classList.add('limit-exceeded');
    } else {
      counter.classList.remove('limit-exceeded');
    }
  }
}

async function generateAiDraft() {
  const title = document.getElementById('draftTitle').value.trim();
  const context = document.getElementById('draftBody').value.trim();
  const platform = document.getElementById('draftPlatform').value;
  const tone = document.getElementById('draftTone').value;
  const provider = document.getElementById('aiProvider').value;
  const useRoundtable = document.getElementById('chkRoundtable').checked;

  if (!title && !context) {
    alert('Please enter a headline or draft topic first.');
    return;
  }

  const btn = document.getElementById('btnAiDraft');
  btn.disabled = true;
  btn.textContent = useRoundtable ? '🤖 4 Agents Conferring…' : 'Generating…';
  
  try {
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        task: useRoundtable ? 'roundtable' : 'draft_post',
        title: title || 'Thought Leadership',
        context: context,
        platform: platform,
        tone: tone,
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
    alert('Failed to connect to AI engine: ' + err);
  } finally {
    btn.disabled = false;
    btn.textContent = '⚡ Generate Post';
  }
}

async function formatThread() {
  const text = document.getElementById('draftBody').value.trim();
  if (!text) { alert('Generate or enter a post body first.'); return; }
  try {
    const res = await fetch('/api/format-thread', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text})
    });
    const data = await res.json();
    if (data.ok && data.tweets) {
      document.getElementById('draftBody').value = data.tweets.join('\n\n---\n\n');
      document.getElementById('draftPlatform').value = 'X';
      updateCharCount();
    }
  } catch (e) {
    alert('Failed to format thread.');
  }
}

async function formatCarousel() {
  const title = document.getElementById('draftTitle').value.trim() || 'Key Insights';
  const text = document.getElementById('draftBody').value.trim();
  if (!text) { alert('Generate or enter a post body first.'); return; }
  try {
    const res = await fetch('/api/format-carousel', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({title, text})
    });
    const data = await res.json();
    if (data.ok && data.slides) {
      const formatted = data.slides.map(s => `[Slide ${s.slide}: ${s.heading}]\n${s.body}`).join('\n\n');
      document.getElementById('draftBody').value = formatted;
      document.getElementById('draftPlatform').value = 'LinkedIn';
      updateCharCount();
      // Render Phase D Visual Slide Preview
      const slidesEl = document.getElementById('carouselSlides');
      slidesEl.innerHTML = data.slides.map(s => `
        <div class="carousel-slide">
          <div class="carousel-slide-num">Slide ${s.slide} of ${data.slides.length}</div>
          <h4>${escapeHtml(s.heading)}</h4>
          <p>${escapeHtml(s.body)}</p>
        </div>
      `).join('');
      document.getElementById('carouselPreview').style.display = 'block';
    }
  } catch (e) {
    alert('Failed to format carousel.');
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

async function searchGifs() {
  const q = document.getElementById('gifSearchQuery').value.trim();
  if (!q) return;
  const grid = document.getElementById('gifResults');
  grid.innerHTML = '<div style="color:var(--muted);grid-column:1/-1">Searching GIFs…</div>';
  try {
    const res = await fetch('/api/gifs?q=' + encodeURIComponent(q));
    const items = await res.json();
    if (!items.length) {
      grid.innerHTML = '<div style="color:var(--muted);grid-column:1/-1">No GIFs found.</div>';
      return;
    }
    window._gifs = items;
    grid.innerHTML = items.map((g, idx) => `
      <img src="${g.url}" alt="${escapeHtml(g.title)}" onclick="attachGif(${idx})">
    `).join('');
  } catch (e) {
    grid.innerHTML = '<div style="color:var(--danger);grid-column:1/-1">GIF search failed.</div>';
  }
}

function attachGif(idx) {
  const g = (window._gifs || [])[idx];
  if (!g) return;
  document.getElementById('draftMediaUrl').value = g.original;
  document.getElementById('attachedMediaUrl').textContent = g.original;
  document.getElementById('attachedMediaPreview').style.display = 'block';
}

function clearAttachedMedia() {
  document.getElementById('draftMediaUrl').value = '';
  document.getElementById('attachedMediaUrl').textContent = '';
  document.getElementById('attachedMediaPreview').style.display = 'none';
}

async function runAutopilot() {
  const btn = document.getElementById('btnAutopilot');
  btn.disabled = true;
  btn.textContent = 'Autopilot Running…';
  const feedUrl = document.getElementById('rssPreset').value;
  const provider = document.getElementById('aiProvider').value;

  try {
    const res = await fetch(`/api/autopilot?feed_url=${encodeURIComponent(feedUrl)}&provider=${encodeURIComponent(provider)}`, {method: 'POST'});
    const data = await res.json();
    if (data.ok) {
      alert(`🎉 Autopilot Complete: Generated ${data.count} ready-to-review drafts in your queue!`);
      loadDrafts();
    } else {
      alert('Autopilot failed: ' + data.error);
    }
  } catch (e) {
    alert('Failed to connect to Autopilot service.');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Draft Top 3 Stories';
  }
}

let _editingDraftId = null;

async function saveDraft() {
  const title = document.getElementById('draftTitle').value.trim();
  const body = document.getElementById('draftBody').value;
  const platform = document.getElementById('draftPlatform').value;
  const image_prompt = document.getElementById('draftImagePrompt').value;
  const source_url = document.getElementById('draftSourceUrl').value;
  const media_url = document.getElementById('draftMediaUrl').value;

  if (!title) {
    alert('Title is required.');
    return;
  }

  const editing = _editingDraftId;
  const res = await fetch(editing ? `/api/drafts/${editing}/update` : '/api/drafts', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({title, body, platform, image_prompt, source_url, media_url})
  });
  const data = await res.json();
  const toast = document.getElementById('saveToast');
  if (res.ok) {
    if (editing) {
      toast.textContent = `Draft #${editing} updated — no duplicate created.`;
      cancelDraftEdit(true);
    } else {
      toast.textContent = 'Saved to local database!';
      if (data.id) setEditingDraft(data.id);
    }
    setTimeout(() => { toast.textContent = ''; }, 3000);
    loadDrafts();
  } else {
    toast.textContent = 'Error: ' + (data.error || 'Save failed');
  }
}

function setEditingDraft(id) {
  _editingDraftId = id;
  const badge = document.getElementById('editingBadge');
  const idEl = document.getElementById('editingDraftId');
  const btn = document.getElementById('btnSaveDraft');
  if (badge) badge.style.display = 'inline-flex';
  if (idEl) idEl.textContent = id;
  if (btn) btn.textContent = '💾 Update Draft';
}

function cancelDraftEdit(silent) {
  _editingDraftId = null;
  const badge = document.getElementById('editingBadge');
  const btn = document.getElementById('btnSaveDraft');
  if (badge) badge.style.display = 'none';
  if (btn) btn.textContent = '💾 Save Draft';
  if (!silent) {
    document.getElementById('draftTitle').value = '';
    document.getElementById('draftBody').value = '';
    document.getElementById('draftImagePrompt').value = '';
    document.getElementById('draftSourceUrl').value = '';
    document.getElementById('draftMediaUrl').value = '';
    document.getElementById('attachedMediaPreview').style.display = 'none';
    updateCharCount();
  }
}

function switchQueueTab(tab) {
  window._queueTab = tab;
  const tAct = document.getElementById('tabActive');
  const tRej = document.getElementById('tabRejected');
  const tArc = document.getElementById('tabArchive');
  if (tAct) tAct.classList.toggle('chip-active', tab === 'active');
  if (tRej) tRej.classList.toggle('chip-active', tab === 'rejected');
  if (tArc) tArc.classList.toggle('chip-active', tab === 'published');
  loadDrafts();
}

async function saveMetrics(id) {
  const live_url = (document.getElementById(`liveUrl_${id}`) || {}).value || '';
  const views = parseInt((document.getElementById(`views_${id}`) || {}).value || '0', 10);
  const engagements = parseInt((document.getElementById(`eng_${id}`) || {}).value || '0', 10);
  const res = await fetch(`/api/drafts/${id}/metrics`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({live_url, views, engagements})
  });
  const data = await res.json();
  if (data.ok) {
    const toast = document.getElementById('saveToast');
    if (toast) {
      toast.textContent = '📊 Performance metrics saved!';
      toast.style.color = '#9ae6b4';
      setTimeout(() => { toast.textContent = ''; }, 3000);
    }
    loadDrafts();
  }
}

async function loadDrafts() {
  const res = await fetch('/api/drafts');
  const drafts = await res.json();
  const queueEl = document.getElementById('draftsQueue');

  window._drafts = {};
  drafts.forEach(d => { window._drafts[d.id] = d; });

  const activeDrafts = drafts.filter(d => d.status !== 'Published' && d.status !== 'Rejected');
  const rejectedDrafts = drafts.filter(d => d.status === 'Rejected');
  const publishedDrafts = drafts.filter(d => d.status === 'Published');
  const actCountEl = document.getElementById('activeCount');
  const rejCountEl = document.getElementById('rejectedCount');
  const arcCountEl = document.getElementById('archiveCount');
  if (actCountEl) actCountEl.textContent = activeDrafts.length;
  if (rejCountEl) rejCountEl.textContent = rejectedDrafts.length;
  if (arcCountEl) arcCountEl.textContent = publishedDrafts.length;

  const tab = window._queueTab || 'active';
  const displayList = tab === 'published' ? publishedDrafts
    : tab === 'rejected' ? rejectedDrafts
    : activeDrafts;
  document.getElementById('queueCount').textContent = `${displayList.length} items`;

  if (!displayList.length) {
    queueEl.innerHTML = tab === 'published'
      ? '<div style="color:var(--muted);padding:16px 0;text-align:center">No published stories in archive yet. Once you publish stories from the Active Queue, they will be tracked here!</div>'
      : tab === 'rejected'
        ? '<div style="color:var(--muted);padding:16px 0;text-align:center">No rejected drafts. Rejected ideas stay here (with their reason) so you can restore or delete them.</div>'
        : '<div style="color:var(--muted);padding:16px 0;text-align:center">No active drafts in queue. Pick a story from Column 1 or write one on the left.</div>';
    return;
  }

  if (tab === 'rejected') {
    queueEl.innerHTML = displayList.map(d => `
      <div class="item-card" style="border-left: 3px solid #742a2a;background:#180f12;opacity:.95">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
          <h3 style="margin:0">${escapeHtml(d.title)}</h3>
          <span class="status-pill status-rejected">REJECTED</span>
        </div>
        <div class="item-meta" style="margin-top:6px">
          <span>${escapeHtml(d.platform)}</span> · <span>${escapeHtml(d.updated_at.slice(0,10))}</span>
        </div>
        ${d.rejection_reason ? `
          <div style="background:#2a1518;border:1px solid #742a2a;border-radius:6px;padding:7px 10px;margin:8px 0;font-size:11px;color:#feb2b2">
            <strong>Reason:</strong> ${escapeHtml(d.rejection_reason)}
          </div>
        ` : ''}
        <p style="white-space:pre-wrap;line-height:1.4;max-height:140px;overflow-y:auto;background:#090d12;padding:8px;border-radius:4px;font-size:12px;margin:8px 0;border:1px solid #1a2430">${escapeHtml(d.body)}</p>
        <div style="display:flex;gap:6px;margin-top:8px">
          <button class="btn btn-small" style="background:#22543d;color:#9ae6b4;border:1px solid #2f855a;font-weight:700" onclick="restoreDraft(${d.id})">↩️ Restore to Queue</button>
          <button class="btn btn-secondary btn-small" onclick="copyDraftText(${d.id})">📋 Copy Text</button>
          <button class="btn btn-danger btn-small" onclick="deleteDraft(${d.id})">Delete Permanently</button>
        </div>
      </div>
    `).join('');
    return;
  }

  if (tab === 'published') {
    queueEl.innerHTML = displayList.map(d => `
      <div class="item-card" style="border-left: 3px solid #3182ce;background:#0d1520">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
          <h3 style="margin:0">${escapeHtml(d.title)}</h3>
          <span class="status-pill status-published">PUBLISHED</span>
        </div>
        <div class="item-meta" style="margin-top:6px">
          <span>${escapeHtml(d.platform)}</span> · <span>Published: ${escapeHtml(d.updated_at.slice(0,16))}</span>
        </div>

        <p style="white-space:pre-wrap;line-height:1.4;max-height:120px;overflow-y:auto;background:#090d12;padding:8px;border-radius:4px;font-size:12px;margin:8px 0;border:1px solid #1a2430">${escapeHtml(d.body)}</p>

        <!-- LIVE URL & 48H METRICS TRACKER -->
        <div style="background:#142233;border:1px solid #2b6cb0;border-radius:6px;padding:8px 10px;margin:8px 0">
          <div style="font-size:11px;color:#90cdf4;font-weight:700;margin-bottom:6px">📊 Performance & Live Post Tracking</div>
          <div style="margin-bottom:6px">
            <label style="font-size:10px;color:var(--muted);display:block;margin:0 0 2px">Live Post URL</label>
            <div style="display:flex;gap:4px">
              <input id="liveUrl_${d.id}" value="${escapeHtml(d.live_url || '')}" placeholder="Paste live post link (e.g. https://linkedin.com/...)" style="font-size:11px;padding:4px 6px;flex:1">
              ${d.live_url ? `<a href="${escapeHtml(d.live_url)}" target="_blank" class="btn btn-small btn-secondary" style="text-decoration:none;font-size:11px">Open ↗</a>` : ''}
            </div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr auto;gap:6px;align-items:flex-end">
            <div>
              <label style="font-size:10px;color:var(--muted);display:block;margin:0 0 2px">Views / Impressions</label>
              <input type="number" id="views_${d.id}" value="${d.views || 0}" style="font-size:11px;padding:4px 6px;width:100%">
            </div>
            <div>
              <label style="font-size:10px;color:var(--muted);display:block;margin:0 0 2px">Reactions / Comments</label>
              <input type="number" id="eng_${d.id}" value="${d.engagements || 0}" style="font-size:11px;padding:4px 6px;width:100%">
            </div>
            <button class="btn btn-small" style="background:#2b6cb0;color:#fff;font-weight:700;font-size:11px;padding:5px 10px" onclick="saveMetrics(${d.id})">💾 Save Stats</button>
          </div>
        </div>

        <div style="display:flex;gap:6px;margin-top:8px">
          <button class="btn btn-secondary btn-small" onclick="copyDraftText(${d.id})">📋 Copy Text</button>
          <button class="btn btn-secondary btn-small" onclick="editDraftInStudio(${d.id})">🔄 Repurpose in Studio</button>
          <button class="btn btn-danger btn-small" onclick="deleteDraft(${d.id})">Delete</button>
        </div>
      </div>
    `).join('');
    return;
  }

  // Active Drafts Queue
  queueEl.innerHTML = displayList.map(d => {
    const statusClass = d.status === 'Approved' ? 'status-approved' : 'status-draft';
    const lm = launchMeta(d.platform);
    const isApproved = d.status === 'Approved';
    return `
      <div class="item-card" style="border-left: 3px solid ${isApproved ? '#38a169' : '#4a5568'}">
        <!-- TOP 1-CLICK LAUNCH BANNER (approval-gated) -->
        <div style="background:#142233;border:1px solid ${isApproved ? '#2b6cb0' : '#2d3748'};border-radius:6px;padding:8px 10px;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center;gap:8px">
          <div>
            <div style="font-size:10px;color:${isApproved ? '#90cdf4' : '#a0aec0'};font-weight:700;letter-spacing:0.5px">${isApproved ? '⚡ APPROVED — READY TO PUBLISH' : '🔒 APPROVAL REQUIRED'}</div>
            <div style="font-size:11px;color:#e2e8f0;margin-top:2px">${isApproved ? `Copies text & opens ${escapeHtml(lm.label)} in browser` : 'Approve this draft to unlock 1-click launch'}</div>
          </div>
          <div>
            ${isApproved
              ? `<button class="btn btn-small" style="background:${lm.color};color:#fff;font-weight:700;padding:6px 12px;font-size:12px" onclick="copyAndLaunch(${d.id}, '${lm.url}')">🚀 Launch to ${escapeHtml(lm.label)} ↗</button>`
              : `<button class="btn btn-small" style="background:#1a202c;color:#718096;border:1px solid #2d3748;font-weight:700;padding:6px 12px;font-size:12px;cursor:not-allowed" disabled>🔒 Approve to launch</button>`}
          </div>
        </div>

        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
          <h3 style="margin:0">${escapeHtml(d.title)}</h3>
          <div style="display:flex;gap:4px;align-items:center;flex-shrink:0">
            <span class="scheduled-pill">📅 ${escapeHtml(d.scheduled_for || 'Unscheduled')}</span>
            <span class="status-pill ${statusClass}">${escapeHtml(d.status)}</span>
          </div>
        </div>
        <div class="item-meta" style="justify-content:space-between;margin-top:6px">
          <div><span>${escapeHtml(d.platform)}</span> · <span>${escapeHtml(d.updated_at.slice(0,10))}</span></div>
          <select class="slot-select" onchange="updateDraftSchedule(${d.id}, this.value)">
            <option value="">Reschedule slot…</option>
            <option value="${getTodaySlot('09:00')}">Today 9:00 AM</option>
            <option value="${getTodaySlot('14:00')}">Today 2:00 PM</option>
            <option value="${getTodaySlot('18:30')}">Today 6:30 PM</option>
            <option value="${getTomorrowSlot('09:00')}">Tomorrow 9:00 AM</option>
            <option value="${getTomorrowSlot('14:00')}">Tomorrow 2:00 PM</option>
            <option value="${getTomorrowSlot('18:30')}">Tomorrow 6:30 PM</option>
          </select>
        </div>
        <p style="white-space:pre-wrap;line-height:1.4">${escapeHtml(d.body)}</p>

        ${(d.platform === 'X' && d.body.length > 280 && !d.body.includes('\n\n---\n\n')) ? `
          <div style="background:#3d1a14;border:1px solid #c53030;border-radius:6px;padding:8px 10px;margin:8px 0;display:flex;justify-content:space-between;align-items:center;gap:6px">
            <span style="font-size:11px;color:#feb2b2;font-weight:600">⚠️ ${d.body.length} chars (Exceeds X limit of 280)</span>
            <div style="display:flex;gap:4px">
              <button class="btn btn-small" style="background:#e53e3e;color:#fff;padding:3px 8px;font-size:11px;font-weight:700" onclick="autoFitXDraft(${d.id})">✂️ Auto-Fit ≤ 280</button>
              <button class="btn btn-small" style="background:#2b6cb0;color:#fff;padding:3px 8px;font-size:11px;font-weight:700" onclick="splitDraftToThread(${d.id})">🧵 Split to Thread</button>
            </div>
          </div>
        ` : ''}

        ${d.media_url ? `
          <div style="margin:8px 0;background:#1a202c;border:1px solid #2d3748;border-radius:6px;padding:8px">
            <img src="${escapeHtml(d.media_url)}" style="max-height:160px;border-radius:4px;display:block;margin-bottom:8px" alt="Attached Media">
            <div style="display:flex;gap:6px;align-items:center">
              <button class="btn btn-secondary btn-small" onclick="openMediaFinder('${escapeHtml(d.media_url.split('/').pop())}')">📂 Reveal Image in Finder</button>
              <a href="${escapeHtml(d.media_url)}" download class="btn btn-secondary btn-small" style="text-decoration:none">📥 Download</a>
              <span style="font-size:10px;color:var(--muted)">Drag into your post!</span>
            </div>
          </div>
        ` : ''}
        
        ${d.image_prompt ? `
          <div class="image-prompt-box">
            <strong>🎨 Visual Prompt:</strong> ${escapeHtml(d.image_prompt)}
            <div style="margin-top:4px">
              <button class="btn btn-secondary btn-small" onclick="copyPromptText(${d.id})">Copy Prompt</button>
            </div>
          </div>
        ` : ''}

        <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;padding-top:10px;border-top:1px solid var(--line)">
          <button class="btn btn-secondary btn-small" onclick="editDraftInStudio(${d.id})">✏️ Edit in Studio</button>
          <button class="btn btn-secondary btn-small" onclick="copyDraftText(${d.id})">📋 Copy Text</button>
          <button class="btn btn-secondary btn-small" onclick="downloadMarkdown(${d.id})">📥 Export .MD</button>
          ${d.status !== 'Approved' ? `
            <button class="btn btn-approve btn-small" onclick="approveDraft(${d.id})">✅ Approve</button>
            <button class="btn btn-small" style="background:transparent;border:1px solid #742a2a;color:#feb2b2" onclick="rejectDraft(${d.id})">🚫 Reject</button>
          ` : `
            <button class="btn btn-secondary btn-small" style="color:#bee3f8" onclick="markPublished(${d.id})">Mark Published</button>
          `}
          <button class="btn btn-secondary btn-small" onclick="notifyDraft(${d.id})">🔔 Notify</button>
          <button class="btn btn-danger btn-small" onclick="deleteDraft(${d.id})">Delete</button>
        </div>
      </div>
    `;
  }).join('');
}

function copyDraftText(id) {
  const d = (window._drafts || {})[id];
  if (!d || !d.body) return;
  let text = d.body;
  if (d.platform === 'LinkedIn') {
    text = cleanMarkdownForSocial(text);
  } else if (d.platform === 'X') {
    text = cleanForX(text);
  }
  copyText(text);
}

async function autoFitXDraft(id) {
  const d = (window._drafts || {})[id];
  if (!d) return;
  const res = await fetch('/api/format-x', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({text: d.body})
  });
  const data = await res.json();
  if (data.ok && data.text) {
    await fetch(`/api/drafts/${id}/update-body`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({body: data.text})
    });
    loadDrafts();
  }
}

async function splitDraftToThread(id) {
  const d = (window._drafts || {})[id];
  if (!d) return;
  const res = await fetch('/api/format-thread', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({text: d.body})
  });
  const data = await res.json();
  if (data.ok && data.tweets) {
    const threadBody = data.tweets.join('\n\n---\n\n');
    await fetch(`/api/drafts/${id}/update-body`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({body: threadBody})
    });
    loadDrafts();
  }
}

function copyPromptText(id) {
  const d = (window._drafts || {})[id];
  if (d && d.image_prompt) copyText(d.image_prompt);
}

async function approveDraft(id) {
  await fetch(`/api/drafts/${id}/approve`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
  loadDrafts();
}

async function rejectDraft(id) {
  const reason = prompt(
    'Why are you rejecting this draft? (optional)\n\n' +
    'Heads up: rejecting keeps the draft in the Rejected tab so you can restore it later. It is not deleted.',
    ''
  );
  if (reason === null) return; // user cancelled
  await fetch(`/api/drafts/${id}/reject`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({reason: reason})
  });
  loadDrafts();
}

async function restoreDraft(id) {
  await fetch(`/api/drafts/${id}/restore`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: '{}'
  });
  loadDrafts();
}

async function markPublished(id) {
  await fetch(`/api/drafts/${id}/publish`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
  loadDrafts();
}

async function deleteDraft(id) {
  if (!confirm('Are you sure you want to delete this draft?')) return;
  await fetch(`/api/drafts/${id}`, {method: 'DELETE'});
  loadDrafts();
}

function copyText(str) {
  navigator.clipboard.writeText(str).then(() => {
    const toast = document.getElementById('saveToast');
    if (toast) {
      toast.textContent = '📋 Copied to clipboard!';
      toast.style.color = '#9ae6b4';
      setTimeout(() => { toast.textContent = ''; }, 3000);
    }
  });
}

function editDraftInStudio(id) {
  const d = (window._drafts || {})[id];
  if (!d) return;
  document.getElementById('draftTitle').value = d.title;
  document.getElementById('draftBody').value = d.body;
  document.getElementById('draftPlatform').value = d.platform;
  document.getElementById('draftImagePrompt').value = d.image_prompt || '';
  document.getElementById('draftSourceUrl').value = d.source_url || '';
  document.getElementById('draftMediaUrl').value = d.media_url || '';
  if (d.media_url) {
    document.getElementById('attachedMediaUrl').textContent = d.media_url;
    document.getElementById('attachedMediaPreview').style.display = 'block';
  }
  setEditingDraft(id);
  updateCharCount();
  const titleEl = document.getElementById('draftTitle');
  if (titleEl && titleEl.scrollIntoView) titleEl.scrollIntoView({behavior: 'smooth', block: 'center'});
  document.getElementById('draftBody').focus();
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

// ─────────────────────────────────────────────────────────────────────────────
// PHASE A: OMNI-PLATFORM REPURPOSING
// ─────────────────────────────────────────────────────────────────────────────
let _omniBundle = {};
async function generateOmniBundle() {
  const title = document.getElementById('draftTitle').value.trim();
  const context = document.getElementById('draftBody').value.trim();
  const provider = document.getElementById('aiProvider').value;
  const tone = document.getElementById('draftTone').value;
  if (!title && !context) { alert('Enter a title or article text first.'); return; }
  const btn = document.getElementById('btnOmni');
  btn.disabled = true; btn.textContent = '⏳ Repurposing All 4…';
  try {
    const liRes = await fetch('/api/generate', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({task:'draft_post', title, context, platform:'LinkedIn', tone, provider})});
    const liData = await liRes.json();
    btn.textContent = '⏳ Formatted LinkedIn (1/4)…';

    const xRes = await fetch('/api/generate', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({task:'draft_post', title, context, platform:'X', tone, provider})});
    const xData = await xRes.json();
    btn.textContent = '⏳ Formatted X Thread (2/4)…';

    const ytRes = await fetch('/api/generate', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({task:'draft_post', title, context, platform:'YouTube', tone, provider})});
    const ytData = await ytRes.json();
    btn.textContent = '⏳ Formatted YouTube Hub (3/4)…';

    const fbRes = await fetch('/api/generate', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({task:'draft_post', title, context, platform:'Facebook', tone, provider})});
    const fbData = await fbRes.json();
    btn.textContent = '⏳ Formatted Facebook (4/4)…';

    _omniBundle = {
      linkedin: liData.ok ? liData.result : 'Error: ' + liData.error,
      x: xData.ok ? xData.result : 'Error: ' + xData.error,
      youtube: ytData.ok ? ytData.result : 'Error: ' + ytData.error,
      facebook: fbData.ok ? fbData.result : 'Error: ' + fbData.error,
      image_prompt: liData.image_prompt || ''
    };
    document.getElementById('omniLinkedin').textContent = _omniBundle.linkedin;
    document.getElementById('omniX').textContent = _omniBundle.x;
    document.getElementById('omniYoutube').textContent = _omniBundle.youtube;
    document.getElementById('omniFacebook').textContent = _omniBundle.facebook;
    document.getElementById('omniBundleTabs').style.display = 'block';
    if (liData.image_prompt) document.getElementById('draftImagePrompt').value = liData.image_prompt;
  } catch(e) { alert('Omni-bundle generation failed: ' + e); }
  finally { btn.disabled = false; btn.textContent = 'Generate All Platforms'; }
}

function showOmniTab(tab, el) {
  ['linkedin','x','youtube','facebook'].forEach(t => {
    document.getElementById('omni' + t.charAt(0).toUpperCase() + t.slice(1)).style.display = t === tab ? 'block' : 'none';
  });
  document.querySelectorAll('.omni-platform-tab').forEach(b => b.classList.remove('active'));
  el.classList.add('active');
}

function loadOmniToDraft(tab) {
  const text = _omniBundle[tab];
  if (!text) return;
  document.getElementById('draftBody').value = text;
  const map = {linkedin: 'LinkedIn', x: 'X', youtube: 'YouTube', facebook: 'Facebook'};
  document.getElementById('draftPlatform').value = map[tab] || 'General';
  cancelDraftEdit(true); // loading a variant starts a new draft
  updateCharCount();
}

async function saveOmniBundle() {
  if (!_omniBundle.linkedin) { alert('Generate bundle first.'); return; }
  const title = document.getElementById('draftTitle').value.trim() || 'Omni Bundle';
  const platforms = [{key:'linkedin', platform:'LinkedIn'}, {key:'x', platform:'X'}, {key:'youtube', platform:'YouTube'}, {key:'facebook', platform:'Facebook'}];
  for (const p of platforms) {
    await fetch('/api/drafts', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({title: `${title} (${p.platform})`, body: _omniBundle[p.key], platform: p.platform,
        image_prompt: _omniBundle.image_prompt || '', source_url: '', media_url: ''})
    });
  }
  alert('✅ Saved 4 platform drafts to queue!');
  loadDrafts();
}

// ─────────────────────────────────────────────────────────────────────────────
// PHASE C: DRAW THINGS LOCAL IMAGE GENERATION
// ─────────────────────────────────────────────────────────────────────────────
let _generatedImageFilename = '';
let _imageBackendLabel = 'Local Image';
async function checkDrawThingsStatus() {
  const el = document.getElementById('dtStatus');
  const btn = document.getElementById('btnGenImage');
  try {
    const res = await fetch('/api/draw-things-status');
    const data = await res.json();
    if (!data.supported) {
      // Capability layer: this host has no local image backend (e.g. Windows).
      // Hide the feature entirely; the pipeline uses the GIF fallback instead.
      if (btn) btn.style.display = 'none';
      if (el) el.style.display = 'none';
      return;
    }
    _imageBackendLabel = data.label || 'Local Image';
    if (btn) btn.textContent = '🖼️ ' + _imageBackendLabel + ' (Local AI)';
    if (data.available) {
      el.innerHTML = '<span class="draw-things-status dt-online">🟢 ' + _imageBackendLabel + ' Online</span>';
    } else {
      el.innerHTML = '<span class="draw-things-status" style="background:#1b251f;border:1px solid #28382e;color:var(--muted);font-size:11px;padding:3px 8px;border-radius:4px;display:inline-block">⚪ ' + _imageBackendLabel + ' Offline (start the local image server)</span>';
    }
  } catch(e) {}
}

async function generateLocalImage() {
  const prompt = document.getElementById('draftImagePrompt').value.trim();
  if (!prompt) { alert('Generate or enter a visual prompt first.'); return; }
  const btn = document.getElementById('btnGenImage');
  btn.disabled = true; btn.textContent = '⏳ Generating…';
  try {
    const res = await fetch('/api/generate-image', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({prompt, width: 1024, height: 576, steps: 20})
    });
    const data = await res.json();
    if (data.ok) {
      _generatedImageFilename = data.filename;
      document.getElementById('generatedImg').src = `/api/media/${data.filename}`;
      document.getElementById('generatedImagePreview').style.display = 'block';
    } else {
      alert(_imageBackendLabel + ': ' + data.error);
    }
  } catch(e) { alert('Failed to reach the local image API: ' + e); }
  finally { btn.disabled = false; btn.textContent = '🖼️ ' + _imageBackendLabel + ' (Local AI)'; }
}

function attachGeneratedImage() {
  if (!_generatedImageFilename) return;
  const url = `/api/media/${_generatedImageFilename}`;
  document.getElementById('draftMediaUrl').value = url;
  document.getElementById('attachedMediaUrl').textContent = _generatedImageFilename;
  document.getElementById('attachedMediaPreview').style.display = 'block';
}

// ─────────────────────────────────────────────────────────────────────────────
// PHASE E: WEBHOOKS
// ─────────────────────────────────────────────────────────────────────────────
function toggleWebhookSettings() {
  const el = document.getElementById('webhookSettings');
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

async function saveWebhooks() {
  const discord = document.getElementById('discordWebhook').value.trim();
  const slack = document.getElementById('slackWebhook').value.trim();
  const custom = document.getElementById('customWebhook').value.trim();
  const res = await fetch('/api/webhooks/save', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({discord, slack, custom})
  });
  const data = await res.json();
  alert(data.ok ? '✅ Webhook URLs saved!' : 'Error: ' + data.error);
}

async function testWebhook(target) {
  const res = await fetch('/api/webhooks/test', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({target})
  });
  const data = await res.json();
  alert(data.ok ? `✅ Test webhook delivered! Status: ${data.status}` : `❌ Failed: ${data.error}`);
}

async function notifyDraft(id) {
  const d = (window._drafts || {})[id];
  if (!d) return;
  const target = prompt('Send to which webhook? (discord / slack / custom):', 'discord');
  if (!target) return;
  const res = await fetch(`/api/drafts/${id}/notify`, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({target})
  });
  const data = await res.json();
  alert(data.ok ? `✅ Draft notification sent to ${target}!` : `❌ Notification error: ${data.error}`);
}

// Initial bootstrap
loadStatus();
// Default to Apple Developer News on load
document.getElementById('rssPreset').value = 'https://developer.apple.com/news/rss/news.rss';
fetchFeed('https://developer.apple.com/news/rss/news.rss');
loadDrafts();
loadRejectedSources();
checkDrawThingsStatus();
setInterval(checkDrawThingsStatus, 30000);
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
                # Capability layer: fill platform-specific labels at serve time so
                # Windows never renders Draw Things UI, even before JS runs.
                if LOCAL_IMAGE_ENABLED:
                    step3_text = f"Painting visual art with {IMAGE_BACKEND_LABEL} on Mac GPU."
                else:
                    step3_text = "Selecting fallback media (GIF)."
                page = (
                    HTML
                    .replace("__IMAGE_LABEL__", IMAGE_BACKEND_LABEL or "Local Image")
                    .replace("__IMAGE_STEP3__", step3_text)
                )
                self._send(page.encode("utf-8"))
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
                    # Filter out stories the user has rejected (persisted).
                    with db() as conn:
                        rejected = {r[0] for r in conn.execute("SELECT url FROM sources WHERE status = 'rejected'").fetchall()}
                    if rejected:
                        stories = [s for s in stories if s.get("url") not in rejected]
                    if not stories:
                        stories = [{"title": "No new stories (all filtered). Refresh or restore rejected stories.", "url": "", "snippet": ""}]
                    self.send_json(stories)
                except Exception as exc:
                    self.send_error_json(500, str(exc))
                return

            if path == "/api/read-article":
                art_url = query.get("url", [""])[0]
                text = extract_article_text(art_url)
                self.send_json({"url": art_url, "text": text})
                return

            if path == "/api/gifs":
                q = query.get("q", [""])[0]
                results = search_gifs(q)
                self.send_json(results)
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

            if path == "/api/sources/rejected":
                with db() as conn:
                    rows = [dict(r) for r in conn.execute("SELECT * FROM sources WHERE status = 'rejected' ORDER BY retrieved_at DESC")]
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

            # Phase C: Draw Things status
            if path == "/api/draw-things-status":
                self.send_json({
                    "available": draw_things_available(),
                    "url": DRAW_THINGS_URL,
                    "supported": LOCAL_IMAGE_ENABLED,
                    "backend": IMAGE_BACKEND,
                    "label": IMAGE_BACKEND_LABEL,
                })
                return

            # Phase C: Serve generated media files
            if path.startswith("/api/media/"):
                filename = path.rsplit("/", 1)[-1]
                if not filename or "/" in filename or ".." in filename or not filename.endswith(".png"):
                    self.send_error_json(400, "Invalid filename")
                    return
                filepath = MEDIA_DIR / filename
                if not filepath.exists():
                    self.send_error_json(404, "Media not found")
                    return
                self._send(filepath.read_bytes(), content_type="image/png")
                return

            # Phase E: Get webhook config (masked)
            if path == "/api/webhooks":
                config = get_webhook_config()
                safe = {k: ("***configured***" if v else "") for k, v in config.items()}
                self.send_json(safe)
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
            query = parse_qs(parsed.query)

            # Autopilot Batch Runner
            if path == "/api/autopilot":
                try:
                    feed_url = query.get("feed_url", ["https://news.ycombinator.com/rss"])[0]
                    provider = query.get("provider", [""])[0]
                    if not provider or provider == "none":
                        provider = "groq:openai/gpt-oss-120b" if os.environ.get("GROQ_API_KEY") else "auto"
                    stories = fetch_rss_feed(feed_url, limit=3)
                    created_count = 0
                    for s in stories:
                        context = s.get("snippet", "")
                        try:
                            deep_text = extract_article_text(s["url"])
                            if deep_text and not deep_text.startswith("("):
                                context = deep_text[:1500]
                        except Exception:
                            pass

                        # If using local Ollama, generate direct high-signal draft to prevent timeouts;
                        # if using Groq or Gemini cloud, run the full 4-agent Roundtable
                        if provider.startswith("ollama:"):
                            sys_p = "You are the JustMeMedia Content Engine. Write high-engagement, brand-aligned posts with zero hype."
                            prompt = (
                                f"Write a high-engagement LinkedIn thought leadership post about:\n"
                                f"Headline: {s['title']}\n"
                                f"Context: {context}\n\n"
                                f"Include a punchy hook, concise takeaways, engaging discussion question, and 3 hashtags."
                            )
                            raw_post = call_ai(provider, prompt, sys_p)
                            final_post = inject_viral_hook(strip_ai_slop(raw_post), s["title"])
                            img_p = f"Photorealistic minimal tech art representing {s['title']}, obsidian and emerald aesthetic, cinematic lighting"
                            res = {"final_post": final_post, "image_prompt": img_p}
                        else:
                            res = run_roundtable(provider, s["title"], context, "LinkedIn", source_url=s.get("url", ""))

                        stamp = now_iso()
                        with db() as conn:
                            conn.execute(
                                """INSERT INTO drafts(title, body, platform, status, image_prompt, source_url, created_at, updated_at)
                                   VALUES(?,?,?,?,?,?,?,?)""",
                                (s["title"][:200], res["final_post"], "LinkedIn", "Draft", res["image_prompt"], s["url"], stamp, stamp)
                            )
                        created_count += 1
                    self.send_json({"ok": True, "count": created_count})
                    return
                except Exception as exc:
                    self.send_json({"ok": False, "error": str(exc)})
                    return

            # Approve draft (human gate)
            if path.startswith("/api/drafts/") and path.endswith("/approve"):
                draft_id = path.split("/")[3]
                stamp = now_iso()
                with db() as conn:
                    row = conn.execute("SELECT platform FROM drafts WHERE id = ?", (draft_id,)).fetchone()
                    if row is None:
                        raise ApiError(404, "Draft not found")
                    conn.execute(
                        "UPDATE drafts SET status = 'Approved', rejection_reason = '', updated_at = ? WHERE id = ?",
                        (stamp, draft_id),
                    )
                    conn.execute(
                        "INSERT INTO approvals(draft_id, approved_at, platform, notes) VALUES(?,?,?,?)",
                        (draft_id, stamp, row["platform"], "Approved by human user"),
                    )
                self.send_json({"ok": True, "status": "Approved"})
                return

            # Reject draft (human gate). Keeps the row + reason instead of deleting it.
            if path.startswith("/api/drafts/") and path.endswith("/reject"):
                draft_id = path.split("/")[3]
                reason = ""
                try:
                    length = int(self.headers.get("Content-Length", "0") or "0")
                    if length > 0:
                        raw = json.loads(self.rfile.read(length).decode("utf-8"))
                        if isinstance(raw, dict):
                            reason = string_field(raw, "reason")
                except Exception:
                    reason = ""
                stamp = now_iso()
                with db() as conn:
                    row = conn.execute("SELECT id FROM drafts WHERE id = ?", (draft_id,)).fetchone()
                    if row is None:
                        raise ApiError(404, "Draft not found")
                    conn.execute(
                        "UPDATE drafts SET status = 'Rejected', rejection_reason = ?, updated_at = ? WHERE id = ?",
                        (reason[:500], stamp, draft_id),
                    )
                self.send_json({"ok": True, "status": "Rejected"})
                return

            # Restore a rejected draft back into the draft queue
            if path.startswith("/api/drafts/") and path.endswith("/restore"):
                draft_id = path.split("/")[3]
                stamp = now_iso()
                with db() as conn:
                    conn.execute(
                        "UPDATE drafts SET status = 'Draft', rejection_reason = '', updated_at = ? WHERE id = ?",
                        (stamp, draft_id),
                    )
                self.send_json({"ok": True, "status": "Draft"})
                return

            # Mark draft published (only after explicit human approval)
            if path.startswith("/api/drafts/") and path.endswith("/publish"):
                draft_id = path.split("/")[3]
                stamp = now_iso()
                with db() as conn:
                    row = conn.execute("SELECT status FROM drafts WHERE id = ?", (draft_id,)).fetchone()
                    if row is None:
                        raise ApiError(404, "Draft not found")
                    if row["status"] != "Approved":
                        raise ApiError(409, "Draft must be Approved before it can be published.")
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

            # Source intake: reject / restore / mark-used
            if path == "/api/sources/reject":
                url = string_field(payload, "url")
                title = string_field(payload, "title") or url
                stamp = now_iso()
                with db() as conn:
                    row = conn.execute("SELECT id FROM sources WHERE url = ?", (url,)).fetchone()
                    if row is None:
                        conn.execute(
                            "INSERT INTO sources(id, url, title, publisher, retrieved_at, status) VALUES(?,?,?,?,?,?)",
                            (f"src_{abs(hash(url))}", url, title[:200], "", stamp, "rejected"),
                        )
                    else:
                        conn.execute("UPDATE sources SET status = 'rejected', title = ?, retrieved_at = ? WHERE url = ?", (title[:200], stamp, url))
                self.send_json({"ok": True, "status": "rejected"})
                return

            if path == "/api/sources/restore":
                url = string_field(payload, "url")
                stamp = now_iso()
                with db() as conn:
                    conn.execute("UPDATE sources SET status = 'new', retrieved_at = ? WHERE url = ?", (stamp, url))
                self.send_json({"ok": True, "status": "new"})
                return

            if path == "/api/sources/use":
                url = string_field(payload, "url")
                title = string_field(payload, "title") or url
                stamp = now_iso()
                with db() as conn:
                    row = conn.execute("SELECT id FROM sources WHERE url = ?", (url,)).fetchone()
                    if row is None:
                        conn.execute(
                            "INSERT INTO sources(id, url, title, publisher, retrieved_at, status) VALUES(?,?,?,?,?,?)",
                            (f"src_{abs(hash(url))}", url, title[:200], "", stamp, "used"),
                        )
                    else:
                        conn.execute("UPDATE sources SET status = 'used', title = ?, retrieved_at = ? WHERE url = ?", (title[:200], stamp, url))
                self.send_json({"ok": True, "status": "used"})
                return

            # Thread Formatter
            if path == "/api/format-thread":
                text = string_field(payload, "text")
                tweets = format_as_thread(text)
                self.send_json({"ok": True, "tweets": tweets, "count": len(tweets)})
                return

            # X Single Post Formatter
            if path == "/api/format-x":
                text = string_field(payload, "text")
                clean = format_for_x(text, max_chars=280)
                self.send_json({"ok": True, "text": clean, "length": len(clean)})
                return

            # Update Draft Body (for auto-fit and split thread on draft card)
            if path.startswith("/api/drafts/") and path.endswith("/update-body"):
                draft_id = path.split("/")[3]
                body_text = string_field(payload, "body")
                stamp = now_iso()
                with db() as conn:
                    conn.execute("UPDATE drafts SET body = ?, updated_at = ? WHERE id = ?", (body_text, stamp, draft_id))
                self.send_json({"ok": True, "body": body_text})
                return

            # Full edit-in-place update of an existing draft. Preserves status.
            if path.startswith("/api/drafts/") and path.endswith("/update"):
                draft_id = path.split("/")[3]
                with db() as conn:
                    row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
                    if row is None:
                        raise ApiError(404, "Draft not found")
                    title = string_field(payload, "title").strip() if "title" in payload else row["title"]
                    if not title:
                        raise ApiError(400, "Title cannot be empty.")
                    body = string_field(payload, "body") if "body" in payload else row["body"]
                    platform = (string_field(payload, "platform").strip() or row["platform"]) if "platform" in payload else row["platform"]
                    image_prompt = string_field(payload, "image_prompt") if "image_prompt" in payload else row["image_prompt"]
                    source_url = string_field(payload, "source_url") if "source_url" in payload else row["source_url"]
                    media_url = string_field(payload, "media_url") if "media_url" in payload else row["media_url"]
                    scheduled_for = string_field(payload, "scheduled_for") if "scheduled_for" in payload else row["scheduled_for"]
                    stamp = now_iso()
                    conn.execute(
                        """UPDATE drafts SET title=?, body=?, platform=?, image_prompt=?, source_url=?,
                           media_url=?, scheduled_for=?, updated_at=? WHERE id=?""",
                        (title[:200], body, platform[:40], image_prompt, source_url, media_url, scheduled_for, stamp, draft_id),
                    )
                self.send_json({"ok": True, "id": draft_id})
                return

            # Update Draft Performance Metrics (Live URL, Views, Engagements)
            if path.startswith("/api/drafts/") and path.endswith("/metrics"):
                draft_id = path.split("/")[3]
                live_url = string_field(payload, "live_url")
                views = int(payload.get("views") or 0)
                engagements = int(payload.get("engagements") or 0)
                stamp = now_iso()
                with db() as conn:
                    conn.execute(
                        "UPDATE drafts SET live_url = ?, views = ?, engagements = ?, updated_at = ? WHERE id = ?",
                        (live_url, views, engagements, stamp, draft_id)
                    )
                self.send_json({"ok": True, "live_url": live_url, "views": views, "engagements": engagements})
                return

            # Carousel Formatter
            if path == "/api/format-carousel":
                title = string_field(payload, "title") or "Key Insights"
                text = string_field(payload, "text")
                slides = format_as_carousel(title, text)
                self.send_json({"ok": True, "slides": slides, "count": len(slides)})
                return

            # Phase C: Local image generation via Draw Things
            if path == "/api/generate-image":
                prompt = string_field(payload, "prompt")
                if not prompt:
                    raise ApiError(400, "prompt is required")
                result = generate_local_image(
                    prompt,
                    negative_prompt=string_field(payload, "negative_prompt"),
                    width=int(payload.get("width", 1024)),
                    height=int(payload.get("height", 576)),
                    steps=int(payload.get("steps", 20))
                )
                self.send_json(result)
                return

            # Phase E: Save webhook config
            if path == "/api/webhooks/save":
                config = get_webhook_config()
                for key in ("discord", "slack", "custom"):
                    if key in payload:
                        val = string_field(payload, key)
                        if val:
                            config[key] = val
                save_webhook_config(config)
                self.send_json({"ok": True})
                return

            # Phase E: Test webhook
            if path == "/api/webhooks/test":
                target = string_field(payload, "target")
                config = get_webhook_config()
                url = config.get(target, "")
                test_draft = {
                    "title": "ContentOS Test", "body": "Test from JustMeMedia ContentOS!",
                    "platform": "General", "status": "Draft",
                    "image_prompt": "", "created_at": now_iso()
                }
                if target == "discord":
                    result = send_webhook(url, build_discord_payload(test_draft))
                elif target == "slack":
                    result = send_webhook(url, build_slack_payload(test_draft))
                else:
                    result = send_webhook(url, test_draft)
                self.send_json(result)
                return

            # Phase E: Notify draft via webhook
            if path.startswith("/api/drafts/") and path.endswith("/notify"):
                parts = path.split("/")
                draft_id = parts[3] if len(parts) > 3 else ""
                target = string_field(payload, "target")
                with db() as conn:
                    cur = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,))
                    row = cur.fetchone()
                if not row:
                    self.send_error_json(404, "Draft not found")
                    return
                draft = dict(row)
                config = get_webhook_config()
                url = config.get(target, "")
                if not url:
                    self.send_error_json(400, f"No webhook URL configured for target '{target}'")
                    return
                if target == "discord":
                    wh_payload = build_discord_payload(draft)
                elif target == "slack":
                    wh_payload = build_slack_payload(draft)
                else:
                    wh_payload = {k: v for k, v in draft.items() if isinstance(v, (str, int, float, bool, type(None)))}
                result = send_webhook(url, wh_payload)
                self.send_json(result)
                return

            # Deep Research Endpoint
            if path == "/api/deep-research":
                url = string_field(payload, "url")
                title = string_field(payload, "title")
                snippet = string_field(payload, "snippet")
                res = deep_research_story(url, title, snippet)
                self.send_json({"ok": True, "dossier": res["dossier"], "links": res["links"]})
                return

            # Open media folder / reveal file in Finder
            if path == "/api/open-media":
                filename = string_field(payload, "filename")
                if sys.platform == "darwin":
                    if filename:
                        filepath = MEDIA_DIR / filename
                        if filepath.exists():
                            subprocess.run(["open", "-R", str(filepath)])
                        else:
                            subprocess.run(["open", str(MEDIA_DIR)])
                    else:
                        subprocess.run(["open", str(MEDIA_DIR)])
                self.send_json({"ok": True})
                return

            # Phone Push Notification (ntfy.sh)
            if path == "/api/notify/phone":
                topic = string_field(payload, "topic")
                title = string_field(payload, "title") or "ContentOS Alert"
                body = string_field(payload, "body") or "Your content is ready in ContentOS."
                priority = string_field(payload, "priority") or "default"
                if not topic:
                    raise ApiError(400, "Topic is required")
                ntfy_url = f"https://ntfy.sh/{topic.strip('/')}"
                req = urllib.request.Request(
                    ntfy_url,
                    data=body.encode("utf-8"),
                    headers={
                        "Title": title,
                        "Priority": priority,
                        "Tags": "sparkles,tea",
                        "User-Agent": "JustMeMedia-ContentOS/1.0"
                    },
                    method="POST"
                )
                try:
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        self.send_json({"ok": True, "status": resp.status})
                except Exception as exc:
                    self.send_json({"ok": False, "error": str(exc)})
                return

            # 1-Click Magic Pipeline
            if path == "/api/one-click-draft":
                title = string_field(payload, "title")
                url = string_field(payload, "url")
                snippet = string_field(payload, "snippet")
                tone = string_field(payload, "tone") or "thought_leadership"
                provider = string_field(payload, "provider")
                if not provider or provider == "none":
                    provider = "groq:openai/gpt-oss-120b" if os.environ.get("GROQ_API_KEY") else "auto"
                if not title:
                    raise ApiError(400, "Title is required")

                # Multi-select targets. Fall back to the single legacy platform field.
                platform_raw = payload.get("platforms")
                platforms = []
                if isinstance(platform_raw, list):
                    for entry in platform_raw:
                        name = entry.strip() if isinstance(entry, str) else ""
                        if name and name[:40] not in platforms:
                            platforms.append(name[:40])
                if not platforms:
                    platforms = [string_field(payload, "platform") or "LinkedIn"]
                platforms = platforms[:6]

                # Agent 0: Deep Investigator (run once, share context across platforms)
                use_deep = payload.get("deep_research", True)
                if use_deep and url:
                    try:
                        research = deep_research_story(url, title, snippet)
                        context = research["dossier"]
                    except Exception:
                        context = extract_article_text(url) or (snippet or title)
                else:
                    deep_text = extract_article_text(url) if url else ""
                    context = deep_text if deep_text and not deep_text.startswith("(") else (snippet or title)

                # Generate one tailored draft per selected platform.
                results = []
                for pf in platforms:
                    res = run_roundtable(provider, title, context, pf, tone=tone, source_url=url)
                    results.append((pf, res))

                # Media is generated once and shared across the produced drafts.
                media_url = ""
                if draw_things_available():
                    try:
                        img_res = generate_local_image(results[0][1]["image_prompt"], width=1024, height=576, steps=20)
                        if img_res.get("ok"):
                            media_url = f"/api/media/{img_res['filename']}"
                    except Exception:
                        media_url = ""

                if not media_url:
                    q_words = [w for w in re.sub(r"[^\w\s]", "", title).split() if len(w) > 3 and w.lower() not in ("with", "that", "this", "from", "have")][:2]
                    try:
                        gifs = search_gifs(" ".join(q_words) if q_words else "tech", limit=1)
                        if gifs:
                            media_url = gifs[0]["original"]
                    except Exception:
                        media_url = ""

                scheduled_for = calculate_next_optimal_slot()
                stamp = now_iso()
                created = []
                with db() as conn:
                    for pf, res in results:
                        cur = conn.execute(
                            """INSERT INTO drafts(title, body, platform, status, image_prompt, source_url, media_url, scheduled_for, created_at, updated_at)
                               VALUES(?,?,?,?,?,?,?,?,?,?)""",
                            (title[:200], res["final_post"], pf, "Draft", res["image_prompt"], url, media_url, scheduled_for, stamp, stamp)
                        )
                        created.append({
                            "id": cur.lastrowid,
                            "platform": pf,
                            "body": res["final_post"],
                            "image_prompt": res["image_prompt"],
                        })

                primary = created[0]
                self.send_json({
                    "ok": True,
                    "id": primary["id"],
                    "title": title,
                    "body": primary["body"],
                    "image_prompt": primary["image_prompt"],
                    "media_url": media_url,
                    "scheduled_for": scheduled_for,
                    "platform": primary["platform"],
                    "status": "Draft",
                    "drafts": created,
                }, 201)
                return

            # Update draft schedule
            if path.startswith("/api/drafts/") and path.endswith("/schedule"):
                draft_id = path.split("/")[3]
                scheduled_for = string_field(payload, "scheduled_for")
                stamp = now_iso()
                with db() as conn:
                    conn.execute("UPDATE drafts SET scheduled_for = ?, updated_at = ? WHERE id = ?", (scheduled_for, stamp, draft_id))
                self.send_json({"ok": True, "scheduled_for": scheduled_for})
                return

            # AI Generation
            if path == "/api/generate":
                try:
                    task = payload.get("task", "draft_post")
                    title = payload.get("title", "")
                    context = payload.get("context", "")
                    platform = payload.get("platform", "LinkedIn")
                    provider = payload.get("provider", "ollama")
                    tone = payload.get("tone", "thought_leadership")

                    if task == "roundtable":
                        res = run_roundtable(provider, title, context, platform, tone=tone, source_url=payload.get("source_url") or payload.get("url") or "")
                        self.send_json({"ok": True, "result": res["final_post"], "image_prompt": res["image_prompt"], "log": res["roundtable_log"]})
                        return

                    system_prompt = (
                        "You are the JustMeMedia Content Engine. Brand voice: professional, credible, "
                        "technology-focused, direct, practical, informed, zero hype. Never invent customer "
                        "claims or fake metrics. Clearly format for the target platform."
                    )

                    if task == "draft_post":
                        if platform.lower() in ("x", "twitter"):
                            user_prompt = (
                                f"Write a high-engagement single post for X (Twitter).\n"
                                f"Topic/Title: {title}\n"
                                f"Context/Source facts: {context[:800]}\n\n"
                                "CRITICAL CONSTRAINT - CHARACTER LIMIT:\n"
                                "- The post MUST be strictly UNDER 250 characters total.\n"
                                "- Include 1 punchy hook sentence, 1 key insight, and 1-2 hashtags.\n"
                                "- DO NOT write multiple paragraphs. DO NOT use bullet points or markdown headers.\n"
                                "Return ONLY the single tweet under 250 characters."
                            )
                        else:
                            user_prompt = (
                                f"Write a high-engagement, brand-aligned post for {platform}.\n"
                                f"Topic/Title: {title}\n"
                                f"Context/Source facts: {context}\n\n"
                                "Formatting guidelines:\n"
                                "- LinkedIn: Executive thought leadership, punchy hook, clean double line breaks, bullet points, top 2 links, closing question (Max 2,200 chars).\n"
                                "- YouTube: Full comprehensive guide, catchy video title ideas, 15-second opening hook, detailed breakdown, complete verified resource link library (Up to 5,000 chars).\n"
                                "- Facebook: Long-form conversational article, clear headers, full links list, discussion question.\n"
                                "- Instagram/Threads: Story hook, clean spacing, engaging question.\n\n"
                                "Return ONLY the post content."
                            )
                        draft_text = call_ai(provider, user_prompt, system_prompt)
                        if platform.lower() in ("x", "twitter"):
                            draft_text = format_for_x(draft_text)
                        elif platform.lower() == "linkedin":
                            draft_text = format_for_linkedin(draft_text)
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
                except Exception as exc:
                    self.send_json({"ok": False, "error": str(exc)})
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
                media_url = string_field(payload, "media_url")
                scheduled_for = string_field(payload, "scheduled_for") or calculate_next_optimal_slot()
                stamp = now_iso()
                with db() as conn:
                    cur = conn.execute(
                        """INSERT INTO drafts(title, body, platform, status, image_prompt, source_url, media_url, scheduled_for, created_at, updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (title[:200], body, platform[:40], "Draft", image_prompt, source_url, media_url, scheduled_for, stamp, stamp)
                    )
                    draft_id = cur.lastrowid
                self.send_json({"ok": True, "id": draft_id, "scheduled_for": scheduled_for}, 201)
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

    def address_string(self) -> str:
        # Avoid slow reverse-DNS lookups on local loopback connections
        return self.client_address[0]

    def log_message(self, fmt, *args):
        print("[ContentOS] " + (fmt % args))


def main():
    connect_db().close()
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as e:
        in_use = getattr(e, "winerror", None) == 10048 or e.errno in (48, 98, 10048)
        if in_use:
            print(f"[ContentOS Error] Port {PORT} is already in use.")
            if sys.platform == "win32":
                print("Run 'Get-Process python* | Stop-Process -Force' or double-click scripts\\run_windows.ps1 to clear it.")
            else:
                print(f"Run 'kill -9 $(lsof -ti :{PORT})' or double-click ContentOS.command to clear it.")
            sys.exit(1)
        raise
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
