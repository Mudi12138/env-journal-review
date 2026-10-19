"""Check an unpacked index pack against its manifest."""
import hashlib
from pathlib import Path


def verify(root: Path, manifest: dict) -> dict:
    bad = {}
    for name, info in manifest["files"].items():
        p = Path(root) / name
        if not p.exists():
            bad[name] = "missing"
            continue
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(1 << 22), b""):
                h.update(b)
        if h.hexdigest() != info["sha256"]:
            bad[name] = "checksum mismatch"
    return {"ok": not bad, "problems": bad}
