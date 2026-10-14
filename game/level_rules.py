"""How things in a level work, for the single-level mode: one entry per kind of object.

`rules_text(state)` looks at the objects present in a level (a Game.snapshot()) and writes the part
of the player's prompt that explains exactly those kinds. Kinds without an entry are returned too, so
the mode can tell you which entries are still missing.

Keys: "Kind" (the game's type name, see game/types.json), "Kind.Variant" for a variant of it (a
monster species), "Hero.<model>" for one hero (model name lowercased, e.g. "Hero.warrior").
A variant or hero entry is added to the entry of its kind. Write only what is verified in the game.
"""
from game.game_state import name_of, nkey

RULES = {
    "Rock": "Push it by walking into it. It moves one tile if the tile behind it is free. It does not move "
            "if another rock is behind it. A rock pushed into water becomes floor you can walk on.",
    "Sign": "Blocks you. To read it, stand next to it and face it; the text is shown once and kept in your journal.",
    "Voice_Log": "A recording. Stand on its tile and activate to hear it; the text is kept in your journal.",
    "Mirror": "Teleports you by reflection. It faces a diagonal direction (north-east, north-west, south-east or "
              "south-west), which the view reports, and it can only be used from the two sides it faces: a "
              "north-east mirror from the north and the east, a north-west one from the north and the west, a "
              "south-east one from the south and the east, a south-west one from the south and the west. To use it, "
              "stand exactly in line with it on one of those sides (same column or same row as the mirror), face it "
              "and activate. You land the same number of tiles away from the mirror as you stood, on its other "
              "side. For example, a north-east mirror: standing 3 tiles north of it puts you 3 tiles east of it, and "
              "standing 3 tiles east of it puts you 3 tiles north of it. "
              "It does not work if an object is on the line of the reflection before the tile where you would land. "
              "When you can use it, the game shows a ghost of where you would land and the view reports that tile. "
              "A mirror can be pushed like a rock.",
    "Door": "A special tile you stand on; its state is active or inactive. "
            "The level ends when all of them are active.",
    "Npc": "A person, there for the story only. It plays no part in the level's mechanics; you can ignore it.",
    "Hero.trader": "Pushes objects, but only one at a time (a rock or a mirror, by walking into it), and can "
                   "teleport through a mirror.",
    "Hero.warrior": "Can push multiple objects at once, in a row, by walking into them.",
    "Hero.thief": "Can only pull objects; it cannot push.",
    "Hero.wizard": "Swaps places with a rock, a hero or a monster it faces. It needs a clear line of sight to it: "
                   "for example, facing north with a rock in clear sight to the east, turning east swaps the "
                   "wizard and the rock.",
    "Hero.priestess": "Protects any other hero on an adjacent tile (left, right, up or down) from monsters' attacks.",
    "Freezer": "Blocks you and encases whatever stands on its tile. It melts away once whatever it is unlocked by "
               "has been triggered; the view says what its arrow points to.",
    "Monster.Goblin": "Attacks a hero or another monster standing on an adjacent tile (up, down, left or right).",
    "Monster.Dragon": "Breathes fire in a straight line in the direction it faces when a hero or a monster stands "
                      "in front of it.",
}


def _name(o):
    return name_of(o)


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


def rules_text(state):
    """(markdown for the prompt, keys present that have no entry)."""
    keys = kinds_present(state)
    lines, missing = [], []
    shown = {o["kind"]: name_of(o) for o in state["objects"] if not o.get("variant")}   # e.g. Door -> Goal Pad
    for k in keys:
        text = RULES.get(k)
        if text:
            who = k.split(".")[-1].replace("_", " ")
            lines.append(f"- **{'Hero: ' + who.title() if k.startswith('Hero.') else shown.get(k) or who}**: {text}")
        elif k == "Hero":
            continue
        elif "." in k or not any(q.startswith(k + ".") and q in RULES for q in keys):
            missing.append(k.replace("Hero.", "hero ") if k.startswith("Hero.") else k.split(".")[-1])
    if missing:
        lines.append("- Also in this level, with no description available: "
                     + ", ".join(m.replace("_", " ") for m in missing) + ".")
    return "\n".join(lines), missing
