"""What the benchmark keeps on disk.

    bench/levels/<name>/level.json        a level captured from the screen: its snapshot and how it looks
    bench/levels/<name>/solution.json     a recorded solution (optional)
    bench/experiments/<name>.json         levels x models x variants x runs
    bench/results/<experiment>/trials.jsonl   one line per finished trial (see bench/runner.py)

A trial is an ordinary API run (runs/api/<run>/), so the viewer shows it like any other.
"""
import json
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LEVELS, EXPERIMENTS, RESULTS = (os.path.join(HERE, d) for d in ("levels", "experiments", "results"))


def slug(name):
    return re.sub(r"[^A-Za-z0-9_-]+", "-", (name or "").strip()).strip("-")[:40]


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)


# ---- snapshots <-> json (a snapshot has sets and tuples) ----
def dump_state(state):
    """A Game.snapshot() as plain JSON data."""
    s = dict(state)
    s["solid"] = sorted(list(c) for c in state["solid"])
    s["water"] = sorted(list(c) for c in state["water"])
    s["window"] = list(state["window"]) if state["window"] else None
    s["origin"] = list(state["origin"]) if state.get("origin") else None
    objs = []
    for o in state["objects"]:
        o = dict(o)
        o["pos"] = list(o["pos"])
        if o.get("mirage"):
            o["mirage"] = {k: list(v) for k, v in o["mirage"].items()}
        if o.get("unlock_far"):
            o["unlock_far"] = {str(i): list(p) for i, p in o["unlock_far"].items()}
        objs.append(o)
    s["objects"] = objs
    return s


def load_state(data):
    """Inverse of dump_state: the snapshot as the renderer expects it."""
    s = dict(data)
    s["solid"] = {tuple(c) for c in data["solid"]}
    s["water"] = {tuple(c) for c in data["water"]}
    s["window"] = tuple(data["window"]) if data.get("window") else None
    s["origin"] = tuple(data["origin"]) if data.get("origin") else None
    objs = []
    for o in data["objects"]:
        o = dict(o)
        o["pos"] = tuple(o["pos"])
        if o.get("mirage"):
            o["mirage"] = {k: tuple(v) for k, v in o["mirage"].items()}
        if o.get("unlock_far"):
            o["unlock_far"] = {int(i): tuple(p) for i, p in o["unlock_far"].items()}
        for k in ("holding", "unlocked_by"):
            if o.get(k):
                o[k] = [tuple(x) if isinstance(x, list) else x for x in o[k]]
        objs.append(o)
    s["objects"] = objs
    return s


# ---- levels ----
def level_dir(name):
    return os.path.join(LEVELS, slug(name))


def list_levels():
    out = []
    for name in sorted(os.listdir(LEVELS)) if os.path.isdir(LEVELS) else []:
        info = read_json(os.path.join(LEVELS, name, "level.json"))
        if info:
            sol = read_json(os.path.join(LEVELS, name, "solution.json"))
            out.append({"name": info["name"], "game_level": info["game_level"], "kinds": info["kinds"],
                        "captured": info["captured"], "solution": bool(sol),
                        "solution_verified": bool(sol and sol.get("verified")),
                        "solution_steps": sol.get("steps") if sol else None})
    return out


def read_level(name):
    info = read_json(os.path.join(level_dir(name), "level.json"))
    if info is None:
        raise FileNotFoundError(f"no captured level '{name}'")
    return info


def read_solution(name):
    return read_json(os.path.join(level_dir(name), "solution.json"))


def capture_level(name=None, game=None):
    """Read the level the game is in (coordinates from 0, as the single-level player sees it) and save it.
    The name is the game's own level name unless one is given. Raises if the game is not in a puzzle level."""
    from game.game_state import Game, render
    from game.level_rules import kinds_present
    game = game or Game(zero_origin=True)
    state = game.snapshot()
    if state["open_world"] or state["level"].startswith("menu_"):
        raise RuntimeError(f"the game is in '{state['level']}', not in a puzzle level")
    name = slug(name) or slug(state["level"])
    info = {"name": name, "game_level": state["level"], "captured": time.time(), "kinds": kinds_present(state),
            "screen": render(state), "state": dump_state(state)}
    write_json(os.path.join(level_dir(name), "level.json"), info)
    return {k: v for k, v in info.items() if k not in ("state", "screen")}


# ---- experiments ----
def list_experiments():
    out = []
    for f in sorted(os.listdir(EXPERIMENTS)) if os.path.isdir(EXPERIMENTS) else []:
        if f.endswith(".json"):
            e = read_json(os.path.join(EXPERIMENTS, f))
            if e:
                out.append(e)
    return out


def read_experiment(name):
    e = read_json(os.path.join(EXPERIMENTS, slug(name) + ".json"))
    if e is None:
        raise FileNotFoundError(f"no experiment '{name}'")
    return e


def save_experiment(exp):
    """Check and save an experiment definition; returns it with defaults filled in.

    {name, levels: [bench level names], models: [model ids],
     variants: [{name?, prompt?, rules?, rulebook?, view?, actions?}], runs: N,
     limits?: {max_turns, max_cost_usd}, effort?: "low"...}
    A variant names template files (see game/templates.py); a left-out kind uses the config.toml default."""
    name = slug(exp.get("name")) or auto_name(exp)
    e = {"name": name, "levels": list(exp.get("levels") or []), "models": list(exp.get("models") or []),
         "variants": list(exp.get("variants") or [{}]), "runs": max(1, int(exp.get("runs") or 1)),
         "limits": exp.get("limits") or {}, "effort": exp.get("effort", ""), "created": exp.get("created", time.time())}
    if not e["levels"] or not e["models"]:
        raise ValueError("pick at least one level and one model")
    for lv in e["levels"]:
        read_level(lv)
    from api_player import prompting
    from api_player.llm import load_config
    for v in e["variants"]:
        for kind in v:
            if kind not in ("name", "prompt", "rules", "rulebook", "view", "actions"):
                raise ValueError(f"unknown template kind {kind!r}")
        bad = prompting.problems(prompting.resolve_templates(load_config(), "level", {k: x for k, x in v.items() if k != "name"}), "level")
        if bad:
            raise ValueError(bad)
    write_json(os.path.join(EXPERIMENTS, name + ".json"), e)
    return e


def auto_name(exp):
    """A name for an experiment that was given none: its levels and the time, made unique."""
    base = slug("+".join(exp.get("levels") or ["experiment"]))[:24] + time.strftime("-%m%d-%H%M")
    name, n = base, 1
    while os.path.exists(os.path.join(EXPERIMENTS, name + ".json")):
        n += 1
        name = f"{base}-{n}"
    return name


def variant_name(v):
    """A short readable name for a variant: its own name, else its non-default parts."""
    if v.get("name"):
        return v["name"]
    parts = [f"{k}={v[k]}" for k in ("prompt", "rules", "rulebook", "view", "actions") if v.get(k)]
    return " ".join(parts) or "default"


def results_path(experiment):
    return os.path.join(RESULTS, slug(experiment), "trials.jsonl")


def read_trials(experiment):
    out = []
    try:
        with open(results_path(experiment), encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    break
    except FileNotFoundError:
        pass
    return out


def append_trial(experiment, trial):
    path = results_path(experiment)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(trial) + "\n")
