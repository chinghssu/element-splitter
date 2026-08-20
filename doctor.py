#!/usr/bin/env python3
"""doctor — check whether this machine can run element-splitter, and fix what's missing.

    python doctor.py          check only, changes nothing
    python doctor.py --fix    download the missing checkpoint

sha256 uses trust-on-first-use: when that field in models/SOURCES.json is null, the
first successful download writes back the computed sha256; every later --fix verifies
against it, so a swapped remote file doesn't go unnoticed.
"""
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODELS = HERE / "models"
SOURCES = MODELS / "SOURCES.json"
FIX = "--fix" in sys.argv[1:]

OK, WARN, BAD = "✅", "🟡", "❌"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_python():
    major, minor = sys.version_info[:2]
    if (major, minor) >= (3, 10):
        print(f"{OK} Python {major}.{minor}")
        return True
    print(f"{BAD} Python {major}.{minor}, need 3.10 or newer")
    return False


def check_packages():
    missing = []
    for mod, hint in [
        ("torch", "torch"),
        ("PIL", "Pillow"),
        ("numpy", "numpy"),
        ("mobile_sam", "mobile-sam (see requirements.txt for the git install)"),
        ("timm", "timm (mobile_sam's TinyViT needs it, but doesn't declare it)"),
        ("PySide6", "PySide6"),
        ("simple_lama_inpainting", "simple-lama-inpainting"),
    ]:
        try:
            __import__(mod)
            print(f"{OK} {hint}")
        except ImportError:
            print(f"{BAD} {hint} not installed")
            missing.append(hint)
    if missing:
        print(f"{WARN} Run: pip install -r requirements.txt")
        return False
    return True


def check_checkpoint() -> bool:
    sources = json.loads(SOURCES.read_text())
    ok = True
    for name, meta in sources.items():
        path = MODELS / name
        if path.exists():
            digest = sha256_of(path)
            if meta.get("sha256") and digest != meta["sha256"]:
                print(f"{BAD} {name}: sha256 mismatch (corrupted or swapped) — delete it and run --fix again")
                ok = False
                continue
            print(f"{OK} {name}")
            continue

        print(f"{BAD} {name} missing (~{meta.get('approx_size_mb', '?')}MB)")
        ok = False
        if not FIX:
            continue

        print(f"    Downloading: {meta['url']}")
        MODELS.mkdir(exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        try:
            urllib.request.urlretrieve(meta["url"], tmp)
        except Exception as e:  # noqa: BLE001 — surface the real download error
            print(f"{BAD} Download failed: {e}")
            tmp.unlink(missing_ok=True)
            continue

        digest = sha256_of(tmp)
        if meta.get("sha256"):
            if digest != meta["sha256"]:
                print(f"{BAD} Downloaded but sha256 mismatch — deleted, please retry")
                tmp.unlink(missing_ok=True)
                continue
        else:
            meta["sha256"] = digest
            SOURCES.write_text(json.dumps(sources, indent=2, ensure_ascii=False) + "\n")
            print(f"{WARN} First download — recorded sha256={digest[:16]}... for future checks")

        tmp.rename(path)
        print(f"{OK} {name} downloaded")
        ok = True
    return ok


def main():
    checks = [check_python(), check_packages(), check_checkpoint()]
    print()
    if all(checks):
        print(f"{OK} Everything's ready — run: python app.py")
    else:
        print(f"{BAD} Some checks failed." + ("" if FIX else " Try `python doctor.py --fix` to auto-fix."))
        sys.exit(1)


if __name__ == "__main__":
    main()
