#!/usr/bin/env python3
"""JustMeMedia ContentOS - 24/7 Background Autopilot Worker.

Designed for headless execution on Windows (ThinkCentre) or macOS (M1 Pro).
Continuously monitors RSS feeds, deep-scrapes new stories, runs the
Multi-Agent Roundtable editorial pipeline, and queues fresh drafts into
the local SQLite database for human approval.

Usage:
    python3 app/worker.py --once
    python3 app/worker.py --daemon --interval 3600
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.server import (
    db, now_iso, fetch_rss_feed, extract_article_text,
    run_roundtable, get_available_providers
)

# Verified primary sources — checked live 2026-11-10
# Updated: 2026-11-11 — Added top tech news sites (TechCrunch, The Verge, WIRED, Ars Technica, CNET, Techmeme)
DEFAULT_FEEDS = [
    # 🍎 Apple official
    "https://developer.apple.com/news/rss/news.rss",
    "https://www.apple.com/newsroom/rss-feed.rss",
    # 🔵 Google official
    "https://blog.google/technology/ai/rss/",
    "https://blog.google/rss/",
    # 🤖 AI Labs (via TechCrunch tag feeds — most reliable)
    "https://openai.com/news/rss.xml",
    "https://techcrunch.com/tag/anthropic/feed/",
    "https://techcrunch.com/tag/deepseek/feed/",
    "https://techcrunch.com/tag/xai/feed/",
    "https://techcrunch.com/tag/meta-ai/feed/",
    "https://techcrunch.com/tag/microsoft-ai/feed/",
    # 📰 Top Tech News Sites (curated from Google search)
    "https://techcrunch.com/category/artificial-intelligence/feed/",       # Startups, VC, breaking news
    "https://techcrunch.com/feed/",                                       # TechCrunch general
    "https://www.theverge.com/rss/index.xml",                             # General tech, gadgets, culture
    "https://www.wired.com/feed/rss",                                     # Deep tech, science, cyber-culture
    "https://feeds.arstechnica.com/arstechnica/index",                    # Software, security, power users
    "https://www.cnet.com/rss/all/",                                      # Consumer advice, reviews
    "https://www.techmeme.com/feed.xml",                                  # Real-time tech news aggregator
    # 📰 Tech & AI aggregators
    "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
    "https://news.ycombinator.com/rss",
    "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
    "https://hnrss.org/frontpage",
]


def log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{stamp}] [ContentOS Worker] {msg}", flush=True)


def is_url_already_processed(url: str) -> bool:
    if not url:
        return False
    with db() as conn:
        cur = conn.execute("SELECT 1 FROM drafts WHERE source_url = ? LIMIT 1", (url,))
        if cur.fetchone():
            return True
        cur = conn.execute("SELECT 1 FROM sources WHERE url = ? LIMIT 1", (url,))
        if cur.fetchone():
            return True
    return False


def get_active_feeds() -> list[str]:
    """Return watchlist feeds (if any) plus DEFAULT_FEEDS as fallback."""
    try:
        import sqlite3
        from app.server import DB_PATH
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT url FROM source_watchlist WHERE enabled = 1 ORDER BY created_at DESC")
        rows = [r["url"] for r in cur.fetchall()]
        conn.close()
        if rows:
            return rows
    except Exception:
        pass
    return DEFAULT_FEEDS


def run_worker_cycle(provider: str | None = None, limit_per_feed: int = 1) -> int:
    """Scan feeds, find new stories, run roundtable, and queue drafts."""
    # Determine best provider if not specified
    if not provider:
        prov_info = get_available_providers()
        prov_list = prov_info.get("providers", [])
        if prov_list and prov_list[0]["id"] != "none":
            provider = prov_list[0]["id"]
        else:
            provider = "auto"

    log(f"Starting intake cycle using AI provider: {provider}")
    drafts_created = 0

    active_feeds = get_active_feeds()
    for feed_url in active_feeds:
        try:
            log(f"Checking feed: {feed_url}")
            stories = fetch_rss_feed(feed_url, limit=limit_per_feed + 2)
            for story in stories:
                url = story["url"]
                title = story["title"]
                
                if is_url_already_processed(url):
                    continue

                log(f"Discovered fresh story: '{title}'")
                deep_text = extract_article_text(url)
                context = deep_text if deep_text and not deep_text.startswith("(") else story["snippet"]

                # Run Multi-Agent Roundtable
                log(f"Conferring Roundtable Editorial Team on '{title}'...")
                res = run_roundtable(provider, title, context, platform="LinkedIn", tone="thought_leadership")
                
                stamp = now_iso()
                with db() as conn:
                    # Record source provenance
                    conn.execute(
                        """INSERT OR IGNORE INTO sources(id, url, title, publisher, retrieved_at, raw_text, summary)
                           VALUES(?,?,?,?,?,?,?)""",
                        (f"src_{stamp[:10]}_{hashlib.md5(url.encode('utf-8')).hexdigest()[:6]}", url, title, "RSS", stamp, context[:5000], story["snippet"])
                    )
                    # Insert draft for human approval
                    conn.execute(
                        """INSERT INTO drafts(title, body, platform, status, image_prompt, source_url, created_at, updated_at)
                           VALUES(?,?,?,?,?,?,?,?)""",
                        (title[:200], res["final_post"], "LinkedIn", "Draft", res["image_prompt"], url, stamp, stamp)
                    )

                drafts_created += 1
                log(f"Successfully queued draft: '{title}' (ID ready for review)")
                
                # Pace between stories
                time.sleep(2)

        except Exception as exc:
            log(f"Error processing feed {feed_url}: {exc}")

    log(f"Intake cycle finished. New drafts queued: {drafts_created}")
    return drafts_created


def main():
    # Keep Windows legacy consoles from crashing on non-cp1252 characters in
    # feed titles or log messages.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="JustMeMedia ContentOS Background Autopilot Worker")
    parser.add_argument("--daemon", action="store_true", help="Run indefinitely in background loop")
    parser.add_argument("--once", action="store_true", help="Run a single intake cycle and exit")
    parser.add_argument("--interval", type=int, default=3600, help="Interval in seconds between cycles (default: 3600)")
    parser.add_argument("--provider", type=str, default="", help="Specific AI provider ID (e.g. 'groq:...', 'ollama:...')")
    args = parser.parse_args()

    if args.once or not args.daemon:
        run_worker_cycle(provider=args.provider or None)
        return

    log(f"Daemon mode started. Polling every {args.interval} seconds. Press Ctrl+C to stop.")
    while True:
        try:
            run_worker_cycle(provider=args.provider or None)
        except Exception as exc:
            log(f"Unhandled error in cycle: {exc}")
        
        log(f"Sleeping for {args.interval}s until next cycle...")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()

