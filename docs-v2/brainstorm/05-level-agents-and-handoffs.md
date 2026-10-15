# Level Agents and Handoffs

## Two roles

| Agent | Scope | Sees |
|---|---|---|
| **Navigator** | The open world: where to go next, which area seems finished, which crossing to try | World graph, journal, frontier, techniques |
| **Level agent** | One sub-level, from entry to exit | Level state, relevant rules, techniques, meta-hypotheses, entry brief |

An optional **curator** step runs between levels to maintain the rulebook (see `01-rulebook-and-knowledge.md`).

Do not split further. Every additional agent adds a handoff where information can be lost.

## Fresh agent per level

When a new level starts, a **clean-sheet** level agent is created with no messages from the open world or from previous levels.

Benefits:

- No leftover noise from navigation or earlier puzzles.
- No stale assumptions carried silently in conversation history.
- Bounded context size per level.
- Failures in one level do not pollute the next.

The cost is that everything the agent knows must come through the handoff. That makes the handoff the most important piece of this design.

## Entry package (what the level agent receives)

1. **Rules** for every object type present in the level, each with status and evidence count. Weak rules are clearly marked.
2. **Techniques**: the full list of strategy lessons. These transfer between levels better than object rules.
3. **Meta-hypotheses**: active ones, plus dormant ones with their activation conditions.
4. **Open ledger entries** relevant to the objects present.
5. **Entry brief**, written by the navigator:
   - how the player reached this level and from which area;
   - what the goal appears to be (checkpoint, exit, crossing);
   - anything noticed from outside (objects seen, suspected mechanics);
   - previous attempts at this level, if any (see retries below).
6. **Initial level state** in the standard representation.

The entry package forms the level agent's **cached prefix**. It is assembled once, rendered deterministically, and not modified during the level. Rule updates discovered during the level are kept in the volatile part of the context and only merged into the rulebook (and into future prefixes) through the exit report and curation.

## Exit report (what the level agent returns)

```
status: solved | stuck | abandoned
summary: 2–4 sentences on what happened
solution: compact action sequence (if solved)
rule_updates:
  - R9 new: stone riding a leaf can be pushed again   evidence: #15
  - R7 confirmed again                                evidence: #12
contradictions:
  - none
new_techniques:
  - "double duty: a stone can ride a leaf, then be pushed off to sink"
open_questions:
  - can the player stand on a leaf?
if stuck:
  tried: the approaches attempted and why each failed
  suspects: rules or assumptions that may be wrong
  ideas: untested directions
```

The report goes to the curator, which updates the persistent stores, and a one-line version goes into the navigator's journal.

## Retries with fresh eyes

If a level agent gets stuck, start a **new** level agent with the stuck report in its entry brief. It receives the facts (what was tried, what failed) without the failed chain of reasoning. Humans benefit from the same thing: coming back to a puzzle later.

Guidelines:

- Limit retries per visit (for example two). After that, the navigator marks the level as "stuck, revisit later" and moves on. New techniques learned elsewhere may unlock it.
- When the navigator later returns, the entry brief includes the stuck reports plus any techniques learned since.

## Risk: wrong rules carried forward

Because the level agent starts fresh, a wrong rule in the rulebook is not questioned by conversation history. Protections:

- Rules carry status and evidence; weak rules are visibly weak.
- The level agent is explicitly allowed to doubt any rule and must report contradictions.
- When stuck, the agent's first step is to list which rules and assumptions its plans depend on and test the weakest ones.
- The curator keeps contradicted rules visible with the contradicting evidence, rather than deleting them.

## Navigator handoff in the other direction

When a level ends, the navigator receives only:

- the one-line journal entry;
- whether a crossing or area was unlocked;
- any new technique that might apply to frontier crossings.

It does not receive the level's message history.
