"""Configuration loader and host/port resolver for Aspera Node API client."""

from __future__ import annotations

import urllib.parse
import yaml
from dataclasses import dataclass

_DEFAULT_PORT_BY_SCHEME = {"http": 80, "https": 443}


def _default_port_for_scheme(scheme: str) -> int:
    return _DEFAULT_PORT_BY_SCHEME.get(scheme.lower(), 9092)


@dataclass
class AsperaConfig:
    """Connection configuration for Aspera Node API."""

    host: str = "localhost"
    port: int = 9092
    user: str | None = None
    password: str | None = None
    verify_ssl: bool = True
    timeout: int = 30
    dynamic_key: str | None = None
    accept_v4: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> AsperaConfig:
        """Create config from dictionary, resolving host/port/url if needed."""
        url = data.get("url")
        if url:
            parsed = urllib.parse.urlparse(url)
            host = parsed.hostname or "localhost"
            port = parsed.port or _default_port_for_scheme(parsed.scheme)
        else:
            host = data.get("host", "localhost")
            port = data.get("port", 9092)

        return cls(
            host=host,
            port=int(port) if port is not None else 9092,
            user=data.get("user"),
            password=data.get("password"),
            verify_ssl=data.get("verify_ssl", True),
            timeout=data.get("timeout", 30),
            dynamic_key=data.get("dynamic_key"),
            accept_v4=data.get("accept_v4", True),
        )


def load_config(config_path: str) -> dict:
    """Load configuration from YAML file."""
    import os

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not config:
        raise ValueError(f"Configuration file is empty: {config_path}")

    return config


def resolve_host_port(
    url: str | None = None,
    host: str | None = None,
    port: int | str | None = None,
    config: dict | None = None,
) -> tuple[str, int]:
    """Resolve host and port.

    Priority: url parameter > config['url'] > host/port parameters > config['host']/config['port'] > defaults.
    """
    config = config or {}
    effective_url = url or config.get("url")
    if effective_url:
        parsed = urllib.parse.urlparse(effective_url)
        resolved_host = parsed.hostname or "localhost"
        resolved_port = parsed.port or _default_port_for_scheme(parsed.scheme)
        return resolved_host, resolved_port

    resolved_host = host or config.get("host", "localhost")
    resolved_port = port if port is not None else config.get("port", 9092)
    return resolved_host, int(resolved_port)
