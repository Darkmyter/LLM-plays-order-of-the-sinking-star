"""Step 2 probe: find live entities in the running game by their entity_type pointer.

Read-only. Prints a census of entity kinds per Entity_Manager.
"""
import json
import struct
import sys
from collections import Counter, defaultdict

import numpy as np

from game.memreader import Process

EXE_IMAGE_BASE = 0x140000000
ENTITY_TYPE_OFF = 0x108
ENTITY_MANAGER_OFF = 0xF0
POSITION_OFF = 0x00
VISUAL_POSITION_OFF = 0xA0
ENTITY_ID_OFF = 0x100


def entity_kinds(types):
    return {n: int(t["address"], 16) for n, t in types.items()
            if t["kind"] == "struct" and t["members"] and t["members"][0]["type"] == "Entity"}


def scan(proc, kinds):
    delta = proc.module_base - EXE_IMAGE_BASE
    runtime = {addr + delta: name for name, addr in kinds.items()}
    needles = np.array(sorted(runtime), dtype=np.uint64)
    lo, hi = needles[0], needles[-1]
    hits = []
    for base, size in proc.regions():
        # Skip the exe image itself (type info lives there, not entities).
        if proc.module_base <= base < proc.module_base + 0x2000000:
            continue
        for off in range(0, size, 64 << 20):
            chunk = proc.read(base + off, min(64 << 20, size - off))
            if not chunk or len(chunk) < 8:
                continue
            arr = np.frombuffer(chunk[: len(chunk) // 8 * 8], dtype=np.uint64)
            cand = np.nonzero((arr >= lo) & (arr <= hi))[0]
            if len(cand) == 0:
                continue
            cand = cand[np.isin(arr[cand], needles)]
            for i in cand:
                ent = base + off + int(i) * 8 - ENTITY_TYPE_OFF
                hits.append((ent, runtime[int(arr[i])]))
    return hits


def main():
    types = json.load(open("game/types.json"))
    kinds = entity_kinds(types)
    proc = Process()
    print(f"pid {proc.pid}, module base {proc.module_base:#x}")
    hits = scan(proc, kinds)
    print(f"{len(hits)} raw hits")

    by_mgr = defaultdict(list)
    for ent, kind in hits:
        hdr = proc.read(ent, 0x110)
        if not hdr:
            continue
        mgr = struct.unpack_from("<Q", hdr, ENTITY_MANAGER_OFF)[0]
        pos = struct.unpack_from("<3f", hdr, POSITION_OFF)
        eid = struct.unpack_from("<I", hdr, ENTITY_ID_OFF)[0]
        by_mgr[mgr].append((ent, kind, eid, pos))

    for mgr, ents in sorted(by_mgr.items(), key=lambda kv: -len(kv[1]))[:8]:
        c = Counter(k for _, k, _, _ in ents)
        print(f"\nmanager {mgr:#x}: {len(ents)} entities")
        print("  " + ", ".join(f"{k}={n}" for k, n in c.most_common()))

    json.dump({hex(m): [[hex(e), k, i, p] for e, k, i, p in v] for m, v in by_mgr.items()},
              open("tools/scan_result.json", "w"))


if __name__ == "__main__":
    main()
