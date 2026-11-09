"""Shared exception base for all hermes-google domain errors."""

from __future__ import annotations


class ServiceError(Exception):
    """Base for all domain errors raised by core modules.

    MCP and CLI layers catch this single type to convert domain failures
    into transport-appropriate responses (ToolError, CLI exit codes, etc.).
    """


def api_failure(action: str, exc: BaseException) -> str:
    """Describe a failed API call: '<action> failed: HTTP <status> <reason>'.

    googleapiclient's HttpError exposes `status_code` and `reason`; any other
    exception is described by its type and text.
    """
    status = getattr(exc, "status_code", None)
    reason = getattr(exc, "reason", None)
    if status is not None and reason is not None:
        return f"{action} failed: HTTP {status} {reason}"
    return f"{action} failed: {type(exc).__name__}: {exc}"
