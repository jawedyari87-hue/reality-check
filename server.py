#!/usr/bin/env python3
"""Reality Check: job-market predictions against the real data.

Runs on the Python standard library alone: no pip install, no build step, no
account, no API key. Start it with `py -3 server.py` (or double-click run.bat)
and it opens in your browser.

What it does:
  * scores famous job/AI predictions (Frey & Osborne, PwC, Hinton, Musk, WEF,
    Amodei...) against official data, with the rule used shown for each;
  * grades every official UK (OBR) and US (Philadelphia Fed survey)
    unemployment/earnings forecast against what actually happened;
  * compares salaries by occupation, UK (ONS ASHE) against US (BLS OEWS);
  * charts the live labour market: unemployment, vacancies, pay, and Indeed
    job postings by sector (software development included);
  * lets you log your own predictions and scores them automatically when the
    data arrives, with a calibration (Brier) score.
"""

import datetime
import json
import mimetypes
import os
import posixpath
import re
import socket
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reality import checks, forecasts, net, salaries, series, store  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(BASE, "web")
DEFAULT_PORT = 8780

# What the Overview tiles show: (series, how to describe the change).
TILES = [
    ("uk.unemployment", "pp"), ("uk.youth_unemployment", "pp"), ("uk.vacancies", "pct"),
    ("uk.postings.software-development", "pct"), ("us.postings.software-development", "pct"),
    ("uk.regular_pay_growth", "pp"), ("uk.inflation", "pp"), ("us.unemployment", "pp"),
]


def today():
    return datetime.date.today()


# --------------------------------------------------------------------------
# Overview tiles
# --------------------------------------------------------------------------

def _year_ago(points):
    last = datetime.date.fromisoformat(points[-1][0])
    target = last.replace(year=last.year - 1) if not (last.month == 2 and last.day == 29) \
        else last.replace(year=last.year - 1, day=28)
    best = None
    for d, v in points:
        if datetime.date.fromisoformat(d) <= target:
            best = (d, v)
    return best


def tile(series_id, mode):
    data = series.load(series_id)
    meta = series.BY_ID[series_id]
    out = {"id": series_id, "name": meta["name"], "country": meta["country"],
           "unit": meta["unit"], "better": meta.get("better"), "source": meta["source"],
           "error": data.get("error")}
    pts = data.get("points") or []
    if not pts:
        return out
    ago = _year_ago(pts)
    out["latest"] = {"date": pts[-1][0], "value": pts[-1][1]}
    if ago:
        out["yearAgo"] = {"date": ago[0], "value": ago[1]}
        out["delta"] = (pts[-1][1] - ago[1]) if mode == "pp" else (pts[-1][1] / ago[1] - 1) * 100
        out["deltaMode"] = mode
    ppy = series.periods_per_year(pts)
    out["spark"] = pts[-(ppy * 3 + 1):]  # three years
    if meta["unit"].startswith("index"):
        out["vsBaseline"] = pts[-1][1] - 100
    return out


def overview():
    tiles = []
    for sid, mode in TILES:
        try:
            tiles.append(tile(sid, mode))
        except Exception as e:
            tiles.append({"id": sid, "error": str(e)})
    famous = [checks.evaluate_item(i) for i in store.famous()["items"]]
    counts = {}
    for f in famous:
        counts[f["status"]] = counts.get(f["status"], 0) + 1
    return {"today": today().isoformat(), "tiles": tiles, "famousCounts": counts}


# --------------------------------------------------------------------------
# Your predictions
# --------------------------------------------------------------------------

def _clean_check(c):
    if not isinstance(c, dict):
        raise ValueError("missing the data rule")
    sid = str(c.get("series") or "")
    if sid not in series.BY_ID:
        raise ValueError("pick a data series")
    test = c.get("test")
    if test not in ("reach", "change", "level"):
        raise ValueError("unknown test")
    op = c.get("op")
    if op not in (">=", "<="):
        raise ValueError("pick 'at least' or 'at most'")
    out = {"series": sid, "test": test, "op": op}
    key = "pct" if test == "change" else "value"
    try:
        out[key] = float(c.get(key))
    except (TypeError, ValueError):
        raise ValueError("the threshold must be a number")
    for k in ("start", "end"):
        v = c.get(k)
        if v in (None, ""):
            out[k] = None
            continue
        try:
            out[k] = datetime.date.fromisoformat(str(v)).isoformat()
        except ValueError:
            raise ValueError("dates must look like 2030-09-01")
    if not out.get("end"):
        raise ValueError("give it a deadline - a prediction with no date can never be wrong")
    if test != "level" and not out.get("start"):
        out["start"] = today().isoformat()
    if out.get("start") and out["start"] > out["end"]:
        raise ValueError("the deadline is before the start date")
    return out


def _clean_item(item):
    claim = re.sub(r"\s+", " ", str(item.get("claim") or "")).strip()[:400]
    if not claim:
        raise ValueError("write the prediction first")
    try:
        conf = int(round(float(item.get("confidence"))))
    except (TypeError, ValueError):
        raise ValueError("confidence must be a number from 1 to 99")
    if not 1 <= conf <= 99:
        raise ValueError("confidence must be between 1 and 99%")
    return {
        "id": str(item.get("id") or "m%d" % int(datetime.datetime.now().timestamp() * 1000))[:40],
        "claim": claim,
        "confidence": conf,
        "madeOn": str(item.get("madeOn") or today().isoformat())[:10],
        "notes": str(item.get("notes") or "")[:2000],
        "checks": [_clean_check(item.get("check") or (item.get("checks") or [None])[0])],
    }


def mine_payload():
    items = [checks.evaluate_item(i) for i in store.mine()["items"]]
    items.sort(key=lambda i: (i["status"] in ("true", "false"), i["checks"][0].get("end") or ""))
    return {"items": items, "brier": checks.brier(items)}


def mine_action(body):
    items = store.mine()["items"]
    action = body.get("action")
    if action == "delete":
        items = [i for i in items if i.get("id") != body.get("id")]
    elif action in ("add", "update"):
        item = _clean_item(body.get("item") or {})
        if action == "add":
            item["created"] = store.now_iso()
            items.append(item)
        else:
            for n, old in enumerate(items):
                if old.get("id") == item["id"]:
                    item["created"] = old.get("created")
                    items[n] = item
                    break
            else:
                raise ValueError("that prediction no longer exists")
    else:
        raise ValueError("unknown action")
    store.save_mine(items)
    return mine_payload()


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "RealityCheck"

    def log_message(self, fmt, *args):
        if os.environ.get("REALITY_VERBOSE"):
            sys.stderr.write("  %s\n" % (fmt % args))

    def _json(self, payload, code=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except ValueError:
            return {}

    def _static(self, path):
        rel = posixpath.normpath(urllib.parse.unquote(path)).lstrip("/")
        if rel in ("", "."):
            rel = "index.html"
        full = os.path.normpath(os.path.join(WEB, rel))
        if not full.startswith(WEB + os.sep) or not os.path.isfile(full):
            self.send_error(404, "Not found")
            return
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if full.endswith(".js"):
            ctype = "text/javascript"
        with open(full, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text") else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)
        if not path.startswith("/api/"):
            return self._static(path)
        try:
            if path == "/api/catalog":
                return self._json({"series": series.public_catalog(),
                                   "forecastSets": forecasts.list_sets(),
                                   "featuredSectors": series.FEATURED_SECTORS,
                                   "today": today().isoformat()})
            if path == "/api/series":
                ids = [x for x in (qs.get("ids", [""])[0] or "").split(",") if x][:12]
                items = []
                for sid in ids:
                    d = series.load(sid)
                    d.pop("years", None)
                    items.append(d)
                return self._json({"items": items})
            if path == "/api/overview":
                return self._json(overview())
            if path == "/api/famous":
                items = [checks.evaluate_item(i) for i in store.famous()["items"]]
                items.sort(key=lambda i: i.get("date") or "")
                return self._json({"items": items, "note": store.famous().get("note", "")})
            if path == "/api/mine":
                return self._json(mine_payload())
            if path == "/api/forecasts":
                return self._json(forecasts.build(qs.get("set", ["obr-unemployment"])[0]))
            if path == "/api/salaries":
                return self._json(salaries.build())
            if path == "/api/salaries/status":
                return self._json(salaries.job_status())
            self.send_error(404, "No such endpoint")
        except KeyError as e:
            self._json({"error": "not found: %s" % e}, 404)
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _same_origin(self):
        """Refuse writes that did not come from this app's own pages.

        Without this, any website open in your browser could POST to
        127.0.0.1 and rewrite your predictions. The Host check stops DNS
        rebinding tricks.
        """
        host = (self.headers.get("Host") or "").lower()
        port = self.server.server_address[1]
        if host not in ("127.0.0.1:%d" % port, "localhost:%d" % port):
            return False
        origin = self.headers.get("Origin")
        if origin and origin.lower() not in ("http://127.0.0.1:%d" % port,
                                             "http://localhost:%d" % port):
            return False
        if self.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
            return False
        return True

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._same_origin():
            return self._json({"error": "cross-origin request refused"}, 403)
        body = self._body()
        try:
            if path == "/api/mine":
                return self._json(mine_action(body))
            if path == "/api/salaries/refresh":
                started = salaries.start_refresh(force=bool(body.get("force")))
                return self._json({"started": started, "job": salaries.job_status()})
            if path == "/api/refresh":
                net.request_refresh()
                threading.Thread(target=prefetch, daemon=True).start()
                return self._json({"ok": True})
            self.send_error(404, "No such endpoint")
        except ValueError as e:
            self._json({"error": str(e)}, 400)
        except Exception as e:
            self._json({"error": str(e)}, 500)


class Server(ThreadingHTTPServer):
    # On Windows, SO_REUSEADDR lets a second copy bind a port that is already
    # in use, and requests keep going to the old copy. Fail loudly instead.
    allow_reuse_address = os.name != "nt"


def free_port(start=DEFAULT_PORT, tries=20):
    for p in range(start, start + tries):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise SystemExit("No free port in range %d-%d" % (start, start + tries))


def prefetch():
    """Warm the cache in the background so the first page view is quick."""
    ids = [sid for sid, _ in TILES] + ["uk.employment", "us.employment", "uk.unemployed",
                                        "uk.employment_rate", "us.employment_rate",
                                        "uk.cpi_index", "us.cpi_index", "fx.usd_per_gbp",
                                        "uk.postings", "us.postings"]
    for sid in ids:
        try:
            series.load(sid)
        except Exception:
            pass
    for sid in forecasts.SETS:
        try:
            forecasts.build(sid)
        except Exception:
            pass


def main():
    store.ensure_dirs()
    port = int(os.environ.get("REALITY_PORT") or free_port())
    url = "http://127.0.0.1:%d/" % port
    try:
        httpd = Server(("127.0.0.1", port), Handler)
    except OSError:
        raise SystemExit("\n  Port %d is already in use - Reality Check is probably already running.\n"
                         "  Open http://127.0.0.1:%d/ or close the other window first.\n" % (port, port))
    print("")
    print("  Reality Check - job-market predictions vs the data")
    print("  --------------------------------------------------")
    print("  Serving at %s" % url)
    print("  Press Ctrl+C to stop.")
    print("")
    if os.environ.get("REALITY_NO_PREFETCH") != "1":
        threading.Thread(target=prefetch, daemon=True).start()
        if not salaries.has_data() and not net.offline():
            salaries.start_refresh()
            print("  First run: downloading salary tables in the background (a few minutes).")
            print("")
    if os.environ.get("REALITY_NO_BROWSER") != "1":
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
        httpd.server_close()


if __name__ == "__main__":
    main()
