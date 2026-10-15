# Context and Memory

The hardest engineering problem is what the model sees each turn. The goals conflict: low token usage, no information overload, but no forgetting, no loops, and a clear sense of how the level has progressed.

## Principle: rebuild, don't accumulate

Do not keep one ever-growing message list and truncate it at X messages. Truncation discards information arbitrarily. Instead, **rebuild the context every turn** from structured state, and keep only a short window of recent messages.

## Memory tiers

| Tier | Contents | Lifetime | Where it lives |
|---|---|---|---|
| Persistent stores | Rulebook, techniques, ledger, world graph, journal | Whole game | Code (JSON / SQLite) |
| Episode state | Pinned initial state, action log, current state, plan, predictions, mode | One level | Code, rendered into the prompt |
| Recent window | Last ~5–10 exchanges | Rolling | Message list |

## Context layout per turn

Ordered from most stable to most volatile, which also keeps prompt caching effective:

```
[system]   role, how to play, rule-writing conventions       never changes
[tools]    tool definitions                                  never changes
[rules]    rules for objects in this level, techniques,
           active meta-hypotheses, open ledger entries       changes per level
[terrain]  static terrain grid for the level                 set at level start
[pinned]   initial level state (compact), level goal         set at level start
[log]      numbered action log, one line per action          grows slowly
[current]  full current state                                replaced every turn
[plan]     current plan, pending predictions, mode           changes often
[recent]   last few exchanges, tool results as events only   rolling
```

## One current state, never several

Every tool call that changes the world returns **only events** (what moved, what sank, what stopped). The `[current]` block is replaced with the new full state. Old full states are never left in the message history.

This gives exactly one representation of the world at any time:

- **Where it started:** the pinned initial state.
- **What it did:** the action log.
- **Where it is now:** the current state.

## The action log

```
#12 push A down from (43,39) → A settled (43,31); leaf 1 + B drifted to (50,32)
#13 push C down from (50,35) → C sank at (50,33)
#14 walk to (50,33)
#15 push B down off leaf 1 → B sank at (50,31)
```

- One line per action, written by the harness from the event trace.
- Objects use stable names (stone A, leaf 1).
- Failed or blocked actions are logged too (`#9 push A left → blocked by land`), since repeated failed attempts are a loop signal.

### Folding long logs

When a level runs long (30–40+ actions), the agent folds earlier stretches into milestone lines:

```
#1–#11  set up stones A and B for the leaf ride (see journal: "leaf ride setup")
```

The agent writes the fold, so it decides what was important. The harness keeps the unfolded log on disk in case it is needed for debugging or for the curator.

## Loop detection

The harness hashes the configuration of all objects plus the player position after every action. If a configuration repeats, the tool result says so:

```
note: this exact state was already reached after #7
```

The harness only reports the repetition. Deciding what to do about it is the agent's job. A good default instruction in the system prompt: "If you return to a previous state, state what you will do differently this time, or switch approach."

## Compaction at meaningful boundaries

Compact when something meaningful ends, not at a message count:

| Trigger | Action |
|---|---|
| Level solved or abandoned | Agent writes the exit report; window cleared; knowledge sent to curation |
| Mode switch (e.g. Explore → Solve) | Exploration chatter summarized into rulebook updates and one journal line |
| Token budget exceeded (safety net) | Oldest recent exchanges summarized, never silently dropped |

## Prompt caching: cache whenever possible

Caching is the single biggest lever on cost. Cached input tokens are much cheaper than uncached ones, and in this design most of each turn's context is identical to the previous turn. The rule is simple: **anything that does not change between calls belongs in the cached prefix, and nothing volatile may appear inside it.**

### How the cache works here

The cache matches the prompt from the start. The first token that differs invalidates the cache for everything after it. So the order of blocks matters as much as their content:

```
┌─ cached ───────────────────────────────────────────────┐
│ [system]   never changes                               │
│ [tools]    fixed per agent role                        │
│ [rules]    fixed for the whole level                   │
│ [terrain]  fixed for the whole level (static layout)   │
│ [pinned]   initial state, goal: fixed for the level    │
└────────────────────────────────────────────────────────┘
┌─ volatile ─────────────────────────────────────────────┐
│ [log]      grows each action                           │
│ [current]  object list + terrain overlays              │
│ [plan]     plan, predictions, mode                     │
│ [recent]   last few exchanges                          │
└────────────────────────────────────────────────────────┘
```

### What to cache

| Block | Cache? | Notes |
|---|---|---|
| System prompt | Always | One version per agent role |
| Tool definitions | Always | Fixed tool set per role (navigator, level agent); never add or remove tools mid-level |
| Rules, techniques, meta-hypotheses | Per level | Loaded once at level start; rule updates made during the level go in the volatile part until the next level |
| Terrain grid | Per level | Terrain is static within a level. Changes (a tile becoming land after a sink) are listed as overlays in the current state, not redrawn |
| Pinned initial state and goal | Per level | Written once at level start |
| Navigator world summary | Per area | Rebuilt only when the player enters a new area or a crossing changes |

### What breaks the cache (keep out of the prefix)

- Timestamps, turn counters, token counts, elapsed time.
- Rules sorted by recency or usage. Sort by ID instead.
- Rule status changes mid-level. Note them in the volatile part; fold them into the rules block at the next level start.
- Redrawing the terrain after every sink.
- Dynamic tool lists (tools appearing or disappearing by mode). Keep one fixed list per agent role and let the system prompt say which tools fit which mode.
- Any randomness or reformatting in how stable blocks are rendered. Rendering must be deterministic: same input, byte-identical output.

### Cache-friendly habits elsewhere

- **Append, don't rewrite**, inside the volatile part where possible: the action log grows at the end; folding old log lines happens only at compaction points, which accept one cache miss.
- **Compaction is a planned cache miss.** Do it at boundaries (level end, mode switch), not every few turns.
- **Fresh level agents** start with a new prefix by design. Their first call pays full price; every later call in the level should hit the cache.
- **Sub-agents and model routing:** caches are per model and per prefix. A small model used for navigation keeps its own stable prefix; do not interleave models on the same prefix and expect hits.

### Measure it

Log cached vs uncached input tokens on every call (see `09-benchmarking-and-metrics.md`). A falling cache-hit rate is the first sign that something volatile slipped into the prefix.

## Core loop (sketch)

```python
while not level_done:
    ctx = build_context(stores, episode, recent)
    reply = llm(ctx, tools)
    for call in reply.tool_calls:
        result = harness.run(call)            # events only
        episode.apply(result)                 # updates current state + log
        recent.append(call, result.events)
    episode.update_plan(reply)
    if episode.boundary_reached():
        compact_and_persist(episode, recent, stores)
```

`build_context` is where the real design work is. The rest is plumbing.

## What the agent should never have to do

- Reconstruct the current state from a history of events.
- Compare two full grid snapshots to find what changed.
- Remember earlier positions by scrolling back through messages.
- Count cells to find an object.
