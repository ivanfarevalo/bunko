// The search box: file names, or text inside files.

import { api } from "./api.js";
import { $, h } from "./dom.js";
import { icon } from "./icons.js";
import { iconFor } from "./kinds.js";
import { appUrl, baseName, parentOf } from "./paths.js";
import { closeDrawer } from "./sidebar.js";
import { state } from "./state.js";

export const results = $("#results");

export const input = $("#q");

export let searchSeq = 0;

export let selected = -1;

export let searchMode = "names";

export function setSearchMode(mode) {
  searchMode = mode;
  for (const button of document.querySelectorAll(".search-modes button")) {
    button.classList.toggle("on", button.dataset.mode === mode);
    button.setAttribute("aria-selected", button.dataset.mode === mode);
  }
  input.placeholder = mode === "names" ? "Search file names" : "Search inside files";
  if (input.value.trim()) runSearch();
}

export function markSpans(text, spans) {
  const out = [];
  let last = 0;
  for (const [start, end] of spans) {
    if (start < last) continue;
    out.push(text.slice(last, start), h("mark", null, text.slice(start, end)));
    last = end;
  }
  out.push(text.slice(last));
  return out;
}

export async function runContentSearch(query, seq) {
  results.hidden = false;
  $("#browse").hidden = true;
  if (query.length < 2) {
    results.replaceChildren(h("div", { class: "none-found" }, "Type at least 2 characters."));
    return;
  }
  results.replaceChildren(h("div", { class: "none-found" }, "Searching…"));
  const data = await api("grep", { q: query });
  if (seq !== searchSeq) return;
  const files = new Map();
  for (const hit of data.results) {
    if (!files.has(hit.path)) files.set(hit.path, []);
    files.get(hit.path).push(hit);
  }
  const rows = [];
  for (const [path, hits] of files) {
    rows.push(
      h(
        "a",
        { class: "row hit", href: appUrl(path, { line: hits[0].line, q: query }), title: path, onclick: closeDrawer },
        h(
          "span",
          { class: "top" },
          icon(iconFor({ name: baseName(path) })),
          h("span", { class: "label" }, baseName(path)),
        ),
        parentOf(path) && h("span", { class: "where" }, h("bdi", null, parentOf(path))),
      ),
    );
    for (const hit of hits) {
      rows.push(
        h(
          "a",
          { class: "snip", href: appUrl(path, { line: hit.line, q: query }), onclick: closeDrawer },
          h("span", { class: "ln" }, String(hit.line)),
          h("span", { class: "tx" }, markSpans(hit.text, hit.marks)),
        ),
      );
    }
  }
  const total = data.results.length;
  let summary = total
    ? `${total.toLocaleString()} line${total === 1 ? "" : "s"} in ${files.size.toLocaleString()} file${files.size === 1 ? "" : "s"}`
    : "No matches.";
  if (data.truncated) summary += ` · showing the first ${total}`;
  if (data.partial) summary += " · stopped early, so there may be more";
  summary += ` · ${data.engine}, ${data.seconds}s`;
  rows.push(h("div", { class: "none-found" }, summary));
  results.replaceChildren(...rows);
  results.scrollTop = 0;
  selected = -1;
}

export function markMatches(text, tokens) {
  const lower = text.toLowerCase();
  const hit = new Array(text.length).fill(false);
  for (const token of tokens) {
    for (let at = lower.indexOf(token); at !== -1; at = lower.indexOf(token, at + 1)) {
      hit.fill(true, at, at + token.length);
    }
  }
  const out = [];
  for (let start = 0; start < text.length; ) {
    let end = start;
    while (end < text.length && hit[end] === hit[start]) end++;
    const piece = text.slice(start, end);
    out.push(hit[start] ? h("mark", null, piece) : piece);
    start = end;
  }
  return out;
}

export function closeSearch() {
  input.value = "";
  results.hidden = true;
  $("#browse").hidden = false;
  selected = -1;
}

export async function runSearch() {
  const query = input.value.trim();
  const seq = ++searchSeq;
  if (!query) return closeSearch();
  if (searchMode === "contents") return runContentSearch(query, seq);
  const data = await api("search", { q: query });
  if (seq !== searchSeq) return;
  showFooter(data);
  const tokens = query.toLowerCase().split(/\s+/);
  const rows = data.results.map((result) => {
    const isDir = result.endsWith("/");
    const path = isDir ? result.slice(0, -1) : result;
    return h(
      "a",
      { class: "row hit", href: appUrl(path), title: path, onclick: closeDrawer },
      h(
        "span",
        { class: "top" },
        icon(iconFor({ name: baseName(path), dir: isDir })),
        h("span", { class: "label" }, markMatches(baseName(path), tokens)),
      ),
      parentOf(path) && h("span", { class: "where" }, h("bdi", null, parentOf(path))),
    );
  });
  if (!rows.length) {
    const hint = data.indexing ? "Still indexing, so more results may appear." : "No files match.";
    rows.push(h("div", { class: "none-found" }, hint));
  }
  results.replaceChildren(...rows);
  results.scrollTop = 0;
  results.hidden = false;
  $("#browse").hidden = true;
  selected = -1;
}

export function moveSelection(step) {
  const hits = [...results.querySelectorAll(".hit, .snip")];
  if (!hits.length) return;
  if (hits[selected]) hits[selected].classList.remove("sel");
  selected = (selected + step + hits.length) % hits.length;
  hits[selected].classList.add("sel");
  hits[selected].scrollIntoView({ block: "nearest" });
}

export let searchTimer;

export function showFooter(info) {
  const count = info.indexed.toLocaleString();
  let text = info.indexing ? `Indexing… ${count} items` : `${count} items indexed`;
  if (info.truncated) text += " (index full)";
  $("#foot-text").textContent = text;
  $("#foot-text").title = state.config.root;
}

export async function watchIndexing() {
  const info = await api("config");
  showFooter(info);
  if (info.indexing) setTimeout(watchIndexing, 2000);
}

export function setupSearch() {
  input.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(runSearch, searchMode === "names" ? 120 : 350);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      moveSelection(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      moveSelection(-1);
    } else if (event.key === "Enter") {
      const hits = results.querySelectorAll(".hit, .snip");
      const target = hits[Math.max(selected, 0)];
      if (target) {
        location.hash = target.getAttribute("href");
        closeDrawer();
      }
    } else if (event.key === "Escape") {
      closeSearch();
      input.blur();
    }
  });
}
