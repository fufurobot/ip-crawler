"""Layer 2 -- mirroring wiki sites into a local, browsable tree.

``WikiMirror`` turns a :class:`~ipcrawler.domain.Source` into a directory of
local files so the analysis stages can serve and drive them offline.
"""

from __future__ import annotations

import pathlib
import unittest

from ipcrawler.analysis.mirror import MirrorResult, WikiMirror
from ipcrawler.domain import Source

from .support import workspace_tmp


class FakeCrawler:
    """A tiny in-memory stand-in for ``WgetMPXCrawler``."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def fetch(self, source: Source) -> str:
        self.calls.append(source.url)
        try:
            return self.pages[source.url]
        except KeyError:  # pragma: no cover - defensive
            raise FileNotFoundError(source.url) from None

    def fetch_all(self, sources):
        return {s.url: self.fetch(s) for s in sources}


class WikiMirrorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = workspace_tmp()

    def test_mirrors_root_page_to_index_html(self) -> None:
        crawler = FakeCrawler({"https://wiki.test/": "<html>root</html>"})
        mirror = WikiMirror(crawler, self.root)
        result = mirror.mirror(Source(url="https://wiki.test/", kind="wiki"))

        self.assertIsInstance(result, MirrorResult)
        self.assertEqual(result.host, "wiki.test")
        index = result.directory / "index.html"
        self.assertTrue(index.exists())
        self.assertEqual(index.read_text(encoding="utf-8"), "<html>root</html>")

    def test_result_records_every_written_file(self) -> None:
        crawler = FakeCrawler(
            {
                "https://wiki.test/": "<html>root</html>",
                "https://wiki.test/wiki/Amiya": "<html>amiya</html>",
            }
        )
        mirror = WikiMirror(crawler, self.root)
        result = mirror.mirror(
            Source(url="https://wiki.test/", kind="wiki"),
            extra_paths=["wiki/Amiya"],
        )

        names = sorted(p.relative_to(self.root).as_posix() for p in result.files)
        self.assertEqual(
            names,
            ["wiki.test/index.html", "wiki.test/wiki/Amiya.html"],
        )

    def test_nested_paths_create_nested_directories(self) -> None:
        crawler = FakeCrawler({"https://wiki.test/a/b/c": "<p>deep</p>"})
        mirror = WikiMirror(crawler, self.root)
        result = mirror.mirror(Source(url="https://wiki.test/a/b/c", kind="wiki"))
        self.assertTrue((result.directory / "a" / "b" / "c.html").exists())

    def test_directory_is_namespaced_by_host(self) -> None:
        crawler = FakeCrawler({"https://a.test/": "<p>a</p>"})
        mirror = WikiMirror(crawler, self.root)
        result = mirror.mirror(Source(url="https://a.test/", kind="wiki"))
        self.assertEqual(result.directory, self.root / "a.test")

    def test_failing_page_is_recorded_not_raised(self) -> None:
        crawler = FakeCrawler({"https://wiki.test/": "<html>root</html>"})
        mirror = WikiMirror(crawler, self.root)
        result = mirror.mirror(
            Source(url="https://wiki.test/", kind="wiki"),
            extra_paths=["wiki/Missing"],
        )

        self.assertEqual(result.failures, ("https://wiki.test/wiki/Missing",))
        self.assertEqual(len(result.files), 1)

    def test_mirroring_twice_is_idempotent(self) -> None:
        crawler = FakeCrawler({"https://wiki.test/": "<html>root</html>"})
        mirror = WikiMirror(crawler, self.root)
        source = Source(url="https://wiki.test/", kind="wiki")
        first = mirror.mirror(source)
        second = mirror.mirror(source)
        self.assertEqual(
            sorted(p.as_posix() for p in first.files),
            sorted(p.as_posix() for p in second.files),
        )

    def test_rejects_non_positive_concurrency(self) -> None:
        with self.assertRaises(ValueError):
            WikiMirror(FakeCrawler({}), self.root, concurrency=0)

    def test_module_is_importable_without_network(self) -> None:
        # The mirror must be pure filesystem + crawler; no sockets opened here.
        self.assertTrue(callable(WikiMirror(FakeCrawler({}), self.root).mirror))


if __name__ == "__main__":
    unittest.main()
