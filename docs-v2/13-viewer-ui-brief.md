# Brief: redesign the viewer UI

## Goal

The viewer should look good, be easy to read, and show most of the information on one screen with little scrolling. Long texts (system prompt, rulebook, notes pages, transcript messages, the text view) get a button that opens them big, for reading.

## What exists

- `viewer/page.html` (~1,560 lines, plain HTML/CSS/JS, no build step, no libraries), served by `viewer/server.py` on port 8765. It has several screens chosen by the URL:
  - landing: pick the player (`/`);
  - API player: level play or game play (`/?mode=api`);
  - the start screen per play type (`/?mode=api&play=level|game`): start options as cards (world view, action results, rulebook format, given/empty, prompt), a live preview (look(), an action example, rulebook section, system prompt), and the filterable run list;
  - the run viewer (`/?mode=api&run=<name>`): header with run controls, two maps (what the player saw / the game now), objects, messages (transcript and next call), notes, moves and actions;
  - overlays: Debug (current level: UI map, text view, template dropdowns, run-an-action box, rulebook, system prompt), Stats and Compare, Progress map, the coding-agent prompt.
- `viewer/bench.html`: the benchmark page (parked; leave it as is).
- The API player's control server (`api_player/control.py`, port 8766) starts, pauses and stops runs; the page calls it directly.

## Constraints

- Keep it dependency-free (vanilla HTML/CSS/JS in the two files), served by `viewer/server.py`.
- The run viewer draws its maps by parsing the original view text (`parseView`). A run using another world view logs an original-format copy in `screen`; the page uses `e.screen || e.result`. Keep that working.
- Keep every existing feature and route; this is a redesign, not a removal.
- The page is screen-recorded during runs (`game/recorder.py` records the viewer window), so the first screen of the run viewer should hold what is worth watching.
- Check the result in a real browser (headless Edge works: `msedge --headless=new --dump-dom`), and against a running game when possible.

## Wishes

- One consistent look across screens: spacing, type sizes, colours (dark theme today), readable monospace for game text.
- Less scrolling: panels that use the screen width; collapsible sections; sticky headers.
- Long text: an "expand" button on every long block, opening a large readable overlay (wrap, comfortable font size, copy button, Esc to close).
- Easy to scan: status colours, compact badges for templates (view, action results, rulebook), clear numbers (turns, cost, tokens).
