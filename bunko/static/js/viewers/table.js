// CSV, TSV, JSONL, and Excel sheets as a virtualized table.

import { api, fetchRange } from "../api.js";
import { h, notice } from "../dom.js";
import { columnLetters, formatSize } from "../format.js";
import { icon } from "../icons.js";
import { CSV_CHUNK } from "../limits.js";
import { encodePath, extOf } from "../paths.js";
import { state } from "../state.js";
import { setSetting, settings } from "../store.js";
import { viewText } from "./text.js";

export const ROW_H = 31; // table row height including its border

// Parses delimited text in pieces, keeping a half-read record between feeds.
export class CsvParser {
  constructor(delimiter) {
    this.delimiter = delimiter;
    this.field = "";
    this.record = [];
    this.quoted = false;
    this.afterQuote = false;
    this.skipLf = false;
  }

  feed(text, rows) {
    const { delimiter } = this;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (this.skipLf) {
        this.skipLf = false;
        if (c === "\n") continue;
      }
      if (this.quoted) {
        if (c === '"') {
          this.quoted = false;
          this.afterQuote = true;
        } else {
          // Copy the run up to the next quote in one step: far faster than per char.
          const next = text.indexOf('"', i);
          const end = next === -1 ? text.length : next;
          this.field += text.slice(i, end);
          i = end - 1;
        }
      } else if (c === '"' && this.afterQuote) {
        this.field += '"'; // "" inside a quoted field
        this.quoted = true;
        this.afterQuote = false;
      } else if (c === '"' && this.field === "") {
        this.quoted = true;
      } else if (c === delimiter) {
        this.record.push(this.field);
        this.field = "";
        this.afterQuote = false;
      } else if (c === "\n" || c === "\r") {
        this.endRecord(rows);
        this.skipLf = c === "\r";
      } else {
        this.field += c;
        this.afterQuote = false;
      }
    }
  }

  endRecord(rows) {
    this.record.push(this.field);
    rows.push(this.record);
    this.record = [];
    this.field = "";
    this.afterQuote = false;
  }

  finish(rows) {
    if (this.field !== "" || this.record.length) this.endRecord(rows);
  }
}

export function sniffDelimiter(name, text) {
  if (extOf(name) === "tsv") return "\t";
  const line = text.slice(0, text.indexOf("\n") + 1 || 4096);
  let best = ",";
  let bestCount = 0;
  for (const candidate of [",", "\t", ";", "|"]) {
    const count = line.split(candidate).length - 1;
    if (count > bestCount) {
      best = candidate;
      bestCount = count;
    }
  }
  return best;
}

export const NUMERIC = /^\s*[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?%?\s*$/;

export function compareCells(a, b) {
  const x = a === undefined ? "" : a;
  const y = b === undefined ? "" : b;
  if (NUMERIC.test(x) && NUMERIC.test(y)) return parseFloat(x) - parseFloat(y);
  if (x === "") return y === "" ? 0 : 1; // blanks last
  if (y === "") return -1;
  return x < y ? -1 : x > y ? 1 : 0;
}

// One JSON object per line. Columns are the union of top-level keys, in order
// of first appearance; nested values show as compact JSON.
export class JsonlParser {
  constructor() {
    this.rest = "";
    this.columns = [];
    this.positions = new Map();
  }

  column(name) {
    if (!this.positions.has(name)) {
      this.positions.set(name, this.columns.length);
      this.columns.push(name);
    }
    return this.positions.get(name);
  }

  add(line, rows) {
    const trimmed = line.trim();
    if (!trimmed) return;
    const row = [];
    let value;
    try {
      value = JSON.parse(trimmed);
    } catch {
      row[this.column("(unparsed line)")] = trimmed;
      rows.push(row);
      return;
    }
    if (value && typeof value === "object" && !Array.isArray(value)) {
      for (const [key, cell] of Object.entries(value)) row[this.column(key)] = cellText(cell);
    } else {
      row[this.column("value")] = cellText(value);
    }
    rows.push(row);
  }

  feed(text, rows) {
    const lines = (this.rest + text).split("\n");
    this.rest = lines.pop();
    for (const line of lines) this.add(line, rows);
  }

  finish(rows) {
    this.add(this.rest, rows);
    this.rest = "";
  }
}

export const cellText = (value) =>
  value === null || value === undefined ? "" : typeof value === "object" ? JSON.stringify(value) : String(value);

// given: rows already in hand (an Excel sheet), instead of reading the file in pieces.
export async function viewTable(ctx, format, given) {
  const { path, stat } = ctx;
  const firstRow = given ? given.firstRow : 1; // the number shown beside the first row
  const decoder = new TextDecoder();
  const rows = [];
  let header = null;
  let parser = null;
  let offset = 0;
  let loading = false;
  let order = []; // indices into rows, after filter and sort
  let sort = null;
  let filter = (ctx.params.get("q") || "").toLowerCase();
  let firstDrawn = -1;
  let shownColumns = 0;

  const scroller = h("div", { class: "table-scroll" });
  const status = h("span", { class: "status" });
  const moreButton = h("button", { class: "btn", onclick: () => loadChunk() }, "Load more");
  const filterBox = h("input", {
    type: "search",
    value: ctx.params.get("q") || "",
    placeholder: "Filter rows",
    "aria-label": "Filter rows",
    oninput: (event) => {
      filter = event.target.value.toLowerCase();
      applyView();
    },
  });
  const bar = h("div", { class: "table-bar" }, filterBox, status, moreButton);
  const table = h("table", { class: "data" });
  const colgroup = h("colgroup");
  const headRow = h("tr");
  const body = h("tbody");
  table.append(colgroup, h("thead", null, headRow), body);
  scroller.append(table);

  async function loadChunk() {
    if (given && !header) {
      header = given.header;
      for (const row of given.rows) rows.push(row);
      offset = stat.size;
      if (rows.length || header.length) buildHeader();
      applyView();
      return;
    }
    if (loading || offset >= stat.size) return;
    loading = true;
    const bytes = await fetchRange(path, offset, CSV_CHUNK);
    if (!ctx.alive()) return;
    offset += bytes.length || stat.size;
    let text = decoder.decode(bytes, { stream: offset < stat.size });
    if (!parser) {
      if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
      parser = format === "jsonl" ? new JsonlParser() : new CsvParser(sniffDelimiter(path, text));
    }
    parser.feed(text, rows);
    if (offset >= stat.size) parser.finish(rows);
    if (format === "jsonl") {
      if (parser.columns.length !== shownColumns) {
        header = parser.columns;
        buildHeader();
      }
    } else if (!header && rows.length) {
      header = rows.shift();
      buildHeader();
    }
    loading = false;
    applyView();
  }

  function buildHeader() {
    const sample = rows.slice(0, 200);
    let columns = header.length;
    shownColumns = header.length;
    for (const row of sample) columns = Math.max(columns, row.length);
    const widths = [];
    const numeric = [];
    for (let column = 0; column < columns; column++) {
      let longest = (header[column] || "").length + 3;
      let numbers = 0;
      let filled = 0;
      for (const row of sample) {
        const cell = row[column] || "";
        if (cell) filled++;
        if (NUMERIC.test(cell)) numbers++;
        longest = Math.max(longest, cell.length);
      }
      numeric.push(filled > 0 && numbers / filled > 0.8);
      widths.push(Math.min(Math.max(longest * 7.4 + 22, 72), 340));
    }
    table.numeric = numeric;
    const lastRow = given ? firstRow + rows.length : Math.max(stat.size / 20, 1000) | 0;
    const gutter = String(Math.max(lastRow, 1000)).length * 8 + 22;
    colgroup.replaceChildren(
      h("col", { style: `width:${gutter}px` }),
      ...widths.map((width) => h("col", { style: `width:${width}px` })),
    );
    table.style.width = `${gutter + widths.reduce((sum, width) => sum + width, 0)}px`;
    headRow.replaceChildren(
      h("th", { class: "rn" }, "#"),
      ...widths.map((_, column) => {
        const letter = given ? columnLetters(given.firstColumn + column) : "";
        const name = header[column] || (given ? letter : `column ${column + 1}`);
        const title = given && name !== letter ? `${letter} · ${name}` : name;
        return h("th", { title, onclick: () => cycleSort(column) }, h("span", { class: "arrow" }), name);
      }),
    );
  }

  function cycleSort(column) {
    if (!sort || sort.column !== column) sort = { column, direction: 1 };
    else if (sort.direction === 1) sort.direction = -1;
    else sort = null;
    [...headRow.children].forEach((cell, index) => {
      const arrow = cell.querySelector(".arrow");
      if (arrow) arrow.textContent = sort && sort.column === index - 1 ? (sort.direction === 1 ? "↑" : "↓") : "";
    });
    applyView();
  }

  function applyView() {
    order = [];
    for (let index = 0; index < rows.length; index++) {
      if (!filter || rows[index].some((cell) => cell.toLowerCase().includes(filter))) order.push(index);
    }
    if (sort) {
      const { column, direction } = sort;
      order.sort((a, b) => direction * compareCells(rows[a][column], rows[b][column]) || a - b);
    }
    const complete = offset >= stat.size;
    const count = rows.length.toLocaleString();
    const columns = header ? `${Math.max(colgroup.children.length - 1, 0)} columns` : "";
    let text = filter ? `${order.length.toLocaleString()} of ${count} rows` : `${count} rows`;
    text += ` · ${columns}`;
    if (!complete) text += ` · loaded ${formatSize(offset)} of ${formatSize(stat.size)}`;
    if (!complete && (filter || sort)) text += ", so sort and filter see only what is loaded";
    if (given?.note) text += ` · ${given.note}`;
    status.textContent = text;
    moreButton.hidden = complete;
    firstDrawn = -1;
    draw();
  }

  function draw() {
    const height = scroller.clientHeight || 600;
    const first = Math.max(Math.floor(scroller.scrollTop / ROW_H) - 12, 0);
    if (first === firstDrawn) return;
    firstDrawn = first;
    const last = Math.min(first + Math.ceil(height / ROW_H) + 24, order.length);
    const columns = colgroup.children.length - 1;
    const trs = [h("tr", { class: "pad" }, h("td", { colSpan: columns + 1, style: `height:${first * ROW_H}px` }))];
    for (let at = first; at < last; at++) {
      const row = rows[order[at]];
      const cells = [h("td", { class: "rn" }, String(order[at] + firstRow))];
      for (let column = 0; column < columns; column++) {
        const value = row[column] === undefined ? "" : row[column];
        cells.push(
          h("td", { class: table.numeric[column] ? "num" : null, title: value.length > 30 ? value : null }, value),
        );
      }
      trs.push(h("tr", null, cells));
    }
    trs.push(
      h("tr", { class: "pad" }, h("td", { colSpan: columns + 1, style: `height:${(order.length - last) * ROW_H}px` })),
    );
    body.replaceChildren(...trs);
    // Near the end of what is loaded, fetch the next piece without being asked.
    if (last >= order.length - 40 && !filter && !sort && offset < stat.size) loadChunk();
  }

  scroller.addEventListener("scroll", () => requestAnimationFrame(draw));
  await loadChunk();
  if (!ctx.alive()) return;
  if (!header || (format === "jsonl" && !rows.length)) {
    ctx.el.append(notice("table", "This table is empty"));
    return;
  }
  ctx.fill();
  ctx.el.append(h("div", { class: "table-view" }, bar, scroller, given?.footer));
  ctx.mounted.push(() => {
    firstDrawn = -1;
    draw();
  });
}

export function viewJsonl(ctx) {
  // Off in Settings, or flipped here, JSONL shows as highlighted text.
  ctx.actions.push(
    h(
      "button",
      {
        class: "icon-btn",
        title: settings.jsonlTable ? "Show as text" : "Show as a table",
        "aria-label": settings.jsonlTable ? "Show as text" : "Show as a table",
        onclick: () => {
          setSetting("jsonlTable", !settings.jsonlTable);
          ctx.rerender({ keepScroll: true });
        },
      },
      icon(settings.jsonlTable ? "text" : "table"),
    ),
  );
  return settings.jsonlTable && !ctx.params.get("line") ? viewTable(ctx, "jsonl") : viewText(ctx);
}

export async function viewXlsx(ctx) {
  const asked = ctx.params.get("sheet");
  const data = await api("office", asked === null ? { path: ctx.path } : { path: ctx.path, sheet: asked });
  if (!ctx.alive()) return;
  // Hidden sheets stay out of the tabs, unless a link opened one.
  const tabs =
    data.sheets.length > 1
      ? h(
          "div",
          { class: "sheet-tabs", role: "tablist" },
          data.sheets.map((sheet, index) => {
            if (sheet.hidden && index !== data.sheet) return null;
            return h(
              "button",
              {
                class: `sheet-tab${index === data.sheet ? " on" : ""}`,
                role: "tab",
                "aria-selected": String(index === data.sheet),
                title: sheet.hidden ? `${sheet.name} (hidden in Excel)` : sheet.name,
                onclick: () => {
                  if (index === data.sheet) return;
                  const params = new URLSearchParams(ctx.params);
                  params.set("sheet", index);
                  params.delete("q");
                  history.replaceState(null, "", `#/${encodePath(ctx.path)}?${params}`);
                  state.stepping = true; // a different sheet of the same file isn't a new visit
                  ctx.rerender();
                },
              },
              sheet.name,
            );
          }),
        )
      : null;
  const hiddenCount = data.sheets.filter((sheet) => sheet.hidden).length;
  if (tabs && hiddenCount) tabs.append(h("span", { class: "sheet-note" }, `${hiddenCount} hidden`));

  if (!data.rows.length) {
    ctx.el.append(notice("table", "This sheet is empty"));
    if (tabs) ctx.el.append(tabs);
    return;
  }
  const notes = [];
  if (data.truncated) notes.push(`first ${(data.rows.length - 1).toLocaleString()} rows`);
  if (data.wide) notes.push("first 1,000 columns");
  await viewTable(ctx, "sheet", {
    header: data.rows[0],
    rows: data.rows.slice(1),
    firstRow: data.first_row + 1,
    firstColumn: data.first_col,
    note: notes.length ? `showing the ${notes.join(" and ")}` : "",
    footer: tabs,
  });
}
