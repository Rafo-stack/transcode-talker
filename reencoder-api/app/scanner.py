"""File scanner — walks scan folders and returns large files."""
import os
from pathlib import Path
from app.models import ScanFolder, ScannedFile


def scan(scan_folders: list[ScanFolder], exclude_folders: list[str],
         extensions: list[str]) -> list[ScannedFile]:
    """
    Walk each scan folder and collect files matching extensions and size threshold.
    Excluded folders are skipped (case-insensitive prefix match).
    """
    exclude_norm = [e.strip().lower().rstrip("/") for e in exclude_folders if e.strip()]
    ext_set      = {e.lower() for e in extensions}
    results: list[ScannedFile] = []

    for folder in scan_folders:
        base            = folder.path
        threshold_bytes = folder.threshold_mb * 1024 * 1024
        if not os.path.exists(base):
            continue

        for root, dirs, files in os.walk(base):
            root_norm = root.lower().rstrip("/")

            # Prune excluded subdirectories
            dirs[:] = [
                d for d in dirs
                if not any(
                    f"{root_norm}/{d.lower()}" == ex or
                    f"{root_norm}/{d.lower()}".startswith(ex + "/")
                    for ex in exclude_norm
                )
            ]

            for fname in files:
                ext = Path(fname).suffix.lower()
                if ext not in ext_set:
                    continue
                fpath      = os.path.join(root, fname)
                fpath_norm = fpath.lower().rstrip("/")
                if any(fpath_norm.startswith(ex + "/") or fpath_norm == ex
                       for ex in exclude_norm):
                    continue
                try:
                    fsize = os.path.getsize(fpath)
                except OSError:
                    continue
                if fsize < threshold_bytes:
                    continue
                results.append(ScannedFile(
                    path=fpath, filename=fname,
                    size_mb=round(fsize / (1024 * 1024), 1),
                    folder=base,
                    relative_path=os.path.relpath(fpath, base),
                    selected=True,
                ))

    results.sort(key=lambda f: f.size_mb, reverse=True)
    return results
