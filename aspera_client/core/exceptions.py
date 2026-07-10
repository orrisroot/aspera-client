"""Exceptions for Aspera Node API client."""

from __future__ import annotations


class AsperaNodeError(Exception):
    """Base exception for Aspera Node API errors."""

    pass


class AsperaAuthError(AsperaNodeError):
    """Authentication failed."""

    pass


class AsperaApiError(AsperaNodeError):
    """API returned an error response."""

    pass
