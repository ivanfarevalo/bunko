// The entry point: routing by the URL hash, rendering a path, live reload, and keyboard shortcuts.

import { api } from "./api.js";
import { renderChrome } from "./chrome.js";
import { $, h, notice } from "./dom.js";
import { formatSize } from "./format.js";
import { icon } from "./icons.js";
import { kindOf } from "./kinds.js";
import { AUTO_RELOAD_MAX } from "./limits.js";
import { baseName } from "./paths.js";
import { changePlaces, closeStarMenu, closeTagMenu, loadPlaces, toggleSection } from "./places.js";
import { input, setSearchMode, setupSearch, showFooter, watchIndexing } from "./search.js";
import { closeSettings, openSettings } from "./settings-panel.js";
import { closeDrawer, setupResize, toggleSidebar } from "./sidebar.js";
import { state, view } from "./state.js";
import { settings, store } from "./store.js";
import { loadChildren, refreshOpenFolders, renderTree, revealInTree, tree } from "./tree.js";
import { viewDocx, viewMarkdown } from "./viewers/document.js";
import { viewDir } from "./viewers/folder.js";
import { viewAudio, viewImage, viewVideo } from "./viewers/media.js";
import { viewHtml, viewPdf } from "./viewers/page.js";
import { viewJsonl, viewTable, viewXlsx } from "./viewers/table.js";
import { downloadButton, viewBinary, viewJson, viewText } from "./viewers/text.js";

export const POLL_MS = 2500;

export const VIEWERS = {
  image: viewImage,
  video: viewVideo,
  audio: viewAudio,
  md: viewMarkdown,
  html: viewHtml,
  csv: (ctx) => viewTable(ctx, "csv"),
  jsonl: viewJsonl,
  pdf: viewPdf,
  json: viewJson,
  docx: viewDocx,
  xlsx: viewXlsx,
  binary: viewBinary,
  text: (ctx) => viewText(ctx),
};

export function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const cut = raw.indexOf("?");
  const encoded = (cut < 0 ? raw : raw.slice(0, cut)).replace(/\/$/, "");
  const params = new URLSearchParams(cut < 0 ? "" : raw.slice(cut + 1));
  let path = encoded;
  try {
    path = decodeURIComponent(encoded);
  } catch {
    /* leave as typed */
  }
  return { path, params };
}

export async function render({ keepScroll = false } = {}) {
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
  const spinner = keepScroll
    ? null
    : setTimeout(() => {
        if (alive()) view.replaceChildren(h("div", { class: "spin" }, "Loading…"));
      }, 200);

  state.path = path;
  let stat = null;
  try {
    stat = await api("stat", { path });
  } catch {
    /* shown below */
  }
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
    path,
    stat,
    el,
    alive,
    params,
    cleanup: state.cleanup,
    mounted: [],
    actions: [], // extra top-bar buttons for this view
    fill: () => {
      el.className = "fill";
    },
    watch: (file) => {
      state.watch = file;
    },
    step: null,
    rerender: (options) => render(options),
    set reload(fn) {
      state.reload = fn;
    },
  };

  try {
    if (!stat) {
      el.append(
        notice(
          "alert",
          "Not found",
          path ? `Nothing at /${path}` : "",
          "It may have moved, or it may be a hidden file.",
        ),
      );
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
    el.replaceChildren(
      notice(
        "alert",
        "Could not open this",
        String(error.message || error),
        stat && stat.type === "file" ? downloadButton(path) : null,
      ),
    );
  }
  if (!alive()) return;
  clearTimeout(spinner);
  state.step = ctx.step;
  state.lastSeen = stat && `${stat.mtime}:${stat.size}`;
  if (state.watch !== path) {
    const watched = await api("stat", { path: state.watch }).catch(() => null);
    if (!alive()) return;
    state.lastSeen = watched && `${watched.mtime}:${watched.size}`;
  }
  view.replaceChildren(el);
  view.scrollTop = keepScroll ? top : 0;
  for (const run of ctx.mounted) run();
  if (ctx.actions.length) $("#actions").prepend(...ctx.actions);
  // Paging through a folder with the arrow keys would bury everything else.
  if (stat && stat.type === "file" && !stepping && !keepScroll) changePlaces({ op: "visit", path }, { quiet: true });
  $("#topbar").classList.toggle("lined", el.className === "fill" || state.kind === "text" || state.kind === "json");
  if (state.stepMeta && stat) $("#meta").textContent = `${state.stepMeta} · ${formatSize(stat.size)}`;
}

// Live reload: when the open file changes on disk, show the new version.
export async function poll() {
  if (document.hidden || !state.config || !state.lastSeen || !settings.liveReload) return;
  const token = state.token;
  const watched = state.watch;
  const stat = await api("stat", { path: watched }).catch(() => null);
  if (!stat || token !== state.token || watched !== state.watch) return;
  const seen = `${stat.mtime}:${stat.size}`;
  if (seen === state.lastSeen) return;
  state.lastSeen = seen;
  if (state.kind === "video" || state.kind === "audio") return;
  if (state.reload) return state.reload();
  if (stat.type === "dir") await loadChildren(watched).then(renderTree);
  if (stat.size > AUTO_RELOAD_MAX && stat.type === "file") {
    // Too big to re-read every few seconds, e.g. a growing log. Let the user choose.
    if (state.pendingChange) return;
    state.pendingChange = true;
    $("#actions").prepend(
      h("button", { class: "pill", onclick: () => render({ keepScroll: true }) }, "Changed · Reload"),
    );
    return;
  }
  render({ keepScroll: true });
}

export async function main() {
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
  $("#settings-btn").addEventListener("click", () => openSettings(() => render({ keepScroll: true })));
  for (const button of document.querySelectorAll(".search-modes button")) {
    button.addEventListener("click", () => {
      setSearchMode(button.dataset.mode);
      input.focus();
    });
  }
  if (!state.config.features.contents) document.querySelector(".search-modes").hidden = true;
  if (store.get("sideHidden", false)) document.body.classList.add("side-hidden");
  setupResize();
  setupSearch();
  showFooter(state.config);
  if (state.config.indexing) watchIndexing();

  const filesHead = $("#files-head");
  filesHead.addEventListener("click", () => toggleSection("files"));
  filesHead.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      toggleSection("files");
    }
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

// Video keys run in the capture phase and cancel the default, so the player's
// own shortcuts (Space, arrows) don't fire twice.
document.addEventListener(
  "keydown",
  (event) => {
    const controls = state.video;
    if (!controls || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.target.closest?.("input, textarea, select")) return;
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
      ArrowLeft: () => state.step?.(-1),
      ArrowRight: () => state.step?.(1),
    };
    if (!actions[key]) return;
    event.preventDefault();
    // Immediate: when the page itself has focus, the target is the document, and
    // plain stopPropagation would still let the handler below run too.
    event.stopImmediatePropagation();
    actions[key]();
  },
  true,
);

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

main();
