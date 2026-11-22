"""Pretends to be the glasses app: shows what the display would say.
Press Enter to "tap the touchpad" (sends capture_request). Type q + Enter to quit.

  python scripts/mock_glasses.py [--server ws://localhost:8000]
"""
import argparse
import asyncio
import json

import websockets

p = argparse.ArgumentParser()
p.add_argument("--server", default="ws://localhost:8000")
args = p.parse_args()


def show(text, count=None):
    line = f"  {text}  " + (f"({count} logged)  " if count is not None else "")
    print("\n  ┌" + "─" * len(line) + "┐\n  │" + line + "│\n  └" + "─" * len(line) + "┘")


async def main():
    async with websockets.connect(f"{args.server}/ws/glasses") as ws:
        print("Glasses connected. Press Enter to tap, q + Enter to quit.")

        async def listen():
            async for raw in ws:
                m = json.loads(raw)
                show(m.get("text", m), m.get("count"))

        listener = asyncio.create_task(listen())
        while True:
            cmd = await asyncio.to_thread(input)
            if cmd.strip().lower() == "q":
                break
            await ws.send(json.dumps({"type": "capture_request"}))
            print("  (tap → capture_request sent)")
        listener.cancel()


asyncio.run(main())
