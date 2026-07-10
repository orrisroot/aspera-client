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
        return "0"

    units = ["", "K", "M", "G", "T"]
    size = float(size)
    unit_index = 0

    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1

    if unit_index == 0:
        return f"{int(size)}"
    return f"{size:.1f}{units[unit_index]}"


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
        return list(LS_DEFAULT_FIELDS)

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


# File type extensions for LS_COLORS-like coloring
_COMPRESS_EXTS = {".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar", ".tgz", ".tbz2"}
_MEDIA_EXTS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".svg",
    ".webp",
    ".ico",
    ".mp4",
    ".avi",
    ".mkv",
    ".mov",
    ".wmv",
    ".flv",
    ".mp3",
    ".wav",
    ".flac",
    ".aac",
    ".ogg",
}

LS_DEFAULT_FIELDS = ("size", "modified", "name")


def _get_type_indicator(entry_type: str) -> str:
    """Return a type indicator character."""
    if entry_type in ("directory", "container"):
        return "d"
    elif entry_type == "symbolic_link":
        return "l"
    return "f"


def _abbreviate_access(access_level: str) -> str:
    """Abbreviate access_level to a single character."""
    access = (access_level or "").lower().strip()
    if access.startswith("r"):
        return "r"
    elif access.startswith("w"):
        return "w"
    elif access.startswith("a"):
        return "a"
    return "-"


def _get_file_color_style(name: str, entry_type: str) -> str:
    """Return a rich color style based on file type (LS_COLORS-like)."""
    if entry_type in ("directory", "container"):
        return "bold blue"
    elif entry_type == "symbolic_link":
        return "cyan"

    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in _COMPRESS_EXTS:
        return "magenta"
    elif ext in _MEDIA_EXTS:
        return "yellow"
    return ""


def format_list_table(
    entries: list[dict[str, Any]],
    path: str,
    fields: str | None = None,
    count: int | None = None,
) -> None:
    """Format list entries in ls-like style.

    Uses ls -l inspired formatting with LS_COLORS-like coloring.
    Respects --fields to control which columns are displayed.

    Args:
        entries: List of file/directory entry dicts.
        path: Remote directory path.
        fields: Comma-separated field names (or None for default).
        count: Number of entries to display in header.
    """
    from rich.console import Console

    console = Console()
    display_fields = _compute_fields(entries, fields)
    if not display_fields:
        display_fields = list(LS_DEFAULT_FIELDS)

    _print_ls_style(console, entries, path, display_fields, count=count)


def _print_ls_style(
    console: Any,  # rich.console.Console
    entries: list[dict[str, Any]],
    path: str,
    fields: list[str],
    count: int | None = None,
) -> None:
    """Print entries in ls -l style with color.

    Args:
        console: Rich console instance.
        entries: List of file/directory entry dicts.
        path: Remote directory path.
        fields: Field names to display (e.g. ["name", "type", "size", "modified"]).
        count: Number of entries to display in header.
    """
    from rich.text import Text

    if count is not None:
        console.print(f"[bold]Directory:[/bold] {path} ({count} items)")
    else:
        console.print(f"[bold]Directory:[/bold] {path}")
    console.print()

    if not entries:
        console.print("  (no entries)")
        return

    # Separate name (always last, colored) from other fields
    mid_fields = [f for f in fields if f != "name"]
    has_name = "name" in fields

    # Compute column widths for mid fields
    col_widths: dict[str, int] = {}
    for field in mid_fields:
        width = len(field.replace("_", " ").title())
        for entry in entries:
            val = _get_field(entry, field)
            if len(val) > width:
                width = len(val)
        col_widths[field] = max(width, 4)

    # Compute name column width
    name_width = 0
    if has_name:
        name_width = len("Name")
        for entry in entries:
            val = len(entry.get("name", ""))
            if val > name_width:
                name_width = val
        name_width = max(name_width, 4)

    # Print header (attribute column header is blank)
    hdr_cells: list[tuple[str, str]] = [("  ", "dim")]
    for field in mid_fields:
        label = field.replace("_", " ").title()
        hdr_cells.append((label.ljust(col_widths[field]), "dim"))
    if has_name:
        hdr_cells.append(("Name".ljust(name_width), "dim"))
    hdr_text = Text()
    for i, (text, style) in enumerate(hdr_cells):
        hdr_text.append(text, style=style)
        if i < len(hdr_cells) - 1:
            hdr_text.append(" ")
    console.print(hdr_text)

    # Format and print each entry
    for entry in entries:
        entry_type = entry.get("type", "file")
        indicator = _get_type_indicator(entry_type)
        access = _abbreviate_access(entry.get("access_level", ""))

        cells: list[tuple[str, str | None]] = []
        # attribute column (2 chars)
        cells.append((f"{indicator}{access}", None))

        # mid columns
        for field in mid_fields:
            val = _get_field(entry, field)
            if not val:
                val = "-"
            # For directories with size 0, show "-" instead of "0"
            if (
                field == "size"
                and entry_type in ("directory", "container")
                and entry.get("size", 0) == 0
            ):
                val = "-"
            cells.append((val.ljust(col_widths[field]), None))

        # name (last, with color)
        if has_name:
            name = entry.get("name", "")
            style = _get_file_color_style(name, entry_type)
            cells.append((name.ljust(name_width), style if style else None))

        line = Text()
        for i, (text, style) in enumerate(cells):
            line.append(text, style=style)
            if i < len(cells) - 1:
                line.append(" ")
        console.print(line)


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

    fieldnames = sorted({k for entry_data in entries for k in entry_data.keys()})
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
