"""Tests for AsperaConnection and browse functionality."""

from __future__ import annotations

import os
import pytest

from aspera_client import (
    AsperaConnection,
    AsperaConfig,
    AsperaEnvironment,
    browse,
    load_config,
)


def test_connection_and_browse() -> None:
    """Test AsperaConnection and browse file listing with credentials."""
    config_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../config.yaml")
    )
    if not os.path.exists(config_path):
        pytest.skip("config.yaml not found, skipping connection/browse test")

    raw_config = load_config(config_path)
    memory_config_dict = {
        "url": raw_config.get("url"),
        "user": raw_config.get("user"),
        "password": raw_config.get("password"),
        "verify_ssl": raw_config.get("verify_ssl", True),
        "timeout": raw_config.get("timeout", 30),
    }
    config = AsperaConfig.from_dict(memory_config_dict)

    env = AsperaEnvironment()

    client = AsperaConnection(config=config, env=env)
    with client:
        entries, next_token = browse(client, path="/", count=100)
        assert isinstance(entries, list)
        assert len(entries) >= 0
