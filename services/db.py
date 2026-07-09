#!/usr/bin/env python3
"""db.py

SQLite persistence layer for the TIMEL annotation studio.

Two tables:

- ``decisions``: one row per validated/edited orphan label (identified by a
  sha256 ``content_hash``, see ``services.data.row_key``), storing the
  chosen final TIMEL id, excluded images and validation status.
- ``actions``: an append-only log of every ``set_final`` / ``validate`` /
  ``set_exclusions`` action, used to build the exported action log CSV.

``init_db`` also transparently migrates the legacy schema (where
``content_hash`` used to be a plain ``"branch||label||tm_id"`` string and the
sole primary key) to the current one (auto-increment ``id`` + unique
``content_hash``).
"""

import hashlib
import json
import os
import sqlite3
from typing import Any


def _legacy_content_hash(branch: str, label: str, tm_id: str) -> str:
    """Recompute the sha256 content hash for a legacy-schema row.

    Used only during the one-time migration in :func:`init_db`, to turn an
    old ``"branch||label||tm_id"`` primary key back into its three parts and
    rehash them the same way :func:`services.data.row_key` does.

    :param branch: Value of the ``first_level_timel`` taxonomy branch.
    :type branch: str
    :param label: Value of ``orphan_label``.
    :type label: str
    :param tm_id: Value of ``reconciled_timel_id``.
    :type tm_id: str
    :returns: Hex-encoded sha256 digest of the three fields.
    :rtype: str
    """
    payload = json.dumps([branch, label, tm_id], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _table_columns(cur: sqlite3.Cursor, table: str) -> list:
    """List the column names of a SQLite table.

    :param cur: Open cursor to run the ``PRAGMA`` query on.
    :type cur: sqlite3.Cursor
    :param table: Table name to inspect.
    :type table: str
    :returns: Column names, in declaration order.
    :rtype: list[str]
    """
    cur.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cur.fetchall()]


def _table_exists(cur: sqlite3.Cursor, table: str) -> bool:
    """Check whether a table exists in the database.

    :param cur: Open cursor to query ``sqlite_master`` with.
    :type cur: sqlite3.Cursor
    :param table: Table name to check.
    :type table: str
    :returns: True if the table exists.
    :rtype: bool
    """
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cur.fetchone() is not None


def _migrate_legacy_decisions(cur: sqlite3.Cursor) -> None:
    """Migrate the legacy ``decisions`` schema to the current one.

    The pre-hash schema had ``row_id TEXT PRIMARY KEY`` holding
    ``"branch||label||tm_id"``. This moves to an auto-increment ``id`` plus a
    unique ``content_hash`` (sha256) column, recomputing the hash for every
    existing row from its old ``row_id``.

    :param cur: Open cursor on the target database (part of an outer
        transaction managed by the caller).
    :type cur: sqlite3.Cursor
    :returns: Nothing; mutates the database in place.
    :rtype: None
    """
    cur.execute("ALTER TABLE decisions RENAME TO decisions_legacy")
    cur.execute("""
    CREATE TABLE decisions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content_hash TEXT NOT NULL UNIQUE,
        final_timel_id TEXT NOT NULL,
        excluded_images TEXT NOT NULL DEFAULT '[]',
        validated INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """)
    cur.execute("SELECT row_id, final_timel_id, excluded_images, validated, updated_at FROM decisions_legacy")
    for row_id, final_id, excluded, validated, updated_at in cur.fetchall():
        branch, label, tm_id = (row_id.split("||", 2) + ["", "", ""])[:3]
        h = _legacy_content_hash(branch, label, tm_id)
        cur.execute(
            """
            INSERT INTO decisions(content_hash, final_timel_id, excluded_images, validated, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(content_hash) DO NOTHING;
            """,
            (h, final_id, excluded, validated, updated_at),
        )
    cur.execute("DROP TABLE decisions_legacy")


def _migrate_legacy_actions(cur: sqlite3.Cursor) -> None:
    """Migrate the legacy ``actions`` schema to the current one.

    Same rationale as :func:`_migrate_legacy_decisions`: renames the
    ``row_id`` column to ``content_hash``, recomputed from the old value.

    :param cur: Open cursor on the target database (part of an outer
        transaction managed by the caller).
    :type cur: sqlite3.Cursor
    :returns: Nothing; mutates the database in place.
    :rtype: None
    """
    cur.execute("ALTER TABLE actions RENAME TO actions_legacy")
    cur.execute("""
    CREATE TABLE actions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content_hash TEXT NOT NULL,
        action TEXT NOT NULL,
        final_timel_id TEXT NOT NULL,
        timestamp TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """)
    cur.execute("SELECT row_id, action, final_timel_id, timestamp FROM actions_legacy")
    for row_id, action, final_id, timestamp in cur.fetchall():
        branch, label, tm_id = (row_id.split("||", 2) + ["", "", ""])[:3]
        h = _legacy_content_hash(branch, label, tm_id)
        cur.execute(
            "INSERT INTO actions(content_hash, action, final_timel_id, timestamp) VALUES (?,?,?,?)",
            (h, action, final_id, timestamp),
        )
    cur.execute("DROP TABLE actions_legacy")


def init_db(db_path: str) -> None:
    """Create the SQLite schema if missing, migrating legacy data if needed.

    Safe to call on every app startup: creates the parent directory and the
    ``decisions``/``actions`` tables if absent, and transparently upgrades
    a pre-hash-schema database in place (see
    :func:`_migrate_legacy_decisions` / :func:`_migrate_legacy_actions`).

    :param db_path: Filesystem path to the SQLite database file.
    :type db_path: str
    :returns: Nothing; the database file is created/updated as a side effect.
    :rtype: None
    """
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()

        if _table_exists(cur, "decisions") and "content_hash" not in _table_columns(cur, "decisions"):
            _migrate_legacy_decisions(cur)
        if _table_exists(cur, "actions") and "content_hash" not in _table_columns(cur, "actions"):
            _migrate_legacy_actions(cur)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS decisions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_hash TEXT NOT NULL UNIQUE,
            final_timel_id TEXT NOT NULL,
            excluded_images TEXT NOT NULL DEFAULT '[]',
            validated INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS actions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_hash TEXT NOT NULL,
            action TEXT NOT NULL,
            final_timel_id TEXT NOT NULL,
            timestamp TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """)
        con.commit()
    finally:
        con.close()


def reset_db(db_path: str) -> None:
    """Drop the decisions/actions tables and recreate an empty schema.

    Irreversible: all recorded decisions and the action log are lost. Used
    by the ``flask reset-db`` CLI command (see app.py).

    :param db_path: Filesystem path to the SQLite database file.
    :type db_path: str
    :returns: Nothing; the database file is reset as a side effect.
    :rtype: None
    """
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute("DROP TABLE IF EXISTS decisions")
        cur.execute("DROP TABLE IF EXISTS actions")
        con.commit()
    finally:
        con.close()
    init_db(db_path)


def db_load_all_decisions(db_path: str) -> dict[str, dict[str, Any]]:
    """Load every recorded decision, keyed by content hash.

    :param db_path: Filesystem path to the SQLite database file.
    :type db_path: str
    :returns: Mapping of ``content_hash`` to a dict with keys
        ``final_timel_id`` (str), ``excluded_images`` (str, JSON-encoded
        list) and ``validated`` (bool).
    :rtype: dict[str, dict[str, Any]]
    """
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("SELECT content_hash, final_timel_id, excluded_images, validated FROM decisions")
    rows = cur.fetchall()
    con.close()
    return {
        h: {"final_timel_id": final_id, "excluded_images": excluded_images, "validated": bool(validated)}
        for h, final_id, excluded_images, validated in rows
    }


def db_upsert_and_log(
    db_path: str,
    row_id: str,
    final_timel_id: str,
    excluded_images: str,
    validated: bool,
    action: str,
) -> None:
    """Upsert a decision and append an action log entry in a single transaction.

    :param db_path: Filesystem path to the SQLite database file.
    :type db_path: str
    :param row_id: sha256 content-hash from :func:`services.data.row_key`,
        stored in the ``content_hash`` column (``decisions``/``actions``
        keep their own auto-increment ``id`` as technical primary key).
    :type row_id: str
    :param final_timel_id: Chosen final TIMEL id, or ``"none"`` for a
        free-text (non-taxonomy) label.
    :type final_timel_id: str
    :param excluded_images: JSON-encoded list of image paths excluded from
        this decision.
    :type excluded_images: str
    :param validated: Whether this decision is marked as validated.
    :type validated: bool
    :param action: Action name recorded in the log (``"set_final"``,
        ``"validate"`` or ``"set_exclusions"``).
    :type action: str
    :returns: Nothing; the database is updated as a side effect.
    :rtype: None
    """
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute(
            """
            INSERT INTO decisions(content_hash, final_timel_id, excluded_images, validated)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(content_hash) DO UPDATE SET
                final_timel_id = excluded.final_timel_id,
                excluded_images = excluded.excluded_images,
                validated = excluded.validated,
                updated_at = datetime('now');
            """,
            (row_id, final_timel_id, excluded_images, int(validated)),
        )
        cur.execute(
            "INSERT INTO actions(content_hash, action, final_timel_id) VALUES (?,?,?)",
            (row_id, action, final_timel_id),
        )
        con.commit()
    finally:
        con.close()
