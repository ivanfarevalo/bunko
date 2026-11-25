#!/usr/bin/env python3
"""Drive the UI in real Chrome against a demo tree.

python3 tests/make_demo.py DEMO
uv run python tests/e2e.py DEMO SHOTS_DIR
"""

import atexit
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

demo = pathlib.Path(sys.argv[1]).resolve()
shots = pathlib.Path(sys.argv[2]).resolve()
shots.mkdir(parents=True, exist_ok=True)
repo = pathlib.Path(__file__).resolve().parent.parent

with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
base = f"http://127.0.0.1:{port}"
# Keep favorites, recents and thumbnails out of the real ~/.config and ~/.cache.
scratch = tempfile.mkdtemp(prefix="bunko-e2e-")
atexit.register(shutil.rmtree, scratch, True)
ENV = dict(
    os.environ,
    XDG_CONFIG_HOME=os.path.join(scratch, "config"),
    XDG_CACHE_HOME=os.path.join(scratch, "cache"),
)
server = subprocess.Popen(
    [sys.executable, "-m", "bunko", str(port), str(demo), "-b", "127.0.0.1"],
    cwd=repo,
    stdout=subprocess.DEVNULL,
    env=ENV,
)
atexit.register(server.terminate)
for _ in range(100):
    try:
        urllib.request.urlopen(base, timeout=1)
        break
    except OSError:
        time.sleep(0.05)

failures = []
passed = 0


def check(name, condition, detail=""):
    global passed
    if condition:
        passed += 1
        print("  ok  ", name)
    else:
        failures.append(name)
        print("  FAIL", name, detail)


def snap(page, name):
    page.screenshot(path=str(shots / (name + ".png")))


with sync_playwright() as p:
    # Google Chrome, not bundled Chromium: Chromium can't play H.264 video.
    # Set BUNKO_E2E_CHROME to use a specific binary.
    binary = os.environ.get("BUNKO_E2E_CHROME")
    browser = (
        p.chromium.launch(executable_path=binary, headless=True)
        if binary
        else p.chromium.launch(channel="chrome", headless=True)
    )
    context = browser.new_context(viewport={"width": 1360, "height": 860}, color_scheme="light")
    context.set_default_timeout(10000)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))

    def console_error(message):
        if message.type == "error":
            where = message.location.get("url", "")
            errors.append(f"console: {message.text} (at {where or page.url})")

    page.on("console", console_error)

    def wait_js(expression, timeout=10000):
        # Not page.wait_for_function: it needs eval, which the app's CSP blocks,
        # and these tests should run under the real policy.
        deadline = time.time() + timeout / 1000
        while not page.evaluate(expression):
            if time.time() > deadline:
                raise TimeoutError(expression)
            page.wait_for_timeout(50)

    def go(path):
        page.goto(f"{base}/#/{path}")
        page.wait_for_timeout(350)

    def hover_click(row, selector):
        # Row tools show on hover. If the sidebar redraws under a still mouse,
        # the new row isn't hovered until the mouse moves, so hover again.
        for _ in range(5):
            row.hover()
            try:
                row.locator(selector).click(timeout=2000)
                return
            except PlaywrightTimeout:
                page.mouse.move(0, 0)
        row.locator(selector).click()

    print("root folder")
    page.goto(base)
    page.wait_for_selector("#tree .row")
    page.wait_for_selector(".folder-head h1")
    names = page.locator("#tree > .row .label").all_text_contents()
    check("tree lists folders first", names[:3] == ["data", "docs", "images"], names[:4])
    check("dotfolders absent from tree", ".hidden" not in names)
    check(
        "README renders under the listing",
        page.locator(".readme h1").inner_text() == "Detector evaluation",
    )
    check("markdown table renders", page.locator(".readme table tr").count() == 3)
    snap(page, "01-folder")

    print("markdown")
    go("docs/guide.md")
    page.wait_for_selector(".md h1")
    check("headings", page.locator(".md h2").count() == 2)
    check("duplicate headings get unique ids", page.locator("[id='second-section-1']").count() == 1)
    check("syntax highlighting", page.locator(".md .hljs-keyword").count() > 0)
    check("task list", page.locator(".md input[type=checkbox]").count() == 2)
    check("front matter folded away", page.locator("details.front").count() == 1)
    page.locator(".md img[alt='A chart']").scroll_into_view_if_needed()
    wait_js("document.querySelector('.md img[alt=\"A chart\"]').naturalWidth > 0")
    check("relative image loads", True)
    check(
        "relative doc link rewritten",
        page.locator(".md a", has_text="relative link").get_attribute("href") == "#/README.md",
    )
    external = page.locator(".md a", has_text="external link")
    check("external link opens a new tab", external.get_attribute("target") == "_blank")
    check("script tags removed", page.evaluate("window.__pwned") is None)
    href = page.locator("#jslink").get_attribute("href")
    check("javascript: links removed", not (href or "").startswith("javascript"), href)
    page.locator(".md a", has_text="heading link").click()
    page.wait_for_timeout(150)
    check(
        "in-page anchor scrolls without changing route",
        page.url.endswith("docs/guide.md")
        and page.evaluate("document.querySelector('#view').scrollTop") > 0,
    )
    page.evaluate("document.querySelector('#view').scrollTop = 0")
    snap(page, "02-markdown")
    page.locator(".md a", has_text="relative link").click()
    page.wait_for_timeout(300)
    check("relative doc link navigates", page.url.endswith("#/README.md"))

    print("html")
    go("report/index.html")
    frame = page.frame_locator("iframe.page-frame")
    frame.locator("#title").wait_for()
    page.wait_for_timeout(300)
    check(
        "relative fetch works in the frame",
        frame.locator("#title").inner_text() == "Fetched from relative JSON",
    )
    color = frame.locator("#title").evaluate("e => getComputedStyle(e).color")
    check("relative CSS applies", color == "rgb(200, 30, 30)", color)
    check("root-absolute image loads", frame.locator("#abs").evaluate("e => e.naturalWidth") > 0)
    snap(page, "03-html")
    frame.locator("#bust").click()
    page.wait_for_timeout(200)
    check("page cannot replace the app", page.url.startswith(base + "/#/report"), page.url)
    frame.locator("#next").click()
    page.wait_for_timeout(500)
    check("link inside a page updates the URL", page.url.endswith("#/report/page2.html"), page.url)
    check("breadcrumbs follow it", page.locator("#crumbs a").last.inner_text() == "page2.html")
    page.go_back()
    page.wait_for_timeout(500)
    check("one Back press undoes a frame link", page.url.endswith("#/report/index.html"), page.url)
    frame.locator("#next").click()
    page.wait_for_timeout(500)
    page.frame_locator("iframe.page-frame").locator("#p2").wait_for()
    page.go_back()
    page.wait_for_timeout(500)
    frame.locator("#folder").wait_for()
    frame.locator("#folder").click()
    page.wait_for_selector(".folder-head h1")
    check(
        "folder link inside a page opens the folder view",
        page.locator(".folder-head h1").inner_text() == "data",
        page.url,
    )
    go("site")
    page.wait_for_selector("iframe.page-frame")
    page.frame_locator("iframe.page-frame").locator("#siteindex").wait_for()
    check("folder with index.html shows the page", True)

    print("image")
    go("images")
    page.wait_for_selector(".grid .card")
    check(
        "image folder opens as gallery",
        page.locator(".grid .card").count() == 8,
        page.locator(".grid .card").count(),
    )
    page.wait_for_timeout(300)
    snap(page, "04-gallery")
    go("images/frame_2.png")
    wait_js("document.querySelector('.stage img')?.naturalWidth > 0")
    page.wait_for_timeout(200)
    check(
        "dimensions shown",
        "640 × 480" in page.locator("#meta").inner_text(),
        page.locator("#meta").inner_text(),
    )
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(350)
    check("right arrow goes to next image", page.url.endswith("frame_3.png"), page.url)
    page.keyboard.press("ArrowLeft")
    page.wait_for_timeout(350)
    check("left arrow goes back", page.url.endswith("frame_2.png"), page.url)
    snap(page, "05-image")
    page.locator(".stage img").click()
    check("click zooms", page.locator(".stage.zoomed").count() == 1)
    go("images/frame_10.svg")
    wait_js("document.querySelector('.stage img')?.naturalWidth > 0")
    check("svg renders", True)
    go("images/broken.png")
    page.wait_for_selector(".notice")
    check(
        "broken image explains itself",
        "could not be decoded" in page.locator(".notice").inner_text(),
    )

    print("video")
    go("videos/clip.mp4")
    page.wait_for_selector("video")
    wait_js("document.querySelector('video').readyState >= 1")
    check(
        "video metadata loads",
        abs(page.evaluate("document.querySelector('video').duration") - 20) < 0.5,
    )
    page.evaluate("document.querySelector('video').currentTime = 15")
    wait_js(
        "document.querySelector('video').readyState >= 2 && Math.abs(document.querySelector('video').currentTime - 15) < 0.5"
    )
    check("seeking works", True)
    page.wait_for_timeout(200)
    snap(page, "06-video")
    go("videos/clip2.webm")
    wait_js("document.querySelector('video')?.readyState >= 1")
    check("webm plays", True)
    go("videos/corrupt.mp4")
    page.wait_for_selector(".notice")
    check("unplayable video explains itself", "cannot play" in page.locator(".notice").inner_text())
    go("videos/tone.wav")
    page.wait_for_selector("audio")
    check("audio player shows", True)

    print("tables")
    go("data/small.csv")
    page.wait_for_selector("table.data tbody tr:not(.pad) td")
    check("small csv rows", page.locator("table.data tbody tr:not(.pad)").count() == 3)
    check("no Load more once fully loaded", not page.locator(".table-bar .btn").is_visible())
    page.locator("table.data thead th", has_text="score").click()
    page.wait_for_timeout(100)
    order = page.locator("table.data tbody tr:not(.pad) td:nth-child(3)").all_inner_texts()
    check("sort ascending by number", order == ["9.5", "10", "100"], order)
    page.locator("table.data thead th", has_text="score").click()
    page.wait_for_timeout(100)
    order = page.locator("table.data tbody tr:not(.pad) td:nth-child(3)").all_inner_texts()
    check("sort descending", order == ["100", "10", "9.5"], order)
    page.locator(".table-bar input").fill("gam")
    page.wait_for_timeout(100)
    check("filter", page.locator("table.data tbody tr:not(.pad)").count() == 1)

    go("data/quoted.csv")
    page.wait_for_selector("table.data tbody tr:not(.pad) td")
    texts = page.locator("table.data tbody tr:not(.pad) td:nth-child(3)").all_inner_texts()
    check(
        "quotes, commas, newlines in fields",
        texts[:3] == ["a, comma", 'say "hi"', "two\nlines"]
        or texts[:3] == ["a, comma", 'say "hi"', "two lines"],
        texts,
    )
    check("ragged rows survive", page.locator("table.data tbody tr:not(.pad)").count() == 5)
    check(
        "extra columns get headers",
        page.locator("table.data thead th").count() == 5,
        page.locator("table.data thead th").count(),
    )
    go("data/semi.csv")
    page.wait_for_selector("table.data tbody tr:not(.pad) td")
    check("semicolon sniffed", page.locator("table.data thead th").count() == 4)
    go("data/tabs.tsv")
    page.wait_for_selector("table.data tbody tr:not(.pad) td")
    check("tsv", page.locator("table.data thead th").count() == 3)
    go("data/bom.csv")
    page.wait_for_selector("table.data tbody tr:not(.pad) td")
    check("BOM stripped", page.locator("table.data thead th").nth(1).inner_text().strip() == "name")
    go("data/empty.csv")
    page.wait_for_selector(".notice")
    check("empty csv", "empty" in page.locator(".notice").inner_text())
    go("data/%3Cb%3Eevil.csv")
    page.wait_for_selector("table.data")
    page.wait_for_timeout(200)
    check(
        "html in csv stays text",
        page.evaluate("window.__pwned") is None and page.locator("table.data img").count() == 0,
    )

    go("data/big.csv")
    page.wait_for_selector("table.data tbody tr:not(.pad) td")
    status = page.locator(".table-bar .status").inner_text()
    check("big csv loads in part", "loaded" in status, status)
    drawn = page.locator("table.data tbody tr").count()
    check("rows are virtualized", drawn < 150, drawn)
    snap(page, "07-csv")
    page.evaluate("document.querySelector('.table-scroll').scrollTop = 200000 * 31")
    page.wait_for_timeout(300)
    first = page.locator("table.data tbody tr:not(.pad) td.rn").first.inner_text()
    check("deep scroll shows the right rows", first.isdigit() and int(first) > 1000, first)
    start = time.time()
    while "loaded" in page.locator(".table-bar .status").inner_text() and time.time() - start < 20:
        page.locator(".table-bar .btn").click(force=True)
        page.wait_for_timeout(300)
    status = page.locator(".table-bar .status").inner_text()
    check("all rows reachable", status.startswith("400,000 rows"), status)
    page.evaluate("document.querySelector('.table-scroll').scrollTop = 1e9")
    page.wait_for_timeout(300)
    last = page.locator("table.data tbody tr:not(.pad) td.rn").last.inner_text()
    check("final row number", last == "400000", last)
    sticky = page.evaluate(
        "document.querySelector('table.data thead th:nth-child(2)').getBoundingClientRect().top - document.querySelector('.table-scroll').getBoundingClientRect().top"
    )
    check("header stays pinned", abs(sticky) < 2, sticky)

    print("text and code")
    go("src/train.py")
    page.wait_for_selector(".code-view")
    check("python highlighted", page.locator(".code-view .hljs-keyword").count() > 0)
    check(
        "line numbers",
        page.locator(".gutter").inner_text().split()[-1] == "8",
        page.locator(".gutter").inner_text(),
    )
    snap(page, "08-code")
    go("src/CMakeLists.txt")
    page.wait_for_selector(".code-view .hljs-keyword, .code-view .hljs-built_in")
    check("cmake highlighted", True)
    go("src/Dockerfile")
    page.wait_for_selector(".code-view .hljs-keyword")
    check("dockerfile highlighted", True)
    go("config.json")
    page.wait_for_selector(".code-view")
    check("json pretty-printed", '"model": "yolox"' in page.locator(".src").inner_text())
    go("broken.json")
    page.wait_for_selector(".code-view")
    check("invalid json shown as written", "oops" in page.locator(".src").inner_text())
    go("notes%20without%20extension")
    page.wait_for_selector(".code-view")
    check("extensionless text sniffed", "plain notes" in page.locator(".src").inner_text())
    go("src/weights.bin")
    page.wait_for_selector(".notice")
    check("binary gets a download card", "no preview" in page.locator(".notice").inner_text())
    go("logs/big.log")
    page.wait_for_selector(".load-more .btn")
    check(
        "big text loads in part",
        "Showing 1.0 MB" in page.locator(".load-more").inner_text(),
        page.locator(".load-more").inner_text(),
    )
    lines_before = len(page.locator(".gutter").inner_text().split())
    page.locator(".load-more .btn").click()
    page.wait_for_timeout(300)
    check("load more appends", len(page.locator(".gutter").inner_text().split()) > lines_before)

    print("awkward names and symlinks")
    go("a%20b%23c%3Fd%25e%20%26%20caf%C3%A9.md")
    page.wait_for_selector(".md h1")
    check("awkward file name opens", page.locator(".md h1").inner_text() == "Awkward name")
    row = page.locator("#tree .row.current")
    check("tree marks it", "Awkward" in page.locator(".md h1").inner_text() and row.count() == 1)
    go("linked/external.md")
    page.wait_for_selector(".md h1")
    check("symlink out of root opens", page.locator(".md h1").inner_text() == "External")
    go(".hidden/secret.txt")
    page.wait_for_selector(".notice")
    check("hidden file reads as not found", "Not found" in page.locator(".notice").inner_text())
    go("does/not/exist.md")
    page.wait_for_selector(".notice")
    check("missing file reads as not found", "Not found" in page.locator(".notice").inner_text())

    print("big folders")
    go("many")
    page.wait_for_selector(".item")
    page.wait_for_timeout(200)
    check(
        "folder draws in batches",
        page.locator(".item").count() <= 400,
        page.locator(".item").count(),
    )
    page.evaluate("document.querySelector('#view').scrollTop = 1e9")
    page.wait_for_timeout(250)
    check("scrolling draws more", page.locator(".item").count() > 200)
    check("natural order", page.locator(".item .n span").nth(2).inner_text() == "sample_2.txt")
    check("tree caps a long folder", page.locator("#tree .row.more").count() == 1)
    go("many/sample_1400.txt")
    page.wait_for_selector(".code-view")
    page.wait_for_timeout(300)
    check("deep link past the cap still reveals", page.locator("#tree .row.current").count() == 1)

    print("search")
    page.keyboard.press("Control+k")
    check("Ctrl+K focuses search", page.evaluate("document.activeElement.id") == "q")
    page.keyboard.type("guide")
    page.wait_for_selector("#results .hit")
    check("search finds a file", "guide.md" in page.locator("#results .hit").first.inner_text())
    check("match is marked", page.locator("#results mark").first.inner_text() == "guide")
    snap(page, "09-search")
    page.keyboard.press("Enter")
    page.wait_for_selector(".md h1")
    check("Enter opens it", page.url.endswith("docs/guide.md"))
    page.locator("#q").fill("external")
    wait_js("document.querySelector('#results .hit')?.textContent.includes('external.md')")
    check("search reaches through symlinks", True)
    page.locator("#q").fill("secret")
    page.wait_for_selector("#results .none-found")
    check("search hides dotfiles", True)
    page.keyboard.press("Escape")
    check("Escape restores the tree", page.locator("#tree").is_visible())

    print("live reload")
    live = demo / "live.md"
    live.write_text("# Before\n")
    go("live.md")
    page.wait_for_selector(".md h1")
    time.sleep(0.05)
    live.write_text("# After\n")
    wait_js("document.querySelector('.md h1')?.textContent === 'After'", timeout=6000)
    check("edited markdown refreshes", True)
    page.wait_for_timeout(100)
    live_html = demo / "live.html"
    live_html.write_text("<h1 id=v>one</h1>")
    go("live.html")
    fl = page.frame_locator("iframe.page-frame")
    fl.locator("#v").wait_for()
    live_html.write_text("<h1 id=v>two!</h1>")
    page.wait_for_timeout(3500)
    check("edited html refreshes", fl.locator("#v").inner_text() == "two!")
    go("")
    page.wait_for_selector(".item")
    (demo / "newfile.txt").write_text("hi")
    page.wait_for_selector("#tree .row[data-path='newfile.txt']", timeout=6000)
    # The tree refreshes first, then the folder view re-renders.
    wait_js(
        "[...document.querySelectorAll('.item')].some(item => item.textContent.includes('newfile.txt'))",
        timeout=3000,
    )
    check(
        "new file appears in tree and folder",
        page.locator(".item", has_text="newfile.txt").count() == 1,
    )
    for leftover in (live, live_html, demo / "newfile.txt"):
        leftover.unlink()

    print("content search")
    page.locator(".search-modes button[data-mode=contents]").click()
    page.locator("#q").fill("duplicate heading")
    wait_js("document.querySelector('#results .snip') !== null")
    snippet = page.locator("#results .snip").first
    check("content hit shows the line", "duplicate heading" in snippet.inner_text().lower())
    check(
        "match is marked in the snippet",
        page.locator("#results .snip mark").first.inner_text().lower() == "duplicate heading",
    )
    snap(page, "14-content-search")
    snippet.click()
    page.wait_for_selector("mark.find.current")
    check(
        "markdown opens at the match",
        "?line=" in page.url and page.locator("mark.find").count() >= 1,
    )
    page.locator("#q").fill("step=777 loss")
    wait_js("document.querySelector('#results .snip')?.textContent.includes('step=777 loss')")
    page.locator("#results .snip").first.click()
    page.wait_for_selector(".line-mark")
    check(
        "text file opens at the line",
        page.evaluate("document.querySelector('#view').scrollTop") > 1000,
    )
    page.locator("#q").fill("step=100000 loss")
    wait_js("document.querySelector('#results .snip')?.textContent.includes('step=100000 loss')")
    page.locator("#results .snip").first.click()
    wait_js(
        "document.querySelector('.gutter')?.textContent.split('\\n').length > 100001", timeout=20000
    )
    page.wait_for_selector(".line-mark")
    lines = page.evaluate("document.querySelector('.gutter').textContent.split('\\n').length")
    check("jump loads past the first megabyte", lines > 100001, lines)
    page.keyboard.press("Escape")
    page.locator(".search-modes button[data-mode=names]").click()

    print("word and excel")
    go("office/review.docx")
    page.wait_for_selector(".docx h1")
    check("word title", page.locator(".docx h1").first.inner_text() == "Quarterly review")
    check(
        "word emphasis and code",
        page.locator(".docx strong", has_text="0.912").count() == 1
        and page.locator(".docx p > code", has_text="eval.py").count() == 1,
    )
    check(
        "word lists nest",
        page.locator(".docx ul ul li").count() == 1
        and page.locator(".docx ol ol[type=a] li").count() == 1,
    )
    check("word table", page.locator(".docx .tbl table tr").count() == 4)
    code = page.locator(".docx .block pre").inner_text()
    check(
        "word code block, with a copy button",
        code == "python eval.py \\\n    --split indoor --threshold 0.45"
        and page.locator(".docx .block .copy").count() == 1,
        code,
    )
    wait_js(
        "(() => { const i = document.querySelector('.docx img'); return i && i.complete && i.naturalWidth === 4 * 50 })()"
    )
    check("embedded image loads", True)
    check(
        "outline beside the document",
        page.locator(".toc .toc-link").count() >= 4,
        page.locator(".toc .toc-link").count(),
    )
    check(
        "word link opens a new tab",
        page.locator(".docx a", has_text="project page").get_attribute("target") == "_blank",
    )
    check(
        "script text stays text",
        page.evaluate("window.__pwned") is None
        and "<script>" in page.locator(".docx").inner_text(),
    )
    check(
        "footnote listed", "Measured on 4,210 clips." in page.locator(".docx .notes").inner_text()
    )
    page.locator(".docx a", has_text="summary").click()
    page.wait_for_timeout(200)
    check(
        "internal link scrolls, route unchanged",
        page.url.endswith("#/office/review.docx")
        and page.evaluate("document.querySelector('#view').scrollTop") > 0,
        page.url,
    )
    snap(page, "24-word")

    go("office/results.xlsx")
    page.wait_for_selector("table.data tbody tr:not(.pad) td")
    heads = [h.strip() for h in page.locator("table.data thead th").all_inner_texts()]
    check("excel header from the first row", heads[1:4] == ["split", "precision", "recall"], heads)
    status = page.locator(".table-bar .status").inner_text()
    check("excel row count", status.startswith("60 rows"), status)
    first = page.locator("table.data tbody tr:not(.pad)").first.locator("td").all_inner_texts()
    check("excel row numbers match Excel", first[0] == "2", first)
    check("dates and percents", first[5:7] == ["2023-10-02", "10%"], first)
    tabs = page.locator(".sheet-tab")
    check(
        "sheet tabs leave out hidden sheets",
        tabs.all_inner_texts() == ["Results", "Budget"],
        tabs.all_inner_texts(),
    )
    check("hidden sheets counted", page.locator(".sheet-note").inner_text() == "1 hidden")
    snap(page, "25-excel")
    tabs.nth(1).click()
    page.wait_for_selector("table.data td >> text=GPUs")
    check("tab switches the sheet", page.url.endswith("office/results.xlsx?sheet=1"), page.url)
    first = page.locator("table.data tbody tr:not(.pad)").first.locator("td").all_inner_texts()
    check("offset sheet keeps Excel's row numbers", first[:2] == ["3", "GPUs"], first)
    check(
        "column letter in the header tooltip",
        page.locator("table.data thead th").nth(1).get_attribute("title") == "B · Item",
    )
    check("sheet tab marked", page.locator(".sheet-tab.on").inner_text() == "Budget")
    page.reload()
    page.wait_for_selector("table.data td >> text=GPUs")
    check("sheet survives a reload", page.locator(".sheet-tab.on").inner_text() == "Budget")
    go("office/old.doc")
    check(
        "old Word files explain themselves",
        "Saved as .docx" in page.locator(".notice").inner_text(),
    )
    go("office/broken.xlsx")
    check(
        "damaged workbook explains itself",
        "valid Office file" in page.locator(".notice").inner_text(),
        page.locator(".notice").inner_text(),
    )

    print("jsonl")
    go("data/events.jsonl")
    page.wait_for_selector("table.data tbody tr:not(.pad) td")
    heads = page.locator("table.data thead th").all_inner_texts()
    check(
        "jsonl columns from keys",
        [h.strip() for h in heads[1:5]] == ["id", "label", "score", "box"],
        heads,
    )
    check("late keys add columns", any("late_key" in h for h in heads), heads)
    check("bad lines kept", any("unparsed" in h for h in heads), heads)
    status = page.locator(".table-bar .status").inner_text()
    check("jsonl row count", status.startswith("3,001 rows"), status)
    page.locator("#actions button[aria-label='Show as text']").click()
    page.wait_for_selector(".code-view")
    check("jsonl can switch to text", '"label"' in page.locator(".src").inner_text())
    page.reload()
    page.wait_for_selector(".code-view")
    check("the choice persists", page.locator("table.data").count() == 0)
    page.locator("#actions button[aria-label='Show as a table']").click()
    page.wait_for_selector("table.data tbody tr:not(.pad) td")
    check("and switches back", True)

    print("video tools")
    go("videos/clip.mp4")
    page.wait_for_selector(".vtools")
    wait_js("document.querySelector('.vt-frame').textContent.includes('fps')")
    check(
        "frame rate from ffprobe",
        "25 fps" in page.locator(".vt-frame").inner_text()
        and "≈" not in page.locator(".vt-frame").inner_text(),
        page.locator(".vt-frame").inner_text(),
    )
    page.locator("body").click(position={"x": 5, "y": 300})
    page.keyboard.press(".")
    wait_js("document.querySelector('.vt-frame').textContent.startsWith('frame 1 ')")
    page.keyboard.press(".")
    wait_js("document.querySelector('.vt-frame').textContent.startsWith('frame 2 ')")
    page.keyboard.press(",")
    wait_js("document.querySelector('.vt-frame').textContent.startsWith('frame 1 ')")
    check("frame stepping", True)
    page.keyboard.press("l")
    wait_js("Math.abs(document.querySelector('video').currentTime - 1.06) < 0.05")
    check("L skips a second", True)
    page.locator("video").click()  # focus the player itself, where Space is native too
    page.keyboard.press("Space")
    page.wait_for_timeout(400)
    playing = page.evaluate("!document.querySelector('video').paused")
    page.keyboard.press("Space")
    page.wait_for_timeout(200)
    check(
        "Space toggles once even with the player focused",
        playing and page.evaluate("document.querySelector('video').paused"),
    )
    page.keyboard.press("]")
    check("] speeds up", page.evaluate("document.querySelector('video').playbackRate") == 1.5)
    page.keyboard.press("t")
    page.wait_for_timeout(100)
    check("T copies a link", page.locator(".vtools .vt-btn.wide").inner_text().strip() == "Copied")
    snap(page, "15-video-tools")
    go("videos/clip.mp4?t=12.5")
    wait_js("Math.abs(document.querySelector('video').currentTime - 12.5) < 0.05")
    check("?t= opens at that moment", True)
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(400)
    check("arrows still change clips", page.url.endswith("clip2.webm"), page.url)

    print("thumbnails")
    go("images")
    page.wait_for_selector(".grid .card img")
    srcs = page.locator(".grid .card img").evaluate_all(
        "els => els.map(e => e.getAttribute('src'))"
    )
    check("gallery asks for thumbnails", any("/api/thumb" in s for s in srcs), srcs[:3])
    wait_js("[...document.querySelectorAll('.grid .card img')].every(i => i.complete)")
    check(
        "broken image falls back to an icon",
        page.locator(".card[title='broken.png'] svg").count() == 1,
    )
    go("videos")
    page.locator("button[aria-label='Gallery view']").click()
    page.wait_for_selector(".grid .card")
    wait_js(
        "[...document.querySelectorAll('.grid .card img')].every(i => i.complete && i.naturalWidth > 0)"
    )
    check("video folder shows posters", page.locator(".grid .card .badge").count() == 2)
    check(
        "unreadable video shows an icon and no badge",
        page.locator(".card[title='corrupt.mp4'] .badge").count() == 0,
    )
    snap(page, "16-video-gallery")

    print("outline")
    go("docs/guide.md")
    page.wait_for_selector(".toc")
    check("outline shows on wide screens", page.locator(".toc").is_visible())
    page.locator(".toc-link", has_text="Second section").first.click()
    page.wait_for_timeout(300)
    check("outline link scrolls", page.evaluate("document.querySelector('#view').scrollTop") > 200)
    snap(page, "17-outline")
    page.locator("#actions button[aria-label='Show or hide the outline']").click()
    check("outline hides", not page.locator(".toc").is_visible())
    page.reload()
    page.wait_for_selector(".md h1")
    check("hidden outline stays hidden", not page.locator(".toc").is_visible())
    page.locator("#actions button[aria-label='Show or hide the outline']").click()

    print("settings")
    page.locator("#settings-btn").click()
    page.wait_for_selector("#settings")
    check(
        "settings panel opens", "Thumbnails in galleries" in page.locator("#settings").inner_text()
    )
    snap(page, "18-settings")
    page.locator("#settings label.opt", has_text="JSONL files as tables").locator("input").uncheck()
    page.keyboard.press("Escape")
    check("Escape closes settings", page.locator("#settings").count() == 0)
    go("data/events.jsonl")
    page.wait_for_selector(".code-view")
    check("setting turns JSONL tables off", page.locator("table.data").count() == 0)
    page.locator("#settings-btn").click()
    page.locator("#settings label.opt", has_text="JSONL files as tables").locator("input").check()
    page.mouse.click(900, 400)
    check("clicking outside closes settings", page.locator("#settings").count() == 0)

    print("recent, favorites, tags")
    # Fresh page with a clean slate: the server above has seen visits already.
    page.goto(base + "/#/")
    page.wait_for_selector("#tree .row")
    page.wait_for_timeout(300)
    for _ in range(3):
        if page.locator("#places .place").count() == 0:
            break
        page.evaluate(
            "fetch('/__bunko/api/places', {method: 'POST', body: JSON.stringify({op: 'clear-recent'}),"
            " headers: {'Content-Type': 'application/json', 'X-Bunko-Request': '1'}})"
        )
        page.reload()
        page.wait_for_selector("#tree .row")
        page.wait_for_timeout(300)
    check(
        "no sections when there's nothing to show",
        page.locator("#places .place").count() == 0 and page.locator("#files-head").is_hidden(),
    )
    go("docs/guide.md")
    page.wait_for_selector(".md h1")
    go("config.json")
    page.wait_for_selector(".code-view")
    page.wait_for_selector("#places [data-section=recent]")

    def recent():
        return page.locator(
            "#places section:has([data-section=recent]) .place-row .label"
        ).all_inner_texts()

    wait_js("document.querySelector('#places .place-row .label')?.textContent === 'config.json'")
    check(
        "recent lists opened files, newest first",
        recent()[:2] == ["config.json", "guide.md"],
        recent(),
    )
    check("the tree gets a Files heading", page.locator("#files-head").is_visible())

    page.locator("#star-btn").click()
    page.wait_for_selector("#places [data-section=favorites]")
    check("star adds a favorite", page.locator("#star-btn.on").count() == 1)
    page.wait_for_selector("#starmenu input")
    check(
        "and offers an optional nickname",
        "Added to favorites" in page.locator("#starmenu").inner_text()
        and page.evaluate("document.activeElement.getAttribute('aria-label')") == "Nickname",
    )

    def favorites():
        return page.locator(
            "#places section:has([data-section=favorites]) .place-row .label"
        ).all_inner_texts()

    check("favorites section", favorites() == ["config.json"], favorites())

    go("docs/guide.md")
    page.wait_for_selector(".md h1")
    page.locator("#tag-btn").click()
    page.wait_for_selector("#tagmenu input")
    page.keyboard.type("review")
    page.keyboard.press("Enter")
    page.wait_for_selector("#chips .chip")
    check("tagging shows a chip", page.locator("#chips .chip").inner_text().strip() == "review")
    check(
        "each tag gets a section", page.locator("#places [data-section='tag:review']").count() == 1
    )
    box = page.locator("#tagmenu").bounding_box()
    tag_button = page.locator("#tag-btn").bounding_box()
    check(
        "tag menu opens under its button",
        box["y"] >= tag_button["y"] + tag_button["height"]
        and box["height"] < 400
        and box["x"] > 600,
        box,
    )
    snap(page, "19-tag-menu")
    page.keyboard.press("Escape")
    go("README.md")
    page.wait_for_selector(".md h1")
    page.locator("#tag-btn").click()
    page.wait_for_selector("#tagmenu .suggest button")
    check("existing tags are suggested", "review" in page.locator("#tagmenu .suggest").inner_text())
    page.locator("#tagmenu .suggest button", has_text="review").click()
    wait_js(
        "document.querySelectorAll('#places section:has([data-section=\"tag:review\"]) .place-row').length === 2"
    )
    check("a tag collects several files", True)
    page.keyboard.press("Escape")

    def box(selector):
        return page.locator(selector).bounding_box()

    page.evaluate("document.querySelector('#browse').scrollTop = 40")
    page.wait_for_timeout(100)
    check(
        "a section's heading sticks while you're inside it",
        abs(box("#places [data-section=recent]")["y"] - box("#browse")["y"]) < 2,
    )
    page.evaluate("document.querySelector('#browse').scrollTop = 0")

    go("many/sample_1400.txt")
    page.wait_for_selector(".code-view")
    page.wait_for_timeout(400)
    browse, row, files = box("#browse"), box("#tree .row.current"), box("#files-head")
    check(
        "the open file scrolls into view below the stuck heading",
        row["y"] >= files["y"] + files["height"] - 1
        and row["y"] + row["height"] <= browse["y"] + browse["height"] + 1,
        (row, files, browse),
    )
    check(
        "only the Files heading is frozen",
        abs(files["y"] - browse["y"]) < 2
        and box("#places [data-section=recent]")["y"] < browse["y"],
    )
    snap(page, "21-sticky-files")
    page.locator("#files-head").click()
    page.wait_for_timeout(200)
    check(
        "the frozen heading collapses its section",
        page.locator("#tree").is_hidden()
        and box("#places [data-section=recent]")["y"] >= browse["y"] - 1,
    )
    page.locator("#files-head").click()
    page.evaluate("document.querySelector('#browse').scrollTop = 0")
    page.locator(
        "#places section:has([data-section=recent]) .place-row", has_text="config.json"
    ).click()
    page.wait_for_selector(".code-view")
    page.wait_for_timeout(400)
    check(
        "opening a recent file doesn't scroll the sidebar away",
        page.evaluate("document.querySelector('#browse').scrollTop") == 0,
    )
    snap(page, "20-places")

    page.reload()
    page.wait_for_selector("#places [data-section=favorites]")
    check(
        "favorites and tags are kept on the server",
        favorites() == ["config.json"]
        and page.locator("#places [data-section='tag:review']").count() == 1,
    )

    row = page.locator("#places section:has([data-section=recent]) .place-row", has_text="guide.md")
    hover_click(row, ".row-x")
    wait_js(
        "![...document.querySelectorAll('#places section')].find(s => s.querySelector('[data-section=recent]'))?.textContent.includes('guide.md')"
    )
    check("a file can be removed from recent", "guide.md" not in recent(), recent())

    page.locator("#places [data-section=recent]").click()
    check(
        "sections collapse",
        page.locator("#places section:has([data-section=recent]) .place-row").count() == 0,
    )
    page.reload()
    page.wait_for_selector("#places [data-section=recent]")
    check(
        "collapsed stays collapsed",
        page.locator("#places section:has([data-section=recent]) .place-row").count() == 0,
    )
    page.locator("#places [data-section=recent]").click()

    go("images/frame_1.png")
    wait_js("document.querySelector('.stage img')?.naturalWidth > 0")
    for _ in range(3):
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(300)
    page.wait_for_timeout(300)
    check(
        "paging with arrow keys doesn't flood recent",
        recent()[0] == "frame_1.png" and "frame_3.png" not in recent(),
        recent()[:4],
    )

    page.once("dialog", lambda dialog: dialog.accept("to read"))
    page.locator("#places [data-section='tag:review'] .tools button", has_text="Rename").click(
        force=True
    )
    page.wait_for_selector("#places [data-section='tag:to read']")
    check("rename a tag", page.locator("#places [data-section='tag:review']").count() == 0)
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#places [data-section='tag:to read'] .tools button", has_text="Delete").click(
        force=True
    )
    wait_js("!document.querySelector('#places [data-section^=\"tag:\"]')")
    check("delete a tag", True)
    go("config.json")
    page.wait_for_selector("#star-btn.on")
    page.locator("#star-btn").click()
    page.locator("#starmenu button", has_text="Remove").click()
    wait_js("!document.querySelector('#places [data-section=favorites]')")
    check(
        "Remove in the star box unstars",
        page.locator("#star-btn.on").count() == 0 and page.locator("#starmenu").count() == 0,
    )

    print("nicknames")

    def fav_label():
        return page.locator(
            "#places section:has([data-section=favorites]) .place-row .label"
        ).inner_text()

    def fav_where():
        return page.locator(
            "#places section:has([data-section=favorites]) .place-row .where-inline"
        ).inner_text()

    go("docs/guide.md")
    page.wait_for_selector(".md h1")
    page.locator("#star-btn").click()
    page.wait_for_selector("#starmenu input")
    page.keyboard.type("Team guide")
    page.keyboard.press("Enter")
    wait_js(
        "document.querySelector('#places [data-section=favorites]')?.closest('section').textContent.includes('Team guide')"
    )
    check("a nickname becomes the main name", fav_label() == "Team guide", fav_label())
    check("with the full path to its right", fav_where() == "docs/guide.md", fav_where())
    check("the star box closes on Enter", page.locator("#starmenu").count() == 0)
    check(
        "the star's tooltip names it",
        "Team guide" in page.locator("#star-btn").get_attribute("title"),
    )
    page.evaluate("document.querySelector('#browse').scrollTop = 0")
    page.locator("#places section:has([data-section=favorites]) .place-row").hover()
    snap(page, "22-nickname")
    page.reload()
    page.wait_for_selector("#places [data-section=favorites]")
    check("nicknames are kept on the server", fav_label() == "Team guide")
    row = page.locator("#places section:has([data-section=favorites]) .place-row")
    dialogs = []
    page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
    hover_click(row, "button[aria-label='Rename (nickname)']")
    page.wait_for_selector("#starmenu input")
    menu, side = page.locator("#starmenu").bounding_box(), page.locator("#sidebar").bounding_box()
    check(
        "✎ opens the same box as the star, not a browser prompt",
        not dialogs
        and page.locator("#starmenu input").input_value() == "Team guide"
        and "docs/guide.md" in page.locator("#starmenu .pop-path").inner_text(),
    )
    check(
        "the box sits by the sidebar row, inside the window",
        menu["x"] >= 8
        and menu["x"] + menu["width"] <= 1360 - 7
        and menu["x"] < side["x"] + side["width"] + 40,
        menu,
    )
    snap(page, "23-rename-box")
    page.locator("#starmenu input").fill("Guide v2")
    page.keyboard.press("Enter")
    wait_js(
        "document.querySelector('#places section:has([data-section=favorites]) .place-row .label')?.textContent === 'Guide v2'"
    )
    check("rename from the sidebar", page.locator("#starmenu").count() == 0)
    page.locator("#star-btn").click()
    page.wait_for_selector("#starmenu input")
    check(
        "the star box shows the current nickname",
        page.locator("#starmenu input").input_value() == "Guide v2"
        and "Added" not in page.locator("#starmenu").inner_text(),
    )
    page.locator("#starmenu input").fill("zzz")
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    check(
        "Escape cancels an edit",
        fav_label() == "Guide v2" and page.locator("#starmenu").count() == 0,
    )
    page.locator("#star-btn").click()
    page.locator("#starmenu input").fill("")
    page.mouse.click(700, 500)
    wait_js(
        "document.querySelector('#places section:has([data-section=favorites]) .place-row .label')?.textContent === 'guide.md'"
    )
    check(
        "clearing it and clicking away goes back to the file name, with the folder on the right",
        fav_where() == "docs",
        fav_where(),
    )
    page.locator("#star-btn").click()
    page.locator("#starmenu button", has_text="Remove").click()
    wait_js("!document.querySelector('#places [data-section=favorites]')")

    print("chrome")

    def width():
        return page.evaluate("document.querySelector('#sidebar').offsetWidth")

    before = width()
    box = page.locator("#resizer").bounding_box()
    page.mouse.move(box["x"] + 2, 300)
    page.mouse.down()
    page.mouse.move(box["x"] + 90, 300, steps=4)
    page.mouse.up()
    check("sidebar resizes", width() > before + 60, width())
    page.keyboard.press("Control+\\")
    check("sidebar hides", not page.locator("#sidebar").is_visible())
    page.keyboard.press("Control+\\")
    check("sidebar returns", page.locator("#sidebar").is_visible())
    page.locator("#actions button[aria-label='Switch theme']").click()
    page.wait_for_timeout(100)
    bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
    check("dark theme", bg == "rgb(21, 23, 26)", bg)
    go("docs/guide.md")
    page.wait_for_selector(".md h1")
    snap(page, "10-dark-markdown")
    go("data/big.csv")
    page.wait_for_selector("table.data tbody tr:not(.pad) td")
    snap(page, "11-dark-csv")
    page.reload()
    page.wait_for_selector("table.data tbody tr:not(.pad) td")
    check(
        "theme and route survive reload",
        page.evaluate("document.documentElement.dataset.theme") == "dark"
        and page.url.endswith("big.csv"),
    )

    # Copy must work on plain HTTP, where navigator.clipboard is missing.
    insecure = browser.new_context(viewport={"width": 1000, "height": 700})
    other = insecure.new_page()
    other.add_init_script("Object.defineProperty(navigator, 'clipboard', {value: undefined})")
    other.goto(f"{base}/#/docs/guide.md")
    other.wait_for_selector(".md h1")
    other.locator("#actions button[aria-label='Copy full path']").click()
    other.wait_for_timeout(100)
    check(
        "copy works without the clipboard API",
        other.locator("#actions button[aria-label='Copy full path']").get_attribute("title")
        == "Copied",
    )
    insecure.close()

    print("phone")
    phone = browser.new_context(
        viewport={"width": 390, "height": 780}, has_touch=True, is_mobile=True
    )
    mobile = phone.new_page()
    mobile.goto(f"{base}/#/docs/guide.md")
    mobile.wait_for_selector(".md h1")
    overflow = mobile.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    check("no sideways page scroll", overflow <= 0, overflow)
    mobile.screenshot(path=str(shots / "12-phone.png"))
    mobile.locator("#expand").tap()
    mobile.wait_for_timeout(250)
    box = mobile.locator("#sidebar").bounding_box()
    check("drawer slides in", box["x"] == 0, box)
    mobile.screenshot(path=str(shots / "13-phone-drawer.png"))
    mobile.locator("#tree .row", has_text="config.json").tap()
    mobile.wait_for_timeout(350)
    check("choosing a file closes the drawer", mobile.locator("#sidebar").bounding_box()["x"] < 0)
    phone.close()

    # Console noise that the deliberately broken fixtures cause on purpose.
    # The malicious fixtures try a frame escape and inline handlers; the browser
    # blocking them is the expected outcome (the injection checks above confirm
    # nothing ran).
    expected = (
        "404",
        "416",
        "Failed to load resource",
        "Unsafe attempt to initiate navigation",
        "Executing inline event handler violates the following Content Security Policy",
        "isn't a valid Office file",
    )
    unexpected = [e for e in errors if not any(text in e for text in expected)]
    print("console")
    check("no script errors", not unexpected, unexpected[:5])

    def start_server(*flags):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            free = probe.getsockname()[1]
        proc = subprocess.Popen(
            [sys.executable, "-m", "bunko", str(free), str(demo), "-b", "127.0.0.1", *flags],
            cwd=repo,
            stdout=subprocess.DEVNULL,
            env=ENV,
        )
        atexit.register(proc.terminate)
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{free}/__bunko/logout", timeout=1)
                break
            except urllib.error.HTTPError:
                break
            except OSError:
                time.sleep(0.05)
        return proc, f"http://127.0.0.1:{free}"

    print("token sign-in")
    token_file = shots / "e2e-token"
    proc, url = start_server("--token", "--token-file", str(token_file))
    token = token_file.read_text().strip()
    signin = browser.new_context(viewport={"width": 1000, "height": 700})
    tab = signin.new_page()
    tab.goto(url + "/")
    check("sign-in page first", tab.locator("input[name=token]").count() == 1)
    tab.locator("input[name=token]").fill("wrong")
    tab.locator("button").click()
    check("wrong token is refused", "doesn't match" in tab.content())
    tab.locator("input[name=token]").fill(token)
    tab.locator("button").click()
    tab.wait_for_selector("#tree .row")
    check(
        "right token opens the app",
        tab.url.rstrip("/").endswith(url.split("//")[1]) or "token=" not in tab.url,
    )
    check("token gone from the address bar", "token=" not in tab.url, tab.url)
    tab.reload()
    tab.wait_for_selector("#tree .row")
    check("cookie keeps you signed in", True)
    tab.goto(url + "/#/videos/clip.mp4")
    tab.wait_for_selector("video")
    ok = False
    for _ in range(100):
        if tab.evaluate("document.querySelector('video').readyState >= 1"):
            ok = True
            break
        tab.wait_for_timeout(50)
    check("media requests carry the cookie", ok)
    tab.locator("#settings-btn").click()
    tab.locator("#settings a", has_text="Sign out").click()
    tab.wait_for_selector("input[name=token]")
    check("sign out", True)
    signin.close()
    proc.terminate()
    token_file.unlink()

    print("tailscale identity")
    proc, url = start_server("--allow-user", "me@example.com", "--allow-user", "you@example.com")
    stranger = browser.new_context(
        extra_http_headers={"Tailscale-User-Login": "someone@else.example"}
    )
    tab = stranger.new_page()
    tab.goto(url + "/")
    check("other tailnet users are refused", "No access" in tab.content())
    stranger.close()
    member = browser.new_context(
        extra_http_headers={"Tailscale-User-Login": "me@example.com", "Tailscale-User-Name": "Me"}
    )
    tab = member.new_page()
    tab.goto(url + "/")
    tab.wait_for_selector("#tree .row")
    tab.locator("#settings-btn").click()
    check(
        "allowed user gets in and sees who they are",
        "Signed in as Me" in tab.locator("#settings").inner_text(),
    )
    tab.keyboard.press("Escape")
    tab.goto(url + "/#/config.json")
    tab.wait_for_selector("#star-btn")
    tab.locator("#star-btn").click()
    tab.wait_for_selector("#places [data-section=favorites]")
    member.close()
    other = browser.new_context(extra_http_headers={"Tailscale-User-Login": "you@example.com"})
    tab = other.new_page()
    tab.goto(url + "/#/config.json")
    tab.wait_for_selector("#star-btn")
    tab.wait_for_timeout(500)
    check(
        "each person has their own favorites",
        tab.locator("#places [data-section=favorites]").count() == 0
        and tab.locator("#star-btn.on").count() == 0,
    )
    other.close()
    proc.terminate()

    browser.close()

server.terminate()
print(f"\n{passed} passed, {len(failures)} failed")
for name in failures:
    print("  -", name)
sys.exit(1 if failures else 0)
