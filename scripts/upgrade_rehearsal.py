"""
Pieces of the upgrade rehearsal (ADR 0075, condition 5).

The rehearsal seeds a database with one release, upgrades it with the
migrations of the next, and shows that no row changed. This module
holds the part that decides whether anything did.
"""

from __future__ import annotations

import csv
import io

Snapshot = dict[str, str]


def _read(
    table: str,
    text: str,
) -> tuple[list[str], dict[str, dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(text))
    columns = list(reader.fieldnames or [])
    if not columns:
        raise ValueError(f"{table}: the export has no header")

    rows: dict[str, dict[str, str]] = {}
    for row in reader:
        row_id = row[columns[0]]
        if row_id in rows:
            raise ValueError(f"{table}: id {row_id} appears twice")
        rows[row_id] = row

    return columns, rows


def compare_snapshots(before: Snapshot, after: Snapshot) -> list[str]:
    """
    Compare two sets of table exports, each a table name mapped to CSV
    text with a header whose first column is the id. Return one line
    per difference, or an empty list when nothing changed.
    """
    differences: list[str] = []

    for table in sorted(set(before) | set(after)):
        if table not in before:
            differences.append(f"{table}: missing from the before snapshot")
            continue
        if table not in after:
            differences.append(f"{table}: missing from the after snapshot")
            continue

        before_columns, before_rows = _read(table, before[table])
        after_columns, after_rows = _read(table, after[table])

        if before_columns != after_columns:
            differences.append(
                f"{table}: columns changed from {before_columns} "
                f"to {after_columns}"
            )
            continue

        for row_id in sorted(before_rows.keys() - after_rows.keys()):
            differences.append(f"{table} {row_id}: row removed")
        for row_id in sorted(after_rows.keys() - before_rows.keys()):
            differences.append(f"{table} {row_id}: row added")
        for row_id in sorted(before_rows.keys() & after_rows.keys()):
            for column in before_columns:
                old = before_rows[row_id][column]
                new = after_rows[row_id][column]
                if old != new:
                    differences.append(
                        f"{table} {row_id}: {column} changed "
                        f"from {old!r} to {new!r}"
                    )

    return differences
