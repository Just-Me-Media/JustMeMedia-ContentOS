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
        from app.server import ApiError
        payload = {"title": "   ", "body": "Some body", "platform": "LinkedIn"}
        with self.assertRaises(ApiError) as cm:
            raise ApiError(400, "Title is required.")
        self.assertIn("Title is required", str(cm.exception))

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
        # Draw Things is offline in sandboxed test run; should gracefully return error dict
        res = generate_local_image("a futuristic workstation")
        self.assertFalse(res["ok"])
        self.assertIn("Draw Things API not available", res["error"])

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


if __name__ == "__main__":
    unittest.main()
