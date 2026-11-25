// Paths inside the served folder, and the URLs for them.

export const encodePath = (path) => path.split("/").map(encodeURIComponent).join("/");

export const rawUrl = (path) => `/${encodePath(path)}`;

// Paths are percent-encoded, so a literal "?" can only start the parameters:
// #/notes/plan.md?line=42&q=term or #/clips/a.mp4?t=12.5
export const appUrl = (path, params) => `#/${encodePath(path)}${params ? `?${new URLSearchParams(params)}` : ""}`;

export const baseName = (path) => path.split("/").pop();

export const parentOf = (path) => path.split("/").slice(0, -1).join("/");

export const join = (dir, name) => (dir ? `${dir}/${name}` : name);

export const extOf = (name) => (name.includes(".") ? name.split(".").pop().toLowerCase() : "");
