# Exploration, Planning and Time

## Balancing exploration and planning

The agent's main task is to progress through the game. Exploration exists to support that, not as a goal of its own. Early levels are mostly about learning mechanics quickly; later levels are mostly about planning with known mechanics, with short exploration bursts when something new appears.

The balance is the model's judgment, but explicit modes with clear triggers keep it from drifting into either over-planning on unverified assumptions or aimless experimenting.

### Modes

| Mode | Enter when | Behaviour |
|---|---|---|
| **Explore** | A new object, tile or mechanic is present; or a plan depends on an unverified rule | Run small, cheap, preferably reversible experiments; write rules |
| **Solve** | Every rule the plan relies on is confirmed | Plan the full solution in reasoning, write predictions, execute |
| **Debug** | A prediction did not match the outcome | Identify which rule or assumption was wrong, fix it, then replan |

### Guardrails

- **No long plans on unverified rules.** If a plan of more than a few steps depends on a hypothesis, test the hypothesis first.
- **Prefer reversible experiments.** Before irreversible actions (sinking a stone, losing one off the map), check whether undo or reset exists. If not, think harder before acting.
- **Write a prediction before every non-trivial action.** Mismatches are the main source of learning.
- **Stuck detection.** After N failed attempts or repeated states: list the rules and assumptions the plans depend on, test the weakest, re-read the meta-hypotheses. If still stuck, report and let the navigator move on.
- **Don't declare impossible.** "One resource short" is a signal to look for reuse or a missing rule, not a conclusion.

### Batched plans in Solve mode

In Solve mode the agent may submit several moves at once. The harness executes them one by one and returns to the agent only on a prediction mismatch, a repeated state, or completion. This reduces the number of model calls, and each call reuses the cached prefix.

### Deliberate imperfection in exploration

Humans discover many mechanics by accident: acting impatiently, pushing before things settle, trying something "just to see". An agent that executes only clean, deliberate plans may never stumble on such interactions. A small amount of deliberate variety in Explore mode (acting before everything has settled, trying an object against every other object type) plays the role of human impatience.

## Time awareness

Most levels are effectively turn-based: an action causes some motion, everything settles, the next action follows. A few levels depend on timing: two objects moving at once, an action taken while something is still in motion. Time must be available to the agent without overwhelming it in the many levels where it doesn't matter.

### What the agent observes

| Situation | Tool result |
|---|---|
| Nothing moves after the action beyond the immediate step | The event and a "settled" marker. No frames |
| Objects keep moving | One compact event line per tick until everything stops, then "settled at tN" |
| Ticks where nothing changes | Dropped |
| Long multi-action runs | Events for every tick in which something changed, still frames omitted |

Example:

```
act: t0 push Y left from (34,38); t3 push X left from (33,39)
t1  Y entered water (32,38)
t2  Y slid (31,38)
t3  Y landed on leaf 2 (30,38); leaf 2 + Y drifting left
t4  leaf 2 + Y at (29,38); X entered water (31,39)
...
t7  X passed (26,39) above leaf 2 → leaf 2 + Y pushed down column 26
t10 leaf 2 + Y stopped at (26,34), blocked by land (26,33)
settled at t10
```

### Dormant until needed

- The first time multi-tick motion is observed, the harness flags it once: "objects can keep moving over several ticks." This activates the timing meta-hypothesis without hinting at any specific solution.
- Before that, and in levels where nothing moves over time, the agent is not prompted to think about timing at all.
- Timing solutions are considered when the timing meta-hypothesis is active **and** either motion is visible in the level or sequential plans have been exhausted.

### Acting on time

The agent cannot react in real time, and does not need to. It plans timing on paper and the harness executes it precisely:

```
act([
  {t: 0, action: "push Y left"},
  {t: 3, action: "push X left"}
])
```

- `act(schedule)` executes actions at exact ticks, including walking between pushes if the player needs to move.
- `wait(n)` lets time pass.
- A new action may be issued while objects are still moving. Without this, timing solutions are not just hard to find, they are outside the action space entirely.

### Why the action space matters

The agent can only discover what its action space, observations and world model can represent:

- If actions are only "push X, wait for everything to settle", no timing solution exists to be found.
- If observations show only final states, the agent never sees that moving objects interact mid-motion.
- If its rules describe only before/after states, timing cannot appear in its reasoning.

All three must allow time for timing-based puzzles to be solvable by the agent at all.
