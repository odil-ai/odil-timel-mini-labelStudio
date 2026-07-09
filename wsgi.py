#!/usr/bin/env python3
"""wsgi.py

Production WSGI entry point. `app.py` exposes an application *factory*
(`create_app()`) rather than a module-level `app` object, so a WSGI server
like gunicorn (which expects to import a ready-made `app` callable) needs
this thin wrapper.

Usage: ``gunicorn -w 4 -b 127.0.0.1:8000 wsgi:app`` (see DEPLOY.md).
"""

from app import create_app

app = create_app()
"""The Flask application instance, built once at import time."""
