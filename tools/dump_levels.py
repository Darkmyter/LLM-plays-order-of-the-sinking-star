"""Dump every level entrance and area of the open world to game/levels.json (for the progress map).

Read-only: reads the running game's memory, presses no keys. The game must be in the open world
(the overworld holds all Level_Entry and Area_Pin entities, discovered or not).

    uv run python -m tools.dump_levels
"""
import json
import os
import struct
import sys

from game.game_state import OPEN_WORLD_LEVELS, POSITION, Game, localized

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "game", "levels.json")


def entities(game, mgr, buckets, kind):
    size, F = game.types.size(kind), game.types.fields(kind)
    for a in game.entities_of(mgr, buckets.get(kind, 0)) if kind in buckets else []:
        b = game.p.read(a, size)
        yield b, struct.unpack_from("<3f", b, POSITION), F


def main():
    game = Game()
    mgr = game.current_manager()
    level = game.level_name(mgr)
    if level not in OPEN_WORLD_LEVELS:
        sys.exit(f"The game is in '{level}'. Go to the open world (leave the level) and run this again.")
    buckets = game.buckets(mgr, level)

    areas = []
    for b, p, F in entities(game, mgr, buckets, "Area_Pin"):
        key = game.decode_field(b, *F["local_area_name"])
        areas.append({"key": key, "name": localized(key) or key, "pos": [round(v, 1) for v in p]})

    levels = []
    for b, p, F in entities(game, mgr, buckets, "Level_Entry"):
        area = min(areas, key=lambda q: (q["pos"][0] - p[0]) ** 2 + (q["pos"][1] - p[1]) ** 2
                   + (2 * (q["pos"][2] - p[2])) ** 2) if areas else None
        levels.append({"name": game.decode_field(b, *F["level_name"]), "area": area and area["key"],
                       "pos": [round(v, 1) for v in p],
                       "locked_now": (game.decode_field(b, *F["enabled_t_target"]) or 0) < 0.5,
                       "solved_now": (game.decode_field(b, *F["solved_t_target"]) or 0) > 0.5})
    levels.sort(key=lambda l: (l["area"] or "", l["pos"][1], l["pos"][0]))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"areas": areas, "levels": levels}, f, indent=1)
    print(f"{len(areas)} areas, {len(levels)} levels -> {os.path.normpath(OUT)}")
    for a in areas:
        print(f"  {a['name']}: {sum(1 for l in levels if l['area'] == a['key'])} levels")


if __name__ == "__main__":
    main()
