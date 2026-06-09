"""Dynamic Open-Graph image rendering via Pillow."""
from __future__ import annotations

import re
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

TEMPLATES = ["default", "dark", "gradient", "minimal"]

# Template palette definitions: (bg_hex, fg_hex)
_PALETTES = {
    "default": ("#4f46e5", "#ffffff"),      # indigo bg, white text
    "dark": ("#0f0f0f", "#ffffff"),         # near-black bg, white text
    "gradient": ("#4f46e5", "#ffffff"),     # gradient indigo→violet, white text
    "minimal": ("#ffffff", "#0f0f0f"),      # white bg, near-black text
}


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Try to load a TrueType font, fall back to default."""
    font_paths = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]

    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except (FileNotFoundError, OSError):
            continue

    return ImageFont.load_default()


def _is_valid_hex_color(color: str | None) -> bool:
    """Validate hex color format #RRGGBB."""
    if not color:
        return False
    return bool(re.match(r"^#[0-9a-fA-F]{6}$", color))


def _apply_gradient(img: Image.Image, color1: str, color2: str) -> None:
    """Apply a vertical gradient from color1 to color2.

    Each row of a vertical gradient is a uniform color, so we draw one horizontal
    line per row (height iterations) instead of touching every pixel (width*height).
    """
    width, height = img.size
    draw = ImageDraw.Draw(img)

    def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore

    rgb1 = hex_to_rgb(color1)
    rgb2 = hex_to_rgb(color2)

    for y in range(height):
        ratio = y / height
        r = int(rgb1[0] * (1 - ratio) + rgb2[0] * ratio)
        g = int(rgb1[1] * (1 - ratio) + rgb2[1] * ratio)
        b = int(rgb1[2] * (1 - ratio) + rgb2[2] * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
               max_width: int, spacing: int = 5) -> list[str]:
    """Wrap text to fit within max_width, return list of lines."""
    lines = []
    current_line = ""

    for word in text.split():
        test_line = f"{current_line} {word}".strip()
        bbox = draw.textbbox((0, 0), test_line, font=font)
        line_width = bbox[2] - bbox[0]

        if line_width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines


def render_og_image(title: str, subtitle: str = "", template: str = "default",
                    bg: str | None = None, fg: str | None = None,
                    watermark: bool = True) -> bytes:
    """Render a 1200x630 Open-Graph image with title and subtitle.

    Args:
        title: Main heading text
        subtitle: Secondary text
        template: One of TEMPLATES (default to "default" if invalid)
        bg: Hex color override for background (#RRGGBB), ignored if invalid
        fg: Hex color override for foreground text (#RRGGBB), ignored if invalid
        watermark: If True, add "ogforge.dev" watermark

    Returns:
        PNG bytes
    """
    # Validate template, fallback to "default"
    if template not in TEMPLATES:
        template = "default"

    # Get palette colors
    palette_bg, palette_fg = _PALETTES[template]

    # Apply hex color overrides if valid
    bg_color = bg if _is_valid_hex_color(bg) else palette_bg
    fg_color = fg if _is_valid_hex_color(fg) else palette_fg

    # Create canvas
    img = Image.new("RGB", (1200, 630), color=bg_color)

    # Apply gradient for gradient template
    if template == "gradient":
        _apply_gradient(img, palette_bg, "#7c3aed")  # indigo to violet
    else:
        # Just fill with bg_color (already done in Image.new)
        pass

    draw = ImageDraw.Draw(img)

    # Load fonts
    title_font = _load_font(72)
    subtitle_font = _load_font(36)
    watermark_font = _load_font(20)

    # Wrap and render title
    padding = 60
    max_text_width = 1200 - 2 * padding

    title_lines = _wrap_text(draw, title, title_font, max_text_width)

    # Calculate total height for title
    title_height = 0
    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        title_height += bbox[3] - bbox[1]

    # Draw title centered
    y = 80
    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        line_height = bbox[3] - bbox[1]
        x = (1200 - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), line, fill=fg_color, font=title_font)
        y += line_height + 10

    # Draw subtitle if provided
    if subtitle:
        subtitle_lines = _wrap_text(draw, subtitle, subtitle_font, max_text_width)
        for line in subtitle_lines:
            bbox = draw.textbbox((0, 0), line, font=subtitle_font)
            line_height = bbox[3] - bbox[1]
            # Dim subtitle by using slightly transparent effect (reduce saturation in RGB)
            # Create a muted version of fg_color
            if fg_color == "#ffffff":
                dim_color = "#999999"
            else:
                dim_color = "#666666"
            x = (1200 - (bbox[2] - bbox[0])) // 2
            draw.text((x, y), line, fill=dim_color, font=subtitle_font)
            y += line_height + 5

    # Draw watermark if enabled
    if watermark:
        watermark_text = "snapcard.dev"
        bbox = draw.textbbox((0, 0), watermark_text, font=watermark_font)
        wm_width = bbox[2] - bbox[0]
        wm_height = bbox[3] - bbox[1]
        wm_x = 1200 - wm_width - 20
        wm_y = 630 - wm_height - 15
        # Dim watermark
        watermark_color = "#666666" if fg_color == "#ffffff" else "#cccccc"
        draw.text((wm_x, wm_y), watermark_text, fill=watermark_color, font=watermark_font)

    # Encode to PNG bytes
    output = BytesIO()
    img.save(output, format="PNG")
    return output.getvalue()
