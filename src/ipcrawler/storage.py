"""Fill a single sqlite database from any layer of the project.

The plan's final step is "fill in the database with a single sqlite", so this
module defines the project's output format and the code that writes it.

Schema
------
``ip``          one row per franchise.
``world``       one row per fictional setting, FK to ``ip``.
``location``    one row per place, FK to ``world``.
``character``   one row per persona, FK to ``ip`` and optionally to
                ``world``/``location`` (by name, because wiki data is messy and
                a character may reference a world that was never enumerated).
``alias``       alternative names, FK to ``character``.
``attribute``   raw infobox key/value pairs, FK to ``character``.
``source``      the wiki/API URLs an IP was learned from, FK to ``ip``.

Everything is written with ``INSERT ... ON CONFLICT DO UPDATE`` plus ``UNIQUE``
constraints, so re-running the crawler over the same wiki converges instead of
duplicating rows.
"""

from __future__ import annotations

import pathlib
import sqlite3
from typing import Iterable

from .domain import Character, IP, Location, Source, World

__all__ = ["Database", "SCHEMA", "TABLES"]

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ip (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS world (
    id       INTEGER PRIMARY KEY,
    ip_id    INTEGER NOT NULL REFERENCES ip(id) ON DELETE CASCADE,
    name     TEXT NOT NULL,
    UNIQUE (ip_id, name)
);

CREATE TABLE IF NOT EXISTS location (
    id         INTEGER PRIMARY KEY,
    world_id   INTEGER NOT NULL REFERENCES world(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    UNIQUE (world_id, name)
);

CREATE TABLE IF NOT EXISTS character (
    id             INTEGER PRIMARY KEY,
    ip_id          INTEGER NOT NULL REFERENCES ip(id) ON DELETE CASCADE,
    name           TEXT NOT NULL,
    world_name     TEXT,
    location_name  TEXT,
    UNIQUE (ip_id, name)
);

CREATE TABLE IF NOT EXISTS alias (
    id            INTEGER PRIMARY KEY,
    character_id  INTEGER NOT NULL REFERENCES character(id) ON DELETE CASCADE,
    value         TEXT NOT NULL,
    UNIQUE (character_id, value)
);

CREATE TABLE IF NOT EXISTS attribute (
    id            INTEGER PRIMARY KEY,
    character_id  INTEGER NOT NULL REFERENCES character(id) ON DELETE CASCADE,
    key           TEXT NOT NULL,
    value         TEXT NOT NULL,
    UNIQUE (character_id, key)
);

CREATE TABLE IF NOT EXISTS source (
    id     INTEGER PRIMARY KEY,
    ip_id  INTEGER NOT NULL REFERENCES ip(id) ON DELETE CASCADE,
    url    TEXT NOT NULL,
    kind   TEXT NOT NULL,
    title  TEXT,
    UNIQUE (ip_id, url)
);

CREATE INDEX IF NOT EXISTS idx_character_ip   ON character(ip_id);
CREATE INDEX IF NOT EXISTS idx_alias_character ON alias(character_id);
CREATE INDEX IF NOT EXISTS idx_attribute_character ON attribute(character_id);
"""

TABLES = frozenset(
    {"ip", "world", "location", "character", "alias", "attribute", "source"}
)


class Database:
    """A single sqlite file holding every layer's records.

    Usable as a context manager::

        with Database("ipcrawler.sqlite3") as db:
            db.save(ip)
    """

    def __init__(self, path: str | pathlib.Path = "ipcrawler.sqlite3") -> None:
        self.path = pathlib.Path(path)
        if self.path.is_dir():
            raise IsADirectoryError(f"database path is a directory: {self.path}")
        self.connection: sqlite3.Connection | None = None

    # ------------------------------------------------------------ lifecycle

    def open(self) -> "Database":
        """Open the file (creating it and its parent directory) and ensure the schema."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA)
        self.connection.commit()
        return self

    def close(self) -> None:
        if self.connection is not None:
            self.connection.commit()
            self.connection.close()
            self.connection = None

    def __enter__(self) -> "Database":
        return self.open()

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _conn(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError("database is not open; call open() first")
        return self.connection

    # ---------------------------------------------------------------- write

    def save(self, ip: IP) -> None:
        """Persist *ip* and everything it owns, idempotently."""
        conn = self._conn()
        with conn:  # one transaction per save
            ip_id = self._upsert_ip(conn, ip.name)
            for source in ip.sources:
                self._upsert_source(conn, ip_id, source)
            for world in ip.worlds:
                world_id = self._upsert_world(conn, ip_id, world)
                for location in world.locations:
                    self._upsert_location(conn, world_id, location)
            for character in ip.characters:
                self._upsert_character(conn, ip_id, character)

    def save_many(self, ips: Iterable[IP]) -> None:
        """Persist many IPs in sequence."""
        for ip in ips:
            self.save(ip)

    # ----------------------------------------------------------------- read

    def count(self, table: str) -> int:
        """Number of rows in *table*."""
        if table not in TABLES:
            raise ValueError(f"unknown table {table!r}")
        row = self._conn().execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0])

    def list_ips(self) -> list[str]:
        """Every stored IP name, ordered."""
        rows = self._conn().execute("SELECT name FROM ip ORDER BY name").fetchall()
        return [row["name"] for row in rows]

    def load_ip(self, name: str) -> IP:
        """Rehydrate a single :class:`~ipcrawler.domain.IP` by name."""
        conn = self._conn()
        row = conn.execute("SELECT id FROM ip WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise KeyError(f"no such ip: {name!r}")
        ip_id = row["id"]

        ip = IP(name=name)

        for source_row in conn.execute(
            "SELECT url, kind, title FROM source WHERE ip_id = ? ORDER BY url",
            (ip_id,),
        ):
            ip.add_source(
                Source(
                    url=source_row["url"],
                    kind=source_row["kind"],
                    title=source_row["title"],
                )
            )

        worlds: dict[int, World] = {}
        for world_row in conn.execute(
            "SELECT id, name FROM world WHERE ip_id = ? ORDER BY id", (ip_id,)
        ):
            world = ip.add_world(World(name=world_row["name"]))
            worlds[world_row["id"]] = world

        for location_row in conn.execute(
            """
            SELECT l.name AS name, l.world_id AS world_id, w.name AS world_name
            FROM location l JOIN world w ON w.id = l.world_id
            WHERE w.ip_id = ?
            ORDER BY l.id
            """,
            (ip_id,),
        ):
            world = worlds.get(location_row["world_id"])
            if world is not None:
                world.add_location(
                    Location(
                        name=location_row["name"],
                        world_name=location_row["world_name"],
                    )
                )

        for character_row in conn.execute(
            """
            SELECT id, name, world_name, location_name
            FROM character WHERE ip_id = ? ORDER BY id
            """,
            (ip_id,),
        ):
            ip.add_character(
                Character(
                    name=character_row["name"],
                    aliases=self._load_aliases(conn, character_row["id"]),
                    world_name=character_row["world_name"],
                    location_name=character_row["location_name"],
                    attributes=self._load_attributes(conn, character_row["id"]),
                )
            )

        return ip

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _upsert_ip(conn: sqlite3.Connection, name: str) -> int:
        conn.execute("INSERT INTO ip (name) VALUES (?) ON CONFLICT(name) DO NOTHING", (name,))
        row = conn.execute("SELECT id FROM ip WHERE name = ?", (name,)).fetchone()
        return int(row["id"])

    @staticmethod
    def _upsert_source(conn: sqlite3.Connection, ip_id: int, source: Source) -> None:
        conn.execute(
            """
            INSERT INTO source (ip_id, url, kind, title) VALUES (?, ?, ?, ?)
            ON CONFLICT(ip_id, url) DO UPDATE SET kind = excluded.kind,
                                                  title = excluded.title
            """,
            (ip_id, source.url, source.kind, source.title),
        )

    @staticmethod
    def _upsert_world(conn: sqlite3.Connection, ip_id: int, world: World) -> int:
        conn.execute(
            "INSERT INTO world (ip_id, name) VALUES (?, ?) ON CONFLICT(ip_id, name) DO NOTHING",
            (ip_id, world.name),
        )
        row = conn.execute(
            "SELECT id FROM world WHERE ip_id = ? AND name = ?", (ip_id, world.name)
        ).fetchone()
        return int(row["id"])

    @staticmethod
    def _upsert_location(
        conn: sqlite3.Connection, world_id: int, location: Location
    ) -> int:
        conn.execute(
            """
            INSERT INTO location (world_id, name) VALUES (?, ?)
            ON CONFLICT(world_id, name) DO NOTHING
            """,
            (world_id, location.name),
        )
        row = conn.execute(
            "SELECT id FROM location WHERE world_id = ? AND name = ?",
            (world_id, location.name),
        ).fetchone()
        return int(row["id"])

    @staticmethod
    def _upsert_character(
        conn: sqlite3.Connection, ip_id: int, character: Character
    ) -> int:
        conn.execute(
            """
            INSERT INTO character (ip_id, name, world_name, location_name)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(ip_id, name) DO UPDATE SET world_name = excluded.world_name,
                                                   location_name = excluded.location_name
            """,
            (ip_id, character.name, character.world_name, character.location_name),
        )
        row = conn.execute(
            "SELECT id FROM character WHERE ip_id = ? AND name = ?",
            (ip_id, character.name),
        ).fetchone()
        character_id = int(row["id"])

        for alias in character.aliases:
            conn.execute(
                """
                INSERT INTO alias (character_id, value) VALUES (?, ?)
                ON CONFLICT(character_id, value) DO NOTHING
                """,
                (character_id, alias),
            )
        for key, value in character.attributes:
            conn.execute(
                """
                INSERT INTO attribute (character_id, key, value) VALUES (?, ?, ?)
                ON CONFLICT(character_id, key) DO UPDATE SET value = excluded.value
                """,
                (character_id, key, value),
            )
        return character_id

    @staticmethod
    def _load_aliases(conn: sqlite3.Connection, character_id: int) -> tuple[str, ...]:
        rows = conn.execute(
            "SELECT value FROM alias WHERE character_id = ? ORDER BY value",
            (character_id,),
        ).fetchall()
        return tuple(row["value"] for row in rows)

    @staticmethod
    def _load_attributes(
        conn: sqlite3.Connection, character_id: int
    ) -> tuple[tuple[str, str], ...]:
        rows = conn.execute(
            "SELECT key, value FROM attribute WHERE character_id = ? ORDER BY id",
            (character_id,),
        ).fetchall()
        return tuple((row["key"], row["value"]) for row in rows)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Database({self.path!s})"
