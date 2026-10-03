"""Layer 1 -- the abstract domain vocabulary.

These tests are written first (TDD): they pin down the behaviour of the
``Crawler`` / ``IP`` / ``Character`` / ``World`` / ``Location`` / ``Source``
abstractions before any implementation exists.
"""

from __future__ import annotations

import unittest

from ipcrawler.domain import (
    Character,
    Crawler,
    IP,
    Location,
    Source,
    World,
)


class SourceTest(unittest.TestCase):
    def test_requires_a_url_and_kind(self) -> None:
        source = Source(url="https://example.test/wiki", kind="wiki")
        self.assertEqual(source.url, "https://example.test/wiki")
        self.assertEqual(source.kind, "wiki")

    def test_rejects_empty_url(self) -> None:
        with self.assertRaises(ValueError):
            Source(url="", kind="wiki")

    def test_rejects_blank_kind(self) -> None:
        with self.assertRaises(ValueError):
            Source(url="https://example.test", kind="   ")

    def test_host_property_strips_scheme_and_path(self) -> None:
        source = Source(url="https://example.test/wiki/Main_Page?x=1", kind="wiki")
        self.assertEqual(source.host, "example.test")

    def test_equality_is_structural(self) -> None:
        a = Source(url="https://example.test", kind="wiki")
        b = Source(url="https://example.test", kind="wiki")
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))

    def test_is_hashable_so_it_can_join_sets(self) -> None:
        sources = {
            Source(url="https://a.test", kind="wiki"),
            Source(url="https://a.test", kind="wiki"),
            Source(url="https://b.test", kind="wiki"),
        }
        self.assertEqual(len(sources), 2)


class LocationTest(unittest.TestCase):
    def test_minimal_location(self) -> None:
        loc = Location(name="Rhodes Island")
        self.assertEqual(loc.name, "Rhodes Island")
        self.assertIsNone(loc.world_name)

    def test_rejects_empty_name(self) -> None:
        with self.assertRaises(ValueError):
            Location(name="")

    def test_is_hashable(self) -> None:
        self.assertEqual(len({Location(name="A"), Location(name="A")}), 1)


class WorldTest(unittest.TestCase):
    def test_world_holds_locations(self) -> None:
        terra = World(name="Terra")
        terra.add_location(Location(name="Rhodes Island"))
        self.assertEqual([loc.name for loc in terra.locations], ["Rhodes Island"])

    def test_adding_the_same_location_twice_is_idempotent(self) -> None:
        terra = World(name="Terra")
        terra.add_location(Location(name="Rhodes Island"))
        terra.add_location(Location(name="Rhodes Island"))
        self.assertEqual(len(terra.locations), 1)

    def test_locations_are_read_only_from_outside(self) -> None:
        terra = World(name="Terra")
        terra.add_location(Location(name="Rhodes Island"))
        # ``locations`` is a tuple: no in-place mutation is possible.
        self.assertIsInstance(terra.locations, tuple)
        with self.assertRaises(AttributeError):
            terra.locations.append(Location(name="Nope"))  # type: ignore[attr-defined]


class CharacterTest(unittest.TestCase):
    def test_minimal_character(self) -> None:
        amiya = Character(name="Amiya")
        self.assertEqual(amiya.name, "Amiya")
        self.assertEqual(amiya.aliases, ())
        self.assertIsNone(amiya.world_name)
        self.assertIsNone(amiya.location_name)

    def test_rejects_empty_name(self) -> None:
        with self.assertRaises(ValueError):
            Character(name="  ")

    def test_alias_set_is_normalised_sorted_and_deduplicated(self) -> None:
        amiya = Character(name="Amiya", aliases=("Chimera", "Amiya", "chimera"))
        self.assertEqual(amiya.aliases, ("Amiya", "Chimera", "chimera"))

    def test_character_is_hashable_by_name(self) -> None:
        self.assertEqual(len({Character(name="Amiya"), Character(name="Amiya")}), 1)


class IPTest(unittest.TestCase):
    def test_ip_groups_worlds_and_characters(self) -> None:
        arknights = IP(name="Arknights")
        arknights.add_world(World(name="Terra"))
        arknights.add_character(Character(name="Amiya"))
        self.assertEqual([w.name for w in arknights.worlds], ["Terra"])
        self.assertEqual([c.name for c in arknights.characters], ["Amiya"])

    def test_rejects_empty_name(self) -> None:
        with self.assertRaises(ValueError):
            IP(name="")

    def test_worlds_and_characters_are_read_only_from_outside(self) -> None:
        arknights = IP(name="Arknights")
        self.assertIsInstance(arknights.worlds, tuple)
        self.assertIsInstance(arknights.characters, tuple)
        with self.assertRaises(AttributeError):
            arknights.worlds.append(World(name="Nope"))  # type: ignore[attr-defined]


class CrawlerTest(unittest.TestCase):
    def test_crawler_is_abstract(self) -> None:
        with self.assertRaises(TypeError):
            Crawler()  # type: ignore[abstract]

    def test_subclass_must_implement_fetch(self) -> None:
        class Incomplete(Crawler):
            pass

        with self.assertRaises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_a_complete_subclass_is_usable(self) -> None:
        class Dummy(Crawler):
            def fetch(self, source: Source) -> str:
                return f"<html>{source.url}</html>"

        source = Source(url="https://example.test", kind="wiki")
        self.assertEqual(Dummy().fetch(source), "<html>https://example.test</html>")


if __name__ == "__main__":
    unittest.main()
