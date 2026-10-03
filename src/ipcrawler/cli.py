"""The ``ip-crawler`` command line.

This is the only module that ties the three layers together, and it is
deliberately thin -- it wires, it does not decide:

``games``
    list every catalogued franchise (layer 3).
``mirror``
    plan or run ``WgetMPXCrawler`` over one or more games (layers 1 + 3).
``analyse``
    infer the meta structure of a mirrored directory (layer 2).
``serve``
    serve a mirror over loopback so ``playwright codegen`` can drive it
    (layer 2).
``codegen``
    plan the ``playwright codegen`` invocation (layer 2).
``build-db``
    analyse every mirrored game and fill the single sqlite database
    (layers 2 + 3 + storage).

Every network-touching command supports ``--dry-run``, so the plan's pipeline
can be inspected without crawling anything.
"""

from __future__ import annotations

import argparse
import dataclasses
import pathlib
import sys
from typing import Callable, Iterable, Mapping, Sequence

from .analysis.driver import codegen_command
from .analysis.mirror import WikiMirror
from .analysis.schema import PageSchema, analyse_page
from .analysis.server import LocalWikiServer
from .crawler import WgetMPXCrawler
from .domain import IP
from .games import GAME_SPECS, GameSpec, build_ip, get_spec
from .storage import Database

__all__ = [
    "build_parser",
    "main",
    "run_mirror",
    "MirrorPlan",
    "DirectoryAnalysis",
    "analyse_directory",
    "build_ip_from_directory",
]

DEFAULT_DATA_ROOT = pathlib.Path("data")
DEFAULT_DATABASE = pathlib.Path("ipcrawler.sqlite3")
_HTML_SUFFIXES = (".html", ".htm")


# --------------------------------------------------------------------- plan


@dataclasses.dataclass(frozen=True)
class MirrorPlan:
    """What a ``mirror`` invocation intends to do for one game."""

    spec: GameSpec
    directory: pathlib.Path
    source_url: str


@dataclasses.dataclass(frozen=True)
class DirectoryAnalysis:
    """The result of analysing a mirrored directory."""

    directory: pathlib.Path
    page_count: int
    schema: PageSchema


# ------------------------------------------------------------------- mirror


def run_mirror(
    games: Sequence[str],
    *,
    data_root: str | pathlib.Path = DEFAULT_DATA_ROOT,
    crawler_factory: Callable[[GameSpec], object] | None = None,
    dry_run: bool = False,
    extra_paths: Sequence[str] = (),
) -> list[MirrorPlan]:
    """Mirror *games* into ``data_root/<slug>/main``.

    With ``dry_run`` the plans are returned without invoking any crawler, so
    the pipeline is inspectable offline.
    """
    plans: list[MirrorPlan] = []
    for slug in games:
        spec = get_spec(slug)
        plans.append(
            MirrorPlan(
                spec=spec,
                directory=spec.mirror_dir(data_root),
                source_url=spec.wiki_url,
            )
        )

    if dry_run:
        return plans

    factory = crawler_factory or (lambda spec: WgetMPXCrawler())
    for plan in plans:
        crawler = factory(plan.spec)
        if crawler is None:  # pragma: no cover - defensive
            raise RuntimeError(f"no crawler available for {plan.spec.slug}")
        mirror = WikiMirror(crawler, plan.directory)
        mirror.mirror(plan.spec.source, extra_paths=extra_paths)

    return plans


# ------------------------------------------------------------------ analyse


def analyse_directory(directory: str | pathlib.Path) -> DirectoryAnalysis:
    """Infer the merged :class:`PageSchema` of every HTML file under *directory*."""
    root = pathlib.Path(directory)
    if not root.is_dir():
        raise NotADirectoryError(f"not a directory: {root}")

    schema = PageSchema()
    count = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _HTML_SUFFIXES:
            continue
        schema = schema.merge(analyse_page(path.read_text(encoding="utf-8", errors="replace")))
        count += 1

    return DirectoryAnalysis(directory=root, page_count=count, schema=schema)


def read_pages(directory: str | pathlib.Path) -> dict[str, str]:
    """Read every HTML file under *directory*, keyed by its relative path."""
    root = pathlib.Path(directory)
    if not root.is_dir():
        raise NotADirectoryError(f"not a directory: {root}")

    pages: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _HTML_SUFFIXES:
            continue
        key = path.relative_to(root).with_suffix("").as_posix()
        pages[key] = path.read_text(encoding="utf-8", errors="replace")
    return pages


def build_ip_from_directory(slug: str, directory: str | pathlib.Path) -> IP:
    """Build the :class:`~ipcrawler.domain.IP` for *slug* from a mirrored directory."""
    spec = get_spec(slug)
    return build_ip(spec, read_pages(directory))


def build_database(
    *,
    data_root: str | pathlib.Path = DEFAULT_DATA_ROOT,
    database: str | pathlib.Path = DEFAULT_DATABASE,
    games: Sequence[str] | None = None,
) -> dict[str, int]:
    """Analyse every mirrored game and fill the single sqlite database."""
    root = pathlib.Path(data_root)
    slugs = list(games) if games else [spec.slug for spec in GAME_SPECS]

    written: dict[str, int] = {}
    with Database(database) as db:
        for slug in slugs:
            spec = get_spec(slug)
            directory = spec.mirror_dir(root)
            if not directory.is_dir():
                continue
            ip = build_ip_from_directory(slug, directory)
            db.save(ip)
            written[slug] = len(ip.characters)
    return written


# ---------------------------------------------------------------------- cli


def build_parser() -> argparse.ArgumentParser:
    """The full argument parser for ``ip-crawler``."""
    parser = argparse.ArgumentParser(
        prog="ip-crawler",
        description="Crawl virtual characters from their wikis into one sqlite database.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("games", help="list every catalogued game")

    mirror = sub.add_parser("mirror", help="mirror one or more game wikis")
    mirror.add_argument("game", nargs="+", help="game slug(s), e.g. arknights")
    mirror.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    mirror.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be mirrored without crawling",
    )

    analyse = sub.add_parser("analyse", help="infer the meta structure of a mirror")
    analyse.add_argument("directory", help="a mirrored directory")
    analyse.add_argument("--game", default=None, help="also build this game's IP")

    serve = sub.add_parser("serve", help="serve a mirror over loopback HTTP")
    serve.add_argument("directory", help="a mirrored directory")

    codegen = sub.add_parser("codegen", help="plan a playwright codegen session")
    codegen.add_argument("url", help="http(s) URL to record")
    codegen.add_argument("-o", "--output", default="output.py")
    codegen.add_argument("--user-data-dir", default=str(pathlib.Path(".data") / "profile"))

    build = sub.add_parser("build-db", help="fill the sqlite database from mirrors")
    build.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    build.add_argument("--database", default=str(DEFAULT_DATABASE))
    build.add_argument("game", nargs="*", help="restrict to these game slugs")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point; returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    echo = print

    if args.command == "games":
        for spec in GAME_SPECS:
            echo(f"{spec.slug}\t{spec.name}\t{spec.wiki_url}")
        return 0

    if args.command == "mirror":
        plans = run_mirror(
            args.game, data_root=args.data_root, dry_run=args.dry_run
        )
        for plan in plans:
            verb = "would mirror" if args.dry_run else "mirrored"
            echo(f"{verb} {plan.spec.name} -> {plan.directory} ({plan.source_url})")
        return 0

    if args.command == "analyse":
        result = analyse_directory(args.directory)
        echo(f"{result.page_count} page(s) analysed in {result.directory}")
        for field in result.schema.fields:
            echo(f"  {field.name}")
        if args.game:
            ip = build_ip_from_directory(args.game, args.directory)
            echo(f"  -> {len(ip.characters)} character(s) for {ip.name}")
        return 0

    if args.command == "serve":
        with LocalWikiServer(args.directory) as server:
            echo(f"serving {args.directory} at {server.base_url}/")
            echo("press ctrl-c to stop")
            try:
                while True:
                    import time

                    time.sleep(3600)
            except KeyboardInterrupt:
                pass
        return 0

    if args.command == "codegen":
        argv_out = codegen_command(
            args.url, output=args.output, user_data_dir=args.user_data_dir
        )
        echo(" ".join(argv_out))
        return 0

    if args.command == "build-db":
        written = build_database(
            data_root=args.data_root,
            database=args.database,
            games=args.game or None,
        )
        total = sum(written.values())
        echo(f"wrote {total} character(s) into {args.database}")
        for slug, count in sorted(written.items()):
            echo(f"  {slug}: {count}")
        return 0

    parser.error(f"unknown command {args.command!r}")  # pragma: no cover
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
