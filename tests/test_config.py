"""Tests for config.py — TOML loader."""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from hermes_google.core import config as config_module
from hermes_google.core.config import Config, load_config


def _write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(dedent(body))
    return path


def test_load_config_minimal(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        """
        [user]
        email = "jimmy@example.com"

        [hermes_account]
        email = "hermes-jimmy@gmail.com"

        [paths]
        credentials = "/tmp/credentials.json"
        cache = "/tmp/cache"
        log = "/tmp/cache/log.jsonl"

        [mcp]
        name = "hermes-google"
        """,
    )
    cfg = load_config(path)
    assert isinstance(cfg, Config)
    assert cfg.user_email == "jimmy@example.com"
    assert cfg.hermes_account_email == "hermes-jimmy@gmail.com"
    assert cfg.credentials_path == Path("/tmp/credentials.json")
    assert cfg.cache_dir == Path("/tmp/cache")
    assert cfg.log_path == Path("/tmp/cache/log.jsonl")
    assert cfg.mcp_name == "hermes-google"
    assert cfg.drive_default_parent_folder_id is None


def test_load_config_with_drive_default(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        """
        [user]
        email = "jimmy@example.com"
        [hermes_account]
        email = "hermes-jimmy@gmail.com"
        [drive]
        default_parent_folder_id = "FOLDERID"
        [paths]
        credentials = "/tmp/credentials.json"
        cache = "/tmp/cache"
        log = "/tmp/cache/log.jsonl"
        [mcp]
        name = "hermes-google"
        """,
    )
    cfg = load_config(path)
    assert cfg.drive_default_parent_folder_id == "FOLDERID"


def test_load_config_expands_tilde(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    path = _write_config(
        tmp_path,
        """
        [user]
        email = "jimmy@example.com"
        [hermes_account]
        email = "hermes-jimmy@gmail.com"
        [paths]
        credentials = "~/credentials.json"
        cache = "~/cache"
        log = "~/cache/log.jsonl"
        [mcp]
        name = "hermes-google"
        """,
    )
    cfg = load_config(path)
    assert cfg.credentials_path == tmp_path / "credentials.json"
    assert cfg.cache_dir == tmp_path / "cache"
    assert cfg.log_path == tmp_path / "cache" / "log.jsonl"


def test_load_config_missing_required_section(tmp_path: Path) -> None:
    path = _write_config(tmp_path, "[user]\nemail = 'x@y.z'\n")
    with pytest.raises(config_module.ConfigError, match="hermes_account"):
        load_config(path)


def test_default_config_path_is_under_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/home/testuser")
    assert config_module.default_config_path() == Path(
        "/home/testuser/.config/hermes-google/config.toml"
    )


def test_load_config_missing_file(tmp_path: Path) -> None:
    with pytest.raises(config_module.ConfigError, match="not found"):
        load_config(tmp_path / "nonexistent.toml")


def test_load_config_invalid_toml_raises_config_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text("this is = not valid = toml =")
    with pytest.raises(config_module.ConfigError, match="not valid TOML"):
        load_config(path)
