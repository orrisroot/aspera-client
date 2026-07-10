"""Environment management for Aspera SDK and tools."""

from __future__ import annotations

import os


class AsperaEnvironment:
    """Manages the installation directory and resolving file paths for Aspera tools."""

    def __init__(self, base_dir: str | None = None) -> None:
        self.base_dir = base_dir or os.path.expanduser("~/.aspera/connect")

    @property
    def bin_dir(self) -> str:
        return os.path.join(self.base_dir, "bin")

    @property
    def client_dir(self) -> str:
        return os.path.join(self.base_dir, "client")

    @property
    def ascp_path(self) -> str:
        import platform

        sys_name = platform.system()
        if sys_name == "Windows":
            return os.path.join(self.bin_dir, "ascp.exe")
        return os.path.join(self.bin_dir, "ascp")

    @property
    def bypass_key_path(self) -> str:
        return os.path.join(self.client_dir, "aspera_bypass_rsa.pem")

    @property
    def fallback_key_path(self) -> str:
        return os.path.join(self.client_dir, "aspera_fallback_cert_private_key.pem")

    @property
    def fallback_cert_path(self) -> str:
        return os.path.join(self.client_dir, "aspera_fallback_cert.pem")

    @property
    def conf_path(self) -> str:
        return os.path.join(self.client_dir, "aspera.conf")
