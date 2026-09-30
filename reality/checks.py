"""Score a prediction against a data series.

A check is a small, explicit rule, so anyone can see exactly what "came true"
means:

  reach   - the series hits a threshold at any point in the window
            {"test": "reach", "series": id, "op": ">=", "value": 10, "start", "end"}
  change  - the series moves by at least X% between two dates
            {"test": "change", "series": id, "op": "<=", "pct": -10, "start", "end"}
  level   - the value on the end date is above/below a threshold
            {"test": "level", "series": id, "op": ">=", "value": 5, "end"}

`end` may be null for predictions that gave no deadline: they stay open and
only report how things are moving.

Outcomes: true (came true), false (didn't happen), pending (window still
open), awaiting (window closed, official figures not out yet), nodata.
"""

import datetime

from . import series

# How far the latest observation may sit before the deadline and still count
# as covering it (one reporting period).
_PERIOD_DAYS = {52: 7, 12: 31, 4: 92, 1: 366}


def _d(s):
    return datetime.date.fromisoformat(s) if s else None


def _cmp(a, op, b):
    return a >= b if op == ">=" else a <= b


def _fmt(v):
    if v is None:
        return "?"
    return ("%.1f" % v) if abs(v) < 1000 else format(round(v), ",")


def _last_on_or_before(points, day):
    best = None
    for d, v in points:
        if _d(d) <= day:
            best = (d, v)
        else:
            break
    return best


def evaluate(check, today=None, data=None):
    today = today or datetime.date.today()
    data = data or series.load(check["series"])
    points = data.get("points") or []
    meta = series.BY_ID.get(check["series"], {})
    out = {"series": check["series"], "seriesName": meta.get("name", check["series"]),
           "country": meta.get("country"), "unit": meta.get("unit", "")}
    if not points:
        out.update(status="nodata", label="No data", detail=data.get("error") or "Series has no data yet.")
        return out

    op = check.get("op", ">=")
    start, end = _d(check.get("start")), _d(check.get("end"))
    last_d, last_v = points[-1]
    out["latest"] = {"date": last_d, "value": last_v}
    period = _PERIOD_DAYS.get(series.periods_per_year(points), 31)
    covers = end is not None and _d(last_d) >= end - datetime.timedelta(days=period)
    closed = end is not None and today > end

    def unresolved(satisfied, progress):
        if closed and not covers:
            status, label = "awaiting", "Waiting for data"
        elif end is None:
            status, label = "open", "No deadline"
        else:
            status, label = "pending", "Too early"
        out.update(status=status, label=label, onTrack=satisfied, progress=progress)
        return out

    test = check["test"]
    if test == "reach":
        target = check["value"]
        window = [(d, v) for d, v in points
                  if (start is None or _d(d) >= start) and (end is None or _d(d) <= end)]
        hit = next(((d, v) for d, v in window if _cmp(v, op, target)), None)
        out["target"] = target
        if hit:
            out.update(status="true", label="Came true", hit={"date": hit[0], "value": hit[1]},
                       progress="Reached %s on %s (target %s %s)." % (_fmt(hit[1]), hit[0], op, _fmt(target)))
            return out
        extreme = (max if op == ">=" else min)((v for _, v in window), default=None)
        if covers and closed:
            out.update(status="false", label="Didn't happen", extreme=extreme,
                       progress="Never got %s %s; closest was %s." % (
                           "above" if op == ">=" else "below", _fmt(target), _fmt(extreme)))
            return out
        return unresolved(False, "Now %s; needs to %s %s." % (
            _fmt(last_v), "reach" if op == ">=" else "fall to", _fmt(target)))

    if test == "change":
        base = _last_on_or_before(points, start) if start else None
        if base is None:
            base = next(((d, v) for d, v in points if start is None or _d(d) >= start), None)
        if base is None or not base[1]:
            out.update(status="nodata", label="No data", detail="No value near the start date.")
            return out
        out["baseline"] = {"date": base[0], "value": base[1]}
        target = check["pct"]
        out["target"] = target
        if covers and closed:
            fin = _last_on_or_before(points, end)
            pct = (fin[1] / base[1] - 1) * 100
            ok = _cmp(pct, op, target)
            out.update(status="true" if ok else "false", label="Came true" if ok else "Didn't happen",
                       changePct=round(pct, 2), final={"date": fin[0], "value": fin[1]},
                       progress="%s to %s: %+.1f%% (needed %s %+.0f%%)." % (
                           base[0][:7], fin[0][:7], pct, op, target))
            return out
        pct = (last_v / base[1] - 1) * 100
        out["changePct"] = round(pct, 2)
        return unresolved(_cmp(pct, op, target), "%+.1f%% since %s so far (needs %s %+.0f%%%s)." % (
            pct, base[0][:7], op, target, "" if end is None else " by " + end.isoformat()[:7]))

    if test == "level":
        target = check["value"]
        out["target"] = target
        if covers and closed:
            fin = _last_on_or_before(points, end)
            ok = _cmp(fin[1], op, target)
            out.update(status="true" if ok else "false", label="Came true" if ok else "Didn't happen",
                       final={"date": fin[0], "value": fin[1]},
                       progress="%s on %s (needed %s %s)." % (_fmt(fin[1]), fin[0], op, _fmt(target)))
            return out
        return unresolved(_cmp(last_v, op, target), "Now %s; needs %s %s on %s." % (
            _fmt(last_v), op, _fmt(target), check.get("end")))

    out.update(status="nodata", label="Unknown test", detail=test)
    return out


def combine(results):
    """Several checks on one prediction (e.g. UK and US): all must come true."""
    states = [r["status"] for r in results]
    if not states:
        return "untestable"
    if "false" in states:
        return "false"
    if all(s == "true" for s in states):
        return "true"
    if "nodata" in states and all(s in ("nodata", "true") for s in states):
        return "nodata"
    for s in ("awaiting", "pending", "open"):
        if s in states:
            return s
    return states[0]


LABELS = {"true": "Came true", "false": "Didn't happen", "pending": "Too early",
          "awaiting": "Waiting for data", "open": "No deadline", "nodata": "No data",
          "untestable": "Can't be scored"}


def evaluate_item(item, today=None):
    """A famous or personal prediction -> itself plus its verdict."""
    out = dict(item)
    if item.get("manual"):
        out["status"] = item["manual"]["verdict"]
        out["auto"] = False
    elif item.get("checks"):
        out["results"] = [evaluate(c, today) for c in item["checks"]]
        out["status"] = combine(out["results"])
        out["auto"] = True
    else:
        out["status"] = "untestable"
        out["auto"] = False
    out["statusLabel"] = LABELS.get(out["status"], out["status"])
    return out


def brier(items):
    """Mean squared gap between your stated confidence and what happened.
    0 is perfect, 0.25 is what always saying 50% gets you."""
    scored = [(i["confidence"] / 100.0, 1.0 if i["status"] == "true" else 0.0)
              for i in items if i.get("status") in ("true", "false")
              and isinstance(i.get("confidence"), (int, float))]
    if not scored:
        return None
    return {"n": len(scored), "score": round(sum((p - o) ** 2 for p, o in scored) / len(scored), 3)}
