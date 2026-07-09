#!/usr/bin/env python3
"""data.py

Data loading and lookup helpers used by app.py: reading the input TSV and
the TIMEL taxonomy JSON, mapping old/new image filenames, computing the
stable per-row content hash, merging SQLite decisions back onto the
dataframe, and searching the taxonomy for the autocomplete widget.
"""

import ast
import hashlib
import json
import os
import re
from typing import Any

import pandas as pd

DEFAULT_COLUMNS = [
    "first_level_timel",
    "total_occ_orphan_label",
    "orphan_label",
    "confidence",
    "matched_on",
    "reconciled_label",
    "reconciled_timel_id",
    "images",
]
"""Columns expected in the input TSV; missing ones are added as ``None`` by
:func:`load_initial_df` so downstream code can rely on their presence."""


def safe_parse_list(value: Any) -> list[str]:
    """Best-effort parse of a cell that should contain a Python list literal.

    Handles the TSV's ``images`` / ``excluded_images`` columns, which are
    stored as the string repr of a Python list (e.g. ``"['a.jpg', 'b.jpg']"``).

    :param value: Raw cell value (str, list, NaN or None).
    :type value: Any
    :returns: The parsed list of strings, or an empty list if the value is
        missing/empty, or a single-element list with the stringified value
        if it isn't a valid list literal.
    :rtype: list[str]
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    s = str(value).strip()
    if not s:
        return []
    try:
        x = ast.literal_eval(s)
        if isinstance(x, list):
            return [str(i) for i in x]
    except Exception:
        pass
    return [s]


def normalize_text(s: str) -> str:
    """Lowercase, strip and collapse whitespace for fuzzy/full-text matching.

    :param s: Input string (may be ``None``).
    :type s: str
    :returns: Normalized string, safe to compare/search on.
    :rtype: str
    """
    s = (s or "").lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def load_taxo(path: str) -> dict[str, dict[str, Any]]:
    """Load the TIMEL taxonomy JSON file.

    :param path: Path to the taxonomy JSON file.
    :type path: str
    :returns: Mapping of ``tm-id`` to its taxonomy entry (``pref_label``,
        ``alt_labels``, ...).
    :rtype: dict[str, dict[str, Any]]
    """
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_filename_mapping(path: str) -> dict[str, str]:
    """Load the old/new image filename mapping TSV.

    :param path: Path to the ``mapping_old_new_img_filename.tsv`` file. If
        falsy or missing, an empty mapping is returned (no crash).
    :type path: str
    :returns: Mapping of ``old_img_filename`` to ``new_img_filename``.
    :rtype: dict[str, str]
    """
    if not path or not os.path.exists(path):
        return {}
    m = pd.read_csv(path, sep="\t", encoding="utf-8", dtype=str)
    return dict(zip(m["old_img_filename"], m["new_img_filename"], strict=True))


def enrich_images(images: list[str], filename_map: dict[str, str]) -> list[dict[str, str]]:
    """Pair each image path with its old/new filenames for display.

    :param images: Image paths as stored in the TSV (e.g.
        ``"gahom/012860.jpg"``).
    :type images: list[str]
    :param filename_map: Old-to-new filename mapping, as returned by
        :func:`load_filename_mapping`.
    :type filename_map: dict[str, str]
    :returns: One dict per image with keys ``rel`` (original path),
        ``old_name`` (basename) and ``new_name`` (mapped filename, or
        ``None`` if the old name isn't in the mapping).
    :rtype: list[dict[str, str]]
    """
    out = []
    for rel in images:
        old_name = rel.rsplit("/", 1)[-1]
        out.append({"rel": rel, "old_name": old_name, "new_name": filename_map.get(old_name)})
    return out


def load_initial_df(csv_tsv_path: str) -> pd.DataFrame:
    """Load and normalize the input TSV of orphan labels.

    :param csv_tsv_path: Path to the tab-separated input file (one row per
        orphan label, with its reconciled TIMEL id candidate and associated
        images).
    :type csv_tsv_path: str
    :returns: The loaded dataframe, with any missing
        :data:`DEFAULT_COLUMNS` added as ``None`` and empty/NaN
        ``reconciled_timel_id`` / ``reconciled_label`` filled with
        ``"none"``.
    :rtype: pandas.DataFrame
    """
    df = pd.read_csv(csv_tsv_path, sep="\t", encoding="utf-8")
    for c in DEFAULT_COLUMNS:
        if c not in df.columns:
            df[c] = None
    df["reconciled_timel_id"] = df["reconciled_timel_id"].fillna("none").replace("", "none")
    df["reconciled_label"] = df["reconciled_label"].fillna("none").replace("", "none")
    return df


def row_key(r: pd.Series) -> str:
    """Compute the stable sha256 content hash identifying a dataframe row.

    Used as ``content_hash`` in the ``decisions``/``actions`` SQLite tables.
    Deterministic (stable across restarts) but not sequential — unlike a
    plain ``"||"``-joined string, it can't collide when a field itself
    contains the separator, and it always has a fixed length.

    :param r: A row of the orphan-labels dataframe (must have
        ``first_level_timel``, ``orphan_label`` and ``reconciled_timel_id``).
    :type r: pandas.Series
    :returns: Hex-encoded sha256 digest of the row's identifying fields.
    :rtype: str
    """
    payload = json.dumps(
        [str(r.get("first_level_timel", "")), str(r.get("orphan_label", "")), str(r.get("reconciled_timel_id", ""))],
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def enrich_df_with_decisions(df: pd.DataFrame, taxo: dict, decisions: dict) -> pd.DataFrame:
    """Merge SQLite decisions onto the input dataframe.

    :param df: Base dataframe as returned by :func:`load_initial_df`.
    :type df: pandas.DataFrame
    :param taxo: Taxonomy mapping as returned by :func:`load_taxo`, used to
        resolve the ``final_label`` for each row's chosen ``final_timel_id``.
    :type taxo: dict
    :param decisions: Decisions keyed by content hash, as returned by
        :func:`services.db.db_load_all_decisions`.
    :type decisions: dict
    :returns: A copy of ``df`` with four added columns: ``final_timel_id``,
        ``final_label``, ``validated`` and ``excluded_images``. Rows with no
        matching decision get ``""``/``False``/``"[]"`` defaults.
    :rtype: pandas.DataFrame
    """
    out = df.copy()
    final_id, validated, excluded, final_label = [], [], [], []

    for _, r in out.iterrows():
        k = row_key(r)
        d = decisions.get(k)
        if d:
            fid = d["final_timel_id"]
            v = d["validated"]
            e = d["excluded_images"]
        else:
            fid, v, e = "", False, "[]"

        final_id.append(fid)
        validated.append(v)
        excluded.append(e)

        if fid == "none":
            final_label.append("none")
        elif fid and fid in taxo:
            final_label.append(taxo[fid].get("pref_label", ""))
        else:
            final_label.append("")

    out["final_timel_id"] = final_id
    out["final_label"] = final_label
    out["validated"] = validated
    out["excluded_images"] = excluded
    return out


def build_taxo_index(taxo: dict[str, dict[str, Any]]) -> list[tuple[str, str]]:
    """Build a flat search index over the taxonomy for :func:`taxo_search`.

    :param taxo: Taxonomy mapping as returned by :func:`load_taxo`.
    :type taxo: dict[str, dict[str, Any]]
    :returns: List of ``(tm_id, haystack)`` pairs, where ``haystack`` is the
        normalized concatenation of the id, preferred label and alt labels.
    :rtype: list[tuple[str, str]]
    """
    idx = []
    for tm_id, obj in taxo.items():
        pref = obj.get("pref_label", "") or ""
        alts = obj.get("alt_labels", []) or []
        hay = normalize_text(" | ".join([tm_id, pref] + list(alts)))
        idx.append((tm_id, hay))
    return idx


def taxo_search(q: str, taxo_index, taxo, limit: int = 30):
    """Rank taxonomy entries matching a free-text query.

    Scoring favors id prefix/substring matches (when the query looks like a
    ``tm-`` id), then full-string substring matches, then individual-token
    matches, so that typing a TIMEL id or a partial label surfaces the most
    relevant entries first.

    :param q: User-typed search query.
    :type q: str
    :param taxo_index: Search index as returned by :func:`build_taxo_index`.
    :type taxo_index: list[tuple[str, str]]
    :param taxo: Taxonomy mapping as returned by :func:`load_taxo`, used to
        fetch each candidate's preferred label for display.
    :type taxo: dict
    :param limit: Maximum number of scored results to return (excluding the
        always-present ``"none"`` entry).
    :type limit: int
    :returns: A ``"none"`` entry followed by up to ``limit`` matches, each a
        dict with keys ``id`` and ``label``.
    :rtype: list[dict[str, str]]
    """
    qq = normalize_text(q)
    if not qq:
        return [{"id": "none", "label": "none"}]

    is_id_like = qq.startswith("tm-")
    scored = []
    for tm_id, hay in taxo_index:
        score = 0
        if is_id_like:
            if tm_id.startswith(qq):
                score += 200
            elif qq in tm_id:
                score += 120
        if qq in hay:
            score += 60
        for t in qq.split(" "):
            if t and t in hay:
                score += 5
        if score > 0:
            pref = taxo[tm_id].get("pref_label", "")
            scored.append((score, tm_id, pref))

    scored.sort(reverse=True, key=lambda x: x[0])
    res = [{"id": "none", "label": "none"}]
    for _, tm_id, pref in scored[:limit]:
        res.append({"id": tm_id, "label": f"{tm_id} — {pref}"})
    return res
