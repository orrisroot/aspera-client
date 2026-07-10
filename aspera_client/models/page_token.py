"""Pagination token definition for Aspera browsing API."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PageToken:
    """Opaque token representing a pagination state, abstracting Gen3 (skip) and Gen4 (iteration_token)."""

    skip: int = 0
    iteration_token: str | None = None
