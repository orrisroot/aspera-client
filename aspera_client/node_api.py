"""IBM Aspera Node API client for authentication, file listing, and token generation."""

from __future__ import annotations

import base64
import json
import sys
import urllib.parse
from collections import deque
from typing import Any, Callable

import requests

try:
    import cryptography  # noqa: F401
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


# HTTP headers for gen4 API
HEADER_X_ASPERA_ACCESS_KEY = "X-Aspera-AccessKey"
HEADER_X_CACHE_CONTROL = "X-Aspera-Cache-Control"
HEADER_X_NEXT_ITER_TOKEN = "X-Aspera-Next-Iteration-Token"
HEADER_ACCEPT_VERSION = "Accept-Version"
HEADER_X_TOTAL_COUNT = "X-Total-Count"

# Folder types in gen4 API
FOLDER_TYPES = ("folder", "directory", "container")

# Default gen4 per_page
DEFAULT_GEN4_PER_PAGE = 1000


class AsperaNodeError(Exception):
    """Base exception for Aspera Node API errors."""


class AsperaAuthError(AsperaNodeError):
    """Authentication failed."""


class AsperaApiError(AsperaNodeError):
    """API returned an error response."""


def gen3_entry_folder(entry: dict[str, Any]) -> bool:
    """Check if a gen3 entry is a folder."""
    return entry.get("type", "") in FOLDER_TYPES


def file_matcher(match_expression: str | object | None = None) -> Callable[[dict[str, Any]], bool]:
    """Create a file matcher function from an expression.

    Create a file matcher function.

    Args:
        match_expression: String glob pattern, regex pattern, proc, or None.

    Returns:
        A lambda that tests if a file entry matches.
    """
    if match_expression is None:
        return lambda _: True
    if isinstance(match_expression, str):
        import fnmatch
        return lambda f: fnmatch.fnmatch(f.get("name", ""), match_expression)
    if hasattr(match_expression, "pattern"):  # regex
        return lambda f: bool(match_expression.search(f.get("name", "")))
    if callable(match_expression):
        return match_expression
    raise TypeError(f"Unsupported match expression type: {type(match_expression)}")


class AsperaNodeClient:
    """Client for IBM Aspera Node API REST endpoints.

    Supports both gen3 (POST /files/browse) and gen4 (GET /files/:id/files
    with Accept-Version: 4.0 and iteration_token pagination).
    """

    def __init__(
        self,
        host: str,
        port: int = 9092,
        user: str | None = None,
        password: str | None = None,
        verify_ssl: bool = True,
        timeout: int = 30,
        dynamic_key: str | None = None,
        accept_v4: bool = True,
    ) -> None:
        """Initialize the client.

        Args:
            host: Aspera Node server hostname or IP.
            port: Node API port (default 9092).
            user: Username for Basic authentication.
            password: Password for Basic authentication.
            verify_ssl: Whether to verify SSL certificates.
            timeout: Request timeout in seconds (default 30).
            dynamic_key: PEM-encoded RSA private key for dynamic key authentication.
            accept_v4: Whether to use gen4 API features (Accept-Version: 4.0).
        """
        self.timeout = timeout
        self.user = user
        self.password = password
        self.verify_ssl = verify_ssl
        self._session = requests.Session()
        self._session.auth = (self.user, self.password) if self.user and self.password else None
        self._session.headers.update({"Accept": "application/json"})
        self._dynamic_key = dynamic_key

        # Set base_url without prefix first for auto-detection
        base_no_prefix = urllib.parse.urlunsplit(("https", f"{host}:{port}", "", "", ""))
        self.base_url = base_no_prefix.rstrip("/")

        prefix = self._auto_detect_prefix()
        base = urllib.parse.urlunsplit(("https", f"{host}:{port}", prefix, "", ""))
        self.base_url = base.rstrip("/")
        self._cached_public_key: str | None = None
        self._cached_public_key_pem: str | None = None
        self._accept_v4 = accept_v4
        self._app_info: dict[str, Any] | None = None
        self._add_tspec: dict[str, Any] | None = None
        self._std_tspec_cache: dict[str, Any] | None = None

    def _auto_detect_prefix(self) -> str:
        """Auto-detect the API path prefix by probing endpoints.

        Tries /files/browse on each candidate prefix and checks if the response
        is valid JSON (API) rather than HTML (web UI).
        Returns empty string if no candidate works (subsequent API calls may fail).
        """
        candidates = ["", "/node_api"]

        for prefix in candidates:
            url = f"{self.base_url}{prefix}/files/browse"
            try:
                resp = self._session.post(
                    url,
                    json={"path": "/", "count": 1},
                    headers={"Accept": "application/json"},
                    verify=self.verify_ssl,
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        if "items" in data or "self" in data:
                            return prefix
                    except (json.JSONDecodeError, ValueError):
                        pass
            except Exception:
                pass

        return ""

    def _request(
        self,
        method: str,
        path: str,
        json_data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        return_response: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any] | tuple[dict[str, Any], requests.Response]:
        """Make an HTTP request and return JSON response.

        Args:
            method: HTTP method (GET, POST, etc.).
            path: API path (e.g., "/files").
            json_data: JSON body for POST/PUT requests.
            headers: Additional headers.
            params: Query parameters.
            return_response: If True, return (data, response) tuple.
            **kwargs: Additional arguments passed to requests.

        Returns:
            Parsed JSON response, or (data, response) tuple if return_response=True.
        """
        url = f"{self.base_url}{path}"
        kwargs.setdefault("verify", self.verify_ssl)
        kwargs.setdefault("timeout", self.timeout)

        if json_data is not None:
            kwargs["json"] = json_data
        if params:
            kwargs["params"] = params
        if headers:
            kwargs["headers"] = headers

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

        if return_response:
            return data, response

        return data

    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------

    # Class-level cache for SSH public key generation (key_pem -> public_key_str)
    _ssh_public_key_cache: dict[str, str] = {}

    @classmethod
    def add_public_key_to_spec(cls, spec: dict[str, Any], dynamic_key: str | None) -> dict[str, Any]:
        """Add public key to transfer spec (dynamic key auth).

        Add public key to transfer spec (dynamic key auth).
        Uses SSH public key format.
        Caches generated public keys to avoid redundant computation.

        Note: Modifies spec in place. Return value is the same dict.
        """
        if not dynamic_key:
            return spec
        if dynamic_key not in cls._ssh_public_key_cache:
            pub_key_str, _ = _generate_ssh_public_key_from_pem(dynamic_key)
            cls._ssh_public_key_cache[dynamic_key] = pub_key_str
        spec["public_keys"] = cls._ssh_public_key_cache[dynamic_key]
        return spec

    @classmethod
    def add_private_key_to_spec(cls, spec: dict[str, Any], dynamic_key: str | None) -> dict[str, Any]:
        """Add private key to transfer spec (dynamic key auth).

        Add private key to transfer spec (dynamic key auth).
        If API returns ssh_private_key, use it; otherwise use the client's key.

        Note: Modifies spec in place. Return value is the same dict.
        """
        if not dynamic_key:
            return spec

        api_key = spec.get("ssh_private_key")
        if not api_key:
            api_key = dynamic_key

        spec["ssh_private_key"] = api_key
        return spec

    def add_public_key(self, payload: dict[str, Any]) -> None:
        """Add public key to download_setup request payload (dynamic key auth).

        Add public key to transfer spec (dynamic key auth).
        Uses cached public key if available to ensure consistency across calls.
        """
        if not self._dynamic_key:
            return
        if self._cached_public_key is None:
            self._cached_public_key, self._cached_public_key_pem = _generate_ssh_public_key_from_pem(
                self._dynamic_key
            )
        payload.setdefault("public_keys", self._cached_public_key)

    def add_private_key(self, transfer_spec: dict[str, Any]) -> dict[str, Any]:
        """Merge private key into transfer spec (dynamic key auth).

        Add private key to transfer spec (dynamic key auth).
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

    # -------------------------------------------------------------------------
    # Gen4 helpers
    # -------------------------------------------------------------------------

    def set_app_info(self, app_info: dict[str, Any]) -> None:
        """Set application info (e.g., AoC, Faspex)."""
        self._app_info = app_info

    def set_add_tspec(self, add_tspec: dict[str, Any]) -> None:
        """Set additional transfer spec to merge."""
        self._add_tspec = add_tspec

    def add_tspec_info(self, tspec: dict[str, Any]) -> dict[str, Any]:
        """Merge additional transfer spec info (e.g., COS tags)."""
        if self._add_tspec:
            tspec.update(self._add_tspec)
        return tspec

    def get_info(self) -> dict[str, Any]:
        """GET /info - Get node information."""
        return self._request("GET", "/info")

    def read(self, subpath: str, query: dict[str, Any] | None = None,
             headers: dict[str, str] | None = None) -> Any:
        """Generic GET request."""
        return self._request("GET", subpath, headers=headers, params=query)

    def create(self, subpath: str, json_data: dict[str, Any] | None = None,
               headers: dict[str, str] | None = None) -> Any:
        """Generic POST request."""
        return self._request("POST", subpath, json_data=json_data, headers=headers)

    def update(self, subpath: str, json_data: dict[str, Any]) -> Any:
        """Generic PUT request."""
        return self._request("PUT", subpath, json_data=json_data)

    def delete(self, subpath: str) -> Any:
        """Generic DELETE request."""
        return self._request("DELETE", subpath)

    def cancel(self, subpath: str) -> Any:
        """Generic POST cancel request."""
        return self._request("POST", subpath)

    def add_cache_control(self, headers: dict[str, str] | None = None) -> dict[str, str]:
        """Add cache control header for no-cache."""
        if headers is None:
            headers = {}
        headers[HEADER_X_CACHE_CONTROL] = "no-cache"
        return headers

    # -------------------------------------------------------------------------
    # Gen3 file listing (POST /files/browse)
    # -------------------------------------------------------------------------

    def list_files(
        self,
        path: str = "/",
        count: int = 1000,
        skip: int = 0,
        sort_by: str | None = None,
        reverse: bool = False,
        type_filter: str | None = None,
    ) -> dict[str, Any]:
        """List files and directories in a remote path (gen3).

        Uses the POST /files/browse endpoint with automatic skip-based pagination.
        sort_by and type_filter are applied as client-side post-processing
        (server-side sorting/filtering is not available for gen3).

        Args:
            path: Remote directory path (e.g., "/", "/some/dir").
            count: Maximum number of entries to return (default 1000).
            skip: Number of entries to skip for pagination (default 0).
            sort_by: Sort field (name, size, modified, type) - client-side.
            reverse: Reverse sort order - client-side.
            type_filter: Filter by type (file, directory, symbolic_link) - client-side.

        Returns:
            Dict with 'entries' (list) and 'total_count' (int).
        """
        all_entries: list[dict[str, Any]] = []
        total_count: int | None = None
        current_skip = skip

        while True:
            data = self._request(
                "POST", "/files/browse",
                json_data={"path": path, "count": count, "skip": current_skip},
            )

            items = data.get("items", [])
            total_count = data.get("total_count", total_count)

            entries = self._parse_gen3_items(items, path)

            if total_count is not None and len(all_entries) + len(entries) > total_count:
                entries = entries[: total_count - len(all_entries)]

            all_entries.extend(entries)

            if len(entries) < count:
                break
            if total_count is not None and len(all_entries) >= total_count:
                break

            current_skip += count

        result = {"entries": all_entries, "total_count": total_count or len(all_entries)}

        # Apply server-side sort/filter if requested
        if sort_by or type_filter:
            result["entries"] = self._apply_server_sort_filter(
                result["entries"], sort_by, reverse, type_filter,
            )

        return result

    # -------------------------------------------------------------------------
    # Gen4 file listing (GET /files/:id/files with Accept-Version: 4.0)
    # -------------------------------------------------------------------------

    def list_files_gen4(
        self,
        file_id: str,
        per_page: int = DEFAULT_GEN4_PER_PAGE,
        iteration_token: str | None = None,
        sort: str | None = None,
        include: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """List files in a folder using gen4 API.

        Uses GET /files/{file_id}/files with Accept-Version: 4.0 and
        iteration_token-based pagination.

        Args:
            file_id: The folder file identifier.
            per_page: Maximum entries per page (default 1000).
            iteration_token: Token for pagination continuation.
            sort: Sort specification (e.g., "name asc").
            include: Fields to include.

        Returns:
            List of file/folder entries.
        """
        headers = self.add_cache_control()
        headers[HEADER_ACCEPT_VERSION] = "4.0"

        query: dict[str, Any] = {"per_page": per_page}
        if iteration_token:
            query["iteration_token"] = iteration_token
        if sort:
            query["sort"] = sort
        if include:
            query["include"] = ",".join(include)

        all_items: list[dict[str, Any]] = []

        while True:
            data, response = self._request(
                "GET", f"/files/{file_id}/files",
                headers=headers, params=query, return_response=True,
            )

            if not isinstance(data, list):
                break

            all_items.extend(data)

            next_token = response.headers.get(HEADER_X_NEXT_ITER_TOKEN, "")
            if not next_token:
                break
            if next_token == iteration_token:
                break  # infinite loop protection

            query["iteration_token"] = next_token

        return all_items

    def read_folder_content(
        self,
        file_id: str,
        query: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Read folder content with pagination (gen4).

        . Falls back to gen3 if gen4 not available.
        """
        if not self._accept_v4:
            # Fallback: gen3 browse for root
            return []

        headers = self.add_cache_control()
        headers[HEADER_ACCEPT_VERSION] = "4.0"
        query = query or {}
        query["per_page"] = query.get("per_page", DEFAULT_GEN4_PER_PAGE)

        all_items: list[dict[str, Any]] = []
        iteration_token = None

        while True:
            if iteration_token:
                query["iteration_token"] = iteration_token

            data, response = self._request(
                "GET", f"/files/{file_id}/files",
                headers=headers, params=query, return_response=True,
            )

            if not isinstance(data, list):
                break

            all_items.extend(data)

            next_token = response.headers.get(HEADER_X_NEXT_ITER_TOKEN, "")
            if not next_token:
                break
            if next_token == iteration_token:
                break

            iteration_token = next_token

        return all_items

    # -------------------------------------------------------------------------
    # Recursive listing (gen3 and gen4)
    # -------------------------------------------------------------------------

    def list_recursive(
        self,
        path: str = "/",
        count: int = 1000,
        max_depth: int = 100,
        sort_by: str | None = None,
        reverse: bool = False,
        type_filter: str | None = None,
    ) -> dict[str, Any]:
        """Recursively list files and directories (gen3).

        .
        """
        all_entries: list[dict[str, Any]] = []
        # Use deque for O(1) pops from left (BFS traversal)
        queue: deque[tuple[str, int]] = deque([(path, 0)])

        while queue:
            current_path, depth = queue.popleft()
            if depth > max_depth:
                continue

            result = self.list_files(current_path, count=count, sort_by=sort_by,
                                     reverse=reverse, type_filter=type_filter)

            for entry in result["entries"]:
                entry_with_depth = dict(entry)
                entry_with_depth["depth"] = depth
                all_entries.append(entry_with_depth)

                if entry.get("type") in FOLDER_TYPES and depth < max_depth:
                    dir_path = entry.get("path", "") or f"{current_path}/{entry['name']}"
                    dir_path = _normalize_path(dir_path)
                    queue.append((dir_path, depth + 1))

        return {"entries": all_entries, "total_count": len(all_entries)}

    def list_recursive_gen4(
        self,
        file_id: str,
        folder_path: str = "/",
        max_depth: int = 100,
    ) -> list[dict[str, Any]]:
        """Recursively list files and directories (gen4).

        .
        """
        all_entries: list[dict[str, Any]] = []
        # Use deque for O(1) pops from left (BFS traversal)
        queue: deque[tuple[str, str, int]] = deque([(file_id, folder_path, 0)])

        while queue:
            current_id, current_path, depth = queue.popleft()
            if depth > max_depth:
                continue

            items = self.read_folder_content(current_id)

            for entry in items:
                if "error" in entry:
                    continue

                entry_with_path = dict(entry)
                entry_with_path["path"] = _normalize_path(
                    current_path + "/" + entry.get("name", "")
                )
                all_entries.append(entry_with_path)

                if entry.get("type") in FOLDER_TYPES and depth < max_depth:
                    sub_id = entry.get("id", "")
                    if sub_id:
                        sub_path = entry_with_path["path"]
                        queue.append((sub_id, sub_path, depth + 1))

        return all_entries

    # -------------------------------------------------------------------------
    # File resolution (gen4)
    # -------------------------------------------------------------------------

    def resolve_fid(self, top_file_id: str, path: str) -> dict[str, Any]:
        """Resolve a path to a file_id on the node (gen4).

        .

        Returns:
            Dict with 'node_api' reference and 'file_id'.
        """
        path_elements = [p for p in path.split("/") if p]
        if not path_elements:
            return {"file_id": top_file_id}

        # BFS through folder tree
        folders_to_explore: deque[tuple[str, str, list[str]]] = deque([(top_file_id, "", path_elements[:])])

        while folders_to_explore:
            current_id, current_path, remaining = folders_to_explore.popleft()
            items = self.read_folder_content(current_id)

            for entry in items:
                if entry.get("name") != remaining[0]:
                    continue

                if len(remaining) == 1:
                    # Found it
                    return {"file_id": entry["id"], "entry": entry}

                if entry.get("type") in FOLDER_TYPES:
                    new_path = _normalize_path(current_path + "/" + entry["name"])
                    folders_to_explore.append((entry["id"], new_path, remaining[1:]))

        raise AsperaApiError(f"Entry not found: {path_elements[0]} in /{_normalize_path(path_elements[:-1])}")

    # -------------------------------------------------------------------------
    # Common root detection for multiple paths (gen4)
    # -------------------------------------------------------------------------

    @staticmethod
    def find_common_root(paths: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
        """Find common root path from a list of source paths.

        .

        Args:
            paths: List of dicts with 'source' key.

        Returns:
            Tuple of (common_root_parts, source_paths_with_relative).
        """
        if not paths:
            return [], []

        # Split each source into path parts
        split_sources = []
        for p in paths:
            source = p.get("source", "")
            parts = [part for part in source.split("/") if part]
            split_sources.append(parts)

        if not split_sources:
            return [], []

        # Find common prefix
        root = []
        min_len = min(len(s) for s in split_sources)
        for i in range(min_len):
            parts_at_i = [s[i] for s in split_sources]
            if len(set(parts_at_i)) == 1:
                root.append(parts_at_i[0])
            else:
                break

        source_folder = "/".join(root) if root else ""

        # Build relative paths
        source_paths = []
        for i, p in enumerate(paths):
            relative_parts = split_sources[i][len(root):]
            relative_path = "/".join(relative_parts) if relative_parts else "."
            m = {"source": relative_path}
            if "destination" in p:
                m["destination"] = p["destination"]
            source_paths.append(m)

        return [source_folder] if source_folder else [], source_paths

    # -------------------------------------------------------------------------
    # Find files with matcher (gen4)
    # -------------------------------------------------------------------------

    def find_files(
        self,
        top_file_id: str,
        test_lambda: Callable[[dict[str, Any]], bool],
        max_depth: int = 100,
    ) -> list[dict[str, Any]]:
        """Recursively find files matching a test function (gen4).

        .
        """
        found: list[dict[str, Any]] = []
        queue: deque[tuple[str, str, int]] = deque([(top_file_id, "/", 0)])

        while queue:
            current_id, current_path, depth = queue.popleft()
            if depth > max_depth:
                continue

            items = self.read_folder_content(current_id)

            for entry in items:
                if "error" in entry:
                    continue

                entry_path = _normalize_path(current_path + "/" + entry.get("name", ""))
                entry_with_path = dict(entry)
                entry_with_path["path"] = entry_path

                if test_lambda(entry_with_path):
                    found.append(entry_with_path)

                if entry.get("type") in FOLDER_TYPES and depth < max_depth:
                    sub_id = entry.get("id", "")
                    if sub_id:
                        queue.append((sub_id, entry_path, depth + 1))

        return found

    # -------------------------------------------------------------------------
    # Download token (gen3)
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # Gen4 download transfer spec
    # -------------------------------------------------------------------------

    def get_transfer_spec_gen4(
        self,
        file_id: str,
        direction: str,
        paths: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create transfer spec for gen4.

        .

        Args:
            file_id: Source folder file identifier.
            direction: 'send' or 'receive'.
            paths: List of path dicts with 'source' key.

        Returns:
            Transfer spec dict.
        """
        # Build token from auth
        if self.user and self.password:
            ak_token = _basic_authorization(self.user, self.password)
            ak_name = self.user
        else:
            raise AsperaAuthError("No credentials for gen4 transfer spec")

        transfer_spec: dict[str, Any] = {
            "direction": direction,
            "token": ak_token,
            "tags": {
                "aspera": {
                    "node": {
                        "access_key": ak_name,
                        "file_id": file_id,
                    }
                }
            }
        }

        # Add additional spec info (e.g., COS tags)
        self.add_tspec_info(transfer_spec)

        # Add paths if provided
        if paths:
            transfer_spec["paths"] = paths

        # Add standard ports if enabled
        if self._accept_v4:
            transfer_spec["remote_user"] = "xfer"
            transfer_spec["ssh_port"] = 33001
            transfer_spec["fasp_port"] = 33001
            # Get remote host from base_url
            parsed = urllib.parse.urlparse(self.base_url)
            transfer_spec["remote_host"] = parsed.hostname or parsed.netloc

            # Try to get transfer user from info
            try:
                info = self.get_info()
                if info.get("transfer_user"):
                    transfer_spec["remote_user"] = info["transfer_user"]
            except Exception:
                pass

        return transfer_spec

    # -------------------------------------------------------------------------
    # Generic transfer spec (gen3)
    # -------------------------------------------------------------------------

    def get_base_spec(self) -> dict[str, Any]:
        """Get base download transfer spec (gen3)."""
        return self.create(
            "files/download_setup",
            {"transfer_requests": [{"transfer_request": {"paths": [{"source": "/"}]}}]}
        )["transfer_specs"][0]["transfer_spec"]

    def get_transport_params(self) -> dict[str, Any]:
        """Get transport parameters from base spec."""
        if self._std_tspec_cache is None:
            spec = self.get_base_spec()
            transport_fields = {"remote_host", "remote_user", "ssh_port", "fasp_port",
                                "wss_enabled", "wss_port"}
            self._std_tspec_cache = {k: v for k, v in spec.items() if k in transport_fields}
        return self._std_tspec_cache

    # -------------------------------------------------------------------------
    # Iteration-based paging for ops/transfers
    # -------------------------------------------------------------------------

    def read_with_paging(
        self,
        subpath: str,
        query: dict[str, Any] | None = None,
        iteration_token: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read resource with iteration_token pagination.

        .
        """
        query = query or {}
        if iteration_token:
            query["iteration_token"] = iteration_token

        all_items: list[dict[str, Any]] = []

        while True:
            data, response = self._request(
                "GET", subpath, params=query, return_response=True,
            )

            if not isinstance(data, list):
                break

            all_items.extend(data)

            next_token = response.headers.get(HEADER_X_NEXT_ITER_TOKEN, "")
            if not next_token:
                break
            if next_token == iteration_token:
                break

            iteration_token = next_token

        return all_items

    # -------------------------------------------------------------------------
    # Close
    # -------------------------------------------------------------------------

    def close(self) -> None:
        """Close the HTTP session."""
        self._session.close()

    def __enter__(self) -> "AsperaNodeClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _parse_gen3_items(
        self,
        items: list[dict[str, Any]],
        default_path: str = "",
    ) -> list[dict[str, Any]]:
        """Parse gen3 /files/browse items into normalized entry dicts."""
        entries = []
        unknown_types: dict[str, int] = {}
        for item in items:
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
                "path": item.get("path", default_path),
            })
        if unknown_types:
            for t, cnt in sorted(unknown_types.items()):
                print(f"Warning: {cnt} item(s) with unknown type '{t}' treated as 'file'",
                      file=sys.stderr)
        return entries

    @staticmethod
    def _apply_server_sort_filter(
        entries: list[dict[str, Any]],
        sort_by: str | None,
        reverse: bool,
        type_filter: str | None,
    ) -> list[dict[str, Any]]:
        """Apply in-memory sort and filter (fallback when server-side not available)."""
        result = entries

        if type_filter:
            result = [e for e in result if e.get("type") == type_filter]

        if sort_by:
            def sort_key(e):
                if sort_by == "name":
                    return e.get("name", "").lower()
                elif sort_by == "size":
                    return (0, e.get("size", 0), "")
                elif sort_by == "modified":
                    return e.get("modified", "")
                elif sort_by == "type":
                    return e.get("type", "")
                return e.get("name", "").lower()

            result = sorted(result, key=sort_key, reverse=reverse)

        return result


def _normalize_path(path: str) -> str:
    """Normalize path, collapsing multiple slashes."""
    parts = [p for p in path.split("/") if p]
    return "/" + "/".join(parts) if parts else "/"


def _basic_authorization(username: str, password: str) -> str:
    """Create Basic auth token string."""
    credentials = f"{username}:{password}"
    return base64.b64encode(credentials.encode("utf-8")).decode("utf-8")


def _generate_ssh_public_key_from_pem(pem_key: str) -> tuple[str, str]:
    """Generate SSH public key string from PEM private key.

    Produces SSH public key format compatible with the Aspera Node API.

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
    from cryptography.hazmat.primitives.asymmetric import rsa

    try:
        private_key = serialization.load_pem_private_key(
            pem_key.encode("utf-8") if isinstance(pem_key, str) else pem_key,
            password=None,
        )
    except (ValueError, InvalidKey) as e:
        raise ValueError(
            "Failed to parse private key -- ensure it is a valid PEM-encoded RSA private key"
        ) from e

    if not isinstance(private_key, rsa.RSAPrivateKey):
        raise ValueError("Only RSA private keys are supported for dynamic key authentication")

    public_key = private_key.public_key()
    public_ssh = public_key.public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    )

    key_type = "ssh-rsa"

    # Format: [base64(key_type), base64(openssh_public_key)]
    # ssh-rsa key type and full OpenSSH public key string are base64-encoded
    key_type_b64 = base64.b64encode(key_type.encode("utf-8")).decode("utf-8")
    key_data_b64_str = base64.b64encode(public_ssh).decode("utf-8")

    public_key_str = f"{key_type_b64} {key_data_b64_str}"

    return public_key_str, pem_key if isinstance(pem_key, str) else pem_key.decode("utf-8")
