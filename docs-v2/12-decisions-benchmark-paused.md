# Decision: benchmark paused (2026-10-15)

The `bench/` module is built (captured levels, solutions, experiments, runner, report, `/bench` page) but parked.

Why: running trials needs the live game, and some levels lead directly into other levels. Before experiments are practical the harness must:

- reset a level automatically between trials;
- go back to the level (or the level before) when a trial leaves it, which it cannot do today (it can leave through the menu but cannot walk back in);
- record solutions from the screen, which is not simple either.

The template system stays and is used by the real player directly: prompts per scope, rulebook templates, presentation templates (see the API player's start options).
