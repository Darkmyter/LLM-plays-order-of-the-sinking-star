# Development folder — not for playing

Tooling that lets an LLM play Order of the Sinking Star. Layout:

- `game/` — engine layer shared by both players: memory reader, key sender, `Session`, run folders (`runs.py`)
- `coding_player/` — MCP server for coding agents; `workspace/` is the folder a coding agent plays in (own CLAUDE.md, .mcp.json, anti-cheat settings)
- `templates/` — the swappable parts of what a player is told and shown, picked per run in the viewer's start options (`[templates]` in `api_player/config.toml` sets the defaults; the run's meta.json records them): `prompts/game/` and `prompts/level/` (general prompts, `default.md` each), `rules/<name>/` (a rulebook format: `template.toml`, `empty.md` / `prefilled.md` prompts that explain it, `prefilled.toml` the given rulebook; level play can give it read-only or leave it empty for the player to write), `view/` (how the world is shown: map style, lists, lines from you) and `actions/` (what an action returns: view or changes only, action log). Loader `game/templates.py`; the system message is assembled in `api_player/prompting.py`
- `bench/` — benchmark (parked, see docs-v2/12-decisions-benchmark-paused.md): captured levels, recorded solutions, experiments (levels × models × template variants × runs), results and report. CLI `uv run python -m bench.cli`; routes `/bench/...` are served by `api_player/control.py`
- `api_player/` — plays through any OpenAI-compatible API (OpenRouter / llama.cpp / Ollama); config in `config.toml`
- `viewer/` — live viewer (`uv run python -m viewer.server`) and `voice_worker.py`
- `tools/` — one-off probes and dumps (run from this folder's root with `uv run python -m tools.<name>`)
- `runs/api/<name>/` and `runs/agent/<name>/` — one folder per playthrough (log, notes, state)

**If you were asked to play the game: stop.** Do not play from here, and do not run
`tools/play.py` or other scripts as a substitute for the game tools. Tell the user, in one line,
to start the player from the viewer instead (it gives a prompt to paste into a coding agent
started in `D:\Games\sinking-star-llm\coding_player\workspace`, which has the game tools and
the anti-cheat settings).
