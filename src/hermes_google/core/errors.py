"""Shared exception base for all hermes-google domain errors."""

from __future__ import annotations


class ServiceError(Exception):
    """Base for all domain errors raised by core modules.

    MCP and CLI layers catch this single type to convert domain failures
    into transport-appropriate responses (ToolError, CLI exit codes, etc.).
    """
