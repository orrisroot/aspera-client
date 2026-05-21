"""IBM Aspera Node API client for authentication, file listing, and token generation."""

from __future__ import annotations

import json
import urllib.parse
from typing import Any

import requests
import requests.exceptions


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

    def list_files(self, path: str = "/", count: int = 1000) -> list[dict[str, Any]]:
        """List files and directories in a remote path.

        Uses the POST /files/browse endpoint.

        Args:
            path: Remote directory path (e.g., "/", "/some/dir").
            count: Maximum number of entries to return (default 1000).

        Returns:
            List of file/directory entries, each with 'name', 'type', 'size', etc.
        """
        data = self._request("POST", "/files/browse", json_data={"path": path, "count": count})

        entries = []
        for item in data.get("items", []):
            item_type = item.get("type", "file")
            entries.append({
                "name": item.get("basename", ""),
                "type": item_type if item_type in ("file", "directory", "symbolic_link") else "file",
                "size": item.get("size", 0),
                "modified": item.get("mtime", ""),
                "path": item.get("path", ""),
            })
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

        data = self._request("POST", "/files/download_setup", json_data=payload)
        return data

    def close(self) -> None:
        """Close the HTTP session."""
        self._session.close()

    def __enter__(self) -> "AsperaNodeClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
