"""デスクトップ版(Tauri)からの入口 ── **ポートを使わない**

窓を持つ外枠(Rust/Tauri、`src-tauri/`)がこのプロセスを子として起動し、
**標準入出力**で要求を渡します。ソケットは1つも開きません。

    画面 ─app://─▶ 外枠(Rust) ─標準入力─▶ bridge.py ─▶ coilcalc.web(計算)
                  ◀─────────── 標準出力 ◀──

画面のファイル(HTML・JS・CSS・three.js・Chart.js・フォント)は外枠が自分で
アプリのフォルダから返します。ここに来るのは `/api/…`(計算)だけです。

【やりとりの形】1件 = 見出し1行(JSON)+ 本文(見出しの `len` バイト)
    python-web-tools(梱包資材総合ツール)の bridge と同じ形です。

    要求  {"id": 7, "method": "POST", "path": "/api/coil/calc", "query": "",
           "headers": [["Content-Type", "application/json"]], "len": 12}\\n<本文>
    応答  {"id": 7, "status": 200, "headers": [[...]], "len": 345}\\n<本文>
    知らせ {"event": "started" | "quit" | "fatal", ...}\\n

【知らせ】
    started  … 受け付けを始めた
    quit     … 終了してよい(画面からの終了)
    fatal    … 起動できない(`message` `hint` `log_dir`)。外枠が理由を窓に出す

【標準出力を守る】
やりとりに使う標準出力へ、ほかの誰かが1文字でも書くとそれ以降すべてずれます。
最初に本物の標準出力を別に取っておき、記述子 1 は標準エラーへ付け替えます。

**標準ライブラリだけで動きます。** 外枠が標準入力を閉じたら(exe が終わったら)終わります。
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, BinaryIO, Optional, Tuple

APP_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_ROOT))

# 1件の本文の上限(壊れた見出しで巨大な読み込みをしないため)。計算の本文は数百バイト
MAX_BODY = 4 * 1024 * 1024
MIN_PYTHON = (3, 8)
# 「quit」を知らせてから、外枠が標準入力を閉じるのを待つ上限(秒)
QUIT_GRACE = 10.0


def read_frame(stream: BinaryIO) -> Optional[Tuple[dict, bytes]]:
    """1件読む。相手が閉じたら `None`。"""
    line = stream.readline()
    if not line:
        return None
    head = json.loads(line.decode("utf-8"))
    size = int(head.get("len", 0) or 0)
    if size < 0 or size > MAX_BODY:
        raise ValueError(f"本文の長さが不正です: {size}")
    body = b""
    while len(body) < size:
        chunk = stream.read(size - len(body))
        if not chunk:
            raise EOFError("本文の途中で終わりました")
        body += chunk
    return head, body


class FrameWriter:
    """応答と知らせを書く。**1件ずつ丸ごと**書く。"""

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._lock = threading.Lock()

    def write(self, head: dict, body: bytes = b"") -> None:
        head = dict(head)
        if body or "id" in head:
            head["len"] = len(body)
        data = json.dumps(head, ensure_ascii=False).encode("utf-8") + b"\n" + body
        with self._lock:
            self._stream.write(data)
            self._stream.flush()

    def event(self, name: str, **fields: Any) -> None:
        self.write({"event": name, **fields})


def _protect_stdout() -> BinaryIO:
    """本物の標準出力を取っておき、記述子 1 は標準エラーへ向ける。"""
    proto = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
    sys.stdout.flush()
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr
    return proto


def watch_stop_requests(app, log) -> None:
    """stop.bat(ランチャーからの停止)の頼みを聞く。**錠を握っている外枠の pid 宛て**の頼みだけ。

    デスクトップ版はポートを持たないので、頼みは錠の隣のファイルで受ける(coilcalc/stop_request.py)。
    外枠は錠を取ってからここを起こすので、錠の場所と持ち主はもう決まっている。
    錠が無い(作業フォルダも一時フォルダも使えない)ときは聞かない ── 窓の × で閉じる。
    """
    from coilcalc import app_config, instance_lock, stop_request
    from coilcalc.vc import db as vc_db

    place = instance_lock.find_busy(app_config.runtime_candidates())
    owner = instance_lock.read_owner(place, wait=2.0) if place is not None else None
    if not owner or owner.get("kind") != instance_lock.KIND_DESKTOP or not isinstance(owner.get("pid"), int):
        log.info("外から止める頼みは受けません(錠の持ち主が分からない)")
        return
    stop_request.Watcher(place, owner["pid"], app.request_shutdown,
                         writing_now=vc_db.writing_now).start()


def serve(reader: BinaryIO, writer: FrameWriter) -> int:
    """標準入力から要求を読み、順に答える。相手が閉じたら終わる。

    計算は1件 1ms もかからないので、届いた順に1つずつ答える(答えの順も崩れない)。
    """
    from coilcalc import app_config, logging_setup, web

    conf = app_config.load()
    logging_setup.setup(app_config.log_dir(conf), to_stderr=True)
    log = logging_setup.get_logger("bridge")

    stop = threading.Event()

    def quit_now() -> None:
        stop.set()
        try:
            writer.event("quit")
        except (BrokenPipeError, OSError):
            pass
        # ふだんは外枠が「quit」を受けて標準入力を閉じ、ここも終わる。
        # 外枠が閉じないまま固まっても、置き去りにならないよう自分で終わる
        fallback = threading.Timer(QUIT_GRACE, lambda: os._exit(0))
        fallback.daemon = True
        fallback.start()

    app = web.App(web.MODE_DESKTOP, on_shutdown=quit_now)
    log.info("デスクトップ版 %s を始めます(ポートは使いません)", conf.get("version"))
    watch_stop_requests(app, log)
    writer.event("started", version=conf.get("version"))
    while not stop.is_set():
        try:
            frame = read_frame(reader)
        except (ValueError, EOFError) as exc:
            log.error("要求を読めませんでした: %s", exc)
            return 1
        if frame is None:
            log.info("外枠が閉じました。終わります")
            return 0
        head, body = frame
        headers = {str(k).lower(): str(v) for k, v in head.get("headers", [])}
        req = web.Request(method=str(head.get("method") or "GET").upper(),
                          path=str(head.get("path") or "/"), query=str(head.get("query") or ""),
                          headers=headers, body=body)
        res = app.handle(req)
        try:
            writer.write({"id": head.get("id"), "status": res.status,
                          "headers": [[k, v] for k, v in res.headers]}, res.body)
        except (BrokenPipeError, OSError):
            return 0                              # 外枠が先に終わった
    return 0


def main() -> int:
    proto = _protect_stdout()
    writer = FrameWriter(proto)
    if sys.version_info < MIN_PYTHON:
        writer.event("fatal", message=f"Python {sys.version.split()[0]} は古すぎます",
                     hint="Python 3.8 以上を入れてください(https://www.python.org/downloads/)。",
                     log_dir="")
        return 1
    try:
        return serve(sys.stdin.buffer, writer)
    except Exception as exc:                      # noqa: BLE001 - 理由を外枠へ渡す
        log_dir = ""
        try:
            from coilcalc import app_config
            log_dir = str(app_config.log_dir())
        except Exception:                         # noqa: BLE001
            pass
        writer.event("fatal", message=f"起動中に思わぬエラー: {exc}",
                     hint="ログを確認してください。", log_dir=log_dir)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
