"""Extract Jai runtime type info (structs + enums) from sinking_star.exe.

Read-only: opens the exe file on disk, never touches the running game.
Writes types.json (machine-readable) and types.txt (human-readable).
"""
import json
import sys
from game.pe import PE

EXE = r"D:\Games\Order of the Sinking Star\sinking_star.exe"

# Type_Info_Tag values, as observed in this build.
INTEGER, FLOAT, BOOL, STRING, POINTER, PROCEDURE, VOID, STRUCT, ARRAY = range(9)
ENUM, TYPE, VARIANT = 11, 13, 18

STRUCT_MEMBERS = 0x40      # Type_Info_Struct.members: [] Type_Info_Struct_Member
MEMBER_SIZE = 0x40         # name(16) type(8) offset(8) flags(8) notes(16) const_off(8)
ENUM_NAMES, ENUM_VALUES = 0x28, 0x38


class Dumper:
    def __init__(self, pe):
        self.p = pe
        self._names = {}

    def valid_ptr(self, va):
        return va is not None and self.p.va_to_off(va) is not None

    def type_name(self, t, depth=0):
        p = self.p
        if not self.valid_ptr(t) or depth > 6:
            return "?"
        if t in self._names:
            return self._names[t]
        tag, size = p.u32(t), p.s64(t + 8)
        if tag == INTEGER:
            signed = p.bytes_at(t + 0x10, 1)[0]
            n = f"{'s' if signed else 'u'}{size * 8}"
        elif tag == FLOAT:
            n = f"float{size * 8}"
        elif tag == BOOL:
            n = "bool"
        elif tag == STRING:
            n = "string"
        elif tag == POINTER:
            n = "*" + self.type_name(p.u64(t + 0x10), depth + 1)
        elif tag == PROCEDURE:
            n = "proc"
        elif tag == VOID:
            n = "void"
        elif tag in (STRUCT, ENUM, VARIANT):
            n = p.jai_string(t + 0x10) or f"<anon tag{tag}>"
        elif tag == ARRAY:
            elem = self.type_name(p.u64(t + 0x10), depth + 1)
            kind, count = p.s64(t + 0x18), p.s64(t + 0x20)
            if count is not None and count >= 0:
                n = f"[{count}]{elem}"
            else:
                n = ("[..]" if kind == 1 else "[]") + elem
        elif tag == TYPE:
            n = "Type"
        else:
            n = f"<tag{tag}>"
        self._names[t] = n
        return n

    def struct(self, r):
        p = self.p
        count, ptr = p.s64(r + STRUCT_MEMBERS), p.u64(r + STRUCT_MEMBERS + 8)
        members = []
        if count and 0 < count < 2000 and self.valid_ptr(ptr):
            for i in range(count):
                m = ptr + i * MEMBER_SIZE
                name = p.jai_string(m)
                if name is None:
                    return None
                members.append({
                    "name": name,
                    "type": self.type_name(p.u64(m + 0x10)),
                    "offset": p.s64(m + 0x18),   # -1 for constants / #place'd consts
                })
        return {"kind": "struct", "size": p.s64(r + 8), "members": members}

    def enum(self, r):
        p = self.p
        nc, np_ = p.s64(r + ENUM_NAMES), p.u64(r + ENUM_NAMES + 8)
        vc, vp = p.s64(r + ENUM_VALUES), p.u64(r + ENUM_VALUES + 8)
        if nc != vc or not (0 <= nc < 5000):
            return None
        values = {}
        if nc:
            if not (self.valid_ptr(np_) and self.valid_ptr(vp)):
                return None
            for i in range(nc):
                name = p.jai_string(np_ + i * 16)
                if name is None:
                    return None
                values[name] = p.s64(vp + i * 8)
        flags = p.u32(r + 0x50 - 0x08) if False else None
        return {"kind": "enum", "size": p.s64(r + 8),
                "underlying": self.type_name(p.u64(r + 0x20)), "values": values}

    def scan(self):
        """Walk .rdata/.data 8 bytes at a time looking for struct/enum headers."""
        p = self.p
        out = {}
        for name, vaddr, vsize, raddr, rsize in p.sections:
            if name not in (".rdata", ".data"):
                continue
            start = p.image_base + vaddr
            for va in range(start, start + min(vsize, rsize) - 0x50, 8):
                tag = p.u32(va)
                if tag not in (STRUCT, ENUM):
                    continue
                size = p.s64(va + 8)
                if size is None or not (0 <= size < 1 << 28):
                    continue
                tname = p.jai_string(va + 0x10)
                if not tname or not tname.replace("_", "a").isalnum():
                    continue
                rec = self.struct(va) if tag == STRUCT else self.enum(va)
                if rec is None:
                    continue
                rec["address"] = hex(va)
                # Keep the richest record per name (polymorphs/dupes exist).
                key = tname
                prev = out.get(key)
                if prev is None or len(rec.get("members", rec.get("values", ()))) > \
                        len(prev.get("members", prev.get("values", ()))):
                    out[key] = rec
        return out


def main():
    d = Dumper(PE(EXE))
    types = d.scan()
    with open("game/types.json", "w") as f:
        json.dump(types, f, indent=1)
    with open("tools/types.txt", "w") as f:
        for name in sorted(types, key=str.lower):
            t = types[name]
            if t["kind"] == "struct":
                f.write(f"struct {name}  // size {t['size']:#x}  @{t['address']}\n")
                for m in t["members"]:
                    off = "const" if m["offset"] < 0 else f"{m['offset']:#06x}"
                    f.write(f"    {off:>8}  {m['name']}: {m['type']}\n")
            else:
                f.write(f"enum {name}: {t['underlying']}  @{t['address']}\n")
                for k, v in t["values"].items():
                    f.write(f"    {k} = {v}\n")
            f.write("\n")
    s = sum(t["kind"] == "struct" for t in types.values())
    print(f"{s} structs, {len(types) - s} enums -> tools/types.txt / game/types.json")


if __name__ == "__main__":
    main()
