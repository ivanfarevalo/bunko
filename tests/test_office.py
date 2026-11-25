"""Word and Excel files: conversion, the HTTP endpoints, and damaged or hostile files.

Run with: python3 -m unittest discover -s tests
"""
import json
import os
import pathlib
import sys
import tempfile
import unittest
import warnings
import zipfile
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import office_samples as make  # noqa: E402
from office_samples import cell, grid, p, r, table  # noqa: E402
from shelf import office  # noqa: E402
from shelf.office import Office, OfficeError  # noqa: E402
from test_features import Running  # noqa: E402


class Folder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def docx(self, body, **kw):
        path = self.dir / "doc.docx"
        make.write_docx(path, body, **kw)
        return office.docx_page(str(path))["html"]

    def xlsx(self, sheets, sheet=None, **kw):
        path = self.dir / "book.xlsx"
        make.write_xlsx(path, sheets, **kw)
        return office.xlsx_sheet(str(path), sheet)


class Word(Folder):
    def test_headings_from_styles_and_outline_levels(self):
        html = self.docx(p("Report", "Title") + p("One", "Heading1") + p("Two", "Heading2") + p("Body"))
        self.assertIn("<h1>Report</h1><h1>One</h1><h2>Two</h2><p>Body</p>", html)

    def test_numbered_heading_style_shows_its_number(self):
        html = self.docx(p("Scope", "NumberedHeading") + p("Method", "NumberedHeading"))
        self.assertIn("<h1>1. Scope</h1><h1>2. Method</h1>", html)

    def test_run_formatting(self):
        html = self.docx(p(runs=r("bold", "b") + r("off", 'b w:val="0"') + r("it", "i") + r("u", "u w:val=\"single\"")
                           + r("gone", "strike") + r("2", 'vertAlign w:val="superscript"') + r("x()", font="Consolas")))
        self.assertIn("<strong>bold</strong>off<em>it</em><u>u</u><s>gone</s><sup>2</sup><code>x()</code>", html)

    def test_hidden_text_and_deleted_revisions_are_left_out(self):
        html = self.docx(p(runs=r("kept") + r("secret", "vanish")
                           + "<w:del><w:r><w:delText>removed</w:delText></w:r></w:del>"
                           + "<w:ins>" + r(" added") + "</w:ins>"))
        self.assertIn("<p>kept added</p>", html)
        self.assertNotIn("secret", html)
        self.assertNotIn("removed", html)

    def test_text_is_escaped(self):
        html = self.docx(p("<img src=x onerror=alert(1)> & more"))
        self.assertIn("&lt;img src=x onerror=alert(1)&gt; &amp; more", html)
        self.assertNotIn("<img", html)

    def test_nested_and_mixed_lists(self):
        html = self.docx(p("a", num=("1", 0)) + p("a1", num=("1", 1)) + p("b", num=("1", 0))
                         + p("between") + p("first", num=("2", 0)) + p("sub", num=("2", 1)))
        self.assertIn("<ul><li>a<ul><li>a1</li></ul></li><li>b</li></ul><p>between</p>"
                      '<ol><li>first<ol type="a"><li>sub</li></ol></li></ol>', html)

    def test_numbering_continues_after_an_interruption(self):
        html = self.docx(p("one", num=("2", 0)) + p("two", num=("2", 0)) + p("note") + p("three", num=("2", 0)))
        self.assertIn('<p>note</p><ol start="3"><li>three</li></ol>', html)

    def test_list_style_without_direct_numbering(self):
        html = self.docx(p("from the style", "ListBullet"))
        self.assertIn("<ul><li>from the style</li></ul>", html)

    def test_lists_sharing_a_definition_keep_counting(self):
        # LibreOffice writes one list as separate numIds over one definition.
        html = self.docx(p("a", num=("6", 0)) + p("b", num=("5", 0)) + p("c", num=("5", 0)))
        self.assertIn("<ol><li>a</li><li>b</li><li>c</li></ol>", html)

    def test_start_override_restarts_a_list(self):
        html = self.docx(p("a", num=("5", 0)) + p("b", num=("5", 0)) + p("gap") + p("again", num=("6", 0)))
        self.assertIn("<p>gap</p><ol><li>again</li></ol>", html)

    def test_code_paragraphs_become_one_block(self):
        html = self.docx(p("Before") + p("def f():", "SourceCode")
                         + p(runs='<w:r><w:tab/><w:t>return 1 &lt; 2</w:t></w:r>', style="SourceCode")
                         + p("", "SourceCode") + p("f()", "SourceCode") + p("", "SourceCode") + p("After"))
        self.assertIn("<p>Before</p><pre><code>def f():\n\treturn 1 &lt; 2\n\nf()</code></pre><p>After</p>", html)

    def test_line_breaks_inside_a_code_paragraph(self):
        html = self.docx(p(runs='<w:r><w:t>a = 1</w:t><w:br/><w:t xml:space="preserve">    b = 2</w:t></w:r>',
                           style="SourceCode"))
        self.assertIn("<pre><code>a = 1\n    b = 2</code></pre>", html)

    def test_character_styles(self):
        html = self.docx(p(runs=r("x", 'rStyle w:val="VerbatimChar"') + r(" and ") + r("y", 'rStyle w:val="Strong"')
                           + r("z", 'rStyle w:val="Strong"', 'b w:val="0"')))
        self.assertIn("<code>x</code> and <strong>y</strong>z", html)

    def test_quote_and_caption_styles(self):
        html = self.docx(p("Said.", "BlockText") + p("Figure 1", "ImageCaption"))
        self.assertIn('<blockquote><p>Said.</p></blockquote><p class="caption">Figure 1</p>', html)

    def test_repeated_bookmarks_get_one_id(self):
        mark = '<w:bookmarkStart w:id="1" w:name="x"/>'
        html = self.docx(p(runs=mark + r("one")) + p(runs=mark + r("two")))
        self.assertEqual(html.count('id="w-x"'), 1)

    def test_tables_with_spans_merges_and_header_rows(self):
        html = self.docx(table([
            ["Name", "Score", "Note"],
            [("a", {"merge": "restart"}), "1", "x"],
            [("", {"merge": "continue"}), "2", "y"],
            [("wide", {"span": 3})],
        ]))
        self.assertIn("<tr><th><p>Name</p></th>", html)
        self.assertIn('<td rowspan="2"><p>a</p></td><td><p>1</p></td>', html)
        self.assertIn("<tr><td><p>2</p></td><td><p>y</p></td></tr>", html)
        self.assertIn('<td colspan="3"><p>wide</p></td>', html)

    def test_links_keep_safe_schemes_only(self):
        rels = [("rIdOk", "hyperlink", "https://example.com/a?b=1&c=2", True),
                ("rIdMail", "hyperlink", "mailto:team@example.com", True),
                ("rIdBad", "hyperlink", "javascript:alert(1)", True)]
        html = self.docx(p(runs='<w:hyperlink r:id="rIdOk">%s</w:hyperlink>' % r("ok")
                           + '<w:hyperlink r:id="rIdMail">%s</w:hyperlink>' % r("mail")
                           + '<w:hyperlink r:id="rIdBad">%s</w:hyperlink>' % r("bad")), rels=rels)
        self.assertIn('<a href="https://example.com/a?b=1&amp;c=2">ok</a>', html)
        self.assertIn('<a href="mailto:team@example.com">mail</a>', html)
        self.assertIn("bad", html)
        self.assertNotIn("javascript", html)

    def test_internal_links_and_bookmarks(self):
        html = self.docx(p(runs='<w:hyperlink w:anchor="later">%s</w:hyperlink>' % r("go"))
                         + p(runs='<w:bookmarkStart w:id="1" w:name="later"/>' + r("here")))
        self.assertIn('<a href="#w-later">go</a>', html)
        self.assertIn('<span id="w-later"></span>here', html)

    def test_images_and_formats_browsers_cannot_show(self):
        html = self.docx(p(runs=make.image("rIdA", descr="A chart") + make.image("rIdB")),
                         rels=[("rIdA", "image", "media/a.png", False), ("rIdB", "image", "media/b.emf", False)],
                         media={"a.png": make.png(), "b.emf": b"EMF"})
        self.assertIn('<img data-part="word/media/a.png" alt="A chart" width="200">', html)
        self.assertIn("[EMF image not shown]", html)

    def test_footnotes_are_numbered_in_order_of_use(self):
        html = self.docx(p(runs=r("a") + '<w:r><w:footnoteReference w:id="7"/></w:r>'
                           + r("b") + '<w:r><w:footnoteReference w:id="3"/></w:r>'),
                         footnotes={"3": "Second.", "7": "First."})
        self.assertIn('<sup><a href="#w-footnote-7">1</a></sup>b<sup><a href="#w-footnote-3">2</a></sup>', html)
        self.assertIn('<li id="w-footnote-7"><p>First.</p></li><li id="w-footnote-3"><p>Second.</p></li>', html)

    def test_note_markers_are_raised_once(self):
        html = self.docx(p(runs=r("a") + '<w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr>'
                           '<w:footnoteReference w:id="1"/></w:r>'), footnotes={"1": "Note."})
        self.assertIn('a<sup><a href="#w-footnote-1">1</a></sup></p>', html)

    def test_content_controls_are_unwrapped(self):
        html = self.docx("<w:sdt><w:sdtPr/><w:sdtContent>%s</w:sdtContent></w:sdt>" % p("inside"))
        self.assertIn("<p>inside</p>", html)

    def test_documents_without_styles_or_numbering(self):
        html = self.docx(p("plain"), styles=None)
        self.assertIn("<p>plain</p>", html)

    def test_strict_namespaces(self):
        strict = make.W_NS.replace("http://schemas.openxmlformats.org/wordprocessingml/2006/main",
                                   "http://purl.oclc.org/ooxml/wordprocessingml/main")
        document = make.HEAD + "<w:document %s><w:body>%s</w:body></w:document>" % (strict, p("strict"))
        self.assertIn("<p>strict</p>", self.docx("", document=document))

    def test_demo_document(self):
        path = self.dir / "demo.docx"
        make.demo_docx(path)
        html = office.docx_page(str(path))["html"]
        for piece in ("<h1>Summary</h1>", "<code>eval.py --split indoor</code>", "<table>",
                      '<a href="https://example.com/project">', "&lt;script&gt;"):
            self.assertIn(piece, html)


class Excel(Folder):
    def test_value_types(self):
        out = self.xlsx([("S", grid([
            ["text", "int", "float", "bool", "error", "formula", "shared"],
            ["a", 3, 0.1 + 0.2, True, ("e", "#DIV/0!"), ("f", ("A1*2", 6)), ("s", 1)],
        ]), None)], shared=["zero", "one"])
        self.assertEqual(out["rows"][1], ["a", "3", "0.3", "TRUE", "#DIV/0!", "6", "one"])

    def test_dates_times_and_percents(self):
        out = self.xlsx([("S", grid([["d", "dt", "pct", "money", "time"],
                                     [45200, 45200.5, 0.125, 1234.5, 0.75]],
                                    styles={0: 1, 1: 2, 2: 3, 3: 4, 4: 5}), None)])
        self.assertEqual(out["rows"][1], ["2023-10-01", "2023-10-01 12:00", "12.5%", "1234.5", "18:00:00"])

    def test_1904_dates(self):
        out = self.xlsx([("S", grid([["d"], [0]], styles={0: 1}), None)], date1904=True)
        self.assertEqual(out["rows"][1], ["1904-01-01"])

    def test_custom_date_formats(self):
        kinds = {code: office._format_kind(code) for code in (
            "yyyy-mm-dd", "mmm d", "h:mm AM/PM", "[h]:mm:ss", "dd/mm/yyyy hh:mm", '0.0"m"', "#,##0", "0.00%",
            '[$-409]mmmm d, yyyy', '"Day "0', "mmm")}
        self.assertEqual(kinds, {
            "yyyy-mm-dd": "date", "mmm d": "date", "h:mm AM/PM": "time", "[h]:mm:ss": "time",
            "dd/mm/yyyy hh:mm": "datetime", '0.0"m"': None, "#,##0": None, "0.00%": "percent",
            '[$-409]mmmm d, yyyy': "date", '"Day "0': None, "mmm": "date"})

    def test_sparse_cells_keep_their_columns_and_blank_rows(self):
        data = ('<row r="3">%s%s</row><row r="5">%s</row>'
                % (cell("C3", "a"), cell("E3", "b"), cell("D5", 1)))
        out = self.xlsx([("S", data, None)])
        self.assertEqual((out["first_row"], out["first_col"], out["first_letter"]), (3, 2, "C"))
        self.assertEqual(out["rows"], [["a", "", "b"], [], ["", "1"]])

    def test_cells_without_references(self):
        out = self.xlsx([("S", '<row><c t="inlineStr"><is><t>a</t></is></c><c><v>2</v></c></row>', None)])
        self.assertEqual(out["rows"], [["a", "2"]])

    def test_rich_and_phonetic_shared_strings(self):
        rich = "<r><rPr><b/></rPr><t>Bo</t></r><r><t>ld</t></r>"
        phonetic = '<t>東京</t><rPh sb="0" eb="2"><t>トウキョウ</t></rPh>'
        out = self.xlsx([("S", grid([[("s", 0), ("s", 1)]]), None)], shared=[rich, phonetic])
        self.assertEqual(out["rows"], [["Bold", "東京"]])

    def test_sheets_active_tab_hidden_and_choice(self):
        sheets = [("One", grid([["1"]]), None), ("Two", grid([["2"]]), None), ("Secret", grid([["3"]]), "hidden")]
        out = self.xlsx(sheets, active=1)
        self.assertEqual(out["sheet"], 1)
        self.assertEqual(out["rows"], [["2"]])  # Two's part has an absolute target
        self.assertEqual(out["sheets"], [{"name": "One", "hidden": False}, {"name": "Two", "hidden": False},
                                         {"name": "Secret", "hidden": True}])
        self.assertEqual(self.xlsx(sheets, sheet="2")["rows"], [["3"]])
        with self.assertRaises(OfficeError):
            self.xlsx(sheets, sheet="9")
        with self.assertRaises(OfficeError):
            self.xlsx(sheets, sheet="x")

    def test_empty_sheet(self):
        out = self.xlsx([("S", '<row r="1"><c r="A1" s="1"/></row>', None)])
        self.assertEqual(out["rows"], [])

    def test_row_and_column_caps(self):
        rows = [[index] for index in range(30)]
        with mock.patch.object(office, "SHEET_ROWS", 10), mock.patch.object(office, "SHEET_COLUMNS", 3):
            out = self.xlsx([("S", grid(rows) + '<row r="40">%s</row>' % cell("E40", "far"), None)])
        self.assertTrue(out["truncated"])
        self.assertEqual(len(out["rows"]), 10)
        out_wide = None
        with mock.patch.object(office, "SHEET_COLUMNS", 3):
            out_wide = self.xlsx([("S", '<row r="1">%s%s</row>' % (cell("A1", "a"), cell("E1", "far")), None)])
        self.assertTrue(out_wide["wide"])
        self.assertEqual(out_wide["rows"], [["a"]])

    def test_column_letters(self):
        self.assertEqual([office.column_letters(n) for n in (0, 25, 26, 701, 702)], ["A", "Z", "AA", "ZZ", "AAA"])


class Hostile(Folder):
    def test_doctype_is_refused(self):
        bomb = make.HEAD + ('<!DOCTYPE d [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>'
                            "<w:document %s><w:body><w:p><w:r><w:t>&b;</w:t></w:r></w:p></w:body></w:document>"
                            % make.W_NS)
        with self.assertRaisesRegex(OfficeError, "DOCTYPE"):
            self.docx("", document=bomb)

    def test_doctype_in_a_streamed_sheet_is_refused(self):
        path = self.dir / "book.xlsx"
        make.write_xlsx(path, [("S", grid([["a"]]), None)])
        with warnings.catch_warnings(), zipfile.ZipFile(path, "a") as archive:
            warnings.simplefilter("ignore")  # the later copy of a duplicate name is the one read
            archive.writestr("xl/sharedStrings.xml", '<!DOCTYPE x [<!ENTITY e "x">]><sst/>')
        with self.assertRaisesRegex(OfficeError, "DOCTYPE"):
            Office().read(str(path), 0, 0)

    def test_parts_larger_than_the_cap(self):
        with mock.patch.object(office, "PART_MAX", 1000):
            with self.assertRaisesRegex(OfficeError, "too large"):
                self.docx(p("x" * 5000))

    def test_not_a_zip(self):
        path = self.dir / "fake.docx"
        path.write_text("just text")
        with self.assertRaisesRegex(OfficeError, "valid Office file"):
            Office().read(str(path), 0, 0)

    def test_zip_without_a_document(self):
        path = self.dir / "empty.xlsx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("other.txt", "x")
        with self.assertRaisesRegex(OfficeError, "no workbook"):
            Office().read(str(path), 0, 0)

    def test_damaged_xml(self):
        with self.assertRaisesRegex(OfficeError, "damaged"):
            path = self.dir / "doc.docx"
            make.write_docx(path, "", document="<w:document")
            Office().read(str(path), 0, 0)

    def test_images_only_from_word_media_types(self):
        path = self.dir / "doc.docx"
        make.write_docx(path, p("x"), media={"a.png": make.png(), "page.svg": b"<svg/>"})
        data, kind = Office().image(str(path), "word/media/a.png")
        self.assertEqual(kind, "image/png")
        self.assertTrue(data.startswith(b"\x89PNG"))
        for part in ("word/media/page.svg", "word/document.xml", "[Content_Types].xml", "word/media/none.png"):
            with self.assertRaises(OfficeError, msg=part):
                Office().image(str(path), part)

    def test_cache_follows_the_file(self):
        path = self.dir / "doc.docx"
        reader = Office()
        make.write_docx(path, p("first"))
        self.assertIn("first", reader.read(str(path), 1, 1)["html"])
        make.write_docx(path, p("second"))
        self.assertIn("first", reader.read(str(path), 1, 1)["html"])  # same mtime and size: cached
        self.assertIn("second", reader.read(str(path), 2, 1)["html"])


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(cls.tmp.name)
        make.demo_docx(root / "report.docx")
        make.demo_xlsx(root / "results.xlsx")
        (root / "broken.docx").write_bytes(b"PK\x03\x04 nope")
        (root / ".private").mkdir()
        make.demo_docx(root / ".private" / "secret.docx")
        cls.server = Running(root)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        cls.tmp.cleanup()

    def get_json(self, path):
        response, body = self.server.get(path)
        return response.status, json.loads(body)

    def test_word_page(self):
        status, data = self.get_json("/__shelf/api/office?path=report.docx")
        self.assertEqual(status, 200)
        self.assertEqual(data["type"], "docx")
        self.assertIn("<h1>Summary</h1>", data["html"])

    def test_excel_sheets(self):
        status, data = self.get_json("/__shelf/api/office?path=results.xlsx")
        self.assertEqual((status, data["type"], data["sheet"]), (200, "xlsx", 0))
        self.assertEqual(data["rows"][0][0], "split")
        status, data = self.get_json("/__shelf/api/office?path=results.xlsx&sheet=1")
        self.assertEqual(data["rows"][-1], ["Total", "12800.5"])
        status, data = self.get_json("/__shelf/api/office?path=results.xlsx&sheet=7")
        self.assertEqual(status, 422)

    def test_errors_are_explained(self):
        status, data = self.get_json("/__shelf/api/office?path=broken.docx")
        self.assertEqual(status, 422)
        self.assertIn("valid Office file", data["error"])

    def test_dotfiles_stay_hidden(self):
        status, _ = self.get_json("/__shelf/api/office?path=.private/secret.docx")
        self.assertEqual(status, 404)
        response, _ = self.server.get("/__shelf/api/office-part?path=.private/secret.docx&part=word/media/chart.png")
        self.assertEqual(response.status, 404)

    def test_embedded_image(self):
        response, body = self.server.get("/__shelf/api/office-part?path=report.docx&part=word/media/chart.png&v=1")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "image/png")
        self.assertIn("sandbox", response.getheader("Content-Security-Policy"))
        self.assertIn("immutable", response.getheader("Cache-Control"))
        self.assertTrue(body.startswith(b"\x89PNG"))
        response, _ = self.server.get("/__shelf/api/office-part?path=report.docx&part=word/document.xml")
        self.assertEqual(response.status, 404)

    def test_raw_file_still_downloads(self):
        response, body = self.server.get("/report.docx")
        self.assertEqual(response.status, 200)
        self.assertTrue(body.startswith(b"PK"))


if __name__ == "__main__":
    unittest.main()
