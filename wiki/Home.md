# shelf wiki

Project notes for shelf: what it is, where it's going, how it's built, and
what has been done so far. User documentation lives in [docs/](../docs/), and
the [README](../README.md) covers installing and launching.

| Page | What's there |
|---|---|
| [Overview](Overview.md) | What shelf is, who it's for, and what it deliberately isn't |
| [Goals and plan](Goals-and-Plan.md) | The high-level goal, the plan in stages, and open questions |
| [Features](Features.md) | Everything shelf does today, by area, with links to the details |
| [Implementation](Implementation.md) | How it's built: the server, the browser app, storage, security, and key decisions |
| [Phases](Phases.md) | The project's history, phase by phase, from the first research to now |
| [Roadmap](Roadmap.md) | What's next, including "ask your files" with LLMs |

## Status

**Version 0.3.0**, in daily use, not yet published. As of 2026-11-24:

- The source is in its own Git repository, with uv, ruff, Biome, and
  pre-commit set up.
- The name is still open: "shelf" collides with other projects (see
  [Goals and plan](Goals-and-Plan.md#open-questions)).
- Next up: publish the repository, then make Word and Excel files searchable.

## Keeping the wiki current

- Finish a phase: add what was done to [Phases](Phases.md), and move items
  out of the [Roadmap](Roadmap.md).
- Add a feature: list it in [Features](Features.md), and document it for users
  in `docs/features.md`.
- Change how something works: update [Implementation](Implementation.md),
  including the reason for the decision.
