"""Layer 2 -- driving a real browser against a mirrored wiki.

Two entry points, both from the plan:

* :func:`codegen_command` -- build the ``playwright codegen`` invocation that
  records a session into a Python script, using a persistent ``--user-data-dir``
  under ``./data``.
* :class:`RecordingDriver` -- run a recorded script inside an event loop we can
  observe, with :mod:`pyautogui` used to poke the live browser window.

No test here launches a browser: the process boundary is injected everywhere.
"""

from __future__ import annotations

import pathlib
import unittest

from ipcrawler.analysis.driver import BrowserDriver, codegen_command
from ipcrawler.analysis.server import LocalWikiServer

from .support import workspace_tmp


class CodegenCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = workspace_tmp()
        (self.root / "index.html").write_text("<html>x</html>", encoding="utf-8")

    def test_records_into_a_python_script(self) -> None:
        with LocalWikiServer(self.root) as server:
            argv = codegen_command(
                server.url_for("index.html"),
                output=self.root / "output.py",
                user_data_dir=self.root / "profile",
            )
        self.assertEqual(argv[0], "playwright")
        self.assertEqual(argv[1], "codegen")
        self.assertIn("-o", argv)
        self.assertIn(str(self.root / "output.py"), argv)
        self.assertIn("--user-data-dir", argv)
        self.assertIn(str(self.root / "profile"), argv)

    def test_target_url_is_the_last_argument(self) -> None:
        argv = codegen_command(
            "http://127.0.0.1:1234/index.html",
            output="out.py",
            user_data_dir="profile",
        )
        self.assertEqual(argv[-1], "http://127.0.0.1:1234/index.html")

    def test_rejects_an_empty_url(self) -> None:
        with self.assertRaises(ValueError):
            codegen_command("", output="out.py", user_data_dir="profile")

    def test_rejects_a_non_http_url(self) -> None:
        with self.assertRaises(ValueError):
            codegen_command("file:///tmp/x.html", output="o.py", user_data_dir="p")

    def test_creates_the_user_data_directory(self) -> None:
        profile = self.root / "deep" / "profile"
        codegen_command(
            "http://127.0.0.1:1/",
            output=self.root / "o.py",
            user_data_dir=profile,
        )
        self.assertTrue(profile.is_dir())


class RecordingDriverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = workspace_tmp()
        self.script = self.root / "output.py"
        self.script.write_text("# recorded\n", encoding="utf-8")

    def test_runs_the_recorded_script_with_the_venv_python(self) -> None:
        calls: list[list[str]] = []

        class Runner:
            def __call__(self, argv, **kwargs):
                calls.append(list(argv))

                class C:
                    returncode = 0
                    stdout = "ok"
                    stderr = ""

                return C()

        driver = BrowserDriver(runner=Runner(), workdir=self.root)
        result = driver.run(self.script)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][-1].endswith("output.py"))

    def test_reports_a_failing_script(self) -> None:
        class Runner:
            def __call__(self, argv, **kwargs):
                class C:
                    returncode = 1
                    stdout = ""
                    stderr = "boom"

                return C()

        driver = BrowserDriver(runner=Runner(), workdir=self.root)
        result = driver.run(self.script)
        self.assertEqual(result.returncode, 1)
        self.assertIn("boom", result.stderr)
        self.assertFalse(result.ok)

    def test_missing_script_raises(self) -> None:
        driver = BrowserDriver(runner=lambda *a, **k: None, workdir=self.root)
        with self.assertRaises(FileNotFoundError):
            driver.run(self.root / "nope.py")

    def test_click_is_delegated_to_the_gui_backend(self) -> None:
        clicks: list[tuple[int, int]] = []

        class Gui:
            def click(self, x, y):
                clicks.append((x, y))

            def moveTo(self, x, y):  # noqa: N802 - pyautogui's spelling
                clicks.append((x, y))

        driver = BrowserDriver(runner=lambda *a, **k: None, gui=Gui(), workdir=self.root)
        driver.click(10, 20)
        self.assertEqual(clicks, [(10, 20)])

    def test_driver_without_a_gui_refuses_to_click(self) -> None:
        driver = BrowserDriver(runner=lambda *a, **k: None, gui=None, workdir=self.root)
        with self.assertRaises(RuntimeError):
            driver.click(1, 2)

    def test_rejects_non_positive_timeout(self) -> None:
        with self.assertRaises(ValueError):
            BrowserDriver(runner=lambda *a, **k: None, workdir=self.root, timeout=0)


if __name__ == "__main__":
    unittest.main()
