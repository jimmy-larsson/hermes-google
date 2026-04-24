"""Shared pytest fixtures for hermes-google tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def mock_gmail_service() -> MagicMock:
    """MagicMock shaped like a googleapiclient.discovery Resource for Gmail."""
    return MagicMock()


@pytest.fixture
def mock_calendar_service() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_drive_service() -> MagicMock:
    return MagicMock()
