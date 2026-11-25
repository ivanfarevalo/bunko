// HTML pages and PDFs, in frames.

import { api } from "../api.js";
import { renderChrome } from "../chrome.js";
import { h } from "../dom.js";
import { appUrl, baseName, rawUrl } from "../paths.js";
import { changePlaces } from "../places.js";
import { state } from "../state.js";
import { revealInTree } from "../tree.js";

export function viewHtml(ctx, page) {
  // allow-same-origin keeps relative fetches and storage working, as they do
  // under http.server. Leaving out allow-top-navigation stops a page from
  // replacing this app.
  const frame = h("iframe", {
    class: "page-frame",
    src: rawUrl(page || ctx.path),
    title: baseName(page || ctx.path),
  });
  frame.setAttribute(
    "sandbox",
    "allow-same-origin allow-scripts allow-forms allow-popups allow-modals allow-downloads",
  );
  frame.addEventListener("load", () => {
    if (!ctx.alive()) return;
    let inside;
    try {
      inside = frame.contentWindow;
      inside.location.pathname;
    } catch {
      return;
    }
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
export async function followFrame(path) {
  try {
    const stat = await api("stat", { path });
    history.replaceState(null, "", appUrl(path));
    state.path = path;
    state.watch = path;
    state.stat = stat;
    renderChrome();
    revealInTree(path, stat.type === "dir");
    if (stat.type === "file") changePlaces({ op: "visit", path }, { quiet: true });
  } catch {
    /* a 404 inside the frame: it shows its own error */
  }
}

export function viewPdf(ctx) {
  // No sandbox here: Chrome will not load its PDF viewer in a sandboxed frame.
  ctx.fill();
  ctx.el.append(h("iframe", { class: "page-frame", src: rawUrl(ctx.path), title: baseName(ctx.path) }));
}
