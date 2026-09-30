"""Polite, cached downloads.

Every source is public and needs no key. Each file is fetched at most once per
`max_age_hours`; if the network fails, the last good copy is used instead and
flagged as stale, so a dropped connection never blanks the page.

Sources throttle bursts (ONS answers HTTP 429), so requests to the same host
are spaced out and a 429 is retried after the delay the server asks for.
"""

import datetime
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import store

USER_AGENT = "RealityCheck/1.0 (personal job-market research app; Python urllib)"
TIMEOUT = 90
HOST_GAP = {"www.ons.gov.uk": 2.5, "api.beta.ons.gov.uk": 2.5, "www.bls.gov": 2.0}
DEFAULT_GAP = 0.5

_file_locks, _host_locks, _last_hit = {}, {}, {}
_guard = threading.Lock()
_refresh_after = 0.0  # files saved before this moment count as stale


def request_refresh():
    """Make the next read of every source go back to the network."""
    global _refresh_after
    _refresh_after = time.time()


class FetchError(Exception):
    pass


def offline():
    return os.environ.get("REALITY_OFFLINE") == "1"


def _lock(table, key):
    with _guard:
        return table.setdefault(key, threading.Lock())


def safe_name(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:150]


def raw_path(name):
    return os.path.join(store.RAW, safe_name(name))


def _mtime_iso(path):
    ts = os.path.getmtime(path)
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).replace(microsecond=0).isoformat()


def age_hours(path):
    try:
        return (time.time() - os.path.getmtime(path)) / 3600
    except OSError:
        return None


def _download(url, tries=3):
    host = urllib.parse.urlparse(url).netloc
    gap = HOST_GAP.get(host, DEFAULT_GAP)
    with _lock(_host_locks, host):
        for attempt in range(tries):
            wait = gap - (time.time() - _last_hit.get(host, 0))
            if wait > 0:
                time.sleep(wait)
            _last_hit[host] = time.time()
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                    return resp.read()
            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and attempt < tries - 1:
                    try:
                        delay = float(e.headers.get("Retry-After") or 0)
                    except ValueError:
                        delay = 0
                    time.sleep(min(60, max(delay, 10 * (attempt + 1))))
                    continue
                raise FetchError("%s answered HTTP %d" % (host, e.code))
            except urllib.error.URLError as e:
                raise FetchError("could not reach %s (%s)" % (host, e.reason))
            except (TimeoutError, OSError) as e:
                raise FetchError("could not reach %s (%s)" % (host, e))
    raise FetchError("%s kept refusing (rate limit)" % host)


def fetch(url, name, max_age_hours):
    """Return (bytes, info). info = {fetchedAt, cached, stale?, error?}."""
    store.ensure_dirs()
    path = raw_path(name)
    with _lock(_file_locks, path):
        age = age_hours(path)
        fresh = age is not None and age < max_age_hours and os.path.getmtime(path) >= _refresh_after
        if age is not None and (fresh or offline()):
            with open(path, "rb") as fh:
                return fh.read(), {"fetchedAt": _mtime_iso(path), "cached": True}
        if offline():
            raise FetchError("offline and no cached copy of %s" % name)
        try:
            body = _download(url)
        except FetchError as e:
            if age is not None:
                with open(path, "rb") as fh:
                    return fh.read(), {"fetchedAt": _mtime_iso(path), "cached": True,
                                       "stale": True, "error": str(e)}
            raise
        tmp = path + ".part"
        with open(tmp, "wb") as fh:
            fh.write(body)
        os.replace(tmp, path)
        return body, {"fetchedAt": _mtime_iso(path), "cached": False}


def get(url):
    """Uncached one-off request (used for small index lookups)."""
    if offline():
        raise FetchError("offline")
    return _download(url)
