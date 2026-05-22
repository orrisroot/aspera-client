"""CLI entry point for Aspera Node API client."""

from __future__ import annotations

import argparse
import os
import sys
import yaml

def load_config(config_path: str) -> dict:
    """Load configuration from YAML file."""
    if not os.path.exists(config_path):
        print(f"Error: Configuration file not found: {config_path}", file=sys.stderr)
        print(f"Please copy config.sample.yaml to {config_path} and edit it.", file=sys.stderr)
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not config:
        print(f"Error: Configuration file is empty: {config_path}", file=sys.stderr)
        sys.exit(1)

    return config


def main() -> None:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        prog="aspera",
        description="IBM Aspera Node API client for file listing and high-speed transfer",
    )
    parser.add_argument(
        "-c", "--config",
        default="config.yaml",
        help="Path to configuration file (default: config.yaml)",
    )
    parser.add_argument("--host", help="Aspera Node server hostname (overrides config)")
    parser.add_argument("--port", type=int, help="Node API port (overrides config)")
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
        "-n", "--count",
        type=int,
        default=1000,
        help="Max entries per page (default: 1000)",
    )
    list_parser.add_argument(
        "-r", "--recursive",
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
        "-f", "--format",
        choices=["table", "json", "csv"],
        default="table",
        help="Output format (default: table)",
    )
    list_parser.add_argument(
        "--fields",
        help="Comma-separated list of fields to display (default: name,type,size,modified)",
    )

    # download subcommand
    download_parser = subparsers.add_parser("download", help="Download files using ascp")
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
        "-f", "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    download_parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress ascp progress bar output",
    )
    download_parser.add_argument(
        "-M", "--multi-session",
        type=int,
        default=1,
        help="Number of concurrent transfer sessions (default: 1)",
    )

    args = parser.parse_args()

    if args.command == "download" and args.multi_session < 1:
        parser.error("--multi-session must be >= 1")

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "list":
        from .list import cmd_list
        exit_code = cmd_list(args)
    elif args.command == "download":
        from .download import cmd_download
        exit_code = cmd_download(args)
    else:
        parser.print_help()
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
