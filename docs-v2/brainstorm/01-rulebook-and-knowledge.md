# Rulebook and Knowledge

The agent's long-term understanding of the game lives in persistent stores that **the agent writes** and **the harness stores**. The harness never fills in rules on the agent's behalf.

There are four kinds of knowledge, kept separate because they are used differently:

| Kind | What it captures | Example |
|---|---|---|
| **Rules** | How a specific object behaves or interacts | "A stone passing adjacent to a leaf pushes the leaf away" |
| **Techniques** | Strategy lessons that are not tied to one object | "A stone can serve twice: ride a leaf, then be pushed again" |
| **Meta-hypotheses** | General possibilities worth keeping in mind | "Outcomes may depend on timing" |
| **Assumption ledger** | Unverified ideas, each with a cheap test | "Can the player stand on a leaf? Test: step onto a docked leaf" |

## 1. Rules, indexed by object

```
OBJECT leaf
  properties:
    floats on water
    blocks player? unknown
  rules:
    R7  stone passes adjacent → leaf drifts away from the stone's path
        until blocked                                   [confirmed ×3]
    R8  stone enters the leaf's tile → stone rides the leaf, both
        continue in that direction until blocked        [confirmed ×2]
    R9  a stone riding a leaf can be pushed again when the player
        stands next to it                               [confirmed ×1]
  open questions:
    Q3  can the player stand on a leaf?
```

```
OBJECT stone
  rules:
    R1  pushed on land → moves one tile                  [confirmed ×6]
    R2  pushed into water → slides until terrain, settles on the
        first terrain tile                               [confirmed ×4]
    R3  sliding stone hits a stone standing on a terrain edge →
        sinks in the last water tile, which becomes terrain
                                                         [confirmed ×2]
```

### Interaction index

A table from object pairs to rules. It answers "what happens when A meets B?" and also reveals which pairs have **never** been observed. Those gaps are exploration targets.

```
(stone, stone)    → R3
(stone, leaf)     → R7, R8, R9
(stone, brown rock) → R2 (acts as terrain)
(leaf, brown rock)  → leaf stops against it
(player, leaf)    → unobserved
(leaf, leaf)      → unobserved
```

### Rule entry fields

| Field | Purpose |
|---|---|
| `id` | Stable reference so plans and reports can cite rules ("by R3…") |
| `objects` | Which objects the rule involves (used for indexing and loading) |
| `statement` | One sentence in the agent's own words |
| `status` | `hypothesis`, `confirmed`, `contradicted` |
| `evidence` | Count and links to trace summaries that support or contradict it |
| `first_seen` | Level / area where it was first observed |
| `conditions` | Known preconditions ("only when the leaf is docked against land") |

Rules confirmed only once stay marked as weak. A level agent can rely on strong rules but should treat weak ones as worth verifying before an irreversible plan depends on them.

## 2. Techniques

Techniques are the most valuable thing to carry from level to level, and they are easily lost if only object rules are stored. They describe **ways of thinking about puzzles**, not object behaviour.

Examples drawn from the puzzles solved so far:

- **Double duty.** A single object can fill two roles in sequence. A stone rode a leaf into position, then was pushed off it to become a sunk tile.
- **Reuse before concluding impossible.** When resources seem one short, look for a piece that can be used twice before deciding the puzzle needs something else.
- **Redirect objects in motion.** A moving leaf can be pushed sideways mid-drift by a stone passing beside it, so it stops in a column it could not otherwise reach.
- **Stoppers define destinations.** Objects that slide stop only where something blocks them. To land something on a specific tile, look for what could stop it there.
- **Build bridges from the far end.** A sink needs a standing stone at the edge; fill the gap starting at the side where such a stone already exists.

Each technique records where it was learned and a one-line example, so the agent can recognise similar situations.

## 3. Meta-hypotheses

Generic possibilities seeded at the start of the game. They are not hints for any specific level; they exist to prevent blind spots.

- Objects may interact while still moving, not only after they settle.
- The outcome of an action may depend on **when** it is taken.
- An object may serve more than one purpose in a solution.
- A resource that looks spent may be reusable.
- A new object type probably has at least one interaction not yet seen.
- Terrain-like objects (brown rocks, checkpoints, decorations) may or may not block movement; check.

Some meta-hypotheses stay **dormant** until triggered. The timing hypothesis, for example, activates when multi-tick motion is first observed or when the agent is stuck and sequential plans are exhausted (see `07-exploration-planning-and-time.md`).

## 4. Assumption ledger

A short list of things the agent is currently assuming without verification, each paired with the cheapest test that would settle it.

```
A4  player can stand on a leaf
    test: step from land onto a docked leaf
    risk if wrong: crossing plan for area "stone island" fails
A5  brown rocks are not walkable
    test: try to step onto one from an adjacent tile
```

The ledger's purpose is to make hidden assumptions visible. A plan that depends on a ledger entry should test that entry first, especially before irreversible actions.

## 5. Curation

Without curation, the rulebook fills with near-duplicates, stale hypotheses and contradictions. After each level (or after a long exploration stretch), a curation step:

1. Reads the level agent's exit report and trace summaries.
2. Merges duplicate rules and rewrites unclear statements.
3. Promotes hypotheses with enough evidence to `confirmed`.
4. Marks contradicted rules, keeping them visible with the contradicting evidence rather than deleting them.
5. Moves strategy-level lessons into the techniques list.
6. Updates the interaction index and removes resolved ledger entries.

Curation can be a separate short LLM call with only the rulebook and the report in context. It should never invent rules that are not supported by reported evidence.

## 6. How rules are loaded into context

- At level start, load all rules for the object types present in the level, plus all techniques and active meta-hypotheses.
- The agent can query the rulebook for anything else (`rulebook.query("leaf")`).
- Rules are shown with their status so the agent knows how much to trust them.

## Why this matters

In the first puzzle, the agent (me, in this conversation) treated a stone riding a leaf as permanently fixed. That missing rule, R9, made a solvable puzzle look impossible. The fix is structural: explicit rules with status, a ledger that exposes assumptions, and meta-hypotheses like "a resource may be reusable" that prompt the agent to question its own model before concluding a puzzle is unsolvable.
