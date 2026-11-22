"""Scripted PropertyLens demo with no hardware. Needs the backend running.

Plays: pass -> flag "water stain near the light" + photo (new since move-in) ->
flag "scuff by the light switch" + photo (pre-existing at move-in) -> phone picked up and
put away (handoff) -> pass -> thermostat photo (read) -> done, and prints what the glasses show.

  python scripts/demo_run.py [--server http://localhost:8000] [--delay 1]
"""
import argparse
import asyncio
import json
from pathlib import Path

import httpx
import websockets

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
p = argparse.ArgumentParser()
p.add_argument("--server", default="http://localhost:8000")
p.add_argument("--delay", type=float, default=1.0, help="seconds between steps")
args = p.parse_args()

SCRIPT = [
    ("pass", None),
    ("flag water stain near the light", "water_stain.jpg"),
    ("flag scuff by the light switch", "scuff.jpg"),
    ("phone", None),  # pick up the phone, then put it away
    ("pass", None),
    ("", "thermostat.jpg"),
]


def show(m):
    lines = [m.get(k) for k in ("line1", "line2", "line3") if m.get(k)] or [m.get("text", "")]
    w = max(len(x) for x in lines) + 4
    print("    ┌" + "─" * w + "┐")
    for x in lines:
        print("    │  " + x.ljust(w - 2) + "│")
    print("    └" + "─" * w + "┘")


async def main():
    ws_url = args.server.replace("http", "ws", 1) + "/ws/glasses"
    async with websockets.connect(ws_url) as ws, httpx.AsyncClient(base_url=args.server, timeout=180) as http:
        async def listen():
            async for raw in ws:
                m = json.loads(raw)
                if m.get("type") in ("step", "result", "reading", "done"):
                    print(f"  glasses [{m['type']}]")
                    show(m)

        listener = asyncio.create_task(listen())

        async def handoff():
            report_url = args.server.replace("http", "ws", 1) + "/ws/report"
            async with websockets.connect(report_url) as phone:
                await phone.send(json.dumps({"type": "hello", "phone": True}))
                print("\n> inspector picks up the phone")
                await phone.send(json.dumps({"type": "presence", "active": True}))
                await asyncio.sleep(2)
                print("\n> inspector locks the phone")
                await phone.send(json.dumps({"type": "presence", "active": False}))
                await asyncio.sleep(1)
        await ws.recv()  # greeting
        await http.post("/api/reset")
        await http.post("/api/inspections", json={"template_id": "property_moveout", "consent": True})
        await asyncio.sleep(0.5)

        for said, photo in SCRIPT:
            await asyncio.sleep(args.delay)
            if said == "phone":
                await handoff()
                continue
            print(f"\n> inspector taps" + (f", says \"{said}\"" if said else "") + (f", photo {photo}" if photo else ""))
            files = {"photo": (photo, (SAMPLES / photo).read_bytes(), "image/jpeg")} if photo else None
            r = await http.post("/api/capture", data={"note": said}, files=files)
            r.raise_for_status()
            await asyncio.sleep(2)  # let "Flagged"/"Read" hold, then the next step arrives

        state = (await http.get("/api/inspections/current")).json()
        print("\nResults:")
        for step, res in zip(state["template"]["steps"], state["results"]):
            extra = res["reading"] or (res["ai_fields"] or {}).get("issue") or ""
            seen = {"new": "NEW since move-in", "pre-existing": "pre-existing"}.get(res.get("attribution"), "")
            print(f"  {res['status']:>7}  {step['label']:<16} {extra:<22} {seen}")
        print(f"\nReport: {args.server}   PDF: {args.server}/report.pdf")
        listener.cancel()


asyncio.run(main())
