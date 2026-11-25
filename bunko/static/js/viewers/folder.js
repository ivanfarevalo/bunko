// Folder listings and galleries.

import { API } from "../api.js";
import { h } from "../dom.js";
import { formatSize, formatWhen } from "../format.js";
import { icon } from "../icons.js";
import { iconFor, kindOf } from "../kinds.js";
import { appUrl, baseName, extOf, join, rawUrl } from "../paths.js";
import { state, view } from "../state.js";
import { settings, store } from "../store.js";
import { loadChildren } from "../tree.js";
import { renderMarkdown } from "./document.js";
import { viewHtml } from "./page.js";

export const BATCH = 200; // folder items drawn per scroll step

export function sortEntries(entries, how) {
  const { key, direction } = how;
  const copy = [...entries];
  if (key === "name") return direction > 0 ? copy : copy.reverse();
  return copy.sort((a, b) => b.dir - a.dir || direction * (a[key] - b[key]));
}

export function folderItem(dir, entry) {
  const path = join(dir, entry.name);
  return h(
    "a",
    { class: "item", href: appUrl(path), title: entry.name },
    h("span", { class: "n" }, icon(iconFor(entry)), h("span", null, entry.name)),
    h("span", { class: "when" }, formatWhen(entry.mtime)),
    h("span", { class: "size" }, entry.dir ? "" : formatSize(entry.size)),
  );
}

export const thumbUrl = (path, entry) => `${API}thumb?${new URLSearchParams({ path, v: entry.mtime })}`;

export function cardPicture(path, entry) {
  const kind = entry.dir ? null : kindOf(entry.name);
  const thumbs = settings.thumbnails;
  if (kind === "image") {
    // Thumbnail first; if the server can't make one, the original; then an icon.
    const useThumb = thumbs && extOf(entry.name) !== "svg";
    const image = h("img", {
      src: useThumb ? thumbUrl(path, entry) : rawUrl(path),
      alt: "",
      loading: "lazy",
      decoding: "async",
    });
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
    poster.addEventListener("error", () => {
      badge.remove();
      poster.replaceWith(icon("video"));
    });
    return [poster, badge];
  }
  return [icon(iconFor(entry))];
}

export function folderCard(dir, entry) {
  const path = join(dir, entry.name);
  return h(
    "a",
    { class: "card", href: appUrl(path), title: entry.name },
    h("div", { class: "thumb" }, cardPicture(path, entry)),
    h("div", { class: "cap" }, entry.name),
  );
}

export async function viewDir(ctx) {
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
  const saved = store.get(`layout:${path}`, null);
  let layout = saved || (media >= 4 && media / Math.max(entries.length, 1) > 0.5 ? "grid" : "list");
  let order = { key: "name", direction: 1 };

  const holder = h("div");
  const listButton = h(
    "button",
    { title: "List", "aria-label": "List view", onclick: () => setLayout("list") },
    icon("list"),
  );
  const gridButton = h(
    "button",
    { title: "Gallery", "aria-label": "Gallery view", onclick: () => setLayout("grid") },
    icon("grid"),
  );

  function setLayout(next) {
    layout = next;
    store.set(`layout:${path}`, next);
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
    const observer = new IntersectionObserver(
      (seen) => {
        if (seen.some((item) => item.isIntersecting)) drawBatch();
      },
      { root: view, rootMargin: "800px" },
    );
    drawBatch();
    const head =
      layout === "list" &&
      h(
        "div",
        { class: "list-head" },
        h("button", { onclick: () => sortBy("name") }, "Name"),
        h("button", { onclick: () => sortBy("mtime") }, "Modified"),
        h("button", { onclick: () => sortBy("size") }, "Size"),
      );
    holder.replaceChildren(...[head, box, sentinel].filter(Boolean));
    if (drawn < sorted.length) observer.observe(sentinel);
    ctx.cleanup.push(() => observer.disconnect());
  }

  drawItems();
  const folders = entries.length - files.length;
  const counts = [
    folders && `${folders.toLocaleString()} folder${folders === 1 ? "" : "s"}`,
    files.length && `${files.length.toLocaleString()} file${files.length === 1 ? "" : "s"}`,
  ]
    .filter(Boolean)
    .join(", ");
  const page = h(
    "div",
    { class: "page wide" },
    h(
      "div",
      { class: "folder-head" },
      h("h1", null, path ? baseName(path) : state.config.name),
      h("span", { class: "count" }, counts || "Empty folder"),
      entries.length ? h("div", { class: "seg" }, listButton, gridButton) : null,
    ),
    holder,
  );

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
