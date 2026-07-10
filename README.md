# QR Studio

**Live:** https://qr-studio-bay-iota.vercel.app

A modern, fast QR code generator built with Flask. Paste any link or text and get a
crisp, high-resolution QR code instantly — customise foreground/background colours and
resolution, then download or copy the image.

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

- Flask (server + JSON API at `POST /api/generate`)
- `qrcode` + `Pillow` for image generation
- Vanilla HTML/CSS/JS front end with live preview, colour + size controls
