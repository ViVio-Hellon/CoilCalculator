"""ブラウザ版とデスクトップ版を**同時に動かさない**ための錠

    <作業フォルダ>\\runtime\\instance.lock   OS のファイルロック(握っている間だけ有効)
    <作業フォルダ>\\runtime\\instance.json   いま握っているのは誰か(版・pid・URL)

**後から開いたほうが止まります**(どちらの版が先でも同じ)。

    先に動いている  後から開いた       後から開いたほうの動き
    ブラウザ版      ブラウザ版         新しく起動せず、動いている画面をブラウザで開く
    ブラウザ版      デスクトップ版     「ブラウザ版が動いています」と出して終わる
    デスクトップ版  ブラウザ版         「デスクトップ版が開いています」と出して終わる
    デスクトップ版  デスクトップ版     新しく起動せず、開いている窓を前に出す

デスクトップ版(Rust)も**同じ2つのファイル**を使います(`src-tauri/src/instance.rs`)。
錠は OS が持つので、落ちても残りません(プロセスが終われば外れる)。instance.json は
錠を取れなかった側が「誰が持っているか」を知るためだけに読みます。古い中身が
残っていても、錠を取れた側が上書きするので害はありません。

Windows: Rust は `LockFileEx`(ファイル全体)、Python は `msvcrt.locking`(先頭1バイト)。
範囲が重なるので互いに取れません。Linux などは両方とも `flock`。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

LOCK_NAME = "instance.lock"
OWNER_NAME = "instance.json"

KIND_BROWSER = "browser"
KIND_DESKTOP = "desktop"


class InstanceLock:
    """1つの作業フォルダにつき、1つのプロセスだけが握れる錠。"""

    def __init__(self, runtime_dir: Path) -> None:
        self.dir = Path(runtime_dir)
        self.path = self.dir / LOCK_NAME
        self.owner_path = self.dir / OWNER_NAME
        self._fd: Optional[int] = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> bool:
        """取れたら True。**待たない**(誰かが握っていればすぐ False)。"""
        if self._fd is not None:
            return True
        self.dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            if os.name == "nt":
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._fd = fd
        return True

    def write_owner(self, kind: str, **info: Any) -> None:
        """いま握っているのは誰か、を書く(錠を取れなかった側が読む)。"""
        data = {"kind": kind, "pid": os.getpid(), "started": time.strftime("%Y-%m-%d %H:%M:%S")}
        data.update(info)
        tmp = self.owner_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(str(tmp), str(self.owner_path))

    def release(self) -> None:
        if self._fd is None:
            return
        # 自分が書いた「持ち主」だけを消す(次の持ち主のものは消さない)
        owner = read_owner(self.dir, wait=0)
        if owner and owner.get("pid") == os.getpid():
            try:
                self.owner_path.unlink()
            except OSError:
                pass
        try:
            if os.name == "nt":
                import msvcrt
                os.lseek(self._fd, 0, os.SEEK_SET)
                try:
                    msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
        finally:
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> "InstanceLock":
        return self

    def __exit__(self, *exc) -> None:
        self.release()


def read_owner(runtime_dir: Path, *, wait: float = 2.0) -> Optional[Dict[str, Any]]:
    """錠を握っているのは誰か。**書き終わる前に読むことがある**ので、少し待って読み直す。"""
    path = Path(runtime_dir) / OWNER_NAME
    deadline = time.monotonic() + wait
    while True:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("kind"):
                return data
        except (OSError, ValueError):
            pass
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.1)


def describe(owner: Optional[Dict[str, Any]]) -> str:
    """利用者に出す「何が動いているか」。"""
    kind = (owner or {}).get("kind")
    if kind == KIND_DESKTOP:
        return "デスクトップ版(CoilCalculator.exe)"
    if kind == KIND_BROWSER:
        return "ブラウザ版(Start.vbs)"
    return "もう一方の版"
