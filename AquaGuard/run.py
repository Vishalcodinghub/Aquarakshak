#!/usr/bin/env python3
"""Start AquaGuard: python run.py   (opens the dashboard in your browser)."""
import argparse
import os
import sys

if sys.version_info < (3, 8):
    sys.exit("AquaGuard needs Python 3.8 or newer (you have %s)." % sys.version.split()[0])
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aquaguard.server import serve  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="AquaGuard water-quality dashboard")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    a = ap.parse_args()
    serve(a.host, a.port, not a.no_browser)
