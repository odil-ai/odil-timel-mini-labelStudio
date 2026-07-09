#!/usr/bin/env python3
"""app.py

Flask application for the TIMEL annotation studio: a single-password web
tool letting annotators review automatic reconciliations between "orphan
labels" and TIMEL taxonomy entries, exclude irrelevant images, validate
decisions, and export the results (CSV snapshot, action log, and a
per-image validated-annotations JSON).

Routes are registered inside the :func:`create_app` factory so that shared
state (the loaded dataframe, taxonomy, filename mapping, and a tiny
in-process cache) stays in closure scope rather than as globals.
"""

import hashlib
import io
import json
import sqlite3
import zipfile
from datetime import datetime
from functools import wraps
from pathlib import Path
from werkzeug.middleware.proxy_fix import ProxyFix

from dotenv import load_dotenv

# .dev.env (local dev override) is loaded first: override=False then
# protects its values from being overwritten by .env (shared/base config).
_app_dir = Path(__file__).resolve().parent
for _env_name in (".dev.env", ".env"):
    _env_path = _app_dir / _env_name
    if _env_path.exists():
        load_dotenv(_env_path, override=False)

import click  # noqa: E402 (must come after the .env loading above)
import pandas as pd  # noqa: E402
from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, session, url_for  # noqa: E402

from config import Config  # noqa: E402
from services.data import (  # noqa: E402
    build_taxo_index,
    enrich_df_with_decisions,
    enrich_images,
    load_filename_mapping,
    load_initial_df,
    load_taxo,
    normalize_text,
    row_key,
    safe_parse_list,
    taxo_search,
)
from services.db import db_load_all_decisions, db_upsert_and_log, init_db, reset_db  # noqa: E402


def with_app_prefix(path: str) -> str:
    """Prepend the configured ``APP_PREFIX`` to a root-relative path.

    Mirrors ``withPrefix()`` in ``static/app.js``. Needed anywhere a
    redirect target is built from a raw path (e.g. ``request.path``, or a
    hardcoded ``"/correction"`` default) instead of via :func:`flask.url_for`
    — ``url_for`` already accounts for the reverse-proxy prefix through
    ``ProxyFix``/``SCRIPT_NAME``, but a raw path doesn't.

    :param path: A root-relative path, e.g. ``"/correction"``.
    :type path: str
    :returns: The path with ``Config.APP_PREFIX`` prepended (unchanged if
        the prefix isn't configured or ``path`` isn't root-relative).
    :rtype: str
    """
    if not Config.APP_PREFIX or not path.startswith("/"):
        return path
    return Config.APP_PREFIX + path


def login_required(view):
    """Redirect anonymous users to the login page for full HTML routes.

    :param view: The Flask view function to protect.
    :type view: Callable
    :returns: The wrapped view, which redirects to ``/login`` (preserving
        the originally requested path via ``?next=``) when the session
        isn't authenticated.
    :rtype: Callable
    """

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("auth_ok"):
            return redirect(url_for("login", next=with_app_prefix(request.path)))
        return view(*args, **kwargs)

    return wrapped


def api_login_required(view):
    """Return a 401 JSON error for anonymous requests to JSON API routes.

    :param view: The Flask view function to protect.
    :type view: Callable
    :returns: The wrapped view, which short-circuits with
        ``{"ok": False, "error": "unauthorized"}`` (HTTP 401) when the
        session isn't authenticated.
    :rtype: Callable
    """

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("auth_ok"):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        return view(*args, **kwargs)

    return wrapped


def create_app():
    """Build and configure the Flask application.

    Loads configuration, the taxonomy, the input dataframe and the
    filename mapping once at startup; registers the ``reset-db`` CLI
    command and every HTTP route as closures over that shared state.

    :returns: The configured Flask application, ready to be run or
        imported by the Flask CLI (``flask --app app run``).
    :rtype: flask.Flask
    """
    app = Flask(
        __name__,
        static_url_path='',
        static_folder='static',
        template_folder='templates'
    )
    app.config.from_object(Config)

    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1, x_proto=1, x_host=1, x_prefix=1
    )

    app.jinja_env.globals["APP_PREFIX"] = app.config["APP_PREFIX"]

    app.jinja_env.globals["BRANCH_LABELS"] = {
        "timel_character": "Personnage",
        "timel_nature_place": "Nature / Lieu",
        "timel_object_architecture": "Objet / Architecture",
        "timel_subject": "Sujet",
        "timel_thema": "Thème",
    }

    if not app.config.get("SECRET_KEY") or app.config["SECRET_KEY"] == "dev-secret":
        raise RuntimeError("SECRET_KEY must be set in the environment — add it to your .env file.")
    if not app.config.get("APP_PASSWORD"):
        raise RuntimeError("APP_PASSWORD must be set in the environment — add it to your .env file.")

    init_db(app.config["DB_PATH"])

    @app.cli.command("reset-db")
    @click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
    def reset_db_command(yes):
        """Flask CLI command: wipe all decisions and the action log.

        Usage: ``flask --app app reset-db [--yes]``.

        :param yes: When True, skip the interactive confirmation prompt
            (useful for scripting/CI).
        :type yes: bool
        :returns: Nothing; prints a confirmation message to stdout.
        :rtype: None
        """
        db_path = app.config["DB_PATH"]
        if not yes:
            click.confirm(
                f"This will delete ALL decisions and the action log ({db_path}). Continue?",
                abort=True,
            )
        reset_db(db_path)
        click.echo(f"Database reset: {db_path}")
        click.echo("Restart the app if it's already running (its in-memory cache still holds the old decisions).")

    taxo = load_taxo(app.config["TAXO_PATH"])
    taxo_index = build_taxo_index(taxo)
    df = load_initial_df(app.config["CSV_TSV_PATH"])
    filename_map = load_filename_mapping(app.config["FILENAME_MAP_PATH"])

    # Cache invalidated on every write; avoids reloading SQLite + re-enriching on every request
    _cache = {"seq": -1, "decisions": None, "df_enriched": None}
    _write_seq = [0]

    def invalidate():
        """Bump the write counter so the next :func:`compute_state` call
        reloads decisions from SQLite instead of serving the stale cache.

        :returns: Nothing.
        :rtype: None
        """
        _write_seq[0] += 1

    def with_image_src(images):
        """Resolve each image's display URL.

        Prefers the IIIF endpoint (using the new/ODIL filename) when both
        ``IMAGE_ENDPOINT`` is configured and a mapped filename is known;
        otherwise falls back to the local ``/image/<rel>`` route (old
        gahom filename).

        :param images: Image dicts as returned by
            :func:`services.data.enrich_images` (each with ``rel``,
            ``old_name``, ``new_name``).
        :type images: list[dict]
        :returns: The same dicts, each with an added ``src`` key holding
            the resolved display URL.
        :rtype: list[dict]
        """
        endpoint = app.config["IMAGE_ENDPOINT"].rstrip("/")
        out = []
        for img in images:
            if endpoint and img["new_name"]:
                src = f"{endpoint}/{img['new_name']}/full/full/0/default.jpg"
            else:
                src = url_for("image", rel=img["rel"])
            out.append({**img, "src": src})
        return out

    def compute_state():
        """Return the current decisions and decision-enriched dataframe,
        recomputing only when a write has invalidated the cache.

        :returns: A ``(decisions, df_enriched)`` tuple, where ``decisions``
            is the dict from
            :func:`services.db.db_load_all_decisions` and ``df_enriched``
            is the dataframe from
            :func:`services.data.enrich_df_with_decisions`.
        :rtype: tuple[dict, pandas.DataFrame]
        """
        if _cache["seq"] == _write_seq[0]:
            return _cache["decisions"], _cache["df_enriched"]
        decisions = db_load_all_decisions(app.config["DB_PATH"])
        df_enriched = enrich_df_with_decisions(df, taxo, decisions)
        _cache.update(seq=_write_seq[0], decisions=decisions, df_enriched=df_enriched)
        return decisions, df_enriched

    def compute_stats(df_enriched):
        """Compute overall and per-branch validation progress.

        :param df_enriched: Decision-enriched dataframe (must have a
            ``validated`` column and a ``first_level_timel`` column).
        :type df_enriched: pandas.DataFrame
        :returns: A ``(stats, per_branch)`` tuple: ``stats`` is
            ``{"total": int, "done": int}`` for the whole dataset;
            ``per_branch`` is a list of per-branch records with
            ``first_level_timel``, ``total``, ``done`` and ``pct`` keys.
        :rtype: tuple[dict, list[dict]]
        """
        total = len(df_enriched)
        done = int(df_enriched["validated"].astype(bool).sum())
        per = (
            df_enriched.groupby("first_level_timel", dropna=False)["validated"]
            .agg(total="count", done=lambda s: int(pd.Series(s).astype(bool).sum()))
            .reset_index()
        )
        per["pct"] = per.apply(lambda r: (r["done"] / r["total"] * 100.0) if r["total"] else 0.0, axis=1)
        return {"total": total, "done": done}, per.to_dict(orient="records")

    def taxo_pref_label(tm_id: str) -> str:
        """Resolve a TIMEL id to its preferred label.

        :param tm_id: A ``tm-...`` id, ``"none"`` (free label) or falsy.
        :type tm_id: str
        :returns: ``"none"`` if ``tm_id`` is ``"none"``, ``""`` if falsy or
            unknown, otherwise the taxonomy's ``pref_label`` for that id.
        :rtype: str
        """
        if not tm_id or tm_id == "none":
            return "none" if tm_id == "none" else ""
        return (taxo.get(tm_id) or {}).get("pref_label", "")

    @app.get("/login")
    def login():
        """Render the login page (GET /login).

        Redirects to ``/correction`` if the session is already
        authenticated.

        :returns: The rendered login page, or a redirect.
        :rtype: flask.Response
        """
        if session.get("auth_ok"):
            return redirect(url_for("correction"))
        next_url = request.args.get("next", with_app_prefix("/correction"))
        return render_template("login.html", next=next_url, error=None)

    @app.post("/login")
    def login_post():
        """Handle the login form submission (POST /login).

        Reads ``password`` and ``next`` from the form body; on success,
        marks the session authenticated and redirects to ``next``.

        :returns: A redirect on success, or the login page re-rendered
            with an error message on failure.
        :rtype: flask.Response
        """
        pwd = (request.form.get("password") or "").strip()
        next_url = request.form.get("next") or with_app_prefix("/correction")

        if pwd == app.config["APP_PASSWORD"]:
            session["auth_ok"] = True
            return redirect(next_url)

        return render_template("login.html", next=next_url, error="Mot de passe incorrect.")

    @app.get("/logout")
    def logout():
        """Clear the session and redirect to the login page (GET /logout).

        :returns: A redirect to ``/login``.
        :rtype: flask.Response
        """
        session.clear()
        return redirect(url_for("login"))

    @app.get("/image/<path:rel>")
    def image(rel):
        """Serve a local image file as a fallback source (GET /image/<rel>).

        Only used for images not covered by the IIIF endpoint / filename
        mapping (see :func:`with_image_src`). Returns 404 if
        ``IMAGES_ROOT`` isn't configured, or if the resolved path escapes
        ``IMAGES_ROOT`` or doesn't exist (path-traversal guard).

        :param rel: Requested image path, e.g. ``"gahom/012860.jpg"``.
        :type rel: str
        :returns: The image file, or a 404 response.
        :rtype: flask.Response
        """
        if not app.config["IMAGES_ROOT"]:
            abort(404)
        root = Path(app.config["IMAGES_ROOT"]).resolve()
        rel2 = rel.replace("gahom/", "")
        p = (root / rel2).resolve()
        if not str(p).startswith(str(root)) or not p.exists():
            abort(404)
        return send_file(p)

    @app.get("/assets/<path:filename>")
    def assets(filename):
        """Serve a static file from the project's ``assets/`` directory
        (GET /assets/<filename>), e.g. institutional logos.

        Guards against path traversal the same way as :func:`image`.

        :param filename: Requested asset filename, e.g.
            ``"logo-banner-enc.png"``.
        :type filename: str
        :returns: The asset file, or a 404 response.
        :rtype: flask.Response
        """
        root = (Path(__file__).resolve().parent / "assets").resolve()
        p = (root / filename).resolve()
        if not str(p).startswith(str(root)) or not p.exists():
            abort(404)
        return send_file(p)

    @app.get("/")
    def home():
        """Redirect the site root to the correction view (GET /).

        :returns: A redirect to ``/correction``.
        :rtype: flask.Response
        """
        return redirect(url_for("correction"))

    @app.get("/table")
    @login_required
    def table():
        """Render the tabular view of all rows (GET /table).

        Supports filtering by free-text search (``q``), pending-only
        (``only_pending``), confidence level (``conf``, repeatable) and
        taxonomy branch (``br``, repeatable).

        :returns: The rendered table page.
        :rtype: flask.Response
        """
        decisions, df_enriched = compute_state()

        q = request.args.get("q", "").strip()
        only_pending = request.args.get("only_pending", "0") == "1"
        confs = request.args.getlist("conf") or ["HIGH", "MEDIUM", "LOW", "NONE"]
        br = request.args.getlist("br")

        dff = df_enriched.copy()
        if confs:
            dff = dff[dff["confidence"].isin(confs)]
        if br:
            dff = dff[dff["first_level_timel"].isin(br)]
        if only_pending:
            dff = dff[~dff["validated"].astype(bool)]

        if q:
            qq = normalize_text(q)

            def row_text(r):
                """Build the normalized haystack used for full-text search
                on a single row.

                :param r: A row of the enriched dataframe.
                :type r: pandas.Series
                :returns: Normalized ``" | "``-joined searchable fields.
                :rtype: str
                """
                fields = [
                    r.get("orphan_label", ""),
                    r.get("reconciled_label", ""),
                    r.get("reconciled_timel_id", ""),
                    r.get("final_label", ""),
                    r.get("final_timel_id", ""),
                ]
                return normalize_text(" | ".join([str(x) for x in fields]))

            mask = dff.apply(lambda r: qq in row_text(r), axis=1)
            dff = dff[mask]

        stats, per_branch = compute_stats(df_enriched)
        dff = dff.copy()
        dff["idx"] = dff.index.astype(int)
        rows = dff.to_dict(orient="records")
        branches = sorted(df_enriched["first_level_timel"].dropna().unique().tolist())

        return render_template(
            "table.html",
            rows=rows,
            stats=stats,
            per_branch=per_branch,
            branches=branches,
            filters={"q": q, "only_pending": only_pending, "confs": confs, "br": br},
        )

    @app.get("/correction")
    @login_required
    def correction():
        """Render the row-by-row correction view (GET /correction).

        Resolves the current cursor position from (in priority order) the
        ``idx`` query param (absolute dataframe row index, used when
        navigating in from the table view), the ``cursor`` query param, or
        the session's last cursor. Supports the same ``pending``/``conf``/
        ``br`` filters as :func:`table`.

        :returns: The rendered correction page (or an "empty" state page
            if no row matches the current filters).
        :rtype: flask.Response
        """
        decisions, df_enriched = compute_state()

        show_only_pending = request.args.get("pending", "1") == "1"
        confs = request.args.getlist("conf") or ["HIGH", "MEDIUM", "LOW", "NONE"]
        br = request.args.get("br", "(toutes)")
        cursor = int(request.args.get("cursor", session.get("cursor", 0)))
        target_idx = request.args.get("idx")
        if target_idx is not None:
            try:
                target_idx = int(target_idx)
            except Exception:
                target_idx = None

        filtered = []
        for idx, r in df.iterrows():
            if confs and str(r.get("confidence")) not in confs:
                continue
            if br != "(toutes)" and str(r.get("first_level_timel")) != br:
                continue
            k = row_key(r)
            d = decisions.get(k)
            if show_only_pending and d and d["validated"]:
                continue
            filtered.append((idx, r, k, d))

        # Resolve target_idx -> cursor position (must happen after `filtered` is built)
        if target_idx is not None:
            for pos, (idx, _r, _k, _d) in enumerate(filtered):
                if int(idx) == target_idx:
                    cursor = pos
                    break

        if not filtered:
            return render_template("correction.html", empty=True, has_decision=False, is_validated=False)

        cursor = max(0, min(cursor, len(filtered) - 1))
        session["cursor"] = cursor

        _, row, key, decision = filtered[cursor]
        images_list = with_image_src(enrich_images(safe_parse_list(row.get("images"))[:25], filename_map))
        excluded_list = safe_parse_list(decision["excluded_images"]) if decision else []

        current_final_id = decision["final_timel_id"] if decision else str(row.get("reconciled_timel_id", "none"))
        current_final_label = taxo_pref_label(current_final_id)

        stats, per_branch = compute_stats(df_enriched)
        branches = sorted(df["first_level_timel"].dropna().unique().tolist())

        return render_template(
            "correction.html",
            has_decision=bool(decision),
            is_validated=bool(decision and decision.get("validated")),
            empty=False,
            row=row.to_dict(),
            key=key,
            cursor=cursor,
            nrows=len(filtered),
            images_list=images_list,
            excluded_list=excluded_list,
            current_final_id=current_final_id,
            current_final_label=current_final_label,
            branches=branches,
            stats=stats,
            per_branch=per_branch,
            filters={"pending": show_only_pending, "confs": confs, "br": br},
        )

    @app.get("/api/correction/row")
    @api_login_required
    def api_correction_row():
        """JSON API: fetch a single row by cursor (GET /api/correction/row).

        Used by the frontend to move between rows (prev/next/goto) without
        a full page reload. Accepts the same ``cursor``/``pending``/
        ``conf``/``br`` query params as :func:`correction`, but resolves
        the cursor purely from the ``cursor`` param (no ``idx``/session
        fallback).

        :returns: JSON payload mirroring the data passed to the
            ``correction.html`` template, or
            ``{"ok": True, "empty": True, ...}`` if no row matches.
        :rtype: flask.Response
        """
        decisions, df_enriched = compute_state()

        show_only_pending = request.args.get("pending", "1") == "1"
        confs = request.args.getlist("conf") or ["HIGH", "MEDIUM", "LOW", "NONE"]
        br = request.args.get("br", "(toutes)")
        cursor = int(request.args.get("cursor", 0))

        filtered = []
        for _, r in df.iterrows():
            if confs and str(r.get("confidence")) not in confs:
                continue
            if br != "(toutes)" and str(r.get("first_level_timel")) != br:
                continue
            k = row_key(r)
            d = decisions.get(k)
            if show_only_pending and d and d["validated"]:
                continue
            filtered.append((r, k, d))

        stats, per_branch = compute_stats(df_enriched)

        if not filtered:
            return jsonify({"ok": True, "empty": True, "stats": stats, "per_branch": per_branch})

        cursor = max(0, min(cursor, len(filtered) - 1))
        row, key, decision = filtered[cursor]

        images_list = with_image_src(enrich_images(safe_parse_list(row.get("images"))[:25], filename_map))
        excluded_list = safe_parse_list(decision["excluded_images"]) if decision else []

        current_final_id = decision["final_timel_id"] if decision else str(row.get("reconciled_timel_id", "none"))

        return jsonify(
            {
                "ok": True,
                "empty": False,
                "cursor": cursor,
                "nrows": len(filtered),
                "key": key,
                "row": row.to_dict(),
                "images_list": images_list,
                "excluded_list": excluded_list,
                "current_final_id": current_final_id,
                "current_final_label": taxo_pref_label(current_final_id),
                "has_decision": bool(decision),
                "is_validated": bool(decision and decision.get("validated")),
                "stats": stats,
                "per_branch": per_branch,
            }
        )

    @app.get("/api/taxo_search")
    @api_login_required
    def api_taxo_search():
        """JSON API: search the taxonomy (GET /api/taxo_search?q=...).

        :returns: JSON list of matches, as produced by
            :func:`services.data.taxo_search`.
        :rtype: flask.Response
        """
        q = request.args.get("q", "")
        return jsonify(taxo_search(q, taxo_index, taxo, limit=30))

    @app.post("/api/decision/set_final")
    @api_login_required
    def api_set_final():
        """JSON API: set the final TIMEL id for a row (POST /api/decision/set_final).

        Expects a JSON body with ``row_id``, ``final_timel_id``, and
        optionally ``excluded_images_json`` / ``validated``. Does not mark
        the row as validated unless ``validated`` is explicitly true.

        :returns: ``{"ok": True, "final_timel_id": ..., "pref_label": ...}``.
        :rtype: flask.Response
        """
        payload = request.get_json(force=True)
        row_id = payload["row_id"]
        final_id = payload["final_timel_id"]
        excluded = payload.get("excluded_images_json", "[]")
        validated = bool(payload.get("validated", False))

        db_upsert_and_log(app.config["DB_PATH"], row_id, final_id, excluded, validated, "set_final")
        invalidate()
        return jsonify({"ok": True, "final_timel_id": final_id, "pref_label": taxo_pref_label(final_id)})

    @app.post("/api/decision/validate")
    @api_login_required
    def api_validate():
        """JSON API: validate a row's decision (POST /api/decision/validate).

        Expects a JSON body with ``row_id``, ``final_timel_id``, and
        optionally ``excluded_images_json``. Always marks the row as
        validated.

        :returns: ``{"ok": True, "final_timel_id": ..., "pref_label": ...}``.
        :rtype: flask.Response
        """
        payload = request.get_json(force=True)
        row_id = payload["row_id"]
        final_id = payload["final_timel_id"]
        excluded = payload.get("excluded_images_json", "[]")

        db_upsert_and_log(app.config["DB_PATH"], row_id, final_id, excluded, True, "validate")
        invalidate()
        return jsonify({"ok": True, "final_timel_id": final_id, "pref_label": taxo_pref_label(final_id)})

    @app.post("/api/decision/set_exclusions")
    @api_login_required
    def api_set_exclusions():
        """JSON API: update excluded images for a row
        (POST /api/decision/set_exclusions).

        Expects a JSON body with ``row_id``, ``final_timel_id``,
        ``excluded_images_json`` and optionally ``validated``.

        :returns: ``{"ok": True}``.
        :rtype: flask.Response
        """
        payload = request.get_json(force=True)
        row_id = payload["row_id"]
        final_id = payload["final_timel_id"]
        excluded = payload.get("excluded_images_json", "[]")
        validated = bool(payload.get("validated", False))

        db_upsert_and_log(app.config["DB_PATH"], row_id, final_id, excluded, validated, "set_exclusions")
        invalidate()
        return jsonify({"ok": True})

    def build_export_buffers():
        """Build the two CSV buffers for the export ZIP.

        :returns: A ``(snapshot_csv, log_csv)`` tuple of CSV strings:
            ``snapshot_csv`` is the full input dataframe with the current
            decision columns merged in; ``log_csv`` is the full
            chronological action log.
        :rtype: tuple[str, str]
        """
        decisions = db_load_all_decisions(app.config["DB_PATH"])
        out = df.copy()

        finals, excls, vals, final_labels = [], [], [], []
        for _, r in out.iterrows():
            k = row_key(r)
            d = decisions.get(k)
            if d:
                ft = d["final_timel_id"]
                finals.append(ft)
                excls.append(d["excluded_images"])
                vals.append(d["validated"])
            else:
                finals.append("")
                excls.append("[]")
                vals.append(False)

            ft = finals[-1]
            if ft == "none":
                final_labels.append("none")
            elif ft and ft in taxo:
                final_labels.append(taxo[ft].get("pref_label", ""))
            else:
                final_labels.append("")

        out["final_timel_id"] = finals
        out["final_label"] = final_labels
        out["excluded_images"] = excls
        out["validated"] = vals

        snap_buf = io.StringIO()
        out.to_csv(snap_buf, index=False, encoding="utf-8")

        con = sqlite3.connect(app.config["DB_PATH"])
        log_df = pd.read_sql_query(
            "SELECT content_hash, action, final_timel_id, timestamp FROM actions ORDER BY id ASC", con
        )
        con.close()
        log_buf = io.StringIO()
        log_df.to_csv(log_buf, index=False, encoding="utf-8")

        return snap_buf.getvalue(), log_buf.getvalue()

    def build_validated_annotations_json():
        """Build the ``validated_annotations.json`` export payload.

        One entry per image referenced by at least one validated decision,
        aggregating every validated TIMEL id (``validated_annotations``)
        and every validated free-text label (``free_labels``, i.e.
        validated with final id ``"none"``) across all rows that include
        that image.

        :returns: JSON string with keys ``total_images`` (int),
            ``total_validated_annotations`` (int, sum of each image's
            ``validated_annotations`` count) and ``images`` (list of
            per-image dicts with ``sha``, ``gahom_filename``,
            ``odil_filename``, ``total_validated_annotations``,
            ``validated_annotations`` and ``free_labels``).
        :rtype: str
        """
        decisions, _ = compute_state()
        images_map = {}

        for _, r in df.iterrows():
            d = decisions.get(row_key(r))
            if not d or not d["validated"]:
                continue

            fid = d["final_timel_id"]
            for rel in safe_parse_list(r.get("images")):
                old_name = rel.rsplit("/", 1)[-1]
                new_name = filename_map.get(old_name)

                entry = images_map.get(old_name)
                if entry is None:
                    sha = hashlib.sha256(
                        json.dumps([old_name, new_name or ""], ensure_ascii=False).encode("utf-8")
                    ).hexdigest()
                    entry = {
                        "sha": sha,
                        "gahom_filename": old_name,
                        "odil_filename": new_name or "",
                        "validated_annotations": [],
                        "free_labels": [],
                        "_tm_ids": set(),
                    }
                    images_map[old_name] = entry

                if fid and fid != "none":
                    if fid not in entry["_tm_ids"]:
                        entry["_tm_ids"].add(fid)
                        entry["validated_annotations"].append(
                            {
                                "timel_id": fid,
                                "timel_label": taxo.get(fid, {}).get("pref_label", ""),
                            }
                        )
                else:
                    free_label = str(r.get("orphan_label", ""))
                    if free_label and free_label not in entry["free_labels"]:
                        entry["free_labels"].append(free_label)

        images = []
        total_validated_annotations = 0
        for entry in images_map.values():
            total_validated_annotations += len(entry["validated_annotations"])
            images.append(
                {
                    "sha": entry["sha"],
                    "gahom_filename": entry["gahom_filename"],
                    "odil_filename": entry["odil_filename"],
                    "total_validated_annotations": len(entry["validated_annotations"]),
                    "validated_annotations": entry["validated_annotations"],
                    "free_labels": entry["free_labels"],
                }
            )

        result = {
            "total_images": len(images),
            "total_validated_annotations": total_validated_annotations,
            "images": images,
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    @app.post("/export")
    @api_login_required
    def export():
        """JSON API: build the export buffers without downloading
        (POST /export).

        Exists mainly to let the frontend trigger/validate export
        generation without transferring the ZIP; the actual file is
        fetched separately via :func:`export_download`.

        :returns: ``{"ok": True}``.
        :rtype: flask.Response
        """
        build_export_buffers()
        return jsonify({"ok": True})

    @app.get("/export/download")
    @login_required
    def export_download():
        """Download the full export as a ZIP file (GET /export/download).

        Bundles ``export_snapshot.csv``, ``export_log.csv`` and
        ``validated_annotations.json`` into a single ZIP, named with the
        current timestamp.

        :returns: The ZIP file as an attachment.
        :rtype: flask.Response
        """
        snap_csv, log_csv = build_export_buffers()
        validated_json = build_validated_annotations_json()

        mem = io.BytesIO()
        with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("export_snapshot.csv", snap_csv)
            z.writestr("export_log.csv", log_csv)
            z.writestr("validated_annotations.json", validated_json)
        mem.seek(0)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return send_file(
            mem,
            as_attachment=True,
            download_name=f"timel_export_{timestamp}.zip",
            mimetype="application/zip",
        )

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
