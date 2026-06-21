#!/usr/bin/env python3
import configparser
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"

EXCLUDED_DIRS = {
    ".git",
    ".github",
    "__pycache__",
    "dist",
    "scripts",
}

EXCLUDED_FILES = {
    ".DS_Store",
    "tmp_control.xml",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".tmp",
    ".log",
}


def plugin_version():
    parser = configparser.ConfigParser()
    parser.read(ROOT / "plugin.cfg", encoding="utf-8")
    return parser.get("PLUGIN", "VERSION")


def should_include(path):
    rel = path.relative_to(ROOT)
    if any(part in EXCLUDED_DIRS for part in rel.parts):
        return False
    if rel.name in EXCLUDED_FILES:
        return False
    if path.suffix in EXCLUDED_SUFFIXES:
        return False
    return True


def main():
    version = plugin_version()
    DIST.mkdir(exist_ok=True)
    output = DIST / f"loxberry-satel-ethm-{version}.zip"
    tmp_output = DIST / f"{output.name}.tmp"

    with ZipFile(tmp_output, "w", ZIP_DEFLATED) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_dir() or not should_include(path):
                continue
            archive.write(path, path.relative_to(ROOT).as_posix())

    tmp_output.replace(output)
    print(output)


if __name__ == "__main__":
    main()
