"""Read legacy Excel 97-2003 (.xls, BIFF8) workbooks with the standard library.

ONS published its earnings tables as .xls until 2024, and there is no stdlib
reader for them, so this is a small one. It understands exactly what those
tables use: the OLE2 container, the shared-string table (including strings
split across CONTINUE records), and numeric / text / formula cells. Styles,
charts and anything else are skipped.

Same interface as xlsx.Book: `Book(data).sheets` and `Book(data).rows(name)`.
"""

import struct

_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_END = 0xFFFFFFFE
_FREE = 0xFFFFFFFF


class XlsError(Exception):
    pass


# --------------------------------------------------------------------------
# OLE2 compound file: find the "Workbook" stream
# --------------------------------------------------------------------------

def _workbook_stream(data):
    if data[:8] != _SIGNATURE:
        raise XlsError("not an Excel 97-2003 file")
    sector_size = 1 << struct.unpack_from("<H", data, 0x1E)[0]
    mini_size = 1 << struct.unpack_from("<H", data, 0x20)[0]
    first_dir = struct.unpack_from("<I", data, 0x30)[0]
    mini_cutoff = struct.unpack_from("<I", data, 0x38)[0]
    first_minifat, n_minifat = struct.unpack_from("<II", data, 0x3C)
    first_difat, n_difat = struct.unpack_from("<II", data, 0x44)

    def sector(n):
        off = (n + 1) * sector_size
        return data[off:off + sector_size]

    # The FAT's own sector list: 109 entries in the header, then a chain.
    fat_sectors = list(struct.unpack_from("<109I", data, 0x4C))
    nxt, per = first_difat, sector_size // 4 - 1
    for _ in range(n_difat):
        if nxt in (_END, _FREE):
            break
        vals = struct.unpack("<%dI" % (per + 1), sector(nxt))
        fat_sectors.extend(vals[:per])
        nxt = vals[per]
    fat = []
    for s in fat_sectors:
        if s in (_END, _FREE):
            continue
        fat.extend(struct.unpack("<%dI" % (sector_size // 4), sector(s)))

    def chain(start, table):
        seen = set()
        while start not in (_END, _FREE) and start < len(table):
            if start in seen:
                raise XlsError("corrupt sector chain")
            seen.add(start)
            yield start
            start = table[start]

    def read(start):
        return b"".join(sector(s) for s in chain(start, fat))

    directory = read(first_dir)
    entries = []
    for off in range(0, len(directory) - 127, 128):
        e = directory[off:off + 128]
        name_len = struct.unpack_from("<H", e, 0x40)[0]
        name = e[:max(0, name_len - 2)].decode("utf-16-le", errors="replace")
        kind = e[0x42]
        start, size = struct.unpack_from("<II", e, 0x74)
        entries.append((name, kind, start, size))

    root = next((e for e in entries if e[1] == 5), None)
    wb = next((e for e in entries if e[1] == 2 and e[0] in ("Workbook", "Book")), None)
    if wb is None:
        raise XlsError("no Workbook stream (is it an older Excel 5 file?)")
    _, _, start, size = wb
    if size >= mini_cutoff:
        return read(start)[:size]

    # Small streams live in the mini stream, addressed through the mini FAT.
    minifat = []
    for s in chain(first_minifat, fat):
        minifat.extend(struct.unpack("<%dI" % (sector_size // 4), sector(s)))
    ministream = read(root[2]) if root else b""
    out = b"".join(ministream[m * mini_size:(m + 1) * mini_size]
                   for m in chain(start, minifat))
    return out[:size]


# --------------------------------------------------------------------------
# BIFF8 records
# --------------------------------------------------------------------------

def _records(stream, pos=0):
    n = len(stream)
    while pos + 4 <= n:
        rtype, length = struct.unpack_from("<HH", stream, pos)
        yield pos, rtype, stream[pos + 4:pos + 4 + length]
        pos += 4 + length


class _Segments:
    """A cursor over an SST record and its CONTINUE records.

    A string whose characters run past a record boundary resumes in the next
    record behind one fresh option byte (which can switch between 8- and 16-bit
    characters). Everything else crosses boundaries transparently.
    """

    def __init__(self, parts):
        self.parts, self.i, self.pos = parts, 0, 0

    def _roll(self):
        while self.i < len(self.parts) and self.pos >= len(self.parts[self.i]):
            self.i += 1
            self.pos = 0

    def take(self, n):
        out = b""
        while n > 0:
            self._roll()
            if self.i >= len(self.parts):
                raise XlsError("shared string table is truncated")
            part = self.parts[self.i]
            chunk = part[self.pos:self.pos + n]
            out += chunk
            self.pos += len(chunk)
            n -= len(chunk)
        return out

    def chars(self, count, high):
        out = []
        while count > 0:
            if self.i >= len(self.parts):
                raise XlsError("shared string table is truncated")
            part = self.parts[self.i]
            width = 2 if high else 1
            fit = min(count, (len(part) - self.pos) // width)
            if fit == 0:
                # No _roll() here: even when the header ended exactly on a
                # record boundary, the characters' record opens with a flag byte.
                # Characters continue in the next record, after a new flag byte.
                self.i += 1
                self.pos = 0
                if self.i >= len(self.parts):
                    raise XlsError("shared string table is truncated")
                high = bool(self.parts[self.i][0] & 1)
                self.pos = 1
                continue
            raw = part[self.pos:self.pos + fit * width]
            out.append(raw.decode("utf-16-le" if high else "latin-1"))
            self.pos += fit * width
            count -= fit
        return "".join(out)


def _sst(parts):
    cur = _Segments(parts)
    _, unique = struct.unpack("<II", cur.take(8))
    strings = []
    for _ in range(unique):
        cch, flags = struct.unpack("<HB", cur.take(3))
        runs = struct.unpack("<H", cur.take(2))[0] if flags & 0x08 else 0
        ext = struct.unpack("<i", cur.take(4))[0] if flags & 0x04 else 0
        strings.append(cur.chars(cch, bool(flags & 1)))
        if runs:
            cur.take(4 * runs)
        if ext > 0:
            cur.take(ext)
    return strings


def _rk(v):
    if v & 0x02:
        n = v >> 2
        if n & 0x20000000:
            n -= 0x40000000
        val = float(n)
    else:
        val = struct.unpack("<d", struct.pack("<Q", (v & 0xFFFFFFFC) << 32))[0]
    return val / 100 if v & 0x01 else val


def _short_string(b, off):
    cch, flags = b[off], b[off + 1]
    if flags & 1:
        return b[off + 2:off + 2 + 2 * cch].decode("utf-16-le", errors="replace")
    return b[off + 2:off + 2 + cch].decode("latin-1")


def _unicode_string(b, off):
    cch, flags = struct.unpack_from("<HB", b, off)
    if flags & 1:
        return b[off + 3:off + 3 + 2 * cch].decode("utf-16-le", errors="replace")
    return b[off + 3:off + 3 + cch].decode("latin-1")


class Book:
    def __init__(self, data):
        self.stream = _workbook_stream(data)
        self.sheets = {}
        self.shared = []
        sst_parts = None
        for pos, rtype, body in _records(self.stream):
            if rtype == 0x0085:  # BOUNDSHEET
                offset = struct.unpack_from("<I", body, 0)[0]
                self.sheets[_short_string(body, 6)] = offset
            elif rtype == 0x00FC:  # SST
                sst_parts = [body]
            elif rtype == 0x003C and sst_parts is not None:  # CONTINUE
                sst_parts.append(body)
            elif sst_parts is not None:
                self.shared = _sst(sst_parts)
                sst_parts = None
            if rtype == 0x000A and self.sheets and pos > 0:  # workbook globals EOF
                break
        if sst_parts is not None:
            self.shared = _sst(sst_parts)

    def rows(self, name):
        cells = {}
        pending = None  # a formula whose text result follows in a STRING record
        for i, (_, rtype, b) in enumerate(_records(self.stream, self.sheets[name])):
            if i and rtype == 0x000A:  # EOF of this sheet
                break
            if rtype == 0x00FD:  # LABELSST
                r, c, _, idx = struct.unpack_from("<HHHI", b)
                cells[(r, c)] = self.shared[idx] if idx < len(self.shared) else None
            elif rtype == 0x0203:  # NUMBER
                r, c, _, v = struct.unpack_from("<HHHd", b)
                cells[(r, c)] = v
            elif rtype == 0x027E:  # RK
                r, c, _, v = struct.unpack_from("<HHHI", b)
                cells[(r, c)] = _rk(v)
            elif rtype == 0x00BD:  # MULRK
                r, first = struct.unpack_from("<HH", b)
                n = (len(b) - 6) // 6
                for k in range(n):
                    v = struct.unpack_from("<I", b, 4 + 6 * k + 2)[0]
                    cells[(r, first + k)] = _rk(v)
            elif rtype == 0x0204:  # LABEL
                r, c = struct.unpack_from("<HH", b)
                cells[(r, c)] = _unicode_string(b, 6)
            elif rtype == 0x0006:  # FORMULA: keep the cached result
                r, c = struct.unpack_from("<HH", b)
                res = b[6:14]
                if res[6:8] == b"\xff\xff":
                    if res[0] == 0:
                        pending = (r, c)
                    elif res[0] == 1:
                        cells[(r, c)] = bool(res[2])
                    else:
                        cells[(r, c)] = None
                else:
                    cells[(r, c)] = struct.unpack("<d", res)[0]
            elif rtype == 0x0207 and pending:  # STRING (formula text result)
                cells[pending] = _unicode_string(b, 0)
                pending = None
        if not cells:
            return []
        n_rows = max(r for r, _ in cells) + 1
        out = [[] for _ in range(n_rows)]
        by_row = {}
        for (r, c), v in cells.items():
            by_row.setdefault(r, {})[c] = v
        for r, cols in by_row.items():
            out[r] = [cols.get(c) for c in range(max(cols) + 1)]
        return out
