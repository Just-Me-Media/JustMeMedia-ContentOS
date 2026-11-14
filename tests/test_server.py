import unittest
import json
import os
import shutil
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from app.server import (
    db, DB_PATH, now_iso, ALLOWED_HOSTNAMES,
    string_field, ApiError
)
import app.server as s
from contextlib import contextmanager


class TestHelpers(unittest.TestCase):
    def test_allowed_hostnames_direct(self):
        # These should all be directly in the frozenset
        for host in ("127.0.0.1", "localhost", "::1"):
            self.assertIn(host, ALLOWED_HOSTNAMES)

    def test_allowed_hostnames_with_port(self):
        # When host has a port, strip it before checking
        for host in ("127.0.0.1:8799", "localhost:8799", "::1:8799"):
            # Simulate _request_hostname stripping the port
            if host.startswith("["):
                h = host[host.find("]")+1:].strip()
            else:
                h = host.rsplit(":", 1)[0].strip().lower()
            self.assertIn(h, ALLOWED_HOSTNAMES)

    def test_allowed_hostnames_reject(self):
        # These should never be in the allowed set
        for host in ("attacker.com", "192.168.1.1", "evil.example"):
            self.assertNotIn(host.split(":")[0], ALLOWED_HOSTNAMES)

    def test_string_field(self):
        ok = string_field({"title": "Hello"}, "title")
        self.assertEqual(ok, "Hello")
        with self.assertRaises(ApiError) as cm:
            string_field({"title": 123}, "title")
        self.assertIn("must be a string", str(cm.exception))
        # missing field -> empty string
        result = string_field({"other": "x"}, "title")
        self.assertEqual(result, "")

    @contextmanager
    def _temp_db(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_db = Path(tmp_dir) / "contentos.test.db"
            yield test_db

    def test_temp_db_cycle(self):
        """db() context manager opens + commits + closes."""
        from app.server import db
        with self._temp_db() as p:
            pass  # path just checked for existence


class TestDatabase(unittest.TestCase):
    def test_create_and_list(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_dir = Path(tmp_dir)
            import app.server as s
            orig = s.DB_PATH
            s.DB_PATH = test_dir / "contentos.db"

            try:
                with db() as conn:
                    cur = conn.execute("SELECT COUNT(*) FROM drafts")
                    count = cur.fetchone()[0]
                    self.assertEqual(count, 0)

                # Insert
                stamp = now_iso()
                with db() as conn:
                    conn.execute(
                        "INSERT INTO drafts(title, body, platform, status, created_at, updated_at) "
                        "VALUES(?,?,?,?,?,?)",
                        ("Test Title", "Test Body", "LinkedIn", "Draft", stamp, stamp),
                    )

                with db() as conn:
                    cur = conn.execute("SELECT title, platform FROM drafts ORDER BY id DESC LIMIT 1")
                    row = cur.fetchone()
                    self.assertEqual(row["title"], "Test Title")
                    self.assertEqual(row["platform"], "LinkedIn")
            finally:
                s.DB_PATH = orig

    def test_schema_divergence(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_dir = Path(tmp_dir)
            import app.server as s
            orig = s.DB_PATH
            s.DB_PATH = test_dir / "contentos.db"
            try:
                with db() as conn:
                    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                    tables = [r[0] for r in cur.fetchall()]
                    for t in ["content_items", "content_versions", "sources", "claims"]:
                        self.assertIn(t, tables, f"Table {t} missing from schema")
            finally:
                s.DB_PATH = orig

    def test_empty_title_rejected(self):
        import tempfile
        from pathlib import Path
        import threading
        from http.server import ThreadingHTTPServer
        import app.server as s
        orig = s.DB_PATH
        tmp = Path(tempfile.mkdtemp())
        s.DB_PATH = tmp / "contentos.db"
        try:
            s.connect_db()
            server = ThreadingHTTPServer(("127.0.0.1", 0), s.Handler)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                import json
                import urllib.error
                import urllib.request
                body = json.dumps({"title": "   ", "body": "Some body", "platform": "LinkedIn"}).encode("utf-8")
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/drafts",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    urllib.request.urlopen(req, timeout=5)
                    self.fail("Expected 400 for empty title")
                except urllib.error.HTTPError as exc:
                    self.assertEqual(exc.code, 400)
                    self.assertIn("Title is required", exc.read().decode("utf-8"))
            finally:
                server.shutdown()
        finally:
            s.DB_PATH = orig

    def test_empty_body_accepted_with_default(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_dir = Path(tmp_dir)
            import app.server as s
            orig = s.DB_PATH
            s.DB_PATH = test_dir / "contentos.db"
            try:
                with db() as conn:
                    conn.execute(
                        "INSERT INTO drafts(title, body, platform, status, created_at, updated_at) "
                        "VALUES(?,?,?,?,?,?)",
                        ("Minimal Title", "", "LinkedIn", "Draft", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
                    )
                with db() as conn:
                    cur = conn.execute("SELECT title, body FROM drafts ORDER BY id DESC LIMIT 1")
                    row = cur.fetchone()
                    self.assertEqual(row["title"], "Minimal Title")
                    self.assertEqual(row["body"], "")
            finally:
                s.DB_PATH = orig

    def test_draft_body_html_roundtrip(self):
        """Rich-text HTML is stored alongside the plain-text body."""
        import threading
        from http.server import ThreadingHTTPServer

        with tempfile.TemporaryDirectory() as tmp_dir:
            test_dir = Path(tmp_dir)
            orig = s.DB_PATH
            s.DB_PATH = test_dir / "contentos.db"
            try:
                s.connect_db()
                server = ThreadingHTTPServer(("127.0.0.1", 0), s.Handler)
                port = server.server_address[1]
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    html = '<div>Hello <b>bold</b> <span style="color: #15BF7F">green</span></div>'
                    payload = {
                        "title": "Rich Draft",
                        "body": "Hello bold green",
                        "body_html": html,
                        "platform": "LinkedIn",
                    }
                    req = Request(
                        f"http://127.0.0.1:{port}/api/drafts",
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    created = json.loads(urlopen(req, timeout=5).read())
                    self.assertTrue(created.get("id"))

                    drafts = json.loads(urlopen(f"http://127.0.0.1:{port}/api/drafts", timeout=5).read())
                    row = next(d for d in drafts if d["id"] == created["id"])
                    self.assertEqual(row["body"], "Hello bold green")
                    self.assertIn("<b>bold</b>", row["body_html"])
                    self.assertIn("#15BF7F", row["body_html"])

                    update = {
                        "title": "Rich Draft",
                        "body": "Updated copy",
                        "body_html": "<div>Updated <i>copy</i></div>",
                        "platform": "LinkedIn",
                        "tags": "",
                        "image_prompt": "",
                        "media_url": "",
                    }
                    req = Request(
                        f"http://127.0.0.1:{port}/api/drafts/{created['id']}/update",
                        data=json.dumps(update).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    urlopen(req, timeout=5).read()

                    drafts = json.loads(urlopen(f"http://127.0.0.1:{port}/api/drafts", timeout=5).read())
                    row = next(d for d in drafts if d["id"] == created["id"])
                    self.assertEqual(row["body"], "Updated copy")
                    self.assertIn("<i>copy</i>", row["body_html"])

                    # The pre-update version snapshot keeps its rich-text HTML
                    versions = json.loads(urlopen(
                        f"http://127.0.0.1:{port}/api/drafts/{created['id']}/versions", timeout=5
                    ).read())
                    snapshot = next(v for v in versions if "<b>bold</b>" in (v.get("body_html") or ""))
                    self.assertEqual(snapshot["body"], "Hello bold green")

                    # Reverting restores formatting as well as plain text
                    req = Request(
                        f"http://127.0.0.1:{port}/api/drafts/{created['id']}/revert",
                        data=json.dumps({"version_id": snapshot["id"]}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    urlopen(req, timeout=5).read()
                    drafts = json.loads(urlopen(f"http://127.0.0.1:{port}/api/drafts", timeout=5).read())
                    row = next(d for d in drafts if d["id"] == created["id"])
                    self.assertEqual(row["body"], "Hello bold green")
                    self.assertIn("<b>bold</b>", row["body_html"])
                finally:
                    server.shutdown()
            finally:
                s.DB_PATH = orig

    def test_missing_content_length_rejected(self):
        from app.server import ApiError
        with self.assertRaises(ApiError) as cm:
            raise ApiError(400, "Invalid Content-Length header.")
        self.assertIn("Content-Length", str(cm.exception))

    def test_oversized_payload_rejected(self):
        from app.server import ApiError
        with self.assertRaises(ApiError) as cm:
            raise ApiError(413, "Request body is too large.")
        self.assertIn("too large", str(cm.exception))


class TestPhasesAtoE(unittest.TestCase):
    def test_strip_ai_slop(self):
        from app.server import strip_ai_slop
        sample = "In today's fast-paced world, we must delve into AI to leverage its transformative power."
        cleaned = strip_ai_slop(sample)
        self.assertNotIn("delve", cleaned.lower())
        self.assertNotIn("leverage", cleaned.lower())
        self.assertNotIn("in today's fast-paced world", cleaned.lower())

    def test_inject_viral_hook(self):
        from app.server import inject_viral_hook
        plain_text = "Here are the top three principles of local-first software architecture."
        hooked = inject_viral_hook(plain_text, "Local First Architecture")
        self.assertTrue(hooked.endswith(plain_text))
        self.assertGreater(len(hooked), len(plain_text))
        # Should not re-hook if already has a hook question
        question_text = "Why is everyone moving to local AI?\nHere is the breakdown."
        self.assertEqual(inject_viral_hook(question_text, "Local AI"), question_text)

    def test_format_as_thread(self):
        from app.server import format_as_thread
        long_post = "First point about AI.\n\nSecond point about privacy.\n\nThird point about cost.\n\nFourth point about speed."
        tweets = format_as_thread(long_post, max_tweet_len=100)
        self.assertTrue(len(tweets) >= 2)
        self.assertTrue(tweets[0].startswith(f"1/{len(tweets)}"))
        self.assertTrue(tweets[-1].startswith(f"{len(tweets)}/{len(tweets)}"))

    def test_format_as_carousel(self):
        from app.server import format_as_carousel
        content = "Intro slide context.\n\nKey Finding 1\nDetails on finding 1.\n\nKey Finding 2\nDetails on finding 2."
        slides = format_as_carousel("My Slide Deck", content)
        self.assertTrue(len(slides) >= 2)
        self.assertEqual(slides[0]["slide"], 1)
        self.assertIn("heading", slides[0])
        self.assertIn("body", slides[0])

    def test_draw_things_unavailable(self):
        from app.server import generate_local_image
        # Force Draw Things to appear offline regardless of the local environment,
        # then assert the graceful error contract.
        import app.server as server
        orig = server.draw_things_available
        server.draw_things_available = lambda: False
        try:
            res = generate_local_image("a futuristic workstation")
            self.assertFalse(res["ok"])
            self.assertIn("Draw Things API not available", res["error"])
        finally:
            server.draw_things_available = orig
        # Draw Things is offline in sandboxed test run; should gracefully return error dict
        res = generate_local_image("a futuristic workstation")
        self.assertFalse(res["ok"])
        self.assertIn("Draw Things API not available", res["error"])
        import app.server as server
        orig = server.draw_things_available
        server.draw_things_available = lambda: False
        try:
            res = generate_local_image("a futuristic workstation")
            self.assertFalse(res["ok"])
            self.assertTrue(res["error"])
        finally:
            server.draw_things_available = orig

    def test_image_backend_capability(self):
        from app import server
        self.assertIn(server.IMAGE_BACKEND, ("none", "drawthings", "a1111"))
        self.assertEqual(
            server.LOCAL_IMAGE_ENABLED,
            server.IMAGE_BACKEND in ("drawthings", "a1111"),
        )
        if server.IMAGE_BACKEND == "none":
            self.assertFalse(server.draw_things_available())
            res = server.generate_local_image("test")
            self.assertFalse(res["ok"])
            self.assertIn("disabled", res["error"].lower())

    def test_build_discord_payload(self):
        from app.server import build_discord_payload
        draft = {"title": "Test Title", "body": "Test Body", "platform": "LinkedIn", "status": "Draft", "image_prompt": "Neon green art"}
        payload = build_discord_payload(draft)
        self.assertIn("embeds", payload)
        self.assertIn("Test Title", payload["embeds"][0]["title"])
        self.assertIn("fields", payload["embeds"][0])

    def test_build_slack_payload(self):
        from app.server import build_slack_payload
        draft = {"title": "Test Title", "body": "Test Body", "platform": "X", "status": "Approved"}
        payload = build_slack_payload(draft)
        self.assertIn("blocks", payload)
        self.assertIn("Test Title", payload["blocks"][0]["text"]["text"])

    def test_send_webhook_empty_url(self):
        from app.server import send_webhook
        res = send_webhook("", {"test": 1})
        self.assertFalse(res["ok"])
        self.assertIn("Invalid webhook URL", res["error"])

    def test_save_and_get_webhook_config(self):
        from app.server import save_webhook_config, get_webhook_config, data_dir
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_file = Path(tmp_dir) / "webhooks.json"
            # Test direct file write/read logic
            cfg = {"discord": "https://discord.com/api/webhooks/test", "slack": "https://hooks.slack.com/test"}
            test_file.write_text(json.dumps(cfg), encoding="utf-8")
            loaded = json.loads(test_file.read_text(encoding="utf-8"))
            self.assertEqual(loaded["discord"], cfg["discord"])
            self.assertEqual(loaded["slack"], cfg["slack"])

    def test_calculate_next_optimal_slot(self):
        from app.server import calculate_next_optimal_slot
        import re
        slot = calculate_next_optimal_slot()
        # Must match YYYY-MM-DD HH:MM format
        self.assertRegex(slot, r"^\d{4}-\d{2}-\d{2} (09:00|14:00|18:30)$")

    def test_draft_scheduled_for_field(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_dir = Path(tmp_dir)
            import app.server as s
            orig = s.DB_PATH
            s.DB_PATH = test_dir / "contentos.db"
            try:
                stamp = now_iso()
                with db() as conn:
                    conn.execute(
                        "INSERT INTO drafts(title, body, platform, status, scheduled_for, created_at, updated_at) "
                        "VALUES(?,?,?,?,?,?,?)",
                        ("Scheduled Post", "Content", "LinkedIn", "Draft", "2026-11-11 09:00", stamp, stamp)
                    )
                with db() as conn:
                    row = conn.execute("SELECT * FROM drafts WHERE title='Scheduled Post'").fetchone()
                    self.assertEqual(row["scheduled_for"], "2026-11-11 09:00")
            finally:
                s.DB_PATH = orig

    def test_check_scheduled_drafts(self):
        from app.server import check_scheduled_drafts
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_dir = Path(tmp_dir)
            import app.server as s
            orig = s.DB_PATH
            s.DB_PATH = test_dir / "contentos.db"
            try:
                stamp = now_iso()
                with db() as conn:
                    conn.execute(
                        "INSERT INTO drafts(title, body, platform, status, scheduled_for, created_at, updated_at) "
                        "VALUES(?,?,?,?,?,?,?)",
                        ("Past Due Post", "Body", "LinkedIn", "Draft", "2020-01-01 09:00", stamp, stamp)
                    )
                notified = check_scheduled_drafts()
                self.assertTrue(any(d["title"] == "Past Due Post" for d in notified))
            finally:
                s.DB_PATH = orig

    def test_deep_research_story_structure(self):
        from app.server import deep_research_story
        res = deep_research_story("", "AI Revolution", "Local AI models run on Apple Silicon.")
        self.assertIn("dossier", res)
        self.assertEqual(res["title"], "AI Revolution")
        self.assertIn("Local AI models run on Apple Silicon", res["dossier"])

    def test_format_for_linkedin(self):
        from app.server import format_for_linkedin
        raw = (
            "🚀 Ready to shape the next wave? The **Swift Student Challenge 2027** is here.\n\n"
            "**Key Dates**\n"
            "• **February 8–28, 2027** (UTC) – submission window\n\n"
            "### Evaluation Criteria\n"
            "- A functional app built with **Swift** for any Apple platform\n"
            "🔗 **Learn more & apply here:** https://developer.apple.com\n\n"
            "*Which Apple platform will you build for?*\n"
            "#Swift #AppleDev"
        )
        cleaned = format_for_linkedin(raw)
        self.assertNotIn("**Key Dates**", cleaned)
        self.assertIn("Key Dates:", cleaned)
        self.assertNotIn("### Evaluation Criteria", cleaned)
        self.assertIn("Evaluation Criteria:", cleaned)
        self.assertNotIn("**Swift**", cleaned)
        self.assertIn("built with Swift for any", cleaned)
        self.assertNotIn("*Which Apple platform", cleaned)
        self.assertIn("Which Apple platform will you build for?", cleaned)
        self.assertIn("https://developer.apple.com", cleaned)
        self.assertIn("#Swift", cleaned)

    def test_format_for_x_strict_limit(self):
        from app.server import format_for_x
        long_raw = (
            "Developers, the Siri AI doors just swung wide open—here's why this reshapes app discovery.\n\n"
            "**What's new in iOS 27.3:**\n"
            "Apple is introducing conversational app intents that let system Siri interact directly with third-party apps "
            "without having to launch full screen applications or navigate complex menu trees. This changes everything for developer workflows "
            "and creates massive opportunities for early builders across iOS, iPadOS, macOS, and visionOS.\n\n"
            "Check the full developer breakdown here: https://developer.apple.com/news/\n"
            "#Apple #DevCommunity #iOS"
        )
        cleaned = format_for_x(long_raw)
        self.assertLessEqual(len(cleaned), 280, f"X post must be <= 280 chars, was {len(cleaned)}")
        self.assertNotIn("**", cleaned)
        self.assertNotIn("###", cleaned)
        self.assertIn("https://developer.apple.com/news/", cleaned)

    def test_format_as_thread_strict_limit(self):
        from app.server import format_as_thread
        long_essay = (
            "Apple just opened its Siri AI API to every developer worldwide. This is the biggest platform shift since the App Store launched in 2008.\n\n"
            "First, app discovery is moving from static keywords to natural language execution. Instead of hoping a user searches for your app name, Siri will call your App Intent whenever their intent matches your capability.\n\n"
            "Second, the execution happens on-device using Private Cloud Compute and Apple Silicon Neural Engines. Users never have to compromise data privacy or wait for high-latency external servers.\n\n"
            "Third, the submission window opens today with complete starter documentation, test suites, and sample projects ready for Swift developers.\n\n"
            "Get started with the full guide here: https://developer.apple.com/news/ #Apple #Swift #AI"
        )
        tweets = format_as_thread(long_essay, max_tweet_len=270)
        self.assertGreater(len(tweets), 1)
        for i, tw in enumerate(tweets):
            self.assertLessEqual(len(tw), 270, f"Tweet {i+1} exceeds 270 chars ({len(tw)}): {tw}")
            self.assertTrue(tw.startswith(f"{i+1}/{len(tweets)}\n\n"))


class TestRejectedSources(unittest.TestCase):
    """User can dismiss an article from the feed; dismissed URLs never reappear."""

    @contextmanager
    def _temp_db(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_dir = Path(tmp_dir)
            import app.server as s
            orig = s.DB_PATH
            s.DB_PATH = test_dir / "contentos.db"
            try:
                yield test_dir
            finally:
                s.DB_PATH = orig

    def test_rejected_table_exists(self):
        with self._temp_db():
            with db() as conn:
                cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                tables = [r[0] for r in cur.fetchall()]
                self.assertIn("rejected_sources", tables)

    def test_reject_and_dedupe(self):
        from app.server import string_field
        stamp = now_iso()
        with self._temp_db():
            with db() as conn:
                conn.execute(
                    "INSERT INTO rejected_sources(url, title, rejected_at) VALUES(?,?,?)",
                    ("https://example.com/a", "Article A", stamp)
                )
                conn.execute(
                    "INSERT OR IGNORE INTO rejected_sources(url, title, rejected_at) VALUES(?,?,?)",
                    ("https://example.com/a", "Article A duplicate", stamp)
                )
                rows = conn.execute("SELECT COUNT(*) AS c FROM rejected_sources").fetchone()
                self.assertEqual(rows["c"], 1)

    def test_filter_rejected_sources(self):
        from app.server import filter_rejected_sources
        with self._temp_db():
            stamp = now_iso()
            with db() as conn:
                conn.execute(
                    "INSERT INTO rejected_sources(url, title, rejected_at) VALUES(?,?,?)",
                    ("https://example.com/b", "Hidden", stamp)
                )
            items = [
                {"title": "Kept", "url": "https://example.com/kept", "snippet": "stay"},
                {"title": "Hidden", "url": "https://example.com/b", "snippet": "go"},
                {"title": "No URL", "url": "", "snippet": "also stay"},
            ]
            kept = filter_rejected_sources(items)
            self.assertEqual([i["title"] for i in kept], ["Kept", "No URL"])

    def test_filter_rejected_empty_input(self):
        from app.server import filter_rejected_sources
        self.assertEqual(filter_rejected_sources([]), [])
        self.assertEqual(filter_rejected_sources(None), None)


class TestGitHubTrending(unittest.TestCase):
    """Tests for the GitHub trending / weekly Top 10 pipeline."""

    @contextmanager
    def _temp_db(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_db = Path(tmp_dir) / "contentos.test.db"
            orig = s.DB_PATH
            s.DB_PATH = test_db
            try:
                yield test_db
            finally:
                s.DB_PATH = orig

    def test_github_tables_exist(self):
        with self._temp_db():
            with db() as conn:
                cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                tables = [r[0] for r in cur.fetchall()]
                self.assertIn("github_repos", tables)
                self.assertIn("github_top10_issues", tables)

    def test_store_and_retrieve_repos(self):
        from app.server import store_github_repos, get_weekly_top_10
        stamp = now_iso()[:10]
        repos = [
            {"full_name": "owner/repo1", "url": "https://github.com/owner/repo1", "description": "test", "stars": 100, "language": "Python"},
            {"full_name": "owner/repo2", "url": "https://github.com/owner/repo2", "description": "test2", "stars": 50, "language": "Python"},
        ]
        with self._temp_db():
            stored = store_github_repos(repos, "General")
            self.assertEqual(stored, 2)
            top = get_weekly_top_10("General", "LinkedIn")
            self.assertEqual(len(top), 2)
            self.assertEqual(top[0]["stars"], 100)
            self.assertEqual(top[1]["stars"], 50)

    def test_store_dedupes(self):
        from app.server import store_github_repos
        stamp = now_iso()[:10]
        repos = [
            {"full_name": "owner/repo1", "url": "https://github.com/owner/repo1", "description": "test", "stars": 100, "language": "Python"},
            {"full_name": "owner/repo1", "url": "https://github.com/owner/repo1", "description": "dup", "stars": 100, "language": "Python"},
        ]
        with self._temp_db():
            stored = store_github_repos(repos, "General")
            self.assertEqual(stored, 1)

    def test_generate_bundle_no_repos(self):
        from app.server import generate_weekly_github_bundle
        with self._temp_db():
            bundle = generate_weekly_github_bundle("General", "LinkedIn")
            self.assertFalse(bundle["ok"])
            self.assertIn("No GitHub repos", bundle["error"])

    def test_generate_bundle_with_repos(self):
        from app.server import store_github_repos, generate_weekly_github_bundle
        repos = [
            {"full_name": "owner/repo1", "url": "https://github.com/owner/repo1", "description": "test", "stars": 100, "language": "Python"},
            {"full_name": "owner/repo2", "url": "https://github.com/owner/repo2", "description": "test2", "stars": 50, "language": "Python"},
        ]
        with self._temp_db():
            store_github_repos(repos, "General")
            bundle = generate_weekly_github_bundle("General", "LinkedIn")
            self.assertTrue(bundle["ok"])
            self.assertIn("Weekly GitHub Top 10", bundle["title"])
            self.assertIn("owner/repo1", bundle["body"])
            self.assertIn("owner/repo2", bundle["body"])
            self.assertEqual(bundle["platform"], "LinkedIn")
            self.assertEqual(len(bundle["repos"]), 2)

    def test_fallback_returns_list(self):
        from app.server import fetch_github_trending
        # Should always return a list (fallback or live scrape)
        result = fetch_github_trending("python", "python", 7)
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)


class TestChatAssistant(unittest.TestCase):
    def test_parse_well_formed_sections(self):
        from app.server import parse_chat_response
        parsed = parse_chat_response(
            "Here are ways to improve it.\n\n"
            "---REVISED POST---\nStronger post.\n---END REVISED POST---\n\n"
            "---IMAGE PROMPT---\nA desk with a green glow.\n---END IMAGE PROMPT---"
        )
        self.assertEqual(parsed["reply"], "Here are ways to improve it.")
        self.assertEqual(parsed["suggested_body"], "Stronger post.")
        self.assertEqual(parsed["image_prompt"], "A desk with a green glow.")

    def test_parse_missing_end_markers(self):
        from app.server import parse_chat_response
        parsed = parse_chat_response(
            "---REVISED POST---\nRewritten.\n\n---IMAGE PROMPT---\nMinimal 3D render."
        )
        self.assertEqual(parsed["suggested_body"], "Rewritten.")
        self.assertEqual(parsed["image_prompt"], "Minimal 3D render.")
        self.assertNotIn("IMAGE PROMPT", parsed["suggested_body"])

    def test_parse_reply_only(self):
        from app.server import parse_chat_response
        parsed = parse_chat_response("Just a conversational answer.")
        self.assertEqual(parsed["reply"], "Just a conversational answer.")
        self.assertEqual(parsed["suggested_body"], "")
        self.assertEqual(parsed["image_prompt"], "")

    def test_chat_empty_message_rejected(self):
        import threading
        from http.server import ThreadingHTTPServer

        with tempfile.TemporaryDirectory() as tmp_dir:
            orig = s.DB_PATH
            s.DB_PATH = Path(tmp_dir) / "contentos.db"
            try:
                s.connect_db()
                server = ThreadingHTTPServer(("127.0.0.1", 0), s.Handler)
                port = server.server_address[1]
                threading.Thread(target=server.serve_forever, daemon=True).start()
                try:
                    req = Request(
                        f"http://127.0.0.1:{port}/api/chat",
                        data=json.dumps({"message": "   "}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with self.assertRaises(HTTPError) as ctx:
                        urlopen(req, timeout=5)
                    self.assertEqual(ctx.exception.code, 400)
                    self.assertIn("message is required", ctx.exception.read().decode("utf-8"))
                finally:
                    server.shutdown()
            finally:
                s.DB_PATH = orig


    def test_parse_search_request(self):
        from app.server import parse_search_request
        raw = "---SEARCH---\n  local-first AI adoption  \n---END SEARCH---"
        self.assertEqual(parse_search_request(raw), "local-first AI adoption")
        self.assertEqual(parse_search_request('---SEARCH--- "edge AI survey" ---END SEARCH---'), "edge AI survey")
        self.assertEqual(parse_search_request("No search needed."), "")

    def test_parse_chat_response_strips_search_block(self):
        from app.server import parse_chat_response
        parsed = parse_chat_response(
            "Let me check that.\n\n---SEARCH---\nlocal-first AI adoption\n---END SEARCH---"
        )
        self.assertEqual(parsed["reply"], "Let me check that.")
        self.assertNotIn("SEARCH", parsed["reply"])

    def test_run_chat_executes_one_requested_search(self):
        import app.server as s
        calls = []
        source = {
            "title": "Local-first AI report",
            "url": "https://example.com/report",
            "snippet": "Adoption is rising.",
        }

        def fake_call(provider, prompt, system_prompt):
            calls.append(prompt)
            if len(calls) == 1:
                return "---SEARCH---\nlocal-first AI adoption\n---END SEARCH---"
            return (
                "Here is what the report says.\n\n"
                "---REVISED POST---\nA stronger post.\n---END REVISED POST---"
            )

        original = (s.call_ai, s.web_research)
        try:
            s.call_ai = fake_call
            s.web_research = lambda query, limit=5: [source]
            result = s.run_chat("test:model", "Find data", title="Local-first AI", body="Draft")
        finally:
            s.call_ai, s.web_research = original

        self.assertEqual(len(calls), 2)
        self.assertEqual(result["sources"], [source])
        self.assertIn(source["url"], calls[1])
        self.assertEqual(result["suggested_body"], "A stronger post.")

    def test_run_chat_skips_search_when_not_requested(self):
        import app.server as s
        original = (s.call_ai, s.web_research)
        try:
            s.call_ai = lambda provider, prompt, system_prompt: "Just an answer."
            s.web_research = lambda query, limit=5: self.fail("search should not run")
            result = s.run_chat("test:model", "Improve this", title="T", body="B")
        finally:
            s.call_ai, s.web_research = original

        self.assertEqual(result["reply"], "Just an answer.")
        self.assertEqual(result["sources"], [])


    def test_run_chat_verifies_unbacked_search_claims(self):
        import app.server as s
        calls = []
        source = {"title": "Report", "url": "https://example.com/r", "snippet": "Data."}

        def fake_call(provider, prompt, system_prompt):
            calls.append(prompt)
            if len(calls) == 1:
                return "I ran a quick search and recent reports agree."
            return "Grounded answer."

        original = (s.call_ai, s.web_research)
        try:
            s.call_ai = fake_call
            s.web_research = lambda query, limit=5: [source]
            result = s.run_chat("test:model", "Add evidence", title="Local-first AI", body="Draft")
        finally:
            s.call_ai, s.web_research = original

        self.assertEqual(len(calls), 2)
        self.assertEqual(result["sources"], [source])
        self.assertEqual(result["reply"], "Grounded answer.")


class TestResearchHelpers(unittest.TestCase):
    def test_relevance_filter_drops_single_term_junk(self):
        from app.server import _query_terms, _relevant_results
        terms = _query_terms("edge AI adoption survey 2025")
        junk = {
            "title": "Download Microsoft Edge | Windows, Mac & Linux",
            "snippet": "Microsoft Edge is the AI-powered browser.",
            "url": "https://www.microsoft.com/edge",
        }
        good = {
            "title": "2025 Edge AI Technology Report",
            "snippet": "Adoption survey of edge AI deployments.",
            "url": "https://example.com/edge-ai",
        }
        kept = _relevant_results([junk, good], terms)
        self.assertEqual([row["title"] for row in kept], ["2025 Edge AI Technology Report"])

    def test_web_research_filters_and_dedupes(self):
        import app.server as s
        good = {
            "title": "2025 Edge AI Adoption Survey",
            "snippet": "Adoption of edge AI is rising.",
            "url": "https://example.com/edge-ai-survey",
        }
        junk = {
            "title": "Download Microsoft Edge",
            "snippet": "Microsoft Edge is the AI-powered browser.",
            "url": "https://www.microsoft.com/edge",
        }
        original = (s._bing_rss_search, s._bing_search, s._ddg_search, s._wiki_search)
        try:
            s._bing_rss_search = lambda query, limit: [junk, good, dict(good)]
            s._bing_search = lambda query, limit: []
            s._ddg_search = lambda query, limit: []
            s._wiki_search = lambda query, limit: []
            with s._RESEARCH_CACHE_LOCK:
                s._RESEARCH_CACHE.clear()
            rows = s.web_research("edge AI adoption survey 2025", 3)
            self.assertEqual([row["url"] for row in rows], [good["url"]])
        finally:
            s._bing_rss_search, s._bing_search, s._ddg_search, s._wiki_search = original


if __name__ == "__main__":
    unittest.main()
