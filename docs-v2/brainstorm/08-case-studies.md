# Case Studies

Two puzzles worked through in the design conversation. Both are useful as test levels for the agent, and both exposed specific weaknesses in how an LLM reasons about this game.

## Rules as known at the time

- A stone pushed on land moves one tile.
- A stone pushed into water slides across and settles on the next terrain tile.
- A sliding stone that hits a stone standing on a terrain edge sinks into the last water tile, which becomes terrain.
- A stone sliding past a leaf (in the tile beside it) makes the leaf drift away from its path until it is blocked.
- A stone entering a leaf's tile settles on the leaf, and both continue in that direction until blocked.

## Case 1: the double-duty stone

### Layout (key elements)

- Stones A (43,38), B (47,37), C (50,36) on the top island. Stone D (50,30) on the bottom island's edge.
- Leaf at (44,34).
- Column 50: sandy tip at (50,34), water at (50,33), (50,32), (50,31), then stone D.
- Brown rock at (51,32), which stops anything drifting right along row 32 in column 50.

### Solution

1. Push B to (44,37), then down. B slides onto the leaf; both ride down to (44,32).
2. Push A down column 43. It passes left of the leaf, which drifts right with B on it and stops at (50,32) against the brown rock.
3. Push C down from the tip. It hits B (on the leaf) and sinks at (50,33).
4. Walk onto (50,33) and push B off the leaf. It slides into D and sinks at (50,31).
5. Bridge complete: sunk C, empty leaf, sunk B.

### What went wrong in the LLM's reasoning

- It treated the stone on the leaf as permanently fixed, so each stone appeared to have one job only. The missing rule was "a stone on a leaf can be pushed again".
- It committed early to an obvious first move (sink C against D), which used up D's role in the wrong place.
- When the count came out one stone short, it concluded the rules must be different, instead of questioning its own plan.

### Design lessons

- **Rule:** a stone riding a leaf can be pushed again → rulebook entry R9.
- **Technique:** double duty; reuse before concluding impossible.
- **Meta-hypothesis:** a resource that looks spent may be reusable.
- **Guardrail:** "one resource short" is a prompt to search for reuse, not a conclusion.
- **Perception:** the first attempt at reading the screenshot placed objects a column off; exact coordinates in an object list would have prevented it.

## Case 2: the timing drift

### Layout (key elements)

- Player on the right island at (36,32). Reachable stones on the right island.
- A small land patch at (26,32)–(26,33), reachable by walking the row-31 strip.
- Leaf at (25,34), next to the checkpoint. The user's target was given as (25,34); in the grid that is the leaf, and the checkpoint is most likely the `c` at (24,34).
- Leaf at (30,38) in open water, on row 38.
- The missing tile is (26,34): it would connect the land patch to the leaf beside the checkpoint.

### Solution

1. Pre-position one stone at (33,38) and another at the edge of row 39.
2. Push the row-38 stone left. It lands on the leaf at (30,38), and stone and leaf ride left along row 38.
3. A moment later, push the row-39 stone left, so it slides along the row above.
4. Timed so that the row-39 stone passes (26,39) exactly when the leaf is at (26,38), the leaf is pushed down column 26 and stops at (26,34), against the land at (26,33).
5. Walk to (26,33), push the stone off the leaf (upward), step onto the leaf at (26,34), then onto the leaf at (25,34), then onto the checkpoint.

The timing window is one tile. One tick early, the leaf goes down column 27 and stops at (27,33). One tick late, it goes down column 25 and stops at (25,35), on top of the other leaf.

### What went wrong in the LLM's reasoning

- Without being told timing was involved, it did not consider actions taken while objects were still moving.
- It asked clarifying questions (reasonable, given unknown symbols), but its model of the game had no notion of objects interacting mid-motion.
- The target coordinate was off by one column due to hand-counting the grid, illustrating the representation problem again.

### Design lessons

- **Action space:** the agent must be able to issue actions while objects are moving, and to schedule actions by tick (`act(schedule)`, `wait`).
- **Observation:** per-tick event traces are needed to see that a stone passing a moving leaf redirects it.
- **Meta-hypothesis:** outcomes may depend on when an action is taken (dormant until multi-tick motion is observed).
- **Technique:** redirect objects in motion; stoppers define destinations.
- **Representation:** legend for every symbol (`c` was undefined), exact coordinates for targets.

## Using these as test levels

| Test | What it checks |
|---|---|
| Case 1 with rule R9 withheld | Does the agent discover that a riding stone can be pushed again, or does it conclude the level is impossible? |
| Case 1 with R9 known | Can it plan a five-step solution in which one object serves twice? |
| Case 2 without timing aids (no scheduling, final-state observations only) | Baseline: expected to fail |
| Case 2 with per-tick traces and scheduling, timing meta-hypothesis dormant | Does it discover timing on its own after seeing multi-tick motion? |
| Case 2 with the timing meta-hypothesis active | Can it compute the correct delay from movement speeds? |

The offline solver can confirm solvability for each configuration and measure how far the agent's solutions are from optimal.
