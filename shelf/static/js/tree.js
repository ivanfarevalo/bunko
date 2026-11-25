// The folder tree in the sidebar.

import { api } from "./api.js";
import { $, h } from "./dom.js";
import { icon } from "./icons.js";
import { iconFor, kindOf } from "./kinds.js";
import { appUrl, baseName, join, parentOf } from "./paths.js";
import { closeDrawer } from "./sidebar.js";
import { state } from "./state.js";
import { store } from "./store.js";

export const TREE_PAGE = 300; // children drawn per folder before "Show more"

export const tree = { children: new Map(), open: new Set(store.get("open", [])), limit: new Map() };

export async function loadChildren(path) {
  try {
    const { entries } = await api("list", { path });
    tree.children.set(path, entries);
    return entries;
  } catch {
    tree.children.set(path, []);
    tree.open.delete(path);
    return [];
  }
}

export function saveOpen() {
  store.set("open", [...tree.open]);
}

export function treeRows(dir, depth, rows) {
  const entries = tree.children.get(dir) || [];
  const limit = tree.limit.get(dir) || TREE_PAGE;
  for (const entry of entries.slice(0, limit)) {
    const path = join(dir, entry.name);
    const isOpen = entry.dir && tree.open.has(path);
    const chevron = h(
      "span",
      {
        class: `chev${isOpen ? " open" : ""}${entry.dir ? "" : " none"}`,
        role: "button",
        "aria-label": isOpen ? "Collapse" : "Expand",
        onclick: (event) => {
          event.preventDefault();
          event.stopPropagation();
          toggleDir(path);
        },
      },
      icon("chevron"),
    );
    rows.push(
      h(
        "a",
        {
          class: `row${path === state.path ? " current" : ""}`,
          href: appUrl(path),
          style: `--d:${depth}`,
          title: entry.name,
          "data-path": path,
          onclick: () => {
            if (entry.dir && !isOpen) toggleDir(path);
            closeDrawer();
          },
        },
        chevron,
        icon(iconFor(entry)),
        h("span", { class: "label" }, entry.name),
      ),
    );
    if (isOpen) {
      if (!tree.children.has(path)) rows.push(h("div", { class: "row empty", style: `--d:${depth + 2}` }, "Loading…"));
      else if (!tree.children.get(path).length)
        rows.push(h("div", { class: "row empty", style: `--d:${depth + 2}` }, "Empty"));
      else treeRows(path, depth + 1, rows);
    }
  }
  if (entries.length > limit) {
    rows.push(
      h(
        "div",
        {
          class: "row more",
          style: `--d:${depth + 1}`,
          onclick: () => {
            tree.limit.set(dir, limit + TREE_PAGE * 3);
            renderTree();
          },
        },
        `Show ${Math.min(TREE_PAGE * 3, entries.length - limit).toLocaleString()} more of ${(entries.length - limit).toLocaleString()}`,
      ),
    );
  }
}

export function renderTree() {
  const rows = [];
  treeRows("", 0, rows);
  $("#tree").replaceChildren(...rows);
}

export async function toggleDir(path) {
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

export async function revealInTree(path, isDir, scroll = true) {
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

export async function refreshOpenFolders() {
  await Promise.all(["", ...tree.open].map(loadChildren));
  renderTree();
}

export async function siblings(path, kinds) {
  const dir = parentOf(path);
  const entries = tree.children.get(dir) || (await loadChildren(dir));
  return entries
    .filter((entry) => !entry.dir && kinds.includes(kindOf(entry.name)))
    .map((entry) => join(dir, entry.name));
}
