"""Shared test helpers."""

from __future__ import annotations

import itertools
import os
import pathlib
import shutil

__all__ = ["workspace_tmp", "temp_dir", "data_root", "project_root"]


def project_root() -> pathlib.Path:
    """The repository root (the directory holding ``pyproject.toml``)."""
    return pathlib.Path(__file__).resolve().parent.parent


def data_root() -> pathlib.Path:
    """The plan's ``./data`` directory, holding one folder per game."""
    return pathlib.Path(os.environ.get("IPCRAWLER_DATA_ROOT", project_root() / "data"))

_counter = itertools.count()


def _base() -> pathlib.Path:
    base = pathlib.Path(os.environ.get("IPCRAWLER_TEST_TMP", ".tmp"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def workspace_tmp(prefix: str = "ipcrawler-test-", cleanup: bool = True) -> pathlib.Path:
    """Create a scratch directory inside the project workspace.

    ``tempfile.TemporaryDirectory`` is deliberately avoided: on Windows it
    creates the directory with an owner-only mode that some restricted
    environments refuse to write into afterwards.  Tests instead create an
    ordinary directory and remove it eagerly, mirroring what CI (Linux) would
    do with ``tmp_path``.
    """
    base = _base()
    for _ in range(1000):
        candidate = base / f"{prefix}{os.getpid()}-{next(_counter)}"
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        break
    else:  # pragma: no cover - pathological
        raise RuntimeError(f"could not allocate a scratch dir under {base}")

    if cleanup:
        import atexit

        atexit.register(shutil.rmtree, str(candidate), True)
    return candidate


# Backwards-compatible alias.
temp_dir = workspace_tmp
