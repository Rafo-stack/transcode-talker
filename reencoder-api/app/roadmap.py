"""Roadmap loader.

Reads three YAML files (bugs / improvements / features) from `/app/roadmap`
(mounted from `./roadmap` in the host repo) and serves a combined response
to the UI. Cached by file mtime so editing the YAMLs in the repo reflects
on the next request without restarting the API.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import-not-found]
except Exception:  # noqa: BLE001
    yaml = None  # type: ignore[assignment]

ROADMAP_DIR = Path(os.environ.get("ROADMAP_DIR", "/app/roadmap"))

_CATEGORIES = {
    "bugs": "bugs.yaml",
    "improvements": "improvements.yaml",
    "features": "features.yaml",
}

_cache: dict[str, Any] = {"mtime_sum": -1.0, "data": None}


def _read_category(name: str, filename: str) -> list[dict]:
    path = ROADMAP_DIR / filename
    if not path.exists():
        return []
    if yaml is None:
        # Without PyYAML installed we simply return an empty category.
        # Better than crashing the whole API for a missing dep.
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        item = {
            "id": str(entry.get("id", "")),
            "category": name,
            "title": str(entry.get("title", "(untitled)")),
            "summary": entry.get("summary"),
            "plain_summary": entry.get("plain_summary"),
            "details": entry.get("details"),
            "status": str(entry.get("status", "open")),
            "severity": entry.get("severity"),
            "priority": entry.get("priority"),
            "area": entry.get("area"),
            "targeted_version": (
                str(entry["targeted_version"]) if entry.get("targeted_version") is not None else None
            ),
        }
        out.append(item)
    return out


def load() -> dict:
    """Return the combined roadmap, using a cheap mtime-sum cache."""
    mtime_sum = 0.0
    for fname in _CATEGORIES.values():
        p = ROADMAP_DIR / fname
        if p.exists():
            mtime_sum += p.stat().st_mtime
    if _cache["data"] is not None and _cache["mtime_sum"] == mtime_sum:
        return _cache["data"]

    bugs = _read_category("bugs", _CATEGORIES["bugs"])
    improvements = _read_category("improvements", _CATEGORIES["improvements"])
    features = _read_category("features", _CATEGORIES["features"])
    data = {
        "bugs": bugs,
        "improvements": improvements,
        "features": features,
        "counts": {
            "bugs": len(bugs),
            "improvements": len(improvements),
            "features": len(features),
            "total": len(bugs) + len(improvements) + len(features),
        },
    }
    _cache.update(mtime_sum=mtime_sum, data=data)
    return data
