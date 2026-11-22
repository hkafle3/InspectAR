"""Makes placeholder move-in photos (baselines/photos/) and the move-out scuff photo (samples/scuff.jpg).
Replace them with real photos of the demo room any time (same file names).

  python scripts/make_movein.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
MOVEIN = ROOT / "baselines" / "photos"
MOVEIN.mkdir(parents=True, exist_ok=True)


def font(size):
    try:
        return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
    except OSError:
        return ImageFont.load_default()


def ceiling(stain: bool):
    img = Image.new("RGB", (800, 600), (236, 233, 226))
    d = ImageDraw.Draw(img)
    if stain:
        for r, c in [(170, (214, 196, 160)), (130, (196, 170, 125)), (95, (176, 146, 100))]:
            d.ellipse((300 - r, 300 - r * 0.8, 300 + r, 300 + r * 0.8), fill=c)
    d.ellipse((520, 230, 620, 330), fill=(250, 250, 245), outline=(200, 200, 195), width=4)
    d.ellipse((550, 260, 590, 300), fill=(255, 250, 220))
    return img, d


def wall_with_scuff(bigger: bool):
    img = Image.new("RGB", (800, 600), (214, 220, 226))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 520, 800, 600), fill=(150, 112, 80))  # floor
    d.rounded_rectangle((470, 200, 550, 320), radius=8, fill=(248, 248, 246), outline=(180, 180, 180), width=3)
    d.rounded_rectangle((498, 235, 522, 285), radius=4, fill=(235, 235, 232), outline=(170, 170, 170), width=2)
    w = 90 if bigger else 60
    for k in range(5):
        d.line((380 - w + k * 6, 300 + k * 7, 440 + k * 4, 290 + k * 6), fill=(120, 120, 125), width=3)
    return img, d


img, d = ceiling(stain=False)
d.text((30, 30), "MOVE-IN · DEC 1, 2025", fill=(120, 120, 120), font=font(28))
img.save(MOVEIN / "movein_ceiling.jpg", quality=85)

img, d = wall_with_scuff(bigger=False)
d.text((30, 30), "MOVE-IN · DEC 1, 2025", fill=(110, 110, 110), font=font(28))
img.save(MOVEIN / "movein_walls.jpg", quality=85)

img, d = wall_with_scuff(bigger=False)
img.save(ROOT / "samples" / "scuff.jpg", quality=85)
print("wrote baselines/photos/movein_ceiling.jpg, baselines/photos/movein_walls.jpg, samples/scuff.jpg")
