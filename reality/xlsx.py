"""Read .xlsx workbooks with the standard library (zipfile + ElementTree).

Only cell values are read: shared strings, inline strings and numbers.
`Book(data).rows(sheet)` returns a list of rows, each a list of cell values
(None where a cell is empty), so row/column positions match the spreadsheet.
"""

import io
import zipfile
import xml.etree.ElementTree as ET

_M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS = {"m": _M, "r": _R}


def _col(ref):
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


class Book:
    def __init__(self, data):
        self.z = zipfile.ZipFile(io.BytesIO(data))
        self.shared = []
        if "xl/sharedStrings.xml" in self.z.namelist():
            root = ET.fromstring(self.z.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", _NS):
                self.shared.append("".join(t.text or "" for t in si.iter("{%s}t" % _M)))
        wb = ET.fromstring(self.z.read("xl/workbook.xml"))
        rels = ET.fromstring(self.z.read("xl/_rels/workbook.xml.rels"))
        targets = {r.get("Id"): r.get("Target") for r in rels}
        self.sheets = {}
        for s in wb.find("m:sheets", _NS):
            target = targets[s.get("{%s}id" % _R)].lstrip("/")
            if not target.startswith("xl/"):
                target = "xl/" + target
            self.sheets[s.get("name")] = target

    def rows(self, name):
        root = ET.fromstring(self.z.read(self.sheets[name]))
        out = []
        for row in root.iter("{%s}row" % _M):
            cells = {}
            for c in row.findall("m:c", _NS):
                t, v = c.get("t"), c.find("m:v", _NS)
                if t == "s" and v is not None:
                    val = self.shared[int(v.text)]
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter("{%s}t" % _M))
                elif t == "str" and v is not None:
                    val = v.text
                elif v is not None:
                    try:
                        val = float(v.text)
                    except (TypeError, ValueError):
                        val = v.text
                else:
                    val = None
                cells[_col(c.get("r"))] = val
            r = int(row.get("r"))
            while len(out) < r - 1:
                out.append([])
            out.append([cells.get(i) for i in range(max(cells) + 1)] if cells else [])
        return out


def open_book(data):
    """Open either format: .xlsx is a zip, .xls is an OLE2 container."""
    if data[:2] == b"PK":
        return Book(data)
    from . import xls
    return xls.Book(data)
