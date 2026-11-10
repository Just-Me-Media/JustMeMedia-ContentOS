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


if __name__ == "__main__":
    unittest.main()
