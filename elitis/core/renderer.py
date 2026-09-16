"""
Pure Pillow rendering — no Qt imports.

render_thumbnail() is the single entry point used by both:
  - the GUI preview worker (called in a background thread)
  - the CLI/batch export pipeline

All drawing logic lives here so there is no duplication between preview and export.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional
import textwrap
import io

from PIL import Image, ImageDraw, ImageFilter

from elitis.core.models import ResolvedSettings, ThumbnailItem, Project
from elitis.core.font_manager import FontManager


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_thumbnail(
    item: ThumbnailItem,
    project: Project,
    font_manager: FontManager,
    preview_size: Optional[tuple[int, int]] = None,
) -> Image.Image:
    """
    Render one thumbnail and return a Pillow Image.

    preview_size: if given, the output is scaled to fit within this box while
    maintaining aspect ratio (for live preview — faster than full-res).
    """
    cfg = project.resolve_item(item)
    bg = _load_background(item, project, cfg)
    bg = _apply_framing(bg, cfg)
    bg = _composite_box(bg, cfg)
    if item.label:
        bg = _draw_text(bg, item.label, cfg, font_manager)
    if preview_size:
        bg = _fit_to_preview(bg, preview_size)
    return bg


def render_all(
    project: Project,
    font_manager: FontManager,
    output_dir: Path,
    fmt: str = "PNG",
    on_progress=None,
) -> list[Path]:
    """Batch render all content items to output_dir. Returns list of written paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    items = project.content_items
    for i, item in enumerate(items):
        img = render_thumbnail(item, project, font_manager)
        safe = _safe_filename(item.label or item.id)
        ext = "jpg" if fmt.upper() == "JPEG" else fmt.lower()
        dest = output_dir / f"{i:03d}_{safe}.{ext}"
        if fmt.upper() == "JPEG":
            img = img.convert("RGB")
        img.save(str(dest), format=fmt)
        saved.append(dest)
        if on_progress:
            on_progress(i + 1, len(items), dest)
    return saved


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_background(item: ThumbnailItem, project: Project, cfg: ResolvedSettings) -> Image.Image:
    path_str = item.effective_image(project.phantom)
    if path_str:
        try:
            return Image.open(path_str).convert("RGBA")
        except Exception:
            pass
    return _checkerboard(cfg.canvas_width, cfg.canvas_height)


def _apply_framing(img: Image.Image, cfg: ResolvedSettings) -> Image.Image:
    W, H = cfg.canvas_width, cfg.canvas_height
    iw, ih = img.size
    fit = cfg.image_fit

    if fit == "stretch":
        return img.resize((W, H), Image.Resampling.LANCZOS)

    if fit == "fill":
        scale = max(W / iw, H / ih)
        nw, nh = int(iw * scale), int(ih * scale)
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        x, y = (nw - W) // 2, (nh - H) // 2
        img = img.crop((x, y, x + W, y + H))
        return img

    if fit == "fit":
        scale = min(W / iw, H / ih)
        nw, nh = int(iw * scale), int(ih * scale)
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        ox, oy = (W - nw) // 2, (H - nh) // 2
        canvas.paste(img, (ox, oy))
        return canvas

    # center: no scaling, just center-crop or pad
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    ox, oy = max(0, (W - iw) // 2), max(0, (H - ih) // 2)
    sx, sy = max(0, (iw - W) // 2), max(0, (ih - H) // 2)
    paste_w = min(iw - sx, W - ox)
    paste_h = min(ih - sy, H - oy)
    canvas.paste(img.crop((sx, sy, sx + paste_w, sy + paste_h)), (ox, oy))
    return canvas


def _composite_box(img: Image.Image, cfg: ResolvedSettings) -> Image.Image:
    if not cfg.box_enabled:
        return img
    W, H = img.size
    box_h = int(H * cfg.box_height)
    r, g, b = cfg.box_color
    a = cfg.box_opacity
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    if cfg.box_position == "bottom":
        draw.rectangle((0, H - box_h, W, H), fill=(r, g, b, a))
    elif cfg.box_position == "top":
        draw.rectangle((0, 0, W, box_h), fill=(r, g, b, a))
    else:  # full
        draw.rectangle((0, 0, W, H), fill=(r, g, b, a))
    return Image.alpha_composite(img, overlay)


def _draw_text(img: Image.Image, label: str, cfg: ResolvedSettings, font_manager: FontManager) -> Image.Image:
    W, H = img.size
    text = _apply_transform(label, cfg.text_transform)
    pad = cfg.box_padding

    # Determine usable width
    usable_w = W - pad * 2

    # Fit font and wrap text
    font, lines = _fit_text(
        text, usable_w,
        cfg.font_name, cfg.font_size, cfg.font_min_size,
        cfg.font_max_lines, cfg.font_auto_size,
        font_manager,
    )

    # Measure total text block
    draw_tmp = ImageDraw.Draw(img.copy())
    line_bboxes = [draw_tmp.textbbox((0, 0), ln, font=font) for ln in lines]
    line_heights = [bb[3] - bb[1] for bb in line_bboxes]
    line_widths  = [bb[2] - bb[0] for bb in line_bboxes]
    spacing = max(4, int(font.size * 0.15))
    total_h = sum(line_heights) + spacing * (len(lines) - 1)
    max_w = max(line_widths) if line_widths else 0

    # Anchor position
    cx = int(W * cfg.text_x)
    cy = int(H * cfg.text_y)
    block_top = cy - total_h // 2

    # Build a new RGBA layer for the text so we can apply opacity
    text_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(text_layer)

    tr, tg, tb = cfg.text_color
    ta = cfg.text_opacity

    y_cursor = block_top
    for ln, lh, lw in zip(lines, line_heights, line_widths):
        if cfg.text_align == "left":
            x = cx - max_w // 2
        elif cfg.text_align == "right":
            x = cx + max_w // 2 - lw
        else:
            x = cx - lw // 2

        # Shadow (drawn first, behind everything)
        if cfg.shadow_enabled:
            sx, sy = cfg.shadow_offset_x, cfg.shadow_offset_y
            sr, sg, sb = cfg.shadow_color
            _draw_shadow(d, ln, x, y_cursor, font, (sr, sg, sb, ta), sx, sy, cfg.shadow_blur)

        # Outline
        if cfg.outline_enabled:
            ow = cfg.outline_width
            or_, og, ob = cfg.outline_color
            for dx in range(-ow, ow + 1):
                for dy in range(-ow, ow + 1):
                    if dx == 0 and dy == 0:
                        continue
                    if abs(dx) + abs(dy) > ow + 1:
                        continue
                    d.text((x + dx, y_cursor + dy), ln, font=font, fill=(or_, og, ob, ta))

        # Main text
        d.text((x, y_cursor), ln, font=font, fill=(tr, tg, tb, ta))
        y_cursor += lh + spacing

    return Image.alpha_composite(img, text_layer)


def _draw_shadow(draw: ImageDraw.Draw, text: str, x: int, y: int, font, color: tuple, ox: int, oy: int, blur: int):
    if blur <= 0:
        draw.text((x + ox, y + oy), text, font=font, fill=color)
        return
    # Render shadow to a tiny temp surface then blur
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    margin = blur * 2
    shadow_img = Image.new("RGBA", (tw + margin * 2, th + margin * 2), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow_img)
    sd.text((margin, margin), text, font=font, fill=color)
    shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(radius=blur))
    draw._image.paste(shadow_img, (x + ox - margin, y + oy - margin), shadow_img)


def _fit_text(
    text: str, max_width: int,
    font_name: str, max_size: int, min_size: int,
    max_lines: int, auto_size: bool,
    font_manager: FontManager,
) -> tuple:
    """Return (font, lines) that fit within max_width and max_lines."""
    sizes = range(max_size, min_size - 1, -2) if auto_size else [max_size]

    for size in sizes:
        font = font_manager.get_pil_font(font_name, size)
        lines = _wrap_text(text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines

    # At min_size, just truncate
    font = font_manager.get_pil_font(font_name, min_size)
    lines = _wrap_text(text, font, max_width)
    return font, lines[:max_lines]


def _wrap_text(text: str, font, max_width: int) -> list[str]:
    """Wrap text using real PIL text measurement."""
    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    words = text.split()
    lines: list[str] = []
    current: list[str] = []

    for word in words:
        candidate = " ".join(current + [word])
        bb = dummy.textbbox((0, 0), candidate, font=font)
        w = bb[2] - bb[0]
        if w <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]

    if current:
        lines.append(" ".join(current))
    return lines or [""]


def _apply_transform(text: str, transform: str) -> str:
    match transform:
        case "upper": return text.upper()
        case "lower": return text.lower()
        case "title": return text.title()
        case _: return text


def _fit_to_preview(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    img.thumbnail(size, Image.Resampling.LANCZOS)
    return img


def _safe_filename(s: str, max_len: int = 60) -> str:
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in s).strip()
    return safe[:max_len] or "item"


def _checkerboard(w: int, h: int, sq: int = 40) -> Image.Image:
    img = Image.new("RGBA", (w, h))
    pix = img.load()
    light = (200, 200, 200, 255)
    dark  = (160, 160, 160, 255)
    for y in range(h):
        for x in range(w):
            pix[x, y] = light if ((x // sq) + (y // sq)) % 2 == 0 else dark
    return img
