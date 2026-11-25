// The Settings panel.

import { setTheme } from "./chrome.js";
import { $, h } from "./dom.js";
import { state } from "./state.js";
import { setSetting, settings } from "./store.js";

export const DOCS = "https://github.com/ivanfarevalo/bunko/tree/main/docs";

export const SHORTCUTS = [
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

export function closeSettings() {
  const panel = $("#settings");
  if (panel) panel.remove();
  document.removeEventListener("pointerdown", settingsOutside, true);
}

export function settingsOutside(event) {
  if (!event.target.closest("#settings, #settings-btn")) closeSettings();
}

export function openSettings(onChange) {
  if ($("#settings")) return closeSettings();
  const { features, access } = state.config;
  const theme = document.documentElement.dataset.theme || "system";
  const themeRow = h(
    "div",
    { class: "seg wide" },
    ["system", "light", "dark"].map((mode) =>
      h(
        "button",
        {
          class: mode === theme ? "on" : "",
          onclick: (event) => {
            setTheme(mode);
            for (const button of event.target.parentNode.children)
              button.classList.toggle("on", button === event.target);
          },
        },
        mode[0].toUpperCase() + mode.slice(1),
      ),
    ),
  );
  const toggle = (key, label, note) =>
    h(
      "label",
      { class: "opt" },
      h("input", {
        type: "checkbox",
        checked: settings[key],
        onchange: (event) => {
          setSetting(key, event.target.checked);
          onChange();
        },
      }),
      h("span", null, label, note && h("small", null, note)),
    );
  let account;
  if (access.mode === "tailscale")
    account = h("p", null, "Signed in as ", h("b", null, access.user || "?"), " through Tailscale.");
  else if (access.mode === "token")
    account = h("p", null, "Signed in with an access token. ", h("a", { href: "/__bunko/logout" }, "Sign out"));
  else
    account = h(
      "p",
      null,
      "No access control on this server. ",
      h("a", { href: `${DOCS}/security.md`, target: "_blank", rel: "noopener" }, "Securing Bunko"),
    );
  const panel = h(
    "div",
    { id: "settings", class: "popover", role: "dialog", "aria-label": "Settings" },
    h("div", { class: "pop-title" }, "Settings"),
    h("div", { class: "pop-label" }, "Theme"),
    themeRow,
    h("div", { class: "pop-label" }, "Viewers"),
    toggle("toc", "Outline beside Markdown"),
    toggle("jsonlTable", "JSONL files as tables"),
    toggle(
      "thumbnails",
      "Thumbnails in galleries",
      features.thumbnails ? null : "ffmpeg isn't installed on the server, so videos show icons",
    ),
    toggle("liveReload", "Reload files when they change on disk"),
    h(
      "details",
      { class: "keys" },
      h("summary", null, "Keyboard shortcuts"),
      h(
        "dl",
        null,
        SHORTCUTS.map(([keys, what]) => [h("dt", null, keys), h("dd", null, what)]),
      ),
    ),
    h("div", { class: "pop-label" }, "Access"),
    account,
    h(
      "div",
      { class: "pop-foot" },
      `Bunko ${state.config.version} · `,
      h("a", { href: DOCS.replace(/\/tree\/main\/docs$/, ""), target: "_blank", rel: "noopener" }, "Docs and source"),
    ),
  );
  document.body.append(panel);
  document.addEventListener("pointerdown", settingsOutside, true);
}
