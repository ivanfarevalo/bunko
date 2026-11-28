# Reports

Bunko can make HTML reports as well as show them: pages in a consistent theme,
saved in a predictable place, that open straight from disk and travel as one
file. AI agents use this through the `/report` skill. Everything also works by
hand with `bunko report`.

- [With an agent: /report](#with-an-agent-report)
- [Settings](#settings)
- [Kinds](#kinds)
- [Workspaces and layouts](#workspaces-and-layouts)
- [Themes](#themes)
- [Commands](#commands)
- [Reports built from data](#reports-built-from-data)

## With an agent: /report

Install the skill once:

```bash
bunko skill install          # Claude Code (~/.claude/skills) and Codex (~/.codex/prompts)
```

Then, in an agent session, type `/report`, or ask for a write-up. The agent
does the following:

1. **Checks your settings.** The first time, it proposes where reports go,
   which layout, and which theme, and saves your answers.
2. **Picks a kind of report:** results, write-up, explainer, or one of yours.
   If none fits, it asks, and can add a new kind for you.
3. **Finds or creates the workspace and the file.** If a report with that
   title exists, it updates that one rather than making a second.
4. **Gives you the Bunko link right away,** so you can watch the report fill
   in.
5. **Writes it, checks it with `bunko report check`, and fixes what the check
   finds.**

You can change any setting by asking: "put write-ups in notes/", "add a kind
for weekly status updates", "use my theme". The agent saves the change with
the commands below, so it applies to every later session and every agent.

## Settings

Settings come in two levels, as with Git:

| File | Scope |
|---|---|
| `~/.config/bunko/report.json` | You, everywhere |
| `.bunko/report.json` in a project or any parent folder | That project, for everyone who has it. Overrides your settings. |

| Setting | Default | Meaning |
|---|---|---|
| `root` | `~/reports` | Where new workspaces are created. In a project file, a relative path is relative to the project. |
| `layout` | `simple` | How new workspaces are laid out |
| `theme` | `house` | How reports look |
| `kinds` | results, write-up, explainer | Types of report, merged by name across the levels |
| `layouts` | simple, experiment | Workspace layouts, merged by name |

Change them with the commands (add `--project` for the project level), or edit
the JSON. A project can remove a kind by setting it to `null`.

## Kinds

A kind is a type of report, defined by:

| Field | Purpose |
|---|---|
| `description` | One line. The agent picks kinds by it. |
| `guidance` | Free text for the agent: tone, length, interactivity, what to lead with |
| `sections` | The outline a new report starts with |
| `file` | File name pattern, with `{slug}`, `{date}`, and `{kind}`. Default `{slug}.html`, from the title. |
| `place` | The folder inside the workspace. Default: the layout decides. |
| `builder` | Whether the report is built from data by a script. See [below](#reports-built-from-data). |
| `theme` | A theme for this kind only |

```bash
bunko report kind add status --description "Weekly status for a manager" \
  --guidance "One page, plain language" --sections "Done,Next,Risks" --place notes
```

## Workspaces and layouts

A workspace is the folder for one piece of work: an experiment, a project, a
client, a topic. A layout says how workspaces are named and arranged:

| Layout | Folder | Inside |
|---|---|---|
| `simple` | `{slug}` | The reports |
| `experiment` | `{date}_{slug}` | `src/`, `configs/`, `data/`, `runs/`, `results/`, `report/`, `notes/`. Results reports go at the top, write-ups in `notes/`, the rest in `report/`. |

`bunko report new` uses the workspace you're in when the working folder is
inside the root. Otherwise you name one with `--workspace`. An existing folder
whose name ends with the name's slug is reused, so `gate tuning` finds
`20261128_gate-tuning`. A path works too.

```bash
bunko report layout add client --folder "{slug}" --subdirs "deliverables,notes" --place "*=deliverables"
bunko report layout use client
```

## Themes

A theme is a folder of plain files:

| File | Holds |
|---|---|
| `template.html` | The page, with `{{title}}`, `{{kicker}}`, `{{summary}}`, `{{contents}}`, `{{sections}}`, `{{provenance}}`, `{{meta}}`, `{{style}}`, `{{script}}` |
| `section.html`, `contents-item.html`, `provenance.html` | The repeated pieces |
| `style.css` | Inlined into each report |
| `script.js` | Optional; inlined |

The built-in **house** theme has a side table of contents, light and dark
modes, and building blocks for reports:
- `.takeaway` and `.analogy` boxes;
- `table.data` inside `.scroll` for wide tables;
- figures and charts;
- `figure.player`, an embedded player that expands into a large overlay with
  an adjustable width.

Its semantic colors are `--good`, `--info`, `--warn`, `--bad`, and `--neutral`.

```bash
bunko report theme new mine          # copy the house theme into ~/.config/bunko/themes/mine
bunko report theme use mine
```

A theme can leave out any file and use the house theme's instead. Themes are
found in the project's `.bunko/themes/`, then `~/.config/bunko/themes/`, then
the built-in ones.

## Commands

Every command prints JSON.

| Command | Does |
|---|---|
| `bunko report init [--root R] [--layout L] [--theme T]` | First-time setup |
| `bunko report config show` / `config set KEY VALUE` | Read or change `root`, `layout`, `theme` |
| `bunko report kind list\|add\|edit\|remove` | Manage kinds |
| `bunko report layout list\|add\|edit\|remove\|use` | Manage layouts |
| `bunko report theme list\|new\|use` | Manage themes |
| `bunko report new KIND "Title" [--workspace W]` | Find or create the workspace and report, never overwriting one. Prints the paths, the kind's guidance, and the Bunko link. |
| `bunko report list [WORKSPACE]` | The reports in a workspace, newest first |
| `bunko report check [--fix] FILE` | Check the contents, links, and paths; `--fix` rebuilds the contents list. Exits 1 on errors. |
| `bunko report render SPEC -o FILE` | Render a page from a JSON spec, for builder scripts |

Every report carries `<meta name="bunko:…">` tags (kind, workspace, created,
updated), which `list` reads. It also has a collapsed "How this was made"
panel at the end.

## Reports built from data

Kinds with `builder` set, such as results, get a script next to the report
(`report/build_<name>.py` in the experiment layout). The script reads your
results, makes the tables and figures, and renders the page through
`bunko report render`, so the report can be rebuilt whenever the data changes:

```bash
python3 report/build_speed_vs_accuracy.py
```

For these reports, edit the script, not the HTML. The next build replaces the
page.
