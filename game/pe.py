"""Minimal read-only PE parser: maps virtual addresses <-> file offsets."""
import struct


class PE:
    def __init__(self, path):
        with open(path, "rb") as f:
            self.data = f.read()
        d = self.data
        e_lfanew = struct.unpack_from("<I", d, 0x3C)[0]
        assert d[e_lfanew:e_lfanew + 4] == b"PE\0\0"
        coff = e_lfanew + 4
        self.num_sections = struct.unpack_from("<H", d, coff + 2)[0]
        opt_size = struct.unpack_from("<H", d, coff + 16)[0]
        opt = coff + 20
        assert struct.unpack_from("<H", d, opt)[0] == 0x20B, "expected PE32+"
        self.image_base = struct.unpack_from("<Q", d, opt + 24)[0]
        self.sections = []
        sec = opt + opt_size
        for i in range(self.num_sections):
            o = sec + i * 40
            name = d[o:o + 8].rstrip(b"\0").decode(errors="replace")
            vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", d, o + 8)
            self.sections.append((name, vaddr, vsize, raddr, rsize))

    def off_to_va(self, off):
        for name, vaddr, vsize, raddr, rsize in self.sections:
            if raddr <= off < raddr + rsize:
                return self.image_base + vaddr + (off - raddr)
        return None

    def va_to_off(self, va):
        rva = va - self.image_base
        for name, vaddr, vsize, raddr, rsize in self.sections:
            if vaddr <= rva < vaddr + min(vsize, rsize):
                return raddr + (rva - vaddr)
        return None

    def section_of_va(self, va):
        rva = va - self.image_base
        for s in self.sections:
            if s[1] <= rva < s[1] + s[2]:
                return s[0]
        return None

    def u64(self, va):
        o = self.va_to_off(va)
        return None if o is None else struct.unpack_from("<Q", self.data, o)[0]

    def s64(self, va):
        o = self.va_to_off(va)
        return None if o is None else struct.unpack_from("<q", self.data, o)[0]

    def u32(self, va):
        o = self.va_to_off(va)
        return None if o is None else struct.unpack_from("<I", self.data, o)[0]

    def bytes_at(self, va, n):
        o = self.va_to_off(va)
        return None if o is None else self.data[o:o + n]

    def jai_string(self, va):
        """A Jai string is {count: s64, data: *u8}."""
        count, ptr = self.s64(va), self.u64(va + 8)
        if count is None or ptr is None or not (0 <= count < 4096):
            return None
        if count == 0:
            return ""
        b = self.bytes_at(ptr, count)
        if b is None:
            return None
        try:
            return b.decode("utf-8")
        except UnicodeDecodeError:
            return None
