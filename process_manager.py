"""止める ── `stop.bat` から

    python process_manager.py           動いているブラウザ版を止める
    python process_manager.py --status  何が動いているかだけ出す
    python process_manager.py --force   応答が無ければ pid で止める(デスクトップ版も)

ブラウザ版には画面の「終了」と同じ要求(POST /api/shutdown)を送り、止まるのを
錠が外れることで確かめます。デスクトップ版はふだん窓の × で閉じます
(`--force` のときだけ pid で止めます)。**ほかの Python アプリには触りません。**
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

APP_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_ROOT))

from coilcalc import app_config, instance_lock  # noqa: E402


def lock_free() -> bool:
    """錠が空いているか(= どちらの版も動いていない)。置き場所の候補をすべて見る。"""
    return instance_lock.find_busy(app_config.runtime_candidates()) is None


def wait_free(seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if lock_free():
            return True
        time.sleep(0.2)
    return lock_free()


def ask_shutdown(url: str) -> bool:
    try:
        # stop.bat は「止める」と決めて実行するものなので、確かめ済みとして送る
        req = urllib.request.Request(url.rstrip("/") + "/api/shutdown", data=b'{"confirmed": true}', method="POST",
                                     headers={"Content-Type": "application/json"})
        # 社内のプロキシを通さない(127.0.0.1 へ直接)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=5) as res:
            return res.status == 200
    except OSError:
        return False


def kill(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="コイル・平板 重量計算ツールを止める")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    runtime = instance_lock.find_busy(app_config.runtime_candidates())
    if runtime is None:
        print("動いていません。")
        return 0
    owner = instance_lock.read_owner(runtime) or {}
    what = instance_lock.describe(owner)
    if args.status:
        print(f"{what} が動いています: {json.dumps(owner, ensure_ascii=False)}")
        return 0

    if owner.get("kind") == instance_lock.KIND_BROWSER and owner.get("url"):
        print(f"{what} を止めます({owner['url']})")
        if ask_shutdown(owner["url"]) and wait_free(8):
            print("止めました。")
            return 0
        if not args.force:
            print("応答がありません。stop.bat --force で強制的に止められます。")
            return 1
    elif not args.force:
        print(f"{what} が開いています。窓の × で閉じてください"
              "(強制的に止めるときは stop.bat --force)。")
        return 1

    pid = owner.get("pid")
    if not isinstance(pid, int):
        print("止める相手(pid)が分かりません。")
        return 1
    print(f"pid {pid} を止めます")
    kill(pid)
    if wait_free(8):
        print("止めました。")
        return 0
    print("止められませんでした。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
