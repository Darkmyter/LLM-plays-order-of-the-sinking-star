# Sinking Star LLM player

Lets an LLM play Order of the Sinking Star by reading the game's memory (read-only) and sending keypresses.

## Run it
```
uv run python -m viewer.server              # viewer: http://127.0.0.1:8765  (pick a player, then a run)
uv run python -m api_player.control         # only for the API player (start/pause/stop from the viewer)
```
- **API player**: set `OPENROUTER_API_KEY` in `.env`; model and limits in `api_player/config.toml`. Start, pause and resume runs from the viewer.
- **Coding agent**: in the viewer pick *Coding agent*, choose or create a run, copy the prompt it shows, and paste it into a coding agent started in `coding_player/workspace/`.
- **Voice** (optional): `uv run --project D:/video-agent/tools/tts/omnivoice python viewer/voice_worker.py --run agent/<name>`

## Layout
- `game/` memory reader, key sender, `Session`, run folders (shared by both players)
- `coding_player/` MCP server + `workspace/` (player instructions, anti-cheat settings)
- `api_player/` OpenAI-compatible loop, token savers (`compact.py`), control server
- `viewer/` viewer server + page, voice worker
- `tools/` one-off probes (`uv run python -m tools.<name>` from this folder)
- `runs/<api|agent>/<name>/` one folder per playthrough: `log.jsonl`, notes, `state/`, `meta.json`
