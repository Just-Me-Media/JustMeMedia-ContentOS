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
from datetime import datetime, timedelta, timezone
from html import unescape as html_unescape
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Ensure the project root is on sys.path so `app.platforms` is importable
# regardless of how the script is launched (python3 ./app/server.py or
# python3 -m app.server).
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Load environment variables from .env file in project root or config dir
from app.env_loader import load_env_file
load_env_file()

# Platform adapter layer — real API publishing to LinkedIn, X, YouTube,
# Facebook, Instagram, GitHub. Imported lazily so missing optional deps
# (e.g. requests) never break server startup.
from app.platforms import publish as platform_publish

APP_NAME = "JustMeMedia"
PRODUCT_NAME = "ContentOS"
HOST = "127.0.0.1"

# Only these hostnames may appear in the Host header. This blocks DNS-rebinding
# attacks where a public domain resolves to 127.0.0.1 and a browser then treats
# this server as same-origin.
ALLOWED_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1"})

# Documents are plain text; anything larger is a mistake or an attack.
MAX_BODY_BYTES = 2_000_000

# Application version (bump for releases)
CONTENTOS_VERSION = "1.0.3"
GITHUB_REPO = "Just-Me-Media/JustMeMedia-ContentOS"

_ENV_KEY_FALLBACK = frozenset({
    "GROQ_API_KEY", "GEMINI_API_KEY",
    "DRAW_THINGS_API_KEY", "DRAW_THINGS_URL",
    "CONTENTOS_X_ACCESS_TOKEN", "X_ACCESS_TOKEN", "TWITTER_ACCESS_TOKEN",
    "CONTENTOS_X_CONSUMER_KEY", "CONTENTOS_X_CONSUMER_SECRET",
    "CONTENTOS_X_ACCESS_TOKEN_SECRET", "CONTENTOS_X_OAUTH_ACCESS_TOKEN",
    "CONTENTOS_X_CLIENT_ID", "CONTENTOS_X_CLIENT_SECRET",
    "OPENAI_API_KEY", "STABILITY_API_KEY", "REPLICATE_API_TOKEN",
})


def _load_env_fallback() -> None:
    """Load API keys from a dedicated secure keys file if not already set.

    Only reads ``~/.secure_keys/.env`` (the file SECURITY.md documents). Shell
    dotfiles are intentionally NOT parsed: they mix secrets with shell config
    and are easy to mis-parse. Set CONTENTOS_LOAD_KEYS=1 to enable; otherwise
    use ordinary environment variables or an OS credential store.
    """
    if os.environ.get("CONTENTOS_LOAD_KEYS", "").strip().lower() not in ("1", "true", "yes"):
        return
    candidates = [Path.home() / ".secure_keys" / ".env"]
    for p in candidates:
        if not p.exists():
            continue
        try:
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                if key.startswith("export "):
                    key = key[len("export "):].strip()
                val = val.strip().strip("\"' ")
                if key in _ENV_KEY_FALLBACK and val and not os.environ.get(key):
                    os.environ[key] = val
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
    if "notified_at" not in cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN notified_at TEXT NOT NULL DEFAULT ''")
    if "auto_publish" not in cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN auto_publish INTEGER NOT NULL DEFAULT 0")
    if "post_id" not in cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN post_id TEXT NOT NULL DEFAULT ''")
    if "publish_error" not in cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN publish_error TEXT NOT NULL DEFAULT ''")
    if "published_at" not in cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN published_at TEXT NOT NULL DEFAULT ''")
    if "tags" not in cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN tags TEXT NOT NULL DEFAULT ''")
    if "body_html" not in cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN body_html TEXT NOT NULL DEFAULT ''")
    if "verification_report" not in cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN verification_report TEXT NOT NULL DEFAULT ''")

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

    # NOTE: the former content_items / content_versions / claims tables were
    # never written by the app or worker (drafts + draft_versions + sources are
    # the real model) and were removed. They have no migration path here; any
    # legacy tables in an existing DB are harmless and simply left untouched.

    # Approvals audit trail
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

    # 6. Rejected / dismissed sources (user dismissed an article they do not want)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rejected_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            rejected_at TEXT NOT NULL,
            UNIQUE(url)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rejected_url ON rejected_sources(url)")

    # 7. User-curated source watchlist (add/remove feeds for discovery)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS source_watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT 'Tech',
            enabled INTEGER NOT NULL DEFAULT 1,
            last_checked TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_url ON source_watchlist(url)")

    # 7b. Migration for existing watchlist tables (add new columns if missing)
    for col, default in [("label", "''"), ("category", "'Tech'"), ("enabled", "1"),
                         ("last_checked", "''"), ("last_error", "''"), ("created_at", "''")]:
        try:
            conn.execute(f"ALTER TABLE source_watchlist ADD COLUMN {col} TEXT NOT NULL DEFAULT {default}")
        except Exception:
            pass

    # 7. GitHub trending repos (daily snapshot for the weekly Top 10)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS github_repos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            url TEXT NOT NULL,
            description TEXT,
            stars INTEGER NOT NULL DEFAULT 0,
            language TEXT,
            fetched_at TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'General',
            UNIQUE(url, fetched_at)
        )
    """)
    # Migration: mark snapshots that came from the offline sample list so a
    # generated post can warn the operator instead of presenting fake stars.
    gcur = conn.execute("PRAGMA table_info(github_repos)")
    if "sample" not in [row["name"] for row in gcur.fetchall()]:
        conn.execute("ALTER TABLE github_repos ADD COLUMN sample INTEGER NOT NULL DEFAULT 0")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_github_fetched ON github_repos(fetched_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_github_stars ON github_repos(stars)")

    # 8. Platform partnerships (which platforms content is approved for posting)
    conn.execute("""CREATE TABLE IF NOT EXISTS platforms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        draft_id INTEGER NOT NULL,
        platform TEXT NOT NULL,
        provider TEXT NOT NULL DEFAULT 'x',
        status TEXT NOT NULL DEFAULT 'approved',
        post_id TEXT NOT NULL DEFAULT '',
        published_at TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        FOREIGN KEY (draft_id) REFERENCES drafts(id) ON DELETE CASCADE
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_platforms_draft ON platforms(draft_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_platforms_status ON platforms(status)")

    # 9. Draft versions (version history for revert)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS draft_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            draft_id INTEGER NOT NULL,
            version_number INTEGER NOT NULL DEFAULT 1,
            title TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            body_html TEXT NOT NULL DEFAULT '',
            platform TEXT NOT NULL DEFAULT 'General',
            image_prompt TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '',
            saved_at TEXT NOT NULL,
            FOREIGN KEY (draft_id) REFERENCES drafts(id) ON DELETE CASCADE
        )
    """)
    vcur = conn.execute("PRAGMA table_info(draft_versions)")
    vcols = [row["name"] for row in vcur.fetchall()]
    if "body_html" not in vcols:
        conn.execute("ALTER TABLE draft_versions ADD COLUMN body_html TEXT NOT NULL DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_versions_draft ON draft_versions(draft_id)")

    # 11. Activity log (audit trail)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL DEFAULT '',
            entity_id INTEGER,
            details TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_log(created_at)")

    # 9. Templates table (reusable composer presets)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            platform TEXT NOT NULL DEFAULT 'General',
            title_template TEXT NOT NULL DEFAULT '',
            body_template TEXT NOT NULL DEFAULT '',
            image_prompt_template TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # 8. Weekly Top 10 issue log (prevents regenerating the same weekly bundle)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS github_top10_issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            draft_ids TEXT NOT NULL,
            platform TEXT NOT NULL DEFAULT 'LinkedIn',
            UNIQUE(week_start, platform)
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


def log_activity(action: str, entity_type: str = "", entity_id: int = None, details: str = "") -> None:
    """Log an activity to the audit trail."""
    try:
        with db() as conn:
            conn.execute(
                "INSERT INTO activity_log(action, entity_type, entity_id, details, created_at) VALUES(?,?,?,?,?)",
                (action, entity_type, entity_id, details[:500], now_iso())
            )
    except Exception:
        pass

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def local_date_str() -> str:
    """Local calendar date (YYYY-MM-DD) for day-keyed records and scheduling.

    The scheduler, optimal slots and scrape times all operate in local time, so
    any record that is later compared against a local-time slot must use the
    same clock. Using ``now_iso()[:10]`` (UTC) here made evening entries in
    negative-UTC-offset zones land on the next day and vanish from lookups.
    """
    return datetime.now().strftime("%Y-%m-%d")


def get_pending_posts(platform: str = None) -> list[dict]:
    """Fetch approved posts ready for Hermes to publish (pending status).

    Returns drafts where:
    - status is 'Approved' or 'Pending'
    - the draft has a platform entry in the platforms table marked 'approved'
    - the platforms entry has not yet been published (empty post_id)
    """
    with db() as conn:
        query = """
            SELECT d.id AS draft_id, d.title, d.body, d.platform AS draft_platform,
                   p.platform AS target_platform, p.id AS platform_id,
                   p.post_id, p.published_at
            FROM drafts d
            JOIN platforms p ON p.draft_id = d.id
            WHERE d.status IN ('Approved', 'Pending')
              AND p.status = 'approved'
              AND p.post_id = ''
            ORDER BY d.id
        """
        if platform:
            query += " AND p.platform = ?"
            params = (platform,)
        else:
            params = ()
        cur = conn.execute(query, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]


def record_post_status(draft_id: int, platform: str, post_id: str, published_at: str = "") -> int:
    """Record the publishing status of a post in the platforms table.

    Returns the number of rows updated.
    """
    with db() as conn:
        now = published_at or now_iso()
        cur = conn.execute(
            """UPDATE platforms
               SET post_id = ?, published_at = ?, status = 'published', updated_at = ?
               WHERE draft_id = ? AND platform = ? AND status = 'approved'
               AND post_id = ''""",
            (post_id, now, now_iso(), draft_id, platform)
        )
        conn.commit()
        return cur.rowcount
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
# PHASE C: LOCAL DRAW THINGS IMAGE GENERATION (AUTOMATIC1111-COMPATIBLE API)
# ─────────────────────────────────────────────────────────────────────────────

DRAW_THINGS_URL = os.environ.get("DRAW_THINGS_URL", "http://127.0.0.1:7860")
DRAW_THINGS_API_KEY = os.environ.get("DRAW_THINGS_API_KEY", "")

# Image backend configuration (used by tests and runtime)
IMAGE_BACKEND = os.environ.get("IMAGE_BACKEND", "drawthings")  # "drawthings" | "a1111" | "none"
LOCAL_IMAGE_ENABLED = IMAGE_BACKEND in ("drawthings", "a1111")
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
    """Check if Draw Things local API server is running."""
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
    if not draw_things_available():
        return {"ok": False, "error": "Draw Things API not available. Enable HTTP server in Draw Things Settings."}

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
            return {"ok": False, "error": "Draw Things returned no images."}

        b64_data = images[0]
        import base64
        filename = f"gen_{now_iso()[:19].replace(':', '-').replace('T', '_')}.png"
        filepath = MEDIA_DIR / filename
        filepath.write_bytes(base64.b64decode(b64_data))

        return {"ok": True, "filename": filename, "b64": b64_data}

    except urllib.error.URLError as exc:
        return {"ok": False, "error": f"Cannot connect to Draw Things: {exc}"}
    except TimeoutError:
        return {"ok": False, "error": "Draw Things API not available (request timed out). Enable HTTP server in Draw Things Settings."}
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


def check_for_update() -> dict:
    """Check GitHub for a newer release. Returns update info or 'up_to_date'."""
    import urllib.parse
    token = os.environ.get("CONTENTOS_GITHUB_TOKEN", "").strip()
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "ContentOS"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        
        latest_tag = data.get("tag_name", "").lstrip("v")
        latest_version = CONTENTOS_VERSION
        changes = data.get("body", "No changes documented").split("\n\n")[:3]
        
        if latest_tag and latest_tag != CONTENTOS_VERSION:
            return {
                "ok": True,
                "current_version": CONTENTOS_VERSION,
                "latest_version": latest_tag,
                "up_to_date": False,
                "changelog": [c.strip() for c in changes if c.strip()],
                "download_url": data.get("html_url", ""),
                "asset_url": None,
            }
        
        return {"ok": True, "current_version": CONTENTOS_VERSION, "latest_version": latest_tag, "up_to_date": True}
    except urllib.error.HTTPError as exc:
        if exc.status == 403:
            return {"ok": True, "current_version": CONTENTOS_VERSION, "latest_version": CONTENTOS_VERSION, "up_to_date": True, "note": "API limit reached"}
        if exc.status == 404:
            # No published releases yet — this is normal for a fresh/private
            # repo, not an error. Be explicit so the UI can say so honestly.
            return {"ok": True, "current_version": CONTENTOS_VERSION,
                    "latest_version": CONTENTOS_VERSION, "up_to_date": True,
                    "has_release": False,
                    "note": "No published releases found — automatic update checks are unavailable"}
        return {"ok": True, "current_version": CONTENTOS_VERSION, "latest_version": CONTENTOS_VERSION, "up_to_date": True, "note": f"Update check failed: {exc.status}"}
    except Exception as exc:
        return {"ok": True, "current_version": CONTENTOS_VERSION, "latest_version": CONTENTOS_VERSION, "up_to_date": True, "note": str(exc)}


def _save_image_b64(b64_data: str, filename: str) -> str:
    """Decode and save a base64 image to MEDIA_DIR. Returns filename."""
    import base64
    filepath = MEDIA_DIR / filename
    filepath.write_bytes(base64.b64decode(b64_data))
    return filename


def generate_openai_image(prompt: str, width: int = 1024, height: int = 576) -> dict:
    """Generate an image via OpenAI DALL-E 3."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {"ok": False, "error": "OPENAI_API_KEY not set."}

    size = "1024x1024"
    if width == 1792 and height == 1024:
        size = "1792x1024"
    elif width == 1024 and height == 1792:
        size = "1024x1792"

    payload = {
        "model": "dall-e-3",
        "prompt": prompt[:4000],
        "n": 1,
        "size": size,
        "response_format": "b64_json",
    }
    try:
        req = urllib.request.Request(
            "https://api.openai.com/v1/images/generations",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        b64_data = (data.get("data") or [{}])[0].get("b64_json", "")
        if not b64_data:
            return {"ok": False, "error": "OpenAI returned no image data."}

        filename = f"gen_{now_iso()[:19].replace(':', '-').replace('T', '_')}.png"
        _save_image_b64(b64_data, filename)
        return {"ok": True, "filename": filename, "b64": b64_data, "provider": "openai"}

    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read().decode("utf-8"))
            msg = err.get("error", {}).get("message", str(exc))
        except Exception:
            msg = str(exc)
        return {"ok": False, "error": f"OpenAI image error: {msg}"}
    except Exception as exc:
        return {"ok": False, "error": f"OpenAI image error: {exc}"}


def generate_stability_image(prompt: str, width: int = 1024, height: int = 576) -> dict:
    """Generate an image via Stability AI (Stable Diffusion XL)."""
    api_key = os.environ.get("STABILITY_API_KEY", "").strip()
    if not api_key:
        return {"ok": False, "error": "STABILITY_API_KEY not set."}

    w = (width // 64) * 64
    h = (height // 64) * 64
    if w < 64 or h < 64:
        w, h = 1024, 576

    payload = {
        "text_prompts": [{"text": prompt[:2000], "weight": 1.0}],
        "cfg_scale": 7.0,
        "height": h,
        "width": w,
        "samples": 1,
        "steps": 30,
    }
    try:
        req = urllib.request.Request(
            "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        artifacts = data.get("artifacts", [])
        if not artifacts or not artifacts[0].get("base64"):
            return {"ok": False, "error": "Stability AI returned no image data."}

        b64_data = artifacts[0]["base64"]
        filename = f"gen_{now_iso()[:19].replace(':', '-').replace('T', '_')}.png"
        _save_image_b64(b64_data, filename)
        return {"ok": True, "filename": filename, "b64": b64_data, "provider": "stability"}

    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read().decode("utf-8"))
            msg = err.get("message", str(exc))
        except Exception:
            msg = str(exc)
        return {"ok": False, "error": f"Stability AI error: {msg}"}
    except Exception as exc:
        return {"ok": False, "error": f"Stability AI error: {exc}"}


def generate_replicate_image(prompt: str, width: int = 1024, height: int = 576) -> dict:
    """Generate an image via Replicate (FLUX Schnell)."""
    api_token = os.environ.get("REPLICATE_API_TOKEN", "").strip()
    if not api_token:
        return {"ok": False, "error": "REPLICATE_API_TOKEN not set."}

    payload = {
        "version": "black-forest-labs/flux-schnell",
        "input": {
            "prompt": prompt[:2000],
            "width": width,
            "height": height,
            "num_outputs": 1,
        },
    }
    try:
        req = urllib.request.Request(
            "https://api.replicate.com/v1/predictions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Token {api_token}",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        prediction_url = data.get("urls", {}).get("get", "")
        if not prediction_url:
            return {"ok": False, "error": "Replicate returned no prediction URL."}

        import time
        for _ in range(45):
            time.sleep(2)
            req = urllib.request.Request(prediction_url, headers={"Authorization": f"Token {api_token}"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            status = result.get("status", "")
            if status == "succeeded":
                output = result.get("output", [])
                if output and isinstance(output, list):
                    img_url = output[0]
                elif isinstance(output, str):
                    img_url = output
                else:
                    return {"ok": False, "error": "Replicate returned no image."}
                req = urllib.request.Request(img_url, headers={"User-Agent": "ContentOS/1.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    img_data = resp.read()
                filename = f"gen_{now_iso()[:19].replace(':', '-').replace('T', '_')}.png"
                filepath = MEDIA_DIR / filename
                filepath.write_bytes(img_data)
                import base64
                b64_data = base64.b64encode(img_data).decode("utf-8")
                return {"ok": True, "filename": filename, "b64": b64_data, "provider": "replicate"}
            elif status in ("failed", "canceled"):
                return {"ok": False, "error": f"Replicate failed: {result.get('error', 'unknown')}"}

        return {"ok": False, "error": "Replicate timed out."}

    except Exception as exc:
        return {"ok": False, "error": f"Replicate error: {exc}"}


def generate_image(prompt: str, negative_prompt: str = "", width: int = 1024,
                  height: int = 576, steps: int = 20, provider_override: str = None) -> dict:
    """Unified image generation: Draw Things (local) first, then cloud fallback.

    Provider selection via IMAGE_PROVIDER env var:
      "auto"       — try Draw Things, then cloud providers in order (default)
      "drawthings" — Draw Things only
      "openai"     — OpenAI DALL-E 3 only
      "stability"  — Stability AI only
      "replicate"  — Replicate only

    provider_override: per-request override (e.g. from API payload).
    """
    provider = (provider_override or os.environ.get("IMAGE_PROVIDER", "auto")).lower().strip()

    if provider == "drawthings":
        return generate_local_image(prompt, negative_prompt, width, height, steps)

    if provider == "openai":
        return generate_openai_image(prompt, width, height)

    if provider == "stability":
        return generate_stability_image(prompt, width, height)

    if provider == "replicate":
        return generate_replicate_image(prompt, width, height)

    # Auto: try Draw Things first, then cloud providers
    if draw_things_available():
        result = generate_local_image(prompt, negative_prompt, width, height, steps)
        if result.get("ok"):
            result["provider"] = "drawthings"
            return result

    # Cloud fallbacks in order of preference
    for cloud_fn in (generate_openai_image, generate_stability_image, generate_replicate_image):
        result = cloud_fn(prompt, width, height)
        if result.get("ok"):
            return result

    return {"ok": False, "error": "No image provider available. Enable Draw Things or set "
            "OPENAI_API_KEY, STABILITY_API_KEY, or REPLICATE_API_TOKEN."}


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


# ─────────────────────────────────────────────────────────────────────────────
# DEEP VERIFICATION — cross-check source claims against independent web sources
# ─────────────────────────────────────────────────────────────────────────────

_EXTRACT_SYSTEM = """You are a meticulous research librarian extracting checkable factual claims.
Return ONLY claims in this exact format, one per block, up to {n}:
---CLAIM---
<one short, specific factual claim from the article, including any number/date/version/name>
---END CLAIM---
Rules: only claims actually stated in the text; no opinions, no invented numbers; if a fact looks dubious still extract it so it can be checked."""

_ADJUDICATE_SYSTEM = """You are a strict fact-checker. You are given claims from a source article and search results from INDEPENDENT sources. The source article may contain mistakes.
For each claim decide a verdict using ONLY the evidence provided:
- "confirmed" — independent sources agree with the claim.
- "corrected" — the claim is wrong; write the accurate version in the corrected field.
- "unverifiable" — evidence is insufficient; do not guess.
Return ONLY verdict blocks, one per claim, in this exact format:
---FACT---
claim: <the original claim>
verdict: confirmed|corrected|unverifiable
corrected: <accurate version if corrected, otherwise empty>
evidence: <the single most relevant URL from the evidence, otherwise empty>
note: <one short sentence explaining the verdict>
---END FACT---
Never invent URLs or numbers. Do not output anything except the blocks."""


def _parse_claims(raw: str, limit: int = 6) -> list[str]:
    """Extract ---CLAIM--- blocks from a model response."""
    claims: list[str] = []
    for match in re.finditer(
        r"---CLAIM---(.*?)(?:---END CLAIM---|$)", raw or "", re.DOTALL | re.IGNORECASE
    ):
        text = re.sub(r"\s+", " ", match.group(1)).strip().strip('"')
        if len(text) >= 8 and text not in claims:
            claims.append(text)
        if len(claims) >= limit:
            break
    return claims


def _parse_facts(raw: str) -> list[dict]:
    """Extract ---FACT--- verdict blocks from a model response."""
    facts: list[dict] = []
    for match in re.finditer(
        r"---FACT---(.*?)(?:---END FACT---|$)", raw or "", re.DOTALL | re.IGNORECASE
    ):
        block = match.group(1)
        fields = {"claim": "", "verdict": "unverifiable", "corrected": "", "evidence": "", "note": ""}
        for line in block.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip().lower()
                if key in fields:
                    fields[key] = value.strip()
        if fields["claim"]:
            facts.append(fields)
    return facts


def verify_claims(provider_id: str, title: str, source_text: str,
                  source_url: str = "") -> dict:
    """Cross-check the source article's factual claims against independent sources.

    Pipeline: extract checkable claims -> web search each claim -> adjudicate with
    an independent model pass -> return a corrected-facts block plus a structured
    report. Never mutates the source; returns structured data the caller feeds to
    the drafter and the human.

    Returns: {"ok": bool, "claims": [...], "facts": [...], "corrected": [...],
              "verified_block": str, "error": str}
    """
    result = {"ok": False, "claims": [], "facts": [], "corrected": [],
              "verified_block": "", "error": ""}
    try:
        if not source_text or len(source_text) < 40:
            result["error"] = "No source text to verify."
            return result

        # Step 1: extract the checkable claims from the source.
        extract_prompt = (
            f"Article title: {title}\n\nArticle text:\n{source_text[:6000]}\n"
        )
        claims_raw = call_ai(provider_id, extract_prompt, _EXTRACT_SYSTEM.format(n=6))
        claims = _parse_claims(claims_raw)
        result["claims"] = claims
        if not claims:
            result["error"] = "No checkable claims were extracted from the source."
            return result

        # Step 2: independently search each claim. Keep the strongest evidence.
        evidence_lines: list[str] = []
        for claim in claims[:6]:
            try:
                hits = web_research(claim, limit=3)
            except Exception:
                hits = []
            if hits:
                evidence_lines.append(f"CLAIM: {claim}")
                for hit in hits[:3]:
                    snippet = re.sub(r"\s+", " ", hit.get("snippet", ""))[:300]
                    evidence_lines.append(
                        f"  SOURCE: {hit.get('title', '')}\n"
                        f"  URL: {hit.get('url', '')}\n"
                        f"  TEXT: {snippet}"
                    )
                evidence_lines.append("")
            else:
                evidence_lines.append(f"CLAIM: {claim}\n  (no independent results found)\n")

        if not evidence_lines:
            result["error"] = "Web research returned no evidence."
            return result

        # Step 3: adjudicate claims against independent evidence only.
        adjudicate_prompt = (
            f"Source article title: {title}\n"
            f"Source article URL: {source_url}\n\n"
            f"Claims and independent evidence:\n" + "\n".join(evidence_lines) + "\n"
        )
        facts_raw = call_ai(provider_id, adjudicate_prompt, _ADJUDICATE_SYSTEM)
        facts = _parse_facts(facts_raw)

        # A small local model may not emit a verdict for every claim. Any claim
        # without a verdict MUST be marked unverifiable (never silently dropped
        # into the draft). Strict 1:1 best-match stops one vague verdict from
        # "covering" several different claims.
        def _tokens(text: str) -> set:
            return set(re.findall(r"[a-z0-9]+", (text or "").lower()))

        # Map each model fact to at most one claim (its best, strongest match).
        fact_for_claim: dict[int, int] = {}
        claimed_facts: set = set()
        for i, claim in enumerate(claims[:6]):
            ct = _tokens(claim)
            best_j, best_score = -1, 0.0
            for j, f in enumerate(facts):
                if j in claimed_facts:
                    continue
                score = len(_tokens(f.get("claim", "")) & ct) / max(len(ct), 1) if ct else 0.0
                if score > best_score:
                    best_j, best_score = j, score
            if best_j >= 0 and best_score >= 0.7:
                fact_for_claim[i] = best_j
                claimed_facts.add(best_j)
        # Any claim with no matched fact gets an explicit unverifiable verdict.
        for i, claim in enumerate(claims[:6]):
            if i not in fact_for_claim:
                facts.append({
                    "claim": claim,
                    "verdict": "unverifiable",
                    "corrected": "",
                    "evidence": "",
                    "note": "No independent verdict was produced; omitted from the post.",
                })
        result["facts"] = facts
        if not facts:
            result["error"] = "No verdicts were produced by the fact-checker."
            return result

        corrected = [f for f in facts if f.get("verdict", "").lower() == "corrected"]
        result["corrected"] = corrected

        # Step 4: build the block that overrides the source in the drafting context.
        lines = [
            "=== INDEPENDENT FACT VERIFICATION (authoritative — the source article may contain errors) ===",
            "Use the VERIFIED/CORRECTED facts below. Ignore the source article wherever it conflicts.",
            "Do not include any claim marked unverifiable. Do not invent facts not listed here.",
        ]
        for f in facts:
            verdict = f.get("verdict", "unverifiable").lower()
            if verdict == "corrected":
                lines.append(f"- SOURCE CLAIM (WRONG): {f['claim']}")
                lines.append(f"  USE INSTEAD: {f.get('corrected') or f['claim']}")
            elif verdict == "confirmed":
                lines.append(f"- VERIFIED: {f['claim']}")
            else:
                lines.append(f"- UNVERIFIABLE (omit from post): {f['claim']}")
            if f.get("evidence"):
                lines.append(f"  EVIDENCE: {f['evidence']}")
            if f.get("note"):
                lines.append(f"  NOTE: {f['note']}")
        if corrected:
            lines.append(
                f"WARNING: {len(corrected)} source claim(s) were wrong and have been corrected above."
            )
        result["verified_block"] = "\n".join(lines)
        result["ok"] = True
        return result
    except Exception as exc:
        result["error"] = str(exc)
        return result


# ─────────────────────────────────────────────────────────────────────────────
# STUDIO AI ASSISTANT — chat, web research, rewrites and image prompts
# ─────────────────────────────────────────────────────────────────────────────

CHAT_SYSTEM_PROMPT = """You are the JustMeMedia Content Studio assistant, a senior editor and research partner.

You help the author improve the draft they are writing. You can:
- critique and improve the writing, structure, hook and clarity
- rewrite, shorten, expand or retitle the post
- suggest credible data, angles and sources
- write vivid, concrete image prompts that match the story

Rules:
- Be specific and practical; no filler or hype.
- Never invent statistics, quotes, customer claims or URLs.
- Keep the conversational reply concise and scannable (short paragraphs or bullets).
- When you propose a rewrite, always output the COMPLETE revised post so it can replace the draft.
- Match the requested platform's conventions.

WEB SEARCH
You do not have direct internet access. Never claim you searched unless you used
the SEARCH block below. If the answer depends on current or verifiable
information (market data, statistics, recent news, sources), respond with ONLY
this block and nothing else:

---SEARCH---
<a short, focused search query, 2-6 words>
---END SEARCH---

The app will run the search and call you again with the results. Never invent
URLs or numbers. When sources are supplied, cite only those URLs.

After the search results are supplied, answer normally. Do not request another
search.

Response format: start with your conversational reply. Then include these optional
sections only when they are relevant (use the exact markers):

---REVISED POST---
<the complete revised post text>
---END REVISED POST---

---IMAGE PROMPT---
<a single, detailed image-generation prompt>
---END IMAGE PROMPT---

Important: the IMAGE PROMPT section must contain ONLY the image prompt text itself —
no preamble, no explanations, no labels, no markdown, and no extra paragraphs. Just
the prompt. The same rule applies to the SEARCH section above.

When the user asks specifically for image prompts, put the prompt(s) directly in the
IMAGE PROMPT section and keep the conversational reply minimal (one short sentence
or empty). Do not list or describe prompts in the reply text.
"""

def _decode_bing_redirect(href: str) -> str:
    """Bing wraps result links in /ck/a?...&u=a1<base64>. Unwrap them."""
    if "bing.com/ck/a" not in href:
        return href
    try:
        query = parse_qs(urlparse(href).query)
        encoded = (query.get("u") or [""])[0]
        if encoded.startswith("a1"):
            payload = encoded[2:]
            payload += "=" * (-len(payload) % 4)
            return base64.urlsafe_b64decode(payload).decode("utf-8", errors="replace")
    except Exception:
        pass
    return href


# Small stopword set used only to score search-result relevance.
_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "about",
    "by", "from", "is", "are", "was", "were", "be", "been", "it", "its", "this",
    "that", "these", "those", "as", "at", "into", "over", "after", "before", "than",
    "then", "so", "such", "can", "could", "should", "would", "may", "might", "will",
    "just", "also", "more", "most", "new", "latest", "best", "top",
    "why", "what", "how", "when", "where", "who", "which", "find", "search",
    "research", "look", "up", "recent", "current", "data", "statistics", "stats",
    "sources", "source", "information", "info",
}


def _query_terms(text: str) -> list[str]:
    """Meaningful, de-duplicated search terms in their original order."""
    terms: list[str] = []
    seen: set[str] = set()
    for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-]*", text or ""):
        low = word.lower().strip("'-")
        if len(low) < 2 or low in _STOPWORDS or low in seen:
            continue
        seen.add(low)
        terms.append(word.strip("'-"))
    return terms


def _dedupe_results(results: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for item in results:
        url = item.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(item)
    return unique


def _relevant_results(results: list[dict], terms: list[str]) -> list[dict]:
    """Keep results that share several query terms, with at least one/two in the title.

    Requiring title matches stops snippets from rescuing off-topic pages (e.g.
    "Microsoft Edge" for an "edge AI adoption survey" query).
    """
    if not terms:
        return results
    if len(terms) == 1:
        need_title, need_total = 1, 1
    elif len(terms) == 2:
        need_title, need_total = 1, 2
    else:
        need_title, need_total = 2, 2

    kept: list[tuple[int, int, dict]] = []
    for order, item in enumerate(results):
        title = (item.get("title") or "").lower()
        title_matches = sum(1 for term in terms if term.lower() in title)
        total_matches = sum(
            1 for term in terms
            if term.lower() in title
            or term.lower() in (item.get("snippet") or "").lower()
            or term.lower() in (item.get("url") or "").lower()
        )
        if title_matches >= need_title and total_matches >= need_total:
            kept.append((total_matches, order, item))
    kept.sort(key=lambda entry: (-entry[0], entry[1]))
    return [item for _, _, item in kept]


def _bing_rss_search(query: str, limit: int) -> list[dict]:
    """Bing RSS output — stable, lightweight and already ranked."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    results: list[dict] = []
    try:
        encoded = urllib.parse.quote_plus(query[:200])
        req = urllib.request.Request(f"https://www.bing.com/search?q={encoded}&format=rss", headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            page = resp.read(500_000).decode(resp.headers.get_content_charset() or "utf-8", errors="replace")

        def field(block: str, name: str) -> str:
            match = re.search(rf"<{name}>(.*?)</{name}>", block, re.S)
            if not match:
                return ""
            value = match.group(1).strip()
            cdata = re.fullmatch(r"<!\[CDATA\[(.*?)\]\]>", value, re.S)
            if cdata:
                value = cdata.group(1)
            return html_unescape(re.sub(r"<[^>]+>", "", value)).strip()

        for block in re.findall(r"<item>(.*?)</item>", page, re.S):
            result_url = field(block, "link")
            title = field(block, "title")
            if result_url.startswith("http") and title:
                results.append({
                    "title": title[:180],
                    "url": result_url,
                    "snippet": field(block, "description")[:320],
                })
            if len(results) >= limit:
                break
    except Exception:
        pass
    return results


def _bing_search(query: str, limit: int) -> list[dict]:
    encoded = urllib.parse.quote_plus(query[:200])
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    results: list[dict] = []
    try:
        # form/qs/sp are required; without them Bing degrades to one-word matches.
        url = f"https://www.bing.com/search?q={encoded}&form=QBLH&qs=n&sp=-1"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            page = resp.read(500_000).decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
        for block in re.findall(r'<li class="b_algo".*?</li>', page, re.S):
            match = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
            if not match:
                continue
            result_url = _decode_bing_redirect(html_unescape(match.group(1)))
            title = html_unescape(re.sub(r"<[^>]+>", "", match.group(2))).strip()
            snippet_match = re.search(r'<p[^>]*>(.*?)</p>', block, re.S)
            snippet = ""
            if snippet_match:
                snippet = html_unescape(re.sub(r"<[^>]+>", "", snippet_match.group(1))).strip()
            if result_url.startswith("http") and title:
                results.append({"title": title[:180], "url": result_url, "snippet": snippet[:320]})
            if len(results) >= limit:
                break
    except Exception:
        pass
    return results


def _ddg_search(query: str, limit: int) -> list[dict]:
    """DuckDuckGo Lite fallback (plain HTML, no JavaScript required)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    results: list[dict] = []
    try:
        encoded = urllib.parse.quote_plus(query[:200])
        req = urllib.request.Request(f"https://lite.duckduckgo.com/lite/?q={encoded}", headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            page = resp.read(500_000).decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
        links = list(re.finditer(
            r'<a[^>]+class=[\'"]result-link[\'"][^>]*href=[\'"]([^\'"]+)[\'"][^>]*>(.*?)</a>',
            page, re.S,
        ))
        for index, match in enumerate(links):
            href = html_unescape(match.group(1))
            if "uddg=" in href:
                parsed = parse_qs(urlparse(href if href.startswith("http") else "https:" + href).query)
                href = (parsed.get("uddg") or [href])[0]
            title = html_unescape(re.sub(r"<[^>]+>", "", match.group(2))).strip()
            window = page[match.end():match.end() + 2500]
            snippet_match = re.search(r'class=[\'"]result-snippet[\'"][^>]*>(.*?)</td>', window, re.S)
            snippet = ""
            if snippet_match:
                snippet = html_unescape(re.sub(r"<[^>]+>", "", snippet_match.group(1))).strip()
            if href.startswith("http") and title:
                results.append({"title": title[:180], "url": href, "snippet": snippet[:320]})
            if len(results) >= limit:
                break
    except Exception:
        pass
    return results


def _wiki_search(query: str, limit: int) -> list[dict]:
    """Last-resort encyclopedic fallback when search engines return nothing usable."""
    results: list[dict] = []
    try:
        encoded = urllib.parse.quote_plus(query[:200])
        wiki = (
            "https://en.wikipedia.org/w/api.php?action=query&list=search&format=json&utf8=1"
            f"&srlimit={limit}&srsearch={encoded}"
        )
        req = urllib.request.Request(wiki, headers={"User-Agent": "JustMeMediaContentOS/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for item in data.get("query", {}).get("search", [])[:limit]:
            title = item.get("title", "")
            if not title:
                continue
            results.append({
                "title": title,
                "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
                "snippet": html_unescape(re.sub(r"<[^>]+>", "", item.get("snippet", ""))).strip()[:320],
            })
    except Exception:
        pass
    return results


_RESEARCH_CACHE: dict[str, tuple[float, list[dict]]] = {}
_RESEARCH_CACHE_LOCK = threading.Lock()
_RESEARCH_CACHE_TTL = 600  # seconds


def web_research(query: str, limit: int = 5) -> list[dict]:
    """Zero-dependency web search with relevance filtering and fallbacks.

    The chat model supplies the query, so this function stays deliberately dumb:
    search, score, dedupe, fall back if the engine returns junk.
    """
    query = (query or "").strip()
    if not query:
        return []
    terms = _query_terms(query)
    cache_key = f"{query.lower()}|{limit}"
    with _RESEARCH_CACHE_LOCK:
        cached = _RESEARCH_CACHE.get(cache_key)
        if cached and time.monotonic() - cached[0] < _RESEARCH_CACHE_TTL:
            return [dict(item) for item in cached[1]]

    results = _relevant_results(_dedupe_results(_bing_rss_search(query, limit * 2)), terms)

    # If the primary engine degrades to first-word matching, retry with the bare
    # terms and then the HTML endpoint before changing engines.
    if not results:
        alt = " ".join(terms)
        if alt and alt.lower() != query.lower():
            results = _relevant_results(
                _dedupe_results(_bing_rss_search(alt, limit * 2)), terms
            )
    if not results:
        results = _relevant_results(_dedupe_results(_bing_search(query, limit * 2)), terms)
    if not results and len(terms) >= 2:
        quoted = '"' + " ".join(terms[:3]) + '"'
        results = _relevant_results(
            _dedupe_results(_bing_search(quoted, limit * 2)), terms
        )

    if len(results) < min(2, limit):
        extra = _relevant_results(_dedupe_results(_ddg_search(query, limit * 2)), terms)
        results = _dedupe_results(results + extra)
    if len(results) < min(2, limit):
        extra = _relevant_results(_dedupe_results(_wiki_search(query, limit)), terms)
        results = _dedupe_results(results + extra)

    results = results[:limit]
    if results:
        with _RESEARCH_CACHE_LOCK:
            if len(_RESEARCH_CACHE) >= 128:
                oldest = min(_RESEARCH_CACHE, key=lambda key: _RESEARCH_CACHE[key][0])
                _RESEARCH_CACHE.pop(oldest, None)
            _RESEARCH_CACHE[cache_key] = (time.monotonic(), [dict(item) for item in results])
    return results


def parse_search_request(raw: str) -> str:
    """Read the model's optional one-shot web search request."""
    match = re.search(
        r"---SEARCH---(.*?)(?:---END SEARCH---|$)",
        raw or "",
        re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return ""
    query = re.sub(r"\s+", " ", match.group(1)).strip().strip('"').strip()
    return query[:160]


def parse_chat_response(raw: str) -> dict:
    """Split the model reply into conversation text, revised post and image prompt."""
    text = (raw or "").strip()
    if not text:
        return {"reply": "", "suggested_body": "", "image_prompt": ""}

    upper = text.upper()
    rev_start = upper.find("---REVISED POST---")
    img_start = upper.find("---IMAGE PROMPT---")
    search_start = upper.find("---SEARCH---")
    rev_end = upper.find("---END REVISED POST---")
    img_end = upper.find("---END IMAGE PROMPT---")

    def clean_section(value: str) -> str:
        value = value.strip()
        if value.startswith("```"):
            value = re.sub(r"^```[a-zA-Z]*\s*", "", value)
            value = re.sub(r"\s*```$", "", value).strip()
        return value

    revised = ""
    if rev_start != -1:
        start = rev_start + len("---REVISED POST---")
        stops = [idx for idx in (rev_end, img_start, search_start) if idx != -1 and idx > start]
        end = min(stops) if stops else len(text)
        revised = clean_section(text[start:end])

    image_prompt = ""
    if img_start != -1:
        start = img_start + len("---IMAGE PROMPT---")
        end = img_end if img_end != -1 and img_end > start else len(text)
        image_prompt = clean_section(text[start:end])

    cut = len(text)
    for marker in (rev_start, img_start, search_start):
        if marker != -1:
            cut = min(cut, marker)
    reply = text[:cut].strip()

    if not reply:
        reply = "I've prepared changes you can apply to the draft." if revised else "Done."
    return {"reply": reply, "suggested_body": revised, "image_prompt": image_prompt}


def run_chat(provider_id: str, message: str, title: str = "", body: str = "",
             platform: str = "", image_prompt: str = "",
             history: list | None = None) -> dict:
    """Context-aware assistant turn, with at most one model-requested search."""
    history = history or []
    context = (
        f"PLATFORM: {platform or 'General'}\n"
        f"TITLE: {title or '(untitled)'}\n"
        f"CURRENT IMAGE PROMPT: {image_prompt or '(none)'}\n"
        f"CURRENT DRAFT:\n{body[:4000] or '(empty)'}\n"
    )
    conversation = ""
    for turn in history[-8:]:
        role = "User" if turn.get("role") == "user" else "Assistant"
        content = str(turn.get("content", ""))[:1200]
        if content:
            conversation += f"{role}: {content}\n"

    base_prompt = (
        f"{context}\n"
        f"CONVERSATION SO FAR:\n{conversation or '(new conversation)'}\n"
        f"USER REQUEST: {message}\n\n"
        "Answer the user. If they ask to improve, rewrite, shorten, retitle or restructure the post, "
        "include the COMPLETE revised post in the REVISED POST section. "
        "If image direction would help, include an IMAGE PROMPT section. "
        "When the user asks specifically for image prompts, put only the prompt(s) in the "
        "IMAGE PROMPT section and keep the conversational reply to one short sentence. "
        "If you need current or verifiable information, request a search and output nothing else."
    )

    raw = call_ai(provider_id, base_prompt, CHAT_SYSTEM_PROMPT)
    sources: list[dict] = []
    search_query = parse_search_request(raw)

    # Safety net: some smaller models claim they searched instead of using the
    # SEARCH block. Verify by running one search rather than showing a false claim.
    if not search_query and re.search(
        r"\b(?:i (?:just )?(?:ran|did|performed|conducted) (?:a |the )?"
        r"(?:quick |web |online )?search|i searched (?:the web|online)|"
        r"search results|my search|i looked it up)\b",
        raw or "",
        re.IGNORECASE,
    ):
        search_query = " ".join(_query_terms(title or message))[:160]

    if search_query:
        sources = web_research(search_query, limit=5)
        if sources:
            lines = [f"- {s['title']} ({s['url']}): {s['snippet']}" for s in sources]
            research_block = "RESEARCH SOURCES (cite these URLs only):\n" + "\n".join(lines) + "\n\n"
        else:
            research_block = (
                "WEB SEARCH RESULT: no usable sources were found. Answer from general "
                "knowledge, say when you are unsure, and do not invent URLs or numbers.\n\n"
            )
        followup = (
            f"{context}\n"
            f"{research_block}"
            f"CONVERSATION SO FAR:\n{conversation or '(new conversation)'}\n"
            f"USER REQUEST: {message}\n\n"
            "The web search you requested has been run. Now answer the user normally. "
            "Do not request another search. Cite only the supplied URLs. "
            "When the user asks specifically for image prompts, put only the prompt(s) in the "
            "IMAGE PROMPT section and keep the conversational reply to one short sentence."
        )
        raw = call_ai(provider_id, followup, CHAT_SYSTEM_PROMPT)

    parsed = parse_chat_response(raw)
    parsed["sources"] = sources
    parsed["ok"] = True
    return parsed


def run_roundtable(provider_id: str, title: str, context: str, platform: str, tone: str = "thought_leadership", source_url: str = "", verified_block: str = "") -> dict:
    """3-Agent Consensus Pipeline: Drafter -> Fact-Checker -> Hook/Format Optimizer -> Art Director.

    ``verified_block`` holds independently-verified/corrected facts. When present
    it is prepended to every agent's context and marked authoritative so a
    mistaken source article cannot propagate into the draft.
    """
    # Independent verification overrides the raw source text. Put it first and
    # last so it wins over the (possibly wrong) source article.
    if verified_block:
        context = (
            verified_block
            + "\n\n=== ORIGINAL SOURCE TEXT (may contain the errors listed above) ===\n"
            + context
        )
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
        "Your job is to verify claims against the INDEPENDENT VERIFIED FACTS supplied above, "
        "which override the original source article. If the source article contains an error "
        "that was corrected, you MUST use the corrected version. "
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
                     AND status IN ('Draft', 'Approved')
                     AND (notified_at IS NULL OR notified_at = '')""",
                (now_str,)
            )
            rows = [dict(r) for r in cur.fetchall()]
        
        for r in rows:
            draft_id = r["id"]
            if draft_id not in _NOTIFIED_SCHEDULED_DRAFTS:
                _NOTIFIED_SCHEDULED_DRAFTS.add(draft_id)
                notified.append(r)
                # Persist notification state so it survives server restarts
                with db() as conn:
                    conn.execute("UPDATE drafts SET notified_at = ? WHERE id = ?", (now_iso(), draft_id))
                msg = f"Time to publish '{r['title'][:40]}' on {r['platform']}! (Scheduled for {r['scheduled_for']})"
                print(f"[ContentOS Scheduler] ⏰ {msg}")
                # Notifications (disabled by default — set NOTIFICATIONS_ENABLED = True to re-enable)
                if NOTIFICATIONS_ENABLED:
                    # 1. Native Mac Desktop Notification
                    if sys.platform == "darwin":
                        try:
                            safe_title = r['title'][:40].replace('"', '\\"').replace("'", "")
                            safe_msg = f"Scheduled for {r['platform']} ({r['scheduled_for']})".replace('"', '\\"').replace("'", "")
                            subprocess.run(
                                ["osascript", "-e", f'tell application "System Events" to display notification "{safe_msg}" with title "ContentOS: Time to Post!" subtitle "{safe_title}" sound name "Glass"'],
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

def auto_publish_scheduled_drafts() -> list[dict]:
    """Auto-publish drafts that have reached their scheduled time and have auto_publish enabled.

    For each due draft, calls the real platform adapter (LinkedIn, X, YouTube,
    Facebook, Instagram, GitHub).  Updates the draft row with the returned
    post_id and live_url on success, or records the error on failure.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    published = []
    try:
        with db() as conn:
            cur = conn.execute(
                """SELECT id, title, body, platform, scheduled_for, status, auto_publish,
                          image_prompt, media_url, source_url
                   FROM drafts
                   WHERE scheduled_for != ''
                     AND scheduled_for <= ?
                     AND status = 'Approved'
                     AND auto_publish = 1""",
                (now_str,)
            )
            rows = [dict(r) for r in cur.fetchall()]

        for r in rows:
            draft_id = r["id"]
            platform = r.get("platform", "")
            title = r.get("title", "")
            body = r.get("body", "")
            image_url = r.get("media_url", "") or r.get("image_prompt", "")

            # ── Call the real platform adapter ──
            result = platform_publish(
                draft_id=draft_id,
                title=title,
                body=body,
                platform=platform,
                image_url="",
                media_url=image_url,
            )

            if result.ok:
                with db() as conn:
                    conn.execute(
                        """UPDATE drafts
                           SET status = 'Published',
                               live_url = ?,
                               post_id = ?,
                               published_at = ?,
                               updated_at = ?
                           WHERE id = ?""",
                        (result.live_url, result.post_id, now_iso(), now_iso(), draft_id),
                    )
                print(f"[ContentOS Auto-Publish] ✅ Published '{title[:40]}' "
                      f"on {platform} → {result.live_url}")
                published.append({**r, "ok": True, "live_url": result.live_url})
            else:
                with db() as conn:
                    conn.execute(
                        """UPDATE drafts
                           SET status = 'Failed',
                               publish_error = ?,
                               updated_at = ?
                           WHERE id = ?""",
                        (result.error, now_iso(), draft_id),
                    )
                print(f"[ContentOS Auto-Publish] ❌ Failed '{title[:40]}' "
                      f"on {platform}: {result.error}")
                published.append({**r, "ok": False, "error": result.error})

            # ── Webhook notification ──
            if NOTIFICATIONS_ENABLED:
                try:
                    cfg = get_webhook_config()
                    alert_draft = {
                        "title": f"🚀 Auto-Published: {title}",
                        "body": f"{'Published' if result.ok else 'Failed'} "
                                f"to {platform} at {r['scheduled_for']}.",
                        "platform": platform,
                        "status": "Published" if result.ok else "Failed",
                    }
                    if cfg.get("discord"):
                        send_webhook(cfg["discord"], build_discord_payload(alert_draft))
                    if cfg.get("slack"):
                        send_webhook(cfg["slack"], build_slack_payload(alert_draft))
                except Exception:
                    pass
    except Exception as e:
        print(f"[ContentOS Auto-Publish Error] {e}")
    return published

def _scheduler_loop() -> None:
    while True:
        try:
            check_scheduled_drafts()
            auto_publish_scheduled_drafts()
        except Exception:
            pass
        time.sleep(60)

def start_scheduler_daemon() -> None:
    t = threading.Thread(target=_scheduler_loop, daemon=True, name="ContentOS-Scheduler")
    t.start()


def _scan_watchlist_feeds(target_url: str = "") -> dict:
    """Scan enabled watchlist feeds and return new stories (no draft creation)."""
    import html as _html
    try:
        with db() as conn:
            if target_url:
                cur = conn.execute(
                    "SELECT * FROM source_watchlist WHERE url = ? AND enabled = 1", (target_url,))
            else:
                cur = conn.execute(
                    "SELECT * FROM source_watchlist WHERE enabled = 1 ORDER BY created_at DESC")
            feeds = [dict(r) for r in cur.fetchall()]
    except Exception:
        feeds = []

    stories = []
    checked = []
    errors = []
    for feed in feeds:
        url = feed["url"]
        try:
            items = fetch_rss_feed(url, limit=5)
            new_items = [i for i in items if i.get("url")]
            stories.extend(new_items)
            checked.append({"url": url, "label": feed.get("label", url), "count": len(new_items), "error": ""})
            with db() as conn:
                conn.execute(
                    "UPDATE source_watchlist SET last_checked = ? WHERE url = ?",
                    (now_iso(), url))
                conn.commit()
        except Exception as exc:
            checked.append({"url": url, "label": feed.get("label", url), "count": 0, "error": str(exc)})
            with db() as conn:
                conn.execute(
                    "UPDATE source_watchlist SET last_error = ? WHERE url = ?",
                    (str(exc)[:200], url))
                conn.commit()
            errors.append({"url": url, "error": str(exc)})

    # Dedupe by URL
    seen = set()
    unique = []
    for s in stories:
        u = s.get("url", "")
        if u and u not in seen:
            seen.add(u)
            unique.append(s)

    return {"ok": True, "feeds_checked": len(checked), "feeds": checked,
            "errors": errors, "stories": unique, "count": len(unique)}


def _run_watchlist_check() -> dict:
    """Check watchlist feeds and auto-queue new stories as drafts."""
    scan = _scan_watchlist_feeds()
    queued = 0
    for story in scan.get("stories", []):
        url = story.get("url", "")
        title = story.get("title", "Untitled")
        if not url:
            continue
        try:
            with db() as conn:
                cur = conn.execute("SELECT 1 FROM drafts WHERE source_url = ? LIMIT 1", (url,))
                if cur.fetchone():
                    continue
                cur = conn.execute("SELECT 1 FROM sources WHERE url = ? LIMIT 1", (url,))
                if cur.fetchone():
                    continue
                # Queue as a draft so it appears in Queue for review
                stamp = now_iso()
                conn.execute(
                    "INSERT INTO drafts(title, body, platform, status, created_at, source_url, image_prompt) VALUES(?,?,?,?,?,?,?)",
                    (title, story.get("snippet", ""), "LinkedIn", "Queued", stamp, url, ""))
                conn.commit()
                queued += 1
        except Exception:
            pass
    scan["queued"] = queued
    scan["message"] = f"Checked {scan['feeds_checked']} feeds, queued {queued} new stories"
    return scan


def calculate_next_scrape_time() -> datetime:
    """Calculate the next 6:30 AM scrape time."""
    now = datetime.now()
    today_630am = now.replace(hour=6, minute=30, second=0, microsecond=0)
    if now < today_630am:
        return today_630am
    from datetime import timedelta
    return (now + timedelta(days=1)).replace(hour=6, minute=30, second=0, microsecond=0)


def _daily_scrape_loop() -> None:
    """Background loop that runs the content scraper at 6:30 AM daily."""
    import subprocess as _sp
    while True:
        next_run = calculate_next_scrape_time()
        wait_seconds = (next_run - datetime.now()).total_seconds()
        if wait_seconds > 0:
            print(f"[ContentOS Daily Scraper] Next scrape scheduled for {next_run.strftime('%Y-%m-%d %H:%M')}")
            time.sleep(wait_seconds)
        # Run the worker cycle
        try:
            project_root = Path(__file__).resolve().parent.parent
            worker_path = project_root / "app" / "worker.py"
            print(f"[ContentOS Daily Scraper] ⏰ Starting 6:30 AM content scrape...")
            result = _sp.run(
                [sys.executable, str(worker_path), "--once"],
                capture_output=True, text=True, timeout=600,
                cwd=str(project_root)
            )
            if result.returncode == 0:
                print(f"[ContentOS Daily Scraper] ✅ Scrape completed successfully")
                if NOTIFICATIONS_ENABLED and sys.platform == "darwin":
                    try:
                        subprocess.run(
                            ["osascript", "-e", 'tell application "System Events" to display notification "Fresh content queued for your review" with title "ContentOS: Daily Scrape Complete" sound name "Glass"'],
                            capture_output=True, timeout=2
                        )
                    except Exception:
                        pass
            else:
                print(f"[ContentOS Daily Scraper] ⚠️ Scrape exited with code {result.returncode}")
                if result.stderr:
                    print(f"[ContentOS Daily Scraper] stderr: {result.stderr[:500]}")
                if NOTIFICATIONS_ENABLED and sys.platform == "darwin":
                    try:
                        subprocess.run(
                            ["osascript", "-e", 'tell application "System Events" to display notification "Check logs for details" with title "ContentOS: Scrape Failed" sound name "Basso"'],
                            capture_output=True, timeout=2
                        )
                    except Exception:
                        pass
        except Exception as exc:
            print(f"[ContentOS Daily Scraper Error] {exc}")
            if NOTIFICATIONS_ENABLED and sys.platform == "darwin":
                try:
                    subprocess.run(
                        ["osascript", "-e", 'tell application "System Events" to display notification "Check logs for details" with title "ContentOS: Scrape Error" sound name "Basso"'],
                        capture_output=True, timeout=2
                    )
                except Exception:
                    pass
        # Sleep a bit to avoid re-triggering
        time.sleep(60)


def start_daily_scrape_daemon() -> None:
    t = threading.Thread(target=_daily_scrape_loop, daemon=True, name="ContentOS-DailyScraper")
    t.start()


_URL_IN_TEXT = re.compile(r"https?://\S+", re.IGNORECASE)


def _x_char_weight(ch: str) -> int:
    """X counts most non-ASCII code points as 2, a few ranges as 1."""
    cp = ord(ch)
    if cp <= 0x10FF or 0x2000 <= cp <= 0x200D or 0x2010 <= cp <= 0x201F or 0x2032 <= cp <= 0x2037:
        return 1
    return 2


def x_weighted_len(text: str) -> int:
    """X/Twitter's weighted character count.

    Every URL counts as 23 characters regardless of its real length (t.co
    wrapping), and emoji/CJK count as 2. This is the number that must stay
    <= 280 — not naive ``len()``.
    """
    if not text:
        return 0
    total = 0
    for part in _URL_IN_TEXT.split(text):
        if part:
            total += sum(_x_char_weight(ch) for ch in part)
    # One URL (23) for each split separator occurrence.
    total += 23 * (len(_URL_IN_TEXT.findall(text)))
    return total


def x_effective_len(text: str) -> int:
    """Conservative length: satisfies BOTH the platform counter and raw len.

    Weighted count is smaller than raw for long URLs; raw is smaller for
    emoji. Taking the max keeps a post within 280 by either measure.
    """
    return max(len(text or ""), x_weighted_len(text or ""))


def _truncate_for_x(text: str, budget: int) -> str:
    """Trim text with an ellipsis until its effective length fits budget."""
    if budget <= 0:
        return ""
    if x_effective_len(text) <= budget:
        return text
    end = text
    while end and x_effective_len(end.rstrip() + "…") > budget:
        end = end[:-1]
    return end.rstrip() + "…" if end else ""


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
                if x_effective_len(s_stripped) > 180:
                    words = s_stripped.split()
                    cur = []
                    for w in words:
                        if x_effective_len(" ".join(cur + [w])) > 180:
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
        elif x_effective_len(current) + x_effective_len(s) + 1 <= budget:
            current += " " + s
        else:
            raw_tweets.append(current.strip())
            current = s
    if current:
        raw_tweets.append(current.strip())

    total = len(raw_tweets)
    if total <= 1:
        t = raw_tweets[0] if raw_tweets else clean_text
        return [_truncate_for_x(t, max_tweet_len)]

    final_tweets = []
    for i, tw in enumerate(raw_tweets):
        prefix = f"{i+1}/{total}\n\n"
        budget = max_tweet_len - x_effective_len(prefix)
        tweet_body = _truncate_for_x(tw, budget)
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
    
    if x_effective_len(cleaned.strip()) <= max_chars:
        return cleaned.strip()

    urls = re.findall(r"https?://\S+", cleaned)
    primary_url = urls[0].rstrip(".,;):") if urls else ""
    hashtags = re.findall(r"#\w+", cleaned)
    tags_str = " ".join(hashtags[:2]) if hashtags else ""

    prose = cleaned
    for u in urls:
        prose = prose.replace(u, "")
    for h in hashtags:
        prose = prose.replace(h, "")
    prose = re.sub(r"\s+", " ", prose).strip()

    # X counts every URL as 23 chars regardless of its real length (t.co).
    url_cost = 23 if primary_url else 0
    tag_cost = x_effective_len(tags_str) if tags_str else 0
    prose_budget = max_chars - url_cost - tag_cost - 4  # newlines/separators
    if prose_budget < 60 and primary_url:
        prose_budget = min(140, max_chars - url_cost - 4)
    prose_budget = max(prose_budget, 20)

    condensed = _truncate_for_x(prose, prose_budget) if x_effective_len(prose) > prose_budget else prose

    parts = [condensed]
    if primary_url:
        parts.append(primary_url)
    if tags_str:
        parts.append(tags_str)

    res = "\n\n".join(p for p in parts if p)
    if x_effective_len(res) > max_chars:
        # Drop hashtags first, then trim prose; always keep the link last.
        parts = [condensed]
        if primary_url:
            parts.append(primary_url)
        res = "\n\n".join(p for p in parts if p)
        if x_effective_len(res) > max_chars:
            res = _truncate_for_x(res, max_chars)
    return res


def format_as_carousel(title: str, post_text: str, handle: str = "@JustMeMedia") -> list[dict]:
    """Convert post into multi-slide carousel outlines for LinkedIn or Instagram.

    ``handle`` is configurable so the closing CTA is not hardcoded to one brand.
    """
    paragraphs = [p.strip() for p in post_text.split("\n\n") if p.strip()]
    slides = [{"slide": 1, "heading": "HOOK", "body": title}]
    for i, p in enumerate(paragraphs[:5], start=2):
        lines = p.split("\n")
        heading = lines[0][:40] if len(lines) > 1 else f"KEY POINT {i-1}"
        body = "\n".join(lines[1:]) if len(lines) > 1 else p
        slides.append({"slide": i, "heading": heading, "body": body})
    cta = (handle or "").strip()
    if cta and not cta.startswith("@"):
        cta = "@" + cta
    slides.append({
        "slide": len(slides) + 1, "heading": "TAKEAWAY",
        "body": f"Follow {cta} for daily cutting-edge insights." if cta else "Follow for daily cutting-edge insights.",
    })
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
        return filter_rejected_sources(items) if items else FALLBACK_STORIES
    except Exception:
        return FALLBACK_STORIES


def filter_rejected_sources(items: list[dict]) -> list[dict]:
    """Drop any article the user has explicitly dismissed via Reject Article."""
    if not items:
        return items
    urls = {i["url"] for i in items if i.get("url")}
    if not urls:
        return items
    try:
        with db() as conn:
            cur = conn.execute(
                f"SELECT url FROM rejected_sources WHERE url IN ({','.join('?' * len(urls))})",
                tuple(urls)
            )
            rejected = {row["url"] for row in cur.fetchall()}
    except Exception:
        rejected = set()
    return [i for i in items if i.get("url") not in rejected]


# ─────────────────────────────────────────────────────────────────────────────
# PHASE F: GITHUB TRENDING REPOS
# ─────────────────────────────────────────────────────────────────────────────

GITHUB_TRENDING_BASE = "https://github.com/trending"
GITHUB_API_BASE = "https://api.github.com"


def fetch_github_trending(category: str = "all", language: str = "", days: int = 7) -> list[dict]:
    """Fetch trending GitHub repos via the public REST API.

    Uses ``/search/repositories`` sorted by stars with a recent ``created:``
    filter to approximate a "trending this week" list. No authentication is
    required (unauthenticated calls are rate-limited to 60/hour); set
    ``CONTENTOS_GITHUB_TOKEN`` to raise the limit. A curated list is used only
    when the API is unreachable, and is labeled as sample data so a post is
    never published from stale numbers without the operator knowing.

    Args:
        category: kept for API compatibility (search is language-based).
        language: language filter (e.g. 'python', 'rust') or '' for all.
        days: window in days for the ``created:`` filter (1, 7, or 30).

    Returns:
        List of dicts with keys: full_name, url, description, stars, language.
    """
    results: list[dict] = []
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        query = f"created:>{since}"
        if language and language.lower() != "all":
            query += f" language:{language}"
        params = urllib.parse.urlencode({
            "q": query, "sort": "stars", "order": "desc", "per_page": 10,
        })
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "JustMeMediaContentOS/1.0",
        }
        token = os.environ.get("CONTENTOS_GITHUB_TOKEN", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(
            f"{GITHUB_API_BASE}/search/repositories?{params}", headers=headers
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        for item in data.get("items", [])[:10]:
            full_name = item.get("full_name", "")
            html_url = item.get("html_url", "")
            if not full_name or not html_url:
                continue
            results.append({
                "full_name": full_name,
                "url": html_url,
                "description": (item.get("description") or "")[:500],
                "stars": int(item.get("stargazers_count") or 0),
                "language": item.get("language") or "Unknown",
            })
    except Exception:
        results = []

    if results:
        return results

    # Offline fallback: labeled sample data so callers can warn the user.
    return _sample_github_repos(language)


def _sample_github_repos(language: str = "") -> list[dict]:
    """Curated illustrative repos used only when the GitHub API is unavailable.

    Star counts are approximate snapshots, not live data. Every entry carries
    ``sample: True`` so the UI can disclose that the list is not live.
    """
    fallbacks = {
        "python": [
            {"full_name": "huggingface/transformers", "url": "https://github.com/huggingface/transformers", "description": "State-of-the-art NLP", "stars": 105000, "language": "Python"},
            {"full_name": "pytorch/pytorch", "url": "https://github.com/pytorch/pytorch", "description": "Deep learning framework", "stars": 210000, "language": "Python"},
            {"full_name": "pandas-dev/pandas", "url": "https://github.com/pandas-dev/pandas", "description": "Data analysis ecosystem", "stars": 45000, "language": "Python"},
            {"full_name": "django/django", "url": "https://github.com/django/django", "description": "Web framework", "stars": 78000, "language": "Python"},
            {"full_name": "scikit-learn/scikit-learn", "url": "https://github.com/scikit-learn/scikit-learn", "description": "Machine learning library", "stars": 58000, "language": "Python"},
            {"full_name": "psf/requests", "url": "https://github.com/psf/requests", "description": "HTTP library", "stars": 62000, "language": "Python"},
            {"full_name": "microsoft/semantic-kernel", "url": "https://github.com/microsoft/semantic-kernel", "description": "Build AI apps with natural language", "stars": 48000, "language": "C#"},
            {"full_name": "openai/openai-cookbook", "url": "https://github.com/openai/openai-cookbook", "description": "Recipes", "stars": 22000, "language": "Python"},
        ],
        "javascript": [
            {"full_name": "facebook/react", "url": "https://github.com/facebook/react", "description": "JavaScript library", "stars": 230000, "language": "JavaScript"},
            {"full_name": "vercel/next.js", "url": "https://github.com/vercel/next.js", "description": "The React Framework", "stars": 160000, "language": "TypeScript"},
            {"full_name": "nodejs/node", "url": "https://github.com/nodejs/node", "description": "Node.js runtime", "stars": 108000, "language": "C++"},
            {"full_name": "angular/angular", "url": "https://github.com/angular/angular", "description": "One framework for mobile", "stars": 83000, "language": "TypeScript"},
        ],
        "rust": [
            {"full_name": "rust-lang/rust", "url": "https://github.com/rust-lang/rust", "description": "The Rust programming language", "stars": 110000, "language": "Rust"},
            {"full_name": "tokio-rs/tokio", "url": "https://github.com/tokio-rs/tokio", "description": "Async runtime", "stars": 26000, "language": "Rust"},
        ],
    }
    lang = language.lower() if language.lower() in fallbacks else "python"
    sample = [dict(r, sample=True) for r in fallbacks[lang][:10]]
    return sample


def store_github_repos(repos: list[dict], category: str = "General") -> int:
    """Store a batch of repos in the daily snapshot table."""
    # Use the SAME local-date clock as get_weekly_top_10() and the scheduler.
    # previously this used now_iso()[:10] (UTC), which disagrees with local
    # date in the evening for negative UTC offsets and hid stored repos.
    stamp = local_date_str()
    stored = 0
    with db() as conn:
        for r in repos:
            cur = conn.execute(
                "INSERT OR IGNORE INTO github_repos(full_name, url, description, stars, language, fetched_at, category, sample) VALUES(?,?,?,?,?,?,?,?)",
                (r["full_name"], r["url"], r["description"][:500], r["stars"], r["language"], stamp, category, 1 if r.get("sample") else 0)
            )
            if cur.rowcount:
                stored += 1
    return stored


def get_weekly_top_10(category: str = "General", platform: str = "LinkedIn") -> list[dict]:
    """Get the top 10 repos of the current week by stars gained (7-day window)."""
    week_start = local_date_str()
    with db() as conn:
        cur = conn.execute(
            "SELECT * FROM github_repos WHERE category = ? AND fetched_at = ? ORDER BY stars DESC LIMIT 10",
            (category, week_start)
        )
        rows = [dict(r) for r in cur.fetchall()]
        if rows:
            return rows
        # Fall back to any category for the current week
        cur = conn.execute(
            "SELECT * FROM github_repos WHERE fetched_at = ? ORDER BY stars DESC LIMIT 10",
            (week_start,)
        )
        return [dict(r) for r in cur.fetchall()]


def generate_weekly_github_bundle(category: str = "General", platform: str = "LinkedIn") -> dict:
    """Generate a ready-to-publish weekly Top 10 GitHub repos post."""
    repos = get_weekly_top_10(category, platform)
    if not repos:
        # Try the most recent days to find any cached repo data
        with db() as conn:
            cur = conn.execute("SELECT DISTINCT fetched_at FROM github_repos ORDER BY fetched_at DESC LIMIT 1")
            row = cur.fetchone()
        if row:
            repos = get_weekly_top_10(category, platform)

    if not repos:
        return {"ok": False, "error": "No GitHub repos cached for this week. Run a fetch cycle first."}

    lines = [f"# Weekly GitHub Stars – Top 10 Open Source ({category})\n"]
    for i, r in enumerate(repos[:10], 1):
        desc = (r["description"] or "No description")[:120]
        lang = r["language"] or "Multilingual"
        lines.append(f"{i}. **{r['full_name']}** – {r['stars']:,} ⭐ | {lang}\n   {desc}\n   🔗 {r['url']}\n")

    lines.append("\n---\n_Published by JustMeMedia ContentOS_")
    body = "\n".join(lines)

    # Generate an image prompt for the post
    img_prompt = f"Modern GitHub Octocat logo integrated with a vertical leaderboard showing ranked open-source projects, dark theme, cyan accents, 4K render style for {'LinkedIn' if platform.lower()=='linkedin' else 'social media'}"

    return {
        "ok": True,
        "title": f"Weekly GitHub Top 10 – {datetime.now().strftime('%B %d, %Y')}",
        "body": body,
        "platform": platform,
        "image_prompt": img_prompt,
        "repos": repos,
        "sample": any(bool(r.get("sample")) for r in repos),
    }


# Load HTML template from static files
_STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
HTML_PATH = os.path.join(_STATIC_DIR, "index.html")

def _load_html() -> str:
    with open(HTML_PATH, encoding="utf-8") as f:
        return f.read()



class Handler(BaseHTTPRequestHandler):
    def _send(self, raw: bytes, status: int = 200, content_type: str = "text/html; charset=utf-8", extra_headers: dict | None = None) -> None:
        path = urlparse(self.path).path
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline' 'unsafe-eval' https:; img-src 'self' data: https:;")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        # Cache policy: fingerprinted assets can be cached forever so browsers
        # pick up new bundles after an update; everything else (HTML shell and
        # API responses) must revalidate or users keep a stale UI after upgrade.
        if path.startswith("/assets/") or path.startswith("/static/assets/"):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        else:
            self.send_header("Cache-Control", "no-cache")
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
                favicon = os.path.join(_STATIC_DIR, "favicon.svg")
                if os.path.isfile(favicon):
                    with open(favicon, "rb") as f:
                        self._send(f.read(), content_type="image/svg+xml")
                else:
                    self.send_response(204)
                    self.end_headers()
                return

            # Serve built JS/CSS/assets from the React build (static/assets/*)
            if path.startswith("/assets/") or path.startswith("/static/assets/"):
                import mimetypes
                rel = path[len("/assets/"):] if path.startswith("/assets/") else path[len("/static/assets/"):]
                rel = rel.replace("..", "")
                file_path = os.path.join(_STATIC_DIR, "assets", rel)
                if os.path.isfile(file_path):
                    mime, _ = mimetypes.guess_type(file_path)
                    with open(file_path, "rb") as f:
                        self._send(f.read(), content_type=mime or "application/octet-stream")
                else:
                    self.send_error(404)
                return

            # SPA fallback: any non-API route serves the React app
            if not path.startswith("/api/"):
                self._send(_load_html().encode("utf-8"))
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

            # Dashboard stats
            if path == "/api/dashboard-stats":
                with db() as conn:
                    total = conn.execute("SELECT COUNT(*) AS c FROM drafts").fetchone()["c"]
                    active = conn.execute("SELECT COUNT(*) AS c FROM drafts WHERE status IN ('Draft', 'Approved')").fetchone()["c"]
                    published = conn.execute("SELECT COUNT(*) AS c FROM drafts WHERE status = 'Published'").fetchone()["c"]
                    scheduled = conn.execute("SELECT COUNT(*) AS c FROM drafts WHERE scheduled_for != '' AND status IN ('Draft', 'Approved')").fetchone()["c"]
                    rejected = conn.execute("SELECT COUNT(*) AS c FROM rejected_sources").fetchone()["c"]
                    # Platform breakdown
                    platform_rows = conn.execute("SELECT platform, COUNT(*) AS c FROM drafts WHERE status IN ('Draft', 'Approved') GROUP BY platform").fetchall()
                    platform_breakdown = {r["platform"]: r["c"] for r in platform_rows}
                    # Recent activity (last 7 days)
                    week_ago = (datetime.now() - __import__('datetime').timedelta(days=7)).strftime("%Y-%m-%d")
                    recent = conn.execute("SELECT COUNT(*) AS c FROM drafts WHERE created_at >= ?", (week_ago,)).fetchone()["c"]
                    # Tag breakdown
                    tag_rows = conn.execute("SELECT tags FROM drafts WHERE tags != ''").fetchall()
                    tag_counts = {}
                    for r in tag_rows:
                        for t in r["tags"].split(","):
                            t = t.strip()
                            if t:
                                tag_counts[t] = tag_counts.get(t, 0) + 1
                self.send_json({
                    "total": total,
                    "active": active,
                    "published": published,
                    "scheduled": scheduled,
                    "rejected": rejected,
                    "recent_7days": recent,
                    "platform_breakdown": platform_breakdown,
                    "tag_counts": tag_counts
                })
                return

            # Templates CRUD
            if path == "/api/templates" and self.command == "GET":
                with db() as conn:
                    rows = [dict(r) for r in conn.execute("SELECT * FROM templates ORDER BY name")]
                self.send_json(rows)
                return

            if path == "/api/templates" and self.command == "POST":
                name = string_field(payload, "name")
                if not name:
                    raise ApiError(400, "Template name is required")
                platform = string_field(payload, "platform") or "General"
                title_template = string_field(payload, "title_template")
                body_template = string_field(payload, "body_template")
                image_prompt_template = string_field(payload, "image_prompt_template")
                tags = string_field(payload, "tags")
                stamp = now_iso()
                with db() as conn:
                    cur = conn.execute(
                        """INSERT INTO templates(name, platform, title_template, body_template, image_prompt_template, tags, created_at, updated_at)
                           VALUES(?,?,?,?,?,?,?,?)""",
                        (name, platform, title_template, body_template, image_prompt_template, tags, stamp, stamp)
                    )
                    template_id = cur.lastrowid
                self.send_json({"ok": True, "id": template_id}, 201)
                return

            if path.startswith("/api/templates/") and path.endswith("/delete") and self.command == "POST":
                template_id = path.split("/")[3]
                with db() as conn:
                    conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))
                self.send_json({"ok": True})
                return

            # Bulk operations
            if path == "/api/drafts/bulk-approve" and self.command == "POST":
                ids = payload.get("ids", [])
                stamp = now_iso()
                with db() as conn:
                    for did in ids:
                        conn.execute("UPDATE drafts SET status = 'Approved', updated_at = ? WHERE id = ?", (stamp, did))
                self.send_json({"ok": True, "count": len(ids)})
                return

            if path == "/api/drafts/bulk-delete" and self.command == "POST":
                ids = payload.get("ids", [])
                with db() as conn:
                    for did in ids:
                        conn.execute("DELETE FROM drafts WHERE id = ?", (did,))
                self.send_json({"ok": True, "count": len(ids)})
                return

            if path == "/api/drafts/bulk-schedule" and self.command == "POST":
                ids = payload.get("ids", [])
                scheduled_for = string_field(payload, "scheduled_for")
                stamp = now_iso()
                auto_publish = 1 if scheduled_for else 0
                with db() as conn:
                    for did in ids:
                        conn.execute("UPDATE drafts SET scheduled_for = ?, auto_publish = ?, updated_at = ? WHERE id = ?", (scheduled_for, auto_publish, stamp, did))
                self.send_json({"ok": True, "count": len(ids), "scheduled_for": scheduled_for})
                return

            # Draft version history
            if path.startswith("/api/drafts/") and path.endswith("/versions") and self.command == "GET":
                draft_id = path.split("/")[3]
                with db() as conn:
                    rows = [dict(r) for r in conn.execute("SELECT * FROM draft_versions WHERE draft_id = ? ORDER BY version_number DESC", (draft_id,))]
                self.send_json(rows)
                return

            if path.startswith("/api/drafts/") and path.endswith("/revert") and self.command == "POST":
                draft_id = path.split("/")[3]
                version_id = payload.get("version_id")
                stamp = now_iso()
                with db() as conn:
                    vrow = conn.execute("SELECT * FROM draft_versions WHERE id = ? AND draft_id = ?", (version_id, draft_id)).fetchone()
                    if not vrow:
                        raise ApiError(404, "Version not found")
                    vrow = dict(vrow)
                    conn.execute(
                        "UPDATE drafts SET title = ?, body = ?, body_html = ?, platform = ?, image_prompt = ?, tags = ?, updated_at = ? WHERE id = ?",
                        (vrow["title"], vrow["body"], vrow.get("body_html", "") or "", vrow["platform"], vrow["image_prompt"], vrow["tags"], stamp, draft_id)
                    )
                log_activity("draft_reverted", "draft", int(draft_id), f"Reverted to version {vrow['version_number']}")
                self.send_json({"ok": True, "version": vrow["version_number"]})
                return

            # Activity log
            if path == "/api/activity-log":
                limit = int(query.get("limit", ["50"])[0])
                with db() as conn:
                    rows = [dict(r) for r in conn.execute("SELECT * FROM activity_log ORDER BY id DESC LIMIT ?", (limit,))]
                self.send_json(rows)
                return

            # Engagement metrics update
            if path.startswith("/api/drafts/") and path.endswith("/engagement") and self.command == "POST":
                draft_id = path.split("/")[3]
                views = payload.get("views", 0)
                engagements = payload.get("engagements", 0)
                stamp = now_iso()
                with db() as conn:
                    conn.execute("UPDATE drafts SET views = ?, engagements = ?, updated_at = ? WHERE id = ?", (views, engagements, stamp, draft_id))
                log_activity("engagement_updated", "draft", int(draft_id), f"Views: {views}, Engagements: {engagements}")
                self.send_json({"ok": True})
                return

            # Source provenance for a draft
            if path.startswith("/api/drafts/") and path.endswith("/provenance") and self.command == "GET":
                draft_id = path.split("/")[3]
                with db() as conn:
                    draft = conn.execute("SELECT source_url, title, created_at FROM drafts WHERE id = ?", (draft_id,)).fetchone()
                    if not draft:
                        raise ApiError(404, "Draft not found")
                    draft = dict(draft)
                    source = None
                    if draft["source_url"]:
                        src = conn.execute("SELECT * FROM sources WHERE url = ?", (draft["source_url"],)).fetchone()
                        if src:
                            source = dict(src)
                self.send_json({"draft": draft, "source": source})
                return

            if path == "/api/drafts":
                with db() as conn:
                    rows = [dict(r) for r in conn.execute("SELECT * FROM drafts ORDER BY updated_at DESC, id DESC")]
                self.send_json(rows)
                return

            if path == "/api/sources":
                with db() as conn:
                    rows = [dict(r) for r in conn.execute("SELECT * FROM sources ORDER BY retrieved_at DESC")]
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

            # Rejected sources list (so dismissed articles stay out of the feed)
            if path == "/api/rejected-sources":
                with db() as conn:
                    rows = [dict(r) for r in conn.execute("SELECT * FROM rejected_sources ORDER BY id DESC")]
                self.send_json(rows)
                return

            # Source Watchlist GET - list all watchlist items
            if path == "/api/watchlist":
                with db() as conn:
                    rows = [dict(r) for r in conn.execute(
                        "SELECT * FROM source_watchlist ORDER BY created_at DESC")]
                self.send_json({"ok": True, "items": rows})
                return

            # --- GitHub Trending APIs ---
            if path == "/api/github/trending":
                lang = query.get("language", [""])[0]
                days = int(query.get("days", ["7"])[0])
                try:
                    repos = fetch_github_trending("all", lang, days)
                    sample = any(bool(r.get("sample")) for r in repos)
                    self.send_json({"ok": True, "repos": repos, "count": len(repos), "sample": sample})
                except Exception as exc:
                    self.send_error_json(500, str(exc))
                return

            if path == "/api/github/fetch":
                lang = query.get("language", [""])[0]
                category = query.get("category", ["General"])[0]
                days = int(query.get("days", ["7"])[0])
                try:
                    repos = fetch_github_trending("all", lang, days)
                    stored = store_github_repos(repos, category)
                    sample = any(bool(r.get("sample")) for r in repos)
                    self.send_json({"ok": True, "fetched": len(repos), "stored": stored, "sample": sample})
                except Exception as exc:
                    self.send_error_json(500, str(exc))
                return

            if path == "/api/github/top10":
                category = query.get("category", ["General"])[0]
                platform = query.get("platform", ["LinkedIn"])[0]
                try:
                    bundle = generate_weekly_github_bundle(category, platform)
                    if bundle["ok"]:
                        self.send_json(bundle)
                    else:
                        self.send_error_json(404, bundle.get("error", "No data"))
                except Exception as exc:
                    self.send_error_json(500, str(exc))
                return

            # Phase C: Draw Things status
            if path == "/api/draw-things-status":
                self.send_json({"available": draw_things_available(), "url": DRAW_THINGS_URL})
                return

            # Image provider status
            if path == "/api/image-providers":
                providers = []
                if draw_things_available():
                    providers.append({"id": "drawthings", "name": "Draw Things (local)", "available": True})
                else:
                    providers.append({"id": "drawthings", "name": "Draw Things (local)", "available": False})
                for pid, name, key in [
                    ("openai", "OpenAI DALL-E 3", "OPENAI_API_KEY"),
                    ("stability", "Stability AI", "STABILITY_API_KEY"),
                    ("replicate", "Replicate (FLUX)", "REPLICATE_API_TOKEN"),
                ]:
                    providers.append({"id": pid, "name": name, "available": bool(os.environ.get(key, "").strip())})
                active = os.environ.get("IMAGE_PROVIDER", "auto").lower().strip()
                self.send_json({"providers": providers, "active": active})
                return

            # Phase C: Serve generated media files
            if path.startswith("/api/media/"):
                filename = path.rsplit("/", 1)[-1]
                ext = filename.rsplit(".", 1)[-1].lower()
                content_types = {
                    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "webp": "image/webp", "gif": "image/gif",
                }
                if not filename or "/" in filename or ".." in filename or ext not in content_types:
                    self.send_error_json(400, "Invalid filename")
                    return
                filepath = MEDIA_DIR / filename
                if not filepath.exists():
                    self.send_error_json(404, "Media not found")
                    return
                self._send(filepath.read_bytes(), content_type=content_types[ext])
                return

            # List generated media files (newest first) for the gallery
            if path == "/api/media":
                try:
                    limit = int(query.get("limit", ["60"])[0])
                except (TypeError, ValueError):
                    limit = 60
                limit = max(1, min(limit, 500))
                files = []
                allowed = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
                for fp in sorted(
                    (p for p in MEDIA_DIR.iterdir() if p.is_file() and p.suffix.lower() in allowed),
                    key=lambda p: p.stat().st_mtime, reverse=True
                )[:limit]:
                    files.append({
                        "filename": fp.name,
                        "url": f"/api/media/{fp.name}",
                        "size": fp.stat().st_size,
                        "modified": datetime.fromtimestamp(fp.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                    })
                self.send_json({"ok": True, "files": files, "count": len(files), "dir": str(MEDIA_DIR)})
                return

            # Phase E: Get webhook config (masked)
            if path == "/api/webhooks":
                config = get_webhook_config()
                safe = {k: ("***configured***" if v else "") for k, v in config.items()}
                self.send_json(safe)
                return

            # ── Update Check ────────────────────────────────────────────────
            if path == "/api/update":
                result = check_for_update()
                self.send_json(result)
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

            # Approve draft
            if path.startswith("/api/drafts/") and path.endswith("/approve"):
                draft_id = path.split("/")[3]
                stamp = now_iso()
                with db() as conn:
                    conn.execute("UPDATE drafts SET status = 'Approved', updated_at = ? WHERE id = ?", (stamp, draft_id))
                    conn.execute("INSERT INTO approvals(draft_id, approved_at, platform, notes) VALUES(?,?,?,?)",
                                 (draft_id, stamp, "General", "Approved by human user"))
                log_activity("draft_approved", "draft", int(draft_id), "Draft approved for publishing")
                self.send_json({"ok": True, "status": "Approved"})
                return

            # Mark draft published
            if path.startswith("/api/drafts/") and path.endswith("/publish"):
                draft_id = int(path.split("/")[3])
                stamp = now_iso()
                # Fetch the draft to call the real platform adapter
                with db() as conn:
                    row = conn.execute(
                        "SELECT * FROM drafts WHERE id = ?", (draft_id,)
                    ).fetchone()
                if not row:
                    self.send_error_json(404, "Draft not found")
                    return
                d = dict(row)
                result = platform_publish(
                    draft_id=draft_id,
                    title=d.get("title", ""),
                    body=d.get("body", ""),
                    platform=d.get("platform", ""),
                    image_url="",
                    media_url=d.get("media_url", ""),
                )
                if result.ok:
                    with db() as conn:
                        conn.execute(
                            """UPDATE drafts
                               SET status = 'Published',
                                   live_url = ?,
                                   post_id = ?,
                                   published_at = ?,
                                   updated_at = ?
                               WHERE id = ?""",
                            (result.live_url, result.post_id, stamp, stamp, draft_id),
                        )
                    log_activity("draft_published", "draft", draft_id,
                                 f"Published on {d.get('platform','')}: {result.live_url}")
                    self.send_json({"ok": True, "status": "Published",
                                    "live_url": result.live_url,
                                    "post_id": result.post_id})
                else:
                    with db() as conn:
                        conn.execute(
                            "UPDATE drafts SET status = 'Failed', publish_error = ?, updated_at = ? WHERE id = ?",
                            (result.error, stamp, draft_id),
                        )
                    self.send_json({"ok": False, "error": result.error,
                                    "status": "Failed"})
                return

            # Mark draft as published manually (user posted it themselves)
            if path.startswith("/api/drafts/") and path.endswith("/mark-published"):
                draft_id = int(path.split("/")[3])
                stamp = now_iso()
                with db() as conn:
                    row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
                    if not row:
                        self.send_error_json(404, "Draft not found")
                        return
                    conn.execute(
                        """UPDATE drafts
                           SET status = 'Published',
                               published_at = ?,
                               updated_at = ?
                           WHERE id = ?""",
                        (stamp, stamp, draft_id),
                    )
                log_activity("draft_marked_published", "draft", draft_id, "Manually marked as published")
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

            # Reject / dismiss a source article so it stops appearing in the feed
            if path == "/api/reject-source":
                url = string_field(payload, "url")
                title = string_field(payload, "title")
                if not url:
                    raise ApiError(400, "Source URL is required to reject an article.")
                stamp = now_iso()
                with db() as conn:
                    conn.execute(
                        "INSERT OR IGNORE INTO rejected_sources(url, title, rejected_at) VALUES(?,?,?)",
                        (url, title[:200], stamp)
                    )
                self.send_json({"ok": True, "url": url})
                return

            # Clear all rejected sources so dismissed articles reappear in the feed
            if path == "/api/rejected-sources/clear":
                with db() as conn:
                    cur = conn.execute("DELETE FROM rejected_sources")
                self.send_json({"ok": True, "cleared": cur.rowcount})
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

            # Weekly GitHub Top 10 bundle generation
            if path == "/api/github/weekly":
                category = string_field(payload, "category") or "General"
                platform = string_field(payload, "platform") or "LinkedIn"
                try:
                    # First ensure we have fresh repos
                    repos = fetch_github_trending("all", "", 7)
                    stored = store_github_repos(repos, category)
                    bundle = generate_weekly_github_bundle(category, platform)
                    if not bundle["ok"]:
                        raise ValueError("Failed to generate bundle")
                    self.send_json({"ok": True, "fetched": len(repos), "stored": stored, **bundle})
                except Exception as exc:
                    self.send_error_json(500, str(exc))
                return

            if path == "/api/github/repos":
                category = query.get("category", ["General"])[0]
                limit = int(query.get("limit", ["10"])[0])
                try:
                    with db() as conn:
                        rows = [dict(r) for r in conn.execute(
                            "SELECT * FROM github_repos WHERE category = ? ORDER BY fetched_at DESC, stars DESC LIMIT ?",
                            (category, limit)
                        )]
                    self.send_json({"ok": True, "repos": rows, "count": len(rows)})
                except Exception as exc:
                    self.send_error_json(500, str(exc))
                return

            # Update Draft Body (for auto-fit and split thread on draft card)
            if path.startswith("/api/drafts/") and path.endswith("/update-body"):
                draft_id = path.split("/")[3]
                body_text = string_field(payload, "body")
                tags = string_field(payload, "tags")
                stamp = now_iso()
                with db() as conn:
                    # Get current draft for version snapshot
                    cur = conn.execute("SELECT title, body, body_html, platform, image_prompt, tags FROM drafts WHERE id = ?", (draft_id,))
                    current = cur.fetchone()
                    if current:
                        vcur = conn.execute("SELECT COALESCE(MAX(version_number), 0) + 1 AS next_v FROM draft_versions WHERE draft_id = ?", (draft_id,))
                        next_v = vcur.fetchone()["next_v"]
                        conn.execute(
                            """INSERT INTO draft_versions(draft_id, version_number, title, body, body_html, platform, image_prompt, tags, saved_at)
                               VALUES(?,?,?,?,?,?,?,?,?)""",
                            (int(draft_id), next_v, current["title"], current["body"], current["body_html"], current["platform"], current["image_prompt"], current["tags"], stamp)
                        )
                    if tags:
                        conn.execute("UPDATE drafts SET body = ?, body_html = '', tags = ?, updated_at = ? WHERE id = ?", (body_text, tags, stamp, draft_id))
                    else:
                        conn.execute("UPDATE drafts SET body = ?, body_html = '', updated_at = ? WHERE id = ?", (body_text, stamp, draft_id))
                log_activity("draft_updated", "draft", int(draft_id), f"Updated draft body ({len(body_text)} chars)")
                self.send_json({"ok": True, "body": body_text})
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
                handle = string_field(payload, "handle") or os.environ.get("CONTENTOS_BRAND_HANDLE", "@JustMeMedia")
                slides = format_as_carousel(title, text, handle)
                self.send_json({"ok": True, "slides": slides, "count": len(slides)})
                return

            # Phase C: Local image generation via Draw Things
            if path == "/api/generate-image":
                prompt = string_field(payload, "prompt")
                if not prompt:
                    raise ApiError(400, "prompt is required")
                result = generate_image(
                    prompt,
                    negative_prompt=string_field(payload, "negative_prompt"),
                    width=int(payload.get("width", 1024)),
                    height=int(payload.get("height", 576)),
                    steps=int(payload.get("steps", 20)),
                    provider_override=string_field(payload, "provider")
                )
                self.send_json(result)
                return

            # Save an uploaded local image into the media folder
            if path == "/api/upload-image":
                data_url = string_field(payload, "data_url")
                if not data_url.startswith("data:image/"):
                    raise ApiError(400, "data_url must be an image data URL")
                header, _, b64_data = data_url.partition(",")
                mime = header[5:].split(";")[0].strip().lower()
                ext_map = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
                ext = ext_map.get(mime)
                if not ext:
                    raise ApiError(400, "Unsupported image type")
                try:
                    raw = base64.b64decode(b64_data)
                except Exception:
                    raise ApiError(400, "Invalid image data")
                if len(raw) > 15 * 1024 * 1024:
                    raise ApiError(400, "Image exceeds 15 MB limit")
                filename = f"upload_{now_iso()[:19].replace(':', '-').replace('T', '_')}.{ext}"
                (MEDIA_DIR / filename).write_bytes(raw)
                self.send_json({"ok": True, "filename": filename, "url": f"/api/media/{filename}"})
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

            # Deep Verification Endpoint — cross-check a story's claims against
            # independent web sources and return corrections. AI is optional.
            if path == "/api/verify":
                url = string_field(payload, "url")
                title = string_field(payload, "title")
                snippet = string_field(payload, "snippet")
                provider = string_field(payload, "provider") or "auto"
                source_text = extract_article_text(url) if url else ""
                if (not source_text or source_text.startswith("(")) and snippet:
                    source_text = snippet
                if not source_text:
                    source_text = title
                verification = verify_claims(provider, title, source_text, url)
                self.send_json(verification)
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
                platform = string_field(payload, "platform") or "LinkedIn"
                tone = string_field(payload, "tone") or "thought_leadership"
                provider = string_field(payload, "provider")
                if not provider or provider == "none":
                    provider = "groq:openai/gpt-oss-120b" if os.environ.get("GROQ_API_KEY") else "auto"
                if not title:
                    raise ApiError(400, "Title is required")
                
                # Agent 0: Deep Investigator
                use_deep = payload.get("deep_research", True)
                verified_block = ""
                verification_report = {}
                if use_deep and url:
                    try:
                        research = deep_research_story(url, title, snippet)
                        context = research["dossier"]
                    except Exception:
                        context = extract_article_text(url) or (snippet or title)
                    # Agent 0b: independent cross-verification. Corrected facts
                    # override the source article so its mistakes don't propagate.
                    try:
                        verification = verify_claims(provider, title, context, url)
                        if verification["ok"] and verification["verified_block"]:
                            verified_block = verification["verified_block"]
                        verification_report = {
                            "ok": verification["ok"],
                            "checked": len(verification["claims"]),
                            "corrected": verification["corrected"],
                            "facts": verification["facts"],
                            "error": verification["error"],
                            "verified_at": now_iso(),
                        }
                    except Exception as exc:
                        verification_report = {"ok": False, "error": str(exc)}
                else:
                    deep_text = extract_article_text(url) if url else ""
                    context = deep_text if deep_text and not deep_text.startswith("(") else (snippet or title)

                res = run_roundtable(provider, title, context, platform, tone=tone, source_url=url, verified_block=verified_block)
                
                media_url = ""
                if draw_things_available() or os.environ.get("OPENAI_API_KEY") or os.environ.get("STABILITY_API_KEY") or os.environ.get("REPLICATE_API_TOKEN"):
                    try:
                        img_res = generate_image(res["image_prompt"], width=1024, height=576, steps=20)
                        if img_res.get("ok") and img_res.get("filename"):
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
                with db() as conn:
                    # ── Duplicate prevention ──
                    existing = None
                    if url:
                        existing = conn.execute(
                            "SELECT id, title, body, platform, image_prompt, media_url, status, scheduled_for FROM drafts WHERE source_url = ? AND status IN ('Draft', 'Approved')",
                            (url,)
                        ).fetchone()
                    if not existing:
                        existing = conn.execute(
                            "SELECT id, title, body, platform, image_prompt, media_url, status, scheduled_for FROM drafts WHERE title = ? AND platform = ? AND status IN ('Draft', 'Approved')",
                            (title[:200], platform[:40])
                        ).fetchone()
                    if existing:
                        d = dict(existing)
                        log_activity("draft_dedup", "draft", d["id"], f"Duplicate prevented for: {d['title'][:60]}")
                        self.send_json({
                            "ok": True,
                            "id": d["id"],
                            "dedup": True,
                            "title": d["title"],
                            "body": d["body"],
                            "platform": d["platform"],
                            "image_prompt": d["image_prompt"],
                            "media_url": d["media_url"],
                            "scheduled_for": d["scheduled_for"],
                            "status": d["status"]
                        }, 200)
                        return
                    cur = conn.execute(
                        """INSERT INTO drafts(title, body, platform, status, image_prompt, source_url, media_url, scheduled_for, verification_report, created_at, updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (title[:200], res["final_post"], platform[:40], "Draft", res["image_prompt"], url, media_url, scheduled_for,
                         json.dumps(verification_report) if verification_report else "", stamp, stamp)
                    )
                    draft_id = cur.lastrowid
                self.send_json({
                    "ok": True,
                    "id": draft_id,
                    "title": title,
                    "body": res["final_post"],
                    "image_prompt": res["image_prompt"],
                    "media_url": media_url,
                    "scheduled_for": scheduled_for,
                    "verification": verification_report,
                    "platform": platform,
                    "status": "Draft"
                }, 201)
                return

            # Update draft schedule (auto_publish=1 means it will auto-publish at the scheduled time)
            if path.startswith("/api/drafts/") and path.endswith("/autopublish"):
                draft_id = int(path.split("/")[3])
                enabled = 1 if payload.get("auto_publish", True) else 0
                stamp = now_iso()
                with db() as conn:
                    conn.execute("UPDATE drafts SET auto_publish = ?, updated_at = ? WHERE id = ?",
                                 (enabled, stamp, draft_id))
                self.send_json({"ok": True, "auto_publish": enabled})
                return

            if path.startswith("/api/drafts/") and path.endswith("/update"):
                draft_id = int(path.split("/")[3])
                body_html = payload.get("body_html")
                stamp = now_iso()
                with db() as conn:
                    # Snapshot the current version (including formatting) before overwriting
                    cur = conn.execute("SELECT title, body, body_html, platform, image_prompt, tags FROM drafts WHERE id = ?", (draft_id,))
                    current = cur.fetchone()
                    if current:
                        vcur = conn.execute("SELECT COALESCE(MAX(version_number), 0) + 1 AS next_v FROM draft_versions WHERE draft_id = ?", (draft_id,))
                        next_v = vcur.fetchone()["next_v"]
                        conn.execute(
                            """INSERT INTO draft_versions(draft_id, version_number, title, body, body_html, platform, image_prompt, tags, saved_at)
                               VALUES(?,?,?,?,?,?,?,?,?)""",
                            (draft_id, next_v, current["title"], current["body"], current["body_html"], current["platform"], current["image_prompt"], current["tags"], stamp)
                        )
                    if isinstance(body_html, str):
                        conn.execute("UPDATE drafts SET title=?, body=?, body_html=?, platform=?, tags=?, image_prompt=?, media_url=?, updated_at=? WHERE id=?",
                                     (payload["title"], payload["body"], body_html, payload["platform"], payload["tags"], payload["image_prompt"], payload["media_url"], stamp, draft_id))
                    else:
                        conn.execute("UPDATE drafts SET title=?, body=?, platform=?, tags=?, image_prompt=?, media_url=?, updated_at=? WHERE id=?",
                                     (payload["title"], payload["body"], payload["platform"], payload["tags"], payload["image_prompt"], payload["media_url"], stamp, draft_id))
                self.send_json({"ok": True})
                return

            if path.startswith("/api/drafts/") and path.endswith("/schedule"):
                draft_id = path.split("/")[3]
                scheduled_for = string_field(payload, "scheduled_for")
                auto_publish = 1 if scheduled_for else 0
                stamp = now_iso()
                with db() as conn:
                    conn.execute("UPDATE drafts SET scheduled_for = ?, auto_publish = ?, updated_at = ? WHERE id = ?", (scheduled_for, auto_publish, stamp, draft_id))
                self.send_json({"ok": True, "scheduled_for": scheduled_for, "auto_publish": auto_publish})
                return

            # Studio AI assistant (chat with the drafting model)
            if path == "/api/chat":
                message = string_field(payload, "message")
                if not message:
                    raise ApiError(400, "message is required")
                provider_id = payload.get("provider", "auto")
                history = payload.get("history") or []
                if not isinstance(history, list):
                    history = []
                try:
                    result = run_chat(
                        provider_id=provider_id,
                        message=message[:4000],
                        title=string_field(payload, "title")[:300],
                        body=string_field(payload, "body")[:12000],
                        platform=string_field(payload, "platform")[:40],
                        image_prompt=string_field(payload, "image_prompt")[:2000],
                        history=history,
                    )
                    self.send_json(result)
                except Exception as exc:
                    self.send_json({"ok": False, "error": str(exc)})
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
                        # Auto-generate image if requested
                        auto_image = payload.get("auto_image", False)
                        media_url = ""
                        if auto_image and image_prompt:
                            try:
                                img_res = generate_image(image_prompt, width=1024, height=576)
                                if img_res.get("ok") and img_res.get("filename"):
                                    media_url = f"/api/media/{img_res['filename']}"
                            except Exception:
                                media_url = ""
                        self.send_json({"ok": True, "result": draft_text, "image_prompt": image_prompt, "media_url": media_url})
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
            # Dashboard stats
            if path == "/api/dashboard-stats":
                with db() as conn:
                    total = conn.execute("SELECT COUNT(*) AS c FROM drafts").fetchone()["c"]
                    active = conn.execute("SELECT COUNT(*) AS c FROM drafts WHERE status IN ('Draft', 'Approved')").fetchone()["c"]
                    published = conn.execute("SELECT COUNT(*) AS c FROM drafts WHERE status = 'Published'").fetchone()["c"]
                    scheduled = conn.execute("SELECT COUNT(*) AS c FROM drafts WHERE scheduled_for != '' AND status IN ('Draft', 'Approved')").fetchone()["c"]
                    rejected = conn.execute("SELECT COUNT(*) AS c FROM rejected_sources").fetchone()["c"]
                    # Platform breakdown
                    platform_rows = conn.execute("SELECT platform, COUNT(*) AS c FROM drafts WHERE status IN ('Draft', 'Approved') GROUP BY platform").fetchall()
                    platform_breakdown = {r["platform"]: r["c"] for r in platform_rows}
                    # Recent activity (last 7 days)
                    week_ago = (datetime.now() - __import__('datetime').timedelta(days=7)).strftime("%Y-%m-%d")
                    recent = conn.execute("SELECT COUNT(*) AS c FROM drafts WHERE created_at >= ?", (week_ago,)).fetchone()["c"]
                    # Tag breakdown
                    tag_rows = conn.execute("SELECT tags FROM drafts WHERE tags != ''").fetchall()
                    tag_counts = {}
                    for r in tag_rows:
                        for t in r["tags"].split(","):
                            t = t.strip()
                            if t:
                                tag_counts[t] = tag_counts.get(t, 0) + 1
                self.send_json({
                    "total": total,
                    "active": active,
                    "published": published,
                    "scheduled": scheduled,
                    "rejected": rejected,
                    "recent_7days": recent,
                    "platform_breakdown": platform_breakdown,
                    "tag_counts": tag_counts
                })
                return

            # Templates CRUD
            if path == "/api/templates" and self.command == "GET":
                with db() as conn:
                    rows = [dict(r) for r in conn.execute("SELECT * FROM templates ORDER BY name")]
                self.send_json(rows)
                return

            if path == "/api/templates" and self.command == "POST":
                name = string_field(payload, "name")
                if not name:
                    raise ApiError(400, "Template name is required")
                platform = string_field(payload, "platform") or "General"
                title_template = string_field(payload, "title_template")
                body_template = string_field(payload, "body_template")
                image_prompt_template = string_field(payload, "image_prompt_template")
                tags = string_field(payload, "tags")
                stamp = now_iso()
                with db() as conn:
                    cur = conn.execute(
                        """INSERT INTO templates(name, platform, title_template, body_template, image_prompt_template, tags, created_at, updated_at)
                           VALUES(?,?,?,?,?,?,?,?)""",
                        (name, platform, title_template, body_template, image_prompt_template, tags, stamp, stamp)
                    )
                    template_id = cur.lastrowid
                self.send_json({"ok": True, "id": template_id}, 201)
                return

            if path.startswith("/api/templates/") and path.endswith("/delete") and self.command == "POST":
                template_id = path.split("/")[3]
                with db() as conn:
                    conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))
                self.send_json({"ok": True})
                return

            # Bulk operations
            if path == "/api/drafts/bulk-approve" and self.command == "POST":
                ids = payload.get("ids", [])
                stamp = now_iso()
                with db() as conn:
                    for did in ids:
                        conn.execute("UPDATE drafts SET status = 'Approved', updated_at = ? WHERE id = ?", (stamp, did))
                self.send_json({"ok": True, "count": len(ids)})
                return

            if path == "/api/drafts/bulk-delete" and self.command == "POST":
                ids = payload.get("ids", [])
                with db() as conn:
                    for did in ids:
                        conn.execute("DELETE FROM drafts WHERE id = ?", (did,))
                self.send_json({"ok": True, "count": len(ids)})
                return

            if path == "/api/drafts/bulk-schedule" and self.command == "POST":
                ids = payload.get("ids", [])
                scheduled_for = string_field(payload, "scheduled_for")
                stamp = now_iso()
                auto_publish = 1 if scheduled_for else 0
                with db() as conn:
                    for did in ids:
                        conn.execute("UPDATE drafts SET scheduled_for = ?, auto_publish = ?, updated_at = ? WHERE id = ?", (scheduled_for, auto_publish, stamp, did))
                self.send_json({"ok": True, "count": len(ids), "scheduled_for": scheduled_for})
                return

            # Draft version history
            if path.startswith("/api/drafts/") and path.endswith("/versions") and self.command == "GET":
                draft_id = path.split("/")[3]
                with db() as conn:
                    rows = [dict(r) for r in conn.execute("SELECT * FROM draft_versions WHERE draft_id = ? ORDER BY version_number DESC", (draft_id,))]
                self.send_json(rows)
                return

            if path.startswith("/api/drafts/") and path.endswith("/revert") and self.command == "POST":
                draft_id = path.split("/")[3]
                version_id = payload.get("version_id")
                stamp = now_iso()
                with db() as conn:
                    vrow = conn.execute("SELECT * FROM draft_versions WHERE id = ? AND draft_id = ?", (version_id, draft_id)).fetchone()
                    if not vrow:
                        raise ApiError(404, "Version not found")
                    vrow = dict(vrow)
                    conn.execute(
                        "UPDATE drafts SET title = ?, body = ?, body_html = ?, platform = ?, image_prompt = ?, tags = ?, updated_at = ? WHERE id = ?",
                        (vrow["title"], vrow["body"], vrow.get("body_html", "") or "", vrow["platform"], vrow["image_prompt"], vrow["tags"], stamp, draft_id)
                    )
                log_activity("draft_reverted", "draft", int(draft_id), f"Reverted to version {vrow['version_number']}")
                self.send_json({"ok": True, "version": vrow["version_number"]})
                return

            # Activity log
            if path == "/api/activity-log":
                limit = int(query.get("limit", ["50"])[0])
                with db() as conn:
                    rows = [dict(r) for r in conn.execute("SELECT * FROM activity_log ORDER BY id DESC LIMIT ?", (limit,))]
                self.send_json(rows)
                return

            # Engagement metrics update
            if path.startswith("/api/drafts/") and path.endswith("/engagement") and self.command == "POST":
                draft_id = path.split("/")[3]
                views = payload.get("views", 0)
                engagements = payload.get("engagements", 0)
                stamp = now_iso()
                with db() as conn:
                    conn.execute("UPDATE drafts SET views = ?, engagements = ?, updated_at = ? WHERE id = ?", (views, engagements, stamp, draft_id))
                log_activity("engagement_updated", "draft", int(draft_id), f"Views: {views}, Engagements: {engagements}")
                self.send_json({"ok": True})
                return

            # Source provenance for a draft
            if path.startswith("/api/drafts/") and path.endswith("/provenance") and self.command == "GET":
                draft_id = path.split("/")[3]
                with db() as conn:
                    draft = conn.execute("SELECT source_url, title, created_at FROM drafts WHERE id = ?", (draft_id,)).fetchone()
                    if not draft:
                        raise ApiError(404, "Draft not found")
                    draft = dict(draft)
                    source = None
                    if draft["source_url"]:
                        src = conn.execute("SELECT * FROM sources WHERE url = ?", (draft["source_url"],)).fetchone()
                        if src:
                            source = dict(src)
                self.send_json({"draft": draft, "source": source})
                return

            if path == "/api/drafts":
                title = string_field(payload, "title")
                if not title:
                    raise ApiError(400, "Title is required and cannot be empty.")
                body = string_field(payload, "body")
                body_html = string_field(payload, "body_html")
                platform = string_field(payload, "platform") or "General"
                image_prompt = string_field(payload, "image_prompt")
                source_url = string_field(payload, "source_url")
                media_url = string_field(payload, "media_url")
                tags = string_field(payload, "tags")
                scheduled_for = string_field(payload, "scheduled_for") or calculate_next_optimal_slot()
                stamp = now_iso()
                with db() as conn:
                    # ── Duplicate prevention ──
                    # 1. If a source_url was provided, check for an existing draft from the same source
                    existing = None
                    if source_url:
                        existing = conn.execute(
                            "SELECT id, title, body, body_html, platform, image_prompt, media_url, status, scheduled_for, tags FROM drafts WHERE source_url = ? AND status IN ('Draft', 'Approved')",
                            (source_url,)
                        ).fetchone()
                    # 2. Fallback: check for same title + platform (manual Studio drafts)
                    if not existing:
                        existing = conn.execute(
                            "SELECT id, title, body, body_html, platform, image_prompt, media_url, status, scheduled_for, tags FROM drafts WHERE title = ? AND platform = ? AND status IN ('Draft', 'Approved')",
                            (title[:200], platform[:40])
                        ).fetchone()
                    if existing:
                        d = dict(existing)
                        log_activity("draft_dedup", "draft", d["id"], f"Duplicate prevented for: {d['title'][:60]}")
                        self.send_json({"ok": True, "id": d["id"], "dedup": True,
                                        "title": d["title"], "body": d["body"], "body_html": d.get("body_html", ""),
                                        "platform": d["platform"], "image_prompt": d["image_prompt"],
                                        "media_url": d["media_url"], "scheduled_for": d["scheduled_for"],
                                        "status": d["status"]})
                        return
                    cur = conn.execute(
                        """INSERT INTO drafts(title, body, body_html, platform, status, image_prompt, source_url, media_url, scheduled_for, tags, created_at, updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (title[:200], body, body_html, platform[:40], "Draft", image_prompt, source_url, media_url, scheduled_for, tags, stamp, stamp)
                    )
                    draft_id = cur.lastrowid
                    # Save initial version
                    conn.execute(
                        """INSERT INTO draft_versions(draft_id, version_number, title, body, body_html, platform, image_prompt, tags, saved_at)
                           VALUES(?,?,?,?,?,?,?,?,?)""",
                        (draft_id, 1, title[:200], body, body_html, platform[:40], image_prompt, tags, stamp)
                    )
                log_activity("draft_created", "draft", draft_id, f"Created draft: {title[:60]}")
                self.send_json({"ok": True, "id": draft_id, "scheduled_for": scheduled_for}, 201)
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

            # ── Source Watchlist CRUD ──────────────────────────────────
            if path == "/api/watchlist":
                with db() as conn:
                    rows = [dict(r) for r in conn.execute(
                        "SELECT * FROM source_watchlist ORDER BY created_at DESC")]
                self.send_json({"ok": True, "items": rows})
                return

            if path == "/api/watchlist/add":
                url = string_field(payload, "url")
                if not url:
                    raise ApiError(400, "URL is required")
                if not (url.startswith("http://") or url.startswith("https://")):
                    raise ApiError(400, "URL must start with http:// or https://")
                label = string_field(payload, "label") or url
                category = string_field(payload, "category") or "Tech"
                stamp = now_iso()
                with db() as conn:
                    try:
                        conn.execute(
                            "INSERT INTO source_watchlist(url, label, category, enabled, created_at) VALUES(?,?,?,?,?)",
                            (url, label, category, 1, stamp))
                        conn.commit()
                        cur = conn.execute("SELECT * FROM source_watchlist WHERE url = ?", (url,))
                        row = cur.fetchone()
                        self.send_json({"ok": True, "item": dict(row) if row else None}, 201)
                        return
                    except Exception as exc:
                        if "UNIQUE" in str(exc):
                            raise ApiError(409, "This feed URL is already in your watchlist")
                        raise
                return

            if path == "/api/watchlist/update":
                url = string_field(payload, "url")
                if not url:
                    raise ApiError(400, "URL is required")
                with db() as conn:
                    cur = conn.execute("SELECT 1 FROM source_watchlist WHERE url = ?", (url,))
                    if not cur.fetchone():
                        raise ApiError(404, "Watchlist entry not found")
                    fields = []
                    params = []
                    for key in ("label", "category", "enabled"):
                        if key in payload:
                            fields.append(f"{key} = ?")
                            params.append(int(payload[key]) if key == "enabled" else string_field(payload, key))
                    if not fields:
                        raise ApiError(400, "No fields to update")
                    params.append(url)
                    conn.execute(f"UPDATE source_watchlist SET {', '.join(fields)} WHERE url = ?", params)
                    conn.commit()
                    cur = conn.execute("SELECT * FROM source_watchlist WHERE url = ?", (url,))
                    row = cur.fetchone()
                self.send_json({"ok": True, "item": dict(row) if row else None})
                return

            if path == "/api/watchlist/remove":
                url = string_field(payload, "url")
                if not url:
                    raise ApiError(400, "URL is required")
                with db() as conn:
                    cur = conn.execute("DELETE FROM source_watchlist WHERE url = ?", (url,))
                    conn.commit()
                    if cur.rowcount == 0:
                        raise ApiError(404, "Watchlist entry not found")
                self.send_json({"ok": True})
                return

            if path == "/api/watchlist/check":
                """Check all enabled watchlist feeds for new stories."""
                result = _run_watchlist_check()
                self.send_json(result)
                return

            if path == "/api/watchlist/scan":
                """Scan enabled watchlist feeds and return new stories (no draft creation)."""
                url = string_field(payload, "url")
                result = _scan_watchlist_feeds(url)
                self.send_json(result)
                return

            # ── Update Check ────────────────────────────────────────────────
            if path == "/api/update":
                result = check_for_update()
                self.send_json(result)
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


# Notification toggle — set to True to re-enable notifications
NOTIFICATIONS_ENABLED = False

def main():
    connect_db().close()
    if NOTIFICATIONS_ENABLED:
        start_scheduler_daemon()
    start_daily_scrape_daemon()
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as e:
        if e.errno == 48:
            print(f"[ContentOS Error] Port {PORT} is already in use.")
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
