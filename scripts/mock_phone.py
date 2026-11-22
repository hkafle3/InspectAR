"""Pretends to be the phone app: waits for capture_request, then "takes a photo and
records a note" by uploading the next sample from samples/.

  python scripts/mock_phone.py [--server http://localhost:8000]
"""
import argparse
import asyncio
import itertools
import json
from pathlib import Path

import httpx
import websockets

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
p = argparse.ArgumentParser()
p.add_argument("--server", default="http://localhost:8000")
args = p.parse_args()
ws_url = args.server.replace("http", "ws", 1) + "/ws/phone"
samples = itertools.cycle(json.loads((SAMPLES / "notes.json").read_text()))


async def main():
    async with websockets.connect(ws_url) as ws, httpx.AsyncClient(timeout=180) as http:
        print("Phone connected. Waiting for capture requests (Ctrl+C to quit)…")
        async for raw in ws:
            if json.loads(raw).get("type") != "capture_request":
                continue
            s = next(samples)
            print(f"capture_request → recording… then uploading: {s['note']!r}")
            await asyncio.sleep(1)  # pretend to record
            photo = SAMPLES / s["photo"]
            files = {"photo": (photo.name, photo.read_bytes(), "image/jpeg")} if photo.exists() else None
            r = await http.post(f"{args.server}/api/capture", data={"note": s["note"]}, files=files)
            print(f"  uploaded → #{r.json()['id']} {r.json()['short_label']}")


asyncio.run(main())
