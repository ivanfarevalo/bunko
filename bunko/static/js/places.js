// Recent files, favorites, and tags: the sidebar sections above the tree, and their menus.

import { API, api } from "./api.js";
import { $, h, placePopover, toast } from "./dom.js";
import { icon } from "./icons.js";
import { iconFor } from "./kinds.js";
import { appUrl, baseName, parentOf } from "./paths.js";
import { closeDrawer } from "./sidebar.js";
import { state } from "./state.js";
import { store } from "./store.js";

export const places = {
  data: { recent: [], favorites: [], tags: [], tagged: {} },
  collapsed: new Set(store.get("placesCollapsed", [])),
};

export const RECENT_SHOWN = 10;

export async function loadPlaces() {
  try {
    places.data = await api("places");
  } catch {
    /* no access yet: the sections stay empty */
  }
  renderPlaces();
  renderPlaceActions();
}

export async function changePlaces(change, { quiet = false } = {}) {
  let response;
  try {
    response = await fetch(`${API}places`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Bunko-Request": "1" },
      body: JSON.stringify(change),
    });
  } catch {
    if (!quiet) toast("Couldn't reach the server.");
    return false;
  }
  let data = {};
  try {
    data = await response.json();
  } catch {
    /* not JSON */
  }
  if (response.status === 401) {
    location.reload();
    return false;
  }
  if (!response.ok) {
    if (!quiet) toast(data.error || "Couldn't save that.");
    return false;
  }
  places.data = data;
  renderPlaces();
  renderPlaceActions();
  return true;
}

export const tagsOf = (path) => places.data.tagged[path] || [];

export function tagColor(name) {
  let hash = 0;
  for (const char of name.toLowerCase()) hash = (hash * 31 + char.codePointAt(0)) >>> 0;
  return `hsl(${hash % 360} 55% 52%)`;
}

export function tagDot(name) {
  return h("span", { class: "dot", style: `--tag:${tagColor(name)}` });
}

export const favoriteOf = (path) => places.data.favorites.find((item) => item.path === path);

export function closeStarMenu() {
  const menu = $("#starmenu");
  if (menu) menu.remove();
  document.removeEventListener("pointerdown", starMenuOutside, true);
}

export function starMenuOutside(event) {
  const menu = $("#starmenu");
  if (event.target.closest("#starmenu") || menu?.anchor?.contains(event.target)) return;
  if (menu?.save)
    menu.save(); // clicking away keeps what was typed
  else closeStarMenu();
}

// One box for a favorite's nickname, opened from the star in the top bar or
// from ✎ on the favorite in the sidebar. The star adds the favorite first.
export async function openStarMenu(anchor, path) {
  const open = $("#starmenu");
  if (open) {
    const same = open.anchor === anchor;
    closeStarMenu();
    if (same) return; // a second click on the same button closes it
  }
  const added = !favoriteOf(path);
  if (added && !(await changePlaces({ op: "favorite", path, on: true }))) return;
  const entry = favoriteOf(path) || {};
  const field = h("input", {
    type: "text",
    value: entry.name || "",
    placeholder: baseName(path),
    maxLength: 60,
    "aria-label": "Nickname",
  });
  let saving = false;
  async function save() {
    if (saving) return;
    saving = true;
    const name = field.value.trim();
    const current = favoriteOf(path)?.name || "";
    if (favoriteOf(path) && name !== current) await changePlaces({ op: "rename-favorite", path, name });
    closeStarMenu();
  }
  field.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      save();
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      closeStarMenu();
    }
  });
  const menu = h(
    "div",
    { id: "starmenu", class: "popover tagmenu", role: "dialog", "aria-label": "Favorite" },
    h("div", { class: "pop-title" }, added ? "Added to favorites" : "Favorite"),
    h("div", { class: "pop-path", title: path }, path),
    h("div", { class: "pop-label" }, "Nickname, optional"),
    field,
    h("div", { class: "hint" }, "Shown in Favorites in place of the file name."),
    h(
      "div",
      { class: "pop-actions" },
      h(
        "button",
        {
          class: "btn quiet",
          onclick: async () => {
            await changePlaces({ op: "favorite", path, on: false });
            closeStarMenu();
          },
        },
        "Remove",
      ),
      h("button", { class: "btn primary", onclick: save }, "Done"),
    ),
  );
  menu.save = save;
  menu.anchor = anchor;
  document.body.append(menu);
  placePopover(menu, anchor);
  field.focus();
  field.select();
  document.addEventListener("pointerdown", starMenuOutside, true);
}

export function renameFavorite(item, event) {
  openStarMenu(event.currentTarget, item.path);
}

export function renderPlaceActions() {
  const path = state.path;
  const star = $("#star-btn");
  if (star) {
    const entry = favoriteOf(path);
    const on = Boolean(entry);
    star.classList.toggle("on", on);
    star.title = on ? `Favorite${entry.name ? `: ${entry.name}` : ""} (click to rename or remove)` : "Add to favorites";
    star.setAttribute("aria-label", star.title);
    star.setAttribute("aria-pressed", on);
  }
  const chips = tagsOf(path).map((name) => h("span", { class: "chip", title: `Tagged ${name}` }, tagDot(name), name));
  $("#chips").replaceChildren(...chips);
}

export function toggleSection(key) {
  if (places.collapsed.has(key)) places.collapsed.delete(key);
  else places.collapsed.add(key);
  store.set("placesCollapsed", [...places.collapsed]);
  renderPlaces();
}

export function rowButton(action, item, glyph) {
  return h(
    "button",
    {
      class: "row-x",
      title: action.label,
      "aria-label": action.label,
      onclick: (event) => {
        event.preventDefault();
        event.stopPropagation();
        action.run(item, event);
      },
    },
    glyph,
  );
}

export function placeRow(item, remove, edit) {
  const name = baseName(item.path);
  // A nickname takes the main spot, so the right side shows the whole path.
  const shown = item.name || name;
  const where = item.name ? item.path : parentOf(item.path);
  return h(
    "a",
    {
      class: `row place-row${item.path === state.path ? " current" : ""}${item.missing ? " missing" : ""}`,
      href: appUrl(item.path),
      title: item.missing ? `${item.path} (not found)` : item.path,
      "data-path": item.path,
      onclick: () => {
        if (item.path !== state.path) state.fromSections = true;
        closeDrawer();
      },
    },
    icon(item.missing ? "alert" : iconFor({ name, dir: item.dir })),
    h("span", { class: `label${item.name ? " nick" : ""}` }, shown),
    where && h("span", { class: "where-inline" }, h("bdi", null, where)),
    (remove || edit) &&
      h("span", { class: "row-tools" }, edit && rowButton(edit, item, "✎"), remove && rowButton(remove, item, "×")),
  );
}

export function placeSection(key, title, items, { remove, edit, tools = [], limit } = {}) {
  if (!items.length) return null;
  const open = !places.collapsed.has(key);
  const head = h(
    "div",
    {
      class: "place-head",
      role: "button",
      tabindex: 0,
      "aria-expanded": String(open),
      "data-section": key,
      onclick: () => toggleSection(key),
      onkeydown: (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          toggleSection(key);
        }
      },
    },
    h("span", { class: `chev${open ? " open" : ""}` }, icon("chevron")),
    h("span", { class: "title" }, title),
    h("span", { class: "count" }, String(items.length)),
    tools.length
      ? h(
          "span",
          { class: "tools" },
          tools.map(([label, run]) =>
            h(
              "button",
              {
                onclick: (event) => {
                  event.stopPropagation();
                  run();
                },
              },
              label,
            ),
          ),
        )
      : null,
  );
  const shown = open ? (limit ? items.slice(0, limit) : items) : [];
  return h(
    "section",
    { class: "place" },
    head,
    shown.map((item) => placeRow(item, remove, edit)),
  );
}

export function renderPlaces() {
  const { recent, favorites, tags } = places.data;
  const sections = [
    placeSection("recent", "Recent", recent, {
      limit: RECENT_SHOWN,
      remove: { label: "Remove from recent", run: (item) => changePlaces({ op: "forget", path: item.path }) },
      tools: [["Clear", () => changePlaces({ op: "clear-recent" })]],
    }),
    placeSection("favorites", "Favorites", favorites, {
      remove: {
        label: "Remove from favorites",
        run: (item) => changePlaces({ op: "favorite", path: item.path, on: false }),
      },
      edit: { label: "Rename (nickname)", run: renameFavorite },
    }),
    ...tags.map((tag) =>
      placeSection(`tag:${tag.name}`, [tagDot(tag.name), h("span", null, tag.name)], tag.files, {
        remove: {
          label: `Remove the ${tag.name} tag`,
          run: (item) => changePlaces({ op: "untag", path: item.path, tag: tag.name }),
        },
        tools: [
          [
            "Rename",
            () => {
              const name = prompt(`Rename the tag "${tag.name}" to:`, tag.name);
              if (name?.trim() && name.trim() !== tag.name)
                changePlaces({ op: "rename-tag", tag: tag.name, name: name.trim() });
            },
          ],
          [
            "Delete",
            () => {
              if (confirm(`Delete the tag "${tag.name}"? The files stay; only the tag goes.`))
                changePlaces({ op: "delete-tag", tag: tag.name });
            },
          ],
        ],
      }),
    ),
  ].filter(Boolean);
  $("#places").replaceChildren(...sections);
  // With places above it, the tree gets its own collapsible heading.
  const filesHead = $("#files-head");
  filesHead.hidden = !sections.length;
  const filesOpen = !places.collapsed.has("files");
  filesHead.replaceChildren(
    h("span", { class: `chev${filesOpen ? " open" : ""}` }, icon("chevron")),
    h("span", { class: "title" }, "Files"),
  );
  filesHead.setAttribute("aria-expanded", filesOpen);
  $("#tree").hidden = sections.length > 0 && !filesOpen;
}

export function closeTagMenu() {
  const menu = $("#tagmenu");
  if (menu) menu.remove();
  document.removeEventListener("pointerdown", tagMenuOutside, true);
}

export function tagMenuOutside(event) {
  if (!event.target.closest("#tagmenu, #tag-btn")) closeTagMenu();
}

function markChoice(options, choice) {
  for (const [index, option] of [...options].entries()) option.classList.toggle("sel", index === choice);
}

export function openTagMenu(anchor, path) {
  if ($("#tagmenu")) return closeTagMenu();
  const field = h("input", { type: "text", placeholder: "Add a tag…", "aria-label": "Tag name", maxLength: 40 });
  const current = h("div", { class: "current" });
  const suggest = h("div", { class: "suggest", role: "listbox" });
  let choice = -1;

  async function add(name) {
    if (!name.trim()) return;
    if (await changePlaces({ op: "tag", path, tag: name.trim() })) {
      field.value = "";
      draw();
    }
  }

  function draw() {
    const mine = tagsOf(path);
    current.replaceChildren(
      ...mine.map((name) =>
        h(
          "span",
          { class: "chip" },
          tagDot(name),
          name,
          h(
            "button",
            {
              title: `Remove ${name}`,
              "aria-label": `Remove ${name}`,
              onclick: async () => {
                await changePlaces({ op: "untag", path, tag: name });
                draw();
              },
            },
            "×",
          ),
        ),
      ),
    );
    const typed = field.value.trim().toLowerCase();
    const others = places.data.tags
      .map((tag) => tag.name)
      .filter((name) => !mine.includes(name) && name.toLowerCase().includes(typed));
    const options = others.map((name) => h("button", { role: "option", onclick: () => add(name) }, tagDot(name), name));
    if (typed && !places.data.tags.some((tag) => tag.name.toLowerCase() === typed)) {
      options.push(
        h("button", { role: "option", onclick: () => add(field.value) }, "Create “", field.value.trim(), "”"),
      );
    }
    choice = Math.min(choice, options.length - 1);
    markChoice(options, choice);
    suggest.replaceChildren(...options);
  }

  field.addEventListener("input", () => {
    choice = -1;
    draw();
  });
  field.addEventListener("keydown", (event) => {
    const options = suggest.querySelectorAll("button");
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!options.length) return;
      choice = (choice + (event.key === "ArrowDown" ? 1 : -1) + options.length) % options.length;
      markChoice(options, choice);
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (choice >= 0 && options[choice]) options[choice].click();
      else add(field.value);
    } else if (event.key === "Escape") {
      closeTagMenu();
    }
  });

  const menu = h(
    "div",
    { id: "tagmenu", class: "popover tagmenu", role: "dialog", "aria-label": "Tags" },
    h("div", { class: "pop-title" }, "Tags"),
    current,
    field,
    suggest,
    h("div", { class: "hint" }, "Each tag gets its own section in the sidebar."),
  );
  document.body.append(menu);
  placePopover(menu, anchor);
  draw();
  field.focus();
  document.addEventListener("pointerdown", tagMenuOutside, true);
}
