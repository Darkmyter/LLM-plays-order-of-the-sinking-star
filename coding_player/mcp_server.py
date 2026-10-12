"""MCP server exposing Order of the Sinking Star as a text game (coding-agent mode).

Reads game memory (read-only) and presses keys in the game window. Every session is bound to
one run (runs/agent/<name>/) with join_run: that is where its log, notes, commentary and
per-level state live, and what the viewer shows.
"""
import functools
import inspect
import json
import os
import re
import threading
import time

from mcp.server.mcpserver import MCPServer

from game import runs
from game.game_state import world_map as game_world_map
from game.session import Session

MODE = "agent"

INSTRUCTIONS = """\
Text interface to the puzzle game "Order of the Sinking Star". Every action really happens
in the game window. You see only what is on screen; the rules are not given to you.
Follow CLAUDE.md for how to play and how to keep notes.
Call join_run(name) first, with the run name from your instructions. Everything you do is
recorded in that run, and a run that already exists is resumed with its notes.
"""

mcp = MCPServer("sinking-star", instructions=INSTRUCTIONS)
_session = None
_lock = threading.Lock()

# The run this server is bound to (set by join_run). Every tool call is appended to its
# log.jsonl so the viewer can show the human what the model sees.
_run = None
_log_lock = threading.Lock()
NEED_RUN = "error: call join_run(name) first (the run name is in your instructions)"


def run_dir():
    return runs.run_dir(MODE, _run)


def _log(entry):
    with _log_lock:
        with open(os.path.join(run_dir(), "log.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        meta = runs.read_meta(MODE, _run) or {}
        runs.write_meta(MODE, _run, actions=meta.get("actions", 0) + 1)


def tool():
    """@mcp.tool() that also records the call and its result in the run's log."""
    def register(fn):
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if _run is None and fn.__name__ != "join_run":
                return NEED_RUN
            t0 = time.time()
            result = fn(*args, **kwargs)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            if _run is not None:
                _log({"t": t0, "ms": round((time.time() - t0) * 1000), "tool": fn.__name__,
                      "args": dict(bound.arguments), "result": result})
            return result
        return mcp.tool()(wrapper)
    return register


def session():
    global _session
    if _session is None:
        _session = Session(os.path.join(run_dir(), "state"))
    return _session


def run(fn):
    global _session
    with _lock:
        try:
            return fn(session())
        except Exception as e:  # game closed/restarted -> reconnect next call
            _session = None
            return f"error: {e} (is the game running and in a level?)"


# ---------- run ----------

@tool()
def join_run(name: str) -> str:
    """Bind this session to a run (a playthrough). Call it first, with the run name from your
    instructions. A new run starts with empty notes; a run that already exists is resumed:
    read its notes (list_notes, then read_note progress) before acting."""
    global _run, _session
    name = runs.slug(name)
    if not name:
        return "error: give a run name"
    if _run is not None:
        return (f"error: already in run '{_run}'. One session is bound to one run; "
                "start a new session to join another.")
    resumed = runs.exists(MODE, name)
    if not resumed:
        runs.create(MODE, name)
    _run, _session = name, None
    os.makedirs(os.path.join(run_dir(), "notes"), exist_ok=True)
    if resumed:
        return (f"Resumed run '{name}'. Your notes survive: list_notes(), read the progress "
                "note first, then look() and carry on.")
    return f"Started new run '{name}' (empty notes). Begin with look()."


# ---------- commentary ----------
# Lines the player says out loud; voice_worker.py speaks them and the viewer shows them.
_speech_lock = threading.Lock()


@tool()
def say(text: str) -> str:
    """Think out loud, like a player commenting on their own playthrough: what you notice,
    what you suspect, what you are about to try and why, surprises, frustration, the moment
    it clicks. It is shown to the human watching and read aloud; it does not affect the game.
    Keep each one short and spoken: one to three sentences."""
    text = " ".join(text.split())
    if not text:
        return "nothing to say"
    if len(text) > 400:
        text = text[:400].rsplit(" ", 1)[0] + "..."
    speech_log = os.path.join(run_dir(), "speech.jsonl")
    with _speech_lock:
        try:
            with open(speech_log, encoding="utf-8") as f:
                n = sum(1 for _ in f)
        except FileNotFoundError:
            n = 0
        with open(speech_log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": n, "t": time.time(), "text": text}) + "\n")
    return "said"


# ---------- playing ----------

@tool()
def look() -> str:
    """Show the current view: map, objects, and any dialogue that just played."""
    return run(lambda s: s.look())


@tool()
def move(direction: str, steps: int = 1) -> str:
    """Walk one grid step per `steps` toward direction: north, south, east or west.
    Each step is confirmed before the next key is sent; walking stops at the first step that
    does not move you exactly one tile, and the report says why (blocked by X, only turned,
    no response). Walking into things may push or interact with them."""
    direction = direction.lower().strip()
    if direction not in ("north", "south", "east", "west"):
        return "direction must be north, south, east or west"
    return run(lambda s: s.do(direction, max(1, min(steps, 20))))


@tool()
def act(commands: str, stop_on_surprise: bool = True) -> str:
    """Do several actions in one call, in order, e.g. "north 3, east 2, activate, undo".
    Each item is a direction (north/south/east/west, or n/s/e/w) or an action
    (undo, restart, activate, take_or_drop, switch_character, select_1..select_9),
    optionally followed by a repeat count. Reports what changed after each item, then
    shows the view once at the end. Stops early if you enter or leave a level and, unless
    stop_on_surprise is false, as soon as a step does not do exactly what was asked (blocked,
    only turned, no response) - the remaining steps are listed as skipped."""
    return run(lambda s: s.do_sequence(commands, stop_on_surprise))


@tool()
def undo(steps: int = 1) -> str:
    """Undo your last move(s). Free and unlimited."""
    return run(lambda s: s.do("undo", max(1, min(steps, 50))))


@tool()
def restart() -> str:
    """Reset the current level to its starting state."""
    return run(lambda s: s.do("restart"))


@tool()
def action(name: str) -> str:
    """Press a game action button. name is one of:
    - activate: use/interact
    - take_or_drop: pick up / put down; also enters level entrances in the open world
    - switch_character: cycle to the next hero (when you have several)
    """
    name = name.lower().strip()
    if name not in ("activate", "take_or_drop", "switch_character"):
        return "name must be activate, take_or_drop or switch_character"
    return run(lambda s: s.do(name))


@tool()
def select_character(number: int) -> str:
    """Select a hero by its number. Heroes are numbered by their own select key (the map and
    the Heroes line show it, e.g. '3=Hero 3 (Wizard)'), so the numbers are not always 1, 2, 3."""
    if not 1 <= number <= 9:
        return "number must be 1-9"
    return run(lambda s: s.do(f"select_{number}"))


@tool()
def world_map() -> str:
    """The world map (like the in-game TAB map): areas you have discovered, where they are
    relative to you, how many of their levels are solved, and teleporters you have found.
    Only works in the open world."""
    return run(lambda s: game_world_map(s.game))


# ---------- notes ----------

NOTE_NAME = re.compile(r"[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*\.md")


def _note_path(name):
    name = name.strip().replace("\\", "/")
    if not name.endswith(".md"):
        name += ".md"
    if not NOTE_NAME.fullmatch(name):
        raise ValueError("note names may only use letters, digits, - and _, with / for folders")
    return os.path.join(run_dir(), "notes", *name.split("/")), name


@tool()
def list_notes() -> str:
    """List your note files (in notes/) with their sizes and last-modified times."""
    rows = []
    notes_dir = os.path.join(run_dir(), "notes")
    for root, _, files in os.walk(notes_dir):
        for f in files:
            p = os.path.join(root, f)
            rel = os.path.relpath(p, notes_dir).replace(os.sep, "/")
            st = os.stat(p)
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
            rows.append(f"{rel}  ({st.st_size} bytes, modified {when})")
    return "\n".join(sorted(rows)) or "(no notes yet)"


@tool()
def read_note(name: str) -> str:
    """Read one note, e.g. read_note("progress") or read_note("levels/heroes")."""
    try:
        path, name = _note_path(name)
        with open(path, encoding="utf-8") as f:
            return f.read() or "(empty)"
    except FileNotFoundError:
        return f"(no note named {name})"
    except ValueError as e:
        return f"error: {e}"


@tool()
def write_note(name: str, content: str) -> str:
    """Create or fully replace a note (markdown). Folders are created as needed."""
    try:
        path, name = _note_path(name)
    except ValueError as e:
        return f"error: {e}"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"saved {name} ({len(content)} chars)"


@tool()
def append_note(name: str, text: str) -> str:
    """Append text to the end of a note (creates it if missing). Good for journals/logs."""
    try:
        path, name = _note_path(name)
    except ValueError as e:
        return f"error: {e}"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(text if text.endswith("\n") else text + "\n")
    return f"appended to {name}"


if __name__ == "__main__":
    mcp.run()
