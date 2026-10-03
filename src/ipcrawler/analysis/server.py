"""Layer 2 -- serve a mirrored wiki tree over loopback HTTP.

``playwright codegen`` needs a URL, not a file path: ``file://`` pages behave
differently from served ones (CORS, ``fetch``, relative-URL resolution), and a
mirrored wiki that uses any of those will not exercise the same code paths.  A
throwaway loopback server removes that discrepancy.

The server is intentionally minimal -- a threaded
:class:`http.server.SimpleHTTPRequestHandler` bound to ``127.0.0.1`` on an
ephemeral port, so several mirrors can be served at once without coordination.
"""

from __future__ import annotations

import contextlib
import functools
import http.server
import pathlib
import threading
import urllib.error
import urllib.request

__all__ = ["LocalWikiServer"]


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """A :class:`SimpleHTTPRequestHandler` that does not spam stderr."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Silence per-request logging; this server is a test/app fixture."""


class LocalWikiServer:
    """Context manager serving *root* at ``http://127.0.0.1:<port>/``.

    Usage::

        with LocalWikiServer("<data>/mirror") as server:
            print(server.url_for("wiki.test/index.html"))
            # ... drive a browser here ...
    """

    def __init__(self, root: str | pathlib.Path, *, host: str = "127.0.0.1") -> None:
        self.root = pathlib.Path(root)
        if not self.root.is_dir():
            raise NotADirectoryError(f"not a directory: {self.root}")
        self.host = host
        self._httpd: http.server.ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------ lifecycle

    def start(self) -> "LocalWikiServer":
        handler = functools.partial(_QuietHandler, directory=str(self.root))
        self._httpd = http.server.ThreadingHTTPServer((self.host, 0), handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name=f"ipcrawler-http-{self._httpd.server_port}",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        httpd, thread = self._httpd, self._thread
        self._httpd = self._thread = None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if thread is not None:
            thread.join(timeout=5)

    def __enter__(self) -> "LocalWikiServer":
        return self.start()

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    # ------------------------------------------------------------- accessors

    @property
    def port(self) -> int:
        if self._httpd is None:
            raise RuntimeError("server is not running")
        return int(self._httpd.server_port)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def url_for(self, path: str) -> str:
        """Absolute URL for *path* (with or without a leading slash)."""
        return f"{self.base_url}/{path.lstrip('/')}"

    # ----------------------------------------------------------------- fetch

    def get(self, path: str) -> str:
        """GET *path* from this server and return the decoded body."""
        return self._request(self.url_for(path))

    @staticmethod
    def _request(url: str) -> str:
        """GET *url*, mapping HTTP failures onto Python exceptions."""
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise LookupError(f"404 Not Found: {url}") from exc
            raise
        except urllib.error.URLError as exc:
            raise OSError(str(exc.reason)) from exc
