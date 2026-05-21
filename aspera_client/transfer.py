"""Aspera transfer module with progress display."""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any

# Default path to Aspera Connect installer
ASPENA_CONNECT_DIR = os.path.expanduser("~/.aspera/connect")
ASPENA_ASCP = os.path.join(ASPENA_CONNECT_DIR, "bin", "ascp")


def _build_ascp_command(
    token: str,
    remote_host: str,
    remote_user: str,
    ssh_port: int,
    fasp_port: int | None = None,
    remote_path: str = "",
    local_dest: str = "",
    identity_file: str | None = None,
) -> list[str]:
    """Build the ascp command from token and transfer specs.

    Args:
        token: Transfer token from the Node API.
        remote_host: Remote Aspera node hostname.
        remote_user: Remote username for ascp.
        ssh_port: SSH port for control connection.
        fasp_port: UDP port for FASP data transfer (defaults to ssh_port).
        remote_path: Remote file path.
        local_dest: Local destination directory.
        identity_file: Path to Aspera SSH identity key (optional).

    Returns:
        List of ascp command arguments.
    """
    if fasp_port is None:
        fasp_port = ssh_port
    cmd = [ASPENA_ASCP]

    # All options must come before SRC and DEST
    if identity_file and os.path.exists(identity_file):
        cmd.extend(["-i", identity_file])
    # Do NOT add -v or -q — ascp shows progress by default on a TTY
    cmd.extend([
        "-T",        # Enable transfer token
        "-P", str(ssh_port),
        "-O", str(fasp_port),
        "-W", token,
    ])

    # SRC then DEST (ascp format: ascp [OPTION] SRC... DEST)
    cmd.extend([
        f"{remote_user}@{remote_host}:{remote_path}",
        local_dest,
    ])

    return cmd




def download_with_progress(
    token_data: dict[str, Any],
    local_dest: str,
    identity_file: str | None = None,
    ascp_verbose: bool = False,
) -> int:
    """Execute ascp transfer with real-time progress display.

    Args:
        token_data: Response from /files/download_setup API call.
        local_dest: Local destination directory.
        identity_file: Path to Aspera SSH identity key (optional).

    Returns:
        Exit code from ascp (0 on success).

    Raises:
        FileNotFoundError: If ascp binary not found.
        RuntimeError: If transfer fails.
    """
    if not os.path.exists(ASPENA_ASCP):
        raise FileNotFoundError(
            f"Ascp binary not found at {ASPENA_ASCP}. "
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
    remote_user = spec.get("remote_user", "xfer")
    ssh_port = spec.get("ssh_port", 33001)
    fasp_port = spec.get("fasp_port", ssh_port)
    token = spec.get("token", "")

    # Get remote paths from the response
    # paths[].source is relative to source_root per OpenAPI spec
    source_root = spec.get("source_root", "")
    paths = spec.get("paths", [])
    if paths:
        remote_path = paths[0].get("source", "")
        # Prepend source_root to form the full remote path
        if source_root and remote_path:
            remote_path = source_root.rstrip("/") + "/" + remote_path.lstrip("/")
    else:
        remote_path = ""

    # Build ascp command
    if remote_path and remote_host:
        cmd = _build_ascp_command(
            token=token,
            remote_host=remote_host,
            remote_user=remote_user,
            ssh_port=ssh_port,
            fasp_port=fasp_port,
            remote_path=remote_path,
            local_dest=local_dest,
            identity_file=identity_file,
 
        )
    else:
        raise RuntimeError(
            "Could not build ascp command. "
            "API response missing required transfer specs."
        )

    # Ensure destination directory exists
    os.makedirs(local_dest, exist_ok=True)

    print(f"Starting Aspera transfer...")
    print(f"  Command: {' '.join(cmd)}")
    print()

    start_time = time.time()

    # Execute ascp — stdout/stderr inherited from parent terminal
    # ascp writes progress directly to the TTY, not via stdout/stderr pipes
    process = subprocess.Popen(cmd)

    try:
        process.wait()
    except KeyboardInterrupt:
        print("\nTransfer interrupted by user.")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        return 130

    if process.returncode == 0:
        elapsed = time.time() - start_time
        print(f"\nTransfer completed successfully! ({elapsed:.1f}s)")
    else:
        print(f"\nTransfer failed with exit code {process.returncode}")

    return process.returncode


