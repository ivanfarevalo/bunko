// Images, video with review tools, and audio.

import { api } from "../api.js";
import { $, copyText, h, notice } from "../dom.js";
import { formatClock, formatSize } from "../format.js";
import { icon } from "../icons.js";
import { appUrl, baseName, rawUrl } from "../paths.js";
import { state } from "../state.js";
import { siblings } from "../tree.js";
import { downloadButton } from "./text.js";

export async function addStepper(ctx, kinds) {
  const list = await siblings(ctx.path, kinds);
  const at = list.indexOf(ctx.path);
  if (list.length < 2 || at < 0) return;
  const go = (step) => {
    state.stepping = true;
    location.hash = appUrl(list[(at + step + list.length) % list.length]);
  };
  ctx.step = go;
  ctx.el.append(
    h(
      "button",
      { class: "nav-btn prev", title: "Previous (←)", "aria-label": "Previous", onclick: () => go(-1) },
      icon("left"),
    ),
    h(
      "button",
      { class: "nav-btn next", title: "Next (→)", "aria-label": "Next", onclick: () => go(1) },
      icon("chevron"),
    ),
  );
  state.stepMeta = `${at + 1} of ${list.length}`;
}

export async function viewImage(ctx) {
  const image = h("img", { src: `${rawUrl(ctx.path)}?v=${ctx.stat.mtime}`, alt: baseName(ctx.path) });
  const stage = h("div", { class: "stage" }, image);
  image.addEventListener("click", () => stage.classList.toggle("zoomed"));
  image.addEventListener("load", () => {
    if (!ctx.alive() || !image.naturalWidth) return;
    $("#meta").textContent = [
      state.stepMeta,
      `${image.naturalWidth} × ${image.naturalHeight}`,
      formatSize(ctx.stat.size),
    ]
      .filter(Boolean)
      .join(" · ");
  });
  image.addEventListener("error", () => {
    if (ctx.alive())
      stage.replaceChildren(
        notice(
          "alert",
          "This image could not be decoded",
          "The browser does not support its format.",
          downloadButton(ctx.path),
        ),
      );
  });
  ctx.fill();
  ctx.el.append(stage);
  await addStepper(ctx, ["image"]);
}

export const SPEEDS = [0.1, 0.25, 0.5, 1, 1.5, 2, 4];

export async function viewVideo(ctx) {
  const video = h("video", { src: rawUrl(ctx.path), controls: true, preload: "metadata", playsInline: true });
  const stage = h("div", { class: "stage video-stage" }, video);
  let facts = null;
  let fps = null;
  let estimated = false;

  const clock = h("span", { class: "vt-clock" }, "0:00.000");
  const frameLabel = h("span", { class: "vt-frame" });
  const playButton = h(
    "button",
    {
      class: "vt-btn",
      title: "Play / pause (Space or K)",
      "aria-label": "Play or pause",
      onclick: () => controls.toggle(),
    },
    icon("play"),
  );
  const speed = h(
    "select",
    {
      class: "vt-speed",
      "aria-label": "Playback speed",
      title: "Speed ([ and ])",
      onchange: () => {
        video.playbackRate = Number(speed.value);
      },
    },
    SPEEDS.map((rate) => h("option", { value: rate, selected: rate === 1 }, `${rate}×`)),
  );
  const linkButton = h(
    "button",
    { class: "vt-btn wide", title: "Copy a link to this moment (T)", onclick: () => controls.copyLink() },
    icon("link"),
    h("span", null, "Link"),
  );
  const button = (label, title, run) => h("button", { class: "vt-btn", title, onclick: run }, label);
  const bar = h(
    "div",
    { class: "vtools" },
    button("−1s", "Back 1 second (J, Shift+J for 5)", () => controls.seek(-1)),
    button("−1f", "Previous frame (,)", () => controls.step(-1)),
    playButton,
    button("+1f", "Next frame (.)", () => controls.step(1)),
    button("+1s", "Forward 1 second (L, Shift+L for 5)", () => controls.seek(1)),
    clock,
    frameLabel,
    h("span", { class: "vt-gap" }),
    speed,
    linkButton,
  );

  const frameOf = (time) => Math.floor(time * fps + 1e-6);

  function update() {
    clock.textContent = formatClock(video.currentTime || 0);
    if (fps) {
      const total = facts?.frames ? ` / ${facts.frames - 1}` : "";
      frameLabel.textContent = `frame ${frameOf(video.currentTime)}${total} · ${estimated ? "≈" : ""}${Math.round(fps * 100) / 100} fps`;
    }
    playButton.replaceChildren(icon(video.paused ? "play" : "pause"));
  }

  const controls = {
    toggle: () => (video.paused ? video.play() : video.pause()),
    step(count) {
      if (!fps) return;
      video.pause();
      const target = (frameOf(video.currentTime) + count + 0.5) / fps; // mid-frame lands reliably
      video.currentTime = Math.min(Math.max(target, 0), Math.max((video.duration || target) - 0.5 / fps, 0));
    },
    seek(seconds) {
      video.currentTime = Math.min(Math.max(video.currentTime + seconds, 0), video.duration || Infinity);
    },
    rate(direction) {
      const at = SPEEDS.indexOf(video.playbackRate);
      const next = SPEEDS[Math.min(Math.max((at < 0 ? 3 : at) + direction, 0), SPEEDS.length - 1)];
      video.playbackRate = next;
      speed.value = String(next);
    },
    async copyLink() {
      const link = `${location.origin}/${appUrl(ctx.path, { t: video.currentTime.toFixed(3) })}`;
      await copyText(link);
      linkButton.lastChild.textContent = "Copied";
      setTimeout(() => {
        linkButton.lastChild.textContent = "Link";
      }, 1500);
    },
  };

  for (const name of ["timeupdate", "seeked", "play", "pause", "loadedmetadata"]) video.addEventListener(name, update);
  const start = Number(ctx.params.get("t"));
  if (start > 0)
    video.addEventListener(
      "loadedmetadata",
      () => {
        video.currentTime = start;
      },
      { once: true },
    );

  // Without ffprobe, measure the frame rate from frames the browser presents.
  function estimate() {
    if (fps || !video.requestVideoFrameCallback) return;
    const times = [];
    const tick = (_now, meta) => {
      if (!ctx.alive() || fps) return;
      times.push(meta.mediaTime);
      if (times.length < 12) return video.requestVideoFrameCallback(tick);
      const gaps = times
        .slice(1)
        .map((time, index) => time - times[index])
        .filter((gap) => gap > 0)
        .sort((a, b) => a - b);
      if (gaps.length) {
        fps = 1 / gaps[Math.floor(gaps.length / 2)];
        estimated = true;
        update();
      }
    };
    video.requestVideoFrameCallback(tick);
  }
  video.addEventListener("play", estimate);

  video.addEventListener("error", () => {
    if (!ctx.alive()) return;
    const codec = facts?.codec ? ` It is encoded as ${facts.codec.toUpperCase()}.` : "";
    stage.replaceChildren(
      notice(
        "alert",
        "The browser cannot play this video",
        `Its codec is probably unsupported.${codec} H.265 and most .mkv or .avi files need a download.`,
        downloadButton(ctx.path),
      ),
    );
    bar.remove();
  });
  ctx.cleanup.push(() => {
    video.pause();
    video.removeAttribute("src");
    video.load();
    state.video = null;
  });
  state.video = controls;
  ctx.fill();
  ctx.el.append(h("div", { class: "video-view" }, stage, bar));

  if (state.config.features.probe) {
    facts = await api("probe", { path: ctx.path }).catch(() => null);
    if (!ctx.alive()) return;
    if (facts?.fps) fps = facts.fps;
    update();
  }
  await addStepper(ctx, ["video"]);
}

export function viewAudio(ctx) {
  ctx.fill();
  ctx.el.append(h("div", { class: "stage" }, h("audio", { src: rawUrl(ctx.path), controls: true })));
}
