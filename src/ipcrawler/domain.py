"""Layer 1 -- the abstract vocabulary of the domain.

Nothing in this module knows about HTTP, sqlite or any particular game.  These
are the nouns the whole project speaks in:

``Crawler``
    *how* bytes are obtained (see :mod:`ipcrawler.crawler` for the concrete
    :class:`~ipcrawler.crawler.wget.WgetMPXCrawler`).
``Source``
    *where* bytes come from -- one wiki, one API, one dump.
``IP``
    A franchise (Arknights, Touhou Project, ...).  It groups worlds and
    characters and owns the sources used to learn about them.
``World``
    A fictional setting inside an IP (Terra, Gensokyo, ...), which contains
    locations.
``Location``
    A place inside a world (Rhodes Island, Hakurei Shrine, ...).
``Character``
    A virtual persona, optionally tied to a world and a location.

All value objects are frozen dataclasses: equality is structural and they are
hashable, so they can be put in sets and used as dict keys while the graph is
being assembled.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Tuple
from urllib.parse import urlsplit

__all__ = [
    "Crawler",
    "Source",
    "Location",
    "World",
    "Character",
    "IP",
]


def _require_text(value: str, field_name: str) -> str:
    """Return *value* stripped, raising ``ValueError`` when it is blank."""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string, got {type(value).__name__}")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must not be empty")
    return stripped


@dataclass(frozen=True)
class Source:
    """Where a crawler gets its bytes from.

    ``kind`` is a free-form label (``"wiki"``, ``"api"``, ``"dump"``, ...) so
    layer 3 can tag sources without layer 1 having to enumerate every
    possibility.
    """

    url: str
    kind: str
    title: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "url", _require_text(self.url, "url"))
        object.__setattr__(self, "kind", _require_text(self.kind, "kind"))
        if self.title is not None:
            object.__setattr__(self, "title", _require_text(self.title, "title"))

    @property
    def host(self) -> str:
        """The bare host of :attr:`url`, without scheme, path or query."""
        return urlsplit(self.url).netloc


@dataclass(frozen=True)
class Location:
    """A place inside a :class:`World`."""

    name: str
    world_name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_text(self.name, "name"))
        if self.world_name is not None:
            object.__setattr__(
                self, "world_name", _require_text(self.world_name, "world_name")
            )


@dataclass(frozen=True)
class Character:
    """A virtual persona.

    ``aliases`` is normalised on construction: stripped, de-duplicated and
    sorted, so two characters built from the same messy wiki data compare
    equal.

    ``attributes`` holds the raw key/value pairs recovered from the character's
    wiki page (class, rarity, faction, ...).  It is kept as a frozen
    ``tuple``-backed mapping so a character stays hashable.
    """

    name: str
    aliases: Tuple[str, ...] = ()
    world_name: str | None = None
    location_name: str | None = None
    attributes: Tuple[Tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_text(self.name, "name"))
        object.__setattr__(self, "aliases", _normalise_aliases(self.aliases))
        for attr in ("world_name", "location_name"):
            value = getattr(self, attr)
            if value is not None:
                object.__setattr__(self, attr, _require_text(value, attr))
        object.__setattr__(self, "attributes", _normalise_attributes(self.attributes))

    def attribute(self, key: str) -> str | None:
        """The value recorded for *key*, or ``None``."""
        return dict(self.attributes).get(key)


def _normalise_attributes(
    attributes: Iterable[tuple[str, str]] | Mapping[str, str],
) -> Tuple[Tuple[str, str], ...]:
    items = attributes.items() if isinstance(attributes, Mapping) else attributes
    normalised: dict[str, str] = {}
    for key, value in items:
        normalised[_require_text(key, "attribute key")] = _require_text(
            value, "attribute value"
        )
    return tuple(normalised.items())


def _normalise_aliases(aliases: Iterable[str]) -> Tuple[str, ...]:
    cleaned = {_require_text(alias, "alias") for alias in aliases}
    return tuple(sorted(cleaned))


@dataclass
class World:
    """A fictional setting, holding a set of unique :class:`Location`."""

    name: str
    _locations: dict[str, Location] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.name = _require_text(self.name, "name")

    def add_location(self, location: Location) -> Location:
        """Register *location* under this world; idempotent by name."""
        if location.world_name is None:
            location = Location(name=location.name, world_name=self.name)
        self._locations[location.name] = location
        return location

    @property
    def locations(self) -> Tuple[Location, ...]:
        """Locations in insertion order, as an immutable tuple."""
        return tuple(self._locations.values())


@dataclass
class IP:
    """A franchise: the root aggregate of the domain."""

    name: str
    _worlds: dict[str, World] = field(default_factory=dict, repr=False)
    _characters: dict[str, Character] = field(default_factory=dict, repr=False)
    _sources: dict[Source, None] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.name = _require_text(self.name, "name")

    def add_world(self, world: World) -> World:
        self._worlds[world.name] = world
        return world

    def add_character(self, character: Character) -> Character:
        self._characters[character.name] = character
        return character

    def add_source(self, source: Source) -> Source:
        self._sources[source] = None
        return source

    @property
    def worlds(self) -> Tuple[World, ...]:
        return tuple(self._worlds.values())

    @property
    def characters(self) -> Tuple[Character, ...]:
        return tuple(self._characters.values())

    @property
    def sources(self) -> Tuple[Source, ...]:
        return tuple(self._sources)


class Crawler(abc.ABC):
    """Abstract byte source.

    A crawler's only obligation is :meth:`fetch`.  Everything else -- caching,
    mirroring, rate limiting -- is a capability subclasses may add.
    """

    @abc.abstractmethod
    def fetch(self, source: Source) -> str:
        """Return the body of *source* as text."""

    def fetch_all(self, sources: Iterable[Source]) -> dict[str, str]:
        """Fetch many sources, keyed by URL.

        The default implementation is sequential; concurrent crawlers
        (e.g. :class:`~ipcrawler.crawler.wget.WgetMPXCrawler`) override it.
        """
        return {source.url: self.fetch(source) for source in sources}
