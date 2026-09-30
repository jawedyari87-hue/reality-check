"""Salaries by occupation: UK (ONS ASHE) against US (BLS OEWS).

UK  ASHE Table 14.7a, "Full-Time" sheet: gross annual pay for full-time
    employee jobs, by 4-digit occupation (SOC). One zip per edition, ~11 MB.
    Each year's *revised* edition is used when it exists, else the provisional
    one. Occupation codes changed in 2021 (SOC 2010 -> SOC 2020), so each
    occupation lists its code under both.
US  OEWS national estimates (May of each year): annual wages by occupation.
    OEWS annualises hourly pay x 2,080 hours, i.e. a full-time equivalent.

Also: the dollar/pound rate (market) and the World Bank's purchasing-power
parity rate, plus both countries' CPI, so the page can show pay in pounds,
at PPP, and in today's prices. Conversions happen in the browser.

Downloads run once in the background; parsed tables are kept in
data/cache/salaries.json and the big zips are deleted after parsing.
"""

import datetime
import io
import json
import os
import threading
import zipfile

from . import net, series, store
from .xlsx import open_book

START_YEAR = 2014
ASHE_ROOT = ("/employmentandlabourmarket/peopleinwork/earningsandworkinghours/datasets/"
             "occupation4digitsoc2010ashetable14")
ASHE_PAGE = "https://www.ons.gov.uk" + ASHE_ROOT
OEWS_ZIP = "https://www.bls.gov/oes/special-requests/oesm%02dnat.zip"
OEWS_PAGE = "https://www.bls.gov/oes/tables.htm"
PPP_URL = ("https://api.worldbank.org/v2/country/GBR/indicator/PA.NUS.PRVT.PP"
           "?format=json&per_page=200")
PPP_PAGE = "https://data.worldbank.org/indicator/PA.NUS.PRVT.PP"
CACHE_FILE = os.path.join(store.CACHE, "salaries.json")

# uk: SOC 2010 code (editions to 2020) and SOC 2020 code (2021 on); "" = all.
# us: (first year, last year, OEWS code). None = no fair US equivalent.
OCCUPATIONS = [
    {"id": "all", "name": "All full-time jobs", "uk": {"soc10": "", "soc20": ""},
     "us": [(2000, 2100, "00-0000")],
     "note": "Every occupation - the baseline to compare the rest against."},
    {"id": "software", "name": "Software developers",
     "uk": {"soc10": "2136", "soc20": "2134"},
     "us": [(2000, 2018, "15-1132"), (2019, 2020, "15-1256"), (2021, 2100, "15-1252")],
     "note": "UK: 'Programmers and software development professionals'. US: application "
             "developers to 2018; 2019-20 also includes QA testers; 2021 on 'Software developers'."},
    {"id": "it_directors", "name": "IT directors and managers",
     "uk": {"soc10": "1136", "soc20": "1137"}, "us": [(2000, 2100, "11-3021")],
     "note": "US: 'Computer and information systems managers', a broader group than UK IT directors."},
    {"id": "cyber", "name": "Cyber security", "uk": {"soc20": "2135"},
     "us": [(2000, 2018, "15-1122"), (2019, 2100, "15-1212")],
     "note": "UK series starts in 2021, when SOC 2020 gave cyber security its own code."},
    {"id": "data", "name": "Data analysts", "uk": {"soc20": "3544"}, "us": None,
     "note": "UK only, from 2021. The US has no matching 'data analyst' occupation."},
    {"id": "it_support", "name": "IT technicians and support", "uk": {"soc10": "313", "soc20": "313"},
     "us": [(2000, 2018, "15-1151"), (2019, 2100, "15-1232")],
     "note": "US: 'Computer user support specialists'."},
    {"id": "electrical_eng", "name": "Electrical engineers", "uk": {"soc10": "2123", "soc20": "2123"},
     "us": [(2000, 2100, "17-2071")], "note": ""},
    {"id": "finance_analysts", "name": "Finance and investment analysts",
     "uk": {"soc10": "3534", "soc20": "2422"}, "us": [(2000, 2100, "13-2051")],
     "note": "Includes financial advisers in the UK."},
    {"id": "consultants", "name": "Management consultants and business analysts",
     "uk": {"soc10": "2423", "soc20": "2431"}, "us": [(2000, 2100, "13-1111")],
     "note": "US: 'Management analysts'."},
    {"id": "lawyers", "name": "Solicitors and lawyers", "uk": {"soc10": "2413", "soc20": "2412"},
     "us": [(2000, 2100, "23-1011")], "note": "UK to 2020: solicitors only."},
    {"id": "teachers", "name": "Secondary school teachers", "uk": {"soc10": "2314", "soc20": "2313"},
     "us": [(2000, 2100, "25-2031")], "note": ""},
    {"id": "nurses", "name": "Nurses", "uk": {"soc10": "2231", "soc20": "223"},
     "us": [(2000, 2100, "29-1141")], "note": "US: registered nurses."},
]

_job = {"running": False, "message": "", "done": 0, "total": 0, "error": None, "finished": None}
_job_lock = threading.Lock()


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _code(v):
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v or "").strip()


# --------------------------------------------------------------------------
# ASHE (UK)
# --------------------------------------------------------------------------

def parse_ashe(rows, year):
    """One Table 14.7a 'Full-Time' sheet -> {occupation id: figures}."""
    head_i = next((i for i, r in enumerate(rows[:15]) if r and str(r[0]).strip() == "Description"), None)
    if head_i is None:
        return {}
    head = rows[head_i]
    pct = {int(_num(h)): i for i, h in enumerate(head) if _num(h) in (10, 25, 75, 90)}
    by_code, all_row = {}, None
    for r in rows[head_i + 1:]:
        if not r or not isinstance(r[0], str):
            continue
        if r[0].strip() == "All employees":
            all_row = r
            continue
        code = _code(r[1] if len(r) > 1 else "")
        if code and code not in by_code:
            by_code[code] = r
    soc = "soc20" if year >= 2021 else "soc10"

    def pick(i, r):
        return _num(r[i]) if i is not None and i < len(r) else None

    out = {}
    for occ in OCCUPATIONS:
        code = occ["uk"].get(soc)
        if code is None:
            continue
        r = all_row if code == "" else by_code.get(code)
        if not r:
            continue
        item = {"year": year, "soc": soc.upper().replace("SOC", "SOC "), "code": code,
                "title": str(r[0]).strip(), "jobs": pick(2, r), "median": pick(3, r),
                "mean": pick(5, r), "p10": pick(pct.get(10), r), "p25": pick(pct.get(25), r),
                "p75": pick(pct.get(75), r), "p90": pick(pct.get(90), r)}
        if item["jobs"] is not None:
            item["jobs"] = item["jobs"] * 1000
        if item["median"] or item["mean"]:
            out[occ["id"]] = item
    return out


def _ashe_editions():
    body, _ = net.fetch(ASHE_PAGE + "/data", "ashe14_index.json", 24 * 7)
    names = [d["uri"].rsplit("/", 1)[1] for d in json.loads(body).get("datasets", [])]
    by_year = {}
    for name in names:
        y = int(name[:4]) if name[:4].isdigit() else None
        if not y or y < START_YEAR:
            continue
        rank = 3 if "revised" in name else 2 if "provisional" in name else 1
        if "soc2010" in name.lower() and y >= 2021:
            continue
        if rank > by_year.get(y, ("", 0))[1]:
            by_year[y] = (name, rank)
    return {y: v[0] for y, v in sorted(by_year.items())}


def _fetch_ashe_edition(edition):
    meta = json.loads(net.get(ASHE_PAGE + "/" + edition + "/data"))
    fn = meta["downloads"][0]["file"]
    url = "https://www.ons.gov.uk/file?uri=%s/%s/%s" % (ASHE_ROOT, edition, fn)
    body, _ = net.fetch(url, "ashe14_" + edition + ".zip", 24 * 365)
    try:
        z = zipfile.ZipFile(io.BytesIO(body))
        name = next(n for n in z.namelist() if "14.7a" in n and "CV" not in n)
        return parse_ashe(open_book(z.read(name)).rows("Full-Time"), int(edition[:4]))
    finally:
        try:
            os.remove(net.raw_path("ashe14_" + edition + ".zip"))  # 11 MB each: keep only the numbers
        except OSError:
            pass


# --------------------------------------------------------------------------
# OEWS (US)
# --------------------------------------------------------------------------

def parse_oews(rows, year):
    head_i = next((i for i, r in enumerate(rows[:10])
                   if r and any(str(x).strip().upper() == "OCC_CODE" for x in r)), None)
    if head_i is None:
        return {}
    col = {str(h).strip().upper(): i for i, h in enumerate(rows[head_i]) if h is not None}
    by_code = {}
    for r in rows[head_i + 1:]:
        i = col.get("OCC_CODE")
        if i is None or i >= len(r):
            continue
        code = str(r[i]).strip()
        if code and code not in by_code:
            by_code[code] = r
    out = {}
    for occ in OCCUPATIONS:
        code = next((c for a, b, c in (occ["us"] or []) if a <= year <= b), None)
        r = by_code.get(code) if code else None
        if not r:
            continue

        def get(name):
            i = col.get(name)
            return r[i] if i is not None and i < len(r) else None

        item = {"year": year, "code": code, "title": str(get("OCC_TITLE") or "").strip(),
                "jobs": _num(get("TOT_EMP")), "topcoded": []}
        for key, name in (("median", "A_MEDIAN"), ("mean", "A_MEAN"), ("p10", "A_PCT10"),
                          ("p25", "A_PCT25"), ("p75", "A_PCT75"), ("p90", "A_PCT90")):
            raw = get(name)
            item[key] = _num(raw)
            if str(raw).strip() == "#":
                item["topcoded"].append(key)  # BLS only says "at least $239,200"
        if item["median"] or item["mean"]:
            out[occ["id"]] = item
    return out


def _fetch_oews(year):
    url = OEWS_ZIP % (year % 100)
    name = "oews_%d.zip" % year
    try:
        body, _ = net.fetch(url, name, 24 * 365)
    except net.FetchError as e:
        if "404" in str(e):
            return None  # not published yet
        raise
    z = zipfile.ZipFile(io.BytesIO(body))
    member = next((n for n in z.namelist()
                   if "national" in n.lower() and n.lower().endswith((".xlsx", ".xls"))), None)
    if not member:
        return {}
    book = open_book(z.read(member))
    for sheet in book.sheets:
        rows = book.rows(sheet)
        parsed = parse_oews(rows, year)
        if parsed:
            return parsed
    return {}


# --------------------------------------------------------------------------
# Conversions
# --------------------------------------------------------------------------

def _ppp():
    body, _ = net.fetch(PPP_URL, "worldbank_ppp_gbr.json", 24 * 30)
    data = json.loads(body)
    rows = data[1] if isinstance(data, list) and len(data) > 1 and data[1] else []
    return {int(r["date"]): r["value"] for r in rows if r.get("value") is not None}


def _fx():
    return {int(d[:4]): v for d, v in series.load("fx.usd_per_gbp")["points"]}


# --------------------------------------------------------------------------
# Refresh job + API payload
# --------------------------------------------------------------------------

def _cached():
    return store.read_json(CACHE_FILE, {"uk": {}, "us": {}}) or {"uk": {}, "us": {}}


def has_data():
    return bool(_cached().get("uk"))


def job_status():
    with _job_lock:
        return dict(_job)


def start_refresh(force=False):
    with _job_lock:
        if _job["running"]:
            return False
        _job.update(running=True, message="Starting", done=0, total=0, error=None)
    threading.Thread(target=_refresh, args=(force,), daemon=True).start()
    return True


def _set(**kw):
    with _job_lock:
        _job.update(kw)


def _refresh(force):
    cache = _cached()
    try:
        _set(message="Checking which ONS editions exist")
        editions = _ashe_editions()
        this_year = datetime.date.today().year
        us_years = list(range(START_YEAR, this_year))
        todo_uk = [(y, ed) for y, ed in editions.items()
                   if force or (cache["uk"].get(str(y)) or {}).get("edition") != ed]
        todo_us = [y for y in us_years if force or str(y) not in cache["us"]]
        _set(total=len(todo_uk) + len(todo_us))
        for y, ed in todo_uk:
            _set(message="UK %d: downloading ONS ASHE (%s, about 11 MB)" % (y, ed))
            cache["uk"][str(y)] = {"edition": ed, "rows": _fetch_ashe_edition(ed)}
            store.write_json(CACHE_FILE, cache)
            _set(done=job_status()["done"] + 1)
        for y in todo_us:
            _set(message="US %d: downloading BLS OEWS" % y)
            parsed = _fetch_oews(y)
            if parsed is not None:
                cache["us"][str(y)] = {"rows": parsed}
                store.write_json(CACHE_FILE, cache)
            _set(done=job_status()["done"] + 1)
        cache["updated"] = store.now_iso()
        store.write_json(CACHE_FILE, cache)
        _set(message="Up to date", finished=store.now_iso())
    except Exception as e:  # keep what was saved; report the rest
        _set(error=str(e), message="Stopped: %s" % e)
    finally:
        _set(running=False)


def build():
    cache = _cached()
    uk, us = {}, {}
    for y, ed in sorted(cache.get("uk", {}).items()):
        for occ_id, item in (ed.get("rows") or {}).items():
            uk.setdefault(occ_id, []).append(dict(item, edition=ed.get("edition")))
    for y, ed in sorted(cache.get("us", {}).items()):
        for occ_id, item in (ed.get("rows") or {}).items():
            us.setdefault(occ_id, []).append(item)
    out = {
        "occupations": [{"id": o["id"], "name": o["name"], "note": o["note"],
                         "hasUS": bool(o["us"])} for o in OCCUPATIONS],
        "uk": uk, "us": us, "updated": cache.get("updated"),
        "sources": {
            "uk": {"name": "ONS Annual Survey of Hours and Earnings, Table 14.7a (full-time)",
                   "url": ASHE_PAGE},
            "us": {"name": "BLS Occupational Employment and Wage Statistics (May each year)",
                   "url": OEWS_PAGE},
            "fx": {"name": "Federal Reserve annual average USD/GBP (via FRED)",
                   "url": series.FRED_PAGE % "AEXUSUK"},
            "ppp": {"name": "World Bank PPP conversion factor, private consumption",
                    "url": PPP_PAGE},
        },
        "job": job_status(),
    }
    for key, fn in (("fx", _fx), ("ppp", _ppp),
                    ("cpiUK", lambda: series.annual("uk.cpi_index")),
                    ("cpiUS", lambda: series.annual("us.cpi_index"))):
        try:
            out[key] = {str(k): v for k, v in fn().items()}
        except Exception as e:
            out[key] = {}
            out.setdefault("warnings", []).append("%s unavailable: %s" % (key, e))
    return out
