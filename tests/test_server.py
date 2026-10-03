"""Layer 2 -- serve a mirrored tree over loopback HTTP.

The plan calls for "a simple python http server to host" the mirrors, so that
``playwright codegen`` can drive a *real* browser against them.  This module
wraps :class:`http.server.ThreadingHTTPServer` in a context manager that binds
an ephemeral port on ``127.0.0.1`` and reports the base URL to use.
"""

from __future__ import annotations

import http.server
import pathlib
import threading
import unittest

from ipcrawler.analysis.server import LocalWikiServer

from .support import workspace_tmp


class _SilentHandler(http.server.SimpleHTTPRequestHandler):
    """Placeholder used only to document intent in tests."""


class LocalWikiServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = workspace_tmp()
        (self.root / "index.html").write_text("<html>home</html>", encoding="utf-8")
        (self.root / "wiki.test").mkdir()
        (self.root / "wiki.test" / "index.html").write_text(
            "<html>wiki</html>", encoding="utf-8"
        )

    def test_serves_files_from_the_root(self) -> None:
        with LocalWikiServer(self.root) as server:
            body = server.get("/wiki.test/index.html")
            self.assertIn("wiki", body)

    def test_binds_loopback_only(self) -> None:
        with LocalWikiServer(self.root) as server:
            self.assertEqual(server.host, "127.0.0.1")
            self.assertTrue(server.base_url.startswith("http://127.0.0.1:"))

    def test_exposes_a_real_url_with_a_port(self) -> None:
        with LocalWikiServer(self.root) as server:
            self.assertIsInstance(server.port, int)
            self.assertGreater(server.port, 0)

    def test_two_servers_do_not_collide(self) -> None:
        with LocalWikiServer(self.root) as a, LocalWikiServer(self.root) as b:
            self.assertNotEqual(a.port, b.port)

    def test_server_stops_after_the_context_exits(self) -> None:
        with LocalWikiServer(self.root) as server:
            port = server.port
            self.assertIn("home", server.get("/index.html"))
        # After exit the port must be closed.
        with self.assertRaises(OSError):
            LocalWikiServer._request(f"http://127.0.0.1:{port}/index.html")

    def test_rejects_a_missing_root(self) -> None:
        with self.assertRaises(NotADirectoryError):
            LocalWikiServer(self.root / "nope")

    def test_url_for_joins_paths(self) -> None:
        with LocalWikiServer(self.root) as server:
            self.assertEqual(
                server.url_for("wiki.test/index.html"),
                f"{server.base_url}/wiki.test/index.html",
            )

    def test_404_is_reported_as_lookup_error(self) -> None:
        with LocalWikiServer(self.root) as server:
            with self.assertRaises(LookupError):
                server.get("/does-not-exist.html")


if __name__ == "__main__":
    unittest.main()
