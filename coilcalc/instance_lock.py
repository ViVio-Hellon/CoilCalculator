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

置き場所は作業フォルダ、そこが壊れている・書けないときは一時フォルダ(`app_config.runtime_candidates`)。
Rust も同じ順に試すので、作業フォルダが壊れていても排他は保たれます。どちらも使えない
ときは、**排他無しで起動します**(計算だけの道具で、2つ動いても壊れるデータが無いため。
起動を止めるほうが困る)。
錠は OS が持つので、落ちても残りません(プロセスが終われば外れる)。instance.json は
錠を取れなかった側が「誰が持っているか」を知るためだけに読みます。古い中身が
残っていても、錠を取れた側が上書きするので害はありません。

Windows: Rust は `LockFileEx`(ファイル全体)、Python は `msvcrt.locking`(先頭1バイト)。
範囲が重なるので互いに取れません。Linux などは両方とも `flock`。
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

log = logging.getLogger("coilcalc.instance_lock")

LOCK_NAME = "instance.lock"
OWNER_NAME = "instance.json"

KIND_BROWSER = "browser"
KIND_DESKTOP = "desktop"

#: acquire_status() の答え
ACQUIRED = "acquired"    # 取れた
BUSY = "busy"            # ほかのプロセスが握っている(もう一方の版が動いている)
UNUSABLE = "unusable"    # この場所が使えない(フォルダが壊れている・書けない)。次の候補へ


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
        return self.acquire_status() == ACQUIRED

    def acquire_status(self) -> str:
        """取れたか(ACQUIRED)・誰かが握っているか(BUSY)・この場所が使えないか(UNUSABLE)。

        「使えない」と「握られている」を分けるのは、壊れた作業フォルダを
        「もう一方の版が動いています」と取り違えて起動を止めないため。
        """
        if self._fd is not None:
            return ACQUIRED
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o644)
        except OSError as exc:
            log.warning("錠を置けません(%s): %s", self.dir, exc)
            return UNUSABLE
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
            return BUSY
        self._fd = fd
        return ACQUIRED

    def write_owner(self, kind: str, **info: Any) -> bool:
        """いま握っているのは誰か、を書く(錠を取れなかった側が読む)。

        **書けなくても起動は止めない**(印は「誰が動いているか」を知らせる手がかりに
        過ぎず、排他そのものは錠が守る)。書けなければ False。
        """
        data = {"kind": kind, "pid": os.getpid(), "started": time.strftime("%Y-%m-%d %H:%M:%S")}
        data.update(info)
        tmp = self.owner_path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(str(tmp), str(self.owner_path))
            return True
        except OSError as exc:
            log.warning("持ち主の印を書けません(起動は続けます): %s", exc)
            try:
                tmp.unlink()
            except OSError:
                pass
            return False

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


def take(candidates: Iterable[Path]) -> Tuple[str, Optional["InstanceLock"], Optional[Path]]:
    """候補の場所を前から順に試して錠を取る。Rust 側(`instance.rs` の `take`)と同じ決め方。

        (ACQUIRED, 錠, 場所)   取れた
        (BUSY, None, 場所)     その場所で誰かが握っている → 後から開いたこちらが止まる
        (UNUSABLE, None, None) どの場所も使えない → **排他無しで起動する**(止めない)
    """
    for place in candidates:
        lock = InstanceLock(place)
        status = lock.acquire_status()
        if status == ACQUIRED:
            return ACQUIRED, lock, Path(place)
        if status == BUSY:
            return BUSY, None, Path(place)
    return UNUSABLE, None, None


def find_busy(candidates: Iterable[Path]) -> Optional[Path]:
    """いま誰かが錠を握っている場所(stop.bat 用)。誰も握っていなければ None。"""
    for place in candidates:
        probe = InstanceLock(place)
        status = probe.acquire_status()
        if status == ACQUIRED:
            probe.release()
            return None
        if status == BUSY:
            return Path(place)
    return None


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
