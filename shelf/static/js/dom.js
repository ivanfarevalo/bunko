// Small DOM helpers shared by every module.

import { icon } from "./icons.js";

export const $ = (selector) => document.querySelector(selector);

export function h(tag, props, ...kids) {
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

// navigator.clipboard only exists on HTTPS and localhost, and this usually runs
// over plain HTTP on a remote host.
export async function copyText(text) {
  if (navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      /* fall through */
    }
  }
  const area = h("textarea", { value: text, style: "position:fixed;opacity:0" });
  document.body.append(area);
  area.select();
  document.execCommand("copy");
  area.remove();
}

export function toast(message) {
  const note = h("div", { class: "toast", role: "status" }, message);
  document.body.append(note);
  setTimeout(() => note.remove(), 3500);
}

// Put a popover next to whatever opened it, inside the window: below and
// right-aligned when there's room (the top bar), otherwise shifted or flipped
// above (the sidebar, the bottom of the screen).
export function placePopover(menu, anchor) {
  const box = anchor.getBoundingClientRect();
  const width = menu.offsetWidth;
  const height = menu.offsetHeight;
  const left = Math.min(Math.max(box.right - width, 8), window.innerWidth - width - 8);
  let top = box.bottom + 6;
  if (top + height > window.innerHeight - 8) top = Math.max(box.top - height - 6, 8);
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;
}

export function notice(iconName, title, ...lines) {
  return h(
    "div",
    { class: "notice" },
    icon(iconName),
    h("h2", null, title),
    lines.map((line) => (typeof line === "string" ? h("p", null, line) : line)),
  );
}
