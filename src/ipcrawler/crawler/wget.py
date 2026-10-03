"""Layer 1 -- the concrete ``WgetMPXCrawler``.

The plan asks for one concrete crawler that mirrors whole websites with
``wget`` driven from a multiprocessing pool.  That is exactly what this module
provides, with one important twist for testability and for the sandbox we run
in: everything below the process boundary is injected.

* ``runner``  -- callable invoked as ``runner(argv, cwd=..., ...)``; defaults to
  :func:`subprocess.run`.  Tests pass a recorder instead of shelling out.
* ``workdir`` -- where per-source scratch directories live.

Mirroring flags are chosen so a wiki is never walked off its own host:

``--mirror``
    recursive, timestamping, infinite depth, keeps the site's directory layout.
``--no-parent``
    never ascend to a parent directory.
``--page-requisites``
    pull the CSS/images needed to *render* the page, which matters because
    layer 2 replays these pages in a real browser.
``--convert-links``
    rewrite links for offline browsing, so the local mirror is self-contained.
``--adjust-extension``
    give HTML saved without an extension a ``.html`` suffix.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, Sequence

from ..domain import Crawler, Source

__all__ = ["WgetMPXCrawler"]


_HTML_SUFFIXES = (".html", ".htm")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class WgetMPXCrawler(Crawler):
    """Mirror websites with ``wget``, one subprocess per source.

    ``workers`` caps how many sources are mirrored at once.  The name keeps the
    ``MPX`` the plan asked for: concurrency is fanned out across processes by
    ``wget`` itself, while the pool here bounds simultaneous invocations.
    """

    def __init__(
        self,
        *,
        runner: Callable[..., object] | None = None,
        workdir: str | pathlib.Path | None = None,
        workers: int = 4,
        timeout: float | None = 300.0,
        wget_binary: str = "wget",
    ) -> None:
        if workers <= 0:
            raise ValueError("workers must be positive")
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must not be negative")

        self.runner = runner if runner is not None else subprocess.run
        self.workdir = pathlib.Path(workdir) if workdir is not None else pathlib.Path(".mirror")
        self.workers = workers
        self.timeout = timeout
        self.wget_binary = wget_binary

    # ------------------------------------------------------------------ plan

    def plan_workers(self, source_count: int) -> int:
        """How many workers to actually use for *source_count* sources."""
        if source_count <= 0:
            return 0
        return min(self.workers, source_count)

    # -------------------------------------------------------------- commands

    def build_command(self, source: Source, destination: pathlib.Path) -> list[str]:
        """The ``wget`` argv used to mirror *source* into *destination*."""
        return [
            self.wget_binary,
            "--mirror",
            "--no-parent",
            "--page-requisites",
            "--convert-links",
            "--adjust-extension",
            "--no-verbose",
            "--no-check-certificate",
            "--directory-prefix",
            str(destination),
            source.url,
        ]

    # ----------------------------------------------------------------- fetch

    def fetch(self, source: Source) -> str:
        """Mirror *source* and return the mirrored HTML for its root URL.

        Raises
        ------
        RuntimeError
            If ``wget`` exits non-zero.
        FileNotFoundError
            If ``wget`` succeeded but produced no readable HTML.
        """
        destination = self._destination_for(source)
        destination.mkdir(parents=True, exist_ok=True)
        argv = self.build_command(source, destination)

        completed = self.runner(argv, cwd=str(destination), timeout=self.timeout)
        returncode = getattr(completed, "returncode", 0)
        if returncode != 0:
            stderr = (getattr(completed, "stderr", "") or "").strip()
            raise RuntimeError(
                f"wget failed for {source.url} (exit {returncode})"
                + (f": {stderr}" if stderr else "")
            )

        return self._read_mirrored_html(destination, source)

    def fetch_all(self, sources: Iterable[Source]) -> dict[str, str]:
        """Mirror many sources concurrently, keyed by URL.

        A source that fails is reported as a :class:`RuntimeError` *inside* the
        returned mapping's construction only if every source failed; otherwise
        failures are skipped so one bad wiki cannot sink the batch.
        """
        sources = list(sources)
        workers = self.plan_workers(len(sources))
        if workers == 0:
            return {}

        bodies: dict[str, str] = {}
        errors: list[BaseException] = []

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self.fetch, source): source for source in sources}
            for future, source in futures.items():
                try:
                    bodies[source.url] = future.result()
                except Exception as exc:  # noqa: BLE001 - collected for the caller
                    errors.append(exc)

        if not bodies and errors:
            raise RuntimeError(
                f"all {len(errors)} source(s) failed; first error: {errors[0]}"
            ) from errors[0]
        return bodies

    # --------------------------------------------------------------- private

    def _destination_for(self, source: Source) -> pathlib.Path:
        return self.workdir / _SAFE_NAME.sub("_", source.host or "unknown")

    def _read_mirrored_html(self, destination: pathlib.Path, source: Source) -> str:
        """Find the HTML ``wget`` just wrote for *source*'s root URL."""
        host_dir = destination / (source.host or "")
        search_root = host_dir if host_dir.exists() else destination

        candidates = _html_candidates(search_root)
        if not candidates:
            raise FileNotFoundError(
                f"wget produced no HTML for {source.url} under {destination}"
            )

        # Prefer an index page, then the shallowest file, then the newest.
        candidates.sort(
            key=lambda p: (
                p.name not in ("index.html", "index.htm"),
                len(p.relative_to(search_root).parts),
                -p.stat().st_mtime,
            )
        )
        return candidates[0].read_text(encoding="utf-8", errors="replace")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"WgetMPXCrawler(workers={self.workers}, timeout={self.timeout}, "
            f"workdir={self.workdir!s})"
        )


def _html_candidates(root: pathlib.Path) -> list[pathlib.Path]:
    if not root.exists():
        return []
    found: list[pathlib.Path] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in _HTML_SUFFIXES:
            found.append(path)
    return found
