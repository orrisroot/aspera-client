"""Tests for config loader and AsperaConfig parsing."""

from __future__ import annotations

import os
import pytest

from aspera_client import AsperaConfig, load_config


def test_load_config() -> None:
    """Test load_config utility and AsperaConfig parser."""
    config_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../config.yaml")
    )
    if not os.path.exists(config_path):
        pytest.skip("config.yaml not found, skipping config loader test")

    raw_config = load_config(config_path)
    memory_config_dict = {
        "url": raw_config.get("url"),
        "user": raw_config.get("user"),
        "password": raw_config.get("password"),
        "verify_ssl": raw_config.get("verify_ssl", True),
        "timeout": raw_config.get("timeout", 30),
    }

    config = AsperaConfig.from_dict(memory_config_dict)
    assert config.host is not None
    assert config.port is not None
