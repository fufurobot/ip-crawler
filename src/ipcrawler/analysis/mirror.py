"""Layer 2 -- turn remote wikis into a local, browsable file tree.

A mirror is deliberately dumb: it asks a :class:`~ipcrawler.domain.Crawler` for
a known list of URLs and writes the bodies into a host-namespaced directory.
Discovery of *which* URLs matter is layer 3's job -- this module only guarantees
that once you name a URL, you get a predictable file on disk.

The resulting tree is directly servable by :mod:`ipcrawler.analysis.server` and
directly understandable by a human opening ``index.html`` in a browser.
"""

from __future__ import annotations

import dataclasses
import pathlib
from typing import Iterable, Sequence
from urllib.parse import urlsplit

from ..domain import Crawler, Source

__all__ = ["MirrorResult", "WikiMirror"]


@dataclasses.dataclass(frozen=True)
class MirrorResult:
    """What a :meth:`WikiMirror.mirror` call produced."""

    host: str
    directory: pathlib.Path
    files: tuple[pathlib.Path, ...] = ()
    failures: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """True when every requested page was written."""
        return not self.failures


class WikiMirror:
    """Writes crawler output into ``root/<host>/<path>.html``.

    Parameters
    ----------
    crawler:
        Any object implementing :meth:`~ipcrawler.domain.Crawler.fetch`.
    root:
        Directory that receives one sub-directory per mirrored host.
    concurrency:
        Accepted for API symmetry with concurrent crawlers; the mirror itself
        delegates batching to ``crawler.fetch_all`` when available.
    """

    def __init__(
        self,
        crawler: Crawler,
        root: str | pathlib.Path,
        *,
        concurrency: int = 4,
    ) -> None:
        if concurrency <= 0:
            raise ValueError("concurrency must be positive")
        self.crawler = crawler
        self.root = pathlib.Path(root)
        self.concurrency = concurrency

    def mirror(
        self,
        source: Source,
        extra_paths: Iterable[str] = (),
    ) -> MirrorResult:
        """Mirror *source* plus every entry in *extra_paths*.

        ``extra_paths`` entries are URL paths relative to ``source`` (for
        example ``"wiki/Amiya"``).  A page that cannot be fetched is recorded
        in :attr:`MirrorResult.failures` instead of aborting the whole mirror.
        """
        urls = [source.url]
        for path in extra_paths:
            urls.append(_join_url(source.url, path))

        directory = self.root / source.host
        directory.mkdir(parents=True, exist_ok=True)

        bodies = self._fetch_all(urls)

        files: list[pathlib.Path] = []
        failures: list[str] = []
        for url in urls:
            body = bodies.get(url)
            if body is None:
                failures.append(url)
                continue
            target = _target_path(self.root, source.host, url, len(urls))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
            files.append(target)

        return MirrorResult(
            host=source.host,
            directory=directory,
            files=tuple(files),
            failures=tuple(failures),
        )

    def _fetch_all(self, urls: Sequence[str]) -> dict[str, str]:
        """Fetch every URL, tolerating individual failures."""
        sources = [Source(url=url, kind="page") for url in urls]
        bodies: dict[str, str] = {}
        fetch_all = getattr(self.crawler, "fetch_all", None)
        if callable(fetch_all):
            try:
                bodies.update(fetch_all(sources))
                return bodies
            except Exception:
                # Fall through to per-URL fetching so one bad page cannot
                # poison the whole mirror.
                bodies.clear()
        for url in urls:
            try:
                bodies[url] = self.crawler.fetch(Source(url=url, kind="page"))
            except Exception:
                continue
        return bodies


def _join_url(base: str, path: str) -> str:
    if path.startswith(("http://", "https://")):
        return path
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _target_path(
    root: pathlib.Path,
    host: str,
    url: str,
    url_count: int,
) -> pathlib.Path:
    """Map *url* to ``root/<host>/<path>.html``.

    A URL with no path (or a bare ``/``) becomes ``index.html``.
    """
    split = urlsplit(url)
    path = split.path.strip("/")
    if not path:
        relative = "index.html"
    elif path.endswith((".html", ".htm")):
        relative = path
    else:
        relative = f"{path}.html"
    return root / host / pathlib.PurePosixPath(relative)
