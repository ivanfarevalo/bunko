// File kinds by extension, and the icon and highlighting language for each.

import { extOf } from "./paths.js";

export const KINDS = {};
for (const [kind, list] of Object.entries({
  image: "png jpg jpeg gif webp avif svg bmp ico",
  video: "mp4 webm mov m4v ogv mkv",
  audio: "mp3 wav ogg oga m4a flac aac opus",
  md: "md markdown mdown mkd",
  html: "html htm",
  csv: "csv tsv",
  pdf: "pdf",
  json: "json geojson",
  jsonl: "jsonl ndjson",
  docx: "docx docm dotx dotm",
  xlsx: "xlsx xlsm xltx xltm",
  binary: "doc xls xlsb ppt pptx",
}))
  for (const ext of list.split(" ")) KINDS[ext] = kind;

export const CODE_EXTS = new Set(
  "py js mjs ts tsx jsx c h cc cpp hpp cu rs go java rb sh bash zsh sql yaml yml toml ini cfg css scss xml lua r kt swift php pl proto cmake".split(
    " ",
  ),
);

export const kindOf = (name) => KINDS[extOf(name)] || "text";

export function iconFor(entry) {
  if (entry.dir) return "folder";
  const kind = kindOf(entry.name);
  if (kind === "md") return "text";
  if (kind === "html") return "globe";
  if (kind === "csv" || kind === "jsonl" || kind === "xlsx") return "table";
  if (kind === "docx") return "text";
  if (kind === "binary") return "file";
  if (kind === "json") return "code";
  if (kind !== "text") return kind;
  const ext = extOf(entry.name);
  if (CODE_EXTS.has(ext)) return "code";
  return ["txt", "log", ""].includes(ext) ? "text" : "file";
}

export function languageFor(name) {
  const lower = name.toLowerCase();
  if (lower === "cmakelists.txt") return "cmake";
  if (lower === "dockerfile") return "dockerfile";
  if (lower === "makefile") return "makefile";
  const aliases = {
    h: "cpp",
    hpp: "cpp",
    cu: "cpp",
    cc: "cpp",
    yml: "yaml",
    toml: "ini",
    cfg: "ini",
    jsonl: "json",
    ndjson: "json",
    svg: "xml",
  };
  const ext = extOf(name);
  const language = aliases[ext] || ext;
  return language && hljs.getLanguage(language) ? language : null;
}
