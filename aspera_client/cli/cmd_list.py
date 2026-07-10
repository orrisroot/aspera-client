"""CLI list and find subcommand implementation."""

from __future__ import annotations

import argparse
import sys
from typing import Any
import requests.exceptions

from ..core.connection import AsperaConnection
from ..core.exceptions import AsperaAuthError, AsperaApiError
from .main import load_config, resolve_host_port
from ..api.browse import browse
from .formatter import (
    format_list_table,
    format_list_json,
    format_list_csv,
)


def _format_list(
    entries: list[dict[str, Any]],
    path: str,
    output_format: str = "table",
    fields: list[str] | None = None,
    count: int = 0,
) -> str | None:
    """Format file listing output."""
    if output_format == "json":
        return format_list_json(entries, fields=fields)
    elif output_format == "csv":
        return format_list_csv(entries, fields=fields)
    else:
        return format_list_table(entries, path, count=count)


def cmd_list(args: argparse.Namespace) -> int:
    """Handle the 'list' subcommand."""
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
    matcher_pattern = args.matcher
    file_id = args.file_id

    try:
        from ..api.browse import _parse_matcher

        matcher = (
            _parse_matcher(matcher_pattern) if matcher_pattern is not None else None
        )

        with AsperaConnection(
            host=host,
            port=port,
            user=user,
            password=password,
            verify_ssl=verify_ssl,
            timeout=timeout,
            accept_v4=accept_v4,
        ) as client:
            entries, _ = browse(
                client=client,
                path=remote_path,
                count=count,
                recursive=recursive,
                sort_by=sort_by,
                reverse=reverse,
                dirs_first=dirs_first,
                type_filter=type_filter,
                use_gen4=use_gen4,
                file_id=file_id,
                matcher=matcher,
            )

            result = _format_list(
                entries, remote_path, output_format, fields, count=len(entries)
            )
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


def cmd_find(args: argparse.Namespace) -> int:
    """Handle the 'find' subcommand."""
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
        from ..api.browse import _parse_matcher

        matcher = _parse_matcher(pattern) if pattern else None
        with AsperaConnection(
            host=host,
            port=port,
            user=user,
            password=password,
            verify_ssl=verify_ssl,
            timeout=timeout,
            accept_v4=accept_v4,
        ) as client:
            entries, _ = browse(
                client=client,
                path=search_path,
                count=count,
                recursive=recursive,
                use_gen4=use_gen4,
                file_id=file_id,
                matcher=matcher,
            )

            result = _format_list(
                entries, search_path, output_format, fields, count=len(entries)
            )
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
