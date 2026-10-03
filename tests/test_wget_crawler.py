"""Layer 1 -- the concrete ``WgetMPXCrawler``.

The plan calls for a single concrete crawler that mirrors whole websites with
``wget`` run in a multiprocessing pool.  These tests pin its observable
behaviour without ever shelling out to a real ``wget`` or touching the network:
the subprocess boundary is injected.
"""

from __future__ import annotations

import pathlib
import unittest

from ipcrawler.crawler.wget import WgetMPXCrawler
from ipcrawler.domain import Crawler, Source

from .support import workspace_tmp


class RecordingRunner:
    """Stands in for ``subprocess.run``; records argv and writes fake output."""

    def __init__(self, *, returncode: int = 0, body: str = "<html>ok</html>") -> None:
        self.returncode = returncode
        self.body = body
        self.commands: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
        # Emulate wget writing the page where the crawler asked it to.
        outdir = pathlib.Path(kwargs["cwd"])
        target = outdir / "mirrored.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.body, encoding="utf-8")

        class Completed:
            pass

        completed = Completed()
        completed.returncode = self.returncode
        completed.stdout = ""
        completed.stderr = ""
        return completed


class WgetMPXCrawlerConstructionTest(unittest.TestCase):
    def test_is_a_crawler(self) -> None:
        self.assertIsInstance(WgetMPXCrawler(runner=RecordingRunner()), Crawler)

    def test_default_workers_is_positive(self) -> None:
        crawler = WgetMPXCrawler(runner=RecordingRunner())
        self.assertGreaterEqual(crawler.workers, 1)

    def test_rejects_non_positive_workers(self) -> None:
        with self.assertRaises(ValueError):
            WgetMPXCrawler(runner=RecordingRunner(), workers=0)

    def test_rejects_negative_timeout(self) -> None:
        with self.assertRaises(ValueError):
            WgetMPXCrawler(runner=RecordingRunner(), timeout=-1)


class WgetMPXCrawlerCommandTest(unittest.TestCase):
    def test_builds_an_argv_that_mirrors_a_website(self) -> None:
        crawler = WgetMPXCrawler(runner=RecordingRunner())
        argv = crawler.build_command(
            Source(url="https://wiki.test/", kind="wiki"),
            pathlib.Path("out"),
        )

        self.assertEqual(argv[0], "wget")
        self.assertIn("--mirror", argv)
        # Never walk off-site: mirroring a wiki must stay on its own host.
        self.assertIn("--no-parent", argv)
        self.assertIn("--page-requisites", argv)
        self.assertIn("--convert-links", argv)
        self.assertIn("--directory-prefix", argv)
        self.assertIn("https://wiki.test/", argv)

    def test_command_has_no_shell_metacharacters_unquoted(self) -> None:
        crawler = WgetMPXCrawler(runner=RecordingRunner())
        argv = crawler.build_command(
            Source(url="https://wiki.test/", kind="wiki"),
            pathlib.Path("out"),
        )
        self.assertTrue(all(isinstance(part, str) for part in argv))


class WgetMPXCrawlerFetchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = workspace_tmp()

    def test_fetch_returns_the_mirrored_body(self) -> None:
        runner = RecordingRunner(body="<html>hello</html>")
        crawler = WgetMPXCrawler(runner=runner, workdir=self.root)
        body = crawler.fetch(Source(url="https://wiki.test/", kind="wiki"))
        self.assertEqual(body, "<html>hello</html>")

    def test_fetch_invokes_the_runner_once_per_source(self) -> None:
        runner = RecordingRunner()
        crawler = WgetMPXCrawler(runner=runner, workdir=self.root)
        crawler.fetch(Source(url="https://wiki.test/", kind="wiki"))
        self.assertEqual(len(runner.commands), 1)

    def test_fetch_raises_on_non_zero_exit(self) -> None:
        runner = RecordingRunner(returncode=8)
        crawler = WgetMPXCrawler(runner=runner, workdir=self.root)
        with self.assertRaises(RuntimeError):
            crawler.fetch(Source(url="https://wiki.test/", kind="wiki"))

    def test_fetch_all_mirrors_every_source_keyed_by_url(self) -> None:
        runner = RecordingRunner()
        crawler = WgetMPXCrawler(runner=runner, workdir=self.root, workers=2)
        sources = [
            Source(url="https://a.test/", kind="wiki"),
            Source(url="https://b.test/", kind="wiki"),
        ]
        result = crawler.fetch_all(sources)

        self.assertEqual(set(result), {"https://a.test/", "https://b.test/"})
        self.assertEqual(len(runner.commands), 2)

    def test_fetch_all_with_no_sources_is_empty(self) -> None:
        crawler = WgetMPXCrawler(runner=RecordingRunner(), workdir=self.root)
        self.assertEqual(crawler.fetch_all([]), {})

    def test_workers_are_capped_by_the_number_of_sources(self) -> None:
        crawler = WgetMPXCrawler(runner=RecordingRunner(), workdir=self.root, workers=16)
        self.assertEqual(crawler.plan_workers(2), 2)
        self.assertEqual(crawler.plan_workers(1), 1)
        self.assertEqual(crawler.plan_workers(0), 0)
        self.assertEqual(crawler.plan_workers(100), 16)


if __name__ == "__main__":
    unittest.main()
