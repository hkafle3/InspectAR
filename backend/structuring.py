"""Turn a transcript (+ optional photo) into a structured defect entry.

Three modes, picked by AI_MODE in .env:
  mock      - free rule-based parser, no AI, always works
  ollama    - free local model via the Ollama app
  anthropic - Claude API (costs money)
If an AI call fails, we fall back to the mock parser so the demo never breaks.
"""
import base64
import json
import logging
import re

import httpx

from . import config

log = logging.getLogger("inspectlog.structuring")

CATEGORIES = ["Plumbing", "Electrical", "Structural", "Roofing", "HVAC",
              "Interior", "Exterior", "Safety", "Other"]
SEVERITIES = ["Minor", "Moderate", "Major", "Safety hazard"]
FIELDS = ["issue", "location", "category", "severity", "description",
          "recommendation", "short_label"]
LABEL_MAX = 28

SCHEMA = {
    "type": "object",
    "properties": {
        "issue": {"type": "string"},
        "location": {"type": "string"},
        "category": {"type": "string", "enum": CATEGORIES},
        "severity": {"type": "string", "enum": SEVERITIES},
        "description": {"type": "string"},
        "recommendation": {"type": "string"},
        "short_label": {"type": "string"},
    },
    "required": FIELDS,
    "additionalProperties": False,
}

PROMPT = f"""You are helping a home inspector write a report. They looked at a defect,
took a photo (if attached) and said a short note. Turn it into one report entry.

Inspector's note: "{{transcript}}"

Return JSON with:
- issue: 2-4 words naming the defect, e.g. "Water stain"
- location: room and spot, e.g. "Master bedroom, ceiling" (use the note; "Unspecified" if unknown)
- category: one of {", ".join(CATEGORIES)}
- severity: one of {", ".join(SEVERITIES)} (use the note's word if given)
- description: ONE short factual sentence about what is visible. Do not repeat the location or the issue name.
- recommendation: ONE short action, at most 10 words, e.g. "Have a plumber check for an active leak."
- short_label: at most {LABEL_MAX} characters, like "Water stain · Master bed"
Plain, professional wording. No filler, no hedging, no "consider". Only use what the note and photo support. Do not invent measurements."""


# ---------------------------------------------------------------- mock parser

SEVERITY_WORDS = [
    ("Safety hazard", ["hazard", "dangerous", "unsafe", "safety", "urgent"]),
    ("Major", ["major", "severe", "serious", "significant", "bad"]),
    ("Moderate", ["moderate", "medium"]),
    ("Minor", ["minor", "small", "slight", "cosmetic", "low"]),
]

CATEGORY_WORDS = [
    ("Safety", ["smoke detector", "carbon monoxide", "railing", "handrail", "trip", "gfci"]),
    ("Interior", ["scuff", "scratch", "dent", "nail hole"]),  # cosmetic, even "by the light switch"
    ("Plumbing", ["water", "leak", "stain", "drip", "pipe", "faucet", "toilet", "drain", "sink", "mold", "damp"]),
    ("Electrical", ["outlet", "wire", "wiring", "breaker", "panel", "switch", "light", "electrical"]),
    ("Roofing", ["roof", "shingle", "gutter", "flashing", "chimney"]),
    ("HVAC", ["furnace", "hvac", "ac ", "air condition", "vent", "duct", "thermostat", "boiler", "radiator"]),
    ("Structural", ["crack", "foundation", "beam", "joist", "sag", "settle", "structural"]),
    ("Exterior", ["siding", "deck", "porch", "driveway", "exterior", "window frame", "paint peel"]),
    ("Interior", ["drywall", "floor", "door", "window", "cabinet", "tile", "carpet", "paint"]),
]

ROOM_WORDS = ["master bedroom", "bedroom", "bathroom", "kitchen", "living room", "dining room",
              "basement", "attic", "garage", "hallway", "laundry", "closet", "stairs", "roof",
              "porch", "deck", "office", "den", "foyer", "entry"]

RECOMMENDATIONS = {
    "Plumbing": "Have a licensed plumber check for an active leak.",
    "Electrical": "Have a licensed electrician evaluate and repair.",
    "Structural": "Have a structural engineer evaluate.",
    "Roofing": "Have a roofing contractor inspect and repair.",
    "HVAC": "Have an HVAC technician service the system.",
    "Interior": "Repair as needed; monitor for changes.",
    "Exterior": "Repair to prevent water entry and further damage.",
    "Safety": "Correct promptly to remove the safety risk.",
    "Other": "Evaluate further and repair as needed.",
}

ABBREV = {"master bedroom": "Master bed", "bedroom": "Bedroom", "bathroom": "Bath",
          "living room": "Living rm", "dining room": "Dining rm", "basement": "Basement",
          "kitchen": "Kitchen", "hallway": "Hall"}


def _find(text: str, table):
    for value, words in table:
        if any(w in text for w in words):
            return value
    return None


def mock_structure(transcript: str, location_hint: str | None = None) -> dict:
    """Free, rule-based: 'water stain on ceiling, master bedroom, moderate'."""
    note = (transcript or "").strip() or "Unlabeled defect"
    low = f" {note.lower()} "
    parts = [p.strip() for p in re.split(r"[,;.]", note) if p.strip()]

    category = _find(low, CATEGORY_WORDS) or "Other"
    cosmetic = any(w in low for w in ("scuff", "scratch", "dent", "nail hole"))
    severity = _find(low, SEVERITY_WORDS) or ("Minor" if cosmetic else "Moderate")
    room = next((r for r in ROOM_WORDS if r in low), None)

    # Issue: the first chunk, minus "on the ceiling" style tails and severity words.
    issue = parts[0] if parts else note
    issue = re.split(r"\b(on|in|at|near|by)\b", issue, maxsplit=1, flags=re.I)[0].strip() or issue
    sev_words = [w for _, ws in SEVERITY_WORDS for w in ws]
    if issue.lower() in sev_words or (room and issue.lower() == room):
        issue = note
    issue = issue[:1].upper() + issue[1:]

    spot = None
    m = re.search(r"\b(?:on|in|at|near|by) (?:the )?([a-z ]+)", parts[0].lower() if parts else "")
    if m:
        spot = m.group(1).strip()
    if room and spot and spot.startswith(room):
        location = spot.capitalize()
    elif room and spot:
        location = f"{room.capitalize()}, {spot}"
    elif room:
        location = room.capitalize()
    elif spot:
        location = spot.capitalize()
    else:
        location = "Unspecified"

    if location_hint:  # checklist steps already know where we are
        location = location_hint
        room = None
    entry = {
        "issue": issue,
        "location": location,
        "category": category,
        "severity": severity,
        "description": note[:1].upper() + note[1:] + ("" if note.endswith(".") else "."),
        "recommendation": RECOMMENDATIONS[category],
        "short_label": "",
    }
    entry["short_label"] = make_label(issue, ABBREV.get(room or "", location.split(",")[0]))
    return entry


def make_label(issue: str, place: str) -> str:
    label = f"{issue} · {place}" if place and place != "Unspecified" else issue
    if len(label) > LABEL_MAX:
        label = issue if len(issue) <= LABEL_MAX else issue[: LABEL_MAX - 1].rstrip() + "…"
    return label


# ------------------------------------------------------------- validation

def validate(data) -> dict | None:
    """Return a cleaned entry, or None if it's unusable."""
    if not isinstance(data, dict):
        return None
    if any(not isinstance(data.get(k), str) or not data[k].strip() for k in FIELDS):
        return None
    out = {k: data[k].strip() for k in FIELDS}
    out["category"] = next((c for c in CATEGORIES if c.lower() == out["category"].lower()), "Other")
    out["severity"] = next((s for s in SEVERITIES if s.lower() == out["severity"].lower()), "Moderate")
    out["description"] = _one_sentence(out["description"])
    out["recommendation"] = _one_sentence(re.sub(r"^(consider|you may want to|it is recommended to)\s+", "",
                                                 out["recommendation"], flags=re.I))
    if len(out["short_label"]) > LABEL_MAX:
        out["short_label"] = make_label(out["issue"], out["location"].split(",")[0])
    return out


def _one_sentence(text: str) -> str:
    """Keep the first sentence and drop trailing hedges like 'if necessary'."""
    first = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]
    first = re.sub(r"\s+(if necessary|if needed|as needed)(?=[.!?]?$)", "", first, flags=re.I)
    first = re.sub(r",?\s+and (consider|possibly|maybe)\b.*$", ".", first, flags=re.I)
    first = first[:1].upper() + first[1:]
    return first if first.endswith((".", "!", "?")) else first + "."


def _parse_json(text: str):
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


# ------------------------------------------------------------- AI backends

async def warm_up():
    """Load the local model at server start so the first tap during the demo isn't slow."""
    if config.AI_MODE != "ollama":
        return
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            await client.post(f"{config.OLLAMA_URL}/api/generate",
                              json={"model": config.OLLAMA_MODEL, "keep_alive": "60m"})
        log.info("Local model %s loaded", config.OLLAMA_MODEL)
    except Exception as e:
        log.warning("Couldn't load the local model (is the Ollama app running?): %s", e)


def shrink(photo: bytes, max_side: int = 448) -> bytes:
    """Local models are much faster on small images; gauges and labels stay readable."""
    try:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(photo)).convert("RGB")
        img.thumbnail((max_side, max_side))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=85)
        return out.getvalue()
    except Exception:
        return photo


async def _ollama(transcript: str, photo: bytes | None) -> dict:
    msg = {"role": "user", "content": PROMPT.format(transcript=transcript)}
    if photo:
        msg["images"] = [base64.b64encode(shrink(photo)).decode()]
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(f"{config.OLLAMA_URL}/api/chat", json={
            "model": config.OLLAMA_MODEL, "messages": [msg],
            "format": SCHEMA, "stream": False, "keep_alive": "60m",
            "options": {"num_predict": 300, "temperature": 0},  # caps runaway output
        })
        r.raise_for_status()
        return _parse_json(r.json()["message"]["content"])


async def _anthropic(transcript: str, photo: bytes | None, media_type: str) -> dict:
    import anthropic  # imported here so mock/ollama modes don't need a key

    content = []
    if photo:
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": media_type,
            "data": base64.standard_b64encode(photo).decode("utf-8")}})
    content.append({"type": "text", "text": PROMPT.format(transcript=transcript)})

    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    response = await client.beta.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=2000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": content}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined the request")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


async def structure(transcript: str, photo: bytes | None = None,
                    media_type: str = "image/jpeg", location_hint: str | None = None) -> tuple[dict, str]:
    """Returns (entry fields, how it was made: 'mock' | 'ollama' | 'anthropic' | 'mock-fallback')."""
    mode = config.AI_MODE
    if mode == "anthropic" and not config.ANTHROPIC_API_KEY:
        log.warning("AI_MODE=anthropic but ANTHROPIC_API_KEY is empty; using mock")
        mode = "mock"
    if mode not in ("ollama", "anthropic") or not transcript.strip():
        return mock_structure(transcript, location_hint), "mock"

    for attempt in (1, 2):  # validate and retry once on bad output
        try:
            if mode == "ollama":
                raw = await _ollama(transcript, photo)
            else:
                raw = await _anthropic(transcript, photo, media_type)
            entry = validate(raw)
            if entry:
                return entry, mode
            log.warning("AI output failed validation (attempt %d): %r", attempt, raw)
        except Exception as e:  # never let the AI break the demo
            log.warning("AI call failed (attempt %d): %s", attempt, e)
    return mock_structure(transcript, location_hint), "mock-fallback"


# ------------------------------------------------------ gauge / label reading

READ_SCHEMA = {
    "type": "object",
    "properties": {
        "reading": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["reading", "confidence"],
    "additionalProperties": False,
}

READ_PROMPT = """This photo shows a {label} (a gauge, display, meter, tag, or label).
Read what it shows. Reply with:
- reading: the key values in a few words, e.g. "72°F, model T6" or "Inspected 03/2026". Max 24 characters.
- confidence: high, medium, or low.
Hint from the inspector (may be empty): "{hint}"
If you can't read it, say "Unreadable" with low confidence. Do not guess numbers."""


def mock_read(hint: str) -> dict:
    """Free mode can't look at photos. Use numbers the inspector said, if any."""
    if hint and re.search(r"\d", hint):
        return {"reading": hint.strip()[:24], "confidence": "medium"}
    return {"reading": "Photo saved", "confidence": "low"}


async def read_photo(photo: bytes, media_type: str, label: str, hint: str = "") -> tuple[dict, str]:
    """Returns ({reading, confidence}, how it was made)."""
    mode = config.AI_MODE
    if mode == "anthropic" and not config.ANTHROPIC_API_KEY:
        mode = "mock"
    if mode not in ("ollama", "anthropic"):
        return mock_read(hint), "mock"
    prompt = READ_PROMPT.format(label=label, hint=hint)
    for attempt in (1, 2):
        try:
            if mode == "ollama":
                async with httpx.AsyncClient(timeout=120) as client:
                    r = await client.post(f"{config.OLLAMA_URL}/api/chat", json={
                        "model": config.OLLAMA_MODEL, "stream": False, "format": READ_SCHEMA, "keep_alive": "60m",
                        "options": {"num_predict": 60, "temperature": 0},
                        "messages": [{"role": "user", "content": prompt,
                                      "images": [base64.b64encode(shrink(photo)).decode()]}]})
                    r.raise_for_status()
                    raw = _parse_json(r.json()["message"]["content"])
            else:
                import anthropic
                client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
                response = await client.beta.messages.create(
                    model=config.ANTHROPIC_MODEL, max_tokens=1000,
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                    output_config={"effort": "low", "format": {"type": "json_schema", "schema": READ_SCHEMA}},
                    messages=[{"role": "user", "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                                     "data": base64.standard_b64encode(photo).decode()}},
                        {"type": "text", "text": prompt}]}])
                if response.stop_reason == "refusal":
                    raise RuntimeError("Claude declined the request")
                raw = json.loads(next(b.text for b in response.content if b.type == "text"))
            if isinstance(raw, dict) and isinstance(raw.get("reading"), str) and raw["reading"].strip():
                conf = raw.get("confidence") if raw.get("confidence") in ("high", "medium", "low") else "low"
                return {"reading": raw["reading"].strip()[:40], "confidence": conf}, mode
        except Exception as e:
            log.warning("Reading failed (attempt %d): %s", attempt, e)
    return mock_read(hint), "mock-fallback"


# ------------------------------------------------- photo-only: pass or flag?

ASSESS_SCHEMA = {
    "type": "object",
    "properties": {
        "seen": {"type": "string"},
        "problem": {"type": "boolean"},
        "issue": {"type": "string"},
    },
    "required": ["seen", "problem", "issue"],
    "additionalProperties": False,
}

ASSESS_PROMPT = """You are a home inspector checking one item during a move-out inspection.
Item: {label} ({area}). What to check: {instruction}.
First describe the condition of the surface in the photo in one sentence (seen).
Then decide: is there any stain, discolouration, crack, hole, leak, mould, scuff, or broken or missing part? (problem)
A clean, even surface with no marks is not a problem.
- issue: if there is a problem, 2-4 words naming it, e.g. "Water stain"; otherwise ""."""


PROBLEM_WORDS = [  # (pattern, issue name) in priority order
    (r"water (stain|damage|mark)", "Water stain"), (r"mou?ld", "Mould"), (r"leak", "Leak"),
    (r"crack", "Crack"), (r"hole", "Hole"), (r"stain", "Stain"), (r"discolou?r", "Discolouration"),
    (r"peel", "Peeling paint"), (r"scuff", "Scuff mark"), (r"scratch", "Scratch"), (r"dent", "Dent"),
    (r"broken|missing|loose", "Broken or missing part"), (r"rust", "Rust"), (r"damage", "Damage"),
    (r"\b(mark|spot)s?\b", "Marks"),
]


def _problem_in(text: str) -> str | None:
    """'There is a brown water stain near the light' -> 'Water stain'. Ignores 'no stains', 'without cracks'."""
    low = text.lower()
    for pattern, name in PROBLEM_WORDS:
        for m in re.finditer(pattern, low):
            before = re.split(r"[.;!?]|\bbut\b|\bhowever\b", low[:m.start()])[-1]  # this sentence, after any "but"
            if re.search(r"\b(no|not|without|free of|free from|any|none)\b", before):
                continue
            return name
    return None


async def assess_photo(photo: bytes, media_type: str, label: str, area: str,
                       instruction: str) -> tuple[dict | None, str]:
    """Photo only, no voice: does this item look OK? Returns ({problem, issue}, made_by),
    or (None, reason) when no vision AI is available (free mock mode can't see photos)."""
    mode = config.AI_MODE
    if mode == "anthropic" and not config.ANTHROPIC_API_KEY:
        mode = "mock"
    if mode not in ("ollama", "anthropic"):
        return None, "mock"
    prompt = ASSESS_PROMPT.format(label=label, area=area, instruction=instruction)
    for attempt in (1, 2):
        try:
            if mode == "ollama":
                # Small local model: describe in plain words, then decide with simple rules.
                async with httpx.AsyncClient(timeout=60) as client:
                    r = await client.post(f"{config.OLLAMA_URL}/api/chat", json={
                        "model": config.OLLAMA_MODEL, "stream": False, "keep_alive": "60m",
                        "options": {"num_predict": 80, "temperature": 0},
                        "messages": [{"role": "user", "images": [base64.b64encode(shrink(photo, 512)).decode()],
                                      "content": f"This photo shows the {label.lower()} ({area}) in an apartment. "
                                                 "Describe its condition in one sentence. Mention any stains, marks, "
                                                 "cracks, holes, mould, leaks, scuffs or damage you can see."}]})
                    r.raise_for_status()
                    seen = r.json()["message"]["content"].strip()
                issue = _problem_in(seen)
                log.info("Photo check (%s): %s -> %s", label, seen[:120], issue or "no problem")
                return {"problem": bool(issue), "issue": issue or "", "seen": seen}, mode
            else:
                import anthropic
                client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
                response = await client.beta.messages.create(
                    model=config.ANTHROPIC_MODEL, max_tokens=500,
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                    output_config={"effort": "low", "format": {"type": "json_schema", "schema": ASSESS_SCHEMA}},
                    messages=[{"role": "user", "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                                     "data": base64.standard_b64encode(photo).decode()}},
                        {"type": "text", "text": prompt}]}])
                if response.stop_reason == "refusal":
                    raise RuntimeError("Claude declined the request")
                raw = json.loads(next(b.text for b in response.content if b.type == "text"))
            if isinstance(raw, dict) and isinstance(raw.get("problem"), bool):
                issue = str(raw.get("issue") or "").strip()[:40]
                if raw["problem"] and not issue:
                    issue = f"Problem with {label.lower()}"
                return {"problem": raw["problem"], "issue": issue}, mode
        except Exception as e:
            log.warning("Photo check failed (attempt %d): %s", attempt, e)
    return None, "failed"
