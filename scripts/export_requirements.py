"""Writes requirements.txt with the EXACT versions installed in this venv (so Docker matches what you tested).
PyTorch is installed separately in the Dockerfile (CPU build), so it is not listed here."""
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

EXTRAS = {"uvicorn": "[standard]"}
lines = []
for raw in Path("requirements.in").read_text().splitlines():
    name = raw.split("#")[0].strip()
    if not name:
        continue
    try:
        lines.append(f"{name}{EXTRAS.get(name, '')}=={version(name)}")
    except PackageNotFoundError:
        print("NOT INSTALLED in this venv (skipped):", name)
Path("requirements.txt").write_text("\n".join(lines) + "\n")
print(f"Wrote requirements.txt with {len(lines)} pinned packages")