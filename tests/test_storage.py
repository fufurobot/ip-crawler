"""Storage -- fill one sqlite database from any layer.

The plan ends with "fill in the database with a single sqlite", so the schema
below is the project's final output format: IPs, worlds, locations, characters,
their aliases, their attributes, and the sources they were learned from.
"""

from __future__ import annotations

import sqlite3
import unittest

from ipcrawler.domain import Character, IP, Location, Source, World
from ipcrawler.storage import Database

from .support import workspace_tmp


def sample_ip() -> IP:
    ip = IP(name="Arknights")
    ip.add_source(Source(url="https://arknights.fandom.com/wiki/", kind="wiki"))
    terra = ip.add_world(World(name="Terra"))
    terra.add_location(Location(name="Rhodes Island"))
    ip.add_character(
        Character(
            name="Amiya",
            aliases=("Chimera",),
            world_name="Terra",
            location_name="Rhodes Island",
            attributes=(("Class", "Caster"), ("Rarity", "6")),
        )
    )
    ip.add_character(Character(name="Kal'tsit", world_name="Terra"))
    return ip


class DatabaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = workspace_tmp()
        self.path = self.root / "ipcrawler.sqlite3"

    def test_creates_the_schema_on_open(self) -> None:
        with Database(self.path) as db:
            tables = {
                row[0]
                for row in db.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertTrue(
            {"ip", "world", "location", "character", "alias", "attribute", "source"}
            <= tables
        )

    def test_creates_the_parent_directory(self) -> None:
        nested = self.root / "deep" / "nested" / "db.sqlite3"
        with Database(nested):
            pass
        self.assertTrue(nested.exists())

    def test_schema_creation_is_idempotent(self) -> None:
        with Database(self.path) as db:
            db.save(sample_ip())
        with Database(self.path) as db:
            db.save(sample_ip())
            self.assertEqual(db.count("character"), 2)

    def test_save_persists_the_ip(self) -> None:
        with Database(self.path) as db:
            db.save(sample_ip())
        with Database(self.path) as db:
            self.assertEqual(db.count("ip"), 1)
            self.assertEqual(db.count("world"), 1)
            self.assertEqual(db.count("location"), 1)
            self.assertEqual(db.count("character"), 2)
            self.assertEqual(db.count("alias"), 1)
            self.assertEqual(db.count("attribute"), 2)
            self.assertEqual(db.count("source"), 1)

    def test_saving_the_same_ip_twice_does_not_duplicate(self) -> None:
        with Database(self.path) as db:
            db.save(sample_ip())
            db.save(sample_ip())
            self.assertEqual(db.count("character"), 2)
            self.assertEqual(db.count("alias"), 1)

    def test_load_round_trips_characters(self) -> None:
        with Database(self.path) as db:
            db.save(sample_ip())
        with Database(self.path) as db:
            ip = db.load_ip("Arknights")

        self.assertEqual(ip.name, "Arknights")
        names = sorted(c.name for c in ip.characters)
        self.assertEqual(names, ["Amiya", "Kal'tsit"])

    def test_load_round_trips_attributes_and_aliases(self) -> None:
        with Database(self.path) as db:
            db.save(sample_ip())
        with Database(self.path) as db:
            ip = db.load_ip("Arknights")

        amiya = next(c for c in ip.characters if c.name == "Amiya")
        self.assertEqual(amiya.attribute("Class"), "Caster")
        self.assertEqual(amiya.aliases, ("Chimera",))
        self.assertEqual(amiya.world_name, "Terra")
        self.assertEqual(amiya.location_name, "Rhodes Island")

    def test_load_round_trips_worlds_and_sources(self) -> None:
        with Database(self.path) as db:
            db.save(sample_ip())
        with Database(self.path) as db:
            ip = db.load_ip("Arknights")

        self.assertEqual([w.name for w in ip.worlds], ["Terra"])
        self.assertEqual(
            [s.url for s in ip.sources], ["https://arknights.fandom.com/wiki/"]
        )

    def test_load_unknown_ip_raises(self) -> None:
        with Database(self.path) as db:
            with self.assertRaises(KeyError):
                db.load_ip("Nothing")

    def test_list_ips(self) -> None:
        with Database(self.path) as db:
            db.save(sample_ip())
            self.assertEqual(db.list_ips(), ["Arknights"])

    def test_count_rejects_an_unknown_table(self) -> None:
        with Database(self.path) as db:
            with self.assertRaises(ValueError):
                db.count("not_a_table")

    def test_save_many_ips(self) -> None:
        other = IP(name="Touhou Project")
        other.add_character(Character(name="Reimu Hakurei"))
        with Database(self.path) as db:
            db.save_many([sample_ip(), other])
            self.assertEqual(db.count("ip"), 2)
            self.assertEqual(db.list_ips(), ["Arknights", "Touhou Project"])

    def test_rejects_a_directory_path(self) -> None:
        with self.assertRaises(IsADirectoryError):
            Database(self.root)

    def test_reopening_after_close_works(self) -> None:
        db = Database(self.path)
        db.open()
        db.save(sample_ip())
        db.close()
        db.open()
        self.assertEqual(db.count("ip"), 1)
        db.close()


if __name__ == "__main__":
    unittest.main()
