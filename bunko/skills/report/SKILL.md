---
name: report
description: Write up the current work as an HTML report, in the user's configured style and folder layout, and give them the Bunko link. Use when the user types /report, or asks for a report, write-up, or explainer of what you've been working on.
---

# Write a report

The `bunko report` commands handle where a report goes, how it looks, and
checking it. You write the content. Every command prints JSON.

## 1. Settings

Run `bunko report config show`.

- If `configured` is false, this is the first run. Propose a root folder for
  reports, a layout (`bunko report layout list`), and a theme
  (`bunko report theme list`). If `bunko servers` lists a running server,
  prefer a root inside the folder it serves, so reports get a link. Ask the
  user to confirm or adjust in one question, then save with
  `bunko report init --root … --layout … --theme …`.
- **Keep every settings change in Bunko, never only in this conversation.**
  When the user asks for a change ("put write-ups in notes/", "add a kind for
  weekly updates", "use my theme"), confirm it, then save it with
  `bunko report kind|layout|theme|config …`. Add `--project` when the change
  belongs to the current project rather than to the user.

## 2. Kind

Run `bunko report kind list` and pick the kind whose description fits the
work. If none fits, or you're unsure, ask the user, offering the likely kinds
plus "something else". For something new, agree on a name, a description,
guidance, and sections, then add it with `bunko report kind add …`.

## 3. Workspace and file

Decide which workspace the report belongs to. If the working folder is inside
the root, it's that one. Otherwise, check `bunko report list NAME` for an
existing one, and ask when it's unclear. Then run:

    bunko report new KIND "Title" [--workspace NAME]

It finds or creates the workspace and the report file, and never overwrites
one. Read its output:

- `link`: give it to the user now. Bunko reloads the page as you write, so
  they can watch it fill in. If it's null, no running Bunko serves the folder.
- `existed: true`: a report with this title is already there. Update it, and
  read it first. Don't create a second one.
- `guidance`: follow it.
- `builder`: if set, this kind is built from data. Write the content in the
  builder script (it reads results and makes the tables and figures), then run
  it with `python3 BUILDER`. Never edit that report's HTML by hand: the next
  build replaces it.

## 4. Write

- Replace the placeholders. Keep the page's structure: a `<section id=…>` with
  an `<h2>` for each part. `bunko report check --fix` rebuilds the contents
  list from the sections.
- Use the building blocks the theme's stylesheet defines. In the house theme:
  `.takeaway`, `.analogy`, `table.data` inside `.scroll`, `figure` with
  `figcaption`, and `figure.player` for embedded players.
- Put images and other files next to the report (for example in `img/`), and
  link to them with relative paths, so the report opens from disk.
- Keep "How this was made" at the end current: sources, commands, commits.
  Set `<meta name="bunko:updated">` to today's date when you update a report.
- Write for a reader who wasn't in this conversation: lead with the answer,
  and say what the numbers mean.

## 5. Check

Run `bunko report check --fix FILE` and fix every error. Read the warnings;
fix the ones that matter. Run it again until there are no errors.

## 6. Finish

Run `bunko link FILE` and give the user the URL. If no server serves the
report, give the file path, and the command to start one: `bunko ROOT`.
