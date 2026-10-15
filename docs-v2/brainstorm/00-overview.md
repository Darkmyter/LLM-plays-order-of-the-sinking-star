# Puzzle Game Agent — Design Overview

## Goal

Build an LLM agent that plays a grid-based puzzle adventure game **as close as possible to how a human plays it**: it observes, forms its own understanding of the mechanics, plans its own moves, makes mistakes, and learns from them.

The game consists of a large **open world** containing many **sub-levels** (puzzles). The open world is explored by walking between areas and by using objects and mechanics (stones, leaves, sinking, drifting, timing) to create crossings. New objects and mechanics are introduced as the game progresses, so the agent must keep discovering rules rather than relying on a fixed rule set.

It is acceptable for the agent to be imperfect. The aim is not to build a solver, but a player whose reasoning is its own.

## Core principle

> **The harness gives the agent what a human perceives and physically does. It never gives the agent what a human thinks.**

| Harness (code) | Agent (LLM) |
|---|---|
| Parses the game state into a clean representation | Forms, tests and revises rules |
| Reports facts: what is where, what is adjacent, what lies along a line | Draws conclusions from those facts |
| Walks the player to a visible destination (motor control) | Decides where to go and why |
| Executes actions and timed schedules precisely | Decides which actions, in which order, with what timing |
| Reports per-tick events, compresses still frames | Interprets cause and effect |
| Stores the rulebook, map and journal | Writes the content of the rulebook, map notes and journal |
| Compares the agent's written predictions with outcomes | Writes predictions, explains mismatches |
| Detects repeated states (loop detection) | Decides how to break out of a loop |

The harness reports **facts**, never **consequences**. "Column 50 below the tip: water, water, water, stone on land" is a fact. "So a stone pushed down will sink at (50,31)" is reasoning, and belongs to the agent.

## Document map

| File | Contents |
|---|---|
| `01-rulebook-and-knowledge.md` | Object-indexed rulebook, techniques, meta-hypotheses, assumption ledger, curation |
| `02-world-representation.md` | Grid format, object lists, line scans, coordinates, what makes a representation LLM-friendly |
| `03-harness-tools-and-aid-boundary.md` | Tool list, what aid is allowed, aid dials, the solver used for evaluation only |
| `04-context-and-memory.md` | Context assembly per turn, action log, single current state, compaction, loop detection |
| `05-level-agents-and-handoffs.md` | Fresh agent per level, what it receives, the exit report, retries |
| `06-open-world-navigation.md` | Areas-and-crossings graph, permanence, frontier, the navigator agent |
| `07-exploration-planning-and-time.md` | Modes, triggers, guardrails, temporal observation, timed actions |
| `08-case-studies.md` | The two worked puzzles and the lessons they teach about agent design |
| `09-benchmarking-and-metrics.md` | Experiments, ablations, generated levels, playthrough metrics, solution store, knowledge history |

## Architecture at a glance

```
                ┌──────────────────────────────┐
                │        Persistent stores      │
                │  rulebook · techniques ·      │
                │  world graph · journal        │
                └──────┬───────────────┬────────┘
                       │               │
          entry brief  │               │  exit report → curator
                       ▼               │
┌──────────────────┐  start   ┌────────┴─────────┐
│ Navigator agent  │ ───────► │  Level agent     │  (fresh, clean sheet
│ (open world)     │ ◄─────── │  per level)      │   for every level)
└────────┬─────────┘  report  └────────┬─────────┘
         │                             │
         ▼                             ▼
   ┌─────────────────────────────────────────┐
   │                Harness                   │
   │ perception · motor · timed execution ·   │
   │ per-tick traces · loop detection ·       │
   │ prediction comparison · storage          │
   └─────────────────────────────────────────┘
                       │
                       ▼
                     Game
```

## Design priorities, in order

1. **Clean perception.** Most LLM errors in grid games come from misreading positions. Fix perception first.
2. **A rulebook the agent writes and trusts appropriately.** Rules carry status and evidence.
3. **Context that contains each fact once, in one form.** One current state, one action log, no stacked snapshots.
4. **Fresh agents per level with a strong handoff.** Clean context, but carried-over knowledge.
5. **Time awareness that stays dormant until needed.** Most levels are turn-based; a few depend on timing.
6. **Minimal, adjustable aid.** Each aid is a dial, so its value can be measured.
7. **Cache whenever possible.** Stable blocks (system prompt, tools, rules, terrain, initial state) go first and never change within a level; everything volatile goes after them. See `04-context-and-memory.md`.

## Recommended build order

1. Single agent, context rebuilt every turn, rulebook loaded by object, compaction at level end.
2. Add the action log, pinned initial state and loop detection.
3. Add per-tick traces and timed action schedules.
4. Split into navigator + fresh level agents once the open world makes the context crowded.
5. Add the curator step once the rulebook starts accumulating duplicates.
6. Add aid dials and run comparisons (with vs without each aid), using the offline solver to diagnose failures.
