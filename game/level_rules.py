"""The prefilled rulebook of a level: what the rulebook template knows about the kinds of object present.

`rulebook_text(state, template)` looks at the objects in a level (a Game.snapshot()) and lays out the entries of
templates/rules/<template>/prefilled.toml for exactly those kinds, in the template's layout. Kinds without an
entry are returned too, so you can see which entries are still missing.

Keys: "Kind" (the game's type name, see game/types.json), "Kind.Variant" for a variant of it (a monster species,
the skipping stone), "Hero.<model>" for one hero (model name lowercased, e.g. "Hero.warrior").
Write only what is verified in the game.
"""
from game import templates
from game.game_state import name_of, nkey


def kinds_present(state):
    """Rule keys for the objects in the level, in a stable order: kinds first, then variants and heroes."""
    keys = []
    for o in state["objects"]:
        if o["kind"] == "Guy":
            key = f"Hero.{(o.get('model') or '').lower()}"
            keys += [k for k in ("Hero", key) if k not in keys]
            continue
        for k in (o["kind"], nkey(o)[1]):
            if k not in keys:
                keys.append(k)
    return sorted(keys, key=lambda k: (k.count("."), k))


def _title(key, shown):
    who = key.split(".")[-1].replace("_", " ")
    return "Hero: " + who.title() if key.startswith("Hero.") else shown.get(key) or who


def _rules(entry):
    """[(id, text)] of an entry: a plain string is one rule without an id."""
    if isinstance(entry, str):
        return [("", entry)]
    return [(r[0], r[1]) for r in entry.get("rules", [])]


def _free(items, missing, template):
    """One bullet per kind: '- **Rock**: text'."""
    lines = [f"- **{title}**: " + " ".join(t for _, t in _rules(entry)) for title, entry in items]
    if missing and template["list_missing"]:
        lines.append("- Also in this level, with no description available: " + ", ".join(m for m in missing) + ".")
    return "\n".join(lines)


def _objects(items, missing, template):
    """One block per kind: OBJECT / properties / rules (R<n>) / open questions (Q<n>)."""
    blocks = []
    for title, entry in items:
        block = [f"OBJECT {title}"]
        if not isinstance(entry, str) and entry.get("properties"):
            block += ["  properties:"] + [f"    {p}" for p in entry["properties"]]
        rules = _rules(entry)
        block += ["  rules:"] + [f"    {i + '  ' if i else ''}{t}" for i, t in rules]
        if not isinstance(entry, str) and entry.get("questions"):
            block += ["  open questions:"] + [f"    {q[0]}  {q[1]}" for q in entry["questions"]]
        blocks.append("\n".join(block))
    if template["list_missing"]:
        blocks += [f"OBJECT {m}\n  no description available" for m in missing]
    return "\n\n".join(blocks)


LAYOUTS = {"free": _free, "objects": _objects}


def rulebook_text(state, template_name):
    """(the prefilled rulebook for the kinds present, the kinds that have no entry)."""
    template = templates.read_rules(template_name)
    entries = template["entries"]
    keys = kinds_present(state)
    shown = {o["kind"]: name_of(o) for o in state["objects"] if not o.get("variant")}   # e.g. Door -> Goal Pad
    items, missing = [], []
    for k in keys:
        if k in entries:
            items.append((_title(k, shown), entries[k]))
        elif k == "Hero":
            continue
        elif "." in k or not any(q.startswith(k + ".") and q in entries for q in keys):
            missing.append((k.replace("Hero.", "hero ") if k.startswith("Hero.") else k.split(".")[-1]).replace("_", " "))
    return LAYOUTS[template["layout"]](items, missing, template), missing
