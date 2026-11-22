"""Simulate captures without any hardware: uploads sample photos + notes to the backend.

  python scripts/mock_capture.py              # log all samples, 2 s apart
  python scripts/mock_capture.py -n 3         # log the first 3
  python scripts/mock_capture.py --note "peeling paint, hallway, minor"   # one text-only entry
"""
import argparse
import json
import time
from pathlib import Path

import httpx

SAMPLES = Path(__file__).resolve().parent.parent / "samples"

p = argparse.ArgumentParser()
p.add_argument("--server", default="http://localhost:8000")
p.add_argument("-n", type=int, default=0, help="how many samples (default: all)")
p.add_argument("--note", help="send a single text-only note instead")
p.add_argument("--delay", type=float, default=2.0)
args = p.parse_args()


def send(note, photo=None):
    files = {"photo": (photo.name, photo.read_bytes(), "image/jpeg")} if photo and photo.exists() else None
    r = httpx.post(f"{args.server}/api/capture", data={"note": note}, files=files, timeout=180)
    r.raise_for_status()
    e = r.json()
    print(f"Logged #{e['id']} · {e['short_label']}  [{e['severity']}, {e['category']}, via {e['made_by']}]")


if args.note:
    send(args.note)
else:
    samples = json.loads((SAMPLES / "notes.json").read_text())
    for i, s in enumerate(samples[: args.n or None]):
        if i:
            time.sleep(args.delay)
        send(s["note"], SAMPLES / s["photo"])
