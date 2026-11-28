# Design: reports (`/report` and `bunko report`)

Status: agreed 2026-11-28; phase 1 built the same day (see docs/reports.md). Phases are at the end. Change this page
when a decision changes, and say why.

## What it's for

Typing `/report` in an agent session (Claude Code, Codex, or any agent that reads
skill files) writes up the work at hand as an HTML report, in a consistent style,
in the right place. Then you get the Bunko link to read it. The link comes early,
so you can watch the report fill in through live reload.

It formalizes a practice that already works by hand: reports written from
instructions in `CLAUDE.md`, a shared stylesheet, and a fixed folder layout. What
it adds:

- **Consistency:** no rebuilding the page from scratch each session.
- **One trigger:** `/report` instead of explaining what you want each time.
- **Portability:** your conventions become settings anyone can change, and
  other agents can use them.
- **A dependable last step:** the link.

## Principles

1. **The agent writes; the tool does the mechanics.** Content, structure, and
   narrative are the agent's job. Where a report goes, its template and
   theme, the folder layout, naming, validation, and the link are done by
   `bunko report` commands, which behave the same every time.
2. **Configurable by conversation, by command, or by hand.** Any setting can be
   changed by asking the agent, by running `bunko report …` yourself, or by
   editing the config file. All three write the same file, so a change
   survives restarts and carries over to every agent. Nothing lives only in an
   agent's context. The skill tells agents to use the commands.
3. **No server required.** Reports are plain HTML files that open straight
   from disk. Bunko adds the link and a way to browse them, but making a
   report doesn't depend on a running server.
4. **Generic at the core, specific in your config.** Nothing in the core knows
   about any one project. Project-specific pieces, such as an embedded video
   player that finds media on the reader's disk, come in through the user's own
   kinds, themes, and builder scripts.

## Concepts

| Term | Meaning |
|---|---|
| **Kind** | A type of report: results, write-up, explainer, or one you add. |
| **Workspace** | The folder for one piece of work (an experiment, a project, a topic). Reports live inside it. |
| **Layout** | How a workspace is laid out: its folder name pattern, subfolders, and where each kind of report goes. |
| **Theme** | How reports look: `template.html`, `style.css`, and optional components. |
| **Root** | Where new workspaces are created. |

"Workspace" here is a report concept. Serving several folders from one Bunko
server is a separate question, covered under [Related](#related-several-folders-in-one-server).

## Configuration

Two levels, as with Git: per user and per project.

- **User:** `~/.config/bunko/report.json`
- **Project:** `.bunko/report.json`, found by walking up from the working folder.
  It overrides the user settings, so a shared repository can carry its own
  kinds and layout.
- **Format:** JSON. Bunko's standard-library rule and its support for Python 3.8 rule out
  TOML (`tomllib` arrived in 3.11). The commands also need to write the
  file, and the standard library can't write TOML or keep its comments. JSON
  covers both, and agents handle it reliably.
- **First run:** `/report` with no config makes the agent propose a root, a
  layout, and a theme, as a question you can accept or adjust. It then saves
  them with `bunko report init`.

### Kinds

A starting definition, to iterate on:

| Field | Purpose |
|---|---|
| `name`, `description` | The agent picks a kind by its description |
| `guidance` | Free text for the agent: tone, length, "interactive charts", "one page" |
| `sections` | Optional starting outline |
| `file` | Naming pattern; default `{slug}.html`, from the title |
| `place` | Where in the workspace it goes (for example `report/`, `notes/`) |
| `builder` | Whether it gets a builder script, so data reports can be rebuilt |
| `theme` | Optional; overrides the default theme |

`guidance` keeps kinds expressive without growing the schema: a very interactive
kind and a terse one differ mostly in what they ask of the agent.

The starter set is **results**, **write-up**, and **explainer**. The agent
picks the kind. When it's unsure, or nothing fits, it asks, offering the likely
kinds plus "something else". A new kind is saved with `bunko report kind add`.

### Layouts

- **`simple`**, the default: `{root}/{slug}/`, reports inside.
- **`experiment`**, a preset: `{root}/{date}_{slug}/` with `src/`, `configs/`,
  `data/`, `runs/`, `results/`, `report/`, and `notes/`.
- Any layout you describe to your agent, saved as your own.

The defaults should stay loose. Revisit them after real use.

### Themes

- Built in: **house**, the default, with the player frame as a component.
- Your own: in `~/.config/bunko/themes/<name>/`, or `.bunko/themes/` in a
  project. `bunko report theme new NAME --from house` starts one from an
  existing theme.
- The theme's CSS is inlined into each report, so reports open from disk and
  travel as one file.
- Semantic colors get general names (`--good`, `--info`, `--warn`, `--bad`,
  `--neutral`), keeping the old ones (`--fg-c`, `--bg-c`, `--fade-c`, `--abs-c`)
  as aliases.

## Commands

| Command | Does |
|---|---|
| `bunko report init` | First-run setup; asks nothing itself, the agent asks you |
| `bunko report config show\|set` | Read or change settings, at user or project level |
| `bunko report kind list\|add\|edit\|remove` | Manage kinds |
| `bunko report layout list\|add\|edit\|use` | Manage layouts |
| `bunko report theme list\|new\|use` | Manage themes |
| `bunko report new KIND "Title"` | Find or create the workspace and the report file, and print the paths and the Bunko link as JSON |
| `bunko report list [WORKSPACE]` | Existing reports, so the agent updates rather than duplicates |
| `bunko report check FILE` | Validate: contents entries, anchors, missing files, server-only dependencies, leaked absolute paths |
| `bunko report bundle FILE` | One self-contained HTML file to send to someone |

All of them print JSON with `--json`, for agents.

## Reports

- **Named for what they are:** `speed-vs-accuracy.html`, not a fixed
  `RESULTS.html`. A workspace can hold many reports.
- **Updated, not duplicated:** the agent lists the workspace's reports first
  and asks when it's unclear whether to update or create.
- **Provenance:** a collapsed "How this was made" panel at the end, with the
  date, the inputs, commits, and the rebuild command. It's closed by default, so it
  doesn't lengthen the report.
- **Findable:** each report carries `<meta>` tags (kind, title, date,
  workspace). Bunko reads them for a Reports section in the sidebar, an
  experiment to evaluate once built.

## Sharing

**Core:** `bunko report bundle` makes one HTML file that opens anywhere. Local
images, styles, and scripts are inlined, and the bundle reports anything it
couldn't include, such as large videos.

**Project-specific, not core:** reports for the overlay video player play
videos from the reader's own copy of the media. That logic belongs in the
player, which is moving there: a control to choose the media folder (a folder
picker where the browser supports it, a typed path otherwise), and a prompt
when a video can't be found. A report embeds the player through the player's
own functions (`embed.assets()` and `embed.block()`) from its builder script.
Bunko only has to keep inlined components intact.

## Skill and plugin

One `SKILL.md` source, two ways to get it:

1. **`bunko skill install`**, first. It writes the skill for Claude Code
   (`~/.claude/skills/report/`) and an equivalent prompt for Codex. It works for
   any agent.
2. **A Claude Code plugin**, later. The same skill, installed in one step from
   the marketplace, with `/bunko` commands, and hooks where they help (for
   example, making sure a server is running).

The Bunko command-line tool does the work in both cases.

## Phases

1. **Core** (built 2026-11-28)
   - The config store, at user and project level, with `init`, `config`,
     `kind`, `layout`, and `theme`.
   - The house theme as the built-in default.
   - `new`, `list`, and `check`.
   - Descriptive names, and updating instead of duplicating.
   - The provenance panel.
   - The skill, and `bunko skill install`.
   - The link at the end.
2. **Sharing and finding:** `bundle`, the meta tags, and the Reports sidebar
   section.
3. **Distribution:** the Claude Code plugin, and a helper library for builder
   scripts if they keep repeating code.

## Related: several folders in one server

Today one Bunko process serves one folder. To see work spread across disks:

- **Now:** symlinks inside the served folder (Bunko follows them, with the
  dotfile rule still applied), or several servers, which `bunko servers` and
  `bunko link` already handle.
- **Possible later:** one server with several named roots, each a top-level
  entry in the sidebar. It's a server feature, independent of reports. It's on
  the roadmap for discussion.

## Open questions

- Is the kind definition right? Revisit after the first few real reports.
- Should the default `simple` layout be looser still, or offer more presets?
