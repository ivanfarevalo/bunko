// Text and code, JSON, and files with no preview.

import { fetchRange } from "../api.js";
import { h, notice } from "../dom.js";
import { formatSize } from "../format.js";
import { icon } from "../icons.js";
import { languageFor } from "../kinds.js";
import { AUTO_RELOAD_MAX, HIGHLIGHT_MAX, JUMP_MAX, TEXT_CHUNK } from "../limits.js";
import { baseName, extOf, rawUrl } from "../paths.js";
import { view } from "../state.js";

export function downloadButton(path) {
  return h("a", { class: "btn", href: rawUrl(path), download: baseName(path) }, icon("download"), "Download");
}

export const NO_PREVIEW = {
  doc: "Older Word files (.doc) don't preview. Saved as .docx, they do.",
  xls: "Older Excel files (.xls) don't preview. Saved as .xlsx, they do.",
  xlsb: "Binary Excel files (.xlsb) don't preview. Saved as .xlsx, they do.",
  ppt: "PowerPoint files don't preview yet.",
  pptx: "PowerPoint files don't preview yet.",
};

export function viewBinary(ctx) {
  const why = NO_PREVIEW[extOf(ctx.path)] || "no preview for this file type";
  ctx.el.append(notice("file", baseName(ctx.path), `${formatSize(ctx.stat.size)} · ${why}`, downloadButton(ctx.path)));
}

export function codeBlock(text, language) {
  const code = h("code", { class: language ? `language-${language}` : "" }, text);
  if (language && text.length <= HIGHLIGHT_MAX) hljs.highlightElement(code);
  return h("div", { class: "block" }, h("pre", null, code));
}

export const looksBinary = (bytes) => bytes.subarray(0, 8192).includes(0);

export async function viewText(ctx, pretty) {
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
    gutter.textContent = lines.map((_, number) => number + 1).join("\n");
    if (language && text.length <= HIGHLIGHT_MAX) {
      code.innerHTML = hljs.highlight(text, { language, ignoreIllegals: true }).value;
    } else {
      code.textContent = text;
    }
    footer.replaceChildren();
    if (offset < stat.size) {
      footer.append(
        `Showing ${formatSize(offset)} of ${formatSize(stat.size)}`,
        h("button", { class: "btn", onclick: more }, "Load more"),
      );
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

export function markLine(box, source, number) {
  const style = getComputedStyle(source);
  const height = parseFloat(style.lineHeight);
  const top = parseFloat(style.paddingTop) + (number - 1) * height;
  box.append(h("div", { class: "line-mark", style: `top:${top}px;height:${height}px` }));
  view.scrollTop = Math.max(top - view.clientHeight / 3, 0);
}

export async function viewJson(ctx) {
  if (ctx.stat.size <= AUTO_RELOAD_MAX && !ctx.params.get("line")) {
    const response = await fetch(rawUrl(ctx.path));
    const source = await response.text();
    if (!ctx.alive()) return;
    try {
      return await viewText(ctx, JSON.stringify(JSON.parse(source), null, 2));
    } catch {
      /* invalid JSON: show it as written */
    }
  }
  return viewText(ctx);
}
