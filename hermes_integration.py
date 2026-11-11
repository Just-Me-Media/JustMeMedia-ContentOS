#!/usr/bin/env python3
"""
Hermes Integration Script for ContentOS

This script reads approved posts from ContentOS's SQLite database and posts them
to X (Twitter) using the X API. It's designed to work with the ContentOS content
generation pipeline.

Architecture:
- ContentOS generates content (research, draft, format)
- ContentOS stores to SQLite with status 'Approved' or 'Pending'
- Hermes reads from ContentOS DB via sqlite3 (standard library)
- Hermes posts to X API
- ContentOS records the publishing status

Usage:
    python3 hermes_integration.py --post-count 5
    python3 hermes_integration.py --dry-run
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Try to load environment variables from ~/.secure_keys/.env
# (This is where ContentOS loads its keys from)
SECURE_KEYS_DIR = os.path.expanduser("~/.secure_keys")
SECURE_KEYS_FILE = os.path.join(SECURE_KEYS_DIR, ".env")

def load_secure_keys():
    """Load API keys from the secure keys file."""
    env = {}
    if os.path.exists(SECURE_KEYS_FILE):
        with open(SECURE_KEYS_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, val = line.partition('=')
                key = key.strip().replace('export ', '')
                val = val.strip().strip('"\'')
                env[key] = val
    return env

def get_contentos_db():
    """Get the ContentOS SQLite database connection."""
    # Use the same database path as ContentOS
    from app.server import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_pending_posts(platform='x'):
    """Fetch approved posts ready for Hermes to publish."""
    from app.server import db
    with db() as conn:
        cur = conn.execute("""
            SELECT d.id AS draft_id, d.title, d.body, d.platform AS draft_platform,
                   p.platform AS target_platform, p.id AS platform_id,
                   p.post_id, p.published_at
            FROM drafts d
            JOIN platforms p ON p.draft_id = d.id
            WHERE d.status IN ('Approved', 'Pending')
              AND p.status = 'approved'
              AND p.post_id = ''
            ORDER BY d.id
        """)
        rows = cur.fetchall()
        return [dict(r) for r in rows]

def record_post_status(draft_id, platform, post_id, published_at=None):
    """Record the publishing status of a post in the platforms table."""
    from app.server import record_post_status as update_record
    return update_record(draft_id, platform, post_id, published_at)

def post_to_x(tweet_text, api_key, bearer_token, username):
    """
    Post a tweet to X using the X API (v2).
    This is a placeholder - you'll need actual X API credentials.
    """
    import requests
    import time

    # X API v2 endpoint for posting tweets
    url = "https://api.x.com/2/tweets"

    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "text": tweet_text
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        print(f"  ✅ Posted: {tweet_text[:40]}...")
        return result.get("data", {}).get("id", "unknown")
    except requests.exceptions.RequestException as e:
        print(f"  ❌ Failed to post: {e}")
        return None

def post_thread_to_x(thread_tweets, api_key, bearer_token, username):
    """
    Post a thread to X (Twitter).
    Posts each tweet in the thread, waiting between posts.
    """
    if not thread_tweets:
        print("  ⚠️  No tweets to post")
        return

    print(f"\n📱 Posting thread to X (fanout)...")

    post_ids = []
    for i, tweet in enumerate(thread_tweets, 1):
        print(f"  Posting tweet {i}/{len(thread_tweets)}...")
        post_id = post_to_x(tweet, api_key, bearer_token, username)
        if post_id:
            post_ids.append(post_id)

        # Rate limit: 3 seconds between tweets (X recommends this)
        time.sleep(3)

    return post_ids

def main():
    parser = argparse.ArgumentParser(description="Hermes ContentOS Integration - Post to X")
    parser.add_argument("--post-count", type=int, default=5, help="Number of pending posts to process")
    parser.add_argument("--dry-run", action="store_true", help="Simulate posting without actually posting")
    parser.add_argument("--platform", type=str, default="x", help="Platform to post to (default: x)")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")

    args = parser.parse_args()

    # Load secure keys
    keys = load_secure_keys()
    x_bearer_token = keys.get("X_BEARER_TOKEN")
    x_api_key = keys.get("X_API_KEY")

    if not x_bearer_token:
        print("⚠️  X_BEARER_TOKEN not found in ~/.secure_keys/.env")
        print("    Create ~/.secure_keys/.env with:")
        print("    X_BEARER_TOKEN=your_bearer_token")
        sys.exit(1)

    # Connect to ContentOS DB
    conn = get_contentos_db()
    conn.row_factory = sqlite3.Row

    print(f"\n📋 ContentOS Hermes Integration")
    print(f"   Platform: {args.platform}")
    print(f"   Dry run: {args.dry_run}")
    print(f"   Scanning for pending posts...\n")

    # Get pending posts
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
        LIMIT ?
    """
    cur = conn.execute(query, (args.post_count,))
    rows = cur.fetchall()
    posts = [dict(r) for r in rows]

    if not posts:
        print("✅ No pending posts found. All clear!")
        conn.close()
        return

    print(f"📥 Found {len(posts)} pending post(s)\n")

    # Post each one
    for i, post in enumerate(posts, 1):
        print(f"\n{'='*60}")
        print(f"  Post #{i}: {post['title'][:50]}...")
        print(f"  Draft ID: {post['draft_id']}")

        # Format the body into tweets (if it's a thread)
        body = post['body']
        if '\n' in body:
            # Split into multiple tweets
            tweets = [t.strip() for t in body.split('\n') if t.strip()]
            print(f"  📊 Format: {len(tweets)} tweets")
        else:
            tweets = [body]
            print(f"  📊 Format: single post")

        if not args.dry_run:
            print(f"  📦 Posting to X...")
            post_ids = post_thread_to_x(tweets, x_bearer_token, x_bearer_token, username=None)

            # Record status
            for j, tweet in enumerate(tweets):
                record_post_status(
                    draft_id=post['draft_id'],
                    platform=post['target_platform'],
                    post_id=post_ids[j] if j < len(post_ids) else f"tweet_{i}_{j}"
                )
        else:
            print(f"  🔬 DRY RUN - Would post {len(tweets)} tweet(s) to X")
            print(f"  📋 Would update status in ContentOS for {len(tweets)} post(s)")

    conn.close()
    print(f"\n{'='*60}")
    print(f"✅ Processing complete")

if __name__ == "__main__":
    main()
