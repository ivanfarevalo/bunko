"use strict";

const API = "/__shelf/api/";
const TEXT_CHUNK = 1 << 20;   // bytes of a text file shown per step
const CSV_CHUNK = 8 << 20;    // bytes of a table parsed per step
const HIGHLIGHT_MAX = 256 << 10;
const AUTO_RELOAD_MAX = 2 << 20;
const JUMP_MAX = 64 << 20;    // how far a jump-to-line will read into a file
const TREE_PAGE = 300;        // children drawn per folder before "Show more"
const BATCH = 200;            // folder items drawn per scroll step
const ROW_H = 31;             // table row height including its border
const POLL_MS = 2500;

// ---------- helpers ----------

const $ = (selector) => document.querySelector(selector);

function h(tag, props, ...kids) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "class") node.className = value;
    else if (key in node && key !== "list") node[key] = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  node.append(...kids.flat().filter((kid) => kid !== null && kid !== undefined && kid !== false));
  return node;
}

const ICONS = {
  folder: "M4 7a2 2 0 0 1 2-2h3.500l2 2.500H18a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z",
  file: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5",
  text: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M9 13h6M9 17h6",
  code: "m8 8-5 4 5 4M16 8l5 4-5 4M14 5l-4 14",
  image: "M5 4h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM8.500 11a1.500 1.500 0 1 0 0-3 1.500 1.500 0 0 0 0 3zM21 16l-5-5-9 9",
  video: "M4 6h11a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2zM17 11l5-3v8l-5-3",
  audio: "M9 18V6l11-2v12M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM20 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0z",
  table: "M4 4h16a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zM3 10h18M3 15h18M9 10v10M15 10v10",
  globe: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM3 12h18M12 3c2.500 2.500 3.800 5.500 3.800 9s-1.300 6.500-3.800 9c-2.500-2.500-3.800-5.500-3.800-9S9.500 5.500 12 3z",
  pdf: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M9 17v-4h1.500a1.200 1.200 0 0 1 0 2.500H9",
  chevron: "m9 6 6 6-6 6",
  left: "m15 6-6 6 6 6",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.300-4.300",
  panel: "M5 4h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM9 4v16",
  external: "M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
  download: "M12 4v12M7 11l5 5 5-5M4 20h16",
  copy: "M10 9h9a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-9a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1zM5 15H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v1",
  theme: "M20.500 14.500A8.500 8.500 0 1 1 9.500 3.500a7 7 0 0 0 11 11z",
  list: "M8 6h12M8 12h12M8 18h12M4 6h.010M4 12h.010M4 18h.010",
  grid: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
  alert: "M12 3 2 20h20zM12 10v4M12 17h.010",
  toc: "M4 6h16M8 12h12M8 18h12M4 12h.010M4 18h.010",
  gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.400 15a1.700 1.700 0 0 0 .300 1.800l.100.100a2 2 0 1 1-2.800 2.800l-.100-.100a1.700 1.700 0 0 0-1.800-.300 1.700 1.700 0 0 0-1 1.500V21a2 2 0 1 1-4 0v-.100a1.700 1.700 0 0 0-1.100-1.500 1.700 1.700 0 0 0-1.800.300l-.100.100a2 2 0 1 1-2.800-2.800l.100-.100a1.700 1.700 0 0 0 .300-1.800 1.700 1.700 0 0 0-1.500-1H3a2 2 0 1 1 0-4h.100a1.700 1.700 0 0 0 1.500-1.100 1.700 1.700 0 0 0-.300-1.800l-.100-.100a2 2 0 1 1 2.800-2.800l.100.100a1.700 1.700 0 0 0 1.800.300H9a1.700 1.700 0 0 0 1-1.500V3a2 2 0 1 1 4 0v.100a1.700 1.700 0 0 0 1 1.500 1.700 1.700 0 0 0 1.800-.300l.100-.100a2 2 0 1 1 2.800 2.800l-.100.100a1.700 1.700 0 0 0-.300 1.800V9a1.700 1.700 0 0 0 1.500 1H21a2 2 0 1 1 0 4h-.100a1.700 1.700 0 0 0-1.500 1z",
  play: "M7 4.500v15l12-7.500z",
  pause: "M8 5v14M16 5v14",
  star: "M12 3.500l2.600 5.300 5.900.900-4.300 4.100 1 5.800L12 16.900l-5.200 2.700 1-5.800L3.500 9.700l5.900-.900z",
  tag: "M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9zM7.500 7.500h.010",
  link: "M10 14a4 4 0 0 0 5.700 0l3-3a4 4 0 0 0-5.700-5.700l-1 1M14 10a4 4 0 0 0-5.700 0l-3 3a4 4 0 0 0 5.700 5.700l1-1",
};

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "i");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", ICONS[name]);
  svg.append(path);
  return svg;
}

const store = {
  get(key, fallback) {
    try {
      const value = localStorage.getItem("shelf." + key);
      return value === null ? fallback : JSON.parse(value);
    } catch (e) { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem("shelf." + key, JSON.stringify(value)); } catch (e) { /* private mode */ }
  },
};

// Viewer preferences, kept per browser. Every one has an off switch in Settings.
const DEFAULT_SETTINGS = { toc: true, jsonlTable: true, thumbnails: true, liveReload: true };
const settings = Object.assign({}, DEFAULT_SETTINGS, store.get("settings", {}));
function setSetting(key, value) {
  settings[key] = value;
  store.set("settings", settings);
}

const encodePath = (path) => path.split("/").map(encodeURIComponent).join("/");
const rawUrl = (path) => "/" + encodePath(path);
// Paths are percent-encoded, so a literal "?" can only start the parameters:
// #/notes/plan.md?line=42&q=term or #/clips/a.mp4?t=12.5
const appUrl = (path, params) => "#/" + encodePath(path) + (params ? "?" + new URLSearchParams(params) : "");
const baseName = (path) => path.split("/").pop();
const parentOf = (path) => path.split("/").slice(0, -1).join("/");
const join = (dir, name) => (dir ? dir + "/" + name : name);
const extOf = (name) => (name.includes(".") ? name.split(".").pop().toLowerCase() : "");

function formatSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = -1;
  do { value /= 1024; unit++; } while (value >= 1024 && unit < units.length - 1);
  return value.toFixed(value < 10 ? 1 : 0) + " " + units[unit];
}

function formatWhen(seconds) {
  const date = new Date(seconds * 1000);
  const age = (Date.now() - date) / 1000;
  if (age < 60) return "just now";
  if (age < 3600) return Math.floor(age / 60) + " min ago";
  if (age < 86400) return Math.floor(age / 3600) + " hr ago";
  if (age < 86400 * 7) return Math.floor(age / 86400) + " d ago";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

async function api(name, params) {
  const response = await fetch(API + name + "?" + new URLSearchParams(params || {}));
  let data = {};
  try { data = await response.json(); } catch (e) { /* not JSON */ }
  if (response.status === 401 || (response.status === 403 && ["no-identity", "not-allowed"].includes(data.error))) {
    location.reload();  // the server answers a page load with its sign-in page
  }
  if (!response.ok) throw Object.assign(new Error(data.error || "request failed"), { status: response.status });
  return data;
}

async function fetchRange(path, start, length) {
  const response = await fetch(rawUrl(path), { headers: { Range: `bytes=${start}-${start + length - 1}` } });
  if (response.status === 416) return new Uint8Array(0);
  if (!response.ok) throw new Error("could not read file");
  return new Uint8Array(await response.arrayBuffer());
}

// navigator.clipboard only exists on HTTPS and localhost, and this usually runs
// over plain HTTP on a remote host.
async function copyText(text) {
  if (navigator.clipboard) {
    try { await navigator.clipboard.writeText(text); return; } catch (e) { /* fall through */ }
  }
  const area = h("textarea", { value: text, style: "position:fixed;opacity:0" });
  document.body.append(area);
  area.select();
  document.execCommand("copy");
  area.remove();
}

// ---------- file kinds ----------

const KINDS = {};
for (const [kind, list] of Object.entries({
  image: "png jpg jpeg gif webp avif svg bmp ico",
  video: "mp4 webm mov m4v ogv mkv",
  audio: "mp3 wav ogg oga m4a flac aac opus",
  md: "md markdown mdown mkd",
  html: "html htm",
  csv: "csv tsv",
  pdf: "pdf",
  json: "json geojson",
  jsonl: "jsonl ndjson",
  docx: "docx docm dotx dotm",
  xlsx: "xlsx xlsm xltx xltm",
  binary: "doc xls xlsb ppt pptx",
})) for (const ext of list.split(" ")) KINDS[ext] = kind;

const CODE_EXTS = new Set("py js mjs ts tsx jsx c h cc cpp hpp cu rs go java rb sh bash zsh sql yaml yml toml ini cfg css scss xml lua r kt swift php pl proto cmake".split(" "));
const kindOf = (name) => KINDS[extOf(name)] || "text";

function iconFor(entry) {
  if (entry.dir) return "folder";
  const kind = kindOf(entry.name);
  if (kind === "md") return "text";
  if (kind === "html") return "globe";
  if (kind === "csv" || kind === "jsonl" || kind === "xlsx") return "table";
  if (kind === "docx") return "text";
  if (kind === "binary") return "file";
  if (kind === "json") return "code";
  if (kind !== "text") return kind;
  const ext = extOf(entry.name);
  if (CODE_EXTS.has(ext)) return "code";
  return ["txt", "log", ""].includes(ext) ? "text" : "file";
}

function languageFor(name) {
  const lower = name.toLowerCase();
  if (lower === "cmakelists.txt") return "cmake";
  if (lower === "dockerfile") return "dockerfile";
  if (lower === "makefile") return "makefile";
  const aliases = { h: "cpp", hpp: "cpp", cu: "cpp", cc: "cpp", yml: "yaml", toml: "ini", cfg: "ini", jsonl: "json", ndjson: "json", svg: "xml" };
  const ext = extOf(name);
  const language = aliases[ext] || ext;
  return language && hljs.getLanguage(language) ? language : null;
}

// ---------- app state ----------

const state = {
  config: null,
  path: "",
  stat: null,
  watch: "",        // the file whose changes refresh the view
  kind: null,
  reload: null,     // a viewer's own in-place refresh, if it has one
  token: 0,         // bumped per navigation so stale async work can stand down
  cleanup: [],
};

const view = $("#view");
const tree = { children: new Map(), open: new Set(store.get("open", [])), limit: new Map() };

// ---------- sidebar tree ----------

async function loadChildren(path) {
  try {
    const { entries } = await api("list", { path });
    tree.children.set(path, entries);
    return entries;
  } catch (error) {
    tree.children.set(path, []);
    tree.open.delete(path);
    return [];
  }
}

function saveOpen() { store.set("open", [...tree.open]); }

function treeRows(dir, depth, rows) {
  const entries = tree.children.get(dir) || [];
  const limit = tree.limit.get(dir) || TREE_PAGE;
  for (const entry of entries.slice(0, limit)) {
    const path = join(dir, entry.name);
    const isOpen = entry.dir && tree.open.has(path);
    const chevron = h("span", {
      class: "chev" + (isOpen ? " open" : "") + (entry.dir ? "" : " none"),
      role: "button",
      "aria-label": isOpen ? "Collapse" : "Expand",
      onclick: (event) => { event.preventDefault(); event.stopPropagation(); toggleDir(path); },
    }, icon("chevron"));
    rows.push(h("a", {
      class: "row" + (path === state.path ? " current" : ""),
      href: appUrl(path),
      style: "--d:" + depth,
      title: entry.name,
      "data-path": path,
      onclick: () => {
        if (entry.dir && !isOpen) toggleDir(path);
        closeDrawer();
      },
    }, chevron, icon(iconFor(entry)), h("span", { class: "label" }, entry.name)));
    if (isOpen) {
      if (!tree.children.has(path)) rows.push(h("div", { class: "row empty", style: `--d:${depth + 2}` }, "Loading…"));
      else if (!tree.children.get(path).length) rows.push(h("div", { class: "row empty", style: `--d:${depth + 2}` }, "Empty"));
      else treeRows(path, depth + 1, rows);
    }
  }
  if (entries.length > limit) {
    rows.push(h("div", {
      class: "row more",
      style: `--d:${depth + 1}`,
      onclick: () => { tree.limit.set(dir, limit + TREE_PAGE * 3); renderTree(); },
    }, `Show ${Math.min(TREE_PAGE * 3, entries.length - limit).toLocaleString()} more of ${(entries.length - limit).toLocaleString()}`));
  }
}

function renderTree() {
  const rows = [];
  treeRows("", 0, rows);
  $("#tree").replaceChildren(...rows);
}

async function toggleDir(path) {
  if (tree.open.has(path)) {
    tree.open.delete(path);
    saveOpen();
    renderTree();
    return;
  }
  tree.open.add(path);
  saveOpen();
  renderTree();
  await loadChildren(path);
  renderTree();
}

async function revealInTree(path, isDir, scroll = true) {
  const parts = path.split("/").filter(Boolean);
  let dir = "";
  for (const part of isDir ? parts : parts.slice(0, -1)) {
    dir = join(dir, part);
    tree.open.add(dir);
    if (!tree.children.has(dir)) await loadChildren(dir);
  }
  // A deep link can land past the "Show more" cut-off.
  const siblings = tree.children.get(parentOf(path)) || [];
  const position = siblings.findIndex((entry) => entry.name === baseName(path));
  if (position >= (tree.limit.get(parentOf(path)) || TREE_PAGE)) tree.limit.set(parentOf(path), position + 50);
  saveOpen();
  renderTree();
  const row = [...document.querySelectorAll("#tree .row[data-path]")].find((node) => node.dataset.path === path);
  if (row && scroll) row.scrollIntoView({ block: "nearest" });
}

async function refreshOpenFolders() {
  await Promise.all(["", ...tree.open].map(loadChildren));
  renderTree();
}

// ---------- search ----------

const results = $("#results");
const input = $("#q");
let searchSeq = 0;
let selected = -1;
let searchMode = "names";

function setSearchMode(mode) {
  searchMode = mode;
  for (const button of document.querySelectorAll(".search-modes button")) {
    button.classList.toggle("on", button.dataset.mode === mode);
    button.setAttribute("aria-selected", button.dataset.mode === mode);
  }
  input.placeholder = mode === "names" ? "Search file names" : "Search inside files";
  if (input.value.trim()) runSearch();
}

function markSpans(text, spans) {
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

async function runContentSearch(query, seq) {
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
    rows.push(h("a", { class: "row hit", href: appUrl(path, { line: hits[0].line, q: query }), title: path, onclick: closeDrawer },
      h("span", { class: "top" }, icon(iconFor({ name: baseName(path) })), h("span", { class: "label" }, baseName(path))),
      parentOf(path) && h("span", { class: "where" }, h("bdi", null, parentOf(path)))));
    for (const hit of hits) {
      rows.push(h("a", { class: "snip", href: appUrl(path, { line: hit.line, q: query }), onclick: closeDrawer },
        h("span", { class: "ln" }, String(hit.line)), h("span", { class: "tx" }, markSpans(hit.text, hit.marks))));
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

function markMatches(text, tokens) {
  const lower = text.toLowerCase();
  const hit = new Array(text.length).fill(false);
  for (const token of tokens) {
    for (let at = lower.indexOf(token); at !== -1; at = lower.indexOf(token, at + 1)) {
      hit.fill(true, at, at + token.length);
    }
  }
  const out = [];
  for (let start = 0; start < text.length;) {
    let end = start;
    while (end < text.length && hit[end] === hit[start]) end++;
    const piece = text.slice(start, end);
    out.push(hit[start] ? h("mark", null, piece) : piece);
    start = end;
  }
  return out;
}

function closeSearch() {
  input.value = "";
  results.hidden = true;
  $("#browse").hidden = false;
  selected = -1;
}

async function runSearch() {
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
    return h("a", { class: "row hit", href: appUrl(path), title: path, onclick: closeDrawer },
      h("span", { class: "top" }, icon(iconFor({ name: baseName(path), dir: isDir })),
        h("span", { class: "label" }, markMatches(baseName(path), tokens))),
      parentOf(path) && h("span", { class: "where" }, h("bdi", null, parentOf(path))));
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

function moveSelection(step) {
  const hits = [...results.querySelectorAll(".hit, .snip")];
  if (!hits.length) return;
  if (hits[selected]) hits[selected].classList.remove("sel");
  selected = (selected + step + hits.length) % hits.length;
  hits[selected].classList.add("sel");
  hits[selected].scrollIntoView({ block: "nearest" });
}

let searchTimer;
input.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(runSearch, searchMode === "names" ? 120 : 350);
});
input.addEventListener("keydown", (event) => {
  if (event.key === "ArrowDown") { event.preventDefault(); moveSelection(1); }
  else if (event.key === "ArrowUp") { event.preventDefault(); moveSelection(-1); }
  else if (event.key === "Enter") {
    const hits = results.querySelectorAll(".hit, .snip");
    const target = hits[Math.max(selected, 0)];
    if (target) { location.hash = target.getAttribute("href"); closeDrawer(); }
  } else if (event.key === "Escape") { closeSearch(); input.blur(); }
});

function showFooter(info) {
  const count = info.indexed.toLocaleString();
  let text = info.indexing ? `Indexing… ${count} items` : `${count} items indexed`;
  if (info.truncated) text += " (index full)";
  $("#foot-text").textContent = text;
  $("#foot-text").title = state.config.root;
}

async function watchIndexing() {
  const info = await api("config");
  showFooter(info);
  if (info.indexing) setTimeout(watchIndexing, 2000);
}

// ---------- top bar ----------

function renderChrome() {
  const { path, stat } = state;
  const crumbs = [h("a", { href: "#/" }, state.config.name)];
  let walked = "";
  for (const part of path.split("/").filter(Boolean)) {
    walked = join(walked, part);
    crumbs.push(h("span", { class: "sep" }, "/"), h("a", { href: appUrl(walked), title: part }, part));
  }
  $("#crumbs").replaceChildren(...crumbs);

  const meta = stat && stat.type === "file"
    ? `${formatSize(stat.size)} · ${formatWhen(stat.mtime)}`
    : "";
  $("#meta").textContent = meta;
  $("#meta").title = stat ? new Date(stat.mtime * 1000).toLocaleString() : "";

  const isFile = stat && stat.type === "file";
  const absolute = path ? state.config.root + "/" + path : state.config.root;
  const copyButton = h("button", { class: "icon-btn", title: "Copy full path", "aria-label": "Copy full path" }, icon("copy"));
  copyButton.addEventListener("click", async () => {
    await copyText(absolute);
    copyButton.title = "Copied";
    setTimeout(() => { copyButton.title = "Copy full path"; }, 1500);
  });
  $("#actions").replaceChildren(...[
    isFile && h("a", { class: "icon-btn", href: rawUrl(path), target: "_blank", rel: "noopener", title: "Open raw file in a new tab", "aria-label": "Open raw file" }, icon("external")),
    isFile && h("a", { class: "icon-btn", href: rawUrl(path), download: baseName(path), title: "Download", "aria-label": "Download" }, icon("download")),
    path && stat && h("button", { id: "star-btn", class: "icon-btn star", onclick: (event) => openStarMenu(event.currentTarget, path) }, icon("star")),
    path && stat && h("button", { id: "tag-btn", class: "icon-btn", title: "Tags", "aria-label": "Tags", onclick: (event) => openTagMenu(event.currentTarget, path) }, icon("tag")),
    copyButton,
    h("button", { class: "icon-btn", title: "Switch light / dark", "aria-label": "Switch theme", onclick: toggleTheme }, icon("theme")),
  ].filter(Boolean));
  document.title = (path ? baseName(path) : state.config.name) + " · shelf";
  renderPlaceActions();
  renderPlaces();
}

function setTheme(mode) {
  const root = document.documentElement;
  if (mode === "system") delete root.dataset.theme;
  else root.dataset.theme = mode;
  store.set("theme", mode === "system" ? null : mode);
}

function toggleTheme() {
  const root = document.documentElement;
  const dark = root.dataset.theme
    ? root.dataset.theme === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  setTheme(dark ? "light" : "dark");
}

const SHORTCUTS = [
  ["Ctrl/⌘ K", "Search file names"],
  ["Ctrl/⌘ Shift F", "Search inside files"],
  ["Ctrl/⌘ \\", "Show or hide the sidebar"],
  ["← →", "Previous / next image or video"],
  ["Space or K", "Play / pause"],
  [", .", "Previous / next frame"],
  ["J L", "Back / forward 1 s (Shift: 5 s)"],
  ["[ ]", "Slower / faster"],
  ["T", "Copy a link to this moment"],
];

function closeSettings() {
  const panel = $("#settings");
  if (panel) panel.remove();
  document.removeEventListener("pointerdown", settingsOutside, true);
}

function settingsOutside(event) {
  if (!event.target.closest("#settings, #settings-btn")) closeSettings();
}

// ---------- recent, favorites, tags ----------

const places = {
  data: { recent: [], favorites: [], tags: [], tagged: {} },
  collapsed: new Set(store.get("placesCollapsed", [])),
};
const RECENT_SHOWN = 10;

function toast(message) {
  const note = h("div", { class: "toast", role: "status" }, message);
  document.body.append(note);
  setTimeout(() => note.remove(), 3500);
}

async function loadPlaces() {
  try { places.data = await api("places"); } catch (e) { /* older server, or no access */ }
  renderPlaces();
  renderPlaceActions();
}

async function changePlaces(change, { quiet = false } = {}) {
  let response;
  try {
    response = await fetch(API + "places", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Shelf-Request": "1" },
      body: JSON.stringify(change),
    });
  } catch (e) {
    if (!quiet) toast("Couldn't reach the server.");
    return false;
  }
  let data = {};
  try { data = await response.json(); } catch (e) { /* not JSON */ }
  if (response.status === 401) { location.reload(); return false; }
  if (!response.ok) {
    if (!quiet) toast(data.error || "Couldn't save that.");
    return false;
  }
  places.data = data;
  renderPlaces();
  renderPlaceActions();
  return true;
}

const tagsOf = (path) => places.data.tagged[path] || [];

function tagColor(name) {
  let hash = 0;
  for (const char of name.toLowerCase()) hash = (hash * 31 + char.codePointAt(0)) >>> 0;
  return `hsl(${hash % 360} 55% 52%)`;
}

function tagDot(name) {
  return h("span", { class: "dot", style: `--tag:${tagColor(name)}` });
}

const favoriteOf = (path) => places.data.favorites.find((item) => item.path === path);

function closeStarMenu() {
  const menu = $("#starmenu");
  if (menu) menu.remove();
  document.removeEventListener("pointerdown", starMenuOutside, true);
}

function starMenuOutside(event) {
  const menu = $("#starmenu");
  if (event.target.closest("#starmenu") || (menu && menu.anchor && menu.anchor.contains(event.target))) return;
  if (menu && menu.save) menu.save();  // clicking away keeps what was typed
  else closeStarMenu();
}

// Put a popover next to whatever opened it, inside the window: below and
// right-aligned when there's room (the top bar), otherwise shifted or flipped
// above (the sidebar, the bottom of the screen).
function placePopover(menu, anchor) {
  const box = anchor.getBoundingClientRect();
  const width = menu.offsetWidth;
  const height = menu.offsetHeight;
  const left = Math.min(Math.max(box.right - width, 8), window.innerWidth - width - 8);
  let top = box.bottom + 6;
  if (top + height > window.innerHeight - 8) top = Math.max(box.top - height - 6, 8);
  menu.style.left = left + "px";
  menu.style.top = top + "px";
}

// One box for a favorite's nickname, opened from the star in the top bar or
// from ✎ on the favorite in the sidebar. The star adds the favorite first.
async function openStarMenu(anchor, path) {
  const open = $("#starmenu");
  if (open) {
    const same = open.anchor === anchor;
    closeStarMenu();
    if (same) return;  // a second click on the same button closes it
  }
  const added = !favoriteOf(path);
  if (added && !(await changePlaces({ op: "favorite", path, on: true }))) return;
  const entry = favoriteOf(path) || {};
  const field = h("input", {
    type: "text", value: entry.name || "", placeholder: baseName(path),
    maxLength: 60, "aria-label": "Nickname",
  });
  let saving = false;
  async function save() {
    if (saving) return;
    saving = true;
    const name = field.value.trim();
    const current = (favoriteOf(path) || {}).name || "";
    if (favoriteOf(path) && name !== current) await changePlaces({ op: "rename-favorite", path, name });
    closeStarMenu();
  }
  field.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); save(); }
    else if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeStarMenu(); }
  });
  const menu = h("div", { id: "starmenu", class: "popover tagmenu", role: "dialog", "aria-label": "Favorite" },
  h("div", { class: "pop-title" }, added ? "Added to favorites" : "Favorite"),
  h("div", { class: "pop-path", title: path }, path),
  h("div", { class: "pop-label" }, "Nickname, optional"),
  field,
  h("div", { class: "hint" }, "Shown in Favorites in place of the file name."),
  h("div", { class: "pop-actions" },
    h("button", { class: "btn quiet", onclick: async () => { await changePlaces({ op: "favorite", path, on: false }); closeStarMenu(); } }, "Remove"),
    h("button", { class: "btn primary", onclick: save }, "Done")));
  menu.save = save;
  menu.anchor = anchor;
  document.body.append(menu);
  placePopover(menu, anchor);
  field.focus();
  field.select();
  document.addEventListener("pointerdown", starMenuOutside, true);
}

function renameFavorite(item, event) {
  openStarMenu(event.currentTarget, item.path);
}

function renderPlaceActions() {
  const path = state.path;
  const star = $("#star-btn");
  if (star) {
    const entry = favoriteOf(path);
    const on = Boolean(entry);
    star.classList.toggle("on", on);
    star.title = on ? `Favorite${entry.name ? ": " + entry.name : ""} (click to rename or remove)` : "Add to favorites";
    star.setAttribute("aria-label", star.title);
    star.setAttribute("aria-pressed", on);
  }
  const chips = tagsOf(path).map((name) => h("span", { class: "chip", title: "Tagged " + name }, tagDot(name), name));
  $("#chips").replaceChildren(...chips);
}

function toggleSection(key) {
  if (places.collapsed.has(key)) places.collapsed.delete(key);
  else places.collapsed.add(key);
  store.set("placesCollapsed", [...places.collapsed]);
  renderPlaces();
}

function rowButton(action, item, glyph) {
  return h("button", {
    class: "row-x", title: action.label, "aria-label": action.label,
    onclick: (event) => { event.preventDefault(); event.stopPropagation(); action.run(item, event); },
  }, glyph);
}

function placeRow(item, remove, edit) {
  const name = baseName(item.path);
  // A nickname takes the main spot, so the right side shows the whole path.
  const shown = item.name || name;
  const where = item.name ? item.path : parentOf(item.path);
  return h("a", {
    class: "row place-row" + (item.path === state.path ? " current" : "") + (item.missing ? " missing" : ""),
    href: appUrl(item.path),
    title: item.missing ? item.path + " (not found)" : item.path,
    "data-path": item.path,
    onclick: () => {
      if (item.path !== state.path) state.fromSections = true;
      closeDrawer();
    },
  },
  icon(item.missing ? "alert" : iconFor({ name, dir: item.dir })),
  h("span", { class: "label" + (item.name ? " nick" : "") }, shown),
  where && h("span", { class: "where-inline" }, h("bdi", null, where)),
  (remove || edit) && h("span", { class: "row-tools" },
    edit && rowButton(edit, item, "✎"),
    remove && rowButton(remove, item, "×")));
}

function placeSection(key, title, items, { remove, edit, tools = [], limit } = {}) {
  if (!items.length) return null;
  const open = !places.collapsed.has(key);
  const head = h("div", {
    class: "place-head", role: "button", tabindex: 0, "aria-expanded": String(open), "data-section": key,
    onclick: () => toggleSection(key),
    onkeydown: (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); toggleSection(key); } },
  },
  h("span", { class: "chev" + (open ? " open" : "") }, icon("chevron")),
  h("span", { class: "title" }, title),
  h("span", { class: "count" }, String(items.length)),
  tools.length ? h("span", { class: "tools" }, tools.map(([label, run]) => h("button", {
    onclick: (event) => { event.stopPropagation(); run(); },
  }, label))) : null);
  const shown = open ? (limit ? items.slice(0, limit) : items) : [];
  return h("section", { class: "place" }, head, shown.map((item) => placeRow(item, remove, edit)));
}

function renderPlaces() {
  const { recent, favorites, tags } = places.data;
  const sections = [
    placeSection("recent", "Recent", recent, {
      limit: RECENT_SHOWN,
      remove: { label: "Remove from recent", run: (item) => changePlaces({ op: "forget", path: item.path }) },
      tools: [["Clear", () => changePlaces({ op: "clear-recent" })]],
    }),
    placeSection("favorites", "Favorites", favorites, {
      remove: { label: "Remove from favorites", run: (item) => changePlaces({ op: "favorite", path: item.path, on: false }) },
      edit: { label: "Rename (nickname)", run: renameFavorite },
    }),
    ...tags.map((tag) => placeSection("tag:" + tag.name, [tagDot(tag.name), h("span", null, tag.name)], tag.files, {
      remove: { label: `Remove the ${tag.name} tag`, run: (item) => changePlaces({ op: "untag", path: item.path, tag: tag.name }) },
      tools: [
        ["Rename", () => {
          const name = prompt(`Rename the tag "${tag.name}" to:`, tag.name);
          if (name && name.trim() && name.trim() !== tag.name) changePlaces({ op: "rename-tag", tag: tag.name, name: name.trim() });
        }],
        ["Delete", () => {
          if (confirm(`Delete the tag "${tag.name}"? The files stay; only the tag goes.`)) changePlaces({ op: "delete-tag", tag: tag.name });
        }],
      ],
    })),
  ].filter(Boolean);
  $("#places").replaceChildren(...sections);
  // With places above it, the tree gets its own collapsible heading.
  const filesHead = $("#files-head");
  filesHead.hidden = !sections.length;
  const filesOpen = !places.collapsed.has("files");
  filesHead.replaceChildren(h("span", { class: "chev" + (filesOpen ? " open" : "") }, icon("chevron")), h("span", { class: "title" }, "Files"));
  filesHead.setAttribute("aria-expanded", filesOpen);
  $("#tree").hidden = sections.length > 0 && !filesOpen;
}

function closeTagMenu() {
  const menu = $("#tagmenu");
  if (menu) menu.remove();
  document.removeEventListener("pointerdown", tagMenuOutside, true);
}

function tagMenuOutside(event) {
  if (!event.target.closest("#tagmenu, #tag-btn")) closeTagMenu();
}

function openTagMenu(anchor, path) {
  if ($("#tagmenu")) return closeTagMenu();
  const field = h("input", { type: "text", placeholder: "Add a tag…", "aria-label": "Tag name", maxLength: 40 });
  const current = h("div", { class: "current" });
  const suggest = h("div", { class: "suggest", role: "listbox" });
  let choice = -1;

  async function add(name) {
    if (!name.trim()) return;
    if (await changePlaces({ op: "tag", path, tag: name.trim() })) {
      field.value = "";
      draw();
    }
  }

  function draw() {
    const mine = tagsOf(path);
    current.replaceChildren(...mine.map((name) => h("span", { class: "chip" }, tagDot(name), name,
      h("button", { title: "Remove " + name, "aria-label": "Remove " + name, onclick: async () => { await changePlaces({ op: "untag", path, tag: name }); draw(); } }, "×"))));
    const typed = field.value.trim().toLowerCase();
    const others = places.data.tags.map((tag) => tag.name)
      .filter((name) => !mine.includes(name) && name.toLowerCase().includes(typed));
    const options = others.map((name) => h("button", { role: "option", onclick: () => add(name) }, tagDot(name), name));
    if (typed && !places.data.tags.some((tag) => tag.name.toLowerCase() === typed)) {
      options.push(h("button", { role: "option", onclick: () => add(field.value) }, "Create “", field.value.trim(), "”"));
    }
    choice = Math.min(choice, options.length - 1);
    options.forEach((option, index) => option.classList.toggle("sel", index === choice));
    suggest.replaceChildren(...options);
  }

  field.addEventListener("input", () => { choice = -1; draw(); });
  field.addEventListener("keydown", (event) => {
    const options = suggest.querySelectorAll("button");
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!options.length) return;
      choice = (choice + (event.key === "ArrowDown" ? 1 : -1) + options.length) % options.length;
      options.forEach((option, index) => option.classList.toggle("sel", index === choice));
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (choice >= 0 && options[choice]) options[choice].click();
      else add(field.value);
    } else if (event.key === "Escape") {
      closeTagMenu();
    }
  });

  const menu = h("div", { id: "tagmenu", class: "popover tagmenu", role: "dialog", "aria-label": "Tags" },
    h("div", { class: "pop-title" }, "Tags"), current, field, suggest,
    h("div", { class: "hint" }, "Each tag gets its own section in the sidebar."));
  document.body.append(menu);
  placePopover(menu, anchor);
  draw();
  field.focus();
  document.addEventListener("pointerdown", tagMenuOutside, true);
}

function openSettings() {
  if ($("#settings")) return closeSettings();
  const { features, access } = state.config;
  const theme = document.documentElement.dataset.theme || "system";
  const themeRow = h("div", { class: "seg wide" }, ["system", "light", "dark"].map((mode) => h("button", {
    class: mode === theme ? "on" : "",
    onclick: (event) => {
      setTheme(mode);
      for (const button of event.target.parentNode.children) button.classList.toggle("on", button === event.target);
    },
  }, mode[0].toUpperCase() + mode.slice(1))));
  const toggle = (key, label, note) => h("label", { class: "opt" },
    h("input", { type: "checkbox", checked: settings[key], onchange: (event) => { setSetting(key, event.target.checked); render({ keepScroll: true }); } }),
    h("span", null, label, note && h("small", null, note)));
  let account;
  if (access.mode === "tailscale") account = h("p", null, "Signed in as ", h("b", null, access.user || "?"), " through Tailscale.");
  else if (access.mode === "token") account = h("p", null, "Signed in with an access token. ", h("a", { href: "/__shelf/logout" }, "Sign out"));
  else account = h("p", null, "No access control on this server. ", h("a", { href: DOCS + "/security.md", target: "_blank", rel: "noopener" }, "Securing shelf"));
  const panel = h("div", { id: "settings", class: "popover", role: "dialog", "aria-label": "Settings" },
    h("div", { class: "pop-title" }, "Settings"),
    h("div", { class: "pop-label" }, "Theme"), themeRow,
    h("div", { class: "pop-label" }, "Viewers"),
    toggle("toc", "Outline beside Markdown"),
    toggle("jsonlTable", "JSONL files as tables"),
    toggle("thumbnails", "Thumbnails in galleries", features.thumbnails ? null : "ffmpeg isn't installed on the server, so videos show icons"),
    toggle("liveReload", "Reload files when they change on disk"),
    h("details", { class: "keys" }, h("summary", null, "Keyboard shortcuts"),
      h("dl", null, SHORTCUTS.map(([keys, what]) => [h("dt", null, keys), h("dd", null, what)]))),
    h("div", { class: "pop-label" }, "Access"), account,
    h("div", { class: "pop-foot" }, `shelf ${state.config.version} · `, h("a", { href: DOCS.replace(/\/tree\/main\/docs$/, ""), target: "_blank", rel: "noopener" }, "Docs and source")));
  document.body.append(panel);
  document.addEventListener("pointerdown", settingsOutside, true);
}

const DOCS = "https://github.com/ivanfarevalo/shelf/tree/main/docs";

// ---------- viewers ----------

function notice(iconName, title, ...lines) {
  return h("div", { class: "notice" }, icon(iconName), h("h2", null, title), lines.map((line) => (typeof line === "string" ? h("p", null, line) : line)));
}

function downloadButton(path) {
  return h("a", { class: "btn", href: rawUrl(path), download: baseName(path) }, icon("download"), "Download");
}

const NO_PREVIEW = {
  doc: "Older Word files (.doc) don't preview. Saved as .docx, they do.",
  xls: "Older Excel files (.xls) don't preview. Saved as .xlsx, they do.",
  xlsb: "Binary Excel files (.xlsb) don't preview. Saved as .xlsx, they do.",
  ppt: "PowerPoint files don't preview yet.",
  pptx: "PowerPoint files don't preview yet.",
};

function viewBinary(ctx) {
  const why = NO_PREVIEW[extOf(ctx.path)] || "no preview for this file type";
  ctx.el.append(notice("file", baseName(ctx.path), `${formatSize(ctx.stat.size)} · ${why}`, downloadButton(ctx.path)));
}

function codeBlock(text, language) {
  const code = h("code", { class: language ? "language-" + language : "" }, text);
  if (language && text.length <= HIGHLIGHT_MAX) hljs.highlightElement(code);
  return h("div", { class: "block" }, h("pre", null, code));
}

const looksBinary = (bytes) => bytes.subarray(0, 8192).includes(0);

async function viewText(ctx, pretty) {
  const { path, stat } = ctx;
  const decoder = new TextDecoder();
  let offset = 0;
  let text = "";
  if (pretty !== undefined) {
    text = pretty;
    offset = stat.size;
  } else {
    const bytes = await fetchRange(path, 0, TEXT_CHUNK);
    if (!ctx.alive()) return;
    if (looksBinary(bytes)) return viewBinary(ctx);
    text = decoder.decode(bytes, { stream: true });
    offset = bytes.length;
  }

  const gutter = h("pre", { class: "gutter", "aria-hidden": "true" });
  const code = h("code");
  const footer = h("div", { class: "load-more" });
  const language = languageFor(baseName(path));

  function paint() {
    const lines = text.split("\n");
    if (lines[lines.length - 1] === "") lines.pop();
    gutter.textContent = lines.map((line, number) => number + 1).join("\n");
    if (language && text.length <= HIGHLIGHT_MAX) {
      code.innerHTML = hljs.highlight(text, { language, ignoreIllegals: true }).value;
    } else {
      code.textContent = text;
    }
    footer.replaceChildren();
    if (offset < stat.size) {
      footer.append(
        `Showing ${formatSize(offset)} of ${formatSize(stat.size)}`,
        h("button", { class: "btn", onclick: more }, "Load more"));
    }
  }

  async function more(repaint = true) {
    const bytes = await fetchRange(path, offset, TEXT_CHUNK);
    if (!ctx.alive()) return;
    text += decoder.decode(bytes, { stream: true });
    offset += bytes.length || stat.size;
    if (repaint) paint();
  }

  // Opened from a search result: load far enough to show that line.
  const wanted = pretty === undefined ? Number(ctx.params.get("line")) || 0 : 0;
  while (wanted && offset < stat.size && offset < JUMP_MAX && text.split("\n").length <= wanted) {
    await more(false);
    if (!ctx.alive()) return;
  }
  paint();
  const source = h("pre", { class: "src" }, code);
  const box = h("div", { class: "code-view" }, gutter, source);
  ctx.el.append(box, footer);
  if (wanted) ctx.mounted.push(() => markLine(box, source, wanted));
}

function markLine(box, source, number) {
  const style = getComputedStyle(source);
  const height = parseFloat(style.lineHeight);
  const top = parseFloat(style.paddingTop) + (number - 1) * height;
  box.append(h("div", { class: "line-mark", style: `top:${top}px;height:${height}px` }));
  view.scrollTop = Math.max(top - view.clientHeight / 3, 0);
}

async function viewJson(ctx) {
  if (ctx.stat.size <= AUTO_RELOAD_MAX && !ctx.params.get("line")) {
    const response = await fetch(rawUrl(ctx.path));
    const source = await response.text();
    if (!ctx.alive()) return;
    try {
      return await viewText(ctx, JSON.stringify(JSON.parse(source), null, 2));
    } catch (e) { /* invalid JSON: show it as written */ }
  }
  return viewText(ctx);
}

function slugify(text) {
  return text.trim().toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu, "").replace(/\s+/g, "-");
}

// 0 -> A, 25 -> Z, 26 -> AA, as Excel names columns.
function columnLetters(index) {
  let text = "";
  for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26)) text = String.fromCharCode(65 + ((n - 1) % 26)) + text;
  return text;
}

function fixRelativeUrls(root, path) {
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
      link.setAttribute("href", "#" + url.pathname.replace(/\/$/, ""));
    } else {
      link.target = "_blank";
      link.rel = "noopener";
    }
  }
}

function renderMarkdown(source, path) {
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
function decorateBlocks(content) {
  for (const pre of [...content.querySelectorAll("pre")]) {
    const code = pre.querySelector("code");
    if (code) {
      const language = /language-([\w+-]+)/.exec(code.className);
      if (language && hljs.getLanguage(language[1]) && code.textContent.length <= HIGHLIGHT_MAX) hljs.highlightElement(code);
    }
    const copy = h("button", { class: "copy" }, "Copy");
    copy.addEventListener("click", async () => {
      await copyText(pre.textContent);
      copy.textContent = "Copied";
      setTimeout(() => { copy.textContent = "Copy"; }, 1200);
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

function highlightText(root, query) {
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

function buildOutline(headings, ctx) {
  const links = headings.map((heading) => h("a", {
    class: "toc-link lvl" + heading.tagName[1],
    href: "#",
    onclick: (event) => { event.preventDefault(); heading.scrollIntoView({ block: "start" }); },
  }, heading.textContent));
  const spy = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const at = headings.indexOf(entry.target);
      links.forEach((link, index) => link.classList.toggle("on", index === at));
    }
  }, { root: view, rootMargin: "0px 0px -70% 0px" });
  ctx.mounted.push(() => headings.forEach((heading) => spy.observe(heading)));
  ctx.cleanup.push(() => spy.disconnect());
  return h("nav", { class: "toc", "aria-label": "On this page" }, h("div", { class: "toc-title" }, "On this page"), links);
}

const narrow = () => matchMedia("(max-width: 1100px)").matches;

async function viewMarkdown(ctx) {
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
    const before = source.split("\n").slice(0, Math.max(line - 1, 0)).join("\n").toLowerCase();
    let skip = 0;
    for (let at = before.indexOf(query.toLowerCase()); at >= 0; at = before.indexOf(query.toLowerCase(), at + 1)) skip++;
    markCurrent(ctx, marks[Math.min(skip, marks.length - 1)]);
  }
}

function markCurrent(ctx, target) {
  if (!target) return;
  target.classList.add("current");
  ctx.mounted.push(() => target.scrollIntoView({ block: "center" }));
}

// A rendered document in the page column, with the outline beside it when it
// has enough headings to need one.
function showArticle(ctx, article) {
  const page = h("div", { class: "page" }, article);
  const headings = [...article.querySelectorAll("h1, h2, h3")];
  if (headings.length >= 2) {
    const layout = h("div", { class: "doc" + (settings.toc ? " toc-on" : "") }, page, buildOutline(headings, ctx));
    ctx.actions.push(h("button", {
      class: "icon-btn", title: "Outline", "aria-label": "Show or hide the outline",
      onclick: () => {
        if (narrow()) return layout.classList.toggle("toc-overlay");
        setSetting("toc", !settings.toc);
        layout.classList.toggle("toc-on", settings.toc);
      },
    }, icon("toc")));
    ctx.el.append(layout);
  } else {
    ctx.el.append(page);
  }
}

// ---------- Word and Excel ----------
// The server turns them into HTML and rows (shelf/office.py).

async function viewDocx(ctx) {
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
    image.src = API + "office-part?" + new URLSearchParams({ path: ctx.path, part: image.dataset.part, v: ctx.stat.mtime });
  }
  const used = new Map();
  for (const heading of article.querySelectorAll("h1,h2,h3,h4,h5,h6")) {
    const slug = "doc-" + slugify(heading.textContent);
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

async function viewXlsx(ctx) {
  const asked = ctx.params.get("sheet");
  const data = await api("office", asked === null ? { path: ctx.path } : { path: ctx.path, sheet: asked });
  if (!ctx.alive()) return;
  // Hidden sheets stay out of the tabs, unless a link opened one.
  const tabs = data.sheets.length > 1 ? h("div", { class: "sheet-tabs", role: "tablist" }, data.sheets.map((sheet, index) => {
    if (sheet.hidden && index !== data.sheet) return null;
    return h("button", {
      class: "sheet-tab" + (index === data.sheet ? " on" : ""),
      role: "tab",
      "aria-selected": String(index === data.sheet),
      title: sheet.hidden ? `${sheet.name} (hidden in Excel)` : sheet.name,
      onclick: () => {
        if (index === data.sheet) return;
        const params = new URLSearchParams(ctx.params);
        params.set("sheet", index);
        params.delete("q");
        history.replaceState(null, "", "#/" + encodePath(ctx.path) + "?" + params);
        state.stepping = true;  // a different sheet of the same file isn't a new visit
        render();
      },
    }, sheet.name);
  })) : null;
  const hiddenCount = data.sheets.filter((sheet) => sheet.hidden).length;
  if (tabs && hiddenCount) tabs.append(h("span", { class: "sheet-note" }, `${hiddenCount} hidden`));

  if (!data.rows.length) {
    ctx.el.append(notice("table", "This sheet is empty"));
    if (tabs) ctx.el.append(tabs);
    return;
  }
  const notes = [];
  if (data.truncated) notes.push(`first ${(data.rows.length - 1).toLocaleString()} rows`);
  if (data.wide) notes.push("first 1,000 columns");
  await viewTable(ctx, "sheet", {
    header: data.rows[0],
    rows: data.rows.slice(1),
    firstRow: data.first_row + 1,
    firstColumn: data.first_col,
    note: notes.length ? "showing the " + notes.join(" and ") : "",
    footer: tabs,
  });
}

function viewHtml(ctx, page) {
  // allow-same-origin keeps relative fetches and storage working, as they do
  // under http.server. Leaving out allow-top-navigation stops a page from
  // replacing this app.
  const frame = h("iframe", {
    class: "page-frame",
    src: rawUrl(page || ctx.path),
    title: baseName(page || ctx.path),
  });
  frame.setAttribute("sandbox", "allow-same-origin allow-scripts allow-forms allow-popups allow-modals allow-downloads");
  frame.addEventListener("load", () => {
    if (!ctx.alive()) return;
    let inside;
    try { inside = frame.contentWindow; inside.location.pathname; } catch (e) { return; }
    const opened = decodeURIComponent(inside.location.pathname).replace(/^\/|\/$/g, "");
    if (inside.document.title === "shelf:folder") location.hash = appUrl(opened);
    else if (opened !== state.watch) followFrame(opened);
  });
  ctx.fill();
  ctx.el.append(frame);
  ctx.reload = () => frame.contentWindow.location.reload();
}

// A link clicked inside a rendered page: track it without reloading the frame.
// The frame's navigation already added a history entry, so relabel that one. A
// second entry would make Back need two presses.
async function followFrame(path) {
  try {
    const stat = await api("stat", { path });
    history.replaceState(null, "", appUrl(path));
    state.path = path;
    state.watch = path;
    state.stat = stat;
    renderChrome();
    revealInTree(path, stat.type === "dir");
    if (stat.type === "file") changePlaces({ op: "visit", path }, { quiet: true });
  } catch (e) { /* a 404 inside the frame: it shows its own error */ }
}

function viewPdf(ctx) {
  // No sandbox here: Chrome will not load its PDF viewer in a sandboxed frame.
  ctx.fill();
  ctx.el.append(h("iframe", { class: "page-frame", src: rawUrl(ctx.path), title: baseName(ctx.path) }));
}

async function siblings(path, kinds) {
  const dir = parentOf(path);
  const entries = tree.children.get(dir) || await loadChildren(dir);
  return entries.filter((entry) => !entry.dir && kinds.includes(kindOf(entry.name))).map((entry) => join(dir, entry.name));
}

async function addStepper(ctx, kinds) {
  const list = await siblings(ctx.path, kinds);
  const at = list.indexOf(ctx.path);
  if (list.length < 2 || at < 0) return;
  const go = (step) => {
    state.stepping = true;
    location.hash = appUrl(list[(at + step + list.length) % list.length]);
  };
  ctx.step = go;
  ctx.el.append(
    h("button", { class: "nav-btn prev", title: "Previous (←)", "aria-label": "Previous", onclick: () => go(-1) }, icon("left")),
    h("button", { class: "nav-btn next", title: "Next (→)", "aria-label": "Next", onclick: () => go(1) }, icon("chevron")));
  state.stepMeta = `${at + 1} of ${list.length}`;
}

async function viewImage(ctx) {
  const image = h("img", { src: rawUrl(ctx.path) + "?v=" + ctx.stat.mtime, alt: baseName(ctx.path) });
  const stage = h("div", { class: "stage" }, image);
  image.addEventListener("click", () => stage.classList.toggle("zoomed"));
  image.addEventListener("load", () => {
    if (!ctx.alive() || !image.naturalWidth) return;
    $("#meta").textContent = [state.stepMeta, `${image.naturalWidth} × ${image.naturalHeight}`, formatSize(ctx.stat.size)].filter(Boolean).join(" · ");
  });
  image.addEventListener("error", () => {
    if (ctx.alive()) stage.replaceChildren(notice("alert", "This image could not be decoded", "The browser does not support its format.", downloadButton(ctx.path)));
  });
  ctx.fill();
  ctx.el.append(stage);
  await addStepper(ctx, ["image"]);
}

function formatClock(seconds) {
  const minutes = Math.floor(seconds / 60);
  const rest = (seconds - minutes * 60).toFixed(3).padStart(6, "0");
  return `${minutes}:${rest}`;
}

const SPEEDS = [0.1, 0.25, 0.5, 1, 1.5, 2, 4];

async function viewVideo(ctx) {
  const video = h("video", { src: rawUrl(ctx.path), controls: true, preload: "metadata", playsInline: true });
  const stage = h("div", { class: "stage video-stage" }, video);
  let facts = null;
  let fps = null;
  let estimated = false;

  const clock = h("span", { class: "vt-clock" }, "0:00.000");
  const frameLabel = h("span", { class: "vt-frame" });
  const playButton = h("button", { class: "vt-btn", title: "Play / pause (Space or K)", "aria-label": "Play or pause", onclick: () => controls.toggle() }, icon("play"));
  const speed = h("select", { class: "vt-speed", "aria-label": "Playback speed", title: "Speed ([ and ])", onchange: () => { video.playbackRate = Number(speed.value); } },
    SPEEDS.map((rate) => h("option", { value: rate, selected: rate === 1 }, rate + "×")));
  const linkButton = h("button", { class: "vt-btn wide", title: "Copy a link to this moment (T)", onclick: () => controls.copyLink() }, icon("link"), h("span", null, "Link"));
  const button = (label, title, run) => h("button", { class: "vt-btn", title, onclick: run }, label);
  const bar = h("div", { class: "vtools" },
    button("−1s", "Back 1 second (J, Shift+J for 5)", () => controls.seek(-1)),
    button("−1f", "Previous frame (,)", () => controls.step(-1)),
    playButton,
    button("+1f", "Next frame (.)", () => controls.step(1)),
    button("+1s", "Forward 1 second (L, Shift+L for 5)", () => controls.seek(1)),
    clock, frameLabel, h("span", { class: "vt-gap" }), speed, linkButton);

  const frameOf = (time) => Math.floor(time * fps + 1e-6);

  function update() {
    clock.textContent = formatClock(video.currentTime || 0);
    if (fps) {
      const total = facts && facts.frames ? ` / ${facts.frames - 1}` : "";
      frameLabel.textContent = `frame ${frameOf(video.currentTime)}${total} · ${estimated ? "≈" : ""}${Math.round(fps * 100) / 100} fps`;
    }
    playButton.replaceChildren(icon(video.paused ? "play" : "pause"));
  }

  const controls = {
    toggle: () => (video.paused ? video.play() : video.pause()),
    step(count) {
      if (!fps) return;
      video.pause();
      const target = (frameOf(video.currentTime) + count + 0.5) / fps;  // mid-frame lands reliably
      video.currentTime = Math.min(Math.max(target, 0), Math.max((video.duration || target) - 0.5 / fps, 0));
    },
    seek(seconds) {
      video.currentTime = Math.min(Math.max(video.currentTime + seconds, 0), video.duration || Infinity);
    },
    rate(direction) {
      const at = SPEEDS.indexOf(video.playbackRate);
      const next = SPEEDS[Math.min(Math.max((at < 0 ? 3 : at) + direction, 0), SPEEDS.length - 1)];
      video.playbackRate = next;
      speed.value = String(next);
    },
    async copyLink() {
      const link = location.origin + "/" + appUrl(ctx.path, { t: video.currentTime.toFixed(3) });
      await copyText(link);
      linkButton.lastChild.textContent = "Copied";
      setTimeout(() => { linkButton.lastChild.textContent = "Link"; }, 1500);
    },
  };

  for (const name of ["timeupdate", "seeked", "play", "pause", "loadedmetadata"]) video.addEventListener(name, update);
  const start = Number(ctx.params.get("t"));
  if (start > 0) video.addEventListener("loadedmetadata", () => { video.currentTime = start; }, { once: true });

  // Without ffprobe, measure the frame rate from frames the browser presents.
  function estimate() {
    if (fps || !video.requestVideoFrameCallback) return;
    const times = [];
    const tick = (now, meta) => {
      if (!ctx.alive() || fps) return;
      times.push(meta.mediaTime);
      if (times.length < 12) return video.requestVideoFrameCallback(tick);
      const gaps = times.slice(1).map((time, index) => time - times[index]).filter((gap) => gap > 0).sort((a, b) => a - b);
      if (gaps.length) { fps = 1 / gaps[Math.floor(gaps.length / 2)]; estimated = true; update(); }
    };
    video.requestVideoFrameCallback(tick);
  }
  video.addEventListener("play", estimate);

  video.addEventListener("error", () => {
    if (!ctx.alive()) return;
    const codec = facts && facts.codec ? ` It is encoded as ${facts.codec.toUpperCase()}.` : "";
    stage.replaceChildren(notice("alert", "The browser cannot play this video", `Its codec is probably unsupported.${codec} H.265 and most .mkv or .avi files need a download.`, downloadButton(ctx.path)));
    bar.remove();
  });
  ctx.cleanup.push(() => { video.pause(); video.removeAttribute("src"); video.load(); state.video = null; });
  state.video = controls;
  ctx.fill();
  ctx.el.append(h("div", { class: "video-view" }, stage, bar));

  if (state.config.features.probe) {
    facts = await api("probe", { path: ctx.path }).catch(() => null);
    if (!ctx.alive()) return;
    if (facts && facts.fps) fps = facts.fps;
    update();
  }
  await addStepper(ctx, ["video"]);
}

function viewAudio(ctx) {
  ctx.fill();
  ctx.el.append(h("div", { class: "stage" }, h("audio", { src: rawUrl(ctx.path), controls: true })));
}

// ---------- tables ----------

// Parses delimited text in pieces, keeping a half-read record between feeds.
class CsvParser {
  constructor(delimiter) {
    this.delimiter = delimiter;
    this.field = "";
    this.record = [];
    this.quoted = false;
    this.afterQuote = false;
    this.skipLf = false;
  }

  feed(text, rows) {
    const { delimiter } = this;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (this.skipLf) {
        this.skipLf = false;
        if (c === "\n") continue;
      }
      if (this.quoted) {
        if (c === '"') { this.quoted = false; this.afterQuote = true; }
        else {
          // Copy the run up to the next quote in one step: far faster than per char.
          const next = text.indexOf('"', i);
          const end = next === -1 ? text.length : next;
          this.field += text.slice(i, end);
          i = end - 1;
        }
      } else if (c === '"' && this.afterQuote) {
        this.field += '"';           // "" inside a quoted field
        this.quoted = true;
        this.afterQuote = false;
      } else if (c === '"' && this.field === "") {
        this.quoted = true;
      } else if (c === delimiter) {
        this.record.push(this.field);
        this.field = "";
        this.afterQuote = false;
      } else if (c === "\n" || c === "\r") {
        this.endRecord(rows);
        this.skipLf = c === "\r";
      } else {
        this.field += c;
        this.afterQuote = false;
      }
    }
  }

  endRecord(rows) {
    this.record.push(this.field);
    rows.push(this.record);
    this.record = [];
    this.field = "";
    this.afterQuote = false;
  }

  finish(rows) {
    if (this.field !== "" || this.record.length) this.endRecord(rows);
  }
}

function sniffDelimiter(name, text) {
  if (extOf(name) === "tsv") return "\t";
  const line = text.slice(0, text.indexOf("\n") + 1 || 4096);
  let best = ",";
  let bestCount = 0;
  for (const candidate of [",", "\t", ";", "|"]) {
    const count = line.split(candidate).length - 1;
    if (count > bestCount) { best = candidate; bestCount = count; }
  }
  return best;
}

const NUMERIC = /^\s*[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?%?\s*$/;

function compareCells(a, b) {
  const x = a === undefined ? "" : a;
  const y = b === undefined ? "" : b;
  if (NUMERIC.test(x) && NUMERIC.test(y)) return parseFloat(x) - parseFloat(y);
  if (x === "") return y === "" ? 0 : 1;   // blanks last
  if (y === "") return -1;
  return x < y ? -1 : x > y ? 1 : 0;
}

// One JSON object per line. Columns are the union of top-level keys, in order
// of first appearance; nested values show as compact JSON.
class JsonlParser {
  constructor() {
    this.rest = "";
    this.columns = [];
    this.positions = new Map();
  }

  column(name) {
    if (!this.positions.has(name)) {
      this.positions.set(name, this.columns.length);
      this.columns.push(name);
    }
    return this.positions.get(name);
  }

  add(line, rows) {
    const trimmed = line.trim();
    if (!trimmed) return;
    const row = [];
    let value;
    try { value = JSON.parse(trimmed); } catch (e) {
      row[this.column("(unparsed line)")] = trimmed;
      rows.push(row);
      return;
    }
    if (value && typeof value === "object" && !Array.isArray(value)) {
      for (const [key, cell] of Object.entries(value)) row[this.column(key)] = cellText(cell);
    } else {
      row[this.column("value")] = cellText(value);
    }
    rows.push(row);
  }

  feed(text, rows) {
    const lines = (this.rest + text).split("\n");
    this.rest = lines.pop();
    for (const line of lines) this.add(line, rows);
  }

  finish(rows) {
    this.add(this.rest, rows);
    this.rest = "";
  }
}

const cellText = (value) => (value === null || value === undefined ? "" : typeof value === "object" ? JSON.stringify(value) : String(value));

// given: rows already in hand (an Excel sheet), instead of reading the file in pieces.
async function viewTable(ctx, format, given) {
  const { path, stat } = ctx;
  const firstRow = given ? given.firstRow : 1;  // the number shown beside the first row
  const decoder = new TextDecoder();
  const rows = [];
  let header = null;
  let parser = null;
  let offset = 0;
  let loading = false;
  let order = [];              // indices into rows, after filter and sort
  let sort = null;
  let filter = (ctx.params.get("q") || "").toLowerCase();
  let firstDrawn = -1;
  let shownColumns = 0;

  const scroller = h("div", { class: "table-scroll" });
  const status = h("span", { class: "status" });
  const moreButton = h("button", { class: "btn", onclick: () => loadChunk() }, "Load more");
  const filterBox = h("input", {
    type: "search",
    value: ctx.params.get("q") || "",
    placeholder: "Filter rows",
    "aria-label": "Filter rows",
    oninput: (event) => { filter = event.target.value.toLowerCase(); applyView(); },
  });
  const bar = h("div", { class: "table-bar" }, filterBox, status, moreButton);
  const table = h("table", { class: "data" });
  const colgroup = h("colgroup");
  const headRow = h("tr");
  const body = h("tbody");
  table.append(colgroup, h("thead", null, headRow), body);
  scroller.append(table);

  async function loadChunk() {
    if (given && !header) {
      header = given.header;
      for (const row of given.rows) rows.push(row);
      offset = stat.size;
      if (rows.length || header.length) buildHeader();
      applyView();
      return;
    }
    if (loading || offset >= stat.size) return;
    loading = true;
    const bytes = await fetchRange(path, offset, CSV_CHUNK);
    if (!ctx.alive()) return;
    offset += bytes.length || stat.size;
    let text = decoder.decode(bytes, { stream: offset < stat.size });
    if (!parser) {
      if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
      parser = format === "jsonl" ? new JsonlParser() : new CsvParser(sniffDelimiter(path, text));
    }
    parser.feed(text, rows);
    if (offset >= stat.size) parser.finish(rows);
    if (format === "jsonl") {
      if (parser.columns.length !== shownColumns) {
        header = parser.columns;
        buildHeader();
      }
    } else if (!header && rows.length) {
      header = rows.shift();
      buildHeader();
    }
    loading = false;
    applyView();
  }

  function buildHeader() {
    const sample = rows.slice(0, 200);
    let columns = header.length;
    shownColumns = header.length;
    for (const row of sample) columns = Math.max(columns, row.length);
    const widths = [];
    const numeric = [];
    for (let column = 0; column < columns; column++) {
      let longest = (header[column] || "").length + 3;
      let numbers = 0;
      let filled = 0;
      for (const row of sample) {
        const cell = row[column] || "";
        if (cell) filled++;
        if (NUMERIC.test(cell)) numbers++;
        longest = Math.max(longest, cell.length);
      }
      numeric.push(filled > 0 && numbers / filled > 0.8);
      widths.push(Math.min(Math.max(longest * 7.4 + 22, 72), 340));
    }
    table.numeric = numeric;
    const lastRow = given ? firstRow + rows.length : Math.max(stat.size / 20, 1000) | 0;
    const gutter = String(Math.max(lastRow, 1000)).length * 8 + 22;
    colgroup.replaceChildren(h("col", { style: `width:${gutter}px` }), ...widths.map((width) => h("col", { style: `width:${width}px` })));
    table.style.width = gutter + widths.reduce((sum, width) => sum + width, 0) + "px";
    headRow.replaceChildren(h("th", { class: "rn" }, "#"), ...widths.map((_, column) => {
      const letter = given ? columnLetters(given.firstColumn + column) : "";
      const name = header[column] || (given ? letter : `column ${column + 1}`);
      const title = given && name !== letter ? `${letter} · ${name}` : name;
      return h("th", { title, onclick: () => cycleSort(column) }, h("span", { class: "arrow" }), name);
    }));
  }

  function cycleSort(column) {
    if (!sort || sort.column !== column) sort = { column, direction: 1 };
    else if (sort.direction === 1) sort.direction = -1;
    else sort = null;
    [...headRow.children].forEach((cell, index) => {
      const arrow = cell.querySelector(".arrow");
      if (arrow) arrow.textContent = sort && sort.column === index - 1 ? (sort.direction === 1 ? "↑" : "↓") : "";
    });
    applyView();
  }

  function applyView() {
    order = [];
    for (let index = 0; index < rows.length; index++) {
      if (!filter || rows[index].some((cell) => cell.toLowerCase().includes(filter))) order.push(index);
    }
    if (sort) {
      const { column, direction } = sort;
      order.sort((a, b) => direction * compareCells(rows[a][column], rows[b][column]) || a - b);
    }
    const complete = offset >= stat.size;
    const count = rows.length.toLocaleString();
    const columns = header ? `${Math.max(colgroup.children.length - 1, 0)} columns` : "";
    let text = filter ? `${order.length.toLocaleString()} of ${count} rows` : `${count} rows`;
    text += ` · ${columns}`;
    if (!complete) text += ` · loaded ${formatSize(offset)} of ${formatSize(stat.size)}`;
    if (!complete && (filter || sort)) text += ", so sort and filter see only what is loaded";
    if (given && given.note) text += ` · ${given.note}`;
    status.textContent = text;
    moreButton.hidden = complete;
    firstDrawn = -1;
    draw();
  }

  function draw() {
    const height = scroller.clientHeight || 600;
    const first = Math.max(Math.floor(scroller.scrollTop / ROW_H) - 12, 0);
    if (first === firstDrawn) return;
    firstDrawn = first;
    const last = Math.min(first + Math.ceil(height / ROW_H) + 24, order.length);
    const columns = colgroup.children.length - 1;
    const trs = [h("tr", { class: "pad" }, h("td", { colSpan: columns + 1, style: `height:${first * ROW_H}px` }))];
    for (let at = first; at < last; at++) {
      const row = rows[order[at]];
      const cells = [h("td", { class: "rn" }, String(order[at] + firstRow))];
      for (let column = 0; column < columns; column++) {
        const value = row[column] === undefined ? "" : row[column];
        cells.push(h("td", { class: table.numeric[column] ? "num" : null, title: value.length > 30 ? value : null }, value));
      }
      trs.push(h("tr", null, cells));
    }
    trs.push(h("tr", { class: "pad" }, h("td", { colSpan: columns + 1, style: `height:${(order.length - last) * ROW_H}px` })));
    body.replaceChildren(...trs);
    // Near the end of what is loaded, fetch the next piece without being asked.
    if (last >= order.length - 40 && !filter && !sort && offset < stat.size) loadChunk();
  }

  scroller.addEventListener("scroll", () => requestAnimationFrame(draw));
  await loadChunk();
  if (!ctx.alive()) return;
  if (!header || (format === "jsonl" && !rows.length)) { ctx.el.append(notice("table", "This table is empty")); return; }
  ctx.fill();
  ctx.el.append(h("div", { class: "table-view" }, bar, scroller, given && given.footer));
  ctx.mounted.push(() => { firstDrawn = -1; draw(); });
}

// ---------- folders ----------

function sortEntries(entries, how) {
  const { key, direction } = how;
  const copy = [...entries];
  if (key === "name") return direction > 0 ? copy : copy.reverse();
  return copy.sort((a, b) => (b.dir - a.dir) || direction * (a[key] - b[key]));
}

function folderItem(dir, entry) {
  const path = join(dir, entry.name);
  return h("a", { class: "item", href: appUrl(path), title: entry.name },
    h("span", { class: "n" }, icon(iconFor(entry)), h("span", null, entry.name)),
    h("span", { class: "when" }, formatWhen(entry.mtime)),
    h("span", { class: "size" }, entry.dir ? "" : formatSize(entry.size)));
}

const thumbUrl = (path, entry) => API + "thumb?" + new URLSearchParams({ path, v: entry.mtime });

function cardPicture(path, entry) {
  const kind = entry.dir ? null : kindOf(entry.name);
  const thumbs = settings.thumbnails;
  if (kind === "image") {
    // Thumbnail first; if the server can't make one, the original; then an icon.
    const useThumb = thumbs && extOf(entry.name) !== "svg";
    const image = h("img", { src: useThumb ? thumbUrl(path, entry) : rawUrl(path), alt: "", loading: "lazy", decoding: "async" });
    image.addEventListener("error", () => {
      if (image.dataset.fallback) return image.replaceWith(icon("image"));
      image.dataset.fallback = "1";
      image.src = rawUrl(path);
    });
    return [image];
  }
  if (kind === "video" && thumbs && state.config.features.thumbnails) {
    const poster = h("img", { src: thumbUrl(path, entry), alt: "", loading: "lazy", decoding: "async" });
    const badge = h("span", { class: "badge" }, icon("play"));
    poster.addEventListener("error", () => { badge.remove(); poster.replaceWith(icon("video")); });
    return [poster, badge];
  }
  return [icon(iconFor(entry))];
}

function folderCard(dir, entry) {
  const path = join(dir, entry.name);
  return h("a", { class: "card", href: appUrl(path), title: entry.name },
    h("div", { class: "thumb" }, cardPicture(path, entry)),
    h("div", { class: "cap" }, entry.name));
}

async function viewDir(ctx) {
  const { path } = ctx;
  const entries = await loadChildren(path);
  if (!ctx.alive()) return;
  const lower = new Map(entries.map((entry) => [entry.name.toLowerCase(), entry]));

  const index = lower.get("index.html") || lower.get("index.htm");
  if (index && !index.dir) {
    const page = join(path, index.name);
    ctx.watch(page);
    return viewHtml(ctx, page);
  }

  const files = entries.filter((entry) => !entry.dir);
  const media = files.filter((entry) => ["image", "video"].includes(kindOf(entry.name))).length;
  const saved = store.get("layout:" + path, null);
  let layout = saved || (media >= 4 && media / Math.max(entries.length, 1) > 0.5 ? "grid" : "list");
  let order = { key: "name", direction: 1 };

  const holder = h("div");
  const listButton = h("button", { title: "List", "aria-label": "List view", onclick: () => setLayout("list") }, icon("list"));
  const gridButton = h("button", { title: "Gallery", "aria-label": "Gallery view", onclick: () => setLayout("grid") }, icon("grid"));

  function setLayout(next) {
    layout = next;
    store.set("layout:" + path, next);
    drawItems();
  }

  function sortBy(key) {
    order = order.key === key ? { key, direction: -order.direction } : { key, direction: key === "name" ? 1 : -1 };
    drawItems();
  }

  function drawItems() {
    listButton.className = layout === "list" ? "on" : "";
    gridButton.className = layout === "grid" ? "on" : "";
    const sorted = sortEntries(entries, order);
    const box = h("div", { class: layout === "grid" ? "grid" : "" });
    const make = layout === "grid" ? folderCard : folderItem;
    const sentinel = h("div", { class: "sentinel" });
    let drawn = 0;
    function drawBatch() {
      const next = sorted.slice(drawn, drawn + BATCH);
      box.append(...next.map((entry) => make(path, entry)));
      drawn += next.length;
      if (drawn >= sorted.length) observer.disconnect();
    }
    const observer = new IntersectionObserver((seen) => {
      if (seen.some((item) => item.isIntersecting)) drawBatch();
    }, { root: view, rootMargin: "800px" });
    drawBatch();
    const head = layout === "list" && h("div", { class: "list-head" },
      h("button", { onclick: () => sortBy("name") }, "Name"),
      h("button", { onclick: () => sortBy("mtime") }, "Modified"),
      h("button", { onclick: () => sortBy("size") }, "Size"));
    holder.replaceChildren(...[head, box, sentinel].filter(Boolean));
    if (drawn < sorted.length) observer.observe(sentinel);
    ctx.cleanup.push(() => observer.disconnect());
  }

  drawItems();
  const folders = entries.length - files.length;
  const counts = [folders && `${folders.toLocaleString()} folder${folders === 1 ? "" : "s"}`, files.length && `${files.length.toLocaleString()} file${files.length === 1 ? "" : "s"}`].filter(Boolean).join(", ");
  const page = h("div", { class: "page wide" },
    h("div", { class: "folder-head" },
      h("h1", null, path ? baseName(path) : state.config.name),
      h("span", { class: "count" }, counts || "Empty folder"),
      entries.length ? h("div", { class: "seg" }, listButton, gridButton) : null),
    holder);

  const readme = files.find((entry) => /^readme(\.(md|markdown))?$/i.test(entry.name));
  if (readme) {
    const readmePath = join(path, readme.name);
    const response = await fetch(rawUrl(readmePath));
    const source = await response.text();
    if (!ctx.alive()) return;
    page.append(h("div", { class: "readme" }, renderMarkdown(source, readmePath)));
  }
  ctx.el.append(page);
}

// ---------- routing ----------

function viewJsonl(ctx) {
  // Off in Settings, or flipped here, JSONL shows as highlighted text.
  ctx.actions.push(h("button", {
    class: "icon-btn",
    title: settings.jsonlTable ? "Show as text" : "Show as a table",
    "aria-label": settings.jsonlTable ? "Show as text" : "Show as a table",
    onclick: () => { setSetting("jsonlTable", !settings.jsonlTable); render({ keepScroll: true }); },
  }, icon(settings.jsonlTable ? "text" : "table")));
  return settings.jsonlTable && !ctx.params.get("line") ? viewTable(ctx, "jsonl") : viewText(ctx);
}

const VIEWERS = {
  image: viewImage, video: viewVideo, audio: viewAudio, md: viewMarkdown,
  html: viewHtml, csv: (ctx) => viewTable(ctx, "csv"), jsonl: viewJsonl, pdf: viewPdf, json: viewJson,
  docx: viewDocx, xlsx: viewXlsx, binary: viewBinary,
  text: (ctx) => viewText(ctx),
};

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const cut = raw.indexOf("?");
  const encoded = (cut < 0 ? raw : raw.slice(0, cut)).replace(/\/$/, "");
  const params = new URLSearchParams(cut < 0 ? "" : raw.slice(cut + 1));
  let path = encoded;
  try { path = decodeURIComponent(encoded); } catch (e) { /* leave as typed */ }
  return { path, params };
}

async function render({ keepScroll = false } = {}) {
  const token = ++state.token;
  for (const undo of state.cleanup.splice(0)) undo();
  state.reload = null;
  state.stepMeta = null;
  state.pendingChange = false;

  const { path, params } = parseHash();
  const alive = () => token === state.token;
  const stepping = state.stepping;
  state.stepping = false;
  closeStarMenu();
  closeTagMenu();
  const fromSections = state.fromSections;
  state.fromSections = false;
  const top = view.scrollTop;
  const spinner = keepScroll ? null : setTimeout(() => {
    if (alive()) view.replaceChildren(h("div", { class: "spin" }, "Loading…"));
  }, 200);

  state.path = path;
  let stat = null;
  try {
    stat = await api("stat", { path });
  } catch (error) { /* shown below */ }
  if (!alive()) return;
  state.stat = stat;
  state.watch = path;
  renderChrome();
  // Not on a live refresh, which would undo a folder the user just collapsed.
  // Not from a Recent, Favorites or tag click either: the sidebar would jump
  // away from the list you just clicked in.
  if (!keepScroll) revealInTree(path, stat && stat.type === "dir", !fromSections);

  const el = h("div");
  const ctx = {
    path, stat, el, alive, params,
    cleanup: state.cleanup,
    mounted: [],
    actions: [],      // extra top-bar buttons for this view
    fill: () => { el.className = "fill"; },
    watch: (file) => { state.watch = file; },
    step: null,
    set reload(fn) { state.reload = fn; },
  };

  try {
    if (!stat) {
      el.append(notice("alert", "Not found", path ? `Nothing at /${path}` : "", "It may have moved, or it may be a hidden file."));
    } else if (stat.type === "dir") {
      state.kind = "dir";
      await viewDir(ctx);
    } else {
      state.kind = kindOf(baseName(path));
      await VIEWERS[state.kind](ctx);
    }
  } catch (error) {
    if (!alive()) return;
    console.error(error);
    el.replaceChildren(notice("alert", "Could not open this", String(error.message || error), stat && stat.type === "file" ? downloadButton(path) : null));
  }
  if (!alive()) return;
  clearTimeout(spinner);
  state.step = ctx.step;
  state.lastSeen = stat && stat.mtime + ":" + stat.size;
  if (state.watch !== path) {
    const watched = await api("stat", { path: state.watch }).catch(() => null);
    if (!alive()) return;
    state.lastSeen = watched && watched.mtime + ":" + watched.size;
  }
  view.replaceChildren(el);
  view.scrollTop = keepScroll ? top : 0;
  ctx.mounted.forEach((run) => run());
  if (ctx.actions.length) $("#actions").prepend(...ctx.actions);
  // Paging through a folder with the arrow keys would bury everything else.
  if (stat && stat.type === "file" && !stepping && !keepScroll) changePlaces({ op: "visit", path }, { quiet: true });
  $("#topbar").classList.toggle("lined", el.className === "fill" || state.kind === "text" || state.kind === "json");
  if (state.stepMeta && stat) $("#meta").textContent = `${state.stepMeta} · ${formatSize(stat.size)}`;
}

// Live reload: when the open file changes on disk, show the new version.
async function poll() {
  if (document.hidden || !state.config || !state.lastSeen || !settings.liveReload) return;
  const token = state.token;
  const watched = state.watch;
  const stat = await api("stat", { path: watched }).catch(() => null);
  if (!stat || token !== state.token || watched !== state.watch) return;
  const seen = stat.mtime + ":" + stat.size;
  if (seen === state.lastSeen) return;
  state.lastSeen = seen;
  if (state.kind === "video" || state.kind === "audio") return;
  if (state.reload) return state.reload();
  if (stat.type === "dir") await loadChildren(watched).then(renderTree);
  if (stat.size > AUTO_RELOAD_MAX && stat.type === "file") {
    // Too big to re-read every few seconds, e.g. a growing log. Let the user choose.
    if (state.pendingChange) return;
    state.pendingChange = true;
    $("#actions").prepend(h("button", { class: "pill", onclick: () => render({ keepScroll: true }) }, "Changed · Reload"));
    return;
  }
  render({ keepScroll: true });
}

// ---------- shell behavior ----------

function closeDrawer() { document.body.classList.remove("side-open"); }

function toggleSidebar() {
  if (matchMedia("(max-width: 760px)").matches) {
    document.body.classList.toggle("side-open");
    return;
  }
  const hidden = document.body.classList.toggle("side-hidden");
  store.set("sideHidden", hidden);
}

function setupResize() {
  const handle = $("#resizer");
  const width = store.get("sideWidth", null);
  if (width) document.documentElement.style.setProperty("--side-w", width + "px");
  handle.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    handle.setPointerCapture(event.pointerId);
    document.body.classList.add("resizing");
    const move = (moved) => {
      const next = Math.min(Math.max(moved.clientX, 200), 560);
      document.documentElement.style.setProperty("--side-w", next + "px");
      store.set("sideWidth", next);
    };
    const stop = () => {
      document.body.classList.remove("resizing");
      handle.removeEventListener("pointermove", move);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", stop, { once: true });
  });
}

// Video keys run in the capture phase and cancel the default, so the player's
// own shortcuts (Space, arrows) don't fire twice.
document.addEventListener("keydown", (event) => {
  const controls = state.video;
  if (!controls || event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.target.closest && event.target.closest("input, textarea, select")) return;
  const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
  const actions = {
    " ": () => controls.toggle(),
    k: () => controls.toggle(),
    ",": () => controls.step(-1),
    ".": () => controls.step(1),
    j: () => controls.seek(event.shiftKey ? -5 : -1),
    l: () => controls.seek(event.shiftKey ? 5 : 1),
    "[": () => controls.rate(-1),
    "]": () => controls.rate(1),
    t: () => controls.copyLink(),
    ArrowLeft: () => state.step && state.step(-1),
    ArrowRight: () => state.step && state.step(1),
  };
  if (!actions[key]) return;
  event.preventDefault();
  // Immediate: when the page itself has focus, the target is the document, and
  // plain stopPropagation would still let the handler below run too.
  event.stopImmediatePropagation();
  actions[key]();
}, true);

document.addEventListener("keydown", (event) => {
  if (event.defaultPrevented) return;
  const mod = event.ctrlKey || event.metaKey;
  if (mod && event.shiftKey && event.key.toLowerCase() === "f") {
    event.preventDefault();
    if (document.body.classList.contains("side-hidden")) toggleSidebar();
    document.body.classList.add("side-open");
    setSearchMode("contents");
    input.focus();
    input.select();
  } else if (mod && event.key.toLowerCase() === "k") {
    event.preventDefault();
    if (document.body.classList.contains("side-hidden")) toggleSidebar();
    document.body.classList.add("side-open");
    setSearchMode("names");
    input.focus();
    input.select();
  } else if (mod && event.key === "\\") {
    event.preventDefault();
    toggleSidebar();
  } else if (event.key === "Escape" && ($("#settings") || $("#tagmenu") || $("#starmenu"))) {
    closeSettings();
    closeTagMenu();
    closeStarMenu();
  } else if (!mod && state.step && !event.target.closest("input, textarea, select")) {
    if (event.key === "ArrowLeft") state.step(-1);
    if (event.key === "ArrowRight") state.step(1);
  }
});

async function start() {
  state.config = await api("config");
  $("#root-name").textContent = state.config.name;
  $("#root-link").title = state.config.root;
  $("#search-icon").replaceChildren(icon("search"));
  $("#search-key").textContent = /Mac/.test(navigator.platform) ? "⌘K" : "Ctrl K";
  $("#collapse").replaceChildren(icon("panel"));
  $("#expand").replaceChildren(icon("panel"));
  $("#collapse").addEventListener("click", toggleSidebar);
  $("#expand").addEventListener("click", toggleSidebar);
  $("#scrim").addEventListener("click", closeDrawer);
  $("#settings-btn").replaceChildren(icon("gear"));
  $("#settings-btn").addEventListener("click", openSettings);
  for (const button of document.querySelectorAll(".search-modes button")) {
    button.addEventListener("click", () => { setSearchMode(button.dataset.mode); input.focus(); });
  }
  if (!state.config.features.contents) document.querySelector(".search-modes").hidden = true;
  if (store.get("sideHidden", false)) document.body.classList.add("side-hidden");
  setupResize();
  showFooter(state.config);
  if (state.config.indexing) watchIndexing();

  const filesHead = $("#files-head");
  filesHead.addEventListener("click", () => toggleSection("files"));
  filesHead.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); toggleSection("files"); }
  });
  loadPlaces();
  await loadChildren("");
  // Restored folders may be gone, or belong to a different root on this port.
  await Promise.all([...tree.open].map(loadChildren));
  renderTree();

  window.addEventListener("hashchange", () => render());
  window.addEventListener("focus", refreshOpenFolders);
  setInterval(poll, POLL_MS);
  render();
}

start();
