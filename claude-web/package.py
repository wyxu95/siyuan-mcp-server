#!/usr/bin/env python3
"""Build the Claude plugin archive."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

root = Path(__file__).resolve().parent
source = root
output = root / "dist"
output.mkdir(exist_ok=True)
files = [source / "README.md", *sorted((source / "skills").rglob("SKILL.md")),
         source / ".claude-plugin/plugin.json", source / ".mcp.json"]
archive = output / "siyuan-notes-claude.zip"
with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
    for path in files:
        bundle.write(path, path.relative_to(source))
print(archive)
