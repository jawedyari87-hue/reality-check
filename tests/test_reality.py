"""Offline tests: no network, a throwaway data folder.

Run from the app folder:  py -3 -m unittest discover -s tests
"""

import atexit
import datetime
import io
import json
import os
import shutil
import struct
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile

_TMP = tempfile.mkdtemp(prefix="reality-test-")
atexit.register(shutil.rmtree, _TMP, ignore_errors=True)
os.environ["REALITY_DATA"] = _TMP
os.environ["REALITY_OFFLINE"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reality import checks, forecasts, salaries, series, xls, xlsx  # noqa: E402
import server  # noqa: E402


# --------------------------------------------------------------------------
# Tiny workbook builders
# --------------------------------------------------------------------------

def make_xlsx(rows, shared):
    """rows: list of lists; str cells go through the shared-string table."""
    def ref(r, c):
        col = ""
        c += 1
        while c:
            c, rem = divmod(c - 1, 26)
            col = chr(65 + rem) + col
        return "%s%d" % (col, r + 1)
    cells = []
    for r, row in enumerate(rows):
        cs = []
        for c, v in enumerate(row):
            if v is None:
                continue
            if isinstance(v, str):
                cs.append('<c r="%s" t="s"><v>%d</v></c>' % (ref(r, c), shared.index(v)))
            else:
                cs.append('<c r="%s"><v>%s</v></c>' % (ref(r, c), v))
        cells.append('<row r="%d">%s</row>' % (r + 1, "".join(cs)))
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", '<workbook %s xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   '<sheets><sheet name="Full-Time" sheetId="1" r:id="rId1"/></sheets></workbook>' % ns)
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/></Relationships>')
        z.writestr("xl/sharedStrings.xml", "<sst %s>%s</sst>" % (ns, "".join("<si><t>%s</t></si>" % s for s in shared)))
        z.writestr("xl/worksheets/sheet1.xml", "<worksheet %s><sheetData>%s</sheetData></worksheet>" % (ns, "".join(cells)))
    return buf.getvalue()


def _rec(rtype, body):
    return struct.pack("<HH", rtype, len(body)) + body


def make_xls(sheet_name, sst_records, cell_records):
    """A minimal BIFF8 workbook inside a minimal OLE2 container."""
    bof = _rec(0x0809, struct.pack("<HHHHII", 0x0600, 0x0005, 0, 0, 0, 0))
    name = sheet_name.encode("latin-1")
    sheet_body = lambda off: struct.pack("<IBB", off, 0, 0) + bytes([len(name), 0]) + name
    globals_len = len(bof) + len(_rec(0x0085, sheet_body(0))) + sum(len(r) for r in sst_records) + 4
    sheet = bof + b"".join(cell_records) + _rec(0x000A, b"")
    stream = bof + _rec(0x0085, sheet_body(globals_len)) + b"".join(sst_records) + _rec(0x000A, b"") + sheet
    stream += b"\0" * max(0, 4096 - len(stream))  # keep it out of the mini stream
    n = -(-len(stream) // 512)
    data = stream + b"\0" * (n * 512 - len(stream))
    dir_sector = n
    fat_sector = n + 1
    fat = [i + 1 for i in range(n - 1)] + [0xFFFFFFFE, 0xFFFFFFFE, 0xFFFFFFFD]
    fat += [0xFFFFFFFF] * (128 - len(fat))

    def entry(nm, kind, start, size):
        raw = nm.encode("utf-16-le")
        e = raw + b"\0" * (64 - len(raw))
        e += struct.pack("<HBB", len(raw) + 2, kind, 1) + struct.pack("<III", 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF)
        e += b"\0" * 16 + b"\0" * 4 + b"\0" * 16 + struct.pack("<III", start, size, 0)
        return e
    directory = entry("Root Entry", 5, 0xFFFFFFFE, 0) + entry("Workbook", 2, 0, len(stream))
    directory += b"\0" * (512 - len(directory))
    header = bytearray(512)
    header[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<HHHHH", header, 0x18, 0x3E, 3, 0xFFFE, 9, 6)
    struct.pack_into("<I", header, 0x2C, 1)
    struct.pack_into("<I", header, 0x30, dir_sector)
    struct.pack_into("<I", header, 0x38, 4096)
    struct.pack_into("<IIII", header, 0x3C, 0xFFFFFFFE, 0, 0xFFFFFFFE, 0)
    difat = [fat_sector] + [0xFFFFFFFF] * 108
    struct.pack_into("<109I", header, 0x4C, *difat)
    return bytes(header) + data + directory + struct.pack("<128I", *fat)


class Readers(unittest.TestCase):
    def test_xlsx_rows_keep_positions(self):
        data = make_xlsx([["Description", "Code", None, "Median"], ["All employees", "", None, 39039.0]],
                         ["Description", "Code", "Median", "All employees", ""])
        rows = xlsx.open_book(data).rows("Full-Time")
        self.assertEqual(rows[0][3], "Median")
        self.assertIsNone(rows[1][2])
        self.assertEqual(rows[1][3], 39039.0)

    def test_xls_shared_strings_split_across_continue(self):
        s1, s2, s3 = "Programmers", "Median pay", "Software"
        # SST: string 1 whole; string 2 has its header at the very end of the
        # record, so its characters start in CONTINUE behind a flag byte;
        # string 3 switches to 16-bit characters halfway through.
        head = struct.pack("<II", 3, 3)
        str1 = struct.pack("<HB", len(s1), 0) + s1.encode("latin-1")
        str2_head = struct.pack("<HB", len(s2), 0)
        sst = _rec(0x00FC, head + str1 + str2_head)
        cont1 = _rec(0x003C, b"\x00" + s2.encode("latin-1") + struct.pack("<HB", len(s3), 0) + s3[:4].encode("latin-1"))
        cont2 = _rec(0x003C, b"\x01" + s3[4:].encode("utf-16-le"))
        cells = [
            _rec(0x00FD, struct.pack("<HHHI", 0, 0, 0, 0)),          # A1 = s1
            _rec(0x00FD, struct.pack("<HHHI", 0, 1, 0, 1)),          # B1 = s2
            _rec(0x00FD, struct.pack("<HHHI", 0, 2, 0, 2)),          # C1 = s3
            _rec(0x0203, struct.pack("<HHHd", 1, 0, 0, 56914.0)),    # A2 NUMBER
            _rec(0x027E, struct.pack("<HHHI", 1, 1, 0, (123 << 2) | 0x02)),  # B2 RK int
            _rec(0x027E, struct.pack("<HHHI", 1, 2, 0, (4250 << 2) | 0x03)),  # C2 RK int/100
            _rec(0x00BD, struct.pack("<HH", 2, 0) + struct.pack("<HI", 0, (7 << 2) | 2)
                 + struct.pack("<HI", 0, (8 << 2) | 2) + struct.pack("<H", 1)),  # MULRK A3:B3
            _rec(0x0006, struct.pack("<HHH", 3, 0, 0) + struct.pack("<d", 3.5) + b"\0" * 6),  # FORMULA
        ]
        book = xls.Book(make_xls("Full-Time", [sst, cont1, cont2], cells))
        self.assertIn("Full-Time", book.sheets)
        rows = book.rows("Full-Time")
        self.assertEqual(rows[0], ["Programmers", "Median pay", "Software"])
        self.assertEqual(rows[1], [56914.0, 123.0, 42.5])
        self.assertEqual(rows[2], [7.0, 8.0])
        self.assertEqual(rows[3], [3.5])

    def test_open_book_rejects_other_files(self):
        with self.assertRaises(xls.XlsError):
            xlsx.open_book(b"not a spreadsheet at all")


class Parsers(unittest.TestCase):
    def test_ons_months_and_years(self):
        body = json.dumps({"months": [{"date": "2026 JUN", "value": "4.9"}, {"date": "2026 MAY", "value": "4.8"},
                                      {"date": "2026 APR", "value": ""}],
                           "years": [{"date": "2025", "value": "4.9"}]}).encode()
        points, years = series.parse_ons(body)
        self.assertEqual(points, [["2026-05-01", 4.8], ["2026-06-01", 4.9]])
        self.assertEqual(years, {2025: 4.9})

    def test_fred_skips_missing(self):
        body = b"observation_date,UNRATE\n2025-09-01,4.4\n2025-10-01,.\n2025-11-01,4.5\n"
        self.assertEqual(series.parse_fred(body), [["2025-09-01", 4.4], ["2025-11-01", 4.5]])

    def test_indeed_weekly_sampling_keeps_latest(self):
        lines = ["date,jobcountry,indeed_job_postings_index,variable,display_name"]
        start = datetime.date(2026, 1, 1)
        for i in range(20):
            d = (start + datetime.timedelta(days=i)).isoformat()
            lines.append("%s,GB,%d,total postings,Software Development" % (d, 100 + i))
            lines.append("%s,GB,1,new postings,Software Development" % d)
        out = series.parse_indeed_sectors("\n".join(lines).encode())["Software Development"]
        self.assertEqual(out[-1], ["2026-01-20", 119.0])
        self.assertEqual([p[0] for p in out], ["2026-01-06", "2026-01-13", "2026-01-20"])

    def test_periods_per_year(self):
        monthly = [["2025-%02d-01" % m, 1] for m in range(1, 13)]
        self.assertEqual(series.periods_per_year(monthly), 12)
        self.assertEqual(series.periods_per_year([["2020-07-01", 1], ["2021-07-01", 1], ["2022-07-01", 1]]), 1)


class Checks(unittest.TestCase):
    TODAY = datetime.date(2026, 9, 19)

    @staticmethod
    def _monthly():
        # Monthly readings Jan 2024 - Jun 2026: 4.0, then 4.4 from Jun 2024,
        # a one-month spike to 5.1 in Jan 2025, 4.8 after, 4.9 in Jun 2026.
        out = []
        for y in (2024, 2025, 2026):
            for m in range(1, 13):
                if (y, m) > (2026, 6):
                    break
                v = 4.0 if (y, m) < (2024, 6) else 4.4 if y == 2024 else 5.1 if (y, m) == (2025, 1) else 4.8
                out.append(["%d-%02d-01" % (y, m), 4.9 if (y, m) == (2026, 6) else v])
        return {"points": out}

    DATA = _monthly.__func__()

    def ev(self, **check):
        check.setdefault("series", "uk.unemployment")
        return checks.evaluate(check, self.TODAY, self.DATA)

    def test_reach_came_true_on_first_hit(self):
        r = self.ev(test="reach", op=">=", value=5, start="2024-01-01", end="2025-12-01")
        self.assertEqual(r["status"], "true")
        self.assertEqual(r["hit"]["date"], "2025-01-01")

    def test_reach_failed_after_window(self):
        r = self.ev(test="reach", op=">=", value=6, start="2024-01-01", end="2025-12-01")
        self.assertEqual(r["status"], "false")
        self.assertEqual(r["extreme"], 5.1)

    def test_reach_pending_inside_window(self):
        r = self.ev(test="reach", op=">=", value=10, start="2026-01-01", end="2030-05-28")
        self.assertEqual(r["status"], "pending")
        self.assertFalse(r["onTrack"])

    def test_awaiting_when_deadline_passed_but_no_figures(self):
        r = self.ev(test="level", op=">=", value=4, end="2026-09-01")
        self.assertEqual(r["status"], "awaiting")

    def test_change_resolves_on_deadline(self):
        r = self.ev(test="change", op=">=", pct=10, start="2024-01-01", end="2025-06-01")
        self.assertEqual(r["status"], "true")
        self.assertAlmostEqual(r["changePct"], 20.0)
        r = self.ev(test="change", op="<=", pct=0, start="2024-01-01", end="2025-06-01")
        self.assertEqual(r["status"], "false")

    def test_change_with_no_deadline_stays_open(self):
        r = self.ev(test="change", op=">=", pct=20, start="2024-06-01", end=None)
        self.assertEqual(r["status"], "open")
        self.assertAlmostEqual(r["changePct"], (4.9 / 4.4 - 1) * 100, places=2)

    def test_combine_and_brier(self):
        self.assertEqual(checks.combine([{"status": "true"}, {"status": "pending"}]), "pending")
        self.assertEqual(checks.combine([{"status": "true"}, {"status": "false"}]), "false")
        self.assertEqual(checks.combine([{"status": "true"}, {"status": "true"}]), "true")
        b = checks.brier([{"status": "true", "confidence": 70}, {"status": "false", "confidence": 20},
                          {"status": "pending", "confidence": 90}])
        self.assertEqual(b, {"n": 2, "score": 0.065})


class Forecasts(unittest.TestCase):
    def test_obr_sheet_and_scoring(self):
        rows = [["ILO unemployment rate"], [], [],
                ["Back to contents", 2023.0, 2024.0, 2025.0],
                ["March 2023", 4.0, 4.4, 4.3],
                ["March 2024", None, 4.4, 4.5],
                [],
                ["Outturn data*", 4.0, 4.3, None]]
        vintages, outturn = forecasts.parse_obr_sheet(rows)
        self.assertEqual([v["label"] for v in vintages], ["March 2023", "March 2024"])
        self.assertEqual(outturn, {2023: 4.0, 2024: 4.3})
        errors, by_h, misses = forecasts.score(vintages, outturn, 0.5, "above")
        h1 = next(h for h in by_h if h["horizon"] == 1)
        self.assertEqual(h1["n"], 1)
        self.assertAlmostEqual(h1["bias"], 0.1)
        self.assertEqual(h1["tooGloomy"], 1.0)

    def test_spf_annual_columns(self):
        rows = [["YEAR", "QUARTER", "UNEMP1", "UNEMP2", "UNEMP3", "UNEMP4", "UNEMP5", "UNEMP6",
                 "UNEMPA", "UNEMPB", "UNEMPC", "UNEMPD"],
                [2024.0, 1.0, 3.7, 3.8, 3.9, 4.0, 4.0, 4.1, 3.9, 4.1, "#N/A", "#N/A"]]
        v = forecasts.parse_spf_sheet(rows)
        self.assertEqual(v[0]["points"], [[2024, 3.9], [2025, 4.1]])
        self.assertEqual(v[0]["date"], "2024-02")


class Salaries(unittest.TestCase):
    def test_ashe_uses_soc_version_by_year(self):
        rows = [["Table 14.7a"], [], [], [],
                ["Description", "Code", "(thousand)", "Median", "change", "Mean", "change", 10.0, 20.0, 25.0, 30.0, 40.0, 60.0, 70.0, 75.0, 80.0, 90.0],
                ["All employees", "", 18154.0, 39039.0, 4.3, 48512.0, 6.0, 23990.0, 1, 29262.0, 1, 1, 1, 1, 54009.0, 1, 76903.0],
                ["   Programmers and software development professionals ", "2134", 343.0, 56914.0, 4.2, 63810.0, 0.7, 32835.0, 1, 42289.0, 1, 1, 1, 1, 75794.0, 1, 102860.0],
                ["   IT quality and testing professionals", "2136", "x", 38649.0, None, 38272.0, None, "x", "x", "x", "x", "x", "x", "x", "x", "x", "x"]]
        out = salaries.parse_ashe(rows, 2025)
        self.assertEqual(out["software"]["median"], 56914.0)
        self.assertEqual(out["software"]["p25"], 42289.0)
        self.assertEqual(out["software"]["jobs"], 343000.0)
        self.assertEqual(out["all"]["p90"], 76903.0)
        # In a SOC 2010 year, 2136 *is* software developers.
        self.assertEqual(salaries.parse_ashe(rows, 2019)["software"]["median"], 38649.0)

    def test_oews_topcoded_values(self):
        rows = [["OCC_CODE", "OCC_TITLE", "TOT_EMP", "A_MEAN", "A_PCT10", "A_PCT25", "A_MEDIAN", "A_PCT75", "A_PCT90"],
                ["15-1252", "Software Developers", "1,654,440", "148,100", "80,000", "105,000", "135,980", "170,000", "#"]]
        out = salaries.parse_oews(rows, 2025)
        self.assertEqual(out["software"]["median"], 135980.0)
        self.assertIsNone(out["software"]["p90"])
        self.assertEqual(out["software"]["topcoded"], ["p90"])


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.Server(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def post(self, path, body, headers=None):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", **(headers or {})}, method="POST")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read() or b"{}")

    def test_cross_site_writes_refused(self):
        item = {"claim": "x", "confidence": 50,
                "check": {"series": "uk.unemployment", "test": "reach", "op": ">=", "value": 6, "end": "2030-01-01"}}
        code, _ = self.post("/api/mine", {"action": "add", "item": item}, {"Origin": "http://evil.example"})
        self.assertEqual(code, 403)
        code, _ = self.post("/api/mine", {"action": "add", "item": item}, {"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(code, 403)

    def test_prediction_round_trip_and_validation(self):
        good = {"claim": "UK unemployment reaches 6%", "confidence": 30,
                "check": {"series": "uk.unemployment", "test": "reach", "op": ">=", "value": 6, "end": "2030-01-01"}}
        code, data = self.post("/api/mine", {"action": "add", "item": good})
        self.assertEqual(code, 200)
        added = [i for i in data["items"] if i["claim"] == good["claim"]][0]
        self.assertEqual(added["checks"][0]["start"], datetime.date.today().isoformat())
        code, data = self.post("/api/mine", {"action": "delete", "id": added["id"]})
        self.assertFalse(any(i["id"] == added["id"] for i in data["items"]))
        for bad, msg in (({**good, "confidence": 100}, "between 1 and 99"),
                         ({**good, "check": {**good["check"], "end": ""}}, "deadline"),
                         ({**good, "check": {**good["check"], "series": "nope"}}, "data series"),
                         ({**good, "claim": "  "}, "write the prediction")):
            code, data = self.post("/api/mine", {"action": "add", "item": bad})
            self.assertEqual(code, 400)
            self.assertIn(msg, data["error"])

    def test_static_files_cannot_escape_web_folder(self):
        for path in ("/../server.py", "/%2e%2e/server.py", "/..%5cserver.py"):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen("http://127.0.0.1:%d%s" % (self.port, path))
            cm.exception.close()
            self.assertEqual(cm.exception.code, 404)


class Content(unittest.TestCase):
    def test_famous_predictions_are_well_formed(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "content", "famous.json"),
                  encoding="utf-8") as fh:
            items = json.load(fh)["items"]
        ids = set()
        for i in items:
            self.assertNotIn(i["id"], ids)
            ids.add(i["id"])
            self.assertTrue(i["sources"], i["id"])
            for s in i["sources"]:
                self.assertTrue(s["url"].startswith("https://"), i["id"])
            for c in i.get("checks") or []:
                self.assertIn(c["series"], series.BY_ID, i["id"])
                self.assertIn(c["test"], ("reach", "change", "level"))
            for sid in i.get("context") or []:
                self.assertIn(sid, series.BY_ID, i["id"])
            if i.get("quote"):
                self.assertLessEqual(len(i["quote"].split()), 15, i["id"])


if __name__ == "__main__":
    unittest.main()
