"""CLI download subcommand implementation."""

from __future__ import annotations

import argparse
import sys
import requests.exceptions

from ..core.connection import AsperaConnection
from ..core.exceptions import AsperaAuthError, AsperaApiError
from .main import load_config, resolve_host_port
from ..api.download import download
from .formatter import format_download_result


def cmd_download(args: argparse.Namespace) -> int:
    """Handle the 'download' subcommand."""
    config = load_config(args.config)

    host, port = resolve_host_port(args, config)
    user = args.user or config.get("user")
    password = args.password or config.get("password")
    verify_ssl = config.get("verify_ssl", True)
    timeout = config.get("timeout", 30)
    private_key_file = config.get("private_key_file")
    accept_v4 = config.get("accept_v4", True)

    remote_paths = args.remote_path
    local_dest = args.local_dest
    dry_run = args.dry_run
    resume = args.resume
    output_format = args.format
    quiet = args.quiet
    multi_session = args.multi_session
    use_gen4 = args.gen4
    file_id = getattr(args, "file_id", None)
    max_retries = getattr(args, "retries", 3)

    from ..core.transfer import DEFAULT_TRANSFER_TIMEOUT

    transfer_timeout = getattr(args, "timeout", DEFAULT_TRANSFER_TIMEOUT)
    ascp_path_override = getattr(args, "ascp_path", None)
    verbose = getattr(args, "verbose", False)

    try:
        with AsperaConnection(
            host=host,
            port=port,
            user=user,
            password=password,
            verify_ssl=verify_ssl,
            timeout=timeout,
            accept_v4=accept_v4,
        ) as client:
            res = download(
                client=client,
                remote_paths=remote_paths,
                local_dest=local_dest,
                dry_run=dry_run,
                resume=resume,
                multi_session=multi_session,
                use_gen4=use_gen4,
                file_id=file_id,
                max_retries=max_retries,
                transfer_timeout=transfer_timeout,
                quiet=quiet,
                verbose=verbose,
                output_format=output_format,
                private_key_file=private_key_file,
                ascp_path_override=ascp_path_override,
            )

            if output_format == "json":
                print(format_download_result(res, "json"))
            elif len(res["results"]) > 1 and not quiet:
                success_count = sum(
                    1 for r in res["results"] if r["status"] == "success"
                )
                print(
                    f"\nTotal: {len(res['results'])} files, "
                    f"{success_count} succeeded, "
                    f"{len(res['results']) - success_count} failed",
                    file=sys.stderr,
                )

            if res["status"] == "failed" or res["status"] == "partial_failure":
                return 1
            return 0

    except FileNotFoundError as e:
        print(f"File error: {e}", file=sys.stderr)
        return 1
    except AsperaAuthError as e:
        print(f"Authentication error: {e}", file=sys.stderr)
        return 1
    except AsperaApiError as e:
        print(f"API error: {e}", file=sys.stderr)
        return 1
    except requests.exceptions.RequestException as e:
        print(f"Connection error: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"OS error: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"Transfer error: {e}", file=sys.stderr)
        return 1
