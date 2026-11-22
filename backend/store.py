"""Entries live in memory and are saved to data/entries.json. Photos go to data/photos/."""
import json
import threading

from . import config

_lock = threading.Lock()
_entries: list[dict] = []
_next_id = 1


def load():
    global _entries, _next_id
    config.PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    if config.ENTRIES_FILE.exists():
        _entries = json.loads(config.ENTRIES_FILE.read_text())
        _next_id = max((e["id"] for e in _entries), default=0) + 1


def _save():
    tmp = config.ENTRIES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_entries, indent=2))
    tmp.replace(config.ENTRIES_FILE)


def all_entries() -> list[dict]:
    return list(_entries)


def reserve_id() -> int:
    global _next_id
    with _lock:
        i = _next_id
        _next_id += 1
        return i


def add(entry: dict):
    with _lock:
        _entries.append(entry)
        _entries.sort(key=lambda e: e["id"])
        _save()


def delete(entry_id: int) -> bool:
    with _lock:
        for e in _entries:
            if e["id"] == entry_id:
                _entries.remove(e)
                if e.get("photo_file"):
                    (config.PHOTOS_DIR / e["photo_file"]).unlink(missing_ok=True)
                _save()
                return True
    return False


def reset():
    global _next_id
    with _lock:
        _entries.clear()
        _next_id = 1
        for p in config.PHOTOS_DIR.glob("*"):
            p.unlink()
        _save()
