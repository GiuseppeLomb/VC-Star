"""Replace Capacitor's default launcher icons and splash with the Vice City Star artwork.

Usage (from the repo root, after `npx cap add android`):
    python scripts/android_icons.py android
"""
import shutil
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from brand_assets import cover, fit_width, square_art, vertical_art, wide_art  # noqa: E402

LAUNCHER = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}


def main(android_dir: str) -> None:
    res = Path(android_dir) / "app" / "src" / "main" / "res"
    icon = square_art()
    # Use the classic PNG icons everywhere (drop Capacitor's adaptive XML icon).
    shutil.rmtree(res / "mipmap-anydpi-v26", ignore_errors=True)
    for density, size in LAUNCHER.items():
        folder = res / f"mipmap-{density}"
        folder.mkdir(parents=True, exist_ok=True)
        img = icon.resize((size, size), Image.LANCZOS)
        for name in ("ic_launcher.png", "ic_launcher_round.png", "ic_launcher_foreground.png"):
            img.save(folder / name)

    portrait, landscape = vertical_art(), wide_art()
    count = 0
    for splash in res.glob("drawable*/splash.png"):
        w, h = Image.open(splash).size
        art = fit_width(portrait, (w, h)) if h > w else cover(landscape, (w, h))
        art.save(splash)
        count += 1
    print(f"launcher icons: {len(LAUNCHER)} densities, splash images: {count}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "android")
