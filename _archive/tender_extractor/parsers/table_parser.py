"""
Table Parser — layout detection and field-value extraction from structured tables.

Algorithm:
  1. detect_layout(table): heuristic to classify a TableContent as
       "key_value" (two-column label→value) or "data_table" (multi-column rows).
  2. parse_key_value_table(table): return {label: value} dict.
  3. parse_data_table(table): return list of row dicts (passthrough).
  4. find_value_in_tables(all_tables, field_labels): scan every table using
       the same label-matching logic as field_parser (case-insensitive substring).
       Returns first matching (value, table_index) or (None, None).
"""
from __future__ import annotations

import re
from typing import Any

from tender_extractor.models import TableContent


def detect_layout(table: TableContent) -> str:
    """
    Classify a TableContent as 'key_value' or 'data_table'.

    Key-value heuristic:
      - Table has exactly 2 columns, OR
      - >60% of rows have a short non-empty value in the first column and a
        non-empty value in the second column, AND the first column values are
        never repeated (acting as unique labels).
    """
    if not table.rows:
        return "data_table"

    num_cols = len(table.headers)

    if num_cols == 2:
        return "key_value"

    # Check if first column looks like unique labels
    first_col_vals = [list(row.values())[0] if row else "" for row in table.rows]
    unique_ratio = len(set(v.strip().lower() for v in first_col_vals if v.strip())) / max(len(first_col_vals), 1)

    short_labels = sum(1 for v in first_col_vals if v.strip() and len(v.strip()) < 80)
    label_ratio = short_labels / max(len(first_col_vals), 1)

    if unique_ratio > 0.7 and label_ratio > 0.6:
        return "key_value"

    return "data_table"


def parse_key_value_table(table: TableContent) -> dict[str, str]:
    """
    Extract a label→value dict from a two-column or key-value style table.
    Uses the first column as label, second column as value.
    Strips trailing colons from labels.
    """
    result: dict[str, str] = {}
    for row in table.rows:
        vals = list(row.values())
        if len(vals) < 2:
            continue
        label = str(vals[0]).strip().rstrip(":")
        value = str(vals[1]).strip()
        if label and value:
            result[label] = value
    return result


def parse_data_table(table: TableContent) -> list[dict[str, str]]:
    """
    Return the table rows as-is (already structured as list of row dicts).
    Filters out rows where all values are empty.
    """
    return [row for row in table.rows if any(v.strip() for v in row.values())]


def find_value_in_tables(
    all_tables: list[TableContent],
    field_labels: list[str],
) -> tuple[Any, int | None]:
    """
    Search all tables for a value matching any of the field_labels.

    For each table:
      1. If layout is key_value: check each label in the key→value dict
         using case-insensitive substring matching.
      2. If layout is data_table: check each column header using the same matching,
         then return the first non-empty value in that column.

    Returns (value, table_index) where table_index is the position in all_tables,
    or (None, None) if not found.
    """
    normalised_labels = [_normalise(lb) for lb in field_labels]

    for idx, table in enumerate(all_tables):
        layout = detect_layout(table)

        if layout == "key_value":
            kv = parse_key_value_table(table)
            for key, val in kv.items():
                if any(_is_label_match(_normalise(key), nl) for nl in normalised_labels):
                    if val.strip():
                        return val.strip(), idx
        else:
            # Search column headers
            for header in table.headers:
                if any(_is_label_match(_normalise(header), nl) for nl in normalised_labels):
                    # Return first non-empty value in this column from any row
                    for row in table.rows:
                        val = row.get(header, "").strip()
                        if val:
                            return val, idx

    return None, None


# ── Helpers ────────────────────────────────────────────────────────────────

def _normalise(s: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation for comparison."""
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _is_label_match(normalised_cell: str, normalised_label: str) -> bool:
    """
    Return True if the label appears anywhere in the cell text
    (substring match on normalised strings).
    """
    return normalised_label in normalised_cell or normalised_cell in normalised_label
