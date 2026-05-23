"""List files and directories with pagination, recursion, sorting, and filtering."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import requests.exceptions

from .cli import load_config, resolve_host_port
from .formatter import (
    format_list_table,
    format_list_json,
    format_list_csv,
)
from .node_api import (
    AsperaAuthError,
    AsperaApiError,
    AsperaNodeClient,
    _normalize_path,
    file_matcher,
    FOLDER_TYPES,
)


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
    entries: list[dict[str, Any]],
    type_filter: str | None,
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


def cmd_list(args: argparse.Namespace) -> int:
    """Handle the 'list' subcommand.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code.
    """
    config = load_config(args.config)

    host, port = resolve_host_port(args, config)
    user = args.user or config.get("user")
    password = args.password or config.get("password")
    verify_ssl = config.get("verify_ssl", True)
    timeout = config.get("timeout", 30)
    accept_v4 = config.get("accept_v4", True)

    remote_path = args.path or "/"
    count = args.count
    recursive = args.recursive
    sort_by = args.sort
    reverse = args.reverse
    dirs_first = args.dirs_first
    type_filter = args.type
    output_format = args.format
    fields = args.fields
    use_gen4 = args.gen4
    matcher = args.matcher
    file_id = args.file_id

    try:
        with AsperaNodeClient(
            host=host,
            port=port,
            user=user,
            password=password,
            verify_ssl=verify_ssl,
            timeout=timeout,
            accept_v4=accept_v4,
        ) as client:
            # find command: use matcher to find files
            if matcher is not None:
                if use_gen4 and file_id:
                    entries = client.find_files(file_id, matcher)
                elif recursive:
                    all_entries = client.list_recursive(remote_path, count=count)
                    entries = [e for e in all_entries["entries"] if matcher(e)]
                else:
                    result = client.list_files(remote_path, count=count)
                    entries = [e for e in result["entries"] if matcher(e)]
                total_count = len(entries)
            elif use_gen4 and file_id:
                # gen4 browse by file_id
                if not recursive:
                    items = client.list_files_gen4(file_id, per_page=count)
                    entries = _parse_gen4_items(items)
                else:
                    entries = client.list_recursive_gen4(file_id, remote_path)
                total_count = len(entries)
            elif recursive:
                result = client.list_recursive(
                    remote_path, count=count,
                    sort_by=sort_by if not dirs_first else None,
                    reverse=reverse if not dirs_first else False,
                    type_filter=type_filter,
                )
                entries = result["entries"]
                total_count = result["total_count"]
            else:
                result = client.list_files(
                    remote_path, count=count,
                    sort_by=sort_by if not dirs_first else None,
                    reverse=reverse if not dirs_first else False,
                    type_filter=type_filter,
                )
                entries = result["entries"]
                total_count = result["total_count"]

            # Apply client-side sort/filter if not done server-side
            # For recursive listing, per-directory sort is not enough - apply global sort
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

            result = _format_list(entries, remote_path, output_format, fields, count=len(entries))
            if result is not None:
                print(result)

    except AsperaAuthError as e:
        print(f"Authentication error: {e}", file=sys.stderr)
        return 1
    except AsperaApiError as e:
        print(f"API error: {e}", file=sys.stderr)
        return 1
    except requests.exceptions.RequestException as e:
        print(f"Connection error: {e}", file=sys.stderr)
        return 1

    return 0


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
    """Parse a matcher pattern string into a callable.

    Supports:
    - Glob patterns (e.g., '*.txt')
    - Regex patterns (e.g., '^test.*')
    - Field comparisons (e.g., 'size>1000', 'type=file')
    """
    # Field comparison: field op value
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


def cmd_find(args: argparse.Namespace) -> int:
    """Handle the 'find' subcommand.

    Search for files matching a pattern using file_matcher support.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code.
    """
    config = load_config(args.config)

    host, port = resolve_host_port(args, config)
    user = args.user or config.get("user")
    password = args.password or config.get("password")
    verify_ssl = config.get("verify_ssl", True)
    timeout = config.get("timeout", 30)
    accept_v4 = config.get("accept_v4", True)

    search_path = args.path or "/"
    pattern = args.pattern
    recursive = args.recursive
    count = args.count
    output_format = args.format
    fields = args.fields
    use_gen4 = args.gen4
    file_id = args.file_id

    try:
        matcher = _parse_matcher(pattern)

        with AsperaNodeClient(
            host=host,
            port=port,
            user=user,
            password=password,
            verify_ssl=verify_ssl,
            timeout=timeout,
            accept_v4=accept_v4,
        ) as client:
            if use_gen4 and file_id:
                entries = client.find_files(file_id, matcher)
            elif recursive:
                result = client.list_recursive(search_path, count=count)
                entries = [e for e in result["entries"] if matcher(e)]
            else:
                result = client.list_files(search_path, count=count)
                entries = [e for e in result["entries"] if matcher(e)]

            result = _format_list(entries, search_path, output_format, fields, count=len(entries))
            if result is not None:
                print(result)

    except AsperaAuthError as e:
        print(f"Authentication error: {e}", file=sys.stderr)
        return 1
    except AsperaApiError as e:
        print(f"API error: {e}", file=sys.stderr)
        return 1
    except requests.exceptions.RequestException as e:
        print(f"Connection error: {e}", file=sys.stderr)
        return 1

    return 0


def _format_list(
    entries: list[dict[str, Any]],
    path: str,
    fmt: str,
    fields: list[str] | None,
    count: int | None = None,
) -> str | None:
    """Format list entries according to the specified format.

    Returns a string for json/csv, or None for table (which prints directly).
    """
    if not entries:
        return f"No files found at: {path}"

    if fmt == "json":
        return format_list_json(entries, path)
    elif fmt == "csv":
        return format_list_csv(entries, path)
    else:
        format_list_table(entries, path, fields, count=count)
        return None
