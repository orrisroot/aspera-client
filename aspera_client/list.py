"""List files and directories with pagination, recursion, sorting, and filtering."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import requests.exceptions

from .cli import load_config
from .formatter import (
    format_list_table,
    format_list_json,
    format_list_csv,
)

from .node_api import AsperaAuthError, AsperaApiError, AsperaNodeClient


def _normalize_path(path: str) -> str:
    """Normalize path, collapsing multiple slashes."""
    return os.path.normpath(path)


def _sort_key(entry: dict[str, Any], sort_by: str = "name"):
    """Generate a sort key for a list entry."""
    if sort_by == "name":
        return entry["name"].lower()
    elif sort_by == "size":
        return (0, entry.get("size", 0), "")
    elif sort_by == "modified":
        return entry.get("modified", "")
    elif sort_by == "type":
        return entry["type"]
    elif sort_by == "depth":
        return (0, entry.get("depth", 0), "")
    return entry["name"].lower()


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
        dirs = [e for e in entries if e["type"] == "directory"]
        files = [e for e in entries if e["type"] != "directory"]
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

    host = args.host or config.get("host", "localhost")
    port = args.port
    if port is None:
        port = config.get("port", 9092)
    user = args.user or config.get("user")
    password = args.password or config.get("password")
    verify_ssl = config.get("verify_ssl", True)
    path_prefix = config.get("path_prefix", "")
    timeout = config.get("timeout", 30)

    remote_path = args.path or "/"
    count = args.count
    recursive = args.recursive
    sort_by = args.sort
    reverse = args.reverse
    dirs_first = args.dirs_first
    type_filter = args.type
    output_format = args.format
    fields = args.fields

    if fields:
        fields = [field.strip() for field in fields.split(",") if field.strip()]

    try:
        with AsperaNodeClient(
            host=host,
            port=port,
            user=user,
            password=password,
            verify_ssl=verify_ssl,
            path_prefix=path_prefix,
            timeout=timeout,
        ) as client:
            if recursive:
                entries = _list_recursive(client, remote_path, count)
            else:
                entries = _list_page(client, remote_path, count)

            entries = _filter_entries(entries, type_filter)
            if type_filter == "directory":
                dirs_first = False
            entries = _sort_entries(entries, sort_by, reverse, dirs_first)

            result = _format_list(entries, remote_path, output_format, fields)
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


def _list_page(
    client: Any,
    path: str,
    count: int,
) -> list[dict[str, Any]]:
    """List files in a single directory with automatic pagination via skip offset."""
    all_entries: list[dict[str, Any]] = []
    skip = 0

    while True:
        entries = client.list_files(path, count=count, skip=skip)
        if not entries:
            break

        all_entries.extend(entries)

        if len(entries) < count:
            break

        skip += len(entries)
        print(f"  ... fetched {len(all_entries)} entries so far...", file=sys.stderr)

    return all_entries


MAX_RECURSION_DEPTH = 100


def _list_recursive(
    client: Any,
    path: str,
    count: int,
    current_depth: int = 0,
) -> list[dict[str, Any]]:
    """Recursively list files and directories with pagination."""
    all_entries: list[dict[str, Any]] = []

    skip = 0
    while True:
        entries = client.list_files(path, count=count, skip=skip)
        if not entries:
            break

        for entry in entries:
            entry = dict(entry)
            entry["depth"] = current_depth
            all_entries.append(entry)

            if entry["type"] == "directory" and current_depth < MAX_RECURSION_DEPTH:
                dir_path = entry.get("path", "") or f"{path}/{entry['name']}"
                dir_path = _normalize_path(dir_path)
                sub_entries = _list_recursive(client, dir_path, count, current_depth + 1)
                all_entries.extend(sub_entries)

        if len(entries) < count:
            break

        skip += len(entries)

    return all_entries


def _format_list(
    entries: list[dict[str, Any]],
    path: str,
    fmt: str,
    fields: list[str] | None,
) -> str:
    """Format list entries according to the specified format."""
    if not entries:
        return f"No files found at: {path}"

    if fmt == "json":
        return format_list_json(entries, path)
    elif fmt == "csv":
        return format_list_csv(entries, path)
    else:
        return format_list_table(entries, path, fields)
