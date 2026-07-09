#!/usr/bin/env python3
"""config.py

Application configuration, populated from environment variables (loaded
from `.dev.env` / `.env` by app.py before this module is imported).

Every setting uses `os.environ.get("X") or "default"` rather than the
two-argument form of `os.environ.get`, so that a variable present but left
empty in `.env`/`.dev.env` (e.g. `DB_PATH=`) falls back to its default
instead of resolving to an empty string (which would crash things like
`os.makedirs("")`).
"""

import os


class Config:
    """Flask configuration object, exposed as ``app.config`` after
    ``app.config.from_object(Config)`` in ``create_app()``.

    Every attribute is a plain class attribute (no instance needed) so Flask
    can read them directly as ``app.config["KEY"]``.
    """

    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-secret"
    """Flask session signing key. Must be overridden in `.env`/`.dev.env`;
    app.py refuses to start while this is left at the "dev-secret" default."""

    APP_PASSWORD = os.environ.get("APP_PASSWORD") or ""
    """Single shared password gating access to the whole app (see
    `login_post` in app.py). Required — app.py refuses to start if empty."""

    IMAGES_ROOT = os.environ.get("IMAGES_ROOT") or ""
    """Optional local root directory used as a fallback image source (via
    the `/image/<rel>` route) for images not covered by `IMAGE_ENDPOINT` /
    `FILENAME_MAP_PATH`. Left empty, the fallback route just 404s."""

    TAXO_PATH = os.environ.get("TAXO_PATH") or "data/timel-taxonomy_enriched.json"
    """Path to the TIMEL taxonomy JSON file (`tm-id -> {pref_label, ...}`)."""

    DB_PATH = os.environ.get("DB_PATH") or "data/timel_reconcile.sqlite"
    """Path to the SQLite database storing decisions and the action log."""

    CSV_TSV_PATH = os.environ.get("CSV_TSV_PATH") or "data/reconcile_timel_prepared.csv"
    """Path to the input TSV: one row per orphan label, with its
    reconciled TIMEL id candidate and the list of associated images."""

    FILENAME_MAP_PATH = os.environ.get("FILENAME_MAP_PATH") or "data/mapping_old_new_img_filename.tsv"
    """Path to the TSV mapping old (gahom) image filenames to their new
    (ODIL/IIIF) filenames."""

    IMAGE_ENDPOINT = os.environ.get("IMAGE_ENDPOINT") or ""
    """Base URL of the IIIF server used to display images by their new
    filename, e.g. `{IMAGE_ENDPOINT}/{new_name}/full/full/0/default.jpg`."""

    EXPORT_SNAPSHOT = os.environ.get("EXPORT_SNAPSHOT") or "export_snapshot.csv"
    """Filename used for the decisions CSV inside the export ZIP."""

    EXPORT_LOG = os.environ.get("EXPORT_LOG") or "export_log.csv"
    """Filename used for the action log CSV inside the export ZIP."""
