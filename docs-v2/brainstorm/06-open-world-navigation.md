# Open-World Navigation

The open world is large, has multiple routes, and is progressed by pushing as far as possible in one direction, getting blocked, going elsewhere to unlock things, and coming back. The agent must track what it has explored, where it can return to, and how it got where it is, without getting lost.

There are no clear exits. Areas are joined by passages in walls and by crossings built with objects and mechanics. The map is therefore modelled as **areas and crossings**.

## The graph

### Nodes: walkable areas

An area is a connected group of walkable tiles. The harness can compute these automatically (connected components), because a human sees "that's a separate island" at a glance. The agent names each area so it can reason about it:

```
AREA "starting beach"     tiles: 64   visited   first entered: from west edge
AREA "stone island"       tiles: 31   visited   contains: level L4 (solved)
AREA "far islet"          tiles: 12   seen, not visited
```

Area fields:

| Field | Purpose |
|---|---|
| `name` | Agent-chosen, used in logs and plans |
| `status` | `seen`, `visited`, `explored` (all edges checked), `finished` (nothing left) |
| `entered_from` | How the player first got here, for the sense of direction and the way back |
| `levels` | Sub-levels inside, with status |
| `unseen_edges` | Sides that run off the visible screen |
| `notes` | Anything the agent wants to remember |

### Edges: crossings

```
CROSSING starting beach ↔ stone island
  type: built bridge (sunk stones, column 50)
  status: open        permanence: permanent
CROSSING stone island ↔ west cliffs
  type: passage in wall at (36,32)
  status: open        permanence: permanent
CROSSING stone island ↔ far islet
  type: water gap, about 9 tiles
  status: candidate   permanence: n/a
  notes: no stones nearby; may need a mechanic not yet seen
```

| Field | Values |
|---|---|
| `type` | passage, built bridge, leaf/raft, mechanic-dependent, unknown |
| `status` | `open`, `candidate` (looks crossable, unsolved), `blocked` (known reason), `closed` (was open, no longer) |
| `permanence` | `permanent` (sunk stones), `temporary` (a leaf that may drift), `unknown` |
| `requires` | What seems needed: a mechanic, an object, a technique |
| `evidence` | How the agent knows (crossed it, saw it, inferred it) |

Permanence matters. A crossing that relied on a leaf may be gone when the agent returns. Recording it avoids planning a return trip over a bridge that no longer exists.

## The frontier

The frontier is the set of places worth going next:

- **Candidate crossings**, each with what they might need.
- **Unseen edges** of visited areas.
- **Stuck levels** marked "revisit later", with their stuck reports.

When a level agent reports a **new technique or rule**, the navigator re-checks the frontier for candidates that it might unlock. This is how "I couldn't cross here earlier, but now I know the leaf trick" happens.

## Journal: the sense of progress

A short chronological log of milestones, kept in the navigator's context:

```
J1  started on starting beach, explored west → dead end
J2  solved L1 (stone bridge) → reached stone island
J3  learned leaf ride + drift (R7, R8)
J4  L4 solved with double-duty technique; far islet still a candidate
J5  passage at (36,32) → west cliffs
```

The journal is what gives the agent the narrative of the game: it came from the left, progressed to the right, and knows which places it left unfinished behind it.

## Navigation actions

- The navigator chooses a **destination** (an area, a level entrance, a crossing).
- The harness computes the route through **open** crossings and walks it (`walk_to` / `travel_to(area)`). This is motor control, not reasoning.
- If the route needs a temporary crossing whose state is unknown, the harness reports that instead of assuming it.

## Navigator decision loop

1. Is the current area finished? (All edges explored, all levels solved or marked.)
2. If not, continue here: nearest unseen edge or unsolved level.
3. If yes, pick from the frontier, preferring:
   - candidates whose `requires` matches a recently learned technique;
   - stuck levels where new techniques may apply;
   - the nearest unseen edge.
4. Write a one-line intention in the journal ("going back to far islet: new drift technique may cross the gap").

## Distinguishing sections of the world

Large regions with a distinct look or theme (beach, reef, cliffs) can be grouped as **regions** containing several areas. Regions are labels for the agent's orientation, not separate structures. The graph stays one graph of areas and crossings; regions just make the summary readable:

```
REGION Shallows: starting beach, stone island, far islet
REGION Cliffs:   west cliffs, ledge path
```

## Context for the navigator

- Full detail for the current area and its direct crossings.
- One line per other area, grouped by region.
- The frontier list.
- The tail of the journal (older entries folded).
- Techniques list.

Cache the stable parts: the system prompt, tools, techniques and the summary of other areas change rarely and go first. The current area's details, frontier and journal tail go after them. The world summary is rebuilt only when the player enters a new area or a crossing changes status.
