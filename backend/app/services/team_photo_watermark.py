"""Compose print-ready JPEGs without changing the official team photograph.

Rendering happens in memory. Callers store the result through the existing
object store under team-photo-prints/, never under team-photos/.
"""

from __future__ import annotations

import io
import re
import secrets
from typing import Iterable, Optional

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

from app.services.team_photo_storage import PhotoRejected

WALGREENS_ORDER_URL = "https://photo.walgreens.com/store/prints"
WALGREENS_DIRECT_ORDERING = False
WALGREENS_NOTE = (
    "No authorized Walgreens photo-print ordering API is connected. "
    "This application does not place or confirm an order. Staff download the print package, "
    "upload it on Walgreens Photo, and choose the pickup store. "
    "Price and store availability are shown by Walgreens during checkout."
)

PRINT_SIZE = "4x6"
PRINT_WIDTH = 1200
PRINT_HEIGHT = 1800
PRINT_DPI = 300
SAFE_MARGIN = 0.04

CONTENT_MODES = {"logo_and_text", "logo_only", "text_only", "custom_logo", "custom_text"}
FONT_FAMILIES = ["Arial", "Montserrat", "Poppins", "Roboto", "Georgia", "Times New Roman"]
FONT_STYLES = {"normal", "medium", "bold", "italic"}
POSITIONS = {
    "top-left": (0.0, 0.0),
    "top-center": (0.5, 0.0),
    "top-right": (1.0, 0.0),
    "middle-left": (0.0, 0.5),
    "center": (0.5, 0.5),
    "middle-right": (1.0, 0.5),
    "bottom-left": (0.0, 1.0),
    "bottom-center": (0.5, 1.0),
    "bottom-right": (1.0, 1.0),
}
NAMED_COLORS = {
    "white": "#ffffff",
    "black": "#111111",
    "gray": "#9e9e9e",
    "red": "#c62828",
    "blue": "#1565c0",
    "yellow": "#f9a825",
}

_FONT_FILES = {
    "Arial": {
        "normal": ["arial.ttf", "Arial.ttf", "LiberationSans-Regular.ttf", "DejaVuSans.ttf"],
        "medium": ["arial.ttf", "Arial.ttf", "LiberationSans-Regular.ttf", "DejaVuSans.ttf"],
        "bold": ["arialbd.ttf", "Arial-Bold.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf"],
        "italic": ["ariali.ttf", "Arial-Italic.ttf", "LiberationSans-Italic.ttf", "DejaVuSans-Oblique.ttf"],
    },
    "Montserrat": {
        "normal": ["Montserrat-Regular.ttf", "arial.ttf", "DejaVuSans.ttf"],
        "medium": ["Montserrat-Medium.ttf", "Montserrat-Regular.ttf", "arial.ttf", "DejaVuSans.ttf"],
        "bold": ["Montserrat-Bold.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"],
        "italic": ["Montserrat-Italic.ttf", "ariali.ttf", "DejaVuSans-Oblique.ttf"],
    },
    "Poppins": {
        "normal": ["Poppins-Regular.ttf", "arial.ttf", "DejaVuSans.ttf"],
        "medium": ["Poppins-Medium.ttf", "Poppins-Regular.ttf", "arial.ttf", "DejaVuSans.ttf"],
        "bold": ["Poppins-Bold.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"],
        "italic": ["Poppins-Italic.ttf", "ariali.ttf", "DejaVuSans-Oblique.ttf"],
    },
    "Roboto": {
        "normal": ["Roboto-Regular.ttf", "arial.ttf", "DejaVuSans.ttf"],
        "medium": ["Roboto-Medium.ttf", "Roboto-Regular.ttf", "arial.ttf", "DejaVuSans.ttf"],
        "bold": ["Roboto-Bold.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"],
        "italic": ["Roboto-Italic.ttf", "ariali.ttf", "DejaVuSans-Oblique.ttf"],
    },
    "Georgia": {
        "normal": ["georgia.ttf", "Georgia.ttf", "LiberationSerif-Regular.ttf", "DejaVuSerif.ttf"],
        "medium": ["georgia.ttf", "Georgia.ttf", "LiberationSerif-Regular.ttf", "DejaVuSerif.ttf"],
        "bold": ["georgiab.ttf", "Georgia-Bold.ttf", "LiberationSerif-Bold.ttf", "DejaVuSerif-Bold.ttf"],
        "italic": ["georgiai.ttf", "Georgia-Italic.ttf", "LiberationSerif-Italic.ttf", "DejaVuSerif-Italic.ttf"],
    },
    "Times New Roman": {
        "normal": ["times.ttf", "timesnr.ttf", "Times New Roman.ttf", "LiberationSerif-Regular.ttf", "DejaVuSerif.ttf"],
        "medium": ["times.ttf", "timesnr.ttf", "LiberationSerif-Regular.ttf", "DejaVuSerif.ttf"],
        "bold": ["timesbd.ttf", "Times New Roman Bold.ttf", "LiberationSerif-Bold.ttf", "DejaVuSerif-Bold.ttf"],
        "italic": ["timesi.ttf", "Times New Roman Italic.ttf", "LiberationSerif-Italic.ttf", "DejaVuSerif-Italic.ttf"],
    },
}
_FONT_DIRS = (
    "C:/Windows/Fonts",
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/truetype/msttcorefonts",
)


def default_settings(tournament_name: str) -> dict:
    return {
        "content_mode": "logo_and_text",
        "event_text": (tournament_name or "Tournament").strip() or "Tournament",
        "custom_text": "",
        "font_family": "Arial",
        "font_style": "bold",
        "color": "#ffffff",
        "size_percent": 28,
        "logo_scale": 1.0,
        "spacing": 8,
        "opacity": 90,
        "position": "top-center",
        "offset_x": 0.0,
        "offset_y": 0.0,
        "shadow": True,
        "visible": True,
        "crop_mode": "fit",
        "crop_x": 0.5,
        "crop_y": 0.5,
        "show_margins": False,
    }


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _hex_color(value: str) -> str:
    text = (value or "").strip().lower()
    if text in NAMED_COLORS:
        return NAMED_COLORS[text]
    if re.fullmatch(r"#[0-9a-f]{6}", text):
        return text
    raise PhotoRejected("Choose a watermark color")


def normalize_settings(payload: Optional[dict], tournament_name: str) -> dict:
    """Return a complete settings object. Unknown fields are dropped."""
    base = default_settings(tournament_name)
    raw = payload or {}
    if not isinstance(raw, dict):
        raise PhotoRejected("Watermark settings are invalid")
    mode = str(raw.get("content_mode") or base["content_mode"])
    if mode not in CONTENT_MODES:
        raise PhotoRejected("Choose a watermark style")
    family = str(raw.get("font_family") or base["font_family"])
    if family not in FONT_FAMILIES:
        raise PhotoRejected("Choose a watermark font")
    style = str(raw.get("font_style") or base["font_style"])
    if style not in FONT_STYLES:
        raise PhotoRejected("Choose a font style")
    position = str(raw.get("position") or base["position"])
    if position not in POSITIONS:
        raise PhotoRejected("Choose a watermark position")
    crop_mode = str(raw.get("crop_mode") or base["crop_mode"])
    if crop_mode not in {"fit", "fill"}:
        raise PhotoRejected("Choose fit or fill")
    event_text = str(raw.get("event_text") if raw.get("event_text") is not None else base["event_text"])
    event_text = " ".join(event_text.split())[:80] or base["event_text"]
    custom_text = " ".join(str(raw.get("custom_text") or "").split())[:80]
    if mode == "custom_text" and not custom_text:
        raise PhotoRejected("Enter the custom watermark text")
    try:
        size_percent = float(raw.get("size_percent", base["size_percent"]))
        logo_scale = float(raw.get("logo_scale", base["logo_scale"]))
        spacing = float(raw.get("spacing", base["spacing"]))
        opacity = float(raw.get("opacity", base["opacity"]))
        offset_x = float(raw.get("offset_x", base["offset_x"]))
        offset_y = float(raw.get("offset_y", base["offset_y"]))
        crop_x = float(raw.get("crop_x", base["crop_x"]))
        crop_y = float(raw.get("crop_y", base["crop_y"]))
    except (TypeError, ValueError) as exc:
        raise PhotoRejected("Watermark settings are invalid") from exc
    return {
        "content_mode": mode,
        "event_text": event_text,
        "custom_text": custom_text,
        "font_family": family,
        "font_style": style,
        "color": _hex_color(str(raw.get("color") or base["color"])),
        "size_percent": int(round(_clamp(size_percent, 8, 80))),
        "logo_scale": round(_clamp(logo_scale, 0.4, 2.5), 2),
        "spacing": int(round(_clamp(spacing, 0, 40))),
        "opacity": int(round(_clamp(opacity, 10, 100))),
        "position": position,
        "offset_x": round(_clamp(offset_x, -1, 1), 4),
        "offset_y": round(_clamp(offset_y, -1, 1), 4),
        "shadow": bool(raw.get("shadow", base["shadow"])),
        "visible": bool(raw.get("visible", base["visible"])),
        "crop_mode": crop_mode,
        "crop_x": round(_clamp(crop_x, 0, 1), 4),
        "crop_y": round(_clamp(crop_y, 0, 1), 4),
        "show_margins": bool(raw.get("show_margins", base["show_margins"])),
    }


def print_pixels(print_size: str, source_width: int, source_height: int) -> tuple[int, int]:
    """Every print is 4×6 portrait, 1200 × 1800, regardless of the source orientation."""
    del source_width, source_height
    if print_size != PRINT_SIZE:
        raise PhotoRejected("Prints are 4×6 portrait only")
    return PRINT_WIDTH, PRINT_HEIGHT


def crop_cuts_photo(source_width: int, source_height: int, crop_mode: str) -> bool:
    """True when fill framing removes part of the photograph, which can cut off a player."""
    if crop_mode != "fill" or source_width <= 0 or source_height <= 0:
        return False
    source_ratio = source_width / source_height
    target_ratio = PRINT_WIDTH / PRINT_HEIGHT
    return abs(source_ratio - target_ratio) > 0.015


def source_needs_upscale(source_width: int, source_height: int, target_width: int, target_height: int, crop_mode: str) -> bool:
    if source_width <= 0 or source_height <= 0:
        return True
    if crop_mode == "fill":
        scale = max(target_width / source_width, target_height / source_height)
    else:
        scale = min(target_width / source_width, target_height / source_height)
    return scale > 1.001


def slug_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value or "").strip("-")
    return cleaned


def print_filename(tournament_name: str, player_names: Iterable[str], print_size: str) -> str:
    names = [
        slug_part(name)
        for name in player_names
        if name and name.strip() and name.strip() != "Partner not on file"
    ]
    parts = [slug_part(tournament_name), *names, print_size]
    stem = "-".join(part for part in parts if part) or f"team-photo-{print_size}"
    return f"{stem}.jpg"


def print_object_key(tournament_id: int, team_id: int, version: str) -> str:
    token = "".join(ch for ch in version if ch.isalnum())[:32]
    if len(token) < 8:
        raise PhotoRejected("Print version is invalid")
    return f"team-photo-prints/{int(tournament_id)}/{int(team_id)}/{token}.jpg"


def logo_object_key(tournament_id: int) -> str:
    return f"team-photo-prints/{int(tournament_id)}/brand/logo.png"


def owned_print_key(tournament_id: int, team_id: int, key: Optional[str]) -> bool:
    if not key or ".." in key or "\\" in key or key.startswith("team-photos/"):
        return False
    prefix = f"team-photo-prints/{int(tournament_id)}/{int(team_id)}/"
    if not key.startswith(prefix):
        return False
    rest = key[len(prefix):]
    return bool(rest) and "/" not in rest and rest.endswith(".jpg")


def owned_logo_key(tournament_id: int, key: Optional[str]) -> bool:
    return key == logo_object_key(tournament_id)


def new_print_version() -> str:
    return secrets.token_hex(8)


def _load_font(family: str, style: str, size: int) -> ImageFont.ImageFont:
    names = _FONT_FILES.get(family, _FONT_FILES["Arial"]).get(style) or _FONT_FILES["Arial"]["normal"]
    for folder in _FONT_DIRS:
        for name in names:
            path = f"{folder}/{name}"
            try:
                return ImageFont.truetype(path, size=max(8, size))
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=max(8, size))
    except TypeError:
        return ImageFont.load_default()


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[index:index + 2], 16) for index in (1, 3, 5))  # type: ignore[return-value]


def _fit_font(draw: ImageDraw.ImageDraw, text: str, family: str, style: str, max_width: int) -> ImageFont.ImageFont:
    size = max(12, int(max_width * 0.18))
    font = _load_font(family, style, size)
    while size > 10:
        font = _load_font(family, style, size)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= max_width:
            return font
        size -= 2
    return font


def _watermark_layer(settings: dict, target_width: int, logo: Optional[Image.Image]) -> Image.Image:
    mode = settings["content_mode"]
    show_logo = mode in {"logo_and_text", "logo_only", "custom_logo"}
    if mode == "custom_text":
        text = settings["custom_text"]
    elif mode == "logo_only":
        text = ""
    elif mode == "custom_logo":
        text = settings["event_text"]
    else:
        text = settings["event_text"]
    mark_width = max(40, int(target_width * settings["size_percent"] / 100))
    color = _rgb(settings["color"])
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    font = _fit_font(probe, text or "RW", settings["font_family"], settings["font_style"], mark_width)
    text_box = probe.textbbox((0, 0), text, font=font) if text else (0, 0, 0, 0)
    text_h = text_box[3] - text_box[1] if text else 0
    text_w = text_box[2] - text_box[0] if text else 0
    logo_h = 0
    logo_image = None
    if show_logo:
        logo_h = max(18, int(mark_width * 0.34 * float(settings["logo_scale"])))
        if logo is not None and mode == "custom_logo":
            logo_image = logo.convert("RGBA")
            logo_image.thumbnail((mark_width, logo_h), Image.Resampling.LANCZOS)
            logo_h = logo_image.height
        else:
            logo_image = None
    gap = settings["spacing"] if text and show_logo else 0
    layer_h = logo_h + gap + text_h + 8
    layer = Image.new("RGBA", (max(mark_width, text_w), max(layer_h, 8)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cursor = 0
    if show_logo:
        if logo_image is not None:
            left = max(0, (layer.width - logo_image.width) // 2)
            layer.alpha_composite(logo_image, (left, 0))
        else:
            badge_w = min(mark_width, max(36, int(logo_h * 1.8)))
            left = max(0, (layer.width - badge_w) // 2)
            draw.rounded_rectangle((left, 0, left + badge_w, logo_h), radius=max(4, logo_h // 5), outline=color + (255,), width=max(2, logo_h // 14))
            badge_font = _fit_font(draw, "RW", settings["font_family"], "bold", int(badge_w * 0.7))
            badge_box = draw.textbbox((0, 0), "RW", font=badge_font)
            draw.text(
                (left + (badge_w - (badge_box[2] - badge_box[0])) / 2, (logo_h - (badge_box[3] - badge_box[1])) / 2 - badge_box[1]),
                "RW",
                font=badge_font,
                fill=color + (255,),
            )
        cursor = logo_h + gap
    if text:
        left = max(0, (layer.width - text_w) // 2)
        if settings["shadow"]:
            draw.text((left + 2, cursor + 2), text, font=font, fill=(0, 0, 0, 180))
        draw.text((left, cursor), text, font=font, fill=color + (255,))
    opacity = settings["opacity"] / 100
    if opacity < 0.999:
        alpha = layer.getchannel("A")
        alpha = ImageEnhance.Brightness(alpha).enhance(opacity)
        layer.putalpha(alpha)
    return layer


def _place_photo(source: Image.Image, canvas_w: int, canvas_h: int, settings: dict) -> Image.Image:
    canvas = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
    src_w, src_h = source.size
    if settings["crop_mode"] == "fill":
        scale = max(canvas_w / src_w, canvas_h / src_h)
        resized = source.resize((max(1, int(round(src_w * scale))), max(1, int(round(src_h * scale)))), Image.Resampling.LANCZOS)
        extra_x = resized.width - canvas_w
        extra_y = resized.height - canvas_h
        left = int(round(extra_x * settings["crop_x"]))
        top = int(round(extra_y * settings["crop_y"]))
        left = max(0, min(left, extra_x))
        top = max(0, min(top, extra_y))
        cropped = resized.crop((left, top, left + canvas_w, top + canvas_h))
        canvas.paste(cropped, (0, 0))
        return canvas
    scale = min(canvas_w / src_w, canvas_h / src_h)
    resized = source.resize((max(1, int(round(src_w * scale))), max(1, int(round(src_h * scale)))), Image.Resampling.LANCZOS)
    left = (canvas_w - resized.width) // 2
    top = (canvas_h - resized.height) // 2
    canvas.paste(resized, (left, top))
    return canvas


def _paste_watermark(canvas: Image.Image, layer: Image.Image, settings: dict) -> Image.Image:
    margin = int(round(min(canvas.size) * SAFE_MARGIN))
    max_w = max(1, canvas.width - margin * 2)
    max_h = max(1, canvas.height - margin * 2)
    if layer.width > max_w or layer.height > max_h:
        layer = layer.copy()
        layer.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
    anchor_x, anchor_y = POSITIONS[settings["position"]]
    x = margin + anchor_x * (canvas.width - margin * 2 - layer.width) + settings["offset_x"] * canvas.width
    y = margin + anchor_y * (canvas.height - margin * 2 - layer.height) + settings["offset_y"] * canvas.height
    x = int(round(_clamp(x, margin, canvas.width - margin - layer.width)))
    y = int(round(_clamp(y, margin, canvas.height - margin - layer.height)))
    base = canvas.convert("RGBA")
    base.alpha_composite(layer, (x, y))
    return base.convert("RGB")


def render_print_jpeg(
    source_bytes: bytes,
    settings: dict,
    print_size: str,
    *,
    logo_bytes: Optional[bytes] = None,
    allow_upscale: bool = False,
) -> tuple[bytes, int, int, int, int, bool]:
    """Return jpeg bytes, width, height, source width, source height, and whether pixels were enlarged."""
    try:
        source = ImageOps.exif_transpose(Image.open(io.BytesIO(source_bytes)))
        source = source.convert("RGB")
    except Exception as exc:
        raise PhotoRejected("Official photograph could not be read") from exc
    source_w, source_h = source.size
    canvas_w, canvas_h = print_pixels(print_size, source_w, source_h)
    low_resolution = source_needs_upscale(source_w, source_h, canvas_w, canvas_h, settings["crop_mode"])
    if low_resolution and not allow_upscale:
        raise PhotoRejected(
            f"This photograph is {source_w}×{source_h}, below 1200×1800 for a 300 DPI 4×6 portrait. "
            "Confirm the resolution warning before creating the print file.",
            status_code=409,
        )
    canvas = _place_photo(source, canvas_w, canvas_h, settings)
    if settings["visible"]:
        logo = None
        if logo_bytes and settings["content_mode"] == "custom_logo":
            try:
                logo = ImageOps.exif_transpose(Image.open(io.BytesIO(logo_bytes)))
            except Exception as exc:
                raise PhotoRejected("Custom logo could not be read") from exc
        layer = _watermark_layer(settings, canvas_w, logo)
        canvas = _paste_watermark(canvas, layer, settings)
    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=92, subsampling=0, dpi=(PRINT_DPI, PRINT_DPI), optimize=True)
    data = out.getvalue()
    if not data:
        raise PhotoRejected("Print file could not be created")
    return data, canvas_w, canvas_h, source_w, source_h, low_resolution


def prepare_logo(raw: bytes) -> bytes:
    if not raw:
        raise PhotoRejected("Logo file is empty")
    if len(raw) > 2 * 1024 * 1024:
        raise PhotoRejected("Logo is too large", status_code=413)
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
        image = image.convert("RGBA")
        image.thumbnail((800, 800), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, format="PNG", optimize=True)
    except PhotoRejected:
        raise
    except Exception as exc:
        raise PhotoRejected("Logo could not be read. Use a PNG or JPEG.") from exc
    data = out.getvalue()
    if not data:
        raise PhotoRejected("Logo could not be saved")
    return data
