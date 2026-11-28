# Bunko wiki

Project notes for Bunko: what it is, where it's going, how it's built, and
what has been done so far. User documentation lives in [docs/](../docs/), and
the [README](../README.md) covers installing and launching.

| Page | What's there |
|---|---|
| [Overview](Overview.md) | What Bunko is, who it's for, and what it deliberately isn't |
| [Goals and plan](Goals-and-Plan.md) | The high-level goal, the plan in stages, and open questions |
| [Features](Features.md) | Everything Bunko does today, by area, with links to the details |
| [Implementation](Implementation.md) | How it's built: the server, the browser app, storage, security, and key decisions |
| [Phases](Phases.md) | The project's history, phase by phase, from the first research to now |
| [Roadmap](Roadmap.md) | What's next, including "ask your files" with LLMs |
| [Report design](Report-Design.md) | The agreed design for `/report` and `bunko report` |

## Status

**Version 0.3.0**, in daily use. As of 2026-11-25:

- Public at [github.com/ivanfarevalo/bunko](https://github.com/ivanfarevalo/bunko),
  with CI on Linux and macOS and a tag-driven release workflow.
- Renamed from "shelf" to **Bunko** (文庫, "a library" or "a collection of
  books" in Japanese) on 2026-11-24.
- Released 0.3.0 on 2026-11-26: `uvx bunko`, `uv tool install bunko`, or the
  `install.sh` one-liner.
- Next up: the companion for AI agents.

## Keeping the wiki current

- Finish a phase: add what was done to [Phases](Phases.md), and move items
  out of the [Roadmap](Roadmap.md).
- Add a feature: list it in [Features](Features.md), and document it for users
  in `docs/features.md`.
- Change how something works: update [Implementation](Implementation.md),
  including the reason for the decision.
