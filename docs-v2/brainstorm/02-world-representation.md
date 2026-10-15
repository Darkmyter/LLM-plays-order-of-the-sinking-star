# World Representation

Most LLM errors in grid games come from **misreading positions**, not from bad reasoning. An LLM does not see a grid; it reads a stream of tokens and has to count characters to locate anything. Every count is a chance for a silent off-by-one error. The representation must remove the need to count.

## Problems with a plain ASCII grid

Observed while working from hand-made grids in this project:

| Problem | Effect |
|---|---|
| Column numbers split across two header lines ("4" over "4") | The model must align characters vertically, which it cannot do reliably |
| Positions found by counting cells in a row | Off-by-one errors (the target was reported at the leaf's column instead of the checkpoint's) |
| One symbol used for two things (`R` for stones and red rocks) | Wrong assumptions about what is pushable |
| Obstacles drawn with the land symbol (brown rocks as `.`) | Unclear what is walkable vs merely blocking |
| No legend | Symbols must be guessed from context |
| One character per cell | Cannot express stacking (stone on leaf, player on leaf) |
| Large uncropped areas | Token cost and attention spent on irrelevant parts |

## Recommended format: terrain grid + object list + facts

### Terrain grid (static layout only)

```
LEGEND: .=land  ~=water  #=blocker (not walkable, stops sliding)
COORDS: x increases right, y increases up. Row label starts each line.

TERRAIN (x 40..52, y 29..38)
y38: ~ ~ . . . . . . . . . ~ ~
y37: ~ . . . . ~ . . . . . . .
y36: ~ . . ~ ~ ~ ~ ~ . . . . .
y35: ~ ~ ~ ~ ~ ~ ~ ~ ~ . . . ~
y34: ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ . ~ ~
y33: ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
y32: ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ # ~
y31: ~ ~ ~ . . . ~ ~ ~ ~ ~ ~ #
y30: ~ ~ ~ . . . . ~ ~ . . ~ ~
y29: ~ ~ . . . . . . . . . . ~
```

Rules for the grid:

- **Row label at the start of every line**, so a row is found by its label, not by counting lines.
- **Column range stated once in the header** (`x 40..52`); no multi-line column numbering.
- **A fixed legend**, identical in every observation for the whole game. New tile types are added to the legend, never redefined.
- **Distinct symbols** for land, water and each kind of obstacle.
- **Cropped** to the area relevant to the current level or the player's surroundings.

The grid gives the overall shape (where the islands and gaps are). The agent should never need it to determine an exact position.

### Object list (exact positions and state)

```
OBJECTS
player     (49,38)
stone A    (43,38)  pushable
stone B    (47,37)  pushable
stone C    (50,36)  pushable
stone D    (50,30)  pushable, on far island
leaf 1     (44,34)  carrying: nothing
checkpoint (50,29)
```

- Every object that can move or matters to a goal is listed with exact coordinates.
- Stacking is expressed as a property (`leaf 1 (50,32) carrying: stone B`).
- Objects keep **stable names** for the whole level (stone A stays stone A after it moves or sinks), so the action log and rules can refer to them.
- Removed objects are listed as gone (`stone C: sunk at (50,33), now terrain`), at least in the action log.

### Facts the harness may add (perception only)

Facts a human gets **at a glance** may be included; consequences a human gets **by thinking** may not. See `03-harness-tools-and-aid-boundary.md`.

Allowed:

```
FACTS
player reachable area: "stone island" (walkable, 31 tiles)
column 50 from (50,34) down: water, water, water, stone D on land
leaf 1 neighbours: N water, S water, E water, W water
```

Not allowed:

```
stone C pushed down → sinks at (50,31)        ← this is reasoning
leaf 1 can be moved to (50,32)                 ← this is planning
```

## Coordinates

- Use **global coordinates** in the open world, so a position means the same thing everywhere.
- Prefix positions with an **area name** in summaries and logs when ambiguity is possible (`stone island (36,32)`).
- State the axis directions explicitly in the legend (which way y increases), because hand-made and engine coordinates often disagree.

## Images

Screenshots are closest to what a human sees, but models misjudge grid positions from images. In this project, the first attempt at reading the screenshot was a column off. Use images as a supplement for things text cannot capture (visual hints, new unknown objects), not as the source of truth for positions.

## Pure JSON

JSON is easy to generate and parse but harder for a model to picture spatially. If used, include the text grid alongside it. A reasonable split is JSON for tool results consumed by code, text grid + object list for anything the model reads.

## Terrain overlays (cache-friendly)

Terrain is static within a level, so the grid is rendered once at level start and kept in the cached part of the prompt. When terrain changes during the level (a stone sinks and becomes land), the change is listed in the current state as an overlay instead of redrawing the grid:

```
TERRAIN CHANGES
(50,31) now land (stone B sank, #15)
(50,33) now land (stone C sank, #13)
```

The grid is redrawn with the changes applied only at the next compaction point or level start. Rendering must be deterministic so the same state always produces byte-identical text.

## Current state vs changes

The model should see **one full world state at a time**: the current one. After each action, tool results report only what changed (events), and the full current state in the context is replaced. See `04-context-and-memory.md`.
