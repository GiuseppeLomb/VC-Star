"""Generate the app icons, header logo and About banner from the Vice City Star artwork in /brand.

    python scripts/brand_assets.py

The crops keep the image-generator mark (bottom-right corner) out of the frame.
Re-run after replacing any file in /brand.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
BRAND = ROOT / "brand"
ICONS = ROOT / "docs" / "icons"

# (left, top, right, bottom) in the original pixels
SQUARE_CROP = (40, 0, 1010, 876)      # vc-star-square.jpg: emblem + "VICE CITY STAR"
EMBLEM_CROP = (90, 170, 1000, 730)    # vc-star-square.jpg: "VC" + star only
WIDE_CROP = (180, 20, 1220, 652)      # vc-star-wide.jpg
VERTICAL_CROP = (0, 0, 768, 1220)     # vc-star-vertical.jpg


def square_art() -> Image.Image:
    """Square icon art: crop, then extend the dark ground at the bottom to make it square."""
    src = Image.open(BRAND / "vc-star-square.jpg").convert("RGB")
    art = src.crop(SQUARE_CROP)
    w, h = art.size
    extra = w - h
    strip = art.crop((0, h - 12, w, h)).resize((w, extra + 24), Image.BILINEAR).filter(ImageFilter.GaussianBlur(18))
    out = Image.new("RGB", (w, w))
    out.paste(strip.crop((0, 12, w, 12 + extra)), (0, h))
    out.paste(art, (0, 0))
    # soften the seam
    seam = out.crop((0, h - 10, w, h + 10)).filter(ImageFilter.GaussianBlur(4))
    out.paste(seam, (0, h - 10))
    return out


def rounded(img: Image.Image, radius_ratio: float = 0.22) -> Image.Image:
    img = img.convert("RGBA")
    mask = Image.new("L", img.size, 0)
    r = int(min(img.size) * radius_ratio)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=r, fill=255)
    img.putalpha(mask)
    return img


def cover(img: Image.Image, size: tuple[int, int], anchor_y: float = 0.5) -> Image.Image:
    """Resize + crop to fill `size` (like CSS object-fit: cover)."""
    tw, th = size
    scale = max(tw / img.width, th / img.height)
    resized = img.resize((max(tw, round(img.width * scale)), max(th, round(img.height * scale))), Image.LANCZOS)
    left = (resized.width - tw) // 2
    top = int((resized.height - th) * anchor_y)
    return resized.crop((left, top, left + tw, top + th))


def fit_width(img: Image.Image, size: tuple[int, int], anchor_y: float = 0.3) -> Image.Image:
    """Keep the full width (nothing cut at the sides). Missing height is filled by
    stretching and blurring the top rows (plain sky); extra height is cropped."""
    tw, th = size
    scaled = img.resize((tw, round(img.height * tw / img.width)), Image.LANCZOS)
    if scaled.height >= th:
        top = int((scaled.height - th) * anchor_y)
        return scaled.crop((0, top, tw, top + th))
    extra = th - scaled.height
    # plain sky colour = average of the top-left rows (avoids the palm leaves on the right)
    sample = scaled.crop((0, 0, tw * 2 // 3, 6)).resize((1, 1), Image.BOX).getpixel((0, 0))
    out = Image.new("RGB", (tw, th), sample)
    out.paste(scaled, (0, extra))
    # fade the artwork's top edge into the sky colour
    fade = min(60, scaled.height // 6)
    band = out.crop((0, extra, tw, extra + fade))
    solid = Image.new("RGB", band.size, sample)
    mask = Image.linear_gradient("L").resize(band.size)  # 0 (top) -> 255 (bottom)
    out.paste(Image.composite(band, solid, mask), (0, extra))
    return out


def vertical_art() -> Image.Image:
    return Image.open(BRAND / "vc-star-vertical.jpg").convert("RGB").crop(VERTICAL_CROP)


def wide_art() -> Image.Image:
    return Image.open(BRAND / "vc-star-wide.jpg").convert("RGB").crop(WIDE_CROP)


def main() -> None:
    ICONS.mkdir(parents=True, exist_ok=True)
    art = square_art()

    # Full-bleed square icons (launchers/OS apply their own mask).
    for name, size in (("icon-512.png", 512), ("icon-192.png", 192), ("apple-touch-icon.png", 180)):
        art.resize((size, size), Image.LANCZOS).save(ICONS / name, optimize=True)
    rounded(art.resize((48, 48), Image.LANCZOS)).save(ICONS / "favicon-48.png", optimize=True)

    # Maskable: artwork inside the 80% safe zone, blurred copy as full-bleed background.
    bg = art.resize((512, 512), Image.LANCZOS).filter(ImageFilter.GaussianBlur(28))
    inner = rounded(art.resize((420, 420), Image.LANCZOS), 0.12)
    bg = bg.convert("RGBA")
    bg.alpha_composite(inner, (46, 46))
    bg.convert("RGB").save(ICONS / "icon-maskable-512.png", optimize=True)

    # Header logo (2x for sharp rendering at 36 px tall).
    emblem = Image.open(BRAND / "vc-star-square.jpg").convert("RGB").crop(EMBLEM_CROP)
    h = 72
    emblem = emblem.resize((round(emblem.width * h / emblem.height), h), Image.LANCZOS)
    rounded(emblem, 0.18).save(ICONS / "logo-emblem.png", optimize=True)

    # About banner.
    banner = wide_art()
    banner = banner.resize((960, round(banner.height * 960 / banner.width)), Image.LANCZOS)
    banner.save(ICONS / "banner-wide.jpg", quality=80, optimize=True, progressive=True)

    for f in sorted(ICONS.iterdir()):
        print(f"{f.name:<24} {f.stat().st_size // 1024:>5} KB")


if __name__ == "__main__":
    main()
