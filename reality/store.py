"""Where things live on disk, and safe JSON reads/writes.

data/            everything the app writes (safe to delete: it re-downloads)
  cache/raw/     downloaded source files, exactly as served
  cache/*.json   parsed results (salary tables, etc.)
  mine.json      your own predictions (the only file you would miss)
content/         shipped with the app: the researched famous predictions
"""

import datetime
import json
import os
import threading

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("REALITY_DATA") or os.path.join(BASE, "data")
CONTENT = os.path.join(BASE, "content")
CACHE = os.path.join(DATA, "cache")
RAW = os.path.join(CACHE, "raw")
MINE = os.path.join(DATA, "mine.json")
FAMOUS = os.path.join(CONTENT, "famous.json")

_lock = threading.Lock()


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def ensure_dirs():
    for d in (DATA, CACHE, RAW):
        os.makedirs(d, exist_ok=True)


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path, value):
    """Write via a temp file so a crash mid-write never leaves half a file."""
    ensure_dirs()
    tmp = path + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(value, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)


def mine():
    return read_json(MINE, {"items": []}) or {"items": []}


def save_mine(items):
    write_json(MINE, {"items": items, "updated": now_iso()})


def famous():
    return read_json(FAMOUS, {"items": []}) or {"items": []}
