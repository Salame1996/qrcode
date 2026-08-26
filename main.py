import base64
import binascii
import os

from flask import Flask, render_template, request, jsonify, Response, redirect

import qrstyle
from qrstyle import QRError

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
app = Flask(__name__, template_folder=TEMPLATE_DIR)

# Keep responses tight and let the browser cache static-ish assets.
app.config["JSON_SORT_KEYS"] = False
# Vercel caps serverless request bodies around 4.5MB; refuse anything larger
# before Flask buffers it.
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024

# Google AdSense publisher ID (e.g. "ca-pub-1234567890123456"). Set via the
# ADSENSE_CLIENT env var on Vercel. While empty, no ad code is emitted anywhere.
# Strip any stray BOM / zero-width chars that shell pipelines can prepend, since
# str.strip() alone won't remove a U+FEFF.
ADSENSE_CLIENT = (
    os.environ.get("ADSENSE_CLIENT", "")
    .replace("﻿", "")
    .replace("​", "")
    .strip()
)


# Canonical ad domain: every alias host funnels here so ads live on one domain,
# and the AdSense code / ads.txt are emitted only on the AdSense-authorized host.
CANONICAL_HOST = "qrgenfree.es"
REDIRECT_HOSTS = {"www.qrgenfree.es", "qrcode.carlossalame.com"}
AD_HOSTS = {"qrgenfree.es"}


def _host():
    return (request.host or "").split(":")[0].lower()


@app.before_request
def canonical_redirect():
    """Permanently send the alias domains to the canonical one (keeps path + query)."""
    if _host() in REDIRECT_HOSTS:
        target = f"https://{CANONICAL_HOST}{request.path}"
        if request.query_string:
            target += "?" + request.query_string.decode()
        return redirect(target, code=308)


@app.context_processor
def inject_adsense():
    """Expose the publisher ID to templates — only on the AdSense-authorized host."""
    return {"adsense_client": ADSENSE_CLIENT if _host() in AD_HOSTS else ""}


@app.route("/", methods=["GET"])
def home():
    return render_template("index.html", presets=qrstyle.preset_list())


@app.route("/api/generate", methods=["POST"])
def generate_api():
    """Smooth path: return the QR as JSON so the page never reloads."""
    payload = request.get_json(silent=True) or request.form
    data = (payload.get("link") or "").strip()
    if not data:
        return jsonify({"error": "Please enter a link or some text."}), 400

    logo_bytes = None
    logo_field = payload.get("logo")
    if logo_field:
        try:
            # The client sends a data URI; SVGs are rasterised in the browser so
            # the server only ever handles flat pixels.
            _, _, encoded = str(logo_field).partition(",")
            logo_bytes = base64.b64decode(encoded or "", validate=True)
        except (binascii.Error, ValueError):
            return jsonify({"error": "That logo couldn't be read — try a PNG."}), 400

    try:
        image = qrstyle.render(
            data,
            fill=payload.get("fill") or "#111111",
            back=payload.get("back") or "#ffffff",
            preset=payload.get("preset") or qrstyle.DEFAULT_PRESET,
            logo_bytes=logo_bytes,
        )
    except QRError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        app.logger.exception("QR generation failed")
        return jsonify({"error": "Could not generate that QR code."}), 400

    return jsonify({"image": image, "data": data})


@app.route("/", methods=["POST"])
def generate_form():
    """Backwards-compatible no-JS fallback that re-renders the page."""
    data = (request.form.get("link") or "").strip()
    image = None
    error = None
    if data:
        try:
            image = qrstyle.render(data)
        except QRError as exc:
            error = str(exc)
    return render_template(
        "index.html", data=image, link=data, error=error, presets=qrstyle.preset_list()
    )


@app.route("/about", methods=["GET"])
def about():
    return render_template("about.html")


@app.route("/privacy", methods=["GET"])
def privacy():
    return render_template("privacy.html")


@app.route("/ads.txt", methods=["GET"])
def ads_txt():
    """AdSense authorized-sellers file. Served only on the ad host when configured."""
    if not ADSENSE_CLIENT or _host() not in AD_HOSTS:
        return "", 404
    pub = ADSENSE_CLIENT.replace("ca-", "", 1)  # ads.txt uses "pub-…", not "ca-pub-…"
    return Response(
        f"google.com, {pub}, DIRECT, f08c47fec0942fa0\n",
        mimetype="text/plain",
    )


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
