#!/usr/bin/env python3
"""Run the envreview command line: python scripts/envreview.py <command> ...

Any Python 3.10+ can launch it. `setup` builds the skill's own environment in
~/.envreview/venv from requirements.txt; afterwards, when the Python that launched a command
lacks the packages, the command runs in that environment instead, so the agent need not know
which of the user's Pythons has them.
"""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV = Path.home() / ".envreview" / "venv"
VENV_PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

# Windows consoles and pipes default to a legacy code page; titles with "−" or "é" would crash
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, str(HERE))
from envreview.cli import NEEDED, main  # noqa: E402  (stdlib-only imports at module level)


def setup() -> int:
    """Create ~/.envreview/venv and install requirements.txt into it (about 1.4 GB)."""
    if not VENV_PY.exists():
        print(f"Creating {VENV} ...", flush=True)
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    subprocess.run([str(VENV_PY), "-m", "pip", "install", "-q", "--upgrade", "pip"], check=True)
    print("Installing packages (a few minutes; torch is the largest) ...", flush=True)
    code = subprocess.run([str(VENV_PY), "-m", "pip", "install", "-r",
                           str(HERE.parent / "requirements.txt")]).returncode
    print("Done. Commands now run in this environment automatically." if code == 0
          else "pip failed; see the messages above.")
    return code


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["setup"]:
        sys.exit(setup())
    in_venv = Path(sys.prefix).resolve() == VENV.resolve()
    missing = any(importlib.util.find_spec(m) is None for m in NEEDED)
    if missing and not in_venv and VENV_PY.exists():
        sys.exit(subprocess.run([str(VENV_PY), str(Path(__file__).resolve()), *args]).returncode)
    main()
