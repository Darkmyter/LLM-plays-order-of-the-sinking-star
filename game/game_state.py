"""Read the current puzzle state of the running game as plain data. Read-only.

    uv run python game_state.py          # what the model sees
    uv run python game_state.py --full   # debug: every decoded field
"""
import json
import math
import os
import re
import struct
import sys
import time

from game.dialogue import bark_text, localized, sign_text
from game.memreader import Process

HERE = os.path.dirname(os.path.abspath(__file__))
EXE_IMAGE_BASE = 0x140000000

# Globals (exe VAs) observed to point at the current level's Entity_Manager.
# The same manager is reused for every level; its first field is the level name.
CURRENT_MANAGER_GLOBALS = [0x140802328, 0x140B64548]
MANAGER_SIZE = 0x7F80
MANAGER_LEVEL_NAME = 0x0
# Camera state inside the manager (found by scanning memory; checked in the intro):
#   0x3D90 current look-at (x, y), 0x3D98 current camera position (x, y, z),
#   0x3DA4 target camera position, 0x3DE0 current screen ("room") centre,
#   0x3DE8 room rectangle (x0, y0, x1, y1).
MANAGER_CAMERA = 0x3D90
# Visible ground half-extents per unit of camera height (measured from a screenshot:
# a camera 14.5 above the floor shows about 21 x 11 tiles).
VIEW_HALF_X_PER_HEIGHT, VIEW_HALF_Y_PER_HEIGHT = 0.70, 0.36

# Entity field offsets (see gameplay_types.md).
POSITION, ORIENTATION, ENTITY_FLAGS, ENTITY_NAME = 0x00, 0x18, 0x28, 0x30
STATUS_FLAGS, VISUAL_POSITION, ENTITY_ID, ENTITY_TYPE = 0x5C, 0xA0, 0x100, 0x108
ENTITY_SIZE = 0x330

EF_INVISIBLE = 1
EF_IN_EXISTENCE_GROUP, EF_CURRENTLY_EXISTS = 1 << 25, 1 << 26
ST_DEAD, ST_FALLING, ST_ACTIVE, ST_ON_EXIT = 1, 2, 4, 16

OPEN_WORLD_LEVELS = {"overworld"}
# Select keys from data/Gameplay.keymap (SelectWarrior = 1, ...), by the hero's model name.
SELECT_KEY = {"warrior": 1, "thief": 2, "wizard": 3, "priestess": 4, "bard": 5, "druid": 6,
              "sailor": 7, "gemsman": 8, "trader": 9}
OPEN_WORLD_VIEW_RADIUS = 12
LARGE_LEVEL = 30  # levels wider/taller than this are shown as a window around the hero
# The world has separate areas stacked vertically (e.g. heights -21, 0, 33);
# only show things near the hero's own height.
LAYER_BELOW, LAYER_ABOVE = 2, 3

# Kinds that only matter for rendering/audio/editor; never shown to the model.
COSMETIC = {
    "Inanimate", "Light_Probe", "Particle_Source", "Particle_Force", "Point_Light", "Fog",
    "Fog_Volume", "Fog_Of_War", "Fog_Of_War_Clear", "Fog_Of_War_Z", "Sky", "Sun", "Wind",
    "Audio_Marker", "Per_Screen_Audio", "Translucent_Shadow", "Shadow_Decal", "Decal",
    "Camera_Control", "Camera_Marker", "Settings", "Entity_Issued_Sound", "Group", "Marker",
    "Level_State", "Ripples", "Temporary_Splash", "Turbulence", "Note", "Playtest_Note",
    "Global_Effects_Settings", "Flow_Updater", "Procedurally_Animating", "Animating",
    "Outline_Override", "Wrapping_Mask", "Promesst_Light",
    "Flat_Decoration", "Treasure_Display", "Combiner_Display", "Ocean_Map", "Spawner",
    "Overworld_Unlock", "Level_Connector", "Glyph_Radical",
}

# What the model may see per kind: only state that is visible on screen.
# Everything else (skills, timers, internal ids, flags) stays hidden so the
# model has to discover mechanics by playing.
OBSERVABLE = {
    "Door": ["open"],
    "Gate": ["open"],
    "Switch": ["pressed"],
    "Freezer": ["unfrozen"],
    "Treasure": ["found"],
    "Teleporter": ["discovered"],
    "Sign": ["line1", "line2", "line3"],
    "Arrow": ["direction"],
    "Fence": ["is_floor"],   # floor-type fences are walkable pieces, not walls
}

# Kinds whose facing direction is visible and can matter.
FACING_KINDS = {"Guy", "Monster", "Mirror", "Rover", "Friendly_Dragon", "Baby_Dragon", "Door",
                "Gate", "Npc", "Lily", "Boat", "Stairs", "Teleporter", "Arrow", "Statue", "Sign",
                "Fence", "Wardrobe"}

# Player-facing names for internal kinds.
DISPLAY = {"Guy": "Hero", "Baby_Dragon": "Baby Dragon", "Friendly_Dragon": "Dragon",
           "Gem_Slot": "Gem Slot", "Elevator_Platform": "Elevator", "Level_Entry": "Level Entrance",
           "Npc": "Person", "Fence": "Fence", "Area_Pin": "Map Piece", "Wardrobe": "Outfit",
           "View_Giver": "Map"}

# Outfits (wardrobes) look like a hero's clothes; name whose outfit it is (visible on screen).
OUTFIT = {"MULTIPUSH": "the Warrior's outfit (red)", "PULL": "the Thief's outfit (green)",
          "TELEPORT": "the Wizard's outfit (blue)", "PROTECTION": "the Priestess's outfit",
          "CHARM": "the Bard's outfit", "TRANSMUTE": "the Druid's outfit",
          "SAILOR": "the Sailor's outfit", "TRADER": "the Trader's outfit"}


def facing(q):
    """Quaternion (x,y,z,w) -> compass direction of the object's yaw (0 deg = east, +x)."""
    x, y, z, w = q
    yaw = math.degrees(2 * math.atan2(z, w)) % 360
    names = ["east", "north", "west", "south"]
    i = round(yaw / 90) % 4
    return names[i] if abs(yaw - 90 * round(yaw / 90)) < 10 else f"{yaw:.0f}deg"


class Types:
    def __init__(self):
        self.t = json.load(open(os.path.join(HERE, "types.json")))
        self.entity_kinds = {n: int(t["address"], 16) for n, t in self.t.items()
                             if t["kind"] == "struct" and t["members"]
                             and t["members"][0]["type"] == "Entity"}

    def size(self, kind):
        return self.t[kind]["size"]

    def fields(self, kind):
        """Own (non-Entity) fields of a kind: {name: (type, offset)}."""
        return {m["name"]: (m["type"], m["offset"]) for m in self.t[kind]["members"][1:]
                if m["offset"] >= 0}

    def enum(self, name):
        t = self.t.get(name)
        return t["values"] if t and t["kind"] == "enum" else None


class Game:
    def __init__(self, full=False):
        self.p = Process()
        self.types = Types()
        self.full = full
        self.delta = self.p.module_base - EXE_IMAGE_BASE
        self.kind_of_type_ptr = {a + self.delta: n for n, a in self.types.entity_kinds.items()}
        self._bucket_cache = {}   # (manager, level) -> {kind: offset}
        self._mesh_names = {}

    # ---------- low level ----------
    def string_at(self, buf, off):
        n, ptr = struct.unpack_from("<qQ", buf, off)
        if n <= 0 or n > 4096 or not ptr:
            return ""
        r = self.p.read(ptr, n)
        return r.decode("utf-8", "replace") if r else ""

    def mesh_name(self, mesh):
        if not mesh:
            return ""
        if mesh not in self._mesh_names:
            b = self.p.read(mesh, 16)
            self._mesh_names[mesh] = self.string_at(b, 0) if b else ""
        return self._mesh_names[mesh]

    def hero_fast(self, addr):
        """Cheap read of one hero (or any entity) for input timing: pos, visual pos, yaw, status."""
        b = self.p.read(addr, 0xB0)
        if not b:
            return None
        pos = struct.unpack_from("<3f", b, POSITION)
        vis = struct.unpack_from("<3f", b, VISUAL_POSITION)
        q = struct.unpack_from("<4f", b, ORIENTATION)
        yaw = math.degrees(2 * math.atan2(q[2], q[3])) % 360
        status = struct.unpack_from("<H", b, STATUS_FLAGS)[0]
        return pos, vis, yaw, status

    def current_manager(self):
        for g in CURRENT_MANAGER_GLOBALS:
            m = self.p.u64(g + self.delta)
            if m:
                return m
        raise RuntimeError("no current level found")

    def level_name(self, mgr):
        return self.string_at(self.p.read(mgr + MANAGER_LEVEL_NAME, 16), 0)

    def camera_window(self, mgr, layer):
        """Ground rectangle the game camera shows (once it finishes panning), or None."""
        f = struct.unpack("<8f", self.p.read(mgr + MANAGER_CAMERA, 32))
        look_x, look_y, cam_x, cam_y, _, tgt_x, tgt_y, tgt_z = f
        height = tgt_z - layer
        if any(math.isnan(v) for v in f) or not 2 < height < 100:
            return None
        # The camera -> look-at offset is fixed, so apply it to the target position.
        cx, cy = tgt_x + (look_x - cam_x), tgt_y + (look_y - cam_y)
        hx, hy = height * VIEW_HALF_X_PER_HEIGHT, height * VIEW_HALF_Y_PER_HEIGHT
        return (round(cx - hx), round(cy - hy), round(cx + hx), round(cy + hy))

    def buckets(self, mgr, level):
        """Find the per-kind [..]*Entity arrays inside the manager."""
        key = (mgr, level)
        if key in self._bucket_cache:
            return self._bucket_cache[key]
        raw = self.p.read(mgr, MANAGER_SIZE)
        found = {}
        for off in range(0, MANAGER_SIZE - 16, 8):
            count, ptr = struct.unpack_from("<qQ", raw, off)
            if not (0 < count < 1_000_000) or ptr < 0x10000:
                continue
            first = self.p.u64(ptr)
            if not first:
                continue
            tp = self.p.u64(first + ENTITY_TYPE)
            kind = self.kind_of_type_ptr.get(tp)
            if not kind or kind in found:
                continue
            # The manager also holds mixed lists (e.g. all undoable entities);
            # a per-kind bucket has the same kind for every element.
            n = min(count, 256)
            elems = struct.unpack(f"<{n}Q", self.p.read(ptr, n * 8))
            if all(self.p.u64(a + ENTITY_TYPE) == tp for a in elems if a):
                found[kind] = off
        self._bucket_cache[key] = found
        return found

    def entities_of(self, mgr, off):
        count, ptr = struct.unpack("<qQ", self.p.read(mgr + off, 16))
        if count <= 0:
            return []
        b = self.p.read(ptr, count * 8)
        return [a for a in struct.unpack(f"<{count}Q", b) if a]

    def locate(self, mgr, level, buckets, ids):
        """Positions of entities with these ids, wherever they are in the level (not only in view).
        Used for things the game points at that are out of sight. Cached per level; ids that were
        not found are looked for again after a while."""
        cache = self.__dict__.setdefault("_located", {})
        now = time.time()
        want = [i for i in ids if (level, i) not in cache or
                (cache[level, i][0] is None and now - cache[level, i][1] > 30)]
        found = {}
        if want:
            todo = set(want)
            for kind, off in buckets.items():
                if kind in ("Wall_Set", "Particle_Source", "Inanimate", "Decal"):
                    continue
                for addr in self.entities_of(mgr, off):
                    b = self.p.read(addr + POSITION, ENTITY_ID + 4 - POSITION)
                    if b is None or len(b) < ENTITY_ID + 4 - POSITION:
                        continue
                    eid = struct.unpack_from("<I", b, ENTITY_ID - POSITION)[0]
                    if eid in todo:
                        found[eid] = struct.unpack_from("<3f", b, 0)
                        todo.discard(eid)
                if not todo:
                    break
            for i in want:
                cache[level, i] = (found.get(i), now)
        return {i: cache[level, i][0] for i in ids if cache.get((level, i), (None,))[0] is not None}

    # ---------- decoding ----------
    def decode_field(self, buf, ftype, off):
        if ftype == "bool":
            return bool(buf[off])
        if ftype[0] in "su" and ftype[1:].isdigit():
            size = int(ftype[1:]) // 8
            fmt = {1: "b", 2: "h", 4: "i", 8: "q"}[size]
            return struct.unpack_from("<" + (fmt if ftype[0] == "s" else fmt.upper()), buf, off)[0]
        if ftype == "float32":
            return round(struct.unpack_from("<f", buf, off)[0], 3)
        if ftype == "string":
            return self.string_at(buf, off)
        if ftype == "Pid":
            return struct.unpack_from("<I", buf, off)[0]
        vals = self.types.enum(ftype)
        if vals is not None:
            size = self.types.size(ftype)
            v = int.from_bytes(buf[off:off + size], "little")
            if ftype.endswith("_Flags"):
                return [k for k, bit in vals.items() if bit and v & bit == bit]
            return next((k for k, x in vals.items() if x == v), v)
        return None

    def read_entity(self, addr, kind):
        b = self.p.read(addr, max(self.types.size(kind), ENTITY_SIZE))
        if not b:
            return None
        flags = struct.unpack_from("<q", b, ENTITY_FLAGS)[0]
        exists = not (flags & EF_IN_EXISTENCE_GROUP) or bool(flags & EF_CURRENTLY_EXISTS)
        if not self.full and (not exists or flags & EF_INVISIBLE):
            return None
        pos = struct.unpack_from("<3f", b, POSITION)
        vis = struct.unpack_from("<3f", b, VISUAL_POSITION)
        status = struct.unpack_from("<H", b, STATUS_FLAGS)[0]
        e = {
            "kind": kind,
            "addr": addr,
            "id": struct.unpack_from("<I", b, ENTITY_ID)[0],
            "pos": tuple(round(v, 2) for v in pos),
            "settled": all(abs(a - c) < 0.01 for a, c in zip(pos, vis)),
            "selected": bool(status & ST_ACTIVE) and kind == "Guy",
            "dead": bool(status & ST_DEAD),
            "falling": bool(status & ST_FALLING),
            "on_exit": bool(status & ST_ON_EXIT),   # hidden from the model; used to detect wins
        }
        if kind in FACING_KINDS:
            e["facing"] = facing(struct.unpack_from("<4f", b, ORIENTATION))
        fields = self.types.fields(kind)
        if self.full:
            wanted = [f for f in fields if not f.startswith(("XXX", "xxx"))]
            name = self.string_at(b, ENTITY_NAME)
            if name:
                e["name"] = name
        else:
            wanted = OBSERVABLE.get(kind, [])
        props = {}
        for f in wanted:
            ftype, off = fields[f]
            v = self.decode_field(b, ftype, off)
            if v is None or (self.full and v in ("", [], 0, False)):
                continue
            props[f] = v
        # Content the player only learns by going there (see Session.discover).
        hidden = {}
        if kind == "Sign" and not self.full:
            hidden["text"] = sign_text([props.pop(k, "") for k in ("line1", "line2", "line3")])
        elif kind == "Voice_Log":
            hidden["name"] = self.decode_field(b, *fields["name"])
            hidden["played"] = self.decode_field(b, *fields["played"])
        elif kind == "Checkpoint":
            hidden["triggered"] = self.decode_field(b, *fields["triggered"])
            hidden["story"] = self.decode_field(b, *fields["story"])
        if hidden:
            e["hidden"] = hidden
        if kind == "Level_Entry" and not self.full:
            f = lambda n: self.decode_field(b, *fields[n]) or 0
            props["state"] = ("locked" if f("enabled_t_target") < 0.5 else
                              "solved" if f("solved_t_target") > 0.5 else "unsolved")
            e["level_name"] = self.decode_field(b, *fields["level_name"])   # internal; not shown
        if kind == "Monster" and not self.full:
            # The game's own species tag (GOBLIN, DRAGON): visible on screen as what the monster looks like.
            flags = self.decode_field(b, *fields["constant_flags"]) or []
            if flags:
                e["variant"] = flags[0].capitalize()
        if kind == "Freezer" and not self.full:
            props["state"] = "thawed" if props.pop("unfrozen", False) else "frozen"
            # The game draws an arrow from a freezer to whatever unlocks it.
            ids = [struct.unpack_from("<I", b, fields[n][1])[0]
                   for n in ("unlocked_by_id", "unlocked_by_id2", "unlocked_by_id3", "unlocked_by_id4")]
            e["unlocked_by"] = [i for i in ids if i]
            e["unlock_any"] = bool(self.decode_field(b, *fields["unlock_is_or_gate"]))
        if kind == "Wardrobe" and not self.full:
            skills = self.decode_field(b, *fields["skill_flags"]) or []
            names = [OUTFIT[k] for k in skills if k in OUTFIT]
            if names:
                props["outfit"] = " + ".join(names)
        if kind == "Guy" and not self.full:
            skills = self.decode_field(b, *fields["skill_flags"]) or []
            if "QUEEN" in skills:   # the Queen wears hero outfits; which one is on screen
                worn = [OUTFIT[k] for k in skills if k in OUTFIT]
                e["worn"] = " + ".join(worn) if worn else "no outfit"
        if kind == "Area_Pin" and not self.full:
            # A pickup that adds an area to the world map; gone once picked up.
            e["picked"] = bool(self.decode_field(b, *fields["activated"]))
            e["area"] = localized(self.decode_field(b, *fields["local_area_name"]) or "") or ""
        if kind == "Guy":
            # Which character this is, from its 3D model (visible on screen); turn order is internal
            # and only used to number the heroes the way the game labels them.
            e["model"] = self.mesh_name(struct.unpack_from("<Q", b, 0x88)[0])
            e["turn_order"] = self.decode_field(b, *fields["turn_order"])
        if props:
            e["props"] = props
        # Dialogue keys the game plays (on level entry / on win); not shown as props.
        e["barks"] = {f: self.decode_field(b, *fields[f]) for f in ("initial_bark", "win_bark")
                      if f in fields}
        return e

    def read_walls(self, addr):
        b = self.p.read(addr, 0x388)
        pos = struct.unpack_from("<3f", b, POSITION)
        corner = struct.unpack_from("<3i", b, 0x330)
        dx, dy, dz = struct.unpack_from("<3i", b, 0x33C)
        slot_count, slot_ptr = struct.unpack_from("<qQ", b, 0x348)
        kind = struct.unpack_from("<I", b, 0x380)[0]
        ox, oy, oz = (round(pos[i]) + corner[i] for i in range(3))
        box = (ox, oy, ox + dx - 1, oy + dy - 1)
        return ox, oy, oz, dx, dy, dz, slot_count, slot_ptr, kind, box

    def wall_cells(self, w, window=None):
        ox, oy, oz, dx, dy, dz, slot_count, slot_ptr, kind, box = w
        if slot_count <= 0 or not slot_ptr:
            return []
        bits = int.from_bytes(self.p.read(slot_ptr, slot_count * 8), "little")
        cells = []
        for z in range(dz):
            for y in range(dy):
                for x in range(dx):
                    if bits >> (x + y * dx + z * dx * dy) & 1:
                        c = (ox + x, oy + y, oz + z)
                        if window is None or in_window(c, window):
                            cells.append(c)
        return cells

    # ---------- snapshot ----------
    def snapshot(self):
        mgr = self.current_manager()
        level = self.level_name(mgr)
        buckets = self.buckets(mgr, level)
        open_world = level in OPEN_WORLD_LEVELS

        heroes = [e for a in self.entities_of(mgr, buckets["Guy"])
                  if (e := self.read_entity(a, "Guy"))] if "Guy" in buckets else []
        # Number each hero by the key that selects it (the game binds keys per character:
        # 1 Warrior, 2 Thief, 3 Wizard, ...; checked in heroes1_11_v2). Unknown characters get 0.
        for h in heroes:
            h["num"] = SELECT_KEY.get((h.get("model") or "").lower(), 0)
        window = None
        sel = next((h for h in heroes if h["selected"]), heroes[0] if heroes else None)
        layer = round(sel["pos"][2]) if sel else 0
        zrange = (layer - LAYER_BELOW, layer + LAYER_ABOVE)
        def view_window():
            """What is on screen: the camera's view, else a square around the hero."""
            w = self.camera_window(mgr, layer)
            if w is None or not in_window(sel["pos"], w):
                cx, cy = round(sel["pos"][0]), round(sel["pos"][1])
                r = OPEN_WORLD_VIEW_RADIUS
                w = (cx - r, cy - r, cx + r, cy + r)
            return w

        if open_world and sel:
            window = view_window()

        solid, objects = set(), []
        for kind, off in buckets.items():
            if kind in COSMETIC and not self.full:
                continue
            for addr in self.entities_of(mgr, off):
                if kind == "Wall_Set":
                    w = self.read_walls(addr)
                    if w[8] == 0 and (window is None or boxes_overlap(w[9], window)):
                        solid.update(c for c in self.wall_cells(w, window)
                                     if zrange[0] - 1 <= c[2] <= zrange[1])
                    continue
                if kind == "Guy":
                    continue
                pos = struct.unpack("<3f", self.p.read(addr + POSITION, 12))
                if not zrange[0] <= round(pos[2]) <= zrange[1]:
                    continue
                if window is not None and not in_window(pos, window):
                    continue
                e = self.read_entity(addr, kind)
                # Thawed freezers have melted away; picked-up map pieces are gone.
                if e and not (kind == "Freezer" and e.get("props", {}).get("state") == "thawed"
                              and not self.full) and not e.get("picked"):
                    objects.append(e)
        # Freezer arrows can point at things outside the view: find out in which direction.
        seen = {o["id"] for o in heroes + objects}
        for f in objects:
            far = [i for i in f.get("unlocked_by", []) if i not in seen]
            if far and f["kind"] == "Freezer" and not self.full:
                f["unlock_far"] = self.locate(mgr, level, buckets, far)
        # A map item shows on screen as a glowing artifact; once it is picked up the glow is gone
        # (the item itself stays in memory), so it counts as collected when no glow is on its tile.
        givers = [o for o in objects if o["kind"] == "View_Giver"]
        if givers and "Particle_Source" in buckets and not self.full:
            glow = [struct.unpack("<3f", self.p.read(a + POSITION, 12))
                    for a in self.entities_of(mgr, buckets["Particle_Source"])]
            for gv in givers:
                if not any(abs(q[0] - gv["pos"][0]) < 1 and abs(q[1] - gv["pos"][1]) < 1 for q in glow):
                    objects.remove(gv)
        if window is None and sel and solid:
            # Big non-puzzle spaces (e.g. the intro) get the same view window as the open world.
            xs = [x for x, _, _ in solid]
            ys = [y for _, y, _ in solid]
            if max(xs) - min(xs) > LARGE_LEVEL or max(ys) - min(ys) > LARGE_LEVEL:
                window = view_window()
                solid = {c for c in solid if in_window(c, window)}
                objects = [o for o in objects if in_window(o["pos"], window)]
        heroes = [h for h in heroes if (window is None or in_window(h["pos"], window))
                  and zrange[0] <= round(h["pos"][2]) <= zrange[1]]
        # A freezer encases whatever stands in its tile (you see it inside the ice).
        tile = lambda o: (round(o["pos"][0]), round(o["pos"][1]))
        for f in objects:
            if f["kind"] == "Freezer":
                f["holding"] = [(o["kind"], o["id"]) for o in heroes + objects
                                if o is not f and o["kind"] not in ("Freezer", "Fence")
                                and tile(o) == tile(f) and abs(o["pos"][2] - f["pos"][2]) <= 1.01]
        return {"manager": hex(mgr), "level": level, "open_world": open_world, "layer": layer,
                "window": window, "solid": solid, "objects": heroes + objects}


def compass(dx, dy):
    """Rough direction name for an offset (north = +y)."""
    if abs(dx) < 3 and abs(dy) < 3:
        return "here"
    ang = math.degrees(math.atan2(dy, dx)) % 360
    names = ["east", "north-east", "north", "north-west", "west", "south-west", "south", "south-east"]
    return names[round(ang / 45) % 8]


def world_map(game):
    """The TAB map: discovered areas, their level progress, discovered teleporters."""
    mgr = game.current_manager()
    level = game.level_name(mgr)
    if level not in OPEN_WORLD_LEVELS:
        return "The world map is only available in the open world (you are inside a puzzle level)."
    buckets = game.buckets(mgr, level)

    def raw(kind):
        if kind not in buckets:
            return
        size = game.types.size(kind)
        F = game.types.fields(kind)
        for a in game.entities_of(mgr, buckets[kind]):
            b = game.p.read(a, size)
            yield b, struct.unpack_from("<3f", b, POSITION), F

    hero = next((e for a in game.entities_of(mgr, buckets["Guy"])
                 if (e := game.read_entity(a, "Guy")) and e["selected"]), None)
    hx, hy, hz = hero["pos"] if hero else (0, 0, 0)

    pins = []
    for b, p, F in raw("Area_Pin"):
        key = game.decode_field(b, *F["local_area_name"])
        pins.append({"key": key, "pos": p, "found": game.decode_field(b, *F["activated"]),
                     "solved": 0, "unsolved": 0, "locked": 0})
    # Assign each level entrance to the nearest area pin (all pins, so hidden areas absorb theirs).
    for b, p, F in raw("Level_Entry"):
        if not pins:
            break
        pin = min(pins, key=lambda q: (q["pos"][0] - p[0]) ** 2 + (q["pos"][1] - p[1]) ** 2
                  + (2 * (q["pos"][2] - p[2])) ** 2)
        en = game.decode_field(b, *F["enabled_t_target"]) or 0
        so = game.decode_field(b, *F["solved_t_target"]) or 0
        pin["locked" if en < 0.5 else "solved" if so > 0.5 else "unsolved"] += 1

    lines = ["World map (discovered areas only). Positions are (x, y, height); north = +y.",
             f"You are at ({hx:.0f}, {hy:.0f}, {hz:.0f}).", ""]
    found = [q for q in pins if q["found"]]
    found.sort(key=lambda q: (q["pos"][0] - hx) ** 2 + (q["pos"][1] - hy) ** 2)
    for q in found:
        x, y, z = (round(v) for v in q["pos"])
        name = localized(q["key"]) or q["key"]
        dist = math.hypot(x - hx, y - hy)
        lvls = q["solved"] + q["unsolved"] + q["locked"]
        prog = (f"levels: {q['solved']}/{lvls} solved" + (f", {q['locked']} locked" if q["locked"] else "")
                if lvls else "no levels")
        lines.append(f"  - {name}: around ({x},{y},{z}), {compass(x - hx, y - hy)}, ~{dist:.0f} away; {prog}")
    tps = []
    for b, p, F in raw("Teleporter"):
        flags = struct.unpack_from("<q", b, ENTITY_FLAGS)[0]
        if game.decode_field(b, *F["discovered"]) and not flags & EF_INVISIBLE:
            x, y, z = (round(v) for v in p)
            tps.append(f"  - teleporter at ({x},{y},{z}), {compass(x - hx, y - hy)}")
    if tps:
        lines += ["", "Discovered teleporters:"] + tps
    return "\n".join(lines)


def in_window(pos, window):
    x0, y0, x1, y1 = window
    return x0 <= round(pos[0]) <= x1 and y0 <= round(pos[1]) <= y1


def boxes_overlap(a, b):
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


# ---------- text rendering ----------
GLYPH = {"Guy": "@", "Rock": "R", "Door": "D", "Fence": "f", "Npc": "N", "Sign": "?",
         "Switch": "s", "Gate": "G", "Gem": "*", "Gem_Slot": "o", "Mirror": "M", "Monster": "m",
         "Stairs": "/", "Teleporter": "T", "Lily": "L", "Rover": "V", "Tree": "t", "Boat": "B",
         "Baby_Dragon": "d", "Friendly_Dragon": "F", "Egg": "e", "Arrow": ">", "Wardrobe": "W",
         "Freezer": "Z", "Level_Entry": "E", "Activator": "A", "Treasure": "$", "Statue": "S",
         "Elevator_Platform": "u", "Hedron": "H", "Tower": "^", "Rubble": ",", "Artifact": "!",
         "Voice_Log": "%", "Checkpoint": "c", "Impeller": "i", "Judge": "J",
         "Area_Pin": "P", "View_Giver": "!"}
OTHER_GLYPH = "&"   # kinds without their own symbol
# Terrain above your floor is a wall: the hero cannot walk through any of it, however high.
WALL = "#"
# Flat things you stand on; when something else shares the tile, that thing is drawn instead.
FLOOR_KINDS = {"Switch", "Level_Entry", "Checkpoint", "Teleporter", "Gem_Slot", "Arrow", "Stairs",
               "Elevator_Platform"}
# Things the hero can stand on or walk through. Every other object (signs, rocks, statues, closed
# gates, ...) blocks the tile it is on. Wardrobes sit on tile edges like a fence, but can be walked through.
WALKABLE_KINDS = FLOOR_KINDS | {"Voice_Log", "Door", "Wardrobe", "Activator", "Guy", "Fence", "View_Giver"}


def blocks_tile(o):
    """True if this object stops a hero from stepping onto its tile (an open gate does not)."""
    if o["kind"] == "Gate":
        return str(o.get("props", {}).get("open", "")).lower() != "true"
    return o["kind"] not in WALKABLE_KINDS


def on_grid(e):
    return all(abs(v - round(v)) < 0.05 for v in e["pos"])


def label(o, numbered):
    if o["kind"] == "Guy" and o.get("num"):
        return f"Hero {o['num']}"
    if o["kind"] == "Guy" and o.get("model"):
        return f"Hero ({hero_name(o)})"
    name = o.get("variant") or DISPLAY.get(o["kind"], o["kind"].replace("_", " "))
    return f"{name} {numbered[nkey(o)]}" if nkey(o) in numbered else name


def nkey(o):
    """Key of an object's label number. Numbering counts per type, so monsters of different kinds
    (Goblin, Dragon) are numbered separately."""
    return (o["id"], o["kind"] + ("." + o["variant"] if o.get("variant") else ""))


def glyph_of(o):
    if o["kind"] == "Guy":
        if o.get("selected"):
            return "@"
        return str(o["num"]) if 1 <= o.get("num", 0) <= 9 else "h"
    if o.get("variant") == "Dragon":
        return "X"
    return GLYPH.get(o["kind"], OTHER_GLYPH)


def hero_name(o):
    model = (o.get("model") or "").replace("_", " ").strip()
    return model.title() if model else ""


def numbering(objects):
    """Stable short labels (Rock 1, Rock 2, ...) ordered by id."""
    out, counts = {}, {}
    for o in sorted(objects, key=lambda o: (nkey(o)[1], o["id"])):
        k = nkey(o)
        counts[k[1]] = counts.get(k[1], 0) + 1
        out[k] = counts[k[1]]
    return out


FENCE_STEP = {"east": (1, 0), "west": (-1, 0), "north": (0, 1), "south": (0, -1)}


def fence_edges(fences, zh):
    """Fences are thin walls on one edge of a tile; the facing says which edge.
    Returns (horiz, vert, other): horiz has (x, y) for a wall between y and y+1,
    vert has (x, y) for a wall between x and x+1. `other` = fences not at the hero's height."""
    horiz, vert, other = set(), set(), []
    for f in fences:
        if f.get("props", {}).get("is_floor"):
            continue
        x, y, z = (round(v) for v in f["pos"])
        dx, dy = FENCE_STEP.get(f.get("facing"), (0, 0))
        if z != zh:
            other.append(f)
        elif dy:
            horiz.add((x, min(y, y + dy)))
        elif dx:
            vert.add((min(x, x + dx), y))
    return horiz, vert, other


def fence_text(horiz, vert, window):
    """Fences per tile, e.g. '(42,1) NS' = fences on the north and south edges of tile (42,1)."""
    x0, y0, x1, y1 = window
    edges = {}
    for x, y in horiz:          # between (x,y) and (x,y+1)
        for t, side in (((x, y), "N"), ((x, y + 1), "S")):
            if x0 <= t[0] <= x1 and y0 <= t[1] <= y1:
                edges.setdefault(t, set()).add(side)
    for x, y in vert:           # between (x,y) and (x+1,y)
        for t, side in (((x, y), "E"), ((x + 1, y), "W")):
            if x0 <= t[0] <= x1 and y0 <= t[1] <= y1:
                edges.setdefault(t, set()).add(side)
    order = "NESW"
    return ", ".join(f"({x},{y}) {''.join(sorted(s, key=order.index))}"
                     for (x, y), s in sorted(edges.items(), key=lambda kv: (-kv[0][1], kv[0][0])))


def floor_rows(state):
    """Terrain you can stand on at your own height, as exact x ranges per row. The same data as
    the '.' tiles of the map, but with the coordinates written out: reading a column number off a
    wide character grid is where text models go wrong. Terrain only: objects and fences are in
    the map and the lists."""
    solid = state["solid"]
    zh = state.get("layer", 0)
    if state["window"]:
        x0, y0, x1, y1 = state["window"]
    else:
        tiles = [(x, y) for x, y, z in solid if z <= zh]
        if not tiles:
            return ""
        x0, x1 = min(x for x, _ in tiles), max(x for x, _ in tiles)
        y0, y1 = min(y for _, y in tiles), max(y for _, y in tiles)
    blocked = {(round(o["pos"][0]), round(o["pos"][1])) for o in state["objects"]
               if on_grid(o) and round(o["pos"][2]) == zh and blocks_tile(o)}
    rows = []
    for y in range(y1, y0 - 1, -1):
        xs = [x for x in range(x0, x1 + 1)
              if (x, y, zh - 1) in solid and (x, y, zh) not in solid and (x, y) not in blocked]
        runs, i = [], 0
        while i < len(xs):
            j = i
            while j + 1 < len(xs) and xs[j + 1] == xs[j] + 1:
                j += 1
            runs.append(str(xs[i]) if i == j else f"{xs[i]}-{xs[j]}")
            i = j + 1
        if runs:
            rows.append(f"  y={y}: x={', '.join(runs)}")
    return ("Floor tiles by row (x ranges of tiles at your level). Fences are not tiles: they are separations "
            "between two tiles, so they are not part of these ranges, and two listed neighbours can still be "
            "separated by a fence (see Fences). Tiles with a sign, rock or other blocking object are left out; "
            "a tile not listed is a wall, a drop or blocked:\n" + "\n".join(rows)) if rows else ""


# What a symbol on the map means for the hero, in plain words. Derived from WALKABLE_KINDS / blocks_tile,
# so the legend never claims more than the engine rules; only a few kinds add how to interact.
USE_STAND, USE_THROUGH, USE_BLOCK = "you can stand on it", "you can walk through it", "blocks you"
USE_OVERRIDE = {"Sign": "blocks you; to read it, stand next to it and face it",
                "Voice_Log": "you can stand on it; activate while standing on it",
                "Rock": "you cannot walk onto it"}


def use_of(o):
    """Plain-words effect of an object on movement, or "" for heroes."""
    if o["kind"] == "Guy":
        return ""
    if o["kind"] in USE_OVERRIDE:
        return USE_OVERRIDE[o["kind"]]
    if o["kind"] == "Gate":
        return USE_BLOCK if blocks_tile(o) else USE_THROUGH
    return USE_BLOCK if blocks_tile(o) else USE_STAND


def render(state, numbered=None):
    solid = state["solid"]
    fences = [o for o in state["objects"] if o["kind"] == "Fence" and on_grid(o)]
    objs = [o for o in state["objects"] if on_grid(o) and o["kind"] not in ("Fence", "Wardrobe")]
    wardrobes = [o for o in state["objects"] if o["kind"] == "Wardrobe" and on_grid(o)
                 and round(o["pos"][2]) == state.get("layer", 0)]
    numbered = numbered or numbering(state["objects"])
    by_key = {(o["kind"], o["id"]): o for o in state["objects"]}
    zh = state.get("layer", 0)
    # Only objects at your own height are drawn on the map; others are in the list with their height.
    map_objs = [o for o in objs if round(o["pos"][2]) == zh]
    top = {}
    for x, y, z in solid:
        if z <= zh:
            top[(x, y)] = max(top.get((x, y), -99), z)
    if state["window"]:
        x0, y0, x1, y1 = state["window"]
    else:
        xs = [x for x, _ in top] + [round(o["pos"][0]) for o in objs]
        ys = [y for _, y in top] + [round(o["pos"][1]) for o in objs]
        if not xs:
            return "(nothing visible)"
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    where = (f"{'Open world' if state['open_world'] else state['level']}, view around you ({x1 - x0 + 1}x{y1 - y0 + 1})" if state["window"]
             else f"Puzzle level '{state['level']}'")
    horiz, vert, other_fences = fence_edges(fences, zh)
    # Outfit gates sit on a tile edge like a fence but can be walked through.
    # Each is drawn with a letter for its colour: R red, G green, B blue, ~ other.
    gate_h, gate_v, marks = {}, {}, {}
    for w in wardrobes:
        x, y = round(w["pos"][0]), round(w["pos"][1])
        dx, dy = FENCE_STEP.get(w.get("facing"), (0, 0))
        m = re.search(r"\((red|green|blue)\)", w.get("props", {}).get("outfit", ""))
        mark = marks[w["id"]] = m.group(1)[0].upper() if m else "~"
        if dy:
            gate_h[(x, min(y, y + dy))] = mark
        elif dx:
            gate_v[(min(x, x + dx), y)] = mark
    edges = bool(horiz or vert or gate_h or gate_v)

    def tile_of(o):
        return (round(o["pos"][0]), round(o["pos"][1]))

    stacks = {}
    for o in map_objs:
        stacks.setdefault(tile_of(o), []).append(o)

    def priority(o):
        # hero > freezer (it encases what is inside) > other objects > flat floor things
        return (o["kind"] != "Guy", o["kind"] != "Freezer", o["kind"] in FLOOR_KINDS, o["kind"], o["id"])

    def tile(x, y):
        here = stacks.get((x, y))
        if here:
            return glyph_of(min(here, key=priority))
        if (x, y, zh) in solid:
            return WALL
        return "." if (x, y, zh - 1) in solid else " "

    in_view = {}
    for o in map_objs:
        g = glyph_of(o)
        if o["kind"] == "Guy":
            name = "you" if o.get("selected") else (f"Hero {o['num']}" if o.get("num") else "other hero")
        else:
            name = o.get("variant") or DISPLAY.get(o["kind"], o["kind"].replace("_", " "))
            if g == OTHER_GLYPH:
                name = "other object (see list)"
        in_view.setdefault(g, set()).add(name)
    symbols = "Symbols: " + "  ".join(f"{g}={'/'.join(sorted(n))}" for g, n in
                                       sorted(in_view.items(), key=lambda kv: (kv[0] != "@", kv[0])))
    heroes = sorted((o for o in state["objects"] if o["kind"] == "Guy"), key=lambda h: h.get("num", 99))
    # Every tile is 2 characters wide: a slot for a '|' fence on its left, then the tile itself.
    # Column numbers are written vertically (read top to bottom), at the top and bottom of the map.
    xs_all = list(range(x0, x1 + 1))
    width = max(len(str(x)) for x in xs_all)
    header = [f"{'x':>4} " + "".join(" " + str(x).rjust(width)[k] for x in xs_all) for k in range(width)]

    def fence_row(y_low):
        return ("     " + "".join(" " + ("-" if (x, y_low) in horiz else gate_h.get((x, y_low), " "))
                                  for x in xs_all)).rstrip()

    lines = [where]
    if len(heroes) > 1:
        lines.append("Heroes: " + "   ".join(
            f"{glyph_of(h)}=" + (f"Hero {h['num']}" if h.get("num") else "Hero")
            + (f" ({hero_name(h)})" if hero_name(h) else "")
            + (" <- you" if h.get("selected") else "") for h in heroes))
    lines += [symbols,
              "Map (top-down; north=up, east=right).",
              "Coordinates: the row number (y) is at both ends of each row; the column number (x) "
              "is written top-to-bottom above and below each column."]
    lines += ["  . floor at your level", "  # wall: blocks you"]
    if horiz or vert:
        lines.append("  | - fence on a tile edge: separates the two tiles it lies between and blocks you")
    lines.append("  (space) drop, water or nothing")
    shown = {}
    for o in map_objs:
        if o["kind"] == "Guy":
            name = "you" if o.get("selected") else (f"Hero {o['num']}" if o.get("num") else "other hero")
        else:
            name = o.get("variant") or DISPLAY.get(o["kind"], o["kind"].replace("_", " "))
        shown[(glyph_of(o), name)] = use_of(o)
    for (g, name), use in sorted(shown.items(), key=lambda kv: (kv[0][0] != "@", kv[0])):
        lines.append(f"  {g} {name}" + (f": {use}" if use else ""))
    if gate_h or gate_v:
        lines.append("Outfit gates are on tile edges too, drawn with a colour letter instead of '-' / '|' "
                     "(R=red, G=green, B=blue, ~=other). You can walk through them; "
                     "the 'Outfit gates:' line under the map says what each one is.")
    if horiz or vert:
        lines.append("Fences are thin walls ON TILE EDGES: '|' between two tiles left/right, "
                     "'-' between two tiles above/below. A fence blocks the way like a wall along that edge. "
                     "The 'Fences:' line under the map lists them per tile.")
    lines += header
    for y in range(y1, y0 - 1, -1):
        if edges:
            lines.append(fence_row(y))
        row = ""
        for x in xs_all:
            row += ("|" if (x - 1, y) in vert else gate_v.get((x - 1, y), " ")) + tile(x, y)
        row += "|" if (x1, y) in vert else gate_v.get((x1, y), " ")
        lines.append(f"{y:4} {row} {y}")
    if edges:
        lines.append(fence_row(y0 - 1))
    lines += header
    if horiz or vert:
        lines.append("")
        lines.append("Fences: " + fence_text(horiz, vert, (x0, y0, x1, y1))
                     + "   (N/E/S/W = which edge of that tile has a fence)")
    if wardrobes:
        lines.append("")
        lines.append("Outfit gates: " + "; ".join(
            f"{marks[w['id']]} = on the {w['facing']} edge of ({round(w['pos'][0])},{round(w['pos'][1])}), "
            f"{w.get('props', {}).get('outfit', 'outfit')}"
            for w in sorted(wardrobes, key=lambda w: (-w['pos'][1], w['pos'][0]))))
    lines.append("")
    lines.append("Objects at your height (x, y, height relative to you):")
    held_by = {}
    by_id = {o["id"]: o for o in state["objects"]}
    for o in state["objects"]:
        for k in o.get("holding", []):
            held_by[k] = o
    # Like the map, the list shows what is at your own height. Things at other heights are not listed
    # (they appear as soon as you are at their height); the count below says some exist.
    listed = [o for o in state["objects"] if o["kind"] != "Fence"
              and (round(o["pos"][2]) == zh or (o["kind"], o["id"]) in held_by)]
    elsewhere = sum(1 for o in state["objects"] if o["kind"] not in ("Fence", "Wardrobe")
                    and o not in listed and not (state["window"] and not in_window(
                        tuple(round(v) for v in o["pos"]), state["window"])))
    for o in sorted(listed, key=lambda o: (o["kind"] != "Guy", o["kind"], o.get("num", 0), o["id"])):
        x, y, z = (round(v) for v in o["pos"])
        extra = []
        if o["kind"] == "Guy":
            if hero_name(o):
                extra.append(hero_name(o))
            if o.get("selected"):
                extra.append("(you, selected)")
            elif len(heroes) > 1:
                extra.append(f"switch to it with select_character({o['num']})" if o.get("num")
                             else "switch to it with action('switch_character')")
        if o.get("worn"):
            extra.append(f"abilities from outfit: {o['worn']}")
        if o["kind"] == "Wardrobe" and o.get("facing"):
            dx, dy = FENCE_STEP.get(o["facing"], (0, 0))
            tx, ty = round(o["pos"][0]) + dx, round(o["pos"][1]) + dy
            extra.append(f"outfit gate on the edge between ({x},{y}) and ({tx},{ty}); "
                         f"walk through to wear it")
        elif o.get("facing"):
            extra.append(f"facing {o['facing']}")
        for flag in ("dead", "falling"):
            if o.get(flag):
                extra.append(flag)
        for k, v in o.get("props", {}).items():
            if k == "state" and o["kind"] == "Freezer":
                extra.append(str(v))
            elif k == "text":
                extra.append(f'says "{v}"')
            elif k == "outfit":
                extra.append(str(v))
            else:
                extra.append(f"{k}={v}")
        if o["kind"] == "Freezer":
            inside = [label(by_key[k], numbered) for k in o.get("holding", []) if k in by_key]
            extra.append("holding " + " and ".join(inside) if inside else "empty")
            if o.get("unlocked_by") and o.get("props", {}).get("state") != "thawed":
                names = []
                for i in o["unlocked_by"]:
                    t, far = by_id.get(i), o.get("unlock_far", {}).get(i)
                    if t:
                        names.append(f"{label(t, numbered)} at ({round(t['pos'][0])},{round(t['pos'][1])})")
                    elif far:
                        d = compass(far[0] - o["pos"][0], far[1] - o["pos"][1])
                        names.append("something right here, not listed" if d == "here"
                                     else f"something out of view to the {d}")
                    else:
                        names.append("something not listed here")
                how = "" if len(names) == 1 else ("any of " if o.get("unlock_any") else "all of ")
                extra.append("arrow points to what unlocks it: " + how + ", ".join(names))
        key = (o["kind"], o["id"])
        if key in held_by:
            extra.append(f"inside {label(held_by[key], numbered)}")
        elif on_grid(o) and round(o["pos"][2]) == zh:
            others = [p for p in stacks.get(tile_of(o), []) if p is not o and p["kind"] != "Freezer"]
            if others and o["kind"] in FLOOR_KINDS:
                on_top = [p for p in others if p["kind"] not in FLOOR_KINDS]
                if on_top:
                    extra.append("under " + " and ".join(label(p, numbered) for p in on_top))
            elif others:
                below = [p for p in others if p["kind"] in FLOOR_KINDS]
                if below:
                    extra.append("standing on " + " and ".join(label(p, numbered) for p in below))
        if o.get("name"):
            extra.append(f"name={o['name']}")
        pos = f"({x},{y},{z - zh:+d})" if on_grid(o) else f"(~{o['pos'][0]:.1f},~{o['pos'][1]:.1f}) off-grid"
        lines.append(f"  {glyph_of(o)} {label(o, numbered)} at {pos} " + ", ".join(e for e in extra if e))
    if elsewhere:
        lines.append(f"({elsewhere} more object{'s' if elsewhere > 1 else ''} in view at other heights, not shown.)")
    return "\n".join(lines)


def dialogue_lines(keys):
    out = []
    for k in keys:
        said = bark_text(k) if k else None
        if said:
            out += [f"  {l}" for l in said]
    return out


if __name__ == "__main__":
    full = "--full" in sys.argv
    g = Game(full=full)
    s = g.snapshot()
    print(render(s))
    intro = dialogue_lines(h["barks"].get("initial_bark") for h in s["objects"] if h["kind"] == "Guy")
    if intro:
        print("\nDialogue on entering:\n" + "\n".join(intro))
