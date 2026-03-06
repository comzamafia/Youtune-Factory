"""Thumbnail Generator — Creates YouTube thumbnails with AI image + text overlay."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.ai.image_generator import get_image_generator
from app.config import settings

logger = logging.getLogger(__name__)

# Thumbnail dimensions (YouTube recommended)
THUMB_WIDTH = 1280
THUMB_HEIGHT = 720


async def generate_thumbnail(
    title: str,
    image_prompt: str,
    output_path: Path,
    font_path: Path | None = None,
    font_size: int = 72,
) -> Path:
    """
    Generate a YouTube thumbnail:
    1. Create a background image via AI image generator.
    2. Overlay the *title* text with a semi-transparent bar.

    Returns the path to the saved thumbnail JPEG.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Step 1 — Generate hero image
    bg_path = output_path.with_suffix(".bg.png")
    image_gen = get_image_generator()
    await image_gen.generate(
        prompt=f"{image_prompt}, cinematic lighting, dramatic composition, 4k, highly detailed",
        output_path=bg_path,
    )

    # Step 2 — Open and resize to exact thumbnail dims
    img = Image.open(bg_path).convert("RGBA")
    img = img.resize((THUMB_WIDTH, THUMB_HEIGHT), Image.LANCZOS)

    # Step 3 — Draw semi-transparent overlay bar at the bottom
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    bar_height = 160
    draw.rectangle(
        [(0, THUMB_HEIGHT - bar_height), (THUMB_WIDTH, THUMB_HEIGHT)],
        fill=(0, 0, 0, 180),
    )
    img = Image.alpha_composite(img, overlay)

    # Step 4 — Render title text
    draw = ImageDraw.Draw(img)

    # Try to load a custom font
    if font_path and font_path.exists():
        font = ImageFont.truetype(str(font_path), font_size)
    else:
        # Search in assets/fonts/
        fonts_dir = settings.fonts_dir
        ttf_files = list(fonts_dir.glob("*.ttf")) + list(fonts_dir.glob("*.otf"))
        if ttf_files:
            font = ImageFont.truetype(str(ttf_files[0]), font_size)
        else:
            # Fallback to system fonts for Thai support
            import sys
            try:
                if sys.platform == "win32":
                    font = ImageFont.truetype("tahoma.ttf", font_size)
                elif sys.platform == "darwin":
                    font = ImageFont.truetype("Thonburi.ttc", font_size)
                else:
                    font = ImageFont.truetype("Sarabun-Regular.ttf", font_size)
            except Exception:
                font = ImageFont.load_default()
                logger.warning("No custom font found — using default bitmap font.")

    # Center text in the bar
    display_title = title.upper()
    bbox = draw.textbbox((0, 0), display_title, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (THUMB_WIDTH - text_w) // 2
    y = THUMB_HEIGHT - bar_height + (bar_height - text_h) // 2

    # Draw text shadow + text
    draw.text((x + 3, y + 3), display_title, font=font, fill=(0, 0, 0, 200))
    draw.text((x, y), display_title, font=font, fill=(255, 255, 255, 255))

    # Step 5 — Save as JPEG
    img_rgb = img.convert("RGB")
    img_rgb.save(output_path, "JPEG", quality=95)

    # Cleanup temp bg
    if bg_path.exists():
        bg_path.unlink()

    logger.info("Thumbnail → %s", output_path.name)
    return output_path
