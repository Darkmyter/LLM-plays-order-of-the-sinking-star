"""Run folders: one playthrough = one folder under runs/<mode>/<name>/.

mode is "api" (api_player) or "agent" (a coding agent through coding_player). Both modes
keep meta.json, log.jsonl and notes in the folder, so the viewer treats them alike.
"""
import json
import os
import re
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODES = ("api", "agent")


def mode_dir(mode):
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}")
    return os.path.join(ROOT, "runs", mode)


def slug(name):
    return re.sub(r"[^A-Za-z0-9_-]+", "-", (name or "").strip()).strip("-")[:40]


def run_dir(mode, name):
    return os.path.join(mode_dir(mode), slug(name))


def exists(mode, name):
    return bool(slug(name)) and os.path.isfile(os.path.join(run_dir(mode, name), "meta.json"))


def read_meta(mode, name):
    try:
        with open(os.path.join(run_dir(mode, name), "meta.json"), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return None


def write_meta(mode, name, **fields):
    """Create or update meta.json (name, mode, created, updated + whatever is passed)."""
    d = run_dir(mode, name)
    os.makedirs(d, exist_ok=True)
    meta = read_meta(mode, name) or {"name": slug(name), "mode": mode, "created": time.time()}
    meta.update(fields)
    meta["updated"] = time.time()
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f)
    return meta


def create(mode, name=None):
    """Make a new run folder; returns its name. Fails if the name is taken."""
    name = slug(name) or time.strftime("run-%Y%m%d-%H%M%S")
    if exists(mode, name):
        raise FileExistsError(f"run '{name}' already exists")
    write_meta(mode, name)
    return name


def list_runs(mode):
    base = mode_dir(mode)
    out = []
    for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        meta = read_meta(mode, name)
        if meta:
            out.append(meta)
    return sorted(out, key=lambda m: m.get("updated", 0), reverse=True)
