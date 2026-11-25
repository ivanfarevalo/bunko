// What is open right now, shared across modules.

import { $ } from "./dom.js";

export const state = {
  config: null,
  path: "",
  stat: null,
  watch: "", // the file whose changes refresh the view
  kind: null,
  reload: null, // a viewer's own in-place refresh, if it has one
  token: 0, // bumped per navigation so stale async work can stand down
  cleanup: [],
};

export const view = $("#view");
