// The top bar: breadcrumbs, file facts, and actions.

import { $, copyText, h } from "./dom.js";
import { formatSize, formatWhen } from "./format.js";
import { icon } from "./icons.js";
import { appUrl, baseName, join, rawUrl } from "./paths.js";
import { openStarMenu, openTagMenu, renderPlaceActions, renderPlaces } from "./places.js";
import { state } from "./state.js";
import { store } from "./store.js";

export function renderChrome() {
  const { path, stat } = state;
  const crumbs = [h("a", { href: "#/" }, state.config.name)];
  let walked = "";
  for (const part of path.split("/").filter(Boolean)) {
    walked = join(walked, part);
    crumbs.push(h("span", { class: "sep" }, "/"), h("a", { href: appUrl(walked), title: part }, part));
  }
  $("#crumbs").replaceChildren(...crumbs);

  const meta = stat && stat.type === "file" ? `${formatSize(stat.size)} · ${formatWhen(stat.mtime)}` : "";
  $("#meta").textContent = meta;
  $("#meta").title = stat ? new Date(stat.mtime * 1000).toLocaleString() : "";

  const isFile = stat && stat.type === "file";
  const absolute = path ? `${state.config.root}/${path}` : state.config.root;
  const copyButton = h(
    "button",
    { class: "icon-btn", title: "Copy full path", "aria-label": "Copy full path" },
    icon("copy"),
  );
  copyButton.addEventListener("click", async () => {
    await copyText(absolute);
    copyButton.title = "Copied";
    setTimeout(() => {
      copyButton.title = "Copy full path";
    }, 1500);
  });
  $("#actions").replaceChildren(
    ...[
      isFile &&
        h(
          "a",
          {
            class: "icon-btn",
            href: rawUrl(path),
            target: "_blank",
            rel: "noopener",
            title: "Open raw file in a new tab",
            "aria-label": "Open raw file",
          },
          icon("external"),
        ),
      isFile &&
        h(
          "a",
          {
            class: "icon-btn",
            href: rawUrl(path),
            download: baseName(path),
            title: "Download",
            "aria-label": "Download",
          },
          icon("download"),
        ),
      path &&
        stat &&
        h(
          "button",
          { id: "star-btn", class: "icon-btn star", onclick: (event) => openStarMenu(event.currentTarget, path) },
          icon("star"),
        ),
      path &&
        stat &&
        h(
          "button",
          {
            id: "tag-btn",
            class: "icon-btn",
            title: "Tags",
            "aria-label": "Tags",
            onclick: (event) => openTagMenu(event.currentTarget, path),
          },
          icon("tag"),
        ),
      copyButton,
      h(
        "button",
        { class: "icon-btn", title: "Switch light / dark", "aria-label": "Switch theme", onclick: toggleTheme },
        icon("theme"),
      ),
    ].filter(Boolean),
  );
  document.title = `${path ? baseName(path) : state.config.name} · shelf`;
  renderPlaceActions();
  renderPlaces();
}

export function setTheme(mode) {
  const root = document.documentElement;
  if (mode === "system") delete root.dataset.theme;
  else root.dataset.theme = mode;
  store.set("theme", mode === "system" ? null : mode);
}

export function toggleTheme() {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  setTheme(dark ? "light" : "dark");
}
