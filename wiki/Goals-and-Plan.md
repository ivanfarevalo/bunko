# Goals and plan

## The goal

**A private reading room for a folder: everything in it rendered, searchable,
and eventually answerable.** You point Bunko at files that already exist, on
your machine or a shared server, and you can read them, find things in them,
and ask questions about them, without uploading anything anywhere.

Two things set it apart from the "chat with your documents" tools:

- **Works in place.** No ingestion step, no sync, no database. The folder is
  the source of truth, and Bunko follows it live.
- **Answers you can check.** Because Bunko already renders every file well,
  an AI answer can link to the exact line, table row, or moment in a video,
  and that source opens right beside the answer.

## The plan, in stages

| Stage | Focus | State |
|---|---|---|
| 1. A better `http.server` | Render the common file types well, with search and a folder tree | Done (0.1) |
| 2. Safe to share | Access control, video review tools, thumbnails, content search, a service mode | Done (0.2) |
| 3. A place to work from | Recent files, favorites, tags, Word and Excel | Done (0.3) |
| 4. A maintained project | Its own repository, tooling, documentation, wiki, and a code review pass | In progress |
| 5. A companion for AI agents | Links agents can print, a "changed recently" view, Word and Excel in search | Next |
| 6. Ask your files | Questions answered from the folder, with citations, by Claude, OpenAI, or a local model | Planned |
| 7. Team use | Per-folder permissions, simpler sign-in, Office formats in more depth | Later |

[Phases](Phases.md) records what each finished stage delivered, and the
[Roadmap](Roadmap.md) has the details of what's next.

## How we'll know it's working

- It replaces `http.server` in daily use, including on remote machines.
- Opening an agent's report or a regenerated plot is one click, and it's
  current.
- Someone new can install it and open a folder in under a minute, using only
  the README.

## Open questions

- **Publishing.** The repository is local. Next it goes to GitHub as
  `ivanfarevalo/bunko`, and to PyPI as `bunko`.
- **How far into team features to go.** Per-folder permissions and simpler
  sign-in would make it suitable for organizations, but they add real
  complexity to something that is currently one small process.
