"""Layer 3 -- the concrete games.

Layer 1 is vocabulary and layer 2 is machinery; this is the part that knows the
actual franchises listed under ``./data``.  Each one is a :class:`GameSpec`: a
slug, a display name, the wiki it is mirrored from, and the few structural hints
layer 2 needs to find character pages.

Keeping the games declarative means adding a franchise is a data edit, not a new
subclass.  :func:`build_ip` then turns a spec plus a mapping of mirrored pages
into a populated :class:`~ipcrawler.domain.IP`.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re
from typing import Iterable, Mapping

from ..analysis.schema import extract_fields
from ..domain import Character, IP, Location, Source, World

__all__ = [
    "GameSpec",
    "GAME_SPECS",
    "get_spec",
    "spec_for_slug",
    "discover_local_games",
    "build_ip",
]

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TITLE_SPLIT = re.compile(r"[^0-9A-Za-z\u00c0-\uffff]+")

# Keys that name a character rather than describe one.
_NAME_KEYS = ("Name", "name", "姓名", "名称", "Title", "title")
# Keys that carry alternative names.
_ALIAS_KEYS = ("Alias", "Aliases", "alias", "别名", "别称", "Other Names")
# Keys that place a character in the fiction.
_WORLD_KEYS = ("World", "world", "Setting", "世界观")
_LOCATION_KEYS = ("Location", "Faction", "Affiliation", "阵营", "所属", "势力")


@dataclasses.dataclass(frozen=True)
class GameSpec:
    """Everything layer 3 needs to know about one franchise."""

    slug: str
    name: str
    wiki_url: str
    character_prefix: str = "wiki/"
    world: str | None = None
    #: ``./data`` sub-directory holding this game's mirrors.
    data_dir: str | None = None

    def __post_init__(self) -> None:
        if not _SLUG.match(self.slug or ""):
            raise ValueError(
                f"slug must be lower-case kebab-case, got {self.slug!r}"
            )
        if not self.name or not self.name.strip():
            raise ValueError("name must not be empty")
        if not self.wiki_url.startswith(("http://", "https://")):
            raise ValueError(f"wiki_url must be http(s), got {self.wiki_url!r}")
        if self.data_dir is None:
            object.__setattr__(self, "data_dir", self.slug)

    @property
    def source(self) -> Source:
        """The wiki this game is mirrored from."""
        return Source(url=self.wiki_url, kind="wiki", title=f"{self.name} wiki")

    def matches_character_path(self, path: str) -> bool:
        """True when *path* (a mirrored page path) names a character page."""
        normalised = path.replace("\\", "/").lstrip("./")
        return normalised.startswith(self.character_prefix)

    def character_name_from_path(self, path: str) -> str:
        """Derive a display name from a character page path."""
        normalised = path.replace("\\", "/")
        stem = normalised.split(self.character_prefix, 1)[-1]
        for suffix in (".html", ".htm"):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
        stem = stem.replace("_", " ").strip("/")
        return stem.strip()

    def mirror_dir(self, root: str | pathlib.Path) -> pathlib.Path:
        """Where this game's mirrors live under *root*."""
        return pathlib.Path(root) / str(self.data_dir) / "main"


# ------------------------------------------------------------------ catalog

GAME_SPECS: tuple[GameSpec, ...] = (
    GameSpec(
        slug="arknights",
        name="Arknights",
        wiki_url="https://arknights.fandom.com/wiki/",
        world="Terra",
    ),
    GameSpec(
        slug="bang-dream",
        name="BanG Dream!",
        wiki_url="https://bang-dream.fandom.com/wiki/",
        world="Japan",
    ),
    GameSpec(
        slug="blue-archive",
        name="Blue Archive",
        wiki_url="https://bluearchive.fandom.com/wiki/",
        world="Kivotos",
    ),
    GameSpec(
        slug="genshin-impact",
        name="Genshin Impact",
        wiki_url="https://genshin-impact.fandom.com/wiki/",
        world="Teyvat",
    ),
    GameSpec(
        slug="harry-potter-magic-awakened",
        name="Harry Potter: Magic Awakened",
        wiki_url="https://harrypotter.fandom.com/wiki/",
        world="Wizarding World",
    ),
    GameSpec(
        slug="kantai-collection",
        name="Kantai Collection",
        wiki_url="https://kancolle.fandom.com/wiki/",
        world="Pacific",
    ),
    GameSpec(
        slug="lovelive",
        name="Love Live!",
        wiki_url="https://love-live.fandom.com/wiki/",
        world="Japan",
    ),
    GameSpec(
        slug="naruto-mobile",
        name="Naruto Mobile",
        wiki_url="https://naruto.fandom.com/wiki/",
        world="Ninja World",
    ),
    GameSpec(
        slug="personality-database-mbti",
        name="Personality Database (MBTI)",
        wiki_url="https://www.personality-database.com/",
        character_prefix="profile/",
    ),
    GameSpec(
        slug="project-seikai",
        name="Project SEKAI",
        wiki_url="https://project-sekai.fandom.com/wiki/",
        world="Shibuya",
    ),
    GameSpec(
        slug="the-fifth-persionality",
        name="The Fifth Personality",
        wiki_url="https://id5.fandom.com/wiki/",
        world="Oletus Manor",
    ),
    GameSpec(
        slug="touhou-project",
        name="Touhou Project",
        wiki_url="https://touhou.fandom.com/wiki/",
        world="Gensokyo",
    ),
)

_BY_SLUG = {spec.slug: spec for spec in GAME_SPECS}


def _slug_from_directory(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


def get_spec(slug: str) -> GameSpec:
    """The :class:`GameSpec` for *slug*.

    Raises
    ------
    KeyError
        If no game is catalogued under that slug.
    """
    try:
        return _BY_SLUG[slug]
    except KeyError:
        known = ", ".join(sorted(_BY_SLUG))
        raise KeyError(f"unknown game {slug!r}; known games: {known}") from None


def spec_for_slug(directory_name: str) -> GameSpec:
    """Resolve a ``./data`` directory name to its catalogued spec.

    ``./data`` is not perfectly kebab-case (``Harry-Potter-Magic-Awakened``),
    so directory names are normalised before lookup.
    """
    return get_spec(_slug_from_directory(directory_name))


def discover_local_games(root: str | pathlib.Path) -> tuple[pathlib.Path, ...]:
    """Game directories present under *root*, sorted by name.

    Hidden and checkpoint directories are skipped.  A missing *root* yields an
    empty tuple rather than raising, because a fresh clone has no mirrors yet.
    """
    base = pathlib.Path(root)
    if not base.is_dir():
        return ()
    found = [
        child
        for child in sorted(base.iterdir())
        if child.is_dir() and not child.name.startswith(".")
    ]
    return tuple(found)


# --------------------------------------------------------------- assembling

def build_ip(spec: GameSpec, pages: Mapping[str, str]) -> IP:
    """Build a populated :class:`~ipcrawler.domain.IP` from mirrored *pages*.

    *pages* maps a mirrored page path (for example ``"wiki/Amiya"``) to its
    HTML.  Pages that do not look like character pages are ignored; pages that
    do but carry no name field fall back to a name derived from the path, so a
    wiki with a non-standard infobox still yields characters.
    """
    ip = IP(name=spec.name)
    ip.add_source(spec.source)

    world = World(name=spec.world) if spec.world else None
    if world is not None:
        ip.add_world(world)

    for path, html in pages.items():
        if not spec.matches_character_path(path):
            continue
        character = _character_from_page(spec, path, html)
        ip.add_character(character)
        if world is not None and character.location_name:
            world.add_location(Location(name=character.location_name))

    return ip


def _character_from_page(spec: GameSpec, path: str, html: str) -> Character:
    fields = extract_fields(html or "")
    fallback = spec.character_name_from_path(path)

    name = _first_present(fields, _NAME_KEYS) or fallback
    aliases = _collect(fields, _ALIAS_KEYS, exclude=name)
    world_name = _first_present(fields, _WORLD_KEYS) or spec.world
    location_name = _first_present(fields, _LOCATION_KEYS)

    return Character(
        name=name,
        aliases=aliases,
        world_name=world_name,
        location_name=location_name,
        attributes=tuple(fields.items()),
    )


def _first_present(fields: Mapping[str, str], keys: Iterable[str]) -> str | None:
    for key in keys:
        value = fields.get(key)
        if value:
            return value
    return None


def _collect(
    fields: Mapping[str, str], keys: Iterable[str], *, exclude: str | None = None
) -> tuple[str, ...]:
    collected: list[str] = []
    for key in keys:
        raw = fields.get(key)
        if not raw:
            continue
        for part in _TITLE_SPLIT.split(raw) or []:
            part = part.strip()
            if part and part != exclude and part not in collected:
                collected.append(part)
    return tuple(collected)
