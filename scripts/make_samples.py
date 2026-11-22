"""Makes placeholder sample photos in samples/. Replace them with real photos any time
(same file names), e.g. pictures of real stains or cracks taken with your phone."""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
COLORS = [(120, 100, 80), (90, 90, 110), (110, 110, 100), (100, 80, 70), (70, 80, 90)]

for i, s in enumerate(json.loads((SAMPLES / "notes.json").read_text())):
    img = Image.new("RGB", (800, 600), COLORS[i % len(COLORS)])
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 40)
    except OSError:
        font = ImageFont.load_default()
    d.text((40, 40), "SAMPLE PHOTO", fill=(255, 255, 255), font=font)
    d.text((40, 110), s["note"][:34], fill=(230, 230, 230), font=font)
    d.text((40, 160), s["note"][34:68], fill=(230, 230, 230), font=font)
    img.save(SAMPLES / s["photo"], quality=80)
    print("wrote", s["photo"])


# ---- Demo props for the PropertyLens checklist (scripts/demo_run.py) ----

def font(size):
    try:
        return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
    except OSError:
        return ImageFont.load_default()


# A ceiling with a brown water stain near a light fixture.
img = Image.new("RGB", (800, 600), (236, 233, 226))
d = ImageDraw.Draw(img)
for r, c in [(170, (214, 196, 160)), (130, (196, 170, 125)), (95, (176, 146, 100)), (60, (160, 128, 85))]:
    d.ellipse((300 - r, 300 - r * 0.8, 300 + r, 300 + r * 0.8), fill=c)
d.ellipse((520, 230, 620, 330), fill=(250, 250, 245), outline=(200, 200, 195), width=4)
d.ellipse((550, 260, 590, 300), fill=(255, 250, 220))
img.save(SAMPLES / "water_stain.jpg", quality=85)
print("wrote water_stain.jpg (ceiling stain)")

# A wall thermostat showing 72°F, model T6.
img = Image.new("RGB", (800, 600), (225, 222, 215))
d = ImageDraw.Draw(img)
d.rounded_rectangle((220, 110, 580, 490), radius=40, fill=(245, 245, 245), outline=(170, 170, 170), width=4)
d.rounded_rectangle((270, 170, 530, 360), radius=16, fill=(30, 40, 45))
d.text((300, 190), "72°F", fill=(120, 230, 255), font=font(110))
d.text((300, 320), "HEAT  SET 70", fill=(160, 200, 210), font=font(26))
d.text((355, 400), "Honeywell T6", fill=(90, 90, 90), font=font(28))
img.save(SAMPLES / "thermostat.jpg", quality=85)
print("wrote thermostat.jpg")
