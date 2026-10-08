"""外から止める頼み(stop.bat → 動いているツール)── ランチャー連携のため

業務ツール統合ランチャー(python-business-tools-launcher)は、ツールを止めるとき
**起動ファイルの隣の `stop.bat`** を実行します。ブラウザ版は `POST /api/shutdown` で
止まりますが、**デスクトップ版はポートを持たない**ので、HTTP では頼めません。
窓に「閉じて」と頼むと(×と同じ)終了の確かめが出て、ランチャーからの切り替えのたびに
利用者が押すことになります。

そこで、錠の隣に置く1つのファイルで頼みます。どちらの版でも同じです。

    <錠の場所>\\stop.request   {"owner_pid": 錠の持ち主の pid, "force": false, ...}

    stop.bat(process_manager.py)  錠を握っている持ち主の pid 宛てに書く
    動いている Python               自分宛ての頼みを見つけたら消して、「終了」と同じ止め方で止まる
                                    (デスクトップ版は外枠に「quit」を知らせ、外枠ごと終わる)

**ほかのプロセスには触りません。** 頼みは持ち主の pid 宛てで、受け取る側も自分宛てだけを
聞きます(前の起動の頼みが残っていても聞かない)。VC計算マスタへ書いている最中なら、
書き終わるまで待ってから止まります(`force` のときは待たない ── 書く取引は途中で
止まっても元に戻るので、マスタは壊れない)。
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .logging_setup import get_logger

log = get_logger("coilcalc.stop_request")

FILE_NAME = "stop.request"
#: 頼みを見に行く間隔(秒)
POLL_SECONDS = 0.5
#: VC計算マスタへ書いている最中なら、書き終わるのを待つ上限(秒)
WRITE_WAIT_SECONDS = 15.0


def _read(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def write(place: Path, owner_pid: int, *, force: bool = False) -> bool:
    """止める頼みを書く(stop.bat から)。書けなければ False。"""
    path = Path(place) / FILE_NAME
    tmp = path.with_name(f".{FILE_NAME}.{os.getpid()}.tmp")
    data = {"owner_pid": owner_pid, "force": bool(force), "from": "stop.bat",
            "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(str(tmp), str(path))
        return True
    except OSError as exc:
        log.warning("止める頼みを書けません: %s (%s)", path, exc)
        _remove(tmp)
        return False


def withdraw(place: Path) -> None:
    """頼みを取り下げる(止まらなかったので別の止め方に替えるとき)。"""
    _remove(Path(place) / FILE_NAME)


class Watcher:
    """止める頼みを見張る。自分宛ての頼みが来たら `on_stop` を1回だけ呼ぶ。"""

    def __init__(self, place: Path, owner_pid: int, on_stop: Callable[[], None], *,
                 writing_now: Callable[[], bool] = lambda: False) -> None:
        self.path = Path(place) / FILE_NAME
        self.owner_pid = owner_pid
        self._on_stop = on_stop
        self._writing_now = writing_now
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._run, name="stop-request", daemon=True)

    def start(self) -> "Watcher":
        stale = _read(self.path)
        if stale is not None and stale.get("owner_pid") != self.owner_pid:
            _remove(self.path)                       # 前の起動に宛てた頼み
        self._thread.start()
        return self

    def close(self) -> None:
        self._done.set()

    def _run(self) -> None:
        while not self._done.wait(POLL_SECONDS):
            try:
                if not self.path.exists():
                    continue
            except OSError:
                continue
            request = _read(self.path)
            if request is None or request.get("owner_pid") != self.owner_pid:
                continue                             # 書いている途中・よその宛先
            _remove(self.path)
            force = bool(request.get("force"))
            log.info("外から終了の頼みを受けました(%s%s)", request.get("from", "?"),
                     "・中断してでも" if force else "")
            if not force:
                deadline = time.monotonic() + WRITE_WAIT_SECONDS
                while self._writing_now() and time.monotonic() < deadline:
                    time.sleep(0.1)
            self._done.set()
            self._on_stop()
            return
