"""Numbers for one trial, read from its run folder (runs/api/<run>/): log.jsonl, transcript.jsonl, meta.json."""
import json
import os

from game import runs

MOVES = ("north", "south", "east", "west")


def _jsonl(path):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    yield json.loads(line)
                except ValueError:
                    break
    except FileNotFoundError:
        return


def trial_metrics(run_name):
    """Moves, tokens, cost and time of one run. A move is one step north/south/east/west that happened;
    actions count every step that happened except undo and restart, which are counted on their own."""
    rdir = runs.run_dir("api", run_name)
    meta = runs.read_meta("api", run_name) or {}
    m = {"moves": 0, "actions": 0, "undos": 0, "restarts": 0, "act_calls": 0, "looks": 0, "notes": 0,
         "blocked": 0, "surprises": 0}
    for e in _jsonl(os.path.join(rdir, "log.jsonl")):
        tool = e.get("tool")
        if tool == "act":
            m["act_calls"] += 1
            result = str(e.get("result", ""))
            m["blocked"] += result.count("you were stopped after")
            for action, taken, outcome in e.get("steps") or []:
                if action == "undo":
                    m["undos"] += taken
                elif action == "restart":
                    m["restarts"] += taken
                else:
                    m["actions"] += taken
                    if action in MOVES:
                        m["moves"] += taken
                if outcome == "unexpected":
                    m["surprises"] += 1
        elif tool == "look":
            m["looks"] += 1
        elif tool in ("note", "write_note"):
            m["notes"] += 1
    stamps = [t["t"] for t in _jsonl(os.path.join(rdir, "transcript.jsonl")) if "t" in t]
    u = meta.get("usage", {})
    m.update({"turns": meta.get("turns", 0), "prompt": u.get("prompt", 0), "cached": u.get("cached", 0),
              "completion": u.get("completion", 0), "cost": round(u.get("cost", 0) or 0, 6),
              "seconds": round(max(stamps) - min(stamps), 1) if len(stamps) > 1 else 0,
              "status": meta.get("status", "")})
    m["tokens"] = m["prompt"] + m["completion"]
    m["solved"] = m["status"] == "solved"
    return m
