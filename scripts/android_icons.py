"""Replace Capacitor's default launcher icons and splash with the Radar icon.

Usage (from the repo root, after `npx cap add android`):
    python scripts/android_icons.py android docs/icons/icon-512.png
"""
import shutil
import sys
from pathlib import Path

from PIL import Image

LAUNCHER = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
BACKGROUND = (7, 2, 15, 255)


def main(android_dir: str, icon_path: str) -> None:
    res = Path(android_dir) / "app" / "src" / "main" / "res"
    icon = Image.open(icon_path).convert("RGBA")
    # Use the classic PNG icons everywhere (drop Capacitor's adaptive XML icon).
    shutil.rmtree(res / "mipmap-anydpi-v26", ignore_errors=True)
    for density, size in LAUNCHER.items():
        folder = res / f"mipmap-{density}"
        folder.mkdir(parents=True, exist_ok=True)
        img = icon.resize((size, size), Image.LANCZOS)
        for name in ("ic_launcher.png", "ic_launcher_round.png", "ic_launcher_foreground.png"):
            img.save(folder / name)
    count = 0
    for splash in res.glob("drawable*/splash.png"):
        w, h = Image.open(splash).size
        canvas = Image.new("RGBA", (w, h), BACKGROUND)
        side = max(48, int(min(w, h) * 0.32))
        logo = icon.resize((side, side), Image.LANCZOS)
        canvas.alpha_composite(logo, ((w - side) // 2, (h - side) // 2))
        canvas.convert("RGB").save(splash)
        count += 1
    print(f"launcher icons: {len(LAUNCHER)} densities, splash images: {count}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
