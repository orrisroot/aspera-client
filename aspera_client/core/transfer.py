"""Aspera transfer module with progress display."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from typing import Any, TypeVar

from .connection import AsperaConnection

find_common_root = AsperaConnection.find_common_root

# Default path to Aspera Connect installer
ASPERA_CONNECT_DIR = os.path.expanduser("~/.aspera/connect")
ASPERA_ASCP = os.path.join(ASPERA_CONNECT_DIR, "bin", "ascp")

# Key file names in client directory
_BYPASS_KEY_NAME = "aspera_bypass_rsa.pem"
_FALLBACK_KEY_NAME = "aspera_fallback_cert_private_key.pem"
_FALLBACK_CERT_NAME = "aspera_fallback_cert.pem"

_CLIENT_DIR = os.path.join(ASPERA_CONNECT_DIR, "client")


def _resolve_sdk_key(filename: str) -> str | None:
    """Resolve path to a client key file if it exists.

    Args:
        filename: Name of the key file in the client directory.

    Returns:
        Full path to the key file, or None if not found.
    """
    key_path = os.path.join(_CLIENT_DIR, filename)
    return key_path if os.path.exists(key_path) else None


def get_bypass_key_path() -> str | None:
    """Get path to the installed bypass key, if available.

    Returns:
        Full path to bypass key, or None.
    """
    return _resolve_sdk_key(_BYPASS_KEY_NAME)


def get_fallback_key_path() -> str | None:
    """Get path to the installed fallback private key, if available.

    Returns:
        Full path to fallback key, or None.
    """
    return _resolve_sdk_key(_FALLBACK_KEY_NAME)


def get_fallback_cert_path() -> str | None:
    """Get path to the installed fallback certificate, if available.

    Returns:
        Full path to fallback certificate, or None.
    """
    return _resolve_sdk_key(_FALLBACK_CERT_NAME)


# Default transfer spec constants
DEFAULT_REMOTE_USER = "xfer"
DEFAULT_SSH_PORT = 33001
DEFAULT_FASP_PORT = 33001

# Retry defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF = 2.0
DEFAULT_RETRY_JITTER = 0.5

# Default transfer timeout in seconds (2 minutes — keeps unreachable-host hangs bounded)
DEFAULT_TRANSFER_TIMEOUT = 120

# ascp exit code descriptions
ASCP_EXIT_CODES: dict[int, str] = {
    0: "Success",
    1: "General error",
    2: "Usage error (invalid arguments)",
    3: "Network error — unable to connect to remote host",
    4: "Authentication failure",
    5: "Transfer rate too low — connection dropped",
    6: "Remote file not found",
    7: "Remote permission denied",
    8: "Local disk full",
    9: "Local permission denied",
    10: "Transfer cancelled by user",
    11: "Remote server error",
    12: "Token expired or invalid",
    13: "FASP handshake failure",
    14: "SSL/TLS error",
    15: "File lock conflict",
    130: "Interrupted by signal (Ctrl+C)",
}

# Exit codes that are safe to retry on
# Note: exit code 1 (General error) is NOT included because it can mask auth failures
RETRYABLE_EXIT_CODES = {3, 5, 11, 12, 13, 14}


T = TypeVar("T")


def get_ascp_path() -> str:
    """Resolve ascp binary path.

    Priority: ASPERA_ASCP env var > ~/.aspera/connect/bin/ascp > system PATH.
    """
    # Check environment variable override
    env_path = os.environ.get("ASPERA_ASCP")
    if env_path and os.path.exists(env_path):
        return env_path

    # Check default install location
    if os.path.exists(ASPERA_ASCP):
        return ASPERA_ASCP

    # Search system PATH
    import shutil

    found = shutil.which("ascp")
    if found:
        return found

    return ASPERA_ASCP


def get_ascp_error_message(exit_code: int) -> str:
    """Get human-readable error message for an ascp exit code."""
    if exit_code in ASCP_EXIT_CODES:
        return ASCP_EXIT_CODES[exit_code]
    return f"Unknown error (exit code {exit_code})"


DIRECTION_SEND = "send"
DIRECTION_RECEIVE = "receive"

POLICY_FIX = {
    "none": "none",
    "attrs": "attributes",
    "sparse_csum": "sparse_checksum",
    "full_csum": "full_checksum",
}

# ascp -k resume level mapping (IBM docs: -k {0|1|2|3})
ASCP_RESUME_LEVEL = {
    "none": "0",
    "attributes": "1",
    "sparse_checksum": "2",
    "full_checksum": "3",
}


def fix_resume_policy(transfer_spec: dict[str, Any]) -> dict[str, Any]:
    """Fix resume policy discrepancy between gen3 and gen4.

    .fix_transferd_resume_policy.
    """
    if "resume_policy" in transfer_spec:
        policy = transfer_spec["resume_policy"]
        if policy in POLICY_FIX:
            transfer_spec["resume_policy"] = POLICY_FIX[policy]
    return transfer_spec


# -------------------------------------------------------------------------
# -------------------------------------------------------------------------


def build_transfer_spec_gen3(
    remote_host: str,
    remote_user: str,
    ssh_port: int,
    fasp_port: int,
    token: str,
    paths: list[dict[str, Any]],
    direction: str = DIRECTION_RECEIVE,
    destination_root: str = "",
    resume_policy: str = "sparse_csum",
    create_dir: bool = True,
    extra_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a gen3-style transfer spec dict.

    .

    Args:
        remote_host: Remote Aspera node hostname.
        remote_user: Remote transfer user.
        ssh_port: SSH port.
        fasp_port: FASP UDP port.
        token: Transfer token.
        paths: List of path dicts with 'source' key.
        direction: 'send' or 'receive'.
        destination_root: Local destination directory.
        resume_policy: Resume policy.
        create_dir: Create destination directory.
        extra_spec: Additional transfer spec fields to merge.

    Returns:
        Transfer spec dict.
    """
    spec: dict[str, Any] = {
        "direction": direction,
        "token": token,
        "remote_host": remote_host,
        "remote_user": remote_user,
        "ssh_port": ssh_port,
        "fasp_port": fasp_port,
        "paths": paths,
        "create_dir": create_dir,
        "resume_policy": resume_policy,
    }

    if destination_root:
        spec["destination_root"] = destination_root

    if extra_spec:
        spec.update(extra_spec)

    return spec


def build_transfer_spec_gen4(
    remote_host: str,
    remote_user: str,
    ssh_port: int,
    fasp_port: int,
    access_key: str,
    file_id: str,
    paths: list[dict[str, Any]],
    direction: str = DIRECTION_RECEIVE,
    destination_root: str = "",
    extra_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a gen4-style transfer spec dict.

    .transfer_spec_gen4.

    Args:
        remote_host: Remote Aspera node hostname.
        remote_user: Remote transfer user.
        ssh_port: SSH port.
        fasp_port: FASP UDP port.
        access_key: Access key identifier.
        file_id: Source folder file ID.
        paths: List of path dicts.
        direction: 'send' or 'receive'.
        destination_root: Local destination directory.
        extra_spec: Additional transfer spec fields.

    Returns:
        Transfer spec dict.
    """
    spec: dict[str, Any] = {
        "direction": direction,
        "token": access_key,
        "remote_host": remote_host,
        "remote_user": remote_user,
        "ssh_port": ssh_port,
        "fasp_port": fasp_port,
        "paths": paths,
        "create_dir": True,
        "resume_policy": "sparse_csum",
        "tags": {
            "aspera": {
                "node": {
                    "access_key": access_key,
                    "file_id": file_id,
                }
            }
        },
    }

    if destination_root:
        spec["destination_root"] = destination_root

    if extra_spec:
        spec.update(extra_spec)

    return spec


# -------------------------------------------------------------------------
# -------------------------------------------------------------------------


def build_file_list(
    paths: list[dict[str, Any]],
    source_root: str = "",
) -> tuple[str | None, str]:
    """Build file list for multiple paths.

    If multiple sources exist, writes them to a temp file and returns the path.
    Otherwise returns the single source path.

    .

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


# -------------------------------------------------------------------------
# ascp command building
# -------------------------------------------------------------------------


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
    verbose: bool = False,
    file_list: str | None = None,
    ssh_private_key: str | None = None,
    resume_policy: str = "sparse_csum",
    bypass_key: str | None = None,
    http_fallback: bool = False,
    fallback_key: str | None = None,
    fallback_cert: str | None = None,
    fallback_port: int | None = None,
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
        resume_policy: Resume policy (sparse_csum, full_csum, etc.).
        bypass_key: Path to bypass key file for token auth.
        http_fallback: Enable HTTP fallback mode.
        fallback_key: Path to fallback private key file.
        fallback_cert: Path to fallback certificate file.
        fallback_port: HTTP fallback server port (default: 443, None=auto).

    Returns:
        Tuple of (ascp command args, environment variables).
    """
    if fasp_port is None:
        fasp_port = ssh_port

    env: dict[str, str] = {}
    cmd = [get_ascp_path()]

    # 1. Quiet mode (suppresses native progress bar; we handle progress ourselves)
    if quiet:
        cmd.append("-q")

    # Verbose mode (enables detailed ascp output)
    if verbose:
        cmd.append("-v")

    # 2. Transfer spec parameters (token, ports)
    if multi_session > 1:
        # Multi-session: per-session -O flags only (no base -O)
        cmd.extend(
            [
                "-T",
                "-P",
                str(ssh_port),
                "-W",
                token,
            ]
        )
        for i in range(multi_session):
            udp_port = fasp_port + i
            cmd.extend(
                [
                    "-C",
                    f"{i + 1}:{multi_session}",
                    "-O",
                    str(udp_port),
                ]
            )
    else:
        # Single session: base -O flag
        cmd.extend(
            [
                "-T",
                "-P",
                str(ssh_port),
                "-O",
                str(fasp_port),
                "-W",
                token,
            ]
        )

    # 3. Set SSH private key for dynamic key auth (ascp reads this env var)
    if ssh_private_key:
        env["ASPERA_SCP_SSH_PRIVATE_KEY"] = ssh_private_key

    # 4. Add bypass key for token authentication (ascp -i flag)
    if bypass_key and os.path.exists(bypass_key):
        cmd.insert(2, bypass_key)
        cmd.insert(2, "-i")

    # Only add -k when resume=True (user explicitly requested resume)
    if resume:
        fixed = fix_resume_policy({"resume_policy": resume_policy})["resume_policy"]
        k_level = ASCP_RESUME_LEVEL.get(fixed, "0")
        cmd.extend(["-k", k_level])

    # 5. File list
    if file_list:
        cmd.extend(["--file-list", file_list])

    # 6. HTTP fallback (ascp -y, -I, -t flags)
    # Note: -y 1 enables HTTP fallback (binary toggle, not a timeout)
    # -Y does NOT exist in ascp — the fallback private key is not used by ascp
    if http_fallback:
        cmd.append("-y")
        cmd.append("1")
        if fallback_cert and os.path.exists(fallback_cert):
            cmd.insert(2, fallback_cert)
            cmd.insert(2, "-I")
        port = fallback_port if fallback_port is not None else 443
        cmd.extend(["-t", str(port)])

    # 6. SRC then DEST (ascp format: ascp [OPTION] SRC... DEST)
    if remote_path:
        cmd.append(f"{remote_user}@{remote_host}:{remote_path}")

    # 7. Destination (MUST be last argument)
    cmd.append(local_dest)

    return cmd, env


# -------------------------------------------------------------------------
# Extract spec from API response
# -------------------------------------------------------------------------


def extract_spec(token_data: dict[str, Any]) -> dict[str, Any]:
    """Extract transfer spec from API response.

    .
    """
    transfer_specs_list = token_data.get("transfer_specs", [])
    if transfer_specs_list:
        return transfer_specs_list[0].get("transfer_spec", {})
    return {}


# -------------------------------------------------------------------------
# Transfer execution
# -------------------------------------------------------------------------


def download_with_progress(
    token_data: dict[str, Any],
    local_dest: str,
    resume: bool = False,
    multi_session: int = 1,
    quiet: bool = False,
    verbose: bool = False,
    ssh_private_key: str | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    transfer_timeout: int | None = None,
    bypass_key: str | None = None,
    http_fallback: bool = False,
    fallback_key: str | None = None,
    fallback_cert: str | None = None,
) -> int:
    """Execute ascp transfer with real-time progress display.

    Args:
        token_data: Response from /files/download_setup API call.
        local_dest: Local destination directory.
        resume: Enable transfer resume policy.
        multi_session: Number of concurrent sessions (1=disabled).
        quiet: Suppress ascp progress bar output.
        ssh_private_key: PEM-encoded private key for dynamic key auth.
        max_retries: Maximum number of retry attempts on transient failure.
        transfer_timeout: Transfer timeout in seconds (None=no timeout).
        bypass_key: Path to bypass key file for token auth.
        http_fallback: Enable HTTP fallback mode.
        fallback_key: Path to fallback private key file.
        fallback_cert: Path to fallback certificate file.

    Returns:
        Exit code from ascp (0 on success).

    Raises:
        FileNotFoundError: If ascp binary not found.
        RuntimeError: If transfer fails.
    """
    ascp_path = get_ascp_path()
    if not os.path.exists(ascp_path):
        raise FileNotFoundError(
            f"Ascp binary not found at {ascp_path}. "
            "Please install Aspera Connect SDK first."
        )

    # Extract transfer specs from API response (nested per OpenAPI spec)
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
    if not ssh_private_key:
        print(
            "Warning: no SSH private key available for authentication. "
            "The server may require a password or the dynamic key setup may be incomplete.",
            file=sys.stderr,
        )
    resume_policy = spec.get("resume_policy", "sparse_csum")

    # Check https_fallback from API response
    api_https_fallback = token_data.get("https_fallback", spec.get("https_fallback"))
    api_fallback_port = token_data.get(
        "https_fallback_port", spec.get("https_fallback_port")
    )
    api_fallback_url = token_data.get(
        "https_fallback_url", spec.get("https_fallback_url")
    )

    # Get remote paths from the response
    source_root = spec.get("source_root", "")
    paths = spec.get("paths", [])

    file_list_path, remote_path = build_file_list(paths, source_root)

    # Build ascp command
    if (remote_path and remote_host) or file_list_path:
        # Determine effective fallback settings: API response takes precedence
        effective_fallback = (
            api_https_fallback if api_https_fallback is not None else http_fallback
        )
        effective_fallback_port = api_fallback_port if api_fallback_port else None

        if effective_fallback and effective_fallback_port:
            print(
                f"  HTTP fallback enabled (port: {effective_fallback_port})",
                file=sys.stderr,
            )
        elif effective_fallback:
            print("  HTTP fallback enabled", file=sys.stderr)
        else:
            print(
                "  HTTP fallback disabled (not supported by server or keys unavailable)",
                file=sys.stderr,
            )
        if api_fallback_url:
            print(f"  Fallback URL: {api_fallback_url}", file=sys.stderr)

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
            verbose=verbose,
            file_list=file_list_path,
            ssh_private_key=ssh_private_key,
            resume_policy=resume_policy,
            bypass_key=bypass_key,
            http_fallback=effective_fallback,
            fallback_key=fallback_key,
            fallback_cert=fallback_cert,
            fallback_port=effective_fallback_port,
        )

        # Log final ascp command with fallback flags (redacted token)
        redacted_cmd = []
        for i, part in enumerate(cmd):
            if i > 0 and cmd[i - 1] == "-W":
                redacted_cmd.append("***")
            else:
                redacted_cmd.append(part)
        print(f"  Final ascp command: {' '.join(redacted_cmd)}", file=sys.stderr)
        if effective_fallback:
            has_fallback_cert = fallback_cert and os.path.exists(fallback_cert)
            print(
                f"  Fallback enabled (cert={'yes' if has_fallback_cert else 'no'}, "
                f"port={effective_fallback_port or 443})",
                file=sys.stderr,
            )
    else:
        raise RuntimeError(
            "Could not build ascp command. "
            "API response missing required transfer specs."
        )

    # Ensure destination directory exists
    os.makedirs(local_dest, exist_ok=True)

    print("Starting Aspera transfer...", file=sys.stderr)
    if env:
        print(
            f"  Environment: {dict((k, '***' if k in ('ASPERA_SCP_TOKEN', 'ASPERA_SCP_SSH_PRIVATE_KEY') else v) for k, v in env.items())}",
            file=sys.stderr,
        )
    print(file=sys.stderr)

    start_time = time.time()

    return_code = _execute_ascp(
        cmd=cmd,
        env=env,
        file_list_path=file_list_path,
        quiet=quiet,
        max_retries=max_retries,
        transfer_timeout=transfer_timeout,
    )

    if return_code == 0:
        elapsed = time.time() - start_time
        print(f"\nTransfer completed successfully! ({elapsed:.1f}s)")
    else:
        error_msg = get_ascp_error_message(return_code)
        print(f"\nTransfer failed with exit code {return_code}: {error_msg}")
        if effective_fallback:
            print(
                "  Fallback was enabled. If FASP failed, check HTTP fallback connectivity "
                f"(port {effective_fallback_port or 443}).",
                file=sys.stderr,
            )

    return return_code


def _execute_ascp(
    cmd: list[str],
    env: dict[str, str],
    file_list_path: str | None,
    quiet: bool = False,
    redirect_stdout: bool = False,
    max_retries: int = DEFAULT_MAX_RETRIES,
    transfer_timeout: int | None = None,
) -> int:
    """Execute ascp with optional stdout/stderr redirection and retry logic.

    Args:
        cmd: The ascp command list.
        env: Environment variables to merge.
        file_list_path: Path to temp file list for cleanup.
        quiet: Suppress completion messages.
        redirect_stdout: If True, redirect stdout/stderr to a single stream.
        max_retries: Maximum number of retry attempts on transient failure.
        transfer_timeout: Transfer timeout in seconds (None=no timeout).

    Returns:
        Exit code from ascp (0 on success).
    """
    merged_env = os.environ.copy()
    merged_env.update(env)

    popen_kwargs: dict[str, Any] = {"env": merged_env}
    if redirect_stdout:
        popen_kwargs["stdout"] = subprocess.STDOUT
        popen_kwargs["stderr"] = subprocess.STDOUT

    last_exit_code: int = 1
    for attempt in range(max_retries + 1):
        process = subprocess.Popen(cmd, **popen_kwargs)

        try:
            if transfer_timeout:
                process.wait(timeout=transfer_timeout)
            else:
                process.wait()
        except subprocess.TimeoutExpired:
            if not quiet:
                print("\nTransfer timed out.", file=sys.stderr)
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            last_exit_code = 1
            if attempt < max_retries:
                delay = DEFAULT_RETRY_BACKOFF**attempt + DEFAULT_RETRY_JITTER * (
                    attempt + 1
                )
                print(
                    f"  Retry {attempt + 1}/{max_retries} after timeout ({delay:.1f}s)",
                    file=sys.stderr,
                )
                time.sleep(delay)
                continue
            return 1

        except KeyboardInterrupt:
            print("\nTransfer interrupted by user.", file=sys.stderr)
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            return 130

        last_exit_code = process.returncode

        if file_list_path:
            try:
                os.unlink(file_list_path)
            except OSError:
                pass

        # Check if exit code is retryable
        if last_exit_code == 0:
            if not quiet and not redirect_stdout:
                print("\nTransfer completed successfully!")
            return 0

        if last_exit_code not in RETRYABLE_EXIT_CODES:
            # Non-retryable error — fail immediately
            if not quiet and not redirect_stdout:
                error_msg = get_ascp_error_message(last_exit_code)
                print(f"\nTransfer failed with exit code {last_exit_code}: {error_msg}")
            return last_exit_code

        if attempt < max_retries:
            delay = DEFAULT_RETRY_BACKOFF**attempt + DEFAULT_RETRY_JITTER * (
                attempt + 1
            )
            print(
                f"  Retry {attempt + 1}/{max_retries} (exit code {last_exit_code}) "
                f"after {delay:.1f}s",
                file=sys.stderr,
            )
            time.sleep(delay)
        else:
            error_msg = get_ascp_error_message(last_exit_code)
            if not quiet and not redirect_stdout:
                print(f"\nTransfer failed with exit code {last_exit_code}: {error_msg}")
            return last_exit_code

    return last_exit_code
