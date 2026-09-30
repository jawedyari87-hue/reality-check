"""Official forecasts versus what actually happened.

UK: the Office for Budget Responsibility's Historical Official Forecasts
    Database - every forecast the OBR has published since June 2010, for
    unemployment, employment and earnings growth (calendar-year averages).
US: the Philadelphia Fed's Survey of Professional Forecasters - the median
    unemployment forecast of professional economists, every quarter since 1968.

Each forecast is scored against the outturn: error = forecast - actual,
grouped by how far ahead it looked (horizon, in years).
"""

import datetime
import re

from . import net, series
from .xlsx import open_book

OBR_DATA_PAGE = "https://obr.uk/data/"
OBR_FALLBACK = "https://obr.uk/download/historical-official-forecasts-database-march-2025/"
SPF_URL = ("https://www.philadelphiafed.org/-/media/frbp/assets/surveys-and-data/"
           "survey-of-professional-forecasters/historical-data/medianlevel.xlsx")
SPF_PAGE = ("https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/"
            "survey-of-professional-forecasters")
TTL_HOURS = 24 * 7

SETS = {
    "obr-unemployment": {
        "country": "UK", "source": "obr", "sheet": "Unemplrate",
        "name": "UK unemployment rate", "unit": "%", "decimals": 1,
        "who": "Office for Budget Responsibility",
        "fill": ("uk.unemployment", 1.0), "tolerance": 0.5, "pessimistic": "above",
        "live": "uk.unemployment",
        "what": "Calendar-year average ILO unemployment rate.",
    },
    "obr-employment": {
        "country": "UK", "source": "obr", "sheet": "Empl",
        "name": "UK employment (people in work)", "unit": "million", "decimals": 2,
        "who": "Office for Budget Responsibility",
        "fill": ("uk.employment", 0.001), "tolerance": 0.3, "pessimistic": "below",
        "live": "uk.employment", "liveScale": 0.001,
        "what": "Calendar-year average number of people in work, 16+.",
    },
    "obr-earnings": {
        "country": "UK", "source": "obr", "sheet": "Earnings",
        "name": "UK average earnings growth", "unit": "%", "decimals": 1,
        "who": "Office for Budget Responsibility",
        "fill": None, "tolerance": 1.0, "pessimistic": "below",
        "live": "uk.pay_growth",
        "what": "Growth in average earnings (wages and salaries per employee) on a year earlier.",
    },
    "spf-unemployment": {
        "country": "US", "source": "spf", "sheet": "UNEMP",
        "name": "US unemployment rate", "unit": "%", "decimals": 1,
        "who": "Survey of Professional Forecasters (median)",
        "tolerance": 0.5, "pessimistic": "above", "live": "us.unemployment",
        "what": "Calendar-year average unemployment rate.",
    },
}

_MONTH_NAMES = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}


def _num(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _obr_url():
    """The OBR renames the file each release; the data page links the latest."""
    try:
        html, _ = net.fetch(OBR_DATA_PAGE, "obr_data_page.html", TTL_HOURS)
        m = re.search(r'https://obr\.uk/download/historical-official-forecasts-database[^"\'?#\s]*',
                      html.decode("utf-8", errors="replace"))
        if m:
            return m.group(0)
    except net.FetchError:
        pass
    return OBR_FALLBACK


def parse_obr_sheet(rows):
    """Rows of one OBR sheet -> (vintages, outturn {year: value})."""
    header = next((r for r in rows if r and any(_num(x) and 1990 < _num(x) < 2100 for x in r[1:])), None)
    if header is None:
        return [], {}
    years = {i: int(_num(x)) for i, x in enumerate(header) if i and _num(x) and 1990 < _num(x) < 2100}
    vintages, outturn = [], {}
    for r in rows:
        if not r or not isinstance(r[0], str):
            continue
        label = r[0].strip()
        values = {years[i]: _num(r[i]) for i in years if i < len(r) and _num(r[i]) is not None}
        if not values:
            continue
        if label.lower().startswith("outturn"):
            outturn = values
            continue
        m = re.match(r"([A-Za-z]+)\s+(\d{4})$", label)
        if not m or m.group(1).lower() not in _MONTH_NAMES:
            continue
        month, year = _MONTH_NAMES[m.group(1).lower()], int(m.group(2))
        vintages.append({"label": label, "date": "%d-%02d" % (year, month),
                         "points": sorted([y, v] for y, v in values.items())})
    vintages.sort(key=lambda v: v["date"])
    return vintages, outturn


def parse_spf_sheet(rows):
    """SPF median levels -> vintages. Columns: YEAR, QUARTER, 1-6 quarterly,
    then A-D = annual averages for this year and the next three."""
    header = rows[0] if rows else []
    col = {str(h).upper(): i for i, h in enumerate(header) if h is not None}
    out = []
    for r in rows[1:]:
        y, q = (_num(r[0]) if r else None), (_num(r[1]) if len(r) > 1 else None)
        if not y or not q:
            continue
        y, q = int(y), int(q)
        points = []
        for k, suffix in enumerate("ABCD"):
            i = col.get("UNEMP" + suffix)
            v = _num(r[i]) if i is not None and i < len(r) else None
            if v is not None:
                points.append([y + k, v])
        if points:
            out.append({"label": "%d Q%d survey" % (y, q), "date": "%d-%02d" % (y, 3 * q - 1),
                        "quarter": q, "points": points})
    return out


def _load_book(source):
    if source == "obr":
        body, info = net.fetch(_obr_url(), "obr_historical_forecasts.xlsx", TTL_HOURS)
    else:
        body, info = net.fetch(SPF_URL, "spf_medianlevel.xlsx", TTL_HOURS)
    return open_book(body), info


def score(vintages, actual, tolerance, pessimistic):
    errors = []
    for v in vintages:
        vy = int(v["date"][:4])
        for year, f in v["points"]:
            h = year - vy
            if h < 0 or h > 5 or year not in actual:
                continue
            e = f - actual[year]
            errors.append({"vintage": v["label"], "date": v["date"], "year": year, "horizon": h,
                           "forecast": round(f, 3), "actual": round(actual[year], 3),
                           "error": round(e, 3)})
    by_h = []
    for h in sorted({e["horizon"] for e in errors}):
        es = [e["error"] for e in errors if e["horizon"] == h]
        gloomy = [x for x in es if (x > 0 if pessimistic == "above" else x < 0)]
        by_h.append({"horizon": h, "n": len(es),
                     "mae": round(sum(abs(x) for x in es) / len(es), 3),
                     "bias": round(sum(es) / len(es), 3),
                     "within": round(sum(1 for x in es if abs(x) <= tolerance) / len(es), 3),
                     "tooGloomy": round(len(gloomy) / len(es), 3)})
    misses = sorted((e for e in errors if e["horizon"] >= 1), key=lambda e: -abs(e["error"]))[:6]
    return errors, by_h, misses


def build(set_id):
    cfg = SETS.get(set_id)
    if not cfg:
        raise KeyError("unknown forecast set %r" % set_id)
    out = {"id": set_id, "name": cfg["name"], "unit": cfg["unit"], "country": cfg["country"],
           "decimals": cfg["decimals"], "who": cfg["who"], "what": cfg["what"],
           "tolerance": cfg["tolerance"], "pessimistic": cfg["pessimistic"]}
    try:
        book, info = _load_book(cfg["source"])
    except net.FetchError as e:
        out["error"] = str(e)
        return out
    out["fetchedAt"] = info["fetchedAt"]

    actual_src = {}
    if cfg["source"] == "obr":
        vintages, outturn = parse_obr_sheet(book.rows(cfg["sheet"]))
        actual = dict(outturn)
        for y in outturn:
            actual_src[y] = "OBR outturn"
        if cfg.get("fill"):
            sid, scale = cfg["fill"]
            try:
                for y, v in series.annual(sid).items():
                    if y not in actual and y < datetime.date.today().year:
                        actual[y] = v * scale
                        actual_src[y] = "ONS annual average"
            except Exception:
                pass
        out["source"] = {"name": "OBR Historical Official Forecasts Database",
                         "url": OBR_DATA_PAGE}
    else:
        vintages = parse_spf_sheet(book.rows(cfg["sheet"]))
        actual = {y: v for y, v in series.annual("us.unemployment").items()
                  if y < datetime.date.today().year}
        for y in actual:
            actual_src[y] = "BLS annual average"
        out["source"] = {"name": "Philadelphia Fed Survey of Professional Forecasters",
                         "url": SPF_PAGE}

    errors, by_h, misses = score(vintages, actual, cfg["tolerance"], cfg["pessimistic"])
    latest = vintages[-1] if vintages else None
    pending = []
    if latest:
        pending = [{"year": y, "forecast": round(f, 3)} for y, f in latest["points"]
                   if y not in actual and y >= int(latest["date"][:4])]
    live = None
    try:
        pts = series.load(cfg["live"])["points"]
        if pts:
            scale = cfg.get("liveScale", 1.0)
            live = {"series": cfg["live"], "date": pts[-1][0], "value": round(pts[-1][1] * scale, 3)}
    except Exception:
        pass

    out.update({
        "vintages": [{**v, "points": [[y, round(f, 3)] for y, f in v["points"]]} for v in vintages],
        "actual": [[y, round(v, 3), actual_src.get(y, "")] for y, v in sorted(actual.items())],
        "errors": errors, "byHorizon": by_h, "misses": misses,
        "latestVintage": latest["label"] if latest else None,
        "pending": pending, "live": live,
    })
    return out


def list_sets():
    return [{"id": k, "name": v["name"], "country": v["country"], "who": v["who"]}
            for k, v in SETS.items()]
