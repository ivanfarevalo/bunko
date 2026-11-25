// Preferences kept in the browser's local storage.

export const store = {
  get(key, fallback) {
    try {
      const value = localStorage.getItem(`shelf.${key}`);
      return value === null ? fallback : JSON.parse(value);
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(`shelf.${key}`, JSON.stringify(value));
    } catch {
      /* private mode */
    }
  },
};

// Viewer preferences, kept per browser. Every one has an off switch in Settings.
export const DEFAULT_SETTINGS = { toc: true, jsonlTable: true, thumbnails: true, liveReload: true };

export const settings = Object.assign({}, DEFAULT_SETTINGS, store.get("settings", {}));

export function setSetting(key, value) {
  settings[key] = value;
  store.set("settings", settings);
}
