# Benchmarking and Metrics

Two complementary activities:

1. **Benchmarking**: controlled experiments on individual levels or skills, run many times with different configurations, to learn what helps the agent.
2. **Playthrough tracking**: metrics recorded during real play of the full game, to measure progress, cost and learning over time, and to collect material for future benchmarks.

Both rely on the same foundations: a modular harness, an offline solver used as the referee (never given to the agent), and replayable run logs.

---

## Part 1 — Benchmarking

### 1.1 Perception probes

Tests that involve no playing, only reading the world correctly.

| Probe type | Examples |
|---|---|
| Lookups | "What is at (44,34)?" · "Where is stone B?" · "What is directly below the leaf?" |
| Structure | "List the water gaps between these two areas" · "Which tiles can the player reach?" |
| Format comparison | The same questions asked over each representation (plain grid, grid + object list, row-labelled grid, JSON, image) |

Purpose: separate "cannot see" from "cannot think". Run perception probes before blaming planning for errors that are really reading errors.

### 1.2 Single-move prediction

Given a state and one action, the model predicts the full outcome ("stone C is pushed down: where does everything end up?").

| Variant | Measures |
|---|---|
| Rules given | Rule application |
| Rules hidden, a few example traces shown | Rule induction from examples |

Good as a fast regression test whenever prompts or formats change.

### 1.3 Move-sequence validity

The model writes a complete move sequence without executing it. The engine replays it and classifies every error:

| Error category | Meaning | Usually points to |
|---|---|---|
| Illegal move | Pushing from an unreachable position, pushing into a wall | Perception or state tracking |
| Unaccounted blocker | Bumped into something it ignored | Perception |
| Wrong rule applied | Expected a slide, got a sink | Rulebook |
| Position drift | Its belief about positions diverged from reality mid-sequence | State tracking |
| Valid but not solving | Every move legal, goal not reached | Planning |

The error mix indicates what to fix.

### 1.4 Single-level mode (open world removed)

The same level run under three rule conditions:

| Condition | Measures |
|---|---|
| **Rules given** | Pure planning ability |
| **Rules hidden** | Discovery + planning |
| **Rules corrupted** (one rule deliberately wrong) | Whether the agent notices failed predictions and repairs its model, or keeps following the wrong rule |

The corrupted condition directly tests the failure seen in case study 1, where a missing rule made a solvable puzzle look impossible.

### 1.5 Robustness variants

Generated variants with logically identical solutions:

| Variant | Detects |
|---|---|
| Mirrored / rotated | Reliance on coordinate habits rather than understanding |
| Renamed symbols and objects | Reliance on specific tokens |
| Shifted coordinates (x 200–230 instead of 40–60) | Sensitivity to number ranges |
| Irrelevant extra islands or objects | Cost of clutter on attention |

### 1.6 Rule induction and transfer

| Test | Method |
|---|---|
| Rule discovery | Feed traces only; ask for a rulebook; score against ground truth |
| Transfer | Learn on levels 1–5; test on level 6 with the same mechanics in a new arrangement |
| Rule change | Silently alter a mechanic mid-run; count actions until the agent notices and updates |

### 1.7 Ablations

Toggle one setting at a time:

| Area | Settings |
|---|---|
| Aids | Line scans, object list, adjacency queries, loop detection, prediction check |
| Context | Action log on/off, rebuilt vs accumulated context, size of recent window |
| Thinking | Reasoning budget, "predict before acting" on/off, reflection after failure on/off |
| Meta-hypotheses | Timing hypothesis dormant vs active (case study 2) |
| Knowledge handoff | Techniques list on/off for fresh level agents |

### 1.8 Comparisons

- **Models**: different sizes and providers on the same suite.
- **Cost efficiency**: solve rate per token or per dollar. A smaller model with better aids may beat a larger model with fewer aids.
- **Human baseline**: several people play the same levels with move logging. This gives a target for "human-like": similar move counts and similar kinds of mistakes.

### 1.9 Generated levels

Use the solver to generate random levels and keep only solvable ones, graded by:

- optimal solution length;
- mechanics required (sinking, leaf ride, drift, timing);
- number of objects and distractors.

This yields a large, difficulty-ordered test set and makes overfitting to a few hand-made puzzles harder.

### 1.10 Harness modularity

Every experiment is a configuration:

```yaml
level: case1_double_duty
variant: mirrored
representation: grid_plus_objects
prompt: system_v3
rules: hidden          # given | hidden | corrupted
aids:
  line_scan: on
  loop_detection: off
model: model_a
thinking_budget: medium
runs: 10
seed: 42
```

- Prompts are separate files (system prompt, rulebook format, mode instructions), swapped by name.
- Representations are pluggable renderers over the same underlying state.
- Every run is saved as a replayable log.
- Each configuration runs several times; single results tell little because LLM outputs vary.

### 1.11 Benchmark metrics

| Metric | Notes |
|---|---|
| Solve rate | Per configuration, over N runs |
| Moves vs optimal | From the solver |
| Illegal-move rate and error categories | From 1.3 |
| Prediction accuracy | Per action |
| Rulebook accuracy | Against ground-truth rules |
| Loops / repeated states | Count and length |
| Soft-locks | Count, and actions between becoming unsolvable and being detected |
| Tokens, cost, wall-clock time | Per run and per solve |
| Actions until first correct rule | Per new mechanic |
| Variance across runs | Spread, not just the mean |

---

## Part 2 — Playthrough tracking (the real game)

Everything recorded during a real playthrough of the full game. These metrics serve three purposes: measuring progress and cost, understanding how knowledge accumulates, and harvesting solved levels as future benchmarks.

### 2.1 Per level

| Metric | Detail |
|---|---|
| Wall-clock time | From level entry to exit |
| Game time | In ticks, excluding time paused while the agent thinks |
| Actions | Total, split by type: pushes, walks, waits, timed schedules |
| Attempts | Resets, undos, fresh-agent retries |
| Outcome | Solved, stuck, abandoned; number of visits before solving |
| Moves vs optimal | When the solver can compute the optimum |
| Errors | Illegal moves, blocked moves, prediction mismatches, repeated states |
| Soft-locks | Count per level; for each: action index where the level became unsolvable, how many actions until the agent noticed (or the harness forced a reset), and whether the agent detected it itself |
| Mode split | Share of actions in Explore, Solve, Debug |
| Usage | Model calls, tool calls by type, input/output tokens, cached tokens, cost |
| Cache-hit rate | Cached input tokens / total input tokens, per level; a drop signals something volatile entered the prefix |
| Aid usage | How often each perception tool was called |

### 2.2 Solution store

Every solved level is saved as a reusable benchmark item:

```yaml
level_id: L4
area: stone island
initial_state_hash: 9f3a…
initial_state: <full state snapshot>
solution:
  - push B left from (48,37)
  - push B left from (47,37)
  - push B down from (44,38)
  - push A down from (43,39)
  - push C down from (50,37)
  - push B down from (50,33)
moves: 6
optimal_moves: 6          # from solver, if available
mechanics_used: [sink, leaf_ride, drift, double_duty]
solved_by:
  model: model_a
  config: config_hash
  rulebook_version: 14
  attempts_before_success: 2
date: 2026-10-14
```

Uses:

- Replay to verify the solution still works after game updates.
- Add to the benchmark suite with the known solution as reference.
- Compare later agents or models on exactly the same starting state.
- Generate robustness variants (mirrored, renamed) from real levels.

### 2.3 Per rule and technique (knowledge history)

| Field | Detail |
|---|---|
| Discovered at | Level, area, action index, timestamp |
| How discovered | Deliberate experiment, accidental observation, prediction mismatch |
| Evidence history | Each confirmation or contradiction with its level and action |
| Status changes | When it moved from hypothesis to confirmed (or contradicted) |
| Times cited in plans | How often the agent relied on it |
| Times part of a solving plan | How useful it actually was |
| Errors linked to it | Plans that failed because of this rule |

The same fields apply to techniques. This answers questions like "which mechanic took longest to understand?" and "which rules were wrong for a long time?"

### 2.4 Open world

| Metric | Detail |
|---|---|
| Areas visited / explored / finished | Over time |
| Crossings opened | By type (passage, built bridge, leaf) |
| Backtracking | Distance and time spent returning to earlier areas |
| Frontier size | Over time; a growing frontier means many open leads |
| Stuck levels | How long each stayed stuck and what unlocked it |
| Time to new technique applied elsewhere | From learning a technique to using it on a frontier candidate |

### 2.5 Whole playthrough

- Progress curve: levels solved and areas finished against time, actions and cost.
- Cost curve: tokens per level over the course of the game. Ideally it falls as the rulebook improves.
- Learning curve: prediction accuracy over time.
- Total hints given by a human, if hints are allowed (see below), with where and why.

### 2.6 Storage

A small database (SQLite is enough) with append-only tables:

```
runs          (run_id, model, config_hash, start, end)
events        (run_id, tick, level_id, type, payload)
actions       (run_id, index, level_id, action, result, predicted, matched)
levels        (run_id, level_id, outcome, time, actions, tokens, cost)
solutions     (level_id, initial_state_hash, sequence, moves, solved_by)
rules_history (rule_id, version, status, statement, level_id, action_index, timestamp)
usage         (run_id, call_index, input_tokens, output_tokens, cached_tokens, cost)
```

Append-only storage keeps the full history, so any point of a playthrough can be reconstructed and replayed.
