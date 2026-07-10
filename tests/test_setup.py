"""Tests for setup_environment functionality."""

from __future__ import annotations

import os
import shutil

from aspera_client import AsperaEnvironment, setup_environment


def test_setup_environment() -> None:
    """Test setup_environment function with a custom environment."""
    custom_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../local_tools_test")
    )

    # Clean up existing test environment
    if os.path.exists(custom_dir):
        shutil.rmtree(custom_dir)

    env = AsperaEnvironment(base_dir=custom_dir)

    # Run setup (SDK install = False to save time, key generation = True)
    setup_res = setup_environment(install_sdk_flag=False, quiet=True, env=env)

    # Verify result paths
    assert setup_res.get("bypass_key") is not None
    assert os.path.exists(setup_res.get("bypass_key"))
    assert setup_res.get("bypass_key").startswith(custom_dir)

    # Clean up after test
    if os.path.exists(custom_dir):
        shutil.rmtree(custom_dir)
