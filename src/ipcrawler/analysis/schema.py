"""Layer 2 -- infer a wiki's meta structure from its mirrored pages.

Layer 3 knows *which* pages matter; it should not have to know *how* a given
wiki spells its infobox.  This module recovers that second piece of knowledge
from the HTML itself, producing a :class:`PageSchema` that describes the fields
available on a page and the values they hold.

Three infobox dialects are recognised, because between them they cover the wikis
this project targets:

``<table><tr><th>K</th><td>V</td></tr>``
    classic MediaWiki / Fandom infobox rows;
``<div class="pi-item">``
    Fandom's portable infobox (``pi-data-label`` / ``pi-data-value``);
``<dt>/<dd>``
    description lists used by several hand-rolled wikis.

Parsing uses :mod:`html.parser` from the standard library: no third-party
dependency, and no network access, which keeps CI hermetic.
"""

from __future__ import annotations

import dataclasses
import html as html_module
import re
from html.parser import HTMLParser
from typing import Iterable, Mapping, Sequence

__all__ = [
    "FieldSpec",
    "PageSchema",
    "analyse_page",
    "extract_fields",
]

_WHITESPACE = re.compile(r"\s+")
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCK_TAGS = {
    "p", "div", "li", "tr", "td", "th", "dt", "dd", "br", "table", "h1",
    "h2", "h3", "h4", "h5", "h6",
}


def _clean(text: str) -> str:
    return _WHITESPACE.sub(" ", html_module.unescape(text)).strip()


@dataclasses.dataclass(frozen=True)
class FieldSpec:
    """One recoverable field of a wiki page."""

    name: str
    examples: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("field name must not be empty")
        object.__setattr__(self, "name", self.name.strip())

    def with_example(self, value: str) -> "FieldSpec":
        value = _clean(value)
        if not value or value in self.examples:
            return self
        return dataclasses.replace(self, examples=self.examples + (value,))


@dataclasses.dataclass(frozen=True)
class PageSchema:
    """The meta structure of one wiki page (or of many, once merged)."""

    fields: tuple[FieldSpec, ...] = ()
    headings: tuple[str, ...] = ()

    def merge(self, other: "PageSchema") -> "PageSchema":
        """Union two schemas, preserving first-seen order and gathering examples."""
        fields: dict[str, FieldSpec] = {}
        for spec in (*self.fields, *other.fields):
            existing = fields.get(spec.name)
            if existing is None:
                fields[spec.name] = spec
            else:
                fields[spec.name] = dataclasses.replace(
                    existing, examples=existing.examples + spec.examples
                )

        headings: list[str] = []
        for heading in (*self.headings, *other.headings):
            if heading not in headings:
                headings.append(heading)

        return PageSchema(fields=tuple(fields.values()), headings=tuple(headings))


# --------------------------------------------------------------------- parser


class _InfoboxParser(HTMLParser):
    """Collects heading text and candidate key/value pairs.

    The parser is deliberately shallow: it tracks a small stack of open tags and
    emits a pair whenever a value-bearing tag closes while a label is pending.
    That is enough for the three dialects above and stays robust against the
    malformed markup real wikis produce.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headings: list[str] = []
        self.pairs: list[tuple[str, str]] = []

        self._tag_stack: list[tuple[str, dict[str, str]]] = []
        self._capture: str | None = None
        self._buffer: list[str] = []
        self._pending_label: str | None = None
        self._pending_label_class: str | None = None

    # ------------------------------------------------------------- helpers

    def _classes(self) -> list[str]:
        if not self._tag_stack:
            return []
        return self._tag_stack[-1][1].get("class", "").split()

    def _flush_text(self) -> str:
        text = _clean("".join(self._buffer))
        self._buffer.clear()
        return text

    # -------------------------------------------------------------- events

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = {k.lower(): (v or "") for k, v in attrs}
        classes = attributes.get("class", "").split()

        if tag in _BLOCK_TAGS:
            # A new block ends any pending label-capture.
            if self._capture is not None and tag != self._capture:
                self._capture = None
                self._buffer.clear()

        # Class-based dialects win over the tag-based ones: Fandom's portable
        # infobox labels its values with <h3 class="pi-data-label">, and the
        # class is the more specific signal.
        if "pi-data-label" in classes:
            self._capture = "label"
            self._buffer.clear()
        elif "pi-data-value" in classes:
            self._capture = "value"
            self._buffer.clear()
        elif tag in _HEADING_TAGS:
            self._capture = "heading"
            self._buffer.clear()
        elif tag == "th":
            self._capture = "label"
            self._buffer.clear()
        elif tag in ("td", "dd"):
            self._capture = "value"
            self._buffer.clear()
        elif tag == "dt":
            self._capture = "dt"
            self._buffer.clear()

        self._tag_stack.append((tag, attributes))

    def handle_data(self, data: str) -> None:
        if self._capture is not None:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        # Pop to the matching open tag, tolerating unbalanced markup.
        while self._tag_stack:
            open_tag, _ = self._tag_stack.pop()
            if open_tag == tag:
                break

        if self._capture is None:
            return

        text = self._flush_text()

        if self._capture == "heading" and tag in _HEADING_TAGS and text:
            self.headings.append(text)
        elif self._capture in ("label", "dt") and text:
            self._pending_label = text
            self._pending_label_class = self._capture
        elif self._capture == "value" and text and self._pending_label:
            self.pairs.append((self._pending_label, text))
            self._pending_label = None
            self._pending_label_class = None

        self._capture = None


# ------------------------------------------------------------------- public


def analyse_page(html: str) -> PageSchema:
    """Infer the :class:`PageSchema` of a single page."""
    parser = _InfoboxParser()
    parser.feed(html or "")
    parser.close()

    fields: dict[str, FieldSpec] = {}
    for name, value in parser.pairs:
        spec = fields.get(name, FieldSpec(name=name))
        fields[name] = spec.with_example(value)

    headings: list[str] = []
    for heading in parser.headings:
        if heading not in headings:
            headings.append(heading)

    return PageSchema(fields=tuple(fields.values()), headings=tuple(headings))


def extract_fields(html: str) -> dict[str, str]:
    """Return the first observed value for every field on a page."""
    parser = _InfoboxParser()
    parser.feed(html or "")
    parser.close()

    extracted: dict[str, str] = {}
    for name, value in parser.pairs:
        extracted.setdefault(name, value)
    return extracted


def analyse_pages(pages: Iterable[str]) -> PageSchema:
    """Merge the schemas of many pages into one wiki-level schema."""
    schema = PageSchema()
    for page in pages:
        schema = schema.merge(analyse_page(page))
    return schema
