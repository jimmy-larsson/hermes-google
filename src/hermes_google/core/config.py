"""Config loading for hermes-google.

Reads `~/.config/hermes-google/config.toml` by default and returns a frozen
Config dataclass. No Google imports; safe to use in every other module.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    """Raised for any config loading failure: file not found, invalid TOML, or missing required fields."""  # noqa: E501


@dataclass(frozen=True)
class Config:
    user_email: str
    hermes_account_email: str
    credentials_path: Path
    cache_dir: Path
    log_path: Path
    mcp_name: str
    drive_default_parent_folder_id: str | None = None
    user_calendar_id: str | None = None


def default_config_path() -> Path:
    return Path(os.path.expanduser("~/.config/hermes-google/config.toml"))


def _expand(value: str) -> Path:
    return Path(os.path.expanduser(value))


def _required(data: dict, section: str, key: str) -> str:
    try:
        return data[section][key]
    except KeyError as exc:
        raise ConfigError(f"missing required config key: [{section}].{key}") from exc


def load_config(path: Path | None = None) -> Config:
    path = path or default_config_path()
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    with path.open("rb") as fh:
        try:
            data = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"config file is not valid TOML: {path}") from exc

    return Config(
        user_email=_required(data, "user", "email"),
        hermes_account_email=_required(data, "hermes_account", "email"),
        credentials_path=_expand(_required(data, "paths", "credentials")),
        cache_dir=_expand(_required(data, "paths", "cache")),
        log_path=_expand(_required(data, "paths", "log")),
        mcp_name=_required(data, "mcp", "name"),
        drive_default_parent_folder_id=data.get("drive", {}).get("default_parent_folder_id"),
        user_calendar_id=data.get("user", {}).get("calendar_id"),
    )
