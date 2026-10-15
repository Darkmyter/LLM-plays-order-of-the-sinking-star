# Harness, Tools and the Aid Boundary

The harness decides how human-like the agent's play is. Too little aid, and the agent fails on perception problems a human never has (miscounting grid cells). Too much aid, and code does the thinking: the agent calls a solver and executes the answer.

## The boundary

> Give the agent what a human **perceives** and **physically does**. Never give it what a human **thinks**.

A human sees the whole screen at once, knows instantly what is next to what, notices when something unexpected happens, and walks without planning each step. A human does **not** get told where a stone will end up, which moves solve a level, or whether a plan will work. Those come from applying learned rules, which is the agent's job.

Test for any proposed aid: **does it report a fact, or a consequence?** Facts are allowed. Consequences are not.

## Aid table

| Aid | Verdict | Reason |
|---|---|---|
| Clean grid + object list with coordinates | Keep | Instant for a human; removes counting errors |
| Line scan: what lies along a row/column until land | Keep | Spotting a water gap is perception |
| Adjacency query: what surrounds an object | Keep | Seeing, not reasoning |
| Walk to a visible destination | Keep | Motor control |
| Per-tick event traces | Keep | Equivalent to watching the screen |
| Notebook storage (rulebook, map, journal) | Keep, agent writes content | Like a human's notes |
| Prediction mismatch flag | Keep, agent writes predictions | Like noticing "that's not what I expected" |
| Repeated-state detection | Keep | "I've been here before" is recognition, cheap for a human, costly for an LLM |
| Undo / reset | Keep if the game has them | A human has them too |
| Novelty flag (new object type) | Optional | Humans notice novelty; can be left to the agent |
| "Where will this object end up" | Remove | Applying a rule |
| `simulate(actions)` | Remove | Code reasoning on the agent's behalf; also invites impossible actions |
| `solve(goal)` | Remove | Code solving the level |

## Tool list

### Perception

| Tool | Returns |
|---|---|
| `observe()` | Current terrain view, object list, player position, area name |
| `scan(from, direction)` | Ordered list of tiles and objects along a line until the edge of the view or a stopping condition the agent specifies (e.g. `until_land`) |
| `neighbours(target)` | The four adjacent tiles and their contents |
| `area_info()` | The walkable area the player is in, its name and size |

### Action

| Tool | Behaviour |
|---|---|
| `walk_to(position)` | Walks the player to a reachable tile; fails with a reason if unreachable |
| `push(object, direction)` | Player must be adjacent on the opposite side; returns the event trace |
| `act(schedule)` | Executes a timed sequence, e.g. `t0: push A left; t4: push B left`. Returns the merged trace |
| `wait(ticks)` | Lets time pass without acting |
| `undo()` / `reset_level()` | If supported by the game |

### Knowledge (storage only)

| Tool | Behaviour |
|---|---|
| `rulebook.query(object)` | Rules for an object, with status and evidence |
| `rulebook.add / update / contradict` | Agent-written changes |
| `techniques.list / add` | Strategy lessons |
| `ledger.add / resolve` | Assumptions and their tests |
| `map.mark(area, note)` / `map.add_crossing(...)` | Open-world notes |
| `journal.add(entry)` | Milestones |

### Self-check

| Tool | Behaviour |
|---|---|
| `predict(action, expected)` | Agent records what it expects before acting; the next result reports match or mismatch |

The harness only compares; it never generates the expected outcome.

## Tool definitions and caching

Tool definitions are sent with every call, so they should be cached:

- One **fixed** tool set per agent role (navigator, level agent). Never add or remove tools mid-level or by mode; the system prompt states which tools suit which mode.
- Short, precise tool descriptions.
- Deterministic ordering of tools.

## Tool result format

Results are compact and event-based. They never repeat the full world state, which is held once in the rebuilt context.

```
push stone A down from (43,39)
t1  A moved (43,38)→(43,37)
t2  A entered water (43,36)
t3–t6  A slid down column 43
t5  leaf 1 (carrying B) began drifting right from (44,32)
t7  A settled on land (43,31)
t11 leaf 1 stopped at (50,32), blocked by # at (51,32)
settled at t11
prediction: MATCH
```

## The solver: for evaluation, not for the agent

Keep a solver, but outside the agent's reach. Use it on the developer side to:

- check that a level is solvable with the rules the agent has discovered so far;
- compare the agent's move count with the optimum;
- diagnose failures: if the agent's rulebook is correct and it still fails, **planning** is the weak link; if the rulebook is wrong, **perception or exploration** is.

## Aid dials

Put every aid behind a configuration setting:

```yaml
aid:
  object_list: on
  line_scan: on
  neighbours: on
  walk_to: on
  loop_detection: on
  novelty_flag: off
  prediction_check: on
  images: off
```

Run the same levels with different settings to measure what each aid contributes. The minimal configuration at which the agent still progresses is likely the most human-like setup available.

## Common failure: tool misuse

If the agent has powerful tools, it tends to substitute tool calls for reasoning, and may call them with actions that are impossible in the game. Keeping tools limited to perception and motor actions avoids this. The agent's plans then take the intended shape:

> "I need to cross column 50. The scan shows three water tiles, then stone D on land. By R3, a stone pushed down will hit D and sink at (50,31). That fills one tile; I still need two more."
