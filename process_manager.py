"""止める ── `stop.bat` から(業務ツール統合ランチャーも、ツールを止めるときこれを実行する)

    python process_manager.py           動いているこのツールを止める(ブラウザ版もデスクトップ版も)
    python process_manager.py --status  何が動いているかだけ出す
    python process_manager.py --force   VC計算マスタへ書いている最中でも止める。
                                        頼んでも止まらなければ pid で止める
    python process_manager.py --check   使えるか(launcher_check.bat)。0 = 使える / 2 = 準備中 /
                                        1 = 動いていない。最後の1行に今の様子

止め方(どれも**確かめの窓を出さない** ── stop.bat は「止める」と決めて実行するもの):

    ブラウザ版      画面の「終了」と同じ要求(POST /api/shutdown)を送る
    デスクトップ版  ポートが無いので、錠の隣に「止める頼み」を置く(coilcalc/stop_request.py)。
                    動いている Python が見つけて、外枠ごと終わる

止まったことは錠が外れることで確かめます。戻り値: 0 = 止まった(動いていなかった)/ 1 = 止まらない
(最後の1行に理由。launcher_stop.bat から呼ぶとランチャーがそのまま利用者に出す)。
**ほかの Python アプリには触りません**(頼みは錠の持ち主の pid 宛て。pid で止めるのも、
錠を握っている持ち主 = このツールだけ)。
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

from coilcalc import app_config, instance_lock, stop_request  # noqa: E402


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


def ask_shutdown(url: str, force: bool = False) -> bool:
    """ランチャーと同じ頼み方で止める。VC計算マスタへ書いている最中なら 409 で断られる(force なら止まる)。"""
    body = json.dumps({"force": bool(force)}).encode("utf-8")
    try:
        req = urllib.request.Request(url.rstrip("/") + "/api/shutdown", data=body, method="POST",
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


def health_of(url: str) -> dict:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url.rstrip("/") + "/api/health", timeout=2) as res:
            data = json.loads(res.read().decode("utf-8"))
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


#: launcher_check.bat の終了コード(業務ツール統合ランチャー 1.7.0 の取り決め)
CHECK_READY, CHECK_NOT_RUNNING, CHECK_STARTING = 0, 1, 2


def check() -> int:
    """使えるか。**錠を取りにいかない**(ランチャーは起動を待つあいだ毎秒これを呼ぶ。
    錠を試しに取ると、ちょうど錠を取ろうとしている版が「もう一方が動いている」と止まる)。"""
    found = instance_lock.running_owner(app_config.runtime_candidates())
    if found is None:
        print("動いていません")
        return CHECK_NOT_RUNNING
    _, owner = found
    if owner.get("kind") == instance_lock.KIND_BROWSER:
        url = str(owner.get("url") or "")
        body = health_of(url) if url else {}
        if body.get("app_id") == app_config.load().get("app_id") and body.get("ready") is True:
            print(f"ブラウザ版が使えます({url})")
            return CHECK_READY
        print("ブラウザ版を準備しています")
        return CHECK_STARTING
    print(f"{instance_lock.describe(owner)} が動いています")
    return CHECK_READY


#: 頼んでから止まるのを待つ上限(秒)。VC計算マスタへ書いている最中なら書き終わるまで待つ(最大15秒)
GRACEFUL_WAIT = 25.0
FORCE_WAIT = 8.0


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="VC長さ・コイル平板 計算ツールを止める")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        return check()

    runtime = instance_lock.find_busy(app_config.runtime_candidates())
    if runtime is None:
        print("動いていません。")
        return 0
    owner = instance_lock.read_owner(runtime) or {}
    what = instance_lock.describe(owner)
    if args.status:
        print(f"{what} が動いています: {json.dumps(owner, ensure_ascii=False)}")
        return 0

    # 途中の様子は溜めておき、最後に結果と一緒に出す。**止めなかった理由は先頭と最後の行**に置く
    # (業務ツール統合ランチャー 1.7.1 は、stop.bat ならはじめの行、launcher_stop.bat なら最後の行を
    # 「止めなかった理由」として利用者に出す)
    steps = []

    def done(code: int, result: str, *extra: str) -> int:
        lines = [result, *extra, *steps]
        if code != 0:
            lines.append(result)
        print("\n".join(lines))
        return code

    pid = owner.get("pid")
    wait = FORCE_WAIT if args.force else GRACEFUL_WAIT
    if owner.get("kind") == instance_lock.KIND_BROWSER and owner.get("url"):
        steps.append(f"{what} に終了を頼みました({owner['url']})")
        if ask_shutdown(owner["url"], args.force) and wait_free(wait):
            return done(0, "止めました。")
    if isinstance(pid, int):
        # デスクトップ版(と、HTTP で答えないブラウザ版)。錠の持ち主宛てに頼む
        steps.append(f"{what} に終了を頼みました(pid {pid})")
        if stop_request.write(runtime, pid, force=args.force) and wait_free(wait):
            return done(0, "止めました。")
        stop_request.withdraw(runtime)
    if not args.force:
        return done(1, "VC計算マスタへの書き込みが終わらないため、止めませんでした",
                    "少し待ってからもう一度止めるか、強制終了(stop.bat --force)を選んでください。")
    if not isinstance(pid, int):
        return done(1, "止める相手(pid)が分からないため、止めませんでした")
    # 錠を握っているのは持ち主の pid だけ(錠を取った側が instance.json を書き直す)。
    # その pid がまだ錠を握っている = このツールなので、ほかのプロセスを落とすことはない
    if lock_free():
        return done(0, "止めました。")
    steps.append(f"pid {pid} を止めました(--force)")
    kill(pid)
    if wait_free(8):
        return done(0, "止めました。")
    return done(1, "pid で止めても終わらないため、止められませんでした")

if __name__ == "__main__":
    raise SystemExit(main())
