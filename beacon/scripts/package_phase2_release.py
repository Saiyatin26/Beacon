"""BEACON V2 — Phase 2 Release Packager.

Packages the clean Phase 2 codebase into beacon_v2_phase2.zip, excluding
temporary files, caches, virtual environments, and build artifacts.
"""

import os
from pathlib import Path
import zipfile

EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".hypothesis",
    ".tempmediaStorage",
    "dist",
    ".system_generated",
}

EXCLUDE_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".log",
}

EXCLUDE_FILES = {
    "beacon_v2_phase1.zip",
    "beacon_v2_phase2.zip",
    "beacon_v2_phase3.zip",
}


def package_phase2(root_dir: Path, output_zip: Path):
    file_count = 0
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(root_dir):
            # Prune excluded directories
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]

            for f in files:
                if f in EXCLUDE_FILES:
                    continue
                file_path = Path(root) / f
                if file_path.suffix in EXCLUDE_EXTENSIONS:
                    continue
                # Calculate relative path
                rel_path = file_path.relative_to(root_dir).as_posix()
                zf.write(file_path, rel_path)
                file_count += 1

    size_mb = output_zip.stat().st_size / (1024 * 1024)
    print(f"PACKAGED: {output_zip.name} with {file_count} files ({size_mb:.2f} MB)")


if __name__ == "__main__":
    beacon_root = Path(__file__).resolve().parent.parent
    zip_path = beacon_root / "beacon_v2_phase2.zip"
    package_phase2(beacon_root, zip_path)
