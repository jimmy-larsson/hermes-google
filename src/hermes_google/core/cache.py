"""Attachment cache hygiene: expire old downloads and wipe on disconnect."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

MAX_AGE_DAYS = 30


def prune_cache(
    cache_dir: Path, *, max_age_days: int = MAX_AGE_DAYS, now: float | None = None
) -> int:
    """Delete cached files older than ``max_age_days`` and directories left empty.

    Returns the number of files removed. A missing cache directory is fine.
    """
    if not cache_dir.is_dir():
        return 0
    cutoff = (time.time() if now is None else now) - max_age_days * 86400
    removed = 0
    for path in sorted(cache_dir.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        try:
            if path.is_symlink():
                continue
            if path.is_file():
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            elif path.is_dir() and not any(path.iterdir()):
                path.rmdir()
        except OSError:
            continue
    return removed


def clear_cache(cache_dir: Path) -> None:
    """Remove everything under ``cache_dir`` and keep the directory itself."""
    if not cache_dir.is_dir():
        return
    for child in cache_dir.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)
