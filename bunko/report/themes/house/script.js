// Player frame: expand an embedded player in place into a large overlay, and drag its width while expanded.
// It must be inlined in <head> before any stylesheet link: an inline script after a stylesheet waits for it, so a slow
// font server would leave the buttons dead until it answered. It binds once the page is parsed. Standard DOM only.
// - The figure is restyled (class "expanded"), never moved: moving an iframe reloads it and the player loses its state.
// - Width: drag either side handle (the frame stays centered), arrow keys on a handle (Shift: bigger steps),
//   double-click a handle for the full width. The last width is remembered per browser; without storage it's the default.
(function () {
  function init() {
  var KEY = "houseStyle.playerFrameWidth";
  var backdrop = document.querySelector(".pf-backdrop");
  if (!backdrop) {
    backdrop = document.createElement("div");
    backdrop.className = "pf-backdrop";
    backdrop.setAttribute("aria-hidden", "true");
    document.body.appendChild(backdrop);
  }
  var open = null;

  function stored() {
    try { return parseInt(localStorage.getItem(KEY) || "", 10) || 0; } catch (e) { return 0; }
  }
  function store(w) {
    try { if (w) localStorage.setItem(KEY, String(Math.round(w))); else localStorage.removeItem(KEY); } catch (e) {}
  }
  function clamp(w) {
    var max = window.innerWidth * 0.98, min = Math.min(420, max);
    return Math.max(min, Math.min(max, w));
  }
  function readout(fig) {
    var r = fig.querySelector(".pf-width");
    if (r) r.textContent = Math.round(fig.getBoundingClientRect().width) + " px";
  }
  function setWidth(fig, w) {
    if (w) fig.style.setProperty("--pf-w", clamp(w) + "px"); else fig.style.removeProperty("--pf-w");
    readout(fig);
  }
  function label(fig, expanded) {
    var b = fig.querySelector("[data-pf=expand]");
    if (!b) return;
    b.setAttribute("aria-expanded", expanded ? "true" : "false");
    b.title = expanded ? "Shrink the player (Esc)" : "Expand the player";
    b.setAttribute("aria-label", b.title);
  }
  function setOpen(fig) {
    if (open) {
      open.classList.remove("expanded");
      open.style.removeProperty("--pf-w");
      label(open, false);
    }
    open = fig;
    if (fig) {
      fig.classList.add("expanded");
      setWidth(fig, stored());
      label(fig, true);
      var b = fig.querySelector("[data-pf=expand]");
      if (b) b.focus();
    }
    backdrop.classList.toggle("on", !!fig);
    document.body.classList.toggle("pf-open", !!fig);
  }

  document.querySelectorAll("figure.player").forEach(function (fig) {
    var btn = fig.querySelector("[data-pf=expand]");
    if (btn) btn.addEventListener("click", function () { setOpen(open === fig ? null : fig); });
    fig.querySelectorAll(".pf-handle").forEach(function (h) {
      var left = h.classList.contains("l");
      h.addEventListener("pointerdown", function (e) {
        e.preventDefault();
        h.setPointerCapture(e.pointerId);
        fig.classList.add("dragging");
        document.body.classList.add("pf-dragging");
      });
      h.addEventListener("pointermove", function (e) {
        if (!h.hasPointerCapture(e.pointerId)) return;
        // Centred frame: its width is twice the pointer's distance from the window's centre line.
        setWidth(fig, 2 * Math.abs(e.clientX - window.innerWidth / 2));
      });
      function end(e) {
        if (!h.hasPointerCapture(e.pointerId)) return;
        h.releasePointerCapture(e.pointerId);
        fig.classList.remove("dragging");
        document.body.classList.remove("pf-dragging");
        store(fig.getBoundingClientRect().width);
      }
      h.addEventListener("pointerup", end);
      h.addEventListener("pointercancel", end);
      h.addEventListener("dblclick", function () { setWidth(fig, 0); store(0); });
      h.addEventListener("keydown", function (e) {
        if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
        e.preventDefault();
        var step = e.shiftKey ? 160 : 40;
        var wider = (e.key === "ArrowRight") !== left;
        var w = fig.getBoundingClientRect().width + (wider ? step : -step);
        setWidth(fig, w);
        store(fig.getBoundingClientRect().width);
      });
    });
  });
  backdrop.addEventListener("click", function () { setOpen(null); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && open) setOpen(null); });
  window.addEventListener("resize", function () { if (open) setWidth(open, stored()); });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
