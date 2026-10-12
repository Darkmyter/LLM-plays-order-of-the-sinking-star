"""Per-level stats for a run: time, calls, restarts, tokens and cost spent in each level.

Derived from the run's append-only files, so it works on old runs too and needs nothing from the
player: log.jsonl (every tool call; its result says when a level was entered or left) and, for API
runs, transcript.jsonl (every model call with its usage). A model call, tool call or stretch of
time belongs to the level the player was in when it happened. Coding-agent runs have no token or
cost data (the agent's own client pays for those), only time and calls.
"""
import json
import os
import re

from game import runs

IDLE_CAP = 300  # a gap longer than this (seconds) is a pause or a closed laptop, not play time
ENTERED = re.compile(r"== You entered: (.+?) ==")
LEFT = re.compile(r"you left (?:level (\S+)|the open world)(?: - (LEVEL SOLVED)| \(not solved\))?")
GAME_TOOLS = {"look", "move", "act", "undo", "restart", "action", "select_character", "world_map"}
OPEN_WORLD = "open world"
SRC_FILES = ("log.jsonl", "transcript.jsonl")


def _jsonl(path):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    yield json.loads(line)
                except ValueError:
                    break  # partially written last line
    except FileNotFoundError:
        return


def _level_name(text):
    return OPEN_WORLD if text == "the open world" else text


def _restarts(entry):
    if entry.get("tool") == "restart":
        return 1
    if entry.get("tool") == "act":
        return len(re.findall(r"\brestart\b", str((entry.get("args") or {}).get("commands", ""))))
    return 0


def compute(mode, name):
    rdir = runs.run_dir(mode, name)
    log = list(_jsonl(os.path.join(rdir, "log.jsonl")))
    transcript = [m for m in _jsonl(os.path.join(rdir, "transcript.jsonl"))
                  if m.get("role") == "assistant" and m.get("usage")]

    # Level changes: (time, level, solved-flag of the level that was left)
    changes, solved = [], set()
    for e in log:
        end = e["t"] + e.get("ms", 0) / 1000
        result = str(e.get("result", ""))
        left = LEFT.search(result)
        if left:
            if left.group(2):
                solved.add(left.group(1) or OPEN_WORLD)
        for m in ENTERED.finditer(result):
            changes.append((end, _level_name(m.group(1))))
    changes.sort()

    def level_at(t):
        cur = changes[0][1] if changes else None
        for ct, lv in changes:
            if ct > t:
                break
            cur = lv
        return cur

    levels, order = {}, []

    def entry(lv):
        if lv not in levels:
            levels[lv] = {"name": lv, "visits": 0, "solved": lv in solved, "seconds": 0.0, "calls": 0,
                          "restarts": 0, "turns": 0, "prompt": 0, "cached": 0, "completion": 0, "cost": 0.0}
            order.append(lv)
        return levels[lv]

    prev = None
    for _, lv in changes:
        if lv != prev:
            entry(lv)["visits"] += 1
        prev = lv

    for e in log:
        if e.get("tool") in GAME_TOOLS:
            lv = level_at(e["t"])
            if lv:
                row = entry(lv)
                row["calls"] += 1
                row["restarts"] += _restarts(e)
    for m in transcript:
        lv = level_at(m["t"])
        if lv:
            row, u = entry(lv), m["usage"]
            row["turns"] += 1
            row["prompt"] += u.get("prompt", 0)
            row["cached"] += u.get("cached", 0)
            row["completion"] += u.get("completion", 0)
            row["cost"] += u.get("cost") or 0

    # Active time: gaps between consecutive events, charged to the level at the start of the gap.
    stamps = sorted([e["t"] for e in log] + [e["t"] + e.get("ms", 0) / 1000 for e in log]
                    + [m["t"] for m in transcript])
    idle = 0.0
    for a, b in zip(stamps, stamps[1:]):
        gap = b - a
        if gap > IDLE_CAP:
            idle += gap
            continue
        lv = level_at(a)
        if lv:
            entry(lv)["seconds"] += gap

    rows = [levels[k] for k in order]
    for r in rows:
        r["seconds"] = round(r["seconds"], 1)
        r["cost"] = round(r["cost"], 6)
    total = {k: sum(r[k] for r in rows) for k in ("seconds", "calls", "restarts", "turns", "prompt",
                                                  "cached", "completion", "cost")}
    total["cost"] = round(total["cost"], 6)
    total["idle_seconds"] = round(idle)
    meta = runs.read_meta(mode, name) or {}
    return {"run": runs.slug(name), "mode": mode, "model": meta.get("model", ""),
            "has_tokens": bool(transcript), "total": total, "levels": rows,
            "progress": {"entered": len(rows), "solved": len([r for r in rows if r["solved"]]),
                         "current": changes[-1][1] if changes else None}}


def cached(mode, name):
    """compute(), saved to stats.json in the run folder and reused until the source files change."""
    rdir = runs.run_dir(mode, name)
    path = os.path.join(rdir, "stats.json")
    try:
        newest = max(os.path.getmtime(os.path.join(rdir, f)) for f in SRC_FILES
                     if os.path.isfile(os.path.join(rdir, f)))
        if os.path.getmtime(path) >= newest:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except (OSError, ValueError):
        pass
    stats = compute(mode, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(stats, f)
    return stats


def compare(mode):
    """Stats of every run of a player, for the comparison view."""
    return [cached(mode, r["name"]) for r in runs.list_runs(mode)]
