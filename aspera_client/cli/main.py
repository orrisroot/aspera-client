"""CLI entry point for Aspera Node API client."""

from __future__ import annotations

import argparse
import sys
from ..models.config import (
    load_config as _load_config,
    resolve_host_port as _resolve_host_port,
)


def load_config(config_path: str) -> dict:
    """Load configuration from YAML file."""
    try:
        return _load_config(config_path)
    except FileNotFoundError:
        print(f"Error: Configuration file not found: {config_path}", file=sys.stderr)
        print(
            f"Please copy config.sample.yaml to {config_path} and edit it.",
            file=sys.stderr,
        )
        sys.exit(1)
    except ValueError:
        print(f"Error: Configuration file is empty: {config_path}", file=sys.stderr)
        sys.exit(1)


def resolve_host_port(args: argparse.Namespace, config: dict) -> tuple[str, int]:
    """Resolve host and port from --url or --host/--port or config.

    Priority: --url flag > config url > --host/--port flags > config host/port > defaults.
    """
    host_flag = getattr(args, "host", None)
    port_flag = getattr(args, "port", None)
    return _resolve_host_port(
        url=args.url, host=host_flag, port=port_flag, config=config
    )


def main() -> None:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        prog="aspera",
        description="IBM Aspera Node API client for file listing and high-speed transfer",
    )
    parser.add_argument(
        "-c",
        "--config",
        default="config.yaml",
        help="Path to configuration file (default: config.yaml)",
    )
    parser.add_argument(
        "--url",
        help="Aspera Node server URL (overrides config, e.g. https://host:9092)",
    )
    parser.add_argument("--user", help="Username (overrides config)")
    parser.add_argument("--password", help="Password (overrides config)")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # list subcommand
    list_parser = subparsers.add_parser("list", help="List files and directories")
    list_parser.add_argument(
        "path",
        nargs="?",
        default="/",
        help="Remote directory path (default: /)",
    )
    list_parser.add_argument(
        "-n",
        "--count",
        type=int,
        default=1000,
        help="Max entries per page (default: 1000)",
    )
    list_parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Recursively list subdirectories",
    )
    list_parser.add_argument(
        "--sort",
        choices=["name", "size", "modified", "type", "depth"],
        default="name",
        help="Sort field (default: name)",
    )
    list_parser.add_argument(
        "--reverse",
        action="store_true",
        help="Reverse sort order",
    )
    list_parser.add_argument(
        "--dirs-first",
        action="store_true",
        help="Show directories before files",
    )
    list_parser.add_argument(
        "--type",
        choices=["file", "directory", "symbolic_link"],
        help="Filter by type",
    )
    list_parser.add_argument(
        "-f",
        "--format",
        choices=["table", "json", "csv"],
        default="table",
        help="Output format (default: table)",
    )
    list_parser.add_argument(
        "--fields",
        help="Comma-separated list of fields. Use '-' prefix to exclude (e.g., '-id,-path')",
    )
    # Gen4 options
    list_parser.add_argument(
        "--gen4",
        action="store_true",
        help="Use gen4 API (Accept-Version: 4.0, iteration_token pagination)",
    )
    list_parser.add_argument(
        "--file-id",
        help="Gen4 file ID to browse (instead of path)",
    )
    list_parser.add_argument(
        "--matcher",
        help="File matcher pattern (glob, regex, or None for all). Used with --find or --type filter.",
    )

    find_parser = subparsers.add_parser("find", help="Find files matching a pattern")
    find_parser.add_argument(
        "path",
        nargs="?",
        default="/",
        help="Search root path (default: /)",
    )
    find_parser.add_argument(
        "pattern",
        help="Glob pattern, regex, or field=value to match (e.g., '*.txt', 'size>1000')",
    )
    find_parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Recursively search subdirectories",
    )
    find_parser.add_argument(
        "-n",
        "--count",
        type=int,
        default=1000,
        help="Max entries per page (default: 1000)",
    )
    find_parser.add_argument(
        "-f",
        "--format",
        choices=["table", "json", "csv"],
        default="table",
        help="Output format (default: table)",
    )
    find_parser.add_argument(
        "--fields",
        help="Comma-separated list of fields to display",
    )
    find_parser.add_argument(
        "--gen4",
        action="store_true",
        help="Use gen4 API",
    )
    find_parser.add_argument(
        "--file-id",
        help="Gen4 file ID to search from",
    )
    # download subcommand
    download_parser = subparsers.add_parser(
        "download", help="Download files using ascp"
    )
    download_parser.add_argument(
        "remote_path",
        nargs="+",
        help="Remote file path(s) on the Aspera node",
    )
    download_parser.add_argument(
        "local_dest",
        help="Local destination directory",
    )
    download_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show transfer specs without executing",
    )
    download_parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume interrupted transfer",
    )
    download_parser.add_argument(
        "-f",
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    download_parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress ascp progress bar output",
    )
    download_parser.add_argument(
        "-M",
        "--multi-session",
        type=int,
        default=1,
        help="Number of concurrent transfer sessions (default: 1)",
    )
    download_parser.add_argument(
        "--gen4",
        action="store_true",
        help="Use gen4 transfer spec",
    )
    download_parser.add_argument(
        "--file-id",
        help="Gen4 file ID for transfer",
    )
    download_parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Max retry attempts on transient failure (default: 3)",
    )
    download_parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Transfer timeout in seconds (default: 120)",
    )
    download_parser.add_argument(
        "--ascp-path",
        help="Path to ascp binary (overrides auto-detection)",
    )
    download_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose ascp output (-v flag)",
    )

    # setup subcommand
    setup_parser = subparsers.add_parser("setup", help="Install SDK and generate keys")
    setup_parser.add_argument(
        "--no-sdk",
        action="store_true",
        help="Skip SDK installation",
    )
    setup_parser.add_argument(
        "--no-bypass-key",
        action="store_true",
        help="Skip bypass key generation",
    )
    setup_parser.add_argument(
        "--no-fallback-key",
        action="store_true",
        help="Skip fallback key generation",
    )
    setup_parser.add_argument(
        "--version",
        help="Specific SDK version to install",
    )

    args = parser.parse_args()

    if (
        args.command == "download"
        and hasattr(args, "multi_session")
        and args.multi_session < 1
    ):
        parser.error("--multi-session must be >= 1")

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "list":
        from .cmd_list import cmd_list

        exit_code = cmd_list(args)
    elif args.command == "find":
        from .cmd_list import cmd_find

        exit_code = cmd_find(args)
    elif args.command == "download":
        from .cmd_download import cmd_download

        exit_code = cmd_download(args)
    elif args.command == "setup":
        from .cmd_setup import cmd_setup

        exit_code = cmd_setup(args)
    else:
        parser.print_help()
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
