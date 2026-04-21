# Created: 23:55 21-Apr-2026
"""Generate the project's icons in one shot.

Outputs:
  assets/logo.png               — 512×512 full-colour logo for the README
  assets/menubar_template.png   — 22×22 black-on-transparent menu-bar icon (1x)
  assets/menubar_template@2x.png — 44×44 retina variant
  assets/icon.iconset/…         — macOS iconset source folder
  assets/AppIcon.icns           — packed macOS icon (needs iconutil)

Design: a rounded-square badge with a stylised stopwatch/archive motif
— a clock face with a backwards-curling arrow around it (history).
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent


def _draw_colour_logo(size: int) -> Image.Image:
    """Return a full-colour app-icon logo at the given size."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Rounded-square badge (macOS icon grid: ~82 % content).
    pad = int(size * 0.09)
    radius = int(size * 0.22)
    # Gradient-free solid fill with a secondary dark overlay for depth.
    d.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=radius,
        fill=(31, 64, 104, 255),        # deep blue
    )
    # Inner highlight rectangle for a subtle top-light sheen.
    highlight = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    hd = ImageDraw.Draw(highlight)
    hd.rounded_rectangle(
        [pad, pad, size - pad, pad + int((size - 2 * pad) * 0.45)],
        radius=radius,
        fill=(94, 179, 255, 55),        # accent blue, translucent
    )
    img.alpha_composite(highlight)

    # Clock face.
    cx = cy = size // 2
    face_r = int(size * 0.32)
    d.ellipse(
        [cx - face_r, cy - face_r, cx + face_r, cy + face_r],
        fill=(232, 232, 232, 255),
        outline=(232, 232, 232, 255),
        width=max(1, size // 128),
    )
    # Inner darker ring — reads as a bezel.
    inner_r = int(face_r * 0.86)
    d.ellipse(
        [cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r],
        fill=(245, 245, 245, 255),
    )
    # Clock hands pointing to ~10:10 (classic watch advertising pose).
    hand_thick = max(2, size // 64)
    # Hour hand: angle measured clockwise from 12 o'clock.
    for angle_deg, length_frac, thick in (
        (-60, 0.52, hand_thick + size // 160),   # hour hand, short thick
        (60,  0.70, hand_thick),                  # minute hand, long thin
    ):
        a = math.radians(angle_deg - 90)  # -90 so 0° points right
        tx = cx + int(math.cos(a) * inner_r * length_frac)
        ty = cy + int(math.sin(a) * inner_r * length_frac)
        d.line([(cx, cy), (tx, ty)], fill=(31, 64, 104, 255), width=thick)
    # Centre pivot.
    pin_r = max(2, size // 70)
    d.ellipse(
        [cx - pin_r, cy - pin_r, cx + pin_r, cy + pin_r],
        fill=(31, 64, 104, 255),
    )

    # "History" curl — an arc with an arrowhead sweeping counter-clockwise
    # around the clock face, suggesting going back in time.
    arc_r = int(face_r * 1.22)
    arc_box = [cx - arc_r, cy - arc_r, cx + arc_r, cy + arc_r]
    d.arc(arc_box, start=200, end=340, fill=(94, 179, 255, 255),
          width=max(2, size // 50))
    # Arrowhead at the end of the arc (angle 340°).
    head_a = math.radians(340)
    hx = cx + int(math.cos(head_a) * arc_r)
    hy = cy + int(math.sin(head_a) * arc_r)
    head_size = size // 18
    # A simple filled triangle, tangent to the arc.
    tangent = head_a + math.pi / 2
    def _pt(a, d_):
        return (hx + int(math.cos(a) * d_), hy + int(math.sin(a) * d_))
    p1 = _pt(tangent,              head_size)
    p2 = _pt(tangent + math.pi,    head_size)
    p3 = _pt(head_a,               head_size)
    d.polygon([p1, p2, p3], fill=(94, 179, 255, 255))

    return img


def _draw_template(size: int) -> Image.Image:
    """Menu-bar template: black-on-transparent so macOS can invert for
    dark mode automatically. Same motif, simplified."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = size // 2
    r = int(size * 0.38)
    stroke = max(1, size // 12)

    # Clock face outline.
    d.ellipse([cx - r, cy - r, cx + r, cy + r],
              outline=(0, 0, 0, 255), width=stroke)
    # Hands: 10:10.
    for ang, frac, th in ((-60, 0.62, stroke), (60, 0.78, stroke)):
        a = math.radians(ang - 90)
        tx = cx + int(math.cos(a) * r * frac)
        ty = cy + int(math.sin(a) * r * frac)
        d.line([(cx, cy), (tx, ty)], fill=(0, 0, 0, 255), width=th)

    # History sweep arc + arrowhead (simpler form at this size).
    arc_r = int(r * 1.25)
    d.arc([cx - arc_r, cy - arc_r, cx + arc_r, cy + arc_r],
          start=205, end=335, fill=(0, 0, 0, 255), width=stroke)
    head_a = math.radians(335)
    hx = cx + int(math.cos(head_a) * arc_r)
    hy = cy + int(math.sin(head_a) * arc_r)
    head_size = max(2, size // 6)
    tangent = head_a + math.pi / 2
    p1 = (hx + int(math.cos(tangent) * head_size), hy + int(math.sin(tangent) * head_size))
    p2 = (hx + int(math.cos(tangent + math.pi) * head_size),
          hy + int(math.sin(tangent + math.pi) * head_size))
    p3 = (hx + int(math.cos(head_a) * head_size), hy + int(math.sin(head_a) * head_size))
    d.polygon([p1, p2, p3], fill=(0, 0, 0, 255))

    return img


def main() -> None:
    # ---- README-facing colour logo ----
    logo = _draw_colour_logo(512)
    (HERE / "logo.png").parent.mkdir(parents=True, exist_ok=True)
    logo.save(HERE / "logo.png")

    # ---- Menu-bar template icons (1x and 2x) ----
    _draw_template(22).save(HERE / "menubar_template.png")
    _draw_template(44).save(HERE / "menubar_template@2x.png")

    # ---- macOS iconset for .icns ----
    # Sizes Apple expects in Contents/Resources/AppIcon.iconset/
    iconset = HERE / "AppIcon.iconset"
    iconset.mkdir(exist_ok=True)
    sizes = [
        ("icon_16x16.png",      16),
        ("icon_16x16@2x.png",   32),
        ("icon_32x32.png",      32),
        ("icon_32x32@2x.png",   64),
        ("icon_128x128.png",    128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png",    256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png",    512),
        ("icon_512x512@2x.png", 1024),
    ]
    for fname, px in sizes:
        _draw_colour_logo(px).save(iconset / fname)

    # Pack into .icns (native macOS tool; fails gracefully if unavailable).
    icns = HERE / "AppIcon.icns"
    try:
        subprocess.run(
            ["iconutil", "--convert", "icns", str(iconset),
             "--output", str(icns)],
            check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print(f"wrote {icns}")
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        print(f"iconutil unavailable ({e}); skipping .icns (PNG fallback works)")

    for f in (HERE / "logo.png", HERE / "menubar_template.png",
              HERE / "menubar_template@2x.png"):
        print(f"wrote {f}")


if __name__ == "__main__":
    main()
