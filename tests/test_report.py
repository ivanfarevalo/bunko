"""bunko report: settings, themes, workspaces, rendering, checks, and the skill.

Run with: python3 -m unittest discover -s tests
"""

import io
import json
import os
import pathlib
import py_compile
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bunko import skills
from bunko.report import check, config, themes, workspace
from bunko.report.cli import main as report_main


class Case(unittest.TestCase):
    """A temporary home: config, runtime folder, and a working folder."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(os.path.realpath(self.tmp.name))
        env = {
            "XDG_CONFIG_HOME": str(self.dir / "config"),
            "XDG_RUNTIME_DIR": str(self.dir / "run"),
            "HOME": str(self.dir / "home"),
        }
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.dir / "home").mkdir()
        self.work = self.dir / "work"
        self.work.mkdir()
        cwd = os.getcwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, cwd)
        self.root = self.dir / "reports"

    def tearDown(self):
        self.tmp.cleanup()

    def run_report(self, *argv, ok=True):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with redirect_stdout(out), redirect_stderr(err):
            try:
                report_main(list(argv))
            except SystemExit as exit:
                code = exit.code if isinstance(exit.code, int) else 1
                if not isinstance(exit.code, int):
                    err.write(str(exit.code))
        if ok:
            self.assertEqual(code, 0, err.getvalue())
        text = out.getvalue()
        return (json.loads(text) if text.strip() else None), code, err.getvalue()

    def init(self, *extra):
        return self.run_report("init", "--root", str(self.root), *extra)[0]


class Settings(Case):
    def test_defaults_before_setup(self):
        settings = config.Settings()
        self.assertFalse(settings.configured)
        self.assertEqual(settings.root, str(self.dir / "home" / "reports"))
        self.assertEqual(sorted(settings.data["kinds"]), ["explainer", "results", "write-up"])

    def test_init_writes_every_setting(self):
        out = self.init()
        saved = json.loads(pathlib.Path(out["saved"]).read_text())
        self.assertEqual(saved, {"root": str(self.root), "layout": "simple", "theme": "house"})
        self.assertEqual(os.stat(out["saved"]).st_mode & 0o777, 0o600)
        self.assertTrue(config.Settings().configured)

    def test_project_overrides_user_and_can_remove_a_kind(self):
        self.init()
        project = self.work / ".bunko"
        project.mkdir()
        (project / "report.json").write_text(
            json.dumps({"root": "out", "kinds": {"explainer": None}})
        )
        (self.work / "deep").mkdir()
        settings = config.Settings(str(self.work / "deep"))
        self.assertEqual(
            settings.root, str(self.work / "out")
        )  # relative to the project, not the cwd
        self.assertNotIn("explainer", settings.data["kinds"])
        self.assertIn("results", settings.data["kinds"])

    def test_project_settings_are_shared_files(self):
        out, _, _ = self.run_report("config", "set", "layout", "experiment", "--project")
        self.assertEqual(out["saved"], str(self.work / ".bunko" / "report.json"))
        self.assertEqual(os.stat(out["saved"]).st_mode & 0o777, 0o644)

    def test_bad_values_are_refused(self):
        _, code, err = self.run_report("config", "set", "layout", "nope", ok=False)
        self.assertEqual(code, 1)
        self.assertIn("No layout named 'nope'", err)
        _, code, err = self.run_report("config", "set", "theme", "nope", ok=False)
        self.assertIn("No theme named 'nope'", err)


class Kinds(Case):
    def test_add_edit_remove(self):
        self.init()
        added, _, _ = self.run_report(
            "kind",
            "add",
            "status",
            "--description",
            "Weekly status",
            "--sections",
            "Done, Next",
            "--place",
            "notes",
        )
        self.assertEqual(added["kind"]["status"]["sections"], ["Done", "Next"])
        self.assertFalse(added["kind"]["status"]["builder"])
        edited, _, _ = self.run_report(
            "kind", "edit", "status", "--builder", "--guidance", "One page"
        )
        self.assertTrue(edited["kind"]["status"]["builder"])
        self.assertEqual(edited["kind"]["status"]["description"], "Weekly status")
        edited, _, _ = self.run_report("kind", "edit", "status", "--guidance", "Two pages")
        self.assertTrue(edited["kind"]["status"]["builder"])  # untouched when the flag is absent
        _, _code, err = self.run_report("kind", "add", "status", "--description", "x", ok=False)
        self.assertIn("exists", err)
        self.run_report("kind", "remove", "results")
        self.assertNotIn("results", config.Settings().data["kinds"])

    def test_add_needs_a_description(self):
        _, _code, err = self.run_report("kind", "add", "thing", ok=False)
        self.assertIn("--description", err)


class Layouts(Case):
    def test_add_and_use(self):
        self.init()
        self.run_report(
            "layout", "add", "client", "--folder", "{slug}", "--subdirs", "out", "--place", "*=out"
        )
        self.run_report("layout", "use", "client")
        result, _, _ = self.run_report("new", "write-up", "Kickoff", "--workspace", "Acme")
        self.assertEqual(result["report"], str(self.root / "acme" / "out" / "kickoff.html"))

    def test_in_use_layouts_stay(self):
        self.init()
        _, _code, err = self.run_report("layout", "remove", "simple", ok=False)
        self.assertIn("in use", err)

    def test_bad_patterns(self):
        _, _code, err = self.run_report("layout", "add", "x", "--folder", "{oops}", ok=False)
        self.assertIn("Bad folder pattern", err)
        _, _code, err = self.run_report(
            "layout", "add", "x", "--folder", "{slug}", "--place", "notes", ok=False
        )
        self.assertIn("KIND=DIR", err)


class Workspaces(Case):
    def test_simple_layout(self):
        self.init()
        result, _, _ = self.run_report(
            "new", "explainer", "How the Gate Works!", "--workspace", "Gate tuning"
        )
        self.assertTrue(result["workspace_created"])
        self.assertEqual(
            result["report"], str(self.root / "gate-tuning" / "how-the-gate-works.html")
        )
        self.assertIsNone(result["builder"])
        self.assertIsNone(result["link"])

    def test_experiment_layout_places_and_builder(self):
        self.init("--layout", "experiment")
        with mock.patch.object(
            workspace, "today", return_value=workspace.datetime.date(2026, 11, 28)
        ):
            result, _, _ = self.run_report(
                "new", "results", "Speed vs accuracy", "--workspace", "gate tuning"
            )
            notes, _, _ = self.run_report(
                "new", "write-up", "Session", "--workspace", "gate tuning"
            )
        folder = self.root / "20261128_gate-tuning"
        self.assertEqual(sorted(os.listdir(folder))[:3], ["configs", "data", "notes"])
        self.assertEqual(result["report"], str(folder / "speed-vs-accuracy.html"))
        self.assertEqual(result["builder"], str(folder / "report" / "build_speed_vs_accuracy.py"))
        py_compile.compile(result["builder"], doraise=True)
        self.assertEqual(notes["report"], str(folder / "notes" / "session.html"))
        self.assertEqual(notes["workspace"], str(folder))  # the dated folder is found again by name

    def test_existing_reports_are_never_overwritten(self):
        self.init()
        first, _, _ = self.run_report("new", "write-up", "Notes", "--workspace", "w")
        pathlib.Path(first["report"]).write_text("edited by hand")
        again, _, _ = self.run_report("new", "write-up", "Notes", "--workspace", "w")
        self.assertTrue(again["existed"])
        self.assertEqual(pathlib.Path(first["report"]).read_text(), "edited by hand")

    def test_current_workspace_from_the_working_folder(self):
        self.init()
        first, _, _ = self.run_report("new", "write-up", "Notes", "--workspace", "w")
        os.chdir(pathlib.Path(first["workspace"]))
        result, _, _ = self.run_report("new", "explainer", "More")
        self.assertEqual(result["workspace"], first["workspace"])
        os.chdir(self.work)
        _, _code, err = self.run_report("new", "explainer", "More", ok=False)
        self.assertIn("Not inside a workspace", err)

    def test_unknown_kind(self):
        self.init()
        _, _code, err = self.run_report("new", "memo", "x", "--workspace", "w", ok=False)
        self.assertIn("No report kind named 'memo'", err)

    def test_list_reads_meta_newest_first(self):
        self.init()
        a, _, _ = self.run_report("new", "write-up", "Older", "--workspace", "w")
        b, _, _ = self.run_report("new", "explainer", "Newer", "--workspace", "w")
        text = (
            pathlib.Path(b["report"])
            .read_text()
            .replace('"bunko:updated" content="', '"bunko:updated" content="9')
        )
        pathlib.Path(b["report"]).write_text(text)
        (pathlib.Path(a["workspace"]) / "plain.html").write_text("<p>not a report</p>")
        listed, _, _ = self.run_report("list", "w")
        self.assertEqual([item["title"] for item in listed["reports"]], ["Newer", "Older"])
        self.assertEqual(listed["reports"][1]["kind"], "write-up")


class Rendering(Case):
    def spec(self, **extra):
        return {
            "title": "A <b>bold</b> claim",
            "kicker": "w · results",
            "summary": "<em>Short</em>",
            "sections": [
                {"title": "One"},
                {"title": "One", "body": "<p>x</p>"},
                {"id": "own", "title": "Two"},
            ],
            "meta": {"kind": "results"},
            "provenance": {"Inputs": ["a.csv", "b.csv"], "Empty": ""},
            **extra,
        }

    def test_render(self):
        page = themes.Theme("house", config.Settings()).render(self.spec())
        self.assertIn("<title>A &lt;b&gt;bold&lt;/b&gt; claim</title>", page)
        self.assertIn("<p><em>Short</em></p>", page)  # summary and bodies are HTML
        for anchor in ('id="one"', 'id="one-2"', 'id="own"', 'href="#one-2"'):
            self.assertIn(anchor, page)
        self.assertIn('<meta name="bunko:kind" content="results">', page)
        self.assertIn("<dt>Inputs</dt><dd><code>a.csv</code><br><code>b.csv</code></dd>", page)
        self.assertNotIn("Empty", page)
        self.assertNotIn("{{", page)
        self.assertLess(
            page.index("<script>"), page.index("fonts.googleapis.com")
        )  # before the fonts link

    def test_render_command_keeps_the_created_date(self):
        output = self.dir / "page.html"
        spec = self.dir / "spec.json"
        spec.write_text(json.dumps(self.spec(meta={"kind": "results", "created": "2020-01-01"})))
        self.run_report("render", str(spec), "-o", str(output))
        spec.write_text(json.dumps(self.spec()))
        self.run_report("render", str(spec), "-o", str(output))
        meta = workspace.read_meta(str(output))
        self.assertEqual(meta["created"], "2020-01-01")
        self.assertEqual(meta["updated"], workspace.today().isoformat())

    def test_user_theme_overrides_files_and_falls_back(self):
        self.run_report("theme", "new", "mine")
        folder = self.dir / "config" / "bunko" / "themes" / "mine"
        (folder / "style.css").write_text("body{color:red}")
        (folder / "provenance.html").unlink()
        page = themes.Theme("mine", config.Settings()).render(self.spec())
        self.assertIn("body{color:red}", page)
        self.assertIn('<details class="provenance">', page)  # from the house theme
        listed, _, _ = self.run_report("theme", "list")
        self.assertEqual(listed["themes"], ["house", "mine"])
        _, _code, err = self.run_report("theme", "new", "mine", ok=False)
        self.assertIn("already exists", err)


class Checks(Case):
    def new_report(self):
        self.init()
        result, _, _ = self.run_report("new", "explainer", "Guide", "--workspace", "w")
        return pathlib.Path(result["report"])

    def test_a_new_report_is_clean(self):
        report = self.new_report()
        result, _code, _ = self.run_report("check", str(report))
        self.assertEqual((result["errors"], result["warnings"]), (0, 0))

    def test_problems_are_found_and_contents_fixed(self):
        report = self.new_report()
        (report.parent / "img").mkdir()
        (report.parent / "img" / "ok.png").write_bytes(b"x")
        extra = (
            '<section class="lesson" id="extra"><h2>Extra &amp; more</h2>'
            '<img src="img/ok.png"><img src="img/missing.png"><a href="#nowhere">x</a>'
            '<img src="/home/me/a.png"><script src="https://cdn.example.com/x.js"></script></section>\n'
        )
        report.write_text(
            report.read_text().replace(
                "<!-- bunko:provenance -->", extra + "<!-- bunko:provenance -->"
            )
        )
        result, code, _ = self.run_report("check", str(report), ok=False)
        self.assertEqual(code, 1)
        messages = " | ".join(problem["message"] for problem in result["problems"])
        for expected in (
            "missing from the contents",
            "#nowhere",
            "missing.png",
            "Absolute path",
            "from the network",
        ):
            self.assertIn(expected, messages)
        self.assertNotIn("ok.png", messages)
        fixed, code, _ = self.run_report("check", "--fix", str(report), ok=False)
        self.assertTrue(fixed["contents_rebuilt"])
        self.assertNotIn("missing from the contents", json.dumps(fixed))
        self.assertIn('<span class="num">04</span>Extra &amp; more</a>', report.read_text())

    def test_pages_without_markers_and_basics(self):
        page = self.dir / "bare.html"
        page.write_text("<p>hi</p>")
        problems = check.check(str(page))
        self.assertEqual({problem["level"] for problem in problems}, {"error", "warning"})
        self.assertFalse(check.fix(str(page), themes.Theme("house", config.Settings())))


class Skill(Case):
    def test_install_for_each_agent(self):
        with mock.patch.dict(
            os.environ,
            {"CLAUDE_CONFIG_DIR": str(self.dir / "claude"), "CODEX_HOME": str(self.dir / "codex")},
        ):
            first = skills.install()
            again = skills.install()
        self.assertEqual([item["status"] for item in first], ["installed", "installed"])
        self.assertEqual([item["status"] for item in again], ["unchanged", "unchanged"])
        claude = (self.dir / "claude" / "skills" / "report" / "SKILL.md").read_text()
        codex = (self.dir / "codex" / "prompts" / "report.md").read_text()
        self.assertTrue(claude.startswith("---\nname: report\ndescription: "))
        self.assertTrue(codex.startswith("---\ndescription: "))
        self.assertNotIn("name: report", codex)
        self.assertIn("bunko report new", codex)


if __name__ == "__main__":
    unittest.main()
