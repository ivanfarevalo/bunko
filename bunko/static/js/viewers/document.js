// Markdown and Word documents, with an outline beside them.

import { API, api } from "../api.js";
import { copyText, h, notice } from "../dom.js";
import { slugify } from "../format.js";
import { icon } from "../icons.js";
import { HIGHLIGHT_MAX } from "../limits.js";
import { rawUrl } from "../paths.js";
import { view } from "../state.js";
import { setSetting, settings } from "../store.js";
import { codeBlock } from "./text.js";

export function fixRelativeUrls(root, path) {
  const base = new URL(rawUrl(path), location.origin);
  for (const node of root.querySelectorAll("img[src], video[src], audio[src], source[src]")) {
    const url = new URL(node.getAttribute("src"), base);
    if (url.origin === location.origin) node.src = url.pathname + url.search;
    if (node.tagName === "IMG") node.loading = "lazy";
  }
  for (const link of root.querySelectorAll("a[href]")) {
    const href = link.getAttribute("href");
    if (href.startsWith("#")) {
      const id = decodeURIComponent(href.slice(1));
      link.addEventListener("click", (event) => {
        event.preventDefault();
        const target = document.getElementById(id);
        if (target) target.scrollIntoView();
      });
      continue;
    }
    const url = new URL(href, base);
    if (url.origin === location.origin) {
      link.setAttribute("href", `#${url.pathname.replace(/\/$/, "")}`);
    } else {
      link.target = "_blank";
      link.rel = "noopener";
    }
  }
}

export function renderMarkdown(source, path) {
  const box = h("article", { class: "md" });
  let body = source;
  const front = /^---\r?\n[\s\S]*?\r?\n---\r?\n/.exec(source);
  if (front) {
    body = source.slice(front[0].length);
    const yaml = front[0].replace(/^---\r?\n|\r?\n---\r?\n$/g, "");
    box.append(h("details", { class: "front" }, h("summary", null, "Front matter"), codeBlock(yaml, "yaml")));
  }
  const content = h("div");
  // Sanitized because these documents can come from anywhere, and they would
  // otherwise run with access to everything this server can read.
  content.innerHTML = DOMPurify.sanitize(marked.parse(body, { gfm: true }), { ADD_ATTR: ["target"] });

  const used = new Map();
  for (const heading of content.querySelectorAll("h1,h2,h3,h4,h5,h6")) {
    const slug = slugify(heading.textContent);
    const seen = used.get(slug) || 0;
    used.set(slug, seen + 1);
    heading.id = seen ? `${slug}-${seen}` : slug;
  }
  decorateBlocks(content);
  fixRelativeUrls(content, path);
  box.append(...content.childNodes);
  return box;
}

// Code blocks get highlighting and a copy button; tables scroll sideways.
export function decorateBlocks(content) {
  for (const pre of [...content.querySelectorAll("pre")]) {
    const code = pre.querySelector("code");
    if (code) {
      const language = /language-([\w+-]+)/.exec(code.className);
      if (language && hljs.getLanguage(language[1]) && code.textContent.length <= HIGHLIGHT_MAX)
        hljs.highlightElement(code);
    }
    const copy = h("button", { class: "copy" }, "Copy");
    copy.addEventListener("click", async () => {
      await copyText(pre.textContent);
      copy.textContent = "Copied";
      setTimeout(() => {
        copy.textContent = "Copy";
      }, 1200);
    });
    const block = h("div", { class: "block" });
    pre.replaceWith(block);
    block.append(pre, copy);
  }
  for (const table of [...content.querySelectorAll("table")]) {
    const wrap = h("div", { class: "tbl" });
    table.replaceWith(wrap);
    wrap.append(table);
  }
}

export function highlightText(root, query) {
  const needle = query.toLowerCase();
  const marks = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const node of nodes) {
    const text = node.nodeValue;
    const lower = text.toLowerCase();
    let at = lower.indexOf(needle);
    if (at < 0 || lower.length !== text.length) continue;
    const pieces = document.createDocumentFragment();
    let last = 0;
    while (at >= 0) {
      const mark = h("mark", { class: "find" }, text.slice(at, at + needle.length));
      pieces.append(text.slice(last, at), mark);
      marks.push(mark);
      last = at + needle.length;
      at = lower.indexOf(needle, last);
    }
    pieces.append(text.slice(last));
    node.replaceWith(pieces);
  }
  return marks;
}

export function buildOutline(headings, ctx) {
  const links = headings.map((heading) =>
    h(
      "a",
      {
        class: `toc-link lvl${heading.tagName[1]}`,
        href: "#",
        onclick: (event) => {
          event.preventDefault();
          heading.scrollIntoView({ block: "start" });
        },
      },
      heading.textContent,
    ),
  );
  const spy = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const at = headings.indexOf(entry.target);
        for (const [index, link] of links.entries()) link.classList.toggle("on", index === at);
      }
    },
    { root: view, rootMargin: "0px 0px -70% 0px" },
  );
  ctx.mounted.push(() => {
    for (const heading of headings) spy.observe(heading);
  });
  ctx.cleanup.push(() => spy.disconnect());
  return h(
    "nav",
    { class: "toc", "aria-label": "On this page" },
    h("div", { class: "toc-title" }, "On this page"),
    links,
  );
}

export const narrow = () => matchMedia("(max-width: 1100px)").matches;

export async function viewMarkdown(ctx) {
  const response = await fetch(rawUrl(ctx.path));
  const source = await response.text();
  if (!ctx.alive()) return;
  const article = renderMarkdown(source, ctx.path);
  showArticle(ctx, article);

  // Opened from a content search: mark the term and go to the matching spot.
  const query = ctx.params.get("q");
  if (query) {
    const marks = highlightText(article, query);
    const line = Number(ctx.params.get("line")) || 0;
    const before = source
      .split("\n")
      .slice(0, Math.max(line - 1, 0))
      .join("\n")
      .toLowerCase();
    let skip = 0;
    for (let at = before.indexOf(query.toLowerCase()); at >= 0; at = before.indexOf(query.toLowerCase(), at + 1))
      skip++;
    markCurrent(ctx, marks[Math.min(skip, marks.length - 1)]);
  }
}

export function markCurrent(ctx, target) {
  if (!target) return;
  target.classList.add("current");
  ctx.mounted.push(() => target.scrollIntoView({ block: "center" }));
}

// A rendered document in the page column, with the outline beside it when it
// has enough headings to need one.
export function showArticle(ctx, article) {
  const page = h("div", { class: "page" }, article);
  const headings = [...article.querySelectorAll("h1, h2, h3")];
  if (headings.length >= 2) {
    const layout = h("div", { class: `doc${settings.toc ? " toc-on" : ""}` }, page, buildOutline(headings, ctx));
    ctx.actions.push(
      h(
        "button",
        {
          class: "icon-btn",
          title: "Outline",
          "aria-label": "Show or hide the outline",
          onclick: () => {
            if (narrow()) return layout.classList.toggle("toc-overlay");
            setSetting("toc", !settings.toc);
            layout.classList.toggle("toc-on", settings.toc);
          },
        },
        icon("toc"),
      ),
    );
    ctx.el.append(layout);
  } else {
    ctx.el.append(page);
  }
}

// Word documents arrive as HTML converted on the server (bunko/office).
export async function viewDocx(ctx) {
  const data = await api("office", { path: ctx.path });
  if (!ctx.alive()) return;
  const article = h("article", { class: "md docx" });
  // Built from escaped text on the server, and sanitized again here.
  article.innerHTML = DOMPurify.sanitize(data.html);
  if (!article.textContent.trim() && !article.querySelector("img")) {
    ctx.el.append(notice("text", "This document is empty"));
    return;
  }
  for (const image of article.querySelectorAll("img[data-part]")) {
    image.src = `${API}office-part?${new URLSearchParams({ path: ctx.path, part: image.dataset.part, v: ctx.stat.mtime })}`;
  }
  const used = new Map();
  for (const heading of article.querySelectorAll("h1,h2,h3,h4,h5,h6")) {
    const slug = `doc-${slugify(heading.textContent)}`;
    const seen = used.get(slug) || 0;
    used.set(slug, seen + 1);
    if (!heading.id) heading.id = seen ? `${slug}-${seen}` : slug;
  }
  decorateBlocks(article);
  fixRelativeUrls(article, ctx.path);
  showArticle(ctx, article);
  const query = ctx.params.get("q");
  if (query) markCurrent(ctx, highlightText(article, query)[0]);
}
