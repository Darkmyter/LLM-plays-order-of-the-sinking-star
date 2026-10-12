"""Step 2 probe: render one entity manager's level as a top-down ASCII map. Read-only."""
import json
import struct
import sys

from game.memreader import Process

SKIP = {"Inanimate", "Light_Probe", "Particle_Source", "Point_Light", "Fog_Volume", "Sky", "Sun",
        "Wind", "Fog", "Audio_Marker", "Translucent_Shadow", "Camera_Control", "Settings",
        "Entity_Issued_Sound", "Group", "Marker", "Level_State", "Wall_Set"}
GLYPH = {"Guy": "@", "Rock": "R", "Door": "D", "Fence": "f", "Npc": "N", "Sign": "S",
         "Switch": "s", "Gate": "G", "Gem": "*", "Gem_Slot": "o", "Mirror": "M", "Monster": "m",
         "Stairs": "/", "Teleporter": "T", "Lily": "L", "Rover": "V", "Tree": "t"}


def read_walls(p, ent, pos):
    b = p.read(ent + 0x330, 0x58)
    corner = struct.unpack_from("<3i", b, 0)
    dims = struct.unpack_from("<3i", b, 12)
    slot_count, slot_ptr, bit_count = struct.unpack_from("<qQq", b, 0x18)
    if slot_count <= 0 or not slot_ptr:
        return None
    bits = int.from_bytes(p.read(slot_ptr, slot_count * 8), "little")
    cells = []
    dx, dy, dz = dims
    for z in range(dz):
        for y in range(dy):
            for x in range(dx):
                i = x + y * dx + z * dx * dy
                if bits >> i & 1:
                    cells.append((round(pos[0]) + corner[0] + x,
                                  round(pos[1]) + corner[1] + y,
                                  round(pos[2]) + corner[2] + z))
    return cells


def main(mgr):
    p = Process()
    ents = json.load(open("tools/scan_result.json"))[mgr]
    height = {}   # (x,y) -> highest solid z
    objects = []
    for e, kind, eid, pos in ents:
        e = int(e, 16)
        if kind == "Wall_Set":
            cells = read_walls(p, e, pos)
            for x, y, z in cells or ():
                height[(x, y)] = max(height.get((x, y), -99), z)
        elif kind not in SKIP:
            objects.append((kind, eid, pos))

    xs = [x for x, _ in height] + [round(o[2][0]) for o in objects]
    ys = [y for _, y in height] + [round(o[2][1]) for o in objects]
    print("legend: '#'=wall (z>=0)  '.'=floor (z=-1)  ' '=nothing/void   objects:", GLYPH)
    print("y up = north; x right = east\n")
    for y in range(max(ys) + 1, min(ys) - 2, -1):
        row = f"{y:3} "
        for x in range(min(xs) - 1, max(xs) + 2):
            here = [o for o in objects if round(o[2][0]) == x and round(o[2][1]) == y]
            if here:
                c = GLYPH.get(here[-1][0], "?")
                if any(o[0] == "Guy" for o in here):
                    c = "@"
            else:
                h = height.get((x, y))
                c = " " if h is None else ("." if h < 0 else "#")
            row += c
        print(row)
    print("    " + "".join(str(abs(x) % 10) for x in range(min(xs) - 1, max(xs) + 2)))
    print()
    for kind, eid, pos in sorted(objects):
        print(f"  {kind:10} id={eid:<10} at ({pos[0]:g}, {pos[1]:g}, {pos[2]:g})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "0x220f10f0080")
