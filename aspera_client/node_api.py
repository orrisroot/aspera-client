"""IBM Aspera Node API client for authentication, file listing, and token generation."""

from __future__ import annotations

import base64
import json
import sys
import urllib.parse
from typing import Any

import requests

try:
    import cryptography  # noqa: F401
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


class AsperaNodeError(Exception):
    """Base exception for Aspera Node API errors."""


class AsperaAuthError(AsperaNodeError):
    """Authentication failed."""


class AsperaApiError(AsperaNodeError):
    """API returned an error response."""


class AsperaNodeClient:
    """Client for IBM Aspera Node API REST endpoints."""

    def __init__(
        self,
        host: str,
        port: int = 9092,
        user: str | None = None,
        password: str | None = None,
        verify_ssl: bool = True,
        path_prefix: str = "",
        timeout: int = 30,
        dynamic_key: str | None = None,
    ) -> None:
        """Initialize the client.

        Args:
            host: Aspera Node server hostname or IP.
            port: Node API port (default 9092).
            user: Username for Basic authentication.
            password: Password for Basic authentication.
            verify_ssl: Whether to verify SSL certificates.
            path_prefix: URL path prefix (e.g., "/node_api" for servers behind a proxy).
            timeout: Request timeout in seconds (default 30).
            dynamic_key: PEM-encoded RSA private key for dynamic key authentication.
        """
        prefix = path_prefix.rstrip("/") if path_prefix else ""
        base = urllib.parse.urlunsplit(("https", f"{host}:{port}", prefix, "", ""))
        self.base_url = base.rstrip("/")
        self.timeout = timeout
        self.user = user
        self.password = password
        self.verify_ssl = verify_ssl
        self._session = requests.Session()
        self._session.auth = (self.user, self.password) if self.user and self.password else None
        self._session.headers.update({"Accept": "application/json"})
        self._dynamic_key = dynamic_key
        self._cached_public_key: str | None = None

    def _request(
        self,
        method: str,
        path: str,
        json_data: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make an HTTP request and return JSON response.

        Args:
            method: HTTP method (GET, POST, etc.).
            path: API path (e.g., "/files").
            json_data: JSON body for POST/PUT requests.
            **kwargs: Additional arguments passed to requests.

        Returns:
            Parsed JSON response.

        Raises:
            AsperaAuthError: If authentication fails.
            AsperaApiError: If API returns an error.
        """
        url = f"{self.base_url}{path}"
        kwargs.setdefault("verify", self.verify_ssl)
        kwargs.setdefault("timeout", self.timeout)

        if json_data is not None:
            kwargs["json"] = json_data

        response = self._session.request(method, url, **kwargs)

        if response.status_code == 401:
            raise AsperaAuthError(f"Authentication failed: {response.text}")

        if response.status_code == 403:
            raise AsperaAuthError(f"Access forbidden: {response.text}")

        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError):
            data = {}

        if response.status_code >= 400:
            error_msg = data.get("message", data.get("error", response.text))
            raise AsperaApiError(f"API error ({response.status_code}): {error_msg}")

        return data

    def add_public_key(self, payload: dict[str, Any]) -> None:
        """Add public key to download_setup request payload (dynamic key auth).

        Mirrors Ruby's Api::Node.add_public_key.
        Uses cached public key if available to ensure consistency across calls.
        """
        if not self._dynamic_key:
            return
        if self._cached_public_key is None:
            self._cached_public_key, _ = _generate_dynamic_key_from_pem(self._dynamic_key)
        payload.setdefault("public_keys", self._cached_public_key)

    def add_private_key(self, transfer_spec: dict[str, Any]) -> dict[str, Any]:
        """Merge private key into transfer spec (dynamic key auth).

        Mirrors Ruby's Api::Node.add_private_key.
        If API returns ssh_private_key, use it; otherwise use the client's key.

        Returns:
            Updated transfer spec with ssh_private_key set.
        """
        if not self._dynamic_key:
            return transfer_spec

        api_key = transfer_spec.get("ssh_private_key")
        if not api_key:
            api_key = self._dynamic_key

        transfer_spec["ssh_private_key"] = api_key
        return transfer_spec

    def list_files(self, path: str = "/", count: int = 1000, skip: int = 0) -> list[dict[str, Any]]:
        """List files and directories in a remote path.

        Uses the POST /files/browse endpoint.

        Args:
            path: Remote directory path (e.g., "/", "/some/dir").
            count: Maximum number of entries to return (default 1000).
            skip: Number of entries to skip for pagination (default 0).

        Returns:
            List of file/directory entries, each with 'name', 'type', 'size', etc.
        """
        data = self._request("POST", "/files/browse", json_data={"path": path, "count": count, "skip": skip})

        entries = []
        unknown_types: dict[str, int] = {}
        for item in data.get("items", []):
            item_type = item.get("type", "file")
            if item_type not in ("file", "directory", "symbolic_link", "symlink"):
                unknown_types[item_type] = unknown_types.get(item_type, 0) + 1
                item_type = "file"
            if item_type == "symlink":
                item_type = "symbolic_link"
            entries.append({
                "name": item.get("basename", ""),
                "type": item_type,
                "size": item.get("size", 0),
                "modified": item.get("mtime", ""),
                "path": item.get("path", ""),
            })
        if unknown_types:
            for t, count in sorted(unknown_types.items()):
                print(f"Warning: {count} item(s) with unknown type '{t}' treated as 'file'", file=sys.stderr)
        return entries

    def get_download_token(
        self,
        remote_path: str,
        local_dest: str,
    ) -> dict[str, Any]:
        """Request a download transfer token for a remote file.

        Args:
            remote_path: Remote file path on the Aspera node.
            local_dest: Local destination directory for the download.

        Returns:
            Dict containing token, ascp_args, and transfer_specs from the API.
        """
        payload: dict[str, Any] = {
            "transfer_requests": [
                {
                    "transfer_request": {
                        "paths": [
                            {"source": remote_path}
                        ],
                        "destination_root": local_dest,
                    }
                }
            ],
        }

        self.add_public_key(payload)
        data = self._request("POST", "/files/download_setup", json_data=payload)

        # Extract and merge private key into transfer spec
        transfer_specs = data.get("transfer_specs", [])
        if transfer_specs:
            spec = transfer_specs[0].get("transfer_spec", {})
            updated_spec = self.add_private_key(spec)
            transfer_specs[0]["transfer_spec"] = updated_spec
            data["transfer_specs"] = transfer_specs

        return data

    def close(self) -> None:
        """Close the HTTP session."""
        self._session.close()

    def __enter__(self) -> "AsperaNodeClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def _generate_dynamic_key_from_pem(pem_key: str) -> tuple[str, str]:
    """Generate public key string from existing PEM private key.

    Returns:
        Tuple of (public_key_str, private_key_pem).
    """
    if not HAS_CRYPTO:
        raise RuntimeError(
            "cryptography package required for dynamic key authentication. "
            "Install it with: pip install cryptography"
        )

    from cryptography.hazmat.primitives import serialization
    from cryptography.exceptions import InvalidKey

    try:
        private_key = serialization.load_pem_private_key(
            pem_key.encode("utf-8") if isinstance(pem_key, str) else pem_key,
            password=None,
        )
    except (ValueError, InvalidKey) as e:
        raise ValueError(
            "Failed to parse private key — ensure it is a valid PEM-encoded RSA private key"
        ) from e

    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    pub_base64 = base64.b64encode(public_pem.encode("utf-8")).decode("utf-8")

    public_key_str = f" {pub_base64}"
    return public_key_str, pem_key if isinstance(pem_key, str) else pem_key.decode("utf-8")
