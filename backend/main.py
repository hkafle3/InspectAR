"""InspectAR backend. Run with:
    uvicorn backend.main:app --host 0.0.0.0 --port 8000
"""
import asyncio
import pathlib
import json
import logging
import time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, inspection, pdf, store
from .structuring import SEVERITIES, structure, warm_up
from .transcribe import transcribe
from .transcribe import warm_up as warm_up_speech

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("inspectlog")

app = FastAPI(title="InspectAR")
store.load()
inspection.load()
app.mount("/photos", StaticFiles(directory=config.PHOTOS_DIR), name="photos")
inspection.BASELINE_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/movein", StaticFiles(directory=inspection.BASELINE_PHOTOS_DIR), name="movein")

@app.on_event("startup")
async def startup():
    asyncio.create_task(warm_up())
    asyncio.create_task(warm_up_speech())
    asyncio.create_task(expire_presence())


RESULT_HOLD_SECONDS = 1.5  # how long "Flagged" / "Read" stays on the glasses before the next step


# ------------------------------------------------------------ WebSocket hubs

class Hub:
    def __init__(self, name: str):
        self.name = name
        self.clients: set[WebSocket] = set()

    async def send_bytes_all(self, data: bytes):
        for ws in list(self.clients):
            try:
                await ws.send_bytes(data)
            except Exception:
                self.clients.discard(ws)

    async def send_all(self, msg: dict):
        for ws in list(self.clients):
            try:
                await ws.send_json(msg)
            except Exception:
                self.clients.discard(ws)


glasses, phones, reports = Hub("glasses"), Hub("phone"), Hub("report")

# Report pages open on a phone. When one is in the wearer's hand (page visible), the glasses step aside.
# The phone page repeats its presence every few seconds; a locked phone that never said goodbye times out.
phone_pages: set[WebSocket] = set()
phone_in_hand: dict[WebSocket, float] = {}
PRESENCE_TIMEOUT = 8.0


async def broadcast_devices():
    await reports.send_all({"type": "devices", "glasses": len(glasses.clients),
                            "phone": len(phones.clients) + len(phone_pages)})


async def set_in_hand(ws: WebSocket, active: bool):
    """Seamless handoff: phone picked up -> glasses say 'On phone'; put away -> glasses resume."""
    was = bool(phone_in_hand)
    if active:
        phone_in_hand[ws] = time.monotonic()
    else:
        phone_in_hand.pop(ws, None)
    await _handoff_changed(was)


async def _handoff_changed(was: bool):
    now_on_phone = bool(phone_in_hand)
    if was == now_on_phone:
        return
    await reports.send_all({"type": "handoff", "on": "phone" if now_on_phone else "glasses"})
    if not inspection.active():
        return
    if now_on_phone:
        step = inspection.template()["steps"][inspection.current["current_step"]]
        log.info("Handoff: phone picked up at %s", step["short"])
        await glasses.send_all({"type": "result", "handoff": True, "line1": "On phone",
                                "line2": step["short"], "line3": "Put phone away to resume"})
    else:
        log.info("Handoff: back to the glasses")
        await glasses.send_all(inspection.step_msg())


async def expire_presence():
    while True:
        await asyncio.sleep(2)
        stale = [ws for ws, seen in phone_in_hand.items() if time.monotonic() - seen > PRESENCE_TIMEOUT]
        if stale:
            was = bool(phone_in_hand)
            for ws in stale:
                phone_in_hand.pop(ws, None)
            await _handoff_changed(was)


async def push_inspection(glasses_msgs: list[dict]):
    """Send checklist updates: state to report pages, display lines to the glasses."""
    await reports.send_all({"type": "inspection", "inspection": inspection_payload()})
    if not glasses_msgs:
        return
    first, rest = glasses_msgs[0], glasses_msgs[1:]
    await glasses.send_all(first)
    await reports.send_all({"type": "hud", "msg": first})  # mirror the glasses display on the web page
    if rest:
        async def later():
            if first["type"] in ("result", "reading"):
                await asyncio.sleep(RESULT_HOLD_SECONDS)
            for m in rest:
                await glasses.send_all(m)
                await reports.send_all({"type": "hud", "msg": m})
        asyncio.create_task(later())


async def _push_state():
    await reports.send_all({"type": "inspection", "inspection": inspection_payload()})


inspection.on_update = _push_state


def inspection_payload() -> dict | None:
    return {**inspection.current, "template": inspection.template()} if inspection.current else None


def glasses_greeting() -> dict:
    if inspection.active():
        return inspection.step_msg()
    return {"type": "status", "text": "Connected", "count": len(store.all_entries())}


async def request_capture(source: str) -> bool:
    """Ask the phone app to take a photo + record a note. False if no phone is connected."""
    log.info("capture_request from %s (%d phone(s) connected)", source, len(phones.clients))
    if not phones.clients:
        await glasses.send_all({"type": "status", "text": "No phone · swipe › to pass"})
        return False
    await phones.send_all({"type": "capture_request"})
    await glasses.send_all({"type": "status", "text": "Listening…"})
    return True


async def _ws_loop(ws: WebSocket, hub: Hub, on_message=None, greeting: dict | None = None, on_bytes=None):
    await ws.accept()
    if greeting:
        await ws.send_json(greeting)
    hub.clients.add(ws)
    await broadcast_devices()
    try:
        while True:
            m = await ws.receive()
            if m["type"] == "websocket.disconnect":
                break
            if m.get("bytes") is not None:  # live view frame from the glasses
                if on_bytes:
                    await on_bytes(m["bytes"])
                continue
            msg = json.loads(m.get("text") or "null")
            if on_message and isinstance(msg, dict):
                await on_message(ws, msg)
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        hub.clients.discard(ws)
        await broadcast_devices()


@app.websocket("/ws/glasses")
async def ws_glasses(ws: WebSocket):
    async def handle(ws, msg):
        if msg.get("type") == "capture_request":
            await request_capture("glasses")
        elif msg.get("type") == "command":  # touchpad swipes: pass / back
            if not inspection.active():
                await ws.send_json({"type": "status", "text": "Start a checklist on the phone"})
                return
            cmd = msg.get("command")
            if cmd in ("pass", "flag", "next", "back", "repeat", "finish"):
                await push_inspection(await inspection.command(cmd, msg.get("note", "")))

    async def frame(data: bytes):
        if not live_on:
            return
        # Newest frame only: a page still busy with the previous frame skips this one (no backlog, no lag).
        for page in list(reports.clients):
            if page in _frame_busy:
                continue
            _frame_busy.add(page)

            async def push(page=page):
                try:
                    await page.send_bytes(data)
                except Exception:
                    pass
                finally:
                    _frame_busy.discard(page)
            asyncio.create_task(push())

    await _ws_loop(ws, glasses, handle, greeting=glasses_greeting(), on_bytes=frame)


@app.websocket("/ws/phone")
async def ws_phone(ws: WebSocket):
    await _ws_loop(ws, phones)


@app.websocket("/ws/report")
async def ws_report(ws: WebSocket):
    async def handle(ws, msg):
        if msg.get("type") == "hello" and msg.get("phone"):
            phone_pages.add(ws)
            await broadcast_devices()
        elif msg.get("type") == "presence":
            await set_in_hand(ws, bool(msg.get("active")))
            # Always tell this page the current state (a reload can overlap the old page's socket).
            await ws.send_json({"type": "handoff", "on": "phone" if phone_in_hand else "glasses"})

    try:
        await _ws_loop(ws, reports, handle)
    finally:
        phone_pages.discard(ws)
        await set_in_hand(ws, False)
        await broadcast_devices()


# ------------------------------------------------------------------ API

@app.get("/api/config")
def get_config():
    return {"property_address": config.PROPERTY_ADDRESS, "inspector": config.INSPECTOR_NAME,
            "ai_mode": config.AI_MODE}


@app.get("/api/entries")
def get_entries():
    return store.all_entries()


@app.post("/api/capture")
async def capture(photo: UploadFile | None = File(None), audio: UploadFile | None = File(None),
                  note: str = Form(""), step_id: str = Form("")):
    """A tap: photo and/or voice note. Goes to the current checklist step if an inspection
    is running, otherwise becomes a free-form entry."""
    photo_bytes, ext, media_type = None, ".jpg", "image/jpeg"
    if photo is not None and photo.filename:
        photo_bytes = await photo.read()
        ext = Path(photo.filename).suffix.lower() or ".jpg"
        media_type = {".png": "image/png", ".webp": "image/webp"}.get(ext, "image/jpeg")

    transcript = note.strip()
    if not transcript and audio is not None and audio.filename:
        transcript = await transcribe(await audio.read(), audio.filename)

    if inspection.active():
        msgs = await inspection.capture(photo_bytes, ext, media_type, transcript, step_id or None)
        await push_inspection(msgs)
        return {"mode": "inspection", "transcript": transcript, "glasses": msgs,
                "inspection": inspection.current}

    entry_id = store.reserve_id()
    photo_file = None
    if photo_bytes:
        photo_file = f"{entry_id}{ext}"
        (config.PHOTOS_DIR / photo_file).write_bytes(photo_bytes)
    fields, made_by = await structure(transcript, photo_bytes, media_type)
    entry = {"id": entry_id, "created_at": datetime.now().isoformat(timespec="seconds"),
             **fields, "transcript": transcript, "photo_file": photo_file,
             "photo_url": f"/photos/{photo_file}" if photo_file else None, "made_by": made_by}
    store.add(entry)
    log.info("Logged #%d %s (%s)", entry_id, fields["short_label"], made_by)

    await glasses.send_all({"type": "logged", "id": entry_id,
                            "text": f"Logged #{entry_id} · {fields['short_label']}",
                            "count": len(store.all_entries())})
    await reports.send_all({"type": "entry", "entry": entry})
    return entry


live_on = False
_frame_busy: set = set()

# ---- recording the glasses display (for the submission video) ----
import subprocess, time as _time
ADB = str(pathlib.Path.home() / "Library/Android/sdk/platform-tools/adb")
_rec = {"proc": None, "started": None, "file": None}


async def _rec_state():
    on = _rec["proc"] is not None and _rec["proc"].poll() is None
    await reports.send_all({"type": "recording", "on": on, "started": _rec["started"] if on else None,
                            "file": _rec["file"]})
    return on


@app.post("/api/record/start")
async def record_start():
    if _rec["proc"] is not None and _rec["proc"].poll() is None:
        return {"on": True}
    _rec["proc"] = subprocess.Popen([ADB, "shell", "screenrecord", "--time-limit", "180", "--bit-rate", "4000000",
                                     "/sdcard/inspectar_rec.mp4"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _rec["started"] = _time.time()
    _rec["file"] = None
    await asyncio.sleep(0.5)
    on = await _rec_state()
    if not on:
        raise HTTPException(409, "Couldn't start: are the glasses plugged in?")
    asyncio.create_task(_rec_watch())
    return {"on": True}


async def _rec_watch():
    p = _rec["proc"]
    while p is not None and p.poll() is None:
        await asyncio.sleep(1)
    if _rec["proc"] is p:  # stopped by the 3-minute limit: save it
        await _rec_save()


async def _rec_save():
    out = config.ROOT / "video" / f"glasses_view_{datetime.now():%H%M%S}.mp4"
    out.parent.mkdir(exist_ok=True)
    await asyncio.sleep(1.0)  # let the file finish
    r = await asyncio.to_thread(subprocess.run, [ADB, "pull", "/sdcard/inspectar_rec.mp4", str(out)],
                                capture_output=True)
    _rec["proc"] = None
    _rec["file"] = str(out) if r.returncode == 0 else None
    await _rec_state()


@app.post("/api/record/stop")
async def record_stop():
    p = _rec["proc"]
    if p is None:
        return {"on": False, "file": _rec["file"]}
    await asyncio.to_thread(subprocess.run, [ADB, "shell", "pkill", "-INT", "screenrecord"], capture_output=True)
    await asyncio.to_thread(p.wait, 10)
    await _rec_save()
    return {"on": False, "file": _rec["file"]}


class LiveBody(BaseModel):
    on: bool


@app.post("/api/live")
async def set_live(body: LiveBody):
    """Turn the glasses' live camera view on or off (the glasses show ● LIVE while it's on)."""
    global live_on
    live_on = body.on and bool(glasses.clients)
    await glasses.send_all({"type": "live", "on": live_on})
    await reports.send_all({"type": "live", "on": live_on})
    return {"on": live_on, "glasses": len(glasses.clients)}


@app.post("/api/capture_request")
async def capture_request():
    """The page's Capture button: same as a tap on the glasses (photo + voice note on the glasses)."""
    if glasses.clients:
        await glasses.send_all({"type": "capture"})
        return {"sent": True, "to": "glasses"}
    return {"sent": await request_capture("report page"), "to": "phone"}


@app.delete("/api/entries/{entry_id}")
async def delete_entry(entry_id: int):
    if not store.delete(entry_id):
        raise HTTPException(404, "No such entry")
    await reports.send_all({"type": "deleted", "id": entry_id})
    return {"ok": True}


@app.post("/api/reset")
async def reset():
    """Clear everything (free-form entries and the inspection) for a fresh demo run."""
    store.reset()
    inspection.clear()
    await reports.send_all({"type": "reset"})
    await reports.send_all({"type": "inspection", "inspection": None})
    await glasses.send_all({"type": "status", "text": "Ready", "count": 0})
    return {"ok": True}


# ----------------------------------------------------------- checklist mode

class StartBody(BaseModel):
    template_id: str
    property_address: str = ""
    inspector: str = ""
    consent: bool = False


class CommandBody(BaseModel):
    command: str
    note: str = ""


class EditBody(BaseModel):
    attribution: str | None = None  # new | pre-existing | check
    severity: str | None = None


@app.get("/api/templates")
def get_templates():
    out = []
    for tpl in inspection.templates().values():
        base = inspection.baseline_for(tpl["id"])
        notes = {}
        for sid, b in ((base or {}).get("steps") or {}).items():
            notes[sid] = b.get("note") if b.get("status") == "flag" else (b.get("reading") or "No issues noted")
        out.append({**tpl, "movein": base.get("label") if base else None, "movein_notes": notes})
    return out


@app.post("/api/inspections")
async def start_inspection(body: StartBody):
    try:
        msgs = inspection.start(body.template_id, body.property_address, body.inspector, body.consent)
    except KeyError:
        raise HTTPException(404, "No such template")
    await push_inspection(msgs)
    return inspection.current


@app.get("/api/inspections/current")
def current_inspection():
    if not inspection.current:
        raise HTTPException(404, "No inspection")
    return inspection_payload()


@app.post("/api/inspections/current/command")
async def inspection_command(body: CommandBody):
    if not inspection.active():
        raise HTTPException(409, "No inspection running")
    if body.command not in ("pass", "flag", "next", "back", "repeat", "finish"):
        raise HTTPException(400, "Unknown command")
    msgs = await inspection.command(body.command, body.note.strip())
    await push_inspection(msgs)
    return {"glasses": msgs, "inspection": inspection.current}


@app.post("/api/inspections/current/steps/{step_id}")
async def edit_step(step_id: str, body: EditBody):
    """A one-tap fix made on the phone (new vs pre-existing, severity). The glasses confirm it."""
    if not inspection.current:
        raise HTTPException(404, "No inspection")
    if body.severity and body.severity not in SEVERITIES:
        raise HTTPException(400, "Unknown severity")
    try:
        confirm = inspection.edit_step(step_id, body.attribution, body.severity)
    except ValueError:
        raise HTTPException(404, "No such step")
    # Phone in hand: leave the confirmation up. Otherwise show it, then go back to the step.
    after = [] if phone_in_hand else [inspection.step_msg() if inspection.active() else inspection.done_msg()]
    await push_inspection([confirm] + after)
    return inspection.current


# ------------------------------------------------------------------ pages

@app.get("/report.pdf")
def report_pdf():
    data = pdf.build(store.all_entries(), inspection.current, inspection.template())
    name = f"inspection-report-{datetime.now():%Y-%m-%d}.pdf"
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}"'})


@app.get("/")
def index():
    return FileResponse(config.STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})
