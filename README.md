# QR Studio

**Live:** https://qr-studio-bay-iota.vercel.app

A modern, fast QR code generator built with Flask. Paste any link or text and get a
crisp, high-resolution QR code instantly — customise foreground/background colours,
pick a style and drop in a company logo, then download or copy the image.

## Branded QR codes

Upload a logo (SVG, PNG, JPG or WEBP) and it is composited into the centre of the code.
Five styles are available: Classic, Dots, Rounded, Target and Soft.

Two design rules keep every generated code scannable, both established by decoding
test renders with OpenCV at sizes from 600px down to 180px:

- **Logo coverage stays at or below 30%** of the QR area, paired with
  `ERROR_CORRECT_H` (30% redundancy). At 38% the code stops decoding entirely.
- **Finder-pattern ("eye") corners stay nearly square** — a corner radius of 0.05.
  This turned out to be the single biggest threat to detection, ahead of both module
  shape and the logo: at radius 0.15 codes fail below 300px. Recolouring the eyes
  costs nothing, so the presets get their personality from colour rather than shape.

The API also rejects colour pairs that cannot scan — under 3:1 contrast, or a
foreground lighter than the background (inverted codes fail on many phone cameras).

## Photo QR codes (halftone)

A second mode where the photo *becomes* the code rather than sitting on top of it —
upload an image or take one with the camera (`getUserMedia` on desktop, the native
camera via the `capture` attribute on phones).

This cannot be done by compositing. Building the module pattern by hand and then
flipping modules toward the picture breaks the code at roughly 10% of modules
flipped, because each flip damages a different Reed-Solomon codeword — measured
image fidelity tops out around 0.34, a faint ghost rather than a picture. It has to
happen at the encoding level, choosing the mask pattern and using the padding region
so the modules fall where the image wants them. `amzqr` does that, and it is pure
Python on top of Pillow, so it deploys to Vercel without native dependencies.

**These codes are more fragile than the logo presets, and the difference is real:**
OpenCV's detector cannot read them at all, while ZXing — the engine behind Android
and most scanner apps — reads them reliably. Every generated code is therefore
verified with ZXing before it is returned, and one that fails is rejected rather
than handed over. The UI says plainly that these are artistic codes worth testing
before a print run. Photos that are too flat to survive being reduced to two tones
are rejected up front.

### SVG handling

SVGs are rasterised to PNG **in the browser** before upload, for two reasons: Vercel's
Python runtime has no Cairo, so no server-side rasteriser (`cairosvg`, `svglib`,
`rlPyCairo`) can be installed there; and an SVG is active XML that can carry scripts and
external entities, so the server never parses one. It only ever receives flat pixels,
which are re-encoded on load to strip metadata.

## Run locally

```bash
pip install -r requirements.txt
python main.py
```

Then open http://localhost:5000

## Deploy to Vercel

This repo is preconfigured for Vercel's Python runtime:

- `api/index.py` exposes the Flask `app` as the serverless entry point.
- `vercel.json` routes every request to it and bundles the `templates/` folder.
- `requirements.txt` lists the dependencies.

Just import the repo on [vercel.com](https://vercel.com) (or run `vercel`) — no extra config needed.

## Tech

- Flask (server + JSON APIs at `POST /api/generate` and `POST /api/photo`)
- `qrcode` + `Pillow` for image generation; styling and logo compositing in `qrstyle.py`
- `amzqr` for halftone photo codes and `zxing-cpp` to verify them, both in `photoqr.py`
- Vanilla HTML/CSS/JS front end with live preview, style presets, colour controls and
  drag-and-drop logo upload
