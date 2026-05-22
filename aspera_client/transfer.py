"""Aspera transfer module with progress display."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from typing import Any

# Default path to Aspera Connect installer
ASPERA_CONNECT_DIR = os.path.expanduser("~/.aspera/connect")
ASPERA_ASCP = os.path.join(ASPERA_CONNECT_DIR, "bin", "ascp")

 # Default transfer spec constants
DEFAULT_REMOTE_USER = "xfer"
DEFAULT_SSH_PORT = 33001
DEFAULT_FASP_PORT = 33001


def _extract_spec(token_data: dict[str, Any]) -> dict[str, Any]:
    """Extract transfer spec from API response."""
    transfer_specs_list = token_data.get("transfer_specs", [])
    if transfer_specs_list:
        return transfer_specs_list[0].get("transfer_spec", {})
    return {}


def _build_file_list(paths: list[dict[str, Any]], source_root: str = "") -> tuple[str | None, str]:
    """Build file list for multiple paths.

    If multiple sources exist, writes them to a temp file and returns the path.
    Otherwise returns the single source path.

    Args:
        paths: List of path dicts with 'source' key.
        source_root: Source root prefix to prepend to paths.

    Returns:
        Tuple of (file_list_path, remote_path).
        file_list_path is None for single-path, or temp file path for multi-path.
        remote_path is the single source path for single-path, or empty string for multi-path.
    """
    sources = [p.get("source", "") for p in paths if p.get("source")]
    if not sources:
        return None, ""

    if len(sources) > 1:
        fd, file_list_path = tempfile.mkstemp(prefix="aspera_filelist_", suffix=".txt")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for s in sources:
                    if source_root and s:
                        full_path = source_root.rstrip("/") + "/" + s.lstrip("/")
                    else:
                        full_path = s
                    f.write(full_path + "\n")
            return file_list_path, ""
        except Exception as e:
            try:
                os.close(fd)
            except OSError:
                pass
            print(f"Error creating file list: {e}", file=sys.stderr)
            return None, ""
    else:
        remote_path = sources[0]
        if source_root and remote_path:
            remote_path = source_root.rstrip("/") + "/" + remote_path.lstrip("/")
        return None, remote_path


def _build_ascp_command(
    token: str,
    remote_host: str,
    remote_user: str,
    ssh_port: int,
    fasp_port: int | None = None,
    remote_path: str = "",
    local_dest: str = "",
    resume: bool = False,
    multi_session: int = 1,
    quiet: bool = False,
    file_list: str | None = None,
    ssh_private_key: str | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Build the ascp command.

    Order: -q, -T -P -O -W, -R, --file-list, SRC..., DEST

    Args:
        token: Transfer token from the Node API.
        remote_host: Remote Aspera node hostname.
        remote_user: Remote username for ascp.
        ssh_port: SSH port for control connection.
        fasp_port: UDP port for FASP data transfer.
        remote_path: Remote file path.
        local_dest: Local destination directory.
        resume: Enable transfer resume policy.
        multi_session: Number of concurrent sessions (1=disabled).
        quiet: Suppress ascp progress bar output.
        file_list: Path to temp file containing source file list.
        ssh_private_key: PEM-encoded private key for dynamic key auth.

    Returns:
        Tuple of (ascp command args, environment variables).
    """
    if fasp_port is None:
        fasp_port = ssh_port

    env: dict[str, str] = {}
    cmd = [ASPERA_ASCP]

    # 1. Quiet mode (suppresses native progress bar; we handle progress ourselves)
    if quiet:
        cmd.append("-q")

    # 2. Transfer spec parameters (token, ports)
    if multi_session > 1:
        # Multi-session: per-session -O flags only (no base -O)
        cmd.extend([
            "-T",
            "-P", str(ssh_port),
            "-W", token,
        ])
        for i in range(multi_session):
            udp_port = fasp_port + i
            cmd.extend([
                "-C", f"{i + 1}:{multi_session}",
                "-O", str(udp_port),
            ])
    else:
        # Single session: base -O flag
        cmd.extend([
            "-T",
            "-P", str(ssh_port),
            "-O", str(fasp_port),
            "-W", token,
        ])

    # 3. Set SSH private key for dynamic key auth (ascp reads this env var)
    if ssh_private_key:
        env["ASPERA_SCP_SSH_PRIVATE_KEY"] = ssh_private_key

    # 5. Resume transfer
    if resume:
        cmd.append("-R")

    # 6. File list
    if file_list:
        cmd.extend(["--file-list", file_list])

    # 7. SRC then DEST (ascp format: ascp [OPTION] SRC... DEST)
    if remote_path:
        cmd.append(f"{remote_user}@{remote_host}:{remote_path}")

    # 8. Destination (MUST be last argument)
    cmd.append(local_dest)

    return cmd, env


def download_with_progress(
    token_data: dict[str, Any],
    local_dest: str,
    resume: bool = False,
    multi_session: int = 1,
    quiet: bool = False,
    ssh_private_key: str | None = None,
) -> int:
    """Execute ascp transfer with real-time progress display.

    Args:
        token_data: Response from /files/download_setup API call.
        local_dest: Local destination directory.
        resume: Enable transfer resume policy.
        multi_session: Number of concurrent sessions (1=disabled).
        quiet: Suppress ascp progress bar output.
        ssh_private_key: PEM-encoded private key for dynamic key auth.

    Returns:
        Exit code from ascp (0 on success).

    Raises:
        FileNotFoundError: If ascp binary not found.
        RuntimeError: If transfer fails.
    """
    if not os.path.exists(ASPERA_ASCP):
        raise FileNotFoundError(
            f"Ascp binary not found at {ASPERA_ASCP}. "
            "Please install Aspera Connect SDK first."
        )

    # Extract transfer specs from API response (nested per OpenAPI spec)
    # Response shape: {"transfer_specs": [{"transfer_spec": {...}}]}
    transfer_specs_list = token_data.get("transfer_specs", [])
    if transfer_specs_list:
        spec = transfer_specs_list[0].get("transfer_spec", {})
    else:
        spec = {}

    remote_host = spec.get("remote_host", "")
    remote_user = spec.get("remote_user", DEFAULT_REMOTE_USER)
    ssh_port = spec.get("ssh_port", DEFAULT_SSH_PORT)
    fasp_port = spec.get("fasp_port", DEFAULT_FASP_PORT)
    token = spec.get("token", "")
    ssh_private_key = ssh_private_key or spec.get("ssh_private_key")

    # Get remote paths from the response
    # paths[].source is relative to source_root per OpenAPI spec
    source_root = spec.get("source_root", "")
    paths = spec.get("paths", [])

    file_list_path, remote_path = _build_file_list(paths, source_root)

    # Build ascp command
    if (remote_path and remote_host) or file_list_path:
        cmd, env = _build_ascp_command(
            token=token,
            remote_host=remote_host,
            remote_user=remote_user,
            ssh_port=ssh_port,
            fasp_port=fasp_port,
            remote_path=remote_path,
            local_dest=local_dest,
            resume=resume,
            multi_session=multi_session,
            quiet=quiet,
            file_list=file_list_path,
            ssh_private_key=ssh_private_key,
        )
    else:
        raise RuntimeError(
            "Could not build ascp command. "
            "API response missing required transfer specs."
        )

    # Ensure destination directory exists
    os.makedirs(local_dest, exist_ok=True)

    print("Starting Aspera transfer...", file=sys.stderr)
    redacted_cmd = []
    for i, part in enumerate(cmd):
        if i > 0 and cmd[i - 1] == "-W":
            redacted_cmd.append("***")
        else:
            redacted_cmd.append(part)
    print(f"  Command: {' '.join(redacted_cmd)}", file=sys.stderr)
    if env:
        print(f"  Environment: {dict((k, '***' if k in ('ASPERA_SCP_TOKEN', 'ASPERA_SCP_SSH_PRIVATE_KEY') else v) for k, v in env.items())}", file=sys.stderr)
    print(file=sys.stderr)

    start_time = time.time()

    return_code = _execute_ascp(
        cmd=cmd,
        env=env,
        file_list_path=file_list_path,
        quiet=quiet,
    )

    if return_code == 0:
        elapsed = time.time() - start_time
        print(f"\nTransfer completed successfully! ({elapsed:.1f}s)")
    else:
        print(f"\nTransfer failed with exit code {return_code}")

    return return_code


def _execute_ascp(
    cmd: list[str],
    env: dict[str, str],
    file_list_path: str | None,
    quiet: bool = False,
    redirect_stdout: bool = False,
) -> int:
    """Execute ascp with optional stdout/stderr redirection.

    Args:
        cmd: The ascp command list.
        env: Environment variables to merge.
        file_list_path: Path to temp file list for cleanup.
        quiet: Suppress completion messages.
        redirect_stdout: If True, redirect stdout/stderr to a single stream.

    Returns:
        Exit code from ascp.
    """
    merged_env = os.environ.copy()
    merged_env.update(env)

    popen_kwargs: dict[str, Any] = {"env": merged_env}
    if redirect_stdout:
        popen_kwargs["stdout"] = subprocess.STDOUT
        popen_kwargs["stderr"] = subprocess.STDOUT

    process = subprocess.Popen(cmd, **popen_kwargs)

    try:
        process.wait()
    except KeyboardInterrupt:
        if not redirect_stdout:
            print("\nTransfer interrupted by user.", file=sys.stderr)
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        return 130

    if file_list_path:
        try:
            os.unlink(file_list_path)
        except OSError:
            pass

    if not quiet and not redirect_stdout:
        if process.returncode == 0:
            print("\nTransfer completed successfully!")
        else:
            print(f"\nTransfer failed with exit code {process.returncode}")

    return process.returncode
