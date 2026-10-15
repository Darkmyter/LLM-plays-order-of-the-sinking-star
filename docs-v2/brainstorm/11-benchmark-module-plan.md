# Benchmark module: plan

Goal: find which representation, prompt, context mode and rule format make an LLM solve a level
faster, in fewer moves and with fewer tokens. The winners are then used in the real game unchanged.

## Principles

- **Templates live in the repo root, shared by the benchmark and the real player.** Nothing is
  benchmark-only. After benchmarking, the real game just points at a different template name.
- **Everything is a swappable, named variant on one axis:** representation, prompt, rules, context.
  A benchmark run is a choice of one variant per axis, plus a level and a model.
- **Same engine as the real player.** A trial is a normal `Run(scope="level")`, so results transfer.
- **Benchmark lives in the API player and is driven from the viewer.** The CLI is only a thin wrapper.

## Layout

```
templates/                 (root; used by the real player too)
  representations/<name>.toml   options for the renderer (fences inline | list, floor rows, object list style, ...)
  prompts/<name>.md             system prompt, slots {rules} {actions}
  rules/<name>.md|.py           rule format + content (bullets | object-indexed | with status | none | corrupted)
  context/<name>.py             how each turn is assembled (see below)
bench/
  levels/<name>/                snapshot.json, meta.json, solution.json (optional)
  experiments/<name>.json       levels x models x variants x runs
  results/<experiment>/<trial>/ normal run folder + trial.json
  runner.py                     queue, serial execution, restart between trials, progress events
  report.py                     aggregate + compare
```

`config.toml` gets one `[template]` block naming the default variant per axis, so the real player and
the benchmark read the same place.

## Code changes needed (the part that touches the player)

| Change | Where | Why |
|---|---|---|
| `render(state, options)` instead of one fixed layout; a representation is data | `game/game_state.py` | Swappable representation; also usable offline on a saved snapshot |
| `Session` gets a renderer argument instead of calling `render` directly | `game/session.py` (3 call sites) | The live game then uses the chosen representation |
| Prompt, rules and context loaded by name from `templates/` | `api_player/player.py` (`system_prompt`, `build_messages`, `prune`) | Swappable prompt / context |
| `ContextBuilder` interface: `build(run) -> messages`, `after_tool(run, result)` | new `api_player/context.py` | Context modes (below) |
| Per-step action counter (steps, acts, undo, restart, blocked) in the run's log | `game/session.py` | The move metric |
| Trial record (level, variants, model, outcome, metrics) in `meta.json` | `game/runs.py` | Comparison |
| Viewer routes: levels, experiments, queue, results | `viewer/server.py`, `page.html` | UI |

## Context modes (including the action log)

Each is a `templates/context/<name>.py`. Adding a new one is adding a file.

| Mode | What the model sees each turn |
|---|---|
| `history` (today) | Message history, old maps stubbed, per-step change reports kept |
| `current` | System + rules + notes + **current state only** + short recent window |
| `current+log` | `current` + numbered action log, one line per action with its outcome, written by the harness |
| `history+log` | `history` + the same action log |

The log line format is itself a template (`templates/log/<name>.md`), so log styles can be compared too.

## Benchmark flow

1. **Add a level.** In the viewer, with the game in a level: capture. The snapshot is saved under the
   level name.
2. **Record a solution (optional).** Play the level in the game while the recorder watches; or take the
   winning move list of any solved run; or paste moves. The harness replays the solution from a
   restart to verify it. A verified solution gives solvability and a move baseline.
3. **Offline probes (fast, parallel, no game).** Perception questions generated from the snapshot with
   ground truth, run over every representation and model. Cheap filter before live play.
4. **Create an experiment.** Pick levels, LLMs, and variants per axis, and N runs per cell.
5. **Run.** Serial, because there is one game window. The runner restarts the level, runs the trial,
   stops on solved / turn limit / cost cap, then the next. The viewer shows the queue and live progress.
6. **Compare.** Per cell: solve rate, median moves, tokens (prompt / cached / completion), cost, time,
   blocked moves, with spread across runs. Side by side per variant, with drill-down into any trial.

## Rulebook benchmark

Same runner, different axis. Fix the representation, prompt and context, then vary the rules variant:
none, given, one corrupted, bullets vs object-indexed vs with status. Use levels where the rules decide
the result. Start with the prefilled template (`level_rules.py` content moved into `templates/rules/`).

## Metrics

Solved, moves (steps; undo / restart separate), act calls, model turns, prompt / cached / completion
tokens, cost, wall time, blocked moves, moves vs the recorded solution. Always report N and spread.

## Build order

1. Template loading from the root + `render` options + `Session` renderer. Behaviour unchanged, default
   templates equal today's output (check with a byte-for-byte diff of the old view).
2. `ContextBuilder` with `history`, then `current`, `current+log`.
3. Step counter and trial record.
4. Level capture + `bench/levels`.
5. Runner + experiment file + report (CLI first).
6. Viewer pages: levels, experiments, queue, results.
7. Offline probes.
8. Solution recording from the screen.

Steps 1-2 give the first real experiment (context mode comparison) even before the UI exists.

## Open points

- **Recording a solution from the screen** is the least certain part: reconstructing moves from polled
  state is unreliable around undo and pushes. The safer sources are a solved run's move list or pasted
  moves, verified by replay. Decide whether screen recording is worth building.
- **Level reset between trials:** confirm `restart` returns a solved level to a playable start.
- **Level set:** pick two or three first levels with different mechanics.
