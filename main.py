import os
from io import BytesIO
from base64 import b64encode

import qrcode
from qrcode.constants import ERROR_CORRECT_H
from flask import Flask, render_template, request, jsonify, Response

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
app = Flask(__name__, template_folder=TEMPLATE_DIR)

# Keep responses tight and let the browser cache static-ish assets.
app.config["JSON_SORT_KEYS"] = False

# Google AdSense publisher ID (e.g. "ca-pub-1234567890123456"). Set via the
# ADSENSE_CLIENT env var on Vercel. While empty, no ad code is emitted anywhere.
ADSENSE_CLIENT = os.environ.get("ADSENSE_CLIENT", "").strip()


@app.context_processor
def inject_adsense():
    """Make the publisher ID available to every template."""
    return {"adsense_client": ADSENSE_CLIENT}


def make_qr_data_uri(data, fill="#000000", back="#ffffff", box_size=12, border=2):
    """Render `data` into a base64 PNG data URI."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_H,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color=fill, back_color=back)

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return "data:image/png;base64," + b64encode(buffer.getvalue()).decode("ascii")


@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")


@app.route("/api/generate", methods=["POST"])
def generate_api():
    """Smooth path: return the QR as JSON so the page never reloads."""
    payload = request.get_json(silent=True) or request.form
    data = (payload.get("link") or "").strip()
    if not data:
        return jsonify({"error": "Please enter a link or some text."}), 400

    fill = payload.get("fill") or "#000000"
    back = payload.get("back") or "#ffffff"

    try:
        image = make_qr_data_uri(data, fill=fill, back=back)
    except Exception as exc:  # noqa: BLE001 - surface a friendly error to the client
        return jsonify({"error": f"Could not generate QR code: {exc}"}), 400

    return jsonify({"image": image, "data": data})


@app.route("/", methods=["POST"])
def generate_form():
    """Backwards-compatible no-JS fallback that re-renders the page."""
    data = (request.form.get("link") or "").strip()
    image = make_qr_data_uri(data) if data else None
    return render_template("index.html", data=image, link=data)


@app.route("/about", methods=["GET"])
def about():
    return render_template("about.html")


@app.route("/privacy", methods=["GET"])
def privacy():
    return render_template("privacy.html")


@app.route("/ads.txt", methods=["GET"])
def ads_txt():
    """AdSense authorized-sellers file. Served only once a publisher ID is set."""
    if not ADSENSE_CLIENT:
        return "", 404
    pub = ADSENSE_CLIENT.replace("ca-", "", 1)  # ads.txt uses "pub-…", not "ca-pub-…"
    return Response(
        f"google.com, {pub}, DIRECT, f08c47fec0942fa0\n",
        mimetype="text/plain",
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
