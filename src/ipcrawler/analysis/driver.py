"""Layer 2 -- drive a real browser against a mirrored wiki.

The plan's second layer is a *discovery* loop: serve a mirror, open it in a real
browser, record what a human would click, and turn that recording into a script
that can be replayed.  This module supplies the two halves of that loop.

:func:`codegen_command`
    Build the ``playwright codegen`` argv.  A persistent ``--user-data-dir``
    matters: it keeps logins, cookies and local storage across sessions, which
    is what makes it possible to analyse a wiki that needs to be signed into.

:class:`BrowserDriver`
    Replay a recorded script in a subprocess, and optionally reach into the
    live window with :mod:`pyautogui` (clicking, moving the mouse) for the
    interactions ``codegen`` cannot express, such as dragging a canvas map.

Both accept injected ``runner``/``gui`` callables so the whole layer is
testable and works headlessly on CI, where no display exists.
"""

from __future__ import annotations

import dataclasses
import pathlib
import subprocess
import sys
from typing import Any, Callable, Sequence

__all__ = ["CodegenResult", "RunResult", "BrowserDriver", "codegen_command"]


@dataclasses.dataclass(frozen=True)
class RunResult:
    """Outcome of replaying a recorded playwright script."""

    script: pathlib.Path
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


# ``CodegenResult`` documents the argv a codegen session would use; it is
# returned by :func:`codegen_command`'s sibling :func:`plan_codegen`.
@dataclasses.dataclass(frozen=True)
class CodegenResult:
    """A planned ``playwright codegen`` invocation."""

    argv: tuple[str, ...]
    output: pathlib.Path
    user_data_dir: pathlib.Path
    url: str


def codegen_command(
    url: str,
    *,
    output: str | pathlib.Path,
    user_data_dir: str | pathlib.Path,
    browser: str | None = None,
    extra_args: Sequence[str] = (),
) -> list[str]:
    """Build a ``playwright codegen`` argv recording *url* into *output*.

    Parameters
    ----------
    url:
        Must be ``http://`` or ``https://``.  ``codegen`` against ``file://``
        produces recordings that do not survive being served, so it is refused
        here rather than failing confusingly later.
    output:
        Path of the generated Python script.
    user_data_dir:
        Persistent browser profile; created if missing.
    browser:
        Optional ``--browser`` value (``chromium``, ``firefox``, ``webkit``).
    """
    if not url or not url.strip():
        raise ValueError("url must not be empty")
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"url must be http(s), got {url!r}")

    output_path = pathlib.Path(output)
    profile = pathlib.Path(user_data_dir)
    profile.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    argv = [
        "playwright",
        "codegen",
        "-o",
        str(output_path),
        "--user-data-dir",
        str(profile),
    ]
    if browser:
        argv += ["--browser", browser]
    argv += list(extra_args)
    argv.append(url)
    return argv


class BrowserDriver:
    """Replay recorded browser scripts; optionally poke the window via pyautogui.

    Parameters
    ----------
    runner:
        Callable invoked as ``runner(argv, timeout=...)``.  Defaults to
        :func:`subprocess.run`; tests inject a recorder.
    gui:
        Object exposing pyautogui-style ``click``/``moveTo``.  ``None`` means
        the driver can replay scripts but cannot interact with a live window.
    python:
        Interpreter used to run recorded scripts; defaults to the interpreter
        running this process, so the recording's imports resolve.
    workdir:
        Default directory for scripts and profiles.
    timeout:
        Seconds allowed per script run.
    """

    def __init__(
        self,
        *,
        runner: Callable[..., Any] | None = None,
        gui: Any | None = None,
        python: str | None = None,
        workdir: str | pathlib.Path | None = None,
        timeout: float | None = 600.0,
    ) -> None:
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be positive")
        self.runner = runner if runner is not None else subprocess.run
        self.gui = gui
        self.python = python or sys.executable
        self.workdir = pathlib.Path(workdir) if workdir is not None else pathlib.Path(".")
        self.timeout = timeout

    # ------------------------------------------------------------ recording

    def codegen(
        self,
        url: str,
        *,
        output: str | pathlib.Path | None = None,
        user_data_dir: str | pathlib.Path | None = None,
        browser: str | None = None,
    ) -> CodegenResult:
        """Plan a codegen session and return its argv without running it."""
        output_path = pathlib.Path(output) if output is not None else self.workdir / "output.py"
        profile = (
            pathlib.Path(user_data_dir)
            if user_data_dir is not None
            else self.workdir / "profile"
        )
        argv = codegen_command(
            url, output=output_path, user_data_dir=profile, browser=browser
        )
        return CodegenResult(
            argv=tuple(argv), output=output_path, user_data_dir=profile, url=url
        )

    # -------------------------------------------------------------- replay

    def run(self, script: str | pathlib.Path) -> RunResult:
        """Replay *script* and return its :class:`RunResult`."""
        path = pathlib.Path(script)
        if not path.is_file():
            raise FileNotFoundError(f"no such script: {path}")

        completed = self.runner(
            [self.python, str(path)], cwd=str(path.parent), timeout=self.timeout
        )
        return RunResult(
            script=path,
            returncode=int(getattr(completed, "returncode", 0)),
            stdout=_as_text(getattr(completed, "stdout", "")),
            stderr=_as_text(getattr(completed, "stderr", "")),
        )

    # ----------------------------------------------------------------- gui

    def click(self, x: int, y: int) -> None:
        """Click at screen coordinates via pyautogui."""
        self._require_gui().click(x, y)

    def move_to(self, x: int, y: int) -> None:
        """Move the pointer to screen coordinates via pyautogui."""
        self._require_gui().moveTo(x, y)

    def _require_gui(self) -> Any:
        if self.gui is None:
            raise RuntimeError(
                "no pyautogui backend configured; pass gui=pyautogui to interact "
                "with a live browser window"
            )
        return self.gui


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
