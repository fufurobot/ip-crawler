"""Layer 3 -- the concrete per-game bindings.

Layer 2 is generic machinery; layer 3 is the part that says "Arknights lives at
this wiki, its characters are under ``/wiki/``, and its infobox uses these
fields".  Everything here is data plus a thin adapter, so adding a game means
adding an entry rather than a subclass.
"""

from __future__ import annotations

import unittest

from ipcrawler.domain import Character, IP, Source
from ipcrawler.games import (
    GAME_SPECS,
    GameSpec,
    build_ip,
    discover_local_games,
    get_spec,
    spec_for_slug,
)

from .support import workspace_tmp


class GameSpecTest(unittest.TestCase):
    def test_spec_carries_a_name_and_a_wiki_source(self) -> None:
        spec = GameSpec(
            slug="demo",
            name="Demo",
            wiki_url="https://demo.test/wiki/",
        )
        self.assertEqual(spec.slug, "demo")
        self.assertEqual(spec.name, "Demo")
        self.assertEqual(spec.source.kind, "wiki")
        self.assertEqual(spec.source.url, "https://demo.test/wiki/")

    def test_rejects_a_bad_slug(self) -> None:
        with self.assertRaises(ValueError):
            GameSpec(slug="Not A Slug", name="X", wiki_url="https://x.test/")

    def test_rejects_a_non_http_wiki_url(self) -> None:
        with self.assertRaises(ValueError):
            GameSpec(slug="demo", name="Demo", wiki_url="ftp://demo.test/")

    def test_entry_paths_default_to_wiki_prefix(self) -> None:
        spec = GameSpec(slug="demo", name="Demo", wiki_url="https://demo.test/wiki/")
        self.assertEqual(spec.character_prefix, "wiki/")
        self.assertTrue(spec.matches_character_path("wiki/Amiya"))

    def test_entry_paths_can_be_overridden(self) -> None:
        spec = GameSpec(
            slug="demo",
            name="Demo",
            wiki_url="https://demo.test/",
            character_prefix="characters/",
        )
        self.assertTrue(spec.matches_character_path("characters/Amiya"))
        self.assertFalse(spec.matches_character_path("wiki/Amiya"))

    def test_specs_are_hashable(self) -> None:
        spec = GameSpec(slug="demo", name="Demo", wiki_url="https://demo.test/")
        self.assertEqual(len({spec, spec}), 1)


class CatalogTest(unittest.TestCase):
    def test_catalog_covers_every_directory_under_data(self) -> None:
        # ./data is the plan's source of truth for "which games exist".
        from .support import data_root

        on_disk = {p.name for p in data_root().iterdir() if p.is_dir()}
        on_disk.discard(".ipynb_checkpoints")
        catalogued = {spec.slug for spec in GAME_SPECS}
        # Every real data directory must be represented...
        missing = {name for name in on_disk if _slugify(name) not in catalogued}
        self.assertEqual(missing, set(), f"uncatalogued games: {sorted(missing)}")

    def test_get_spec_returns_a_known_game(self) -> None:
        spec = get_spec("arknights")
        self.assertEqual(spec.slug, "arknights")
        self.assertIn("arknights", spec.name.lower())

    def test_get_spec_rejects_an_unknown_game(self) -> None:
        with self.assertRaises(KeyError):
            get_spec("no-such-game")

    def test_spec_for_slug_normalises_directory_names(self) -> None:
        # ./data uses "Harry-Potter-Magic-Awakened" and "the-fifth-persionality".
        self.assertEqual(spec_for_slug("Harry-Potter-Magic-Awakened").slug, "harry-potter-magic-awakened")

    def test_slugs_are_unique(self) -> None:
        slugs = [spec.slug for spec in GAME_SPECS]
        self.assertEqual(len(slugs), len(set(slugs)))


class BuildIPTest(unittest.TestCase):
    def test_builds_an_ip_from_a_spec_and_pages(self) -> None:
        spec = get_spec("arknights")
        pages = {
            "wiki/Amiya": """
                <table class="infobox">
                  <tr><th>Name</th><td>Amiya</td></tr>
                  <tr><th>Class</th><td>Caster</td></tr>
                  <tr><th>Faction</th><td>Rhodes Island</td></tr>
                </table>""",
            "wiki/Kal'tsit": """
                <table class="infobox">
                  <tr><th>Name</th><td>Kal'tsit</td></tr>
                  <tr><th>Class</th><td>Medic</td></tr>
                </table>""",
            "main/index": "<h1>Arknights</h1>",
        }
        ip = build_ip(spec, pages)

        self.assertIsInstance(ip, IP)
        self.assertEqual(ip.name, spec.name)
        names = sorted(c.name for c in ip.characters)
        self.assertEqual(names, ["Amiya", "Kal'tsit"])

    def test_characters_carry_extracted_fields(self) -> None:
        spec = get_spec("arknights")
        pages = {
            "wiki/Amiya": "<table><tr><th>Name</th><td>Amiya</td></tr>"
            "<tr><th>Class</th><td>Caster</td></tr></table>"
        }
        ip = build_ip(spec, pages)
        amiya = next(c for c in ip.characters if c.name == "Amiya")
        self.assertEqual(amiya.attributes["Class"], "Caster")

    def test_non_character_pages_are_ignored(self) -> None:
        spec = get_spec("arknights")
        pages = {
            "main/index": "<h1>Arknights</h1>",
            "wiki/Amiya": "<table><tr><th>Name</th><td>Amiya</td></tr></table>",
        }
        ip = build_ip(spec, pages)
        self.assertEqual([c.name for c in ip.characters], ["Amiya"])

    def test_the_ip_owns_its_wiki_source(self) -> None:
        spec = get_spec("arknights")
        ip = build_ip(spec, {})
        self.assertIn(spec.source, ip.sources)

    def test_pages_without_a_name_fall_back_to_the_path(self) -> None:
        spec = get_spec("arknights")
        pages = {"wiki/Mystery_Unit": "<p>no infobox</p>"}
        ip = build_ip(spec, pages)
        self.assertEqual([c.name for c in ip.characters], ["Mystery Unit"])

    def test_aliases_are_harvested_when_present(self) -> None:
        spec = get_spec("arknights")
        pages = {
            "wiki/Amiya": "<table><tr><th>Name</th><td>Amiya</td></tr>"
            "<tr><th>Alias</th><td>Chimera</td></tr></table>"
        }
        ip = build_ip(spec, pages)
        amiya = next(c for c in ip.characters if c.name == "Amiya")
        self.assertIn("Chimera", amiya.aliases)


class DiscoverLocalGamesTest(unittest.TestCase):
    def test_finds_game_directories_under_a_root(self) -> None:
        root = workspace_tmp()
        (root / "arknights").mkdir()
        (root / "touhou-project").mkdir()
        (root / ".ipynb_checkpoints").mkdir()
        (root / "loose-file.txt").write_text("x", encoding="utf-8")

        found = sorted(p.name for p in discover_local_games(root))
        self.assertEqual(found, ["arknights", "touhou-project"])

    def test_missing_root_yields_nothing(self) -> None:
        self.assertEqual(list(discover_local_games(workspace_tmp() / "nope")), [])

    def test_mirror_dir_for_maps_a_game_to_its_output_path(self) -> None:
        spec = get_spec("arknights")
        self.assertEqual(
            spec.mirror_dir("some/root"),
            __import__("pathlib").Path("some/root/arknights/main"),
        )


def _slugify(name: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


if __name__ == "__main__":
    unittest.main()
