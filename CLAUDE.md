# Development folder — not for playing

Tooling that lets an LLM play Order of the Sinking Star. Layout:

- `game/` — engine layer shared by both players: memory reader, key sender, `Session`, run folders (`runs.py`)
- `coding_player/` — MCP server for coding agents; `workspace/` is the folder a coding agent plays in (own CLAUDE.md, .mcp.json, anti-cheat settings)
- `api_player/` — plays through any OpenAI-compatible API (OpenRouter / llama.cpp / Ollama); config in `config.toml`
- `viewer/` — live viewer (`uv run python -m viewer.server`) and `voice_worker.py`
- `tools/` — one-off probes and dumps (run from this folder's root with `uv run python -m tools.<name>`)
- `runs/api/<name>/` and `runs/agent/<name>/` — one folder per playthrough (log, notes, state)

**If you were asked to play the game: stop.** Do not play from here, and do not run
`tools/play.py` or other scripts as a substitute for the game tools. Tell the user, in one line,
to start the player from the viewer instead (it gives a prompt to paste into a coding agent
started in `D:\Games\sinking-star-llm\coding_player\workspace`, which has the game tools and
the anti-cheat settings).
