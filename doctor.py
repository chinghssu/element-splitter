#!/usr/bin/env python3
"""doctor — 檢查這台電腦能不能跑 element-splitter，缺什麼就補什麼。

    python doctor.py          只檢查，不動任何東西
    python doctor.py --fix    下載缺少的 checkpoint

sha256 採 trust-on-first-use：models/SOURCES.json 裡該欄位是 null 時，第一次下載
成功後把算出來的 sha256 寫回去；之後每次 --fix 都會用那個值驗證完整性，避免之後
遠端檔案被置換掉卻沒察覺。
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
    print(f"{BAD} Python {major}.{minor}，需要 3.10 以上")
    return False


def check_packages():
    missing = []
    for mod, hint in [
        ("torch", "torch"),
        ("PIL", "Pillow"),
        ("numpy", "numpy"),
        ("mobile_sam", "mobile-sam（見 requirements.txt 的 git 安裝方式）"),
    ]:
        try:
            __import__(mod)
            print(f"{OK} {hint}")
        except ImportError:
            print(f"{BAD} {hint} 未安裝")
            missing.append(hint)
    if missing:
        print(f"{WARN} 請先執行：pip install -r requirements.txt")
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
                print(f"{BAD} {name}：sha256 不符（可能損毀或被置換），請刪除後重新 --fix")
                ok = False
                continue
            print(f"{OK} {name}")
            continue

        print(f"{BAD} {name} 缺失（約 {meta.get('approx_size_mb', '?')}MB）")
        ok = False
        if not FIX:
            continue

        print(f"    下載中：{meta['url']}")
        MODELS.mkdir(exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        try:
            urllib.request.urlretrieve(meta["url"], tmp)
        except Exception as e:  # noqa: BLE001 — 下載失敗原因要如實印出來
            print(f"{BAD} 下載失敗：{e}")
            tmp.unlink(missing_ok=True)
            continue

        digest = sha256_of(tmp)
        if meta.get("sha256"):
            if digest != meta["sha256"]:
                print(f"{BAD} 下載完但 sha256 不符，已刪除，請重試")
                tmp.unlink(missing_ok=True)
                continue
        else:
            meta["sha256"] = digest
            SOURCES.write_text(json.dumps(sources, indent=2, ensure_ascii=False) + "\n")
            print(f"{WARN} 首次下載，已記錄 sha256={digest[:16]}… 供之後驗證")

        tmp.rename(path)
        print(f"{OK} {name} 下載完成")
        ok = True
    return ok


def main():
    checks = [check_python(), check_packages(), check_checkpoint()]
    print()
    if all(checks):
        print(f"{OK} 一切就緒，可以執行：python app.py")
    else:
        print(f"{BAD} 還有項目沒過。" + ("" if FIX else " 執行 `python doctor.py --fix` 試著自動修。"))
        sys.exit(1)


if __name__ == "__main__":
    main()
