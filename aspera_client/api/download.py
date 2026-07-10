"""High-level Python API for downloading files from Aspera node."""

from __future__ import annotations

import os
import time
import urllib.parse
import sys
from typing import Any

from ..core.connection import AsperaConnection
from ..core.exceptions import AsperaApiError
from ..models.environment import AsperaEnvironment
from ..core.transfer import (
    DIRECTION_RECEIVE,
    DEFAULT_TRANSFER_TIMEOUT,
    _build_ascp_command,
    _execute_ascp,
    build_file_list,
    build_transfer_spec_gen4,
    download_with_progress,
    extract_spec,
    find_common_root,
)


def _execute_transfer_spec(
    transfer_spec: dict[str, Any],
    local_dest: str,
    multi_session: int = 1,
    quiet: bool = False,
    resume: bool = False,
    max_retries: int = 3,
    transfer_timeout: int | None = None,
    https_fallback: bool = True,
    fallback_port: int | None = None,
    env: AsperaEnvironment | None = None,
) -> int:
    """Execute ascp from a transfer spec dict."""
    env = env or AsperaEnvironment()

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

    cmd, env_vars = _build_ascp_command(
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
        bypass_key=env.bypass_key_path if os.path.exists(env.bypass_key_path) else None,
        http_fallback=https_fallback,
        fallback_key=env.fallback_key_path
        if os.path.exists(env.fallback_key_path)
        else None,
        fallback_cert=env.fallback_cert_path
        if os.path.exists(env.fallback_cert_path)
        else None,
        fallback_port=fallback_port,
    )

    os.makedirs(local_dest, exist_ok=True)

    return _execute_ascp(
        cmd=cmd,
        env=env_vars,
        file_list_path=file_list_path,
        quiet=quiet,
        max_retries=max_retries,
        transfer_timeout=transfer_timeout,
    )


def _download_with_output_redirect(
    token_data: dict[str, Any],
    local_dest: str,
    resume: bool = False,
    multi_session: int = 1,
    max_retries: int = 3,
    transfer_timeout: int | None = None,
    env: AsperaEnvironment | None = None,
) -> int:
    """Execute download, redirecting stdout/stderr to stderr for clean JSON stdout."""
    env = env or AsperaEnvironment()

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
        raise RuntimeError(
            "Could not build ascp command. API response missing required transfer specs."
        )

    api_fallback_port = token_data.get(
        "https_fallback_port", spec.get("https_fallback_port")
    )
    fallback_enabled = os.path.exists(env.fallback_key_path) and os.path.exists(
        env.fallback_cert_path
    )
    cmd, env_vars = _build_ascp_command(
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
        bypass_key=env.bypass_key_path if os.path.exists(env.bypass_key_path) else None,
        http_fallback=fallback_enabled,
        fallback_key=env.fallback_key_path
        if os.path.exists(env.fallback_key_path)
        else None,
        fallback_cert=env.fallback_cert_path
        if os.path.exists(env.fallback_cert_path)
        else None,
        fallback_port=api_fallback_port,
    )

    os.makedirs(local_dest, exist_ok=True)

    return _execute_ascp(
        cmd=cmd,
        env=env_vars,
        file_list_path=file_list_path,
        quiet=True,
        redirect_stdout=True,
        max_retries=max_retries,
        transfer_timeout=transfer_timeout,
    )


def _download_gen4(
    client: AsperaConnection,
    file_id: str,
    remote_paths: list[str],
    local_dest: str,
    resume: bool = False,
    multi_session: int = 1,
    quiet: bool = False,
    max_retries: int = 3,
    transfer_timeout: int | None = None,
    https_fallback: bool = False,
    fallback_port: int | None = None,
) -> int:
    """Execute gen4 download transfer."""
    path_dicts = [{"source": p} for p in remote_paths]

    common_root, source_paths = find_common_root(path_dicts)

    if common_root:
        try:
            resolved = client.resolve_fid(file_id, "/".join(common_root))
            transfer_file_id = resolved["file_id"]
        except AsperaApiError:
            transfer_file_id = file_id
    else:
        transfer_file_id = file_id

    try:
        info = client.get_info()
        remote_user = info.get("transfer_user", "xfer")
        ssh_port = 33001
        fasp_port = 33001
    except Exception:
        remote_user = "xfer"
        ssh_port = 33001
        fasp_port = 33001

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

    if client._dynamic_key:
        AsperaConnection.add_private_key_to_spec(transfer_spec, client._dynamic_key)

    if resume:
        transfer_spec["resume_policy"] = "sparse_csum"

    return _execute_transfer_spec(
        transfer_spec=transfer_spec,
        local_dest=local_dest,
        multi_session=multi_session,
        quiet=quiet,
        resume=resume,
        max_retries=max_retries,
        transfer_timeout=transfer_timeout,
        https_fallback=https_fallback,
        fallback_port=fallback_port,
        env=client.env,
    )


def download(
    client: AsperaConnection,
    remote_paths: list[str] | str,
    local_dest: str,
    dry_run: bool = False,
    resume: bool = False,
    multi_session: int = 1,
    use_gen4: bool = False,
    file_id: str | None = None,
    max_retries: int = 3,
    transfer_timeout: int | None = None,
    quiet: bool = True,
    verbose: bool = False,
    output_format: str = "text",
    private_key: str | None = None,
    private_key_file: str | None = None,
    ascp_path_override: str | None = None,
) -> dict[str, Any]:
    """Download files and folders from remote node."""
    if isinstance(remote_paths, str):
        remote_paths = [remote_paths]

    ascp_path = ascp_path_override or client.env.ascp_path
    if not os.path.exists(ascp_path):
        raise FileNotFoundError(
            f"Aspera ascp not found at {ascp_path}. "
            "Please run install_tools() or install Aspera Connect SDK first."
        )

    dynamic_key = private_key
    if not dynamic_key and private_key_file:
        with open(private_key_file, "r", encoding="utf-8") as f:
            dynamic_key = f.read().strip()

    if dynamic_key:
        client._dynamic_key = dynamic_key

    results: list[dict[str, Any]] = []
    total_start = time.time()
    effective_transfer_timeout = (
        transfer_timeout if transfer_timeout is not None else DEFAULT_TRANSFER_TIMEOUT
    )

    for remote_path in remote_paths:
        if not quiet:
            print(f"Requesting download token for: {remote_path}", file=sys.stderr)

        if dry_run:
            token_data = client.get_download_token(
                remote_path=remote_path,
                local_dest=local_dest,
            )
            spec = extract_spec(token_data)
            if not quiet:
                print()
                print(f"=== Dry Run: {remote_path} ===")
                print(f"  remote_host: {spec.get('remote_host', '')}")
                print(f"  remote_user: {spec.get('remote_user', '')}")
                print(f"  ssh_port:    {spec.get('ssh_port', 33001)}")
                print(f"  fasp_port:   {spec.get('fasp_port', 33001)}")
                print(f"  source_root: {spec.get('source_root', '')}")
                print("  paths:")
                for p in spec.get("paths", []):
                    print(f"    - {p.get('source')}")
                print(f"  destination_root: {spec.get('destination_root', '')}")
                print()
            return_code = 0
            start_time = time.time()
        elif use_gen4 and file_id:
            start_time = time.time()
            return_code = _download_gen4(
                client=client,
                file_id=file_id,
                remote_paths=[remote_path],
                local_dest=local_dest,
                resume=resume,
                multi_session=multi_session,
                quiet=quiet,
                max_retries=max_retries,
                transfer_timeout=effective_transfer_timeout,
            )
        elif output_format == "json":
            token_data = client.get_download_token(
                remote_path=remote_path,
                local_dest=local_dest,
            )
            start_time = time.time()
            return_code = _download_with_output_redirect(
                token_data=token_data,
                local_dest=local_dest,
                resume=resume,
                multi_session=multi_session,
                max_retries=max_retries,
                transfer_timeout=effective_transfer_timeout,
                env=client.env,
            )
        else:
            token_data = client.get_download_token(
                remote_path=remote_path,
                local_dest=local_dest,
            )
            start_time = time.time()
            spec = extract_spec(token_data)
            return_code = download_with_progress(
                token_data=token_data,
                local_dest=local_dest,
                resume=resume,
                multi_session=multi_session,
                quiet=quiet,
                verbose=verbose,
                ssh_private_key=spec.get("ssh_private_key"),
                bypass_key=client.env.bypass_key_path
                if os.path.exists(client.env.bypass_key_path)
                else None,
                http_fallback=True,
                fallback_key=client.env.fallback_key_path
                if os.path.exists(client.env.fallback_key_path)
                else None,
                fallback_cert=client.env.fallback_cert_path
                if os.path.exists(client.env.fallback_cert_path)
                else None,
                max_retries=max_retries,
                transfer_timeout=effective_transfer_timeout,
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

        if not quiet:
            if return_code != 0:
                print(f"\nDownload failed for: {remote_path}", file=sys.stderr)
            else:
                print(
                    f"\nDownload completed successfully: {remote_path}", file=sys.stderr
                )

    total_status = "success"
    success_count = sum(1 for r in results if r["status"] == "success")
    if success_count == 0:
        total_status = "failed"
    elif success_count < len(results):
        total_status = "partial_failure"

    return {
        "status": total_status,
        "results": results,
        "elapsed": time.time() - total_start,
    }
