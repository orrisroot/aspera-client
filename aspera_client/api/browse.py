"""High-level Python API for listing and searching files on Aspera node."""

from __future__ import annotations

from typing import Any

from ..core.connection import AsperaConnection
from ..models.page_token import PageToken

FOLDER_TYPES = ("directory", "container")


def _sort_key(entry: dict[str, Any], sort_by: str = "name"):
    """Generate a sort key for a list entry."""
    if sort_by == "name":
        return entry.get("name", "").lower()
    elif sort_by == "size":
        return (0, entry.get("size", 0), "")
    elif sort_by == "modified":
        return entry.get("modified", "")
    elif sort_by == "type":
        return entry.get("type", "file")
    elif sort_by == "depth":
        return (0, entry.get("depth", 0), "")
    return entry.get("name", "").lower()


def _filter_entries(
    entries: list[dict[str, Any]], type_filter: str | None
) -> list[dict[str, Any]]:
    """Filter entries by type."""
    if type_filter is None:
        return entries
    return [e for e in entries if e["type"] == type_filter]


def _sort_entries(
    entries: list[dict[str, Any]],
    sort_by: str = "name",
    reverse: bool = False,
    dirs_first: bool = False,
) -> list[dict[str, Any]]:
    """Sort entries with optional directories-first ordering."""
    if dirs_first:
        dirs = [e for e in entries if e["type"] in FOLDER_TYPES]
        files = [e for e in entries if e["type"] not in FOLDER_TYPES]
        dirs.sort(key=lambda e: _sort_key(e, sort_by))
        files.sort(key=lambda e: _sort_key(e, sort_by))
        if reverse:
            dirs.reverse()
            files.reverse()
        return dirs + files
    return sorted(entries, key=lambda e: _sort_key(e, sort_by), reverse=reverse)


def _parse_gen4_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse gen4 API items into normalized entry dicts."""
    entries = []
    for item in items:
        entry_type = item.get("type", "file")
        if entry_type == "link":
            entry_type = "symbolic_link"
        elif entry_type not in ("file", "directory", "container", "symbolic_link"):
            entry_type = "file"

        entry = {
            "name": item.get("name", ""),
            "type": entry_type,
            "size": item.get("size", 0) or item.get("recursive_size", 0),
            "modified": item.get("modified_time", ""),
            "path": item.get("path", ""),
            "id": item.get("id", ""),
            "access_level": item.get("access_level", ""),
        }
        entries.append(entry)
    return entries


def _parse_matcher(pattern: str):
    """Parse a matcher pattern string into a callable."""
    from ..core.connection import file_matcher

    for op in (">=", "<=", "!=", "=", ">", "<"):
        if op in pattern:
            parts = pattern.split(op, 1)
            if len(parts) == 2:
                field, value = parts
                field = field.strip()
                value = value.strip()
                if field == "type":
                    return lambda e, v=value: e.get("type", "") == v
                if field in ("size", "depth"):
                    try:
                        num_val = int(value)
                    except ValueError:
                        num_val = float(value)
                    if op == ">":
                        return lambda e, f=field, v=num_val: e.get(f, 0) > v
                    elif op == ">=":
                        return lambda e, f=field, v=num_val: e.get(f, 0) >= v
                    elif op == "<":
                        return lambda e, f=field, v=num_val: e.get(f, 0) < v
                    elif op == "<=":
                        return lambda e, f=field, v=num_val: e.get(f, 0) <= v
                    elif op == "=":
                        return lambda e, f=field, v=num_val: e.get(f, 0) == v
                    elif op == "!=":
                        return lambda e, f=field, v=num_val: e.get(f, 0) != v

    return file_matcher(pattern)


def browse(
    client: AsperaConnection,
    path: str = "/",
    count: int = 1000,
    recursive: bool = False,
    sort_by: str = "name",
    reverse: bool = False,
    dirs_first: bool = False,
    type_filter: str | None = None,
    use_gen4: bool = False,
    file_id: str | None = None,
    matcher: Any = None,
    page_token: PageToken | None = None,
) -> tuple[list[dict[str, Any]], PageToken | None]:
    """Browse and filter remote directory entries."""
    skip_val = 0
    iter_token_val = None
    all_pages = True

    if page_token is not None:
        skip_val = page_token.skip
        iter_token_val = page_token.iteration_token
        all_pages = False

    next_page_token = None

    if matcher is not None:
        if isinstance(matcher, str):
            matcher = _parse_matcher(matcher)

        if use_gen4 and file_id:
            entries = client.find_files(file_id, matcher)
        elif recursive:
            all_entries = client.list_recursive(path, count=count)
            entries = [e for e in all_entries["entries"] if matcher(e)]
        else:
            result = client.list_files(
                path, count=count, skip=skip_val, all_pages=all_pages
            )
            entries = [e for e in result["entries"] if matcher(e)]
            if not all_pages and result.get("next_skip") is not None:
                next_page_token = PageToken(skip=result["next_skip"])
    elif use_gen4 and file_id:
        if not recursive:
            if not all_pages:
                res = client.list_files_gen4(
                    file_id,
                    per_page=count,
                    iteration_token=iter_token_val,
                    all_pages=False,
                )
                entries = _parse_gen4_items(res["items"])
                if res.get("next_iteration_token"):
                    next_page_token = PageToken(
                        iteration_token=res["next_iteration_token"]
                    )
            else:
                items = client.list_files_gen4(file_id, per_page=count)
                entries = _parse_gen4_items(items)
        else:
            entries = client.list_recursive_gen4(file_id, path)
    elif recursive:
        result = client.list_recursive(
            path,
            count=count,
            sort_by=sort_by if not dirs_first else None,
            reverse=reverse if not dirs_first else False,
            type_filter=type_filter,
        )
        entries = result["entries"]
    else:
        result = client.list_files(
            path,
            count=count,
            skip=skip_val,
            sort_by=sort_by if not dirs_first else None,
            reverse=reverse if not dirs_first else False,
            type_filter=type_filter,
            all_pages=all_pages,
        )
        entries = result["entries"]
        if not all_pages and result.get("next_skip") is not None:
            next_page_token = PageToken(skip=result["next_skip"])

    if not use_gen4 or not file_id:
        if type_filter and type_filter != "directory":
            entries = _filter_entries(entries, type_filter)
        if dirs_first and type_filter != "directory":
            entries = _sort_entries(entries, sort_by, reverse, dirs_first)
        elif type_filter == "directory":
            dirs_first = False
            entries = _sort_entries(entries, sort_by, reverse, False)
        elif sort_by and not dirs_first and not recursive:
            entries = _sort_entries(entries, sort_by, reverse, False)
        elif sort_by and recursive:
            entries = _sort_entries(entries, sort_by, reverse, False)

    return entries, next_page_token
