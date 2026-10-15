"""Recorded solutions of a benchmark level.

A solution comes from a solved run's log (or pasted moves). The undos and restarts of a real run are cancelled out
to get a clean move list, and `verify` replays it in the game from a restart to prove the level is solvable that way.
That gives a baseline: the fewest moves a player is known to need.
"""
import json
import os
import re
import time

from bench import store
from game import runs
from game.session import Session

MAX_REPEAT = 20   # Session.parse_sequence caps one repeat at this


def units_from_run(run_name):
    """The unit actions of a solved run, undo and restart applied: a list like ['north', 'north', 'activate'].
    Raises if the run never solved its level."""
    path = os.path.join(runs.run_dir("api", run_name), "log.jsonl")
    entries = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    break
                if e.get("tool") == "act":
                    entries.append(e)
    except FileNotFoundError:
        raise FileNotFoundError(f"no log for run '{run_name}'")
    solved = [i for i, e in enumerate(entries) if "LEVEL SOLVED" in str(e.get("result", ""))]
    if not solved:
        raise ValueError(f"run '{run_name}' did not solve its level")
    stack = []
    for e in entries[:solved[-1] + 1]:
        steps = e.get("steps")
        if steps is None:   # an older run: assume every step happened
            steps = [[a, n, "ok"] for a, n in Session.parse_sequence(str((e.get("args") or {}).get("commands", "")))]
        for action, taken, _ in steps:
            for _ in range(taken):
                if action == "restart":
                    stack.clear()
                elif action == "undo":
                    if stack:
                        stack.pop()
                else:
                    stack.append(action)
    return stack


def to_commands(units):
    """['north','north','activate'] -> 'north 2, activate' (repeats capped for the act tool)."""
    out, i = [], 0
    while i < len(units):
        j = i
        while j + 1 < len(units) and units[j + 1] == units[i] and j + 1 - i < MAX_REPEAT:
            j += 1
        n = j - i + 1
        out.append(units[i] + (f" {n}" if n > 1 else ""))
        i = j + 1
    return ", ".join(out)


def parse_commands(text):
    """Pasted moves ('north 3, e2, activate') -> unit actions."""
    return [a for a, n in Session.parse_sequence(text) for _ in range(n)]


def save(level, units, source):
    store.read_level(level)
    sol = {"level": level, "source": source, "units": units, "commands": to_commands(units), "steps": len(units),
           "moves": sum(u in ("north", "south", "east", "west") for u in units), "verified": False,
           "recorded": time.time()}
    store.write_json(os.path.join(store.level_dir(level), "solution.json"), sol)
    return sol


def record_from_run(level, run_name):
    return save(level, units_from_run(run_name), f"run:{run_name}")


def record_from_text(level, text):
    return save(level, parse_commands(text), "pasted")


def verify(level, session=None):
    """Replay the saved solution from a restart. The game must be in the level. Returns the solution with
    `verified` set (and saved)."""
    info, sol = store.read_level(level), store.read_solution(level)
    if sol is None:
        raise FileNotFoundError(f"level '{level}' has no solution")
    session = session or Session(zero_origin=True)
    if session._level() != info["game_level"]:
        raise RuntimeError(f"the game is in '{session._level()}', not in level '{info['game_level']}'")
    session.do("restart")
    result = ""
    for chunk in re.split(r",\s*", sol["commands"]):
        result = session.do_sequence(chunk, stop_on_surprise=False)
        if "LEVEL SOLVED" in result or session._level() != info["game_level"]:
            break
    sol["verified"] = "LEVEL SOLVED" in result
    sol["verified_at"] = time.time()
    store.write_json(os.path.join(store.level_dir(level), "solution.json"), sol)
    return sol
