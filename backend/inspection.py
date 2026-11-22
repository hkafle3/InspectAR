"""InspectAR checklist engine: templates, the current inspection, and commands.

Every change returns a list of glasses messages ({"type": "step"|"result"|"reading"|"done", ...}).
main.py sends them and pushes the new state to report pages.
"""
import asyncio
import json
import logging
import re
from datetime import datetime

from . import config
from .structuring import assess_photo, mock_structure, read_photo, structure

log = logging.getLogger("inspectlog.inspection")
TEMPLATES_DIR = config.ROOT / "templates"
STATE_FILE = config.DATA_DIR / "inspection.json"

current: dict | None = None
on_update = None  # set by main.py: async fn() that pushes the latest state to report pages
_background: set = set()


# ------------------------------------------------------------------ templates

def templates() -> dict[str, dict]:
    out = {}
    for f in sorted(TEMPLATES_DIR.glob("*.json")):
        t = json.loads(f.read_text())
        out[t["id"]] = t
    return out


def template() -> dict | None:
    return templates().get(current["template_id"]) if current else None


# ------------------------------------------------------- move-in baseline

BASELINES_DIR = config.ROOT / "baselines"
BASELINE_PHOTOS_DIR = BASELINES_DIR / "photos"
STOP_WORDS = {"near", "with", "from", "there", "this", "that", "small", "large", "minor", "major",
              "some", "next", "looks", "like", "little", "big", "moderate", "about", "around"}


def baseline_for(template_id: str) -> dict | None:
    """The move-in record for this template, if one exists (baselines/<template_id>.json)."""
    f = BASELINES_DIR / f"{template_id}.json"
    return json.loads(f.read_text()) if f.exists() else None


def _words(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[a-z]+", (text or "").lower()) if len(w) >= 4 and w not in STOP_WORDS}


def compare_to_baseline(base: dict | None, note: str) -> str | None:
    """Was this flag already there at move-in? 'new' | 'pre-existing' | 'check' | None (no record)."""
    if not base:
        return None
    if base.get("status") != "flag":
        return "new"
    if not note.strip():
        return "check"
    return "pre-existing" if _words(note) & _words(base.get("note", "")) else "new"


ATTRIBUTION_TEXT = {"new": "new", "pre-existing": "at move-in", "check": "check move-in"}


# ---------------------------------------------------------------- state

def load():
    global current
    if STATE_FILE.exists():
        current = json.loads(STATE_FILE.read_text())


def save():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=2))
    tmp.replace(STATE_FILE)


def clear():
    global current
    current = None
    STATE_FILE.unlink(missing_ok=True)


def active() -> bool:
    return bool(current and not current.get("finished_at"))


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def start(template_id: str, address: str = "", inspector: str = "", consent: bool = False) -> list[dict]:
    global current
    t = templates().get(template_id)
    if not t:
        raise KeyError(template_id)
    base = baseline_for(t["id"]) or {}
    base_steps = base.get("steps", {})

    def step_baseline(step_id: str) -> dict | None:
        b = base_steps.get(step_id)
        if not b:
            return None
        photo = b.get("photo")
        return {**b, "photo_url": f"/movein/{photo}" if photo else None}

    current = {
        "id": datetime.now().strftime("%Y%m%d-%H%M%S"),
        "template_id": t["id"],
        "template_name": t["name"],
        "property_address": address or config.PROPERTY_ADDRESS,
        "inspector": inspector or config.INSPECTOR_NAME,
        "consent": consent,
        "started_at": now(),
        "finished_at": None,
        "current_step": 0,
        "results": [{"step_id": s["id"], "status": "pending", "note": "", "photo_path": None,
                     "photo_url": None, "reading": None, "confidence": None, "ai_fields": None,
                     "time": None, "baseline": step_baseline(s["id"]), "attribution": None}
                    for s in t["steps"]],
        "baseline": {k: base[k] for k in ("label", "date", "inspector") if k in base} or None,
        "log": [],
    }
    note_log(f"Started {t['name']}" + (f" with the {base['label']} record" if base.get("label") else ""))
    save()
    return [step_msg()]


def note_log(text: str):
    log.info(text)
    current["log"].append({"time": now(), "text": text})
    current["log"] = current["log"][-50:]


def step_msg() -> dict:
    t = template()
    i = current["current_step"]
    s = t["steps"][i]
    return {"type": "step", "line1": f"Step {i + 1}/{len(t['steps'])}",
            "line2": s["short"], "line3": movein_hint(i) or s["instruction"], "step": i}


def movein_hint(i: int) -> str | None:
    """What the move-in record says about this step, in a few words for the display."""
    b = current["results"][i].get("baseline")
    if not b:
        return None
    if b.get("status") == "flag":
        return f"Move-in: {b.get('short') or b.get('note', '')}"[:26]
    if template()["steps"][i].get("read"):
        return None  # keep "Tap to read the thermostat"
    return "Move-in: OK"


def counts() -> dict:
    c = {"pass": 0, "flag": 0, "pending": 0, "readings": 0, "new": 0, "pre-existing": 0, "check": 0}
    for r in current["results"]:
        c[r["status"]] += 1
        c["readings"] += 1 if r["reading"] else 0
        if r["status"] == "flag" and r.get("attribution"):
            c[r["attribution"]] += 1
    return c


def done_msg() -> dict:
    c = counts()
    if current.get("baseline") and c["flag"]:
        new = f"{c['new']} new issue" + ("" if c["new"] == 1 else "s")
        rest = [f"{c['pass']} pass"] + ([f"{c['pre-existing']} at move-in"] if c["pre-existing"] else [])
        return {"type": "done", "line1": "Done", "line2": new, "line3": " · ".join(rest)}
    return {"type": "done", "line1": "Done", "line2": f"{c['pass']} pass · {c['flag']} flag"}


def finish() -> list[dict]:
    current["finished_at"] = now()
    c = counts()
    note_log(f"Finished: {c['pass']} pass, {c['flag']} flag, {c['pending']} skipped")
    save()
    return [done_msg()]


def advance() -> list[dict]:
    if current["current_step"] + 1 >= len(current["results"]):
        return finish()
    current["current_step"] += 1
    save()
    return [step_msg()]


# ------------------------------------------------------------ voice commands

def parse_command(text: str) -> tuple[str, str]:
    """'flag water stain near the light' -> ('flag', 'water stain near the light')."""
    t = (text or "").strip()
    low = t.lower().strip(" .!?,")
    if re.match(r"^(pass|passed|good|ok|okay|looks good|all good)\b", low):
        return "pass", ""
    m = re.match(r"^(flag|flagged|issue)\b[\s,:.-]*(.*)$", t, re.I | re.S)
    if m:
        return "flag", m.group(2).strip()
    if re.match(r"^(next|skip)\b", low):
        return "next", ""
    if re.match(r"^(back|go back|previous)\b", low):
        return "back", ""
    if re.match(r"^(repeat|again|say again)\b", low):
        return "repeat", ""
    if re.match(r"^(finish|finished|done|end inspection)\b", low):
        return "finish", ""
    return "flag-implied", t


async def _structure_flag(r: dict, photo: bytes | None, media_type: str):
    s = template()["steps"][current["results"].index(r)]
    where = f"{s['area']}, {s['label'].lower()}"
    text = f"{r['note']} ({where})" if r["note"] else f"Problem with {s['label'].lower()} ({s['area']})"
    fields, made_by = await structure(text, photo, media_type, location_hint=where)
    r["ai_fields"] = {k: fields[k] for k in ("issue", "category", "severity", "description",
                                             "recommendation", "short_label")}
    r["ai_fields"]["made_by"] = made_by
    if made_by.startswith("mock"):  # free mode: the inspector's own words are the description
        note = r["note"] or fields["issue"]
        r["ai_fields"]["description"] = note[:1].upper() + note[1:] + ("" if note.endswith(".") else ".")
    if r.get("severity_override"):  # a fix made on the phone wins over the AI
        r["ai_fields"]["severity"] = r["severity_override"]


def edit_step(step_id: str, attribution: str | None = None, severity: str | None = None) -> dict:
    """A fix made on the phone. Returns the glasses message confirming it."""
    ids = [r["step_id"] for r in current["results"]]
    r = current["results"][ids.index(step_id)]  # ValueError if unknown
    changed = []
    if attribution in ATTRIBUTION_TEXT:
        r["attribution"] = attribution
        changed.append({"new": "New", "pre-existing": "Pre-existing", "check": "Check"}[attribution])
    if severity:
        r["severity_override"] = severity
        if r.get("ai_fields"):
            r["ai_fields"]["severity"] = severity
        changed.append(severity)
    note_log(f"Edited on phone: {template()['steps'][ids.index(step_id)]['short']} -> {', '.join(changed) or 'no change'}")
    save()
    return {"type": "result", "line1": "Updated on phone", "line2": (changed[0] if changed else "No change")[:20]}


async def command(cmd: str, note: str = "", photo: bytes | None = None,
                  media_type: str = "image/jpeg", fields: dict | None = None) -> list[dict]:
    if not active():
        return []
    i = current["current_step"]
    r = current["results"][i]
    label = template()["steps"][i]["short"]

    if cmd == "flag-implied":
        note_log(f"Didn't hear pass/flag; flagged step {i + 1} with the note: \"{note}\"")
        cmd = "flag"
    if cmd == "pass":
        r.update(status="pass", time=now(), attribution=None)
        if note:
            r["note"] = note
        note_log(f"Step {i + 1} {label}: pass")
        return [{"type": "result", "line1": "Pass", "line2": label}] + advance()
    if cmd == "flag":
        r.update(status="flag", note=note or r["note"], time=now())
        r["attribution"] = compare_to_baseline(r.get("baseline"), r["note"])
        photo_bytes = photo or _read_step_photo(r)
        seen = f" ({ATTRIBUTION_TEXT[r['attribution']]})" if r["attribution"] else ""
        note_log(f"Step {i + 1} {label}: flag - {r['note'] or 'no note'}{seen}")
        # Confirm on the glasses right away; the AI write-up fills in on the report a few seconds later.
        quick = mock_structure(r["note"])["issue"] if r["note"] else label
        if fields:  # the photo check already described it: no second AI call (keeps the next tap fast)
            r["ai_fields"] = fields
            if r.get("severity_override"):
                r["ai_fields"]["severity"] = r["severity_override"]
            save()
        else:
            task = asyncio.create_task(_structure_later(current["id"], i, photo_bytes, media_type))
            _background.add(task)
            task.add_done_callback(_background.discard)
        line1 = f"Flagged · {ATTRIBUTION_TEXT[r['attribution']]}" if r["attribution"] else "Flagged"
        return [{"type": "result", "line1": line1, "line2": quick[:20]}] + advance()
    if cmd == "next":
        note_log(f"Step {i + 1} {label}: skipped")
        return advance()
    if cmd == "back":
        current["current_step"] = max(0, i - 1)
        save()
        return [step_msg()]
    if cmd == "repeat":
        return [step_msg()]
    if cmd == "finish":
        return finish()
    raise ValueError(cmd)


async def _structure_later(inspection_id: str, i: int, photo: bytes | None, media_type: str):
    try:
        if not current or current["id"] != inspection_id:
            return
        r = current["results"][i]
        await _structure_flag(r, photo, media_type)
        if current and current["id"] == inspection_id:
            save()
            if on_update:
                await on_update()
    except Exception as e:
        log.warning("Flag write-up failed: %s", e)


def _read_step_photo(r: dict) -> bytes | None:
    if r.get("photo_path"):
        p = config.PHOTOS_DIR / r["photo_path"]
        if p.exists():
            return p.read_bytes()
    return None


def attach_photo(step_index: int, photo: bytes, ext: str):
    r = current["results"][step_index]
    if r.get("photo_path"):
        (config.PHOTOS_DIR / r["photo_path"]).unlink(missing_ok=True)
    name = f"insp-{r['step_id']}-{datetime.now():%H%M%S%f}{ext}"
    (config.PHOTOS_DIR / name).write_bytes(photo)
    r["photo_path"] = name
    r["photo_url"] = f"/photos/{name}"


async def capture(photo: bytes | None, ext: str, media_type: str, transcript: str,
                  step_id: str | None = None) -> list[dict]:
    """A tap capture (photo and/or voice note) while an inspection is active."""
    i = current["current_step"]
    if step_id:  # a late photo for an earlier step
        ids = [r["step_id"] for r in current["results"]]
        if step_id in ids:
            i = ids.index(step_id)
    r = current["results"][i]
    step = template()["steps"][i]
    if photo:
        attach_photo(i, photo, ext)
        save()

    cmd, note = parse_command(transcript) if transcript.strip() else (None, "")
    if i != current["current_step"]:
        cmd = None  # late photo for an earlier step: never move the checklist

    # Read steps: a photo gets read by the vision model, then auto-pass.
    if step.get("read") and photo and i == current["current_step"] and cmd in (None, "pass", "flag-implied"):
        result, made_by = await read_photo(photo, media_type, step["label"], transcript)
        r.update(status="pass", reading=result["reading"], confidence=result["confidence"], time=now())
        note_log(f"Step {i + 1} {step['short']}: read \"{result['reading']}\" ({result['confidence']}, {made_by})")
        return [{"type": "reading", "line1": "Read", "line2": result["reading"][:20]}] + advance()

    # A photo for a step that's already flagged: redo the AI fields with the photo.
    if photo and cmd is None and r["status"] == "flag":
        await _structure_flag(r, photo, media_type)
        save()
        note_log(f"Step {i + 1} {step['short']}: photo added, flag details updated")
        return []

    if cmd is None and photo and i == current["current_step"]:
        # Photo only, no voice: the AI looks at it and decides pass or flag.
        verdict, made_by = await assess_photo(photo, media_type, step["label"], step["area"], step["instruction"])
        if verdict is None:
            note_log(f"Step {i + 1} {step['short']}: photo saved (no AI to check it: swipe to pass, or say flag)")
            return [{"type": "result", "line1": "Photo saved", "line2": "Swipe › to pass"}, step_msg()]
        if verdict["problem"]:
            note_log(f"Step {i + 1} {step['short']}: AI saw a problem in the photo: {verdict['issue']} ({made_by})")
            base = mock_structure(verdict["issue"], f"{step['area']}, {step['label'].lower()}")
            seen = verdict.get("seen") or ""
            fields = {"issue": verdict["issue"], "category": base["category"], "severity": base["severity"],
                      "description": seen.split(". ")[0].rstrip(".") + "." if seen else base["description"],
                      "recommendation": base["recommendation"], "short_label": base["short_label"],
                      "made_by": made_by}
            return await command("flag", verdict["issue"], photo, media_type, fields=fields)
        note_log(f"Step {i + 1} {step['short']}: AI saw no problem in the photo ({made_by})")
        return await command("pass", "", photo, media_type)

    if cmd is None:  # photo for an earlier step
        note_log(f"Step {i + 1} {step['short']}: photo saved")
        return []
    return await command(cmd, note, photo, media_type)
