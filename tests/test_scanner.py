"""Tests for app/scanner.py — closes M-009 and validates M-017 (relative_path)."""
import os
from pathlib import Path

import pytest

from app.scanner import scan
from app.models import ScanFolder


def _mkfile(path: Path, size_mb: float):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"X" * int(size_mb * 1024 * 1024))


def test_scan_returns_relative_path(tmp_path):
    """M-017: scanner must emit relative_path so the UI can build a folder tree."""
    base = tmp_path / "media"
    _mkfile(base / "Series" / "Season1" / "ep01.mkv", 2)
    _mkfile(base / "Movies" / "big.mkv", 2)
    _mkfile(base / "shallow.mkv", 2)

    results = scan(
        [ScanFolder(path=str(base), threshold_mb=1)],
        exclude_folders=[],
        extensions=[".mkv"],
    )

    rels = sorted(f.relative_path for f in results)
    assert rels == [
        "Movies/big.mkv",
        "Series/Season1/ep01.mkv",
        "shallow.mkv",
    ]

    # folder field still points to the scan root (back-compat)
    for f in results:
        assert f.folder == str(base)


def test_scan_excludes_below_threshold(tmp_path):
    base = tmp_path / "media"
    _mkfile(base / "small.mkv", 0.5)
    _mkfile(base / "big.mkv",   3)

    results = scan(
        [ScanFolder(path=str(base), threshold_mb=1)],
        exclude_folders=[],
        extensions=[".mkv"],
    )

    names = [f.filename for f in results]
    assert names == ["big.mkv"]


def test_scan_filters_extensions(tmp_path):
    base = tmp_path / "media"
    _mkfile(base / "video.mkv", 2)
    _mkfile(base / "audio.mp3", 2)
    _mkfile(base / "doc.txt",   2)

    results = scan(
        [ScanFolder(path=str(base), threshold_mb=1)],
        exclude_folders=[],
        extensions=[".mkv", ".mp4"],
    )

    assert [f.filename for f in results] == ["video.mkv"]


def test_scan_respects_exclude_folders(tmp_path):
    base = tmp_path / "media"
    _mkfile(base / "keep" / "ok.mkv", 2)
    _mkfile(base / "skip" / "no.mkv", 2)
    _mkfile(base / "deep" / "nested" / "deep.mkv", 2)

    results = scan(
        [ScanFolder(path=str(base), threshold_mb=1)],
        exclude_folders=[str(base / "skip"), str(base / "deep" / "nested")],
        extensions=[".mkv"],
    )

    rels = sorted(f.relative_path for f in results)
    assert rels == ["keep/ok.mkv"]


def test_scan_sorts_by_size_desc(tmp_path):
    base = tmp_path / "media"
    _mkfile(base / "small.mkv",  1.5)
    _mkfile(base / "huge.mkv",   5)
    _mkfile(base / "medium.mkv", 3)

    results = scan(
        [ScanFolder(path=str(base), threshold_mb=1)],
        exclude_folders=[],
        extensions=[".mkv"],
    )

    assert [f.filename for f in results] == ["huge.mkv", "medium.mkv", "small.mkv"]


def test_scan_skips_missing_scan_folder(tmp_path):
    base = tmp_path / "does_not_exist"
    results = scan(
        [ScanFolder(path=str(base), threshold_mb=1)],
        exclude_folders=[],
        extensions=[".mkv"],
    )
    assert results == []


def test_scan_case_insensitive_extensions(tmp_path):
    base = tmp_path / "media"
    _mkfile(base / "UPPER.MKV", 2)
    _mkfile(base / "lower.mkv", 2)

    results = scan(
        [ScanFolder(path=str(base), threshold_mb=1)],
        exclude_folders=[],
        extensions=[".mkv"],
    )

    assert sorted(f.filename for f in results) == ["UPPER.MKV", "lower.mkv"]
