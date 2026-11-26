"""Tests for cache.py: attachment cache expiry and wipe."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hermes_google.core.cache import MAX_AGE_DAYS, clear_cache, prune_cache

DAY = 86400


def _touch(path: Path, age_days: float, now: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    stamp = now - age_days * DAY
    os.utime(path, (stamp, stamp))
    os.utime(path.parent, (stamp, stamp))


def test_prune_removes_old_files_and_empty_dirs_and_keeps_fresh_ones(tmp_path: Path) -> None:
    now = 1_800_000_000.0
    _touch(tmp_path / "m1" / "old.pdf", MAX_AGE_DAYS + 1, now)
    _touch(tmp_path / "drive" / "f1" / "old.csv", 90, now)
    _touch(tmp_path / "m2" / "fresh.pdf", 1, now)

    removed = prune_cache(tmp_path, now=now)

    assert removed == 2
    assert not (tmp_path / "m1").exists()
    assert not (tmp_path / "drive" / "f1").exists()
    assert (tmp_path / "m2" / "fresh.pdf").exists()
    assert tmp_path.exists()


def test_prune_respects_custom_age(tmp_path: Path) -> None:
    now = 1_800_000_000.0
    _touch(tmp_path / "m1" / "a.pdf", 5, now)
    assert prune_cache(tmp_path, max_age_days=3, now=now) == 1
    assert prune_cache(tmp_path, max_age_days=3, now=now) == 0


def test_prune_missing_dir_returns_zero(tmp_path: Path) -> None:
    assert prune_cache(tmp_path / "nope") == 0


def test_clear_cache_empties_but_keeps_the_directory(tmp_path: Path) -> None:
    now = 1_800_000_000.0
    _touch(tmp_path / "m1" / "a.pdf", 1, now)
    _touch(tmp_path / "drive" / "f1" / "b.md", 1, now)
    (tmp_path / "loose.txt").write_text("x")

    assert clear_cache(tmp_path) == []

    assert tmp_path.exists()
    assert list(tmp_path.iterdir()) == []


def test_clear_cache_missing_dir_is_fine(tmp_path: Path) -> None:
    clear_cache(tmp_path / "nope")


def test_prune_keeps_a_directory_created_moments_ago(tmp_path: Path) -> None:
    now = 1_800_000_000.0
    fresh = tmp_path / "m-live"
    fresh.mkdir()
    os.utime(fresh, (now, now))
    assert prune_cache(tmp_path, now=now) == 0
    assert fresh.is_dir()


def test_prune_skips_symlinks(tmp_path: Path) -> None:
    now = 1_800_000_000.0
    outside = tmp_path.parent / f"{tmp_path.name}-outside.bin"
    outside.write_bytes(b"keep")
    cache = tmp_path / "cache"
    cache.mkdir()
    link = cache / "link.bin"
    link.symlink_to(outside)
    os.utime(link, (now - 90 * DAY, now - 90 * DAY), follow_symlinks=False)
    try:
        assert prune_cache(cache, now=now) == 0
        assert link.is_symlink()
        assert outside.read_bytes() == b"keep"
    finally:
        outside.unlink()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permission bits")
def test_clear_cache_reports_what_it_could_not_remove(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "a.bin").write_bytes(b"x")
    (tmp_path / "free.bin").write_bytes(b"y")
    locked.chmod(0o500)
    try:
        leftovers = clear_cache(tmp_path)
    finally:
        locked.chmod(0o700)
    assert leftovers == [locked]
    assert not (tmp_path / "free.bin").exists()
