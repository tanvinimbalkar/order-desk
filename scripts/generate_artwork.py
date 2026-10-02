"""Draw one simple pouch PNG for each artwork version.

Run from the project root: python scripts/generate_artwork.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.artwork import ART_DIR, load_projects  # noqa: E402

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install Pillow to generate artwork images.") from exc


def _font(size: int):
    for path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial.ttf",
    ):
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _logo(draw: ImageDraw.ImageDraw, kind: str, box: tuple[int, int, int, int]) -> None:
    if kind == "triangle":
        left, top, right, bottom = box
        mid = (left + right) // 2
        draw.polygon([(mid, top), (right, bottom), (left, bottom)], fill="#1F5F5B")
        return
    if kind == "square":
        draw.rounded_rectangle(box, radius=8, fill="#C8742B")
        return
    draw.ellipse(box, fill="#1F5F5B")


def draw_version(brand: str, visual: dict, destination: Path) -> None:
    image = Image.new("RGB", (360, 480), "#F7F4EE")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((64, 96, 296, 430), radius=36, fill="#FFFFFF", outline="#1F5F5B", width=4)
    draw.polygon([(64, 128), (180, 58), (296, 128)], fill="#E7F0EF", outline="#1F5F5B")
    scale = float(visual.get("logo_scale") or 0.4)
    logo_size = int(56 + 110 * scale)
    left = 180 - logo_size // 2
    top = 142
    _logo(draw, str(visual.get("logo") or "circle"), (left, top, left + logo_size, top + logo_size))
    title = _font(18)
    small = _font(14)
    title_y = min(top + logo_size + 14, 320)
    draw.text((80, title_y), brand, fill="#1E2A2A", font=title)
    y = title_y + 26
    for line in visual.get("extra_lines") or []:
        draw.text((80, y), str(line), fill="#1E2A2A", font=small)
        y += 22
    finish = str(visual.get("finish_label") or "")
    if finish:
        draw.text((80, 360), finish, fill="#1F5F5B", font=small)
    date_label = str(visual.get("date_label") or "")
    if date_label:
        draw.rounded_rectangle((80, 390, 250, 418), radius=6, outline="#1E2A2A")
        draw.text((90, 396), date_label, fill="#1E2A2A", font=small)
    if visual.get("approved_stamp"):
        draw.text((200, 150), "OK", fill="#1F5F5B", font=title)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="PNG")


def main() -> int:
    count = 0
    for project in load_projects():
        for version in project["versions"]:
            draw_version(project["brand"], version.get("visual") or {}, ART_DIR / version["file"])
            count += 1
    print(f"Wrote {count} artwork files to data/artwork/images/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
