# Suggested Improvements (short list)

Filtered from docs 00–09 against the player design principles: describe, never explain or solve; never mislead; let the player learn and take notes.

## Do first

1. **Clean world representation** (02). Row labels, stated column range, fixed legend, object list with exact coordinates, stable object names. Check it covers fences, floor rows and heights. Validate with perception probes before anything else.
2. **Action log + one current state** (04). One line per action, failed actions included. Tool results report only what changed; the full state is replaced each turn, never stacked.
3. **Loop detection** (04). Hash objects + player after each action and report "this state was already reached after #N". Report only, never advise.
4. **Per-tick event traces** (07). One line per tick where something changed, then "settled at tN". Needed to see anything that moves over time.
5. **Perception probes** (09 §1.1). "What is at (x,y)?", "what is below X?" Run on every format change, together with the existing OpenRouter comparison, to separate "cannot see" from "cannot think".

## Do next

6. **Rules given / hidden / corrupted** (09 §1.4). Run the same level under all three. Corrupted shows whether the player notices a wrong rule and repairs it.
7. **Aid dials in config** (03). Every aid gets a default (on / off) so each can be ablated. Start with: line scan, neighbours, loop detection, per-tick traces.
8. **Optional `predict` tool** (03). The agent writes the expectation, the harness only compares. Off by default; use as an ablation.
9. **Retry with a stuck report** (05). A new agent gets what was tried and what failed, not the old reasoning. Build this alone, without the navigator split.
10. **Offline solver for evaluation only** (03). Never exposed to the player. Use it to tell planning failures from rule or perception failures.

## Later, only if a real run shows the need

11. Navigator / level-agent split (05). Needs a clear "level start / end" signal first.
12. Curator step and object-indexed rulebook (01). Add when plain notes pile up duplicates.
13. Techniques list carried between levels (01). Most transferable knowledge, but start as ordinary notes.
14. `act(schedule)` / `wait` timing actions (07). Only if the game has timed mechanics.
15. Prompt-caching layout (04). Cost optimisation, not design.

## Keep out by default (conflicts with the principles)

- Auto-computed areas, `travel_to(area)`, reachability hints, frontier list (06, `area_info` in 03).
- Interaction index showing "never observed" pairs (01).
- Seeded meta-hypotheses and ledger tests that hint how to experiment (01).
- Explore / Solve / Debug modes and strategy guardrails in the prompt (07).
- The one-time "objects keep moving" flag (07). Mild, but still a hint; make it an ablation.

## Housekeeping

- Add a status line to each doc: idea / decided / built.
- State the boundary once (00) and link to it elsewhere.
- Move case-study layouts into level files so tests can load them.
- Say how benchmarking builds on the existing `runs/` folders instead of adding a database.
