"""CLI entry point for Aspera Node API client."""

from __future__ import annotations

import argparse
import os
import sys
import yaml

from .node_api import AsperaNodeClient, AsperaAuthError, AsperaApiError
import requests.exceptions
from .transfer import download_with_progress, ASPENA_ASCP


def load_config(config_path: str) -> dict:
    """Load configuration from YAML file.

    Args:
        config_path: Path to the YAML config file.

    Returns:
        Configuration dictionary.
    """
    if not os.path.exists(config_path):
        print(f"Error: Configuration file not found: {config_path}")
        print(f"Please copy config.sample.yaml to {config_path} and edit it.")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not config:
        print(f"Error: Configuration file is empty: {config_path}")
        sys.exit(1)

    return config


def cmd_list(args: argparse.Namespace) -> int:
    """Handle the 'list' subcommand.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code.
    """
    config = load_config(args.config)

    host = config.get("host", args.host)
    port = config.get("port", 9092)
    user = config.get("user", args.user)
    password = config.get("password", args.password)
    verify_ssl = config.get("verify_ssl", True)
    path_prefix = config.get("path_prefix", "")
    timeout = config.get("timeout", 30)

    remote_path = args.path if args.path else "/"

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
            entries = client.list_files(remote_path)

            if not entries:
                print(f"No files found at: {remote_path}")
                return 0

            # Sort: directories first, then files
            entries.sort(key=lambda e: (e["type"] == "file", e["name"].lower()))

            print(f"Directory: {remote_path}")
            print()

            for entry in entries:
                name = entry["name"]
                entry_type = entry["type"]
                size = entry["size"]
                modified = entry.get("modified", "")

                prefix = "📁" if entry_type == "directory" else "📄"
                size_str = _format_size(size) if entry_type == "file" else ""

                parts = [prefix, name]
                if size_str:
                    parts.append(f"({size_str})")
                if modified:
                    parts.append(f"[{modified}]")

                print("  " + " ".join(parts))

    except AsperaAuthError as e:
        print(f"Authentication error: {e}")
        return 1
    except AsperaApiError as e:
        print(f"API error: {e}")
        return 1
    except requests.exceptions.RequestException as e:
        print(f"Connection error: {e}")
        return 1

    return 0


def cmd_download(args: argparse.Namespace) -> int:
    """Handle the 'download' subcommand.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code.
    """
    config = load_config(args.config)

    host = config.get("host", args.host)
    port = config.get("port", 9092)
    user = config.get("user", args.user)
    password = config.get("password", args.password)
    verify_ssl = config.get("verify_ssl", True)
    path_prefix = config.get("path_prefix", "")
    timeout = config.get("timeout", 30)

    remote_path = args.remote_path
    local_dest = args.local_dest

    identity_file = args.identity_file or config.get("identity_file")

    # Check ascp availability
    if not os.path.exists(ASPENA_ASCP):
        print(f"Error: Aspera ascp not found at {ASPENA_ASCP}")
        print("Please install Aspera Connect SDK:")
        print("  https://www.ibm.com/products/aspera-connect")
        return 1

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
            print(f"Requesting download token for: {remote_path}")

            token_data = client.get_download_token(
                remote_path=remote_path,
                local_dest=local_dest,
            )

            print(f"Token received. Starting transfer...")
            print()

            return_code = download_with_progress(
                token_data=token_data,
                local_dest=local_dest,
                identity_file=identity_file,
            )

            return return_code

    except FileNotFoundError as e:
        print(f"File error: {e}")
        return 1
    except AsperaAuthError as e:
        print(f"Authentication error: {e}")
        return 1
    except AsperaApiError as e:
        print(f"API error: {e}")
        return 1
    except requests.exceptions.RequestException as e:
        print(f"Connection error: {e}")
        return 1
    except RuntimeError as e:
        print(f"Transfer error: {e}")
        return 1


def _format_size(size: int | float) -> str:
    """Format file size for display."""
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

    # download subcommand
    download_parser = subparsers.add_parser("download", help="Download a file using ascp")
    download_parser.add_argument(
        "remote_path",
        help="Remote file path on the Aspera node",
    )
    download_parser.add_argument(
        "local_dest",
        help="Local destination directory",
    )
    download_parser.add_argument(
        "-i", "--identity-file",
        help="Path to Aspera SSH identity key",
    )
  

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "list":
        exit_code = cmd_list(args)
    elif args.command == "download":
        exit_code = cmd_download(args)
    else:
        parser.print_help()
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
