// Showing, hiding, and resizing the sidebar.

import { $ } from "./dom.js";
import { store } from "./store.js";

export function closeDrawer() {
  document.body.classList.remove("side-open");
}

export function toggleSidebar() {
  if (matchMedia("(max-width: 760px)").matches) {
    document.body.classList.toggle("side-open");
    return;
  }
  const hidden = document.body.classList.toggle("side-hidden");
  store.set("sideHidden", hidden);
}

export function setupResize() {
  const handle = $("#resizer");
  const width = store.get("sideWidth", null);
  if (width) document.documentElement.style.setProperty("--side-w", `${width}px`);
  handle.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    handle.setPointerCapture(event.pointerId);
    document.body.classList.add("resizing");
    const move = (moved) => {
      const next = Math.min(Math.max(moved.clientX, 200), 560);
      document.documentElement.style.setProperty("--side-w", `${next}px`);
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
