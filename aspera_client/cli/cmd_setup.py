"""CLI setup subcommand implementation."""

from __future__ import annotations

import argparse

from ..api.setup_environment import setup_environment


def cmd_setup(args: argparse.Namespace) -> int:
    """Handle the 'setup' subcommand."""
    results = setup_environment(
        install_sdk_flag=not args.no_sdk,
        bypass_key_flag=not args.no_bypass_key,
        fallback_key_flag=not args.no_fallback_key,
        version=getattr(args, "version", None),
    )
    has_errors = any(k.endswith("_error") for k in results)
    return 1 if has_errors else 0
