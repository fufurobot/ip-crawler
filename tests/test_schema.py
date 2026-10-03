"""Layer 2 -- infer a wiki's meta structure from its mirrored pages.

"Meta structure" is the answer to: *given this wiki, how do I get from a page to
the fields of a character?*  Rather than hard-coding per-wiki selectors, layer 2
infers a reusable :class:`PageSchema`: which elements repeat, which of them look
like infobox key/value rows, and which look like navigation to other pages.

Layer 3 then only has to say "this wiki's characters live under /wiki/".
"""

from __future__ import annotations

import unittest

from ipcrawler.analysis.schema import (
    FieldSpec,
    PageSchema,
    analyse_page,
    extract_fields,
)

INFOBOX_HTML = """
<html><body>
  <table class="infobox">
    <tr><th>Name</th><td>Amiya</td></tr>
    <tr><th>Class</th><td>Caster</td></tr>
    <tr><th>Faction</th><td>Rhodes Island</td></tr>
  </table>
  <p>Amiya is a Caster.</p>
</body></html>
"""

PLAIN_HTML = """
<html><body>
  <h1>Some page</h1>
  <p>No infobox here.</p>
</body></html>
"""


class AnalysePageTest(unittest.TestCase):
    def test_detects_infobox_field_names(self) -> None:
        schema = analyse_page(INFOBOX_HTML)
        self.assertIsInstance(schema, PageSchema)
        self.assertEqual(
            [field.name for field in schema.fields],
            ["Name", "Class", "Faction"],
        )

    def test_field_names_are_deduplicated_and_ordered(self) -> None:
        html = """
        <table><tr><th>Name</th><td>A</td></tr>
        <tr><th>Name</th><td>B</td></tr></table>
        """
        schema = analyse_page(html)
        self.assertEqual([f.name for f in schema.fields], ["Name"])

    def test_page_without_tables_has_no_fields(self) -> None:
        schema = analyse_page(PLAIN_HTML)
        self.assertEqual(schema.fields, ())

    def test_records_heading_structure(self) -> None:
        schema = analyse_page(PLAIN_HTML)
        self.assertIn("Some page", schema.headings)

    def test_empty_html_is_not_an_error(self) -> None:
        schema = analyse_page("")
        self.assertEqual(schema.fields, ())
        self.assertEqual(schema.headings, ())

    def test_schema_is_hashable_and_comparable(self) -> None:
        a = analyse_page(INFOBOX_HTML)
        b = analyse_page(INFOBOX_HTML)
        self.assertEqual(a, b)
        self.assertEqual(len({a, b}), 1)


class ExtractFieldsTest(unittest.TestCase):
    def test_extracts_values_for_the_detected_fields(self) -> None:
        fields = extract_fields(INFOBOX_HTML)
        self.assertEqual(fields["Name"], "Amiya")
        self.assertEqual(fields["Class"], "Caster")
        self.assertEqual(fields["Faction"], "Rhodes Island")

    def test_missing_table_yields_an_empty_mapping(self) -> None:
        self.assertEqual(extract_fields(PLAIN_HTML), {})

    def test_whitespace_is_normalised(self) -> None:
        html = "<table><tr><th>  Name </th><td>\n  Amiya  \n</td></tr></table>"
        self.assertEqual(extract_fields(html)["Name"], "Amiya")

    def test_class_plus_content_layout_is_understood(self) -> None:
        # MediaWiki's modern infobox emits <div class="pi-item"> rows.
        html = """
        <div class="pi-item"><h3 class="pi-data-label">Rarity</h3>
          <div class="pi-data-value">6</div></div>
        """
        self.assertEqual(extract_fields(html)["Rarity"], "6")


class FieldSpecTest(unittest.TestCase):
    def test_field_spec_carries_a_name_and_optional_examples(self) -> None:
        spec = FieldSpec(name="Class", examples=("Caster", "Medic"))
        self.assertEqual(spec.name, "Class")
        self.assertEqual(spec.examples, ("Caster", "Medic"))

    def test_rejects_empty_name(self) -> None:
        with self.assertRaises(ValueError):
            FieldSpec(name="  ")


class SchemaMergeTest(unittest.TestCase):
    def test_merging_unions_field_names(self) -> None:
        a = analyse_page(INFOBOX_HTML)
        b = analyse_page("<table><tr><th>Rarity</th><td>6</td></tr></table>")
        merged = a.merge(b)
        self.assertEqual(
            [f.name for f in merged.fields], ["Name", "Class", "Faction", "Rarity"]
        )

    def test_merging_collects_examples(self) -> None:
        a = analyse_page(INFOBOX_HTML)
        b = analyse_page("<table><tr><th>Name</th><td>Kal'tsit</td></tr></table>")
        merged = a.merge(b)
        name = next(f for f in merged.fields if f.name == "Name")
        self.assertIn("Kal'tsit", name.examples)


if __name__ == "__main__":
    unittest.main()
