import os
import sys

# Make the project root importable so we can reuse the Flask app in main.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app  # noqa: E402  (import after sys.path tweak)

# Vercel's Python runtime looks for a WSGI callable named `app`.
