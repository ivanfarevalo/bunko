// Formatting sizes, times, and names for display.

export function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = -1;
  do {
    value /= 1024;
    unit++;
  } while (value >= 1024 && unit < units.length - 1);
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`;
}

export function formatWhen(seconds) {
  const date = new Date(seconds * 1000);
  const age = (Date.now() - date) / 1000;
  if (age < 60) return "just now";
  if (age < 3600) return `${Math.floor(age / 60)} min ago`;
  if (age < 86400) return `${Math.floor(age / 3600)} hr ago`;
  if (age < 86400 * 7) return `${Math.floor(age / 86400)} d ago`;
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function formatClock(seconds) {
  const minutes = Math.floor(seconds / 60);
  const rest = (seconds - minutes * 60).toFixed(3).padStart(6, "0");
  return `${minutes}:${rest}`;
}

export function slugify(text) {
  return text
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s-]/gu, "")
    .replace(/\s+/g, "-");
}

// 0 -> A, 25 -> Z, 26 -> AA, as Excel names columns.
export function columnLetters(index) {
  let text = "";
  for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26)) text = String.fromCharCode(65 + ((n - 1) % 26)) + text;
  return text;
}
