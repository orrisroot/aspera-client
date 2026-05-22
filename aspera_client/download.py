"""Download files and directories with ascp, supporting recursion, multi-file, and structured output."""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.parse
from typing import Any

import requests.exceptions

from .cli import load_config, resolve_host_port
from .formatter import format_download_result
from .node_api import AsperaAuthError, AsperaApiError, AsperaNodeClient
from .transfer import (
    ASPERA_ASCP,
    DIRECTION_RECEIVE,
    _build_ascp_command,
    _execute_ascp,
    build_file_list,
    build_transfer_spec_gen3,
    build_transfer_spec_gen4,
    extract_spec,
    find_common_root,
    fix_resume_policy,
    download_with_progress,
)


def cmd_download(args: argparse.Namespace) -> int:
    """Handle the 'download' subcommand.

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

    # Check ascp availability
    if not os.path.exists(ASPERA_ASCP):
        print(f"Error: Aspera ascp not found at {ASPERA_ASCP}", file=sys.stderr)
        print("Please install Aspera Connect SDK:", file=sys.stderr)
        print("  https://www.ibm.com/products/aspera-connect", file=sys.stderr)
        return 1

    try:
        dynamic_key = None
        if private_key_file:
            try:
                with open(private_key_file, "r", encoding="utf-8") as f:
                    dynamic_key = f.read().strip()
            except OSError as e:
                print(f"Error reading private key file '{private_key_file}': {e}", file=sys.stderr)
                return 1

        with AsperaNodeClient(
            host=host,
            port=port,
            user=user,
            password=password,
            verify_ssl=verify_ssl,
            timeout=timeout,
            dynamic_key=dynamic_key,
            accept_v4=accept_v4,
        ) as client:
            results: list[dict[str, Any]] = []
            total_start = time.time()

            for remote_path in remote_paths:
                print(f"Requesting download token for: {remote_path}", file=sys.stderr)

                if dry_run:
                    token_data = client.get_download_token(
                        remote_path=remote_path,
                        local_dest=local_dest,
                    )
                    spec = extract_spec(token_data)
                    print()
                    print(f"=== Dry Run: {remote_path} ===")
                    print(f"  remote_host: {spec.get('remote_host', '')}")
                    print(f"  remote_user: {spec.get('remote_user', '')}")
                    print(f"  ssh_port:    {spec.get('ssh_port', '')}")
                    print(f"  fasp_port:   {spec.get('fasp_port', '')}")
                    print(f"  source_root: {spec.get('source_root', '')}")
                    print("  paths:")
                    for p in spec.get("paths", []):
                        print(f"    - {p.get('source', '')}")
                    print(f"  destination_root: {local_dest}")
                    print()
                    results.append({
                        "source": remote_path,
                        "status": "dry_run",
                        "spec": spec,
                    })
                    continue

                # Gen4 transfer (handles all paths at once)
                if use_gen4 and file_id:
                    return_code = _download_gen4(
                        client=client,
                        file_id=file_id,
                        remote_paths=remote_paths,
                        local_dest=local_dest,
                        resume=resume,
                        multi_session=multi_session,
                        quiet=quiet,
                    )
                    elapsed = time.time() - total_start
                    status = "success" if return_code == 0 else "failed"
                    results.append({
                        "source": remote_paths[0],
                        "status": status,
                        "exit_code": return_code,
                        "elapsed": elapsed,
                    })
                    if return_code != 0:
                        print(f"\nDownload failed for: {remote_paths[0]}", file=sys.stderr)
                    else:
                        print(f"\nDownload completed: {remote_paths[0]} ({elapsed:.1f}s)", file=sys.stderr)
                    break

                # Gen3 transfer
                token_data = client.get_download_token(
                    remote_path=remote_path,
                    local_dest=local_dest,
                )

                print("Token received. Starting transfer...", file=sys.stderr)
                print(file=sys.stderr)

                start_time = time.time()
                if output_format == "json":
                    return_code = _download_with_output_redirect(
                        token_data=token_data,
                        local_dest=local_dest,
                        resume=resume,
                        multi_session=multi_session,
                    )
                else:
                    spec = extract_spec(token_data)
                    return_code = download_with_progress(
                        token_data=token_data,
                        local_dest=local_dest,
                        resume=resume,
                        multi_session=multi_session,
                        quiet=quiet,
                        ssh_private_key=spec.get("ssh_private_key"),
                    )
                elapsed = time.time() - start_time

                if return_code == 0:
                    status = "success"
                else:
                    status = "failed"

                result = {
                    "source": remote_path,
                    "status": status,
                    "exit_code": return_code,
                    "elapsed": elapsed,
                }

                if return_code != 0:
                    result["error"] = f"ascp exited with code {return_code}"

                results.append(result)

                if return_code != 0:
                    print(f"\nDownload failed for: {remote_path}", file=sys.stderr)
                else:
                    print(f"\nDownload completed: {remote_path} ({elapsed:.1f}s)", file=sys.stderr)

            # Structured output
            if output_format == "json":
                total_elapsed = time.time() - total_start
                output = {
                    "status": "success" if all(r["status"] == "success" for r in results) else "partial_failure",
                    "files": len(results),
                    "results": results,
                    "total_elapsed": total_elapsed,
                }
                print(format_download_result(output, "json"))
            elif len(results) > 1:
                success_count = sum(1 for r in results if r["status"] == "success")
                print(f"\nTotal: {len(results)} files, {success_count} succeeded, {len(results) - success_count} failed", file=sys.stderr)

            # Return non-zero if any failed
            if any(r["status"] == "failed" for r in results):
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
    except RuntimeError as e:
        print(f"Transfer error: {e}", file=sys.stderr)
        return 1


def _download_gen4(
    client: AsperaNodeClient,
    file_id: str,
    remote_paths: list[str],
    local_dest: str,
    resume: bool = False,
    multi_session: int = 1,
    quiet: bool = False,
) -> int:
    """Execute gen4 download transfer.

    
    1. Find common root of paths
    2. Build gen4 transfer spec
    3. Execute ascp

    Args:
        client: AsperaNodeClient instance.
        file_id: Root file ID for the transfer.
        remote_paths: List of remote paths to download.
        local_dest: Local destination directory.
        resume: Enable resume.
        multi_session: Number of concurrent sessions.
        quiet: Suppress output.

    Returns:
        Exit code from ascp.
    """
    # Build paths for transfer spec
    path_dicts = [{"source": p} for p in remote_paths]

    common_root, source_paths = find_common_root(path_dicts)

    # Resolve the common root to a file_id
    if common_root:
        try:
            resolved = client.resolve_fid(file_id, "/".join(common_root))
            transfer_file_id = resolved["file_id"]
        except AsperaApiError:
            transfer_file_id = file_id
    else:
        transfer_file_id = file_id

    # Get transport params from API
    try:
        info = client.get_info()
        remote_user = info.get("transfer_user", "xfer")
        ssh_port = 33001
        fasp_port = 33001
    except Exception:
        remote_user = "xfer"
        ssh_port = 33001
        fasp_port = 33001

    # Build gen4 transfer spec
    transfer_spec = build_transfer_spec_gen4(
        remote_host=urllib.parse.urlparse(client.base_url).hostname or "",
        remote_user=remote_user,
        ssh_port=ssh_port,
        fasp_port=fasp_port,
        access_key=client.user or "",
        file_id=transfer_file_id,
        paths=source_paths,
        direction=DIRECTION_RECEIVE,
        destination_root=local_dest,
    )

    # Add dynamic key if available
    if client._dynamic_key:
        AsperaNodeClient.add_private_key_to_spec(transfer_spec, client._dynamic_key)

    # Fix resume policy
    if resume:
        transfer_spec["resume_policy"] = "sparse_csum"

    # Build ascp command from transfer spec
    return _execute_transfer_spec(
        transfer_spec=transfer_spec,
        local_dest=local_dest,
        multi_session=multi_session,
        quiet=quiet,
        resume=resume,
    )


def _execute_transfer_spec(
    transfer_spec: dict[str, Any],
    local_dest: str,
    multi_session: int = 1,
    quiet: bool = False,
    resume: bool = False,
) -> int:
    """Execute ascp from a transfer spec dict.

    .start_transfer.

    Args:
        transfer_spec: Transfer spec dict.
        local_dest: Local destination.
        multi_session: Number of sessions.
        quiet: Quiet mode.
        resume: Enable resume policy.

    Returns:
        Exit code.
    """
    remote_host = transfer_spec.get("remote_host", "")
    remote_user = transfer_spec.get("remote_user", "xfer")
    ssh_port = transfer_spec.get("ssh_port", 33001)
    fasp_port = transfer_spec.get("fasp_port", 33001)
    token = transfer_spec.get("token", "")
    ssh_private_key = transfer_spec.get("ssh_private_key")
    paths = transfer_spec.get("paths", [])
    source_root = transfer_spec.get("source_root", "")
    resume_policy = transfer_spec.get("resume_policy", "sparse_csum")

    if not remote_host or not token:
        raise RuntimeError("Transfer spec missing required fields: remote_host, token")

    file_list_path, remote_path = build_file_list(paths, source_root)

    cmd, env = _build_ascp_command(
        token=token,
        remote_host=remote_host,
        remote_user=remote_user,
        ssh_port=ssh_port,
        fasp_port=fasp_port,
        remote_path=remote_path,
        local_dest=local_dest,
        multi_session=multi_session,
        quiet=quiet,
        file_list=file_list_path,
        ssh_private_key=ssh_private_key,
        resume=resume,
        resume_policy=resume_policy,
    )

    os.makedirs(local_dest, exist_ok=True)

    return _execute_ascp(
        cmd=cmd,
        env=env,
        file_list_path=file_list_path,
        quiet=quiet,
    )


def _download_with_output_redirect(
    token_data: dict[str, Any],
    local_dest: str,
    resume: bool = False,
    multi_session: int = 1,
) -> int:
    """Execute download, redirecting stdout/stderr to stderr for clean JSON stdout."""

    transfer_specs_list = token_data.get("transfer_specs", [])
    if transfer_specs_list:
        spec = transfer_specs_list[0].get("transfer_spec", {})
    else:
        spec = {}

    remote_host = spec.get("remote_host", "")
    remote_user = spec.get("remote_user", "xfer")
    ssh_port = spec.get("ssh_port", 33001)
    fasp_port = spec.get("fasp_port", 33001)
    token = spec.get("token", "")
    source_root = spec.get("source_root", "")
    paths = spec.get("paths", [])

    file_list_path, remote_path = build_file_list(paths, source_root)

    if (not remote_path and not file_list_path) or not remote_host:
        raise RuntimeError("Could not build ascp command. API response missing required transfer specs.")

    cmd, env = _build_ascp_command(
        token=token,
        remote_host=remote_host,
        remote_user=remote_user,
        ssh_port=ssh_port,
        fasp_port=fasp_port,
        remote_path=remote_path,
        local_dest=local_dest,
        resume=resume,
        file_list=file_list_path,
        ssh_private_key=spec.get("ssh_private_key"),
        multi_session=multi_session,
        quiet=True,
    )

    os.makedirs(local_dest, exist_ok=True)

    return _execute_ascp(
        cmd=cmd,
        env=env,
        file_list_path=file_list_path,
        quiet=True,
        redirect_stdout=True,
    )
