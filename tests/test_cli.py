"""The ``ip-crawler`` command line -- the one place all three layers meet."""

from __future__ import annotations

import pathlib
import unittest

from ipcrawler.cli import build_parser, main, run_mirror

from .support import workspace_tmp


class ParserTest(unittest.TestCase):
    def test_parses_the_mirror_subcommand(self) -> None:
        args = build_parser().parse_args(["mirror", "arknights"])
        self.assertEqual(args.command, "mirror")
        self.assertEqual(args.game, ["arknights"])

    def test_mirror_accepts_several_games(self) -> None:
        args = build_parser().parse_args(["mirror", "arknights", "touhou-project"])
        self.assertEqual(args.game, ["arknights", "touhou-project"])

    def test_lists_games(self) -> None:
        args = build_parser().parse_args(["games"])
        self.assertEqual(args.command, "games")

    def test_analyse_subcommand_takes_a_directory(self) -> None:
        args = build_parser().parse_args(["analyse", "data/arknights/main"])
        self.assertEqual(args.command, "analyse")
        self.assertEqual(args.directory, "data/arknights/main")

    def test_build_db_subcommand(self) -> None:
        args = build_parser().parse_args(["build-db"])
        self.assertEqual(args.command, "build-db")

    def test_serve_subcommand(self) -> None:
        args = build_parser().parse_args(["serve", "data/arknights/main"])
        self.assertEqual(args.command, "serve")

    def test_codegen_subcommand_records_a_script(self) -> None:
        args = build_parser().parse_args(["codegen", "http://127.0.0.1:1/"])
        self.assertEqual(args.command, "codegen")
        self.assertTrue(args.output.endswith(".py"))

    def test_no_arguments_exits_with_usage(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args([])

    def test_games_lists_every_catalogued_game(self) -> None:
        import io
        from contextlib import redirect_stdout

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["games"])
        self.assertEqual(code, 0)
        self.assertIn("arknights", buffer.getvalue())


class RunMirrorTest(unittest.TestCase):
    def test_dry_run_does_not_touch_the_network(self) -> None:
        calls: list[object] = []

        class Crawler:
            def fetch(self, source):
                calls.append(source)
                return "<html></html>"

            def fetch_all(self, sources):
                calls.extend(sources)
                return {s.url: "<html></html>" for s in sources}

        root = workspace_tmp()
        plan = run_mirror(
            ["arknights"],
            data_root=root,
            crawler_factory=lambda spec: Crawler(),
            dry_run=True,
        )

        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0].spec.slug, "arknights")
        self.assertEqual(calls, [], "dry run must not invoke the crawler")

    def test_dry_run_reports_the_target_directory(self) -> None:
        root = workspace_tmp()
        plan = run_mirror(
            ["arknights"],
            data_root=root,
            crawler_factory=lambda spec: None,
            dry_run=True,
        )
        self.assertEqual(plan[0].directory, root / "arknights" / "main")

    def test_unknown_game_raises(self) -> None:
        with self.assertRaises(KeyError):
            run_mirror(["nope"], data_root=workspace_tmp(), dry_run=True)


class AnalyseDirectoryTest(unittest.TestCase):
    def test_reads_html_files_and_reports_a_schema(self) -> None:
        from ipcrawler.cli import analyse_directory

        root = workspace_tmp()
        (root / "Amiya.html").write_text(
            "<table><tr><th>Class</th><td>Caster</td></tr></table>", encoding="utf-8"
        )
        result = analyse_directory(root)

        self.assertEqual(result.page_count, 1)
        self.assertIn("Class", [f.name for f in result.schema.fields])

    def test_empty_directory_is_not_an_error(self) -> None:
        from ipcrawler.cli import analyse_directory

        result = analyse_directory(workspace_tmp())
        self.assertEqual(result.page_count, 0)

    def test_missing_directory_raises(self) -> None:
        from ipcrawler.cli import analyse_directory

        with self.assertRaises(NotADirectoryError):
            analyse_directory(workspace_tmp() / "nope")

    def test_build_ip_from_a_directory(self) -> None:
        from ipcrawler.cli import build_ip_from_directory

        root = workspace_tmp()
        (root / "wiki").mkdir()
        (root / "wiki" / "Amiya.html").write_text(
            "<table><tr><th>Name</th><td>Amiya</td></tr></table>", encoding="utf-8"
        )
        ip = build_ip_from_directory("arknights", root)
        self.assertEqual([c.name for c in ip.characters], ["Amiya"])


if __name__ == "__main__":
    unittest.main()
