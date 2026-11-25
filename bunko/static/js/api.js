// Requests to the server's API and raw files.

import { rawUrl } from "./paths.js";

export const API = "/__bunko/api/";

export async function api(name, params) {
  const response = await fetch(`${API + name}?${new URLSearchParams(params || {})}`);
  let data = {};
  try {
    data = await response.json();
  } catch {
    /* not JSON */
  }
  if (response.status === 401 || (response.status === 403 && ["no-identity", "not-allowed"].includes(data.error))) {
    location.reload(); // the server answers a page load with its sign-in page
  }
  if (!response.ok) throw Object.assign(new Error(data.error || "request failed"), { status: response.status });
  return data;
}

export async function fetchRange(path, start, length) {
  const response = await fetch(rawUrl(path), { headers: { Range: `bytes=${start}-${start + length - 1}` } });
  if (response.status === 416) return new Uint8Array(0);
  if (!response.ok) throw new Error("could not read file");
  return new Uint8Array(await response.arrayBuffer());
}
