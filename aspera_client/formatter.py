"""Output formatter for list and download results."""

from __future__ import annotations

import csv
import io
import json
from typing import Any


FIELDS_EXCLUDE = "-"


def format_size(size: int | float) -> str:
    """Format file size in human-readable form."""
    if size == 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size)
    unit_index = 0

    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1

    if unit_index == 0:
        return f"{int(size)} B"
    return f"{size:.1f} {units[unit_index]}"


def _get_field(entry: dict[str, Any], field: str) -> str:
    """Extract a field value from an entry for display."""
    if field == "name":
        return entry.get("name", "")
    elif field == "type":
        t = entry.get("type", "file")
        return t.replace("_", " ").title()
    elif field == "size":
        return format_size(entry.get("size", 0))
    elif field == "modified":
        return entry.get("modified", "")
    elif field == "modified_time":
        return entry.get("modified_time", "")
    elif field == "path":
        return entry.get("path", "")
    elif field == "extension":
        name = entry.get("name", "")
        if "." in name:
            return name.rsplit(".", 1)[-1]
        return ""
    elif field == "depth":
        return str(entry.get("depth", 0))
    elif field == "recursive_size":
        return format_size(entry.get("recursive_size", 0))
    elif field == "access_level":
        return entry.get("access_level", "")
    return str(entry.get(field, ""))


def _compute_fields(
    entries: list[dict[str, Any]],
    raw_fields: str | None,
) -> list[str]:
    """Compute the list of fields to display.

    Supports:
    - Specific field names
    - '-' prefix for exclusion (e.g., '-id')
    - '+' prefix for inclusion only
    - All fields if None
    """
    if raw_fields is None:
        # Get all fields from all entries
        return sorted({k for e in entries for k in e.keys()})

    parts = [f.strip() for f in raw_fields.split(",") if f.strip()]
    result: list[str] = []
    excludes: list[str] = []
    includes_only = False

    for part in parts:
        if part.startswith(FIELDS_EXCLUDE):
            excludes.append(part[1:])
        elif part.startswith("+"):
            includes_only = True
            result.append(part[1:])
        else:
            result.append(part)

    # Get all available fields
    all_fields = sorted({k for e in entries for k in e.keys()})

    if not result and not excludes:
        return all_fields

    if includes_only:
        return result

    # Start with all fields, remove excludes
    if not result:
        result = [f for f in all_fields if f not in excludes]
    else:
        # Use specified fields, remove excludes
        result = [f for f in result if f not in excludes]

    return result


def format_list_table(
    entries: list[dict[str, Any]],
    path: str,
    fields: str | None = None,
) -> str:
    """Format list entries as a human-readable table.

    Args:
        entries: List of file/directory entry dicts.
        path: Remote directory path.
        fields: Comma-separated field names, with '-' prefix for exclusion.
    """
    all_fields = _compute_fields(entries, fields)
    if not all_fields:
        all_fields = ["name", "type", "size", "modified"]

    lines = [f"Directory: {path}", ""]

    for entry in entries:
        parts = []
        for field in all_fields:
            val = _get_field(entry, field)
            parts.append(val if val else "-")
        lines.append("  " + "    ".join(parts))

    return "\n".join(lines)


def format_list_json(entries: list[dict[str, Any]], path: str) -> str:
    """Format list entries as JSON."""
    result = {
        "path": path,
        "count": len(entries),
        "entries": entries,
    }
    return json.dumps(result, indent=2, ensure_ascii=False)


def format_list_csv(entries: list[dict[str, Any]], path: str) -> str:
    """Format list entries as CSV."""
    if not entries:
        return ""

    fieldnames = sorted(
        {k for entry_data in entries for k in entry_data.keys()}
    )
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(entries)
    return buf.getvalue()


def format_download_result(
    result: dict[str, Any],
    fmt: str = "text",
) -> str:
    """Format download transfer result."""
    if fmt == "json":
        return json.dumps(result, indent=2, ensure_ascii=False)

    lines = []
    status = result.get("status", "unknown")
    lines.append(f"Status: {status}")

    if "files" in result:
        total = result["files"]
        lines.append(f"Files transferred: {total}")

    if "total_bytes" in result:
        lines.append(f"Bytes transferred: {format_size(result['total_bytes'])}")

    if "elapsed" in result:
        lines.append(f"Elapsed: {result['elapsed']:.1f}s")

    if "speed" in result:
        lines.append(f"Speed: {format_size(result['speed'])}/s")

    if "error" in result:
        lines.append(f"Error: {result['error']}")

    return "\n".join(lines)
