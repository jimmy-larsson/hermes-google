"""Attachment cache hygiene: expire old downloads and wipe on disconnect."""

from __future__ import annotations

import shutil
import stat
import time
from pathlib import Path

MAX_AGE_DAYS = 30


def prune_cache(
    cache_dir: Path, *, max_age_days: int = MAX_AGE_DAYS, now: float | None = None
) -> int:
    """Delete cached files older than ``max_age_days`` and old directories left empty.

    Directory ages are read before anything is deleted, so a directory that a
    concurrent download has just created is left alone. Returns the number of
    files removed. A missing cache directory is fine.
    """
    if not cache_dir.is_dir():
        return 0
    cutoff = (time.time() if now is None else now) - max_age_days * 86400
    snapshot: list[tuple[Path, int, float]] = []
    try:
        for path in sorted(cache_dir.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            try:
                st = path.lstat()
            except OSError:
                continue
            snapshot.append((path, st.st_mode, st.st_mtime))
    except OSError:
        return 0
    removed = 0
    for path, mode, mtime in snapshot:
        if stat.S_ISLNK(mode) or mtime >= cutoff:
            continue
        try:
            if stat.S_ISREG(mode):
                path.unlink()
                removed += 1
            elif stat.S_ISDIR(mode) and not any(path.iterdir()):
                path.rmdir()
        except OSError:
            continue
    return removed


def clear_cache(cache_dir: Path) -> list[Path]:
    """Remove everything under ``cache_dir`` and keep the directory itself.

    Returns the entries that could not be removed.
    """
    if not cache_dir.is_dir():
        return []
    leftovers: list[Path] = []
    for child in cache_dir.iterdir():
        try:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        except OSError:
            leftovers.append(child)
    return leftovers
