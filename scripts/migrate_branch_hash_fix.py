#!/usr/bin/env python3
"""migrate_branch_hash_fix.py

One-time migration for the "mauvaise branche" fix: correcting a row's
`first_level_timel` in data/reconcile_timel_prepared.csv changes its
content_hash (see services.data.row_key), which would silently orphan any
existing decision for that row. This script diffs the pre-fix CSV snapshot
against the current one to find every row whose branch changed, and re-keys
the matching decision in the live SQLite DB so existing annotator work stays
attached to the corrected row.

Run this on the server, against its own live database, right after
deploying the corrected CSV — do not run it against a stale local copy of
the database, it needs to see whatever decisions actually exist in
production right now.

Safe to re-run: once a decision has been migrated (or dropped on
collision), its old hash no longer exists in `decisions`, so a second run
finds nothing left to do.

Usage:
    python3 scripts/migrate_branch_hash_fix.py           # dry run (prints only)
    python3 scripts/migrate_branch_hash_fix.py --yes      # applies the changes
"""

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OLD_CSV = BASE / "data" / "reconcile_timel_prepared.csv.bak-20260818-173641"
NEW_CSV = BASE / "data" / "reconcile_timel_prepared.csv"
DB_PATH = BASE / "data" / "timel_reconcile.sqlite"


def row_key(first_level_timel: str, orphan_label: str, reconciled_timel_id: str) -> str:
    """Recompute the sha256 content hash the same way services.data.row_key does.

    :param first_level_timel: Branch slug.
    :type first_level_timel: str
    :param orphan_label: The row's orphan_label.
    :type orphan_label: str
    :param reconciled_timel_id: The row's reconciled_timel_id.
    :type reconciled_timel_id: str
    :returns: Hex-encoded sha256 digest.
    :rtype: str
    """
    payload = json.dumps([str(first_level_timel), str(orphan_label), str(reconciled_timel_id)], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> None:
    """Diff the old/new CSV snapshots and migrate affected decisions.

    :returns: Nothing; exits with a non-zero status on unrecoverable input
        errors (missing snapshot, row count mismatch).
    :rtype: None
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="Apply changes (default: dry run, prints only)")
    args = parser.parse_args()

    if not OLD_CSV.exists():
        sys.exit(f"Missing {OLD_CSV} — can't diff branches without the pre-fix snapshot.")
    if not NEW_CSV.exists():
        sys.exit(f"Missing {NEW_CSV}.")
    if not DB_PATH.exists():
        sys.exit(f"Missing {DB_PATH}.")

    with open(OLD_CSV, encoding="utf-8", newline="") as f:
        old_rows = list(csv.DictReader(f, delimiter="\t"))
    with open(NEW_CSV, encoding="utf-8", newline="") as f:
        new_rows = list(csv.DictReader(f, delimiter="\t"))

    if len(old_rows) != len(new_rows):
        sys.exit(
            f"Row count mismatch (old={len(old_rows)}, new={len(new_rows)}) "
            "— refusing to guess row alignment, stopping without changes."
        )

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT content_hash FROM decisions")
    decision_hashes = {r[0] for r in cur.fetchall()}

    migrated = 0
    dropped_collisions = []

    for old, new in zip(old_rows, new_rows):
        old_branch = old["first_level_timel"]
        new_branch = new["first_level_timel"]
        if old_branch == new_branch:
            continue

        label = new["orphan_label"]
        tid = new["reconciled_timel_id"]
        old_hash = row_key(old_branch, label, tid)
        new_hash = row_key(new_branch, label, tid)

        if old_hash not in decision_hashes:
            continue

        prefix = "[DRY RUN] " if not args.yes else ""
        if new_hash in decision_hashes:
            # Two CSV rows collapsed onto the same (label, tm-id) once the
            # branch was fixed (duplicate source rows); both already have a
            # decision. Keep whichever is already at new_hash — it's the
            # one under the now-correct branch — and drop the other.
            print(f"{prefix}collision, dropping duplicate: {label!r} ({tid}) {old_branch} -> {new_branch}")
            if args.yes:
                cur.execute("DELETE FROM decisions WHERE content_hash = ?", (old_hash,))
            dropped_collisions.append((label, tid))
            continue

        print(f"{prefix}migrate: {label!r} ({tid}) {old_branch} -> {new_branch}")
        if args.yes:
            cur.execute("UPDATE decisions SET content_hash = ? WHERE content_hash = ?", (new_hash, old_hash))
        migrated += 1

    if args.yes:
        con.commit()
    con.close()

    print(f"\n{'Migrated' if args.yes else 'Would migrate'}: {migrated}.")
    print(f"{'Dropped' if args.yes else 'Would drop'} (collisions): {len(dropped_collisions)}.")
    for label, tid in dropped_collisions:
        print(f"  {label!r} ({tid})")
    if not args.yes:
        print("\nDry run only — re-run with --yes to apply.")


if __name__ == "__main__":
    main()
