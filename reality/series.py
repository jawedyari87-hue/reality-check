"""The real data: a catalog of labour-market series and their loaders.

Every series comes back in one shape: a list of [ISO date, value] pairs,
oldest first. Monthly and quarterly data are dated on the first day of the
month they describe; Indeed's daily postings index is sampled weekly.

Sources (all public, no key):
  ONS      - UK official statistics, JSON time-series endpoints
  FRED     - St Louis Fed's mirror of US official statistics, CSV
  Indeed   - Hiring Lab's job-postings tracker on GitHub (CC BY 4.0), CSV
"""

import csv
import datetime
import io
import json
import re
import threading

from . import net

ONS_PAGE = "https://www.ons.gov.uk%s"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=%s"
FRED_PAGE = "https://fred.stlouisfed.org/series/%s"
INDEED_RAW = "https://raw.githubusercontent.com/hiring-lab/job_postings_tracker/master/%s/%s"
INDEED_PAGE = "https://github.com/hiring-lab/job_postings_tracker"

TTL_HOURS = 12
INDEED_TTL_HOURS = 24

_LMS = "/employmentandlabourmarket/peoplenotinwork/unemployment/timeseries/%s/lms"
_EMP = "/employmentandlabourmarket/peopleinwork/employmentandemployeetypes/timeseries/%s/lms"
_PAY = "/employmentandlabourmarket/peopleinwork/earningsandworkinghours/timeseries/%s/%s"
_CPI = "/economy/inflationandpriceindices/timeseries/%s/mm23"

INDEED_SECTORS = [
    "Accounting", "Administrative Assistance", "Architecture", "Arts & Entertainment",
    "Banking & Finance", "Childcare", "Civil Engineering", "Cleaning & Sanitation",
    "Community & Social Service", "Construction", "Customer Service", "Data & Analytics",
    "Dental", "Driving", "Education & Instruction", "Electrical Engineering",
    "Food Preparation & Service", "Hospitality & Tourism", "Human Resources",
    "IT Infrastructure, Operations & Support", "IT Systems & Solutions",
    "Industrial Engineering", "Installation & Maintenance", "Insurance", "Legal",
    "Loading & Stocking", "Logistic Support", "Management", "Marketing",
    "Mechanical Engineering", "Media & Communications", "Medical Information",
    "Medical Technician", "Nursing", "Personal Care & Home Health", "Pharmacy",
    "Physicians & Surgeons", "Production & Manufacturing", "Project Management",
    "Real Estate", "Retail", "Sales", "Scientific Research & Development",
    "Security & Public Safety", "Social Science", "Software Development", "Sports",
    "Therapy", "Veterinary",
]
# Sectors a CS student is most likely to care about, shown first.
FEATURED_SECTORS = ["Software Development", "Data & Analytics", "IT Systems & Solutions",
                    "IT Infrastructure, Operations & Support", "Scientific Research & Development",
                    "Banking & Finance"]


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower().replace("&", "and")).strip("-")


def _ons(id, country, name, unit, topic, cdid, uri, better=None, note="", hidden=False):
    return {"id": id, "country": country, "name": name, "unit": unit, "topic": topic,
            "better": better, "note": note, "hidden": hidden,
            "source": {"name": "ONS", "code": cdid.upper(), "url": ONS_PAGE % uri},
            "loader": {"kind": "ons", "uri": uri}}


def _fred(id, country, name, unit, topic, code, better=None, note="", hidden=False, source="BLS via FRED"):
    return {"id": id, "country": country, "name": name, "unit": unit, "topic": topic,
            "better": better, "note": note, "hidden": hidden,
            "source": {"name": source, "code": code, "url": FRED_PAGE % code},
            "loader": {"kind": "fred", "code": code}}


def _indeed(country, sector=None):
    cc = {"UK": "GB", "US": "US"}[country]
    if sector:
        return {"id": "%s.postings.%s" % (country.lower(), slug(sector)), "country": country,
                "name": "Job postings: %s" % sector, "unit": "index (1 Feb 2020 = 100)",
                "topic": "Job postings by sector", "better": "up", "sector": sector,
                "note": "Indeed postings in this category, 7-day average, relative to "
                        "1 Feb 2020. Not seasonally adjusted.",
                "source": {"name": "Indeed Hiring Lab", "code": cc, "url": INDEED_PAGE},
                "loader": {"kind": "indeed_sector", "cc": cc, "sector": sector}}
    return {"id": "%s.postings" % country.lower(), "country": country,
            "name": "Job postings: all jobs", "unit": "index (1 Feb 2020 = 100)",
            "topic": "Job postings", "better": "up",
            "note": "All job postings on Indeed, seasonally adjusted, relative to 1 Feb 2020.",
            "source": {"name": "Indeed Hiring Lab", "code": cc, "url": INDEED_PAGE},
            "loader": {"kind": "indeed_agg", "cc": cc}}


BASE_CATALOG = [
    # ---------------- UK ----------------
    _ons("uk.unemployment", "UK", "Unemployment rate (16+)", "%", "Unemployment", "MGSX",
         _LMS % "mgsx", better="down",
         note="Labour Force Survey, three months ending in the month shown, seasonally adjusted."),
    _ons("uk.youth_unemployment", "UK", "Youth unemployment rate (16-24)", "%", "Unemployment",
         "MGWY", _LMS % "mgwy", better="down",
         note="Includes full-time students looking for work. LFS, seasonally adjusted."),
    _ons("uk.unemployed", "UK", "People unemployed (16+)", "thousands", "Unemployment", "MGSC",
         _LMS % "mgsc", better="down"),
    _ons("uk.employment", "UK", "People in work (16+)", "thousands", "Employment", "MGRZ",
         _EMP % "mgrz", better="up"),
    _ons("uk.employment_rate", "UK", "Employment rate (16-64)", "%", "Employment", "LF24",
         _EMP % "lf24", better="up"),
    _ons("uk.vacancies", "UK", "Job vacancies", "thousands", "Vacancies", "AP2Y",
         _EMP % "ap2y", better="up", note="ONS Vacancy Survey, three months ending in the month shown."),
    _ons("uk.pay_growth", "UK", "Pay growth, total pay (year on year)", "%", "Pay",
         "KAC3", _PAY % ("kac3", "lms"), better="up",
         note="Average weekly earnings, whole economy, 3-month average vs a year earlier. Not adjusted for inflation."),
    _ons("uk.regular_pay_growth", "UK", "Pay growth, regular pay (year on year)", "%", "Pay",
         "KAI9", _PAY % ("kai9", "lms"), better="up",
         note="Excludes bonuses. Not adjusted for inflation - compare with CPI inflation."),
    _ons("uk.weekly_pay", "UK", "Average weekly pay (whole economy)", "£ per week", "Pay",
         "KAB9", _PAY % ("kab9", "lms"), better="up"),
    _ons("uk.tech_weekly_pay", "UK", "Average weekly pay: information & communication sector",
         "£ per week", "Pay", "K5E9", _PAY % ("k5e9", "emp"), better="up",
         note="Not seasonally adjusted, so bonus months spike. Includes telecoms and media as well as software."),
    _ons("uk.inflation", "UK", "Inflation (CPI, year on year)", "%", "Prices", "D7G7",
         _CPI % "d7g7"),
    _ons("uk.cpi_index", "UK", "Consumer price index (2015 = 100)", "index", "Prices", "D7BT",
         _CPI % "d7bt", hidden=True),
    _indeed("UK"),
    # ---------------- US ----------------
    _fred("us.unemployment", "US", "Unemployment rate (16+)", "%", "Unemployment", "UNRATE",
          better="down"),
    _fred("us.youth_unemployment", "US", "Youth unemployment rate (16-24)", "%", "Unemployment",
          "LNS14024887", better="down"),
    _fred("us.employment", "US", "Payroll employment", "thousands", "Employment", "PAYEMS",
          better="up", note="Jobs on employer payrolls (a count of jobs, not people)."),
    _fred("us.employment_rate", "US", "Employment-population ratio (16+)", "%", "Employment",
          "EMRATIO", better="up",
          note="Share of everyone aged 16+ in work - includes retirees, so it sits lower than the UK's 16-64 rate."),
    _fred("us.openings", "US", "Job openings (JOLTS)", "thousands", "Vacancies", "JTSJOL",
          better="up"),
    _fred("us.tech_weekly_pay", "US", "Average weekly pay: information sector", "$ per week",
          "Pay", "CES5000000011", better="up"),
    _fred("us.cpi_index", "US", "Consumer price index (1982-84 = 100)", "index", "Prices",
          "CPIAUCSL", hidden=True),
    _indeed("US"),
    # ---------------- exchange rate ----------------
    _fred("fx.usd_per_gbp", "UK", "US dollars per pound (annual average)", "$ per £", "Prices",
          "AEXUSUK", hidden=True, source="Federal Reserve via FRED"),
]

CATALOG = BASE_CATALOG + [_indeed(c, s) for c in ("UK", "US") for s in INDEED_SECTORS]
BY_ID = {s["id"]: s for s in CATALOG}


def public_catalog():
    out = []
    for s in CATALOG:
        item = {k: v for k, v in s.items() if k != "loader"}
        item["featured"] = s.get("sector") in FEATURED_SECTORS if s.get("sector") else True
        out.append(item)
    return out


# --------------------------------------------------------------------------
# Parsers
# --------------------------------------------------------------------------

_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_ons(body):
    """ONS time-series JSON -> (points, {year: annual value})."""
    d = json.loads(body)
    points = []
    for r in d.get("months") or []:
        parts = str(r.get("date", "")).split()
        v = _num(r.get("value"))
        if len(parts) == 2 and parts[1][:3].upper() in _MONTHS and v is not None:
            points.append(["%s-%02d-01" % (parts[0], _MONTHS[parts[1][:3].upper()]), v])
    if not points:
        for r in d.get("quarters") or []:
            m = re.match(r"(\d{4})\s*Q([1-4])", str(r.get("date", "")))
            v = _num(r.get("value"))
            if m and v is not None:
                points.append(["%s-%02d-01" % (m.group(1), int(m.group(2)) * 3), v])
    years = {}
    for r in d.get("years") or []:
        v = _num(r.get("value"))
        if str(r.get("date", "")).isdigit() and v is not None:
            years[int(r["date"])] = v
    if not points:
        points = [["%d-07-01" % y, v] for y, v in sorted(years.items())]
    points.sort()
    return points, years


def parse_fred(body):
    rows = list(csv.reader(io.StringIO(body.decode("utf-8", errors="replace"))))
    out = []
    for r in rows[1:]:
        if len(r) >= 2:
            v = _num(r[1])
            if v is not None:
                out.append([r[0], v])
    return out


def _weekly(daily):
    """Keep one point every 7 days, counted back from the latest date."""
    if not daily:
        return []
    daily.sort()
    last = datetime.date.fromisoformat(daily[-1][0])
    return [p for p in daily if (last - datetime.date.fromisoformat(p[0])).days % 7 == 0]


def parse_indeed_aggregate(body):
    reader = csv.DictReader(io.StringIO(body.decode("utf-8", errors="replace")))
    daily = []
    for r in reader:
        if (r.get("variable") or "total postings") != "total postings":
            continue
        v = _num(r.get("indeed_job_postings_index_SA") or r.get("indeed_job_postings_index"))
        if v is not None:
            daily.append([r["date"], v])
    return _weekly(daily)


def parse_indeed_sectors(body):
    reader = csv.DictReader(io.StringIO(body.decode("utf-8", errors="replace")))
    by_sector = {}
    for r in reader:
        if r.get("variable") != "total postings":
            continue
        v = _num(r.get("indeed_job_postings_index"))
        if v is not None:
            by_sector.setdefault(r["display_name"], []).append([r["date"], v])
    return {k: _weekly(v) for k, v in by_sector.items()}


# --------------------------------------------------------------------------
# Loading, memoised on the downloaded file
# --------------------------------------------------------------------------

_memo = {}
_memo_lock = threading.Lock()


def _memoised(key, fetched, parse):
    body, info = fetched
    stamp = (info["fetchedAt"], len(body))
    with _memo_lock:
        hit = _memo.get(key)
        if hit and hit[0] == stamp:
            return hit[1], info
    value = parse(body)
    with _memo_lock:
        _memo[key] = (stamp, value)
    return value, info


def load(series_id):
    """Return {id, points, fetchedAt, stale?, error?} for one catalog series."""
    s = BY_ID.get(series_id)
    if not s:
        raise KeyError("unknown series %r" % series_id)
    ld = s["loader"]
    out = {"id": series_id}
    try:
        if ld["kind"] == "ons":
            fetched = net.fetch(ONS_PAGE % ld["uri"] + "/data", "ons_" + ld["uri"], TTL_HOURS)
            (points, years), info = _memoised(series_id, fetched, parse_ons)
            out["years"] = years
        elif ld["kind"] == "fred":
            fetched = net.fetch(FRED_CSV % ld["code"], "fred_%s.csv" % ld["code"], TTL_HOURS)
            points, info = _memoised(series_id, fetched, parse_fred)
        elif ld["kind"] == "indeed_agg":
            name = "aggregate_job_postings_%s.csv" % ld["cc"]
            fetched = net.fetch(INDEED_RAW % (ld["cc"], name), "indeed_" + name, INDEED_TTL_HOURS)
            points, info = _memoised(series_id, fetched, parse_indeed_aggregate)
        elif ld["kind"] == "indeed_sector":
            name = "job_postings_by_sector_%s.csv" % ld["cc"]
            fetched = net.fetch(INDEED_RAW % (ld["cc"], name), "indeed_" + name, INDEED_TTL_HOURS)
            sectors, info = _memoised("indeed_sectors_" + ld["cc"], fetched, parse_indeed_sectors)
            points = sectors.get(ld["sector"], [])
        else:
            raise KeyError(ld["kind"])
    except net.FetchError as e:
        out.update(points=[], error=str(e))
        return out
    out["points"] = points
    out["fetchedAt"] = info["fetchedAt"]
    if info.get("stale"):
        out["stale"] = True
        out["error"] = info.get("error")
    return out


def annual(series_id):
    """{year: annual value}. ONS publishes official annual figures; for other
    data a year counts once it is complete. A finished year may miss one
    reading (BLS published no October 2025 figures during the shutdown)."""
    data = load(series_id)
    if data.get("years"):
        return data["years"]
    by_year = {}
    for d, v in data["points"]:
        by_year.setdefault(int(d[:4]), []).append(v)
    ppy = periods_per_year(data["points"])
    this_year = datetime.date.today().year

    def complete(y, n):
        return n >= ppy if y >= this_year else n >= max(1, ppy - 1)
    return {y: sum(vs) / len(vs) for y, vs in by_year.items() if complete(y, len(vs))}


def periods_per_year(points):
    """12 for monthly data, 4 for quarterly, 52 for weekly, 1 for annual."""
    if len(points) < 3:
        return 1
    dates = [datetime.date.fromisoformat(p[0]) for p in points[-13:]]
    gaps = sorted((b - a).days for a, b in zip(dates, dates[1:]))
    gap = gaps[len(gaps) // 2]
    return 52 if gap <= 8 else 12 if gap <= 40 else 4 if gap <= 100 else 1
