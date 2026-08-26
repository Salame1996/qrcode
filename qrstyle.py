"""Branded QR rendering: styled modules, recoloured eyes and a centred logo.

Every preset here is deliberately kept inside an envelope that was verified
against a strict decoder (OpenCV) at full size, 400px and 220px. Two findings
from that testing shape the numbers below:

  * Logo coverage is safe to ~30% of the QR area with ERROR_CORRECT_H; 38% fails
    outright. Presets sit at 22-26% to leave headroom for print and screens.
  * Rounding the finder-pattern ("eye") corners is the single biggest threat to
    detection — bigger than module shape or the logo, both of which decode
    cleanly on their own down to 180px. Radius 0.05 is safe at every size
    tested; 0.10 is already flaky below 300px and 0.15 fails there outright.
    Recolouring the eyes costs nothing, so the presets lean on colour for
    personality and keep the corners nearly square.
"""

import base64
import io

import qrcode
from qrcode.constants import ERROR_CORRECT_H
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.colormasks import SolidFillColorMask
from qrcode.image.styles.moduledrawers.pil import (
    CircleModuleDrawer,
    GappedSquareModuleDrawer,
    RoundedModuleDrawer,
    SquareModuleDrawer,
)
from PIL import Image, ImageDraw

# --- upload limits -----------------------------------------------------------
# Vercel caps a serverless request body at 4.5MB; a 2MB logo leaves room for the
# base64 inflation plus the rest of the JSON payload.
MAX_LOGO_BYTES = 2 * 1024 * 1024
MAX_LOGO_PIXELS = 25_000_000  # decompression-bomb guard
ALLOWED_LOGO_FORMATS = {"PNG", "JPEG", "WEBP"}

# Hard ceilings; presets stay well under these.
MAX_LOGO_RATIO = 0.30
MAX_EYE_RADIUS = 0.05

BOX_SIZE = 16
BORDER = 4  # spec minimum quiet zone, matters for print


class QRError(ValueError):
    """Raised with a message that is safe to show the end user."""


# --- colour helpers ----------------------------------------------------------

def hex_to_rgb(value, fallback=(17, 17, 17)):
    if not isinstance(value, str):
        return fallback
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    if len(v) != 6:
        return fallback
    try:
        return tuple(int(v[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return fallback


def _relative_luminance(rgb):
    """WCAG relative luminance."""
    channels = []
    for c in rgb:
        c = c / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a, b):
    la, lb = _relative_luminance(a), _relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def validate_colors(fill_rgb, back_rgb):
    """Reject colour pairs that produce a QR real scanners choke on."""
    if contrast_ratio(fill_rgb, back_rgb) < 3.0:
        raise QRError(
            "Those two colours are too similar to scan reliably. "
            "Pick a darker foreground or a lighter background."
        )
    # Most scanners assume dark-on-light; inverted codes fail on many phones.
    if _relative_luminance(fill_rgb) >= _relative_luminance(back_rgb):
        raise QRError(
            "The foreground needs to be darker than the background — "
            "inverted QR codes fail on a lot of phone cameras."
        )


# --- presets -----------------------------------------------------------------
# eye_outer / eye_inner of None means "use the foreground colour".
PRESETS = {
    "classic": {
        "label": "Classic",
        "drawer": SquareModuleDrawer,
        "drawer_kwargs": {},
        "eye_radius": 0.0,
        "eye_outer": None,
        "eye_inner": None,
        "logo_ratio": 0.24,
    },
    "dots": {
        "label": "Dots",
        "drawer": CircleModuleDrawer,
        "drawer_kwargs": {},
        "eye_radius": 0.05,
        "eye_outer": None,
        "eye_inner": None,
        "logo_ratio": 0.24,
    },
    "rounded": {
        "label": "Rounded",
        "drawer": RoundedModuleDrawer,
        "drawer_kwargs": {"radius_ratio": 1},
        "eye_radius": 0.05,
        "eye_outer": None,
        "eye_inner": None,
        "logo_ratio": 0.24,
    },
    "target": {
        "label": "Target",
        "drawer": CircleModuleDrawer,
        "drawer_kwargs": {},
        "eye_radius": 0.05,
        "eye_outer": "#d32f2f",
        "eye_inner": "#1a237e",
        "logo_ratio": 0.24,
    },
    "soft": {
        "label": "Soft",
        "drawer": GappedSquareModuleDrawer,
        # 0.8 (the library default) loses too much ink to survive downscaling
        # once a logo is present; 0.92 still reads as gapped.
        "drawer_kwargs": {"size_ratio": 0.92},
        "eye_radius": 0.0,
        "eye_outer": None,
        "eye_inner": None,
        "logo_ratio": 0.24,
    },
}
DEFAULT_PRESET = "classic"


def preset_list():
    """Serialisable preset metadata for the front end."""
    return [{"id": key, "label": cfg["label"]} for key, cfg in PRESETS.items()]


# --- logo handling -----------------------------------------------------------

def load_logo(raw):
    """Decode an uploaded logo into a sanitised RGBA image.

    Only raster formats are accepted. SVG is deliberately never parsed here —
    it is an active XML format (scripts, external entities), so the browser
    rasterises it to PNG before upload and the server only ever sees pixels.
    """
    if not raw:
        return None
    if len(raw) > MAX_LOGO_BYTES:
        raise QRError("That logo is too large — please use a file under 2 MB.")

    try:
        probe = Image.open(io.BytesIO(raw))
        fmt = (probe.format or "").upper()
        width, height = probe.size
    except Exception:
        raise QRError("That file doesn't look like a valid image.")

    if fmt not in ALLOWED_LOGO_FORMATS:
        raise QRError("Logos must be a PNG, JPG or WEBP file.")
    if width * height > MAX_LOGO_PIXELS:
        raise QRError("That image's dimensions are too large.")

    try:
        # Re-open and convert: this also drops EXIF and any ancillary chunks.
        logo = Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception:
        raise QRError("That image couldn't be read — try re-exporting it.")

    return logo


def _fit_logo(logo, target_px):
    """Scale the logo to fit a square box without distorting its aspect ratio."""
    w, h = logo.size
    if w == 0 or h == 0:
        raise QRError("That image has no dimensions.")
    scale = target_px / max(w, h)
    return logo.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)


# --- rendering ---------------------------------------------------------------

def _repaint_eyes(qr, img, outer_rgb, inner_rgb, back_rgb, radius_frac):
    """Redraw the three finder patterns, preserving their 7/5/3 module geometry."""
    n = qr.modules_count
    draw = ImageDraw.Draw(img)
    size = 7 * BOX_SIZE
    radius = int(size * radius_frac)

    for cx, cy in [(0, 0), (n - 7, 0), (0, n - 7)]:
        x0, y0 = (BORDER + cx) * BOX_SIZE, (BORDER + cy) * BOX_SIZE
        x1, y1 = x0 + size, y0 + size
        draw.rectangle([x0, y0, x1, y1], fill=back_rgb + (255,))
        # 7x7 outer ring
        draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=outer_rgb + (255,))
        # 5x5 knockout
        draw.rounded_rectangle(
            [x0 + BOX_SIZE, y0 + BOX_SIZE, x1 - BOX_SIZE, y1 - BOX_SIZE],
            radius=int(radius * 0.72),
            fill=back_rgb + (255,),
        )
        # 3x3 core
        draw.rounded_rectangle(
            [x0 + 2 * BOX_SIZE, y0 + 2 * BOX_SIZE, x1 - 2 * BOX_SIZE, y1 - 2 * BOX_SIZE],
            radius=int(radius * 0.45),
            fill=inner_rgb + (255,),
        )
    return img


def render(data, fill="#111111", back="#ffffff", preset=DEFAULT_PRESET, logo_bytes=None):
    """Render `data` as a branded QR code and return a PNG data URI."""
    if not data:
        raise QRError("Please enter a link or some text.")

    cfg = PRESETS.get(preset) or PRESETS[DEFAULT_PRESET]
    fill_rgb, back_rgb = hex_to_rgb(fill), hex_to_rgb(back, (255, 255, 255))
    validate_colors(fill_rgb, back_rgb)

    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_H,
        box_size=BOX_SIZE,
        border=BORDER,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=cfg["drawer"](**cfg.get("drawer_kwargs", {})),
        color_mask=SolidFillColorMask(front_color=fill_rgb, back_color=back_rgb),
    ).convert("RGBA")

    eye_radius = min(cfg["eye_radius"], MAX_EYE_RADIUS)
    outer = hex_to_rgb(cfg["eye_outer"], fill_rgb) if cfg["eye_outer"] else fill_rgb
    inner = hex_to_rgb(cfg["eye_inner"], fill_rgb) if cfg["eye_inner"] else fill_rgb
    if eye_radius > 0 or cfg["eye_outer"] or cfg["eye_inner"]:
        # Eye colours must clear the background too, or the pattern disappears.
        for candidate in (outer, inner):
            if contrast_ratio(candidate, back_rgb) < 3.0:
                raise QRError("This style's colours don't contrast enough with that background.")
        img = _repaint_eyes(qr, img, outer, inner, back_rgb, eye_radius)

    logo = load_logo(logo_bytes)
    if logo is not None:
        width, height = img.size
        ratio = min(cfg["logo_ratio"], MAX_LOGO_RATIO)
        logo = _fit_logo(logo, int(width * ratio))

        # A background-coloured plate keeps modules from showing through
        # transparent parts of the logo and gives the decoder a clean island.
        pad = width // 40
        plate = Image.new(
            "RGBA", (logo.width + pad * 2, logo.height + pad * 2), back_rgb + (255,)
        )
        img.alpha_composite(plate, ((width - plate.width) // 2, (height - plate.height) // 2))
        img.alpha_composite(logo, ((width - logo.width) // 2, (height - logo.height) // 2))

    buffer = io.BytesIO()
    img.convert("RGB").save(buffer, format="PNG", optimize=True)
    buffer.seek(0)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
