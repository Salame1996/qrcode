"""Photo QR ("halftone") rendering: the picture becomes the code itself.

This is a fundamentally different technique from the logo presets in qrstyle.py.
There, a logo sits on top of an otherwise ordinary QR and the error-correction
budget absorbs what it covers. Here the image is expressed *through* the module
pattern, which only works by choosing the encoding — mask pattern and padding
region — so the modules naturally fall where the picture wants them.

Compositing alone cannot do that. Building the pattern by hand and then flipping
modules toward the image breaks the code at roughly 10% of modules flipped,
because each flip damages a different Reed-Solomon codeword; measured fidelity
tops out around 0.34, which reads as a faint ghost rather than a picture. amzqr
works at the encoding level instead, so it gets both a legible image and a
readable code.

The trade-off is real and worth stating plainly: these codes are more fragile
than the logo presets. OpenCV's detector cannot read them at all, while ZXing —
the engine behind Android and most scanner apps — reads them reliably. Every
code is therefore verified before it is returned, and the caller is told whether
that verification actually ran.
"""

import base64
import io
import os
import tempfile

from PIL import Image

from qrstyle import QRError, load_logo

try:  # Verification is best-effort: never let a missing wheel break generation.
    import zxingcpp
except Exception:  # pragma: no cover - depends on the deployment target
    zxingcpp = None

try:
    from amzqr import amzqr
except Exception:  # pragma: no cover
    amzqr = None

# amzqr renders fairly small; upscaling with NEAREST is lossless for a pattern
# of hard-edged blocks and gives people a file worth downloading.
TARGET_PX = 1080
MIN_VERSION = 5
MAX_VERSION = 20

# A photo needs real tonal spread to survive being reduced to black and white.
MIN_STDDEV = 18.0


def _pick_version(data):
    """More modules means more room for the picture, within what the data allows."""
    length = len(data.encode("utf-8"))
    if length <= 40:
        return 8
    if length <= 90:
        return 12
    if length <= 160:
        return 16
    return MAX_VERSION


def check_photo_suitability(image):
    """Warn early about photos that will turn to mush once reduced to 2 tones."""
    grey = image.convert("L").resize((128, 128), Image.LANCZOS)
    import statistics

    pixels = list(grey.getdata())
    spread = statistics.pstdev(pixels)
    if spread < MIN_STDDEV:
        raise QRError(
            "That photo is too flat to turn into a QR code. Pick one with a clear "
            "subject and strong light and dark areas — a face against a plain "
            "background works best."
        )
    return spread


def verify(image, expected):
    """Return True/False if we could check, or None if no decoder is available."""
    if zxingcpp is None:
        return None
    try:
        results = zxingcpp.read_barcodes(image.convert("L"))
    except Exception:
        return None
    return bool(results) and results[0].text == expected


def render(data, photo_bytes, colorized=False, contrast=1.5, brightness=1.1):
    """Render `data` as a halftone QR built out of `photo_bytes`.

    Returns (data_uri, verified) where verified is True/False/None.
    """
    if not data:
        raise QRError("Please enter a link or some text.")
    if amzqr is None:
        raise QRError("Photo QR codes aren't available on this server right now.")
    if not photo_bytes:
        raise QRError("Please add a photo first.")

    # Reuse the upload validation from the logo path: size cap, format allowlist,
    # decompression-bomb guard, and a re-encode that drops EXIF.
    photo = load_logo(photo_bytes)
    if photo is None:
        raise QRError("Please add a photo first.")
    check_photo_suitability(photo)

    # Clamp the inputs the front end can influence.
    contrast = max(0.5, min(float(contrast or 1.5), 3.0))
    brightness = max(0.5, min(float(brightness or 1.1), 2.0))

    with tempfile.TemporaryDirectory(dir=tempfile.gettempdir()) as work:
        source = os.path.join(work, "source.png")
        # Flatten to RGB on a white ground: transparency has no meaning here and
        # amzqr wants a plain raster on disk.
        flat = Image.new("RGB", photo.size, (255, 255, 255))
        flat.paste(photo, mask=photo.split()[-1])
        flat.save(source)

        try:
            _, _, produced = amzqr.run(
                data,
                version=_pick_version(data),
                level="H",
                picture=source,
                colorized=bool(colorized),
                contrast=contrast,
                brightness=brightness,
                save_name="photo-qr.png",
                save_dir=work,
            )
        except Exception as exc:  # amzqr raises bare ValueErrors for oversized data
            raise QRError(f"Couldn't build a photo QR from that: {exc}")

        image = Image.open(produced)
        image.load()

    if image.width < TARGET_PX:
        # Round the factor up, so every download clears TARGET_PX rather than
        # leaving mid-sized renders at their original scale.
        factor = -(-TARGET_PX // image.width)
        image = image.resize((image.width * factor, image.height * factor), Image.NEAREST)

    verified = verify(image, data)
    if verified is False:
        raise QRError(
            "That photo produced a code that wouldn't scan. Try one with a clearer "
            "subject, or raise the contrast."
        )

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG", optimize=True)
    buffer.seek(0)
    uri = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    return uri, verified
