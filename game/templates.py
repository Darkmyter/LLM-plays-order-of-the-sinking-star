"""Templates: the swappable parts of what a player is told and shown, in the repo's templates/ folder.

    templates/prompts/game/<name>.md       the general prompt for playing the whole game
    templates/prompts/level/<name>.md      the general prompt for solving one level
    templates/rules/<name>/                a rulebook format (see read_rules)
    templates/view/<name>.toml             how the game world is shown in text (api_player/presentation.py)
    templates/actions/<name>.toml          what an action returns: the view or only the changes, the action log

A run records which variant it used per kind, so it can be resumed, viewed and compared. Swapping a variant is
changing a name in api_player/config.toml ([templates]) or in the viewer's start options.
"""
import os
import re
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(ROOT, "templates")
SCOPES = ("game", "level")
# kind -> (folder, what a template is). "prompts/<scope>" kinds are files, "rules" are folders.
KINDS = {"prompts/game": "file:.md", "prompts/level": "file:.md", "rules": "dir", "view": "file:.toml",
         "actions": "file:.toml"}
RULEBOOK_MODES = ("empty", "prefilled")


def prompt_kind(scope):
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}")
    return "prompts/" + scope


def _check(name):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name or ""):
        raise ValueError(f"bad template name {name!r}")
    return name


def path(kind, name):
    """The file (or, for rules, the folder) of a template."""
    form = KINDS[kind]
    if form == "dir":
        return os.path.join(TEMPLATES, kind, _check(name))
    return os.path.join(TEMPLATES, *kind.split("/"), _check(name) + form.split(":")[1])


def names(kind):
    base = os.path.join(TEMPLATES, *kind.split("/"))
    if not os.path.isdir(base):
        return []
    form = KINDS[kind]
    if form == "dir":
        return sorted(d for d in os.listdir(base) if os.path.isfile(os.path.join(base, d, "template.toml")))
    ext = form.split(":")[1]
    return sorted(f[:-len(ext)] for f in os.listdir(base) if f.endswith(ext))


def exists(kind, name):
    return name in names(kind)


def read_text(kind, name):
    with open(path(kind, name), encoding="utf-8") as f:
        return f.read()


def read_toml(kind, name):
    with open(path(kind, name), "rb") as f:
        return tomllib.load(f)


def _read_in(folder, file, binary=False):
    p = os.path.join(folder, file)
    try:
        with open(p, "rb" if binary else "r", **({} if binary else {"encoding": "utf-8"})) as f:
            return tomllib.load(f) if binary else f.read()
    except FileNotFoundError:
        return {} if binary else ""


def read_rules(name):
    """A rulebook template: {name, description, layout, list_missing, empty, prefilled, entries}.
    The folder holds template.toml (name, description, layout), empty.md and prefilled.md (the prompt that explains
    the rulebook when it starts empty / is given read-only) and prefilled.toml (the entries of the given rulebook)."""
    folder = path("rules", name)
    meta = _read_in(folder, "template.toml", binary=True)
    return {"name": name, "description": meta.get("description", ""), "layout": meta.get("layout", "free"),
            "list_missing": meta.get("list_missing", True),
            "empty": _read_in(folder, "empty.md"), "prefilled": _read_in(folder, "prefilled.md"),
            "entries": _read_in(folder, "prefilled.toml", binary=True).get("entries", {})}


def describe():
    """Every template available, for the viewer: {kind: [{name, description}]}."""
    out = {}
    for kind in KINDS:
        rows = []
        for n in names(kind):
            desc = ""
            if kind == "rules":
                desc = read_rules(n)["description"]
            elif kind in ("view", "actions"):
                desc = read_toml(kind, n).get("description", "")
            rows.append({"name": n, "description": desc})
        out[kind] = rows
    return out
