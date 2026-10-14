"""The actions a player may use and how the act tool describes them."""

ACTION_ITEMS = [("north/south/east/west (n/s/e/w)", None), ("undo", None), ("restart", None), ("activate", None),
                ("take_or_drop", "take_or_drop"), ("switch_character", "switch_character"),
                ("select_1..select_9", "select")]


def action_list(disabled=()):
    """The actions a player may use, as one line (what it is told in the prompt and the act tool)."""
    return ", ".join(name for name, key in ACTION_ITEMS if key not in disabled)


def act_tool(disabled=()):
    return {"type": "function", "function": {
        "name": "act",
        "description": "Do game actions in order, e.g. \"north 3, e2, activate, undo\". Items: "
                       + action_list(disabled) + ", each with an optional repeat count. "
                       "Stops at the first step that does not go as asked; shows the view at the end.",
        "parameters": {"type": "object", "properties": {"commands": {"type": "string"}},
                       "required": ["commands"]}}}


def disabled_for(objects):
    """Actions taken away in a single-level run, from the objects in the level: with one hero there is nobody
    to switch to, and take_or_drop only matters when there are gems."""
    if sum(o["kind"] == "Guy" for o in objects) != 1:
        return []
    gems = any(o["kind"] in ("Gem", "Gem_Slot") for o in objects)
    return ["switch_character", "select"] + ([] if gems else ["take_or_drop"])
