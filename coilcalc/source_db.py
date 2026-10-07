"""共有フォルダの sqlite3(VC計算マスタ)を、**手元に写してから**読む

日報管理ツールの `nippou/source_db.py` から、VC計算マスタに要る部分だけを移したもの。

【なぜ写すのか】
共有の sqlite3 を**開くと、開いた側もそのファイルに手を出します**(ロック・付き添いの
`-journal` など)。Windows では、誰かが開いているファイルは**置き換えられません** ──
読んでいるだけの端末が、管理者のマスタの差し替えを止めてしまいます。だから読むときは
共有のファイルを開かず、バイト列として手元(%LOCALAPPDATA%\\CoilCalculator\\cache\\source)へ
写して、写しを開きます。写しは大きさと更新時刻が変わったときだけ写し直します
(ふだんの読みでは共有のファイルを1度も開かない)。

【写しが破れていたら】
相手が書いている最中に写すと、途中で切れた写しができることがあります。写したあとに
`PRAGMA quick_check` を通し、破れていれば少し待って写し直します。だめなら読めないと言う
(黙って欠けた中身を読ませない)。

共有のファイルそのものを開くのは、管理者が書くときだけ(`vc/db.py` の `writing`。
開いて書いて、すぐ閉じる)。
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Optional, Tuple

from . import app_config
from .logging_setup import get_logger

log = get_logger("source_db")

# 取り込み元の拡張子。**この2つだけを探す**
SUFFIXES = (".sqlite3", ".db")

# 一緒に写すファイル。**本体だけ写すと、直前に書かれた分が抜ける**
SIDECARS = ("-wal", "-shm", "-journal")

# 共有フォルダの上でロックを待つ時間(ミリ秒)
BUSY_TIMEOUT_MS = 10_000

# 破れた写しを引いたときに、写し直す回数と、そのあいだ待つ秒数。
# 相手が書き終わるのを待つだけなので、長くは待たない
COPY_RETRY = 3
COPY_RETRY_WAIT_SEC = 0.4

# sqlite3 のファイルの先頭にある印
MAGIC = b"SQLite format 3\x00"


class SourceError(RuntimeError):
    """取り込み元を読めなかった。"""


def quote_identifier(name: str) -> str:
    """テーブル名・列名を囲む。日本語の名前がそのまま出てくるので必須。"""
    return '"' + str(name).replace('"', '""') + '"'


# ==================================================================
# URI では開きません ── **開くのは手元の写しだけ**
#
# ここには以前 `to_uri()` がありました。共有フォルダ(UNC)を
# `file:////サーバ/共有/x.sqlite3` の形に組み立てる関数です ──
# `Path.as_uri()` は `//サーバ` を authority として書き、SQLite は
# 空か `localhost` 以外の authority を受け付けないためです。
#
# **一度も呼ばれていませんでした。** 書いた回(b107eb4)で同時に
# 「読むときは写しを開く」に決めたので、URI で共有を開く道がその場で
# 無くなっています。残しておくと「ここを通っている」と読めてしまうので
# 消しました ── **効いていないものを置くと、効いているつもりで
# 次の人が数えます。**
#
# いま共有のファイルそのものを開くのは、マスタ管理から人が書くときだけ
# (`SourceConnection`)。そちらは素のパスで開きます ── `sqlite3.connect`
# は UNC のパスをそのまま受けるので、URI に直す必要がありません
# (URI に直すほうが壊れる、というのが上の話です)。
# ==================================================================


def looks_like_sqlite(path: Path) -> bool:
    """先頭の印だけを見る。**中身の正しさまでは見ない。**"""
    try:
        with open(path, "rb") as handle:
            return handle.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


# ==================================================================
# 手元への写し
# ==================================================================
# 写しの置き場。**同じファイルを何度も写さない** ── 画面は開くたびに
# 何度もマスタを引くので、そのつど共有から写すと待たされる
_COPIES: Dict[str, Tuple[Tuple[int, int], Path]] = {}
_COPY_DIR: Optional[Path] = None


def copy_dir() -> Path:
    """写しの置き場所。利用者ごとのローカル領域の下に置く。

    共有フォルダにもアプリ本体にも書かない(基盤仕様書 2.7)。終了時に
    消さないのは、次の起動でそのまま使い回せるようにするためです ──
    元が変わっていなければ写し直しません。

    **毎回、あることを確かめます。** 一度作ったから在り続ける、とは
    言えません ── ディスクの掃除で消えることもあれば、利用者ごとの
    ローカル領域そのものが差し替わることもあります(検証用の起動、
    `NIPPOU_LOCAL_DIR`)。無い場所へ写そうとすると、参照マスタが
    まるごと「読めません」になります。
    """
    global _COPY_DIR
    if _COPY_DIR is not None:
        try:
            _COPY_DIR.mkdir(parents=True, exist_ok=True)
            return _COPY_DIR
        except OSError:
            _COPY_DIR = None
    # 作業フォルダが壊れている・書けない PC でも、共有のマスタを読めるように
    # 一時フォルダへ逃がす(錠の置き場所と同じ考え。`app_config.runtime_candidates`)
    last: Optional[OSError] = None
    for base in (app_config.local_root(), app_config.temp_root() / "CoilCalculator"):
        candidate = base / "cache" / "source"
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            last = exc
            continue
        _COPY_DIR = candidate
        return candidate
    raise SourceError(f"マスタの写しを置く場所を作れません: {last}")


def copy_dir_path() -> Path:
    """写しの置き場所。**作らない**(見せるだけのとき ── 設定画面の一覧)。"""
    return _COPY_DIR or app_config.local_root() / "cache" / "source"


def _copy_name(resolved: Path) -> str:
    """写しのファイル名。**元の名前が読める形にする。**

    調べるときに開くのは写しのほうなので、`3f2a1b.sqlite3` では
    どのマスタか分かりません。名前を残したうえで、同じ名前が別のフォルダ
    にある場合に備えて道の指紋を付けます。
    """
    import hashlib

    digest = hashlib.sha1(str(resolved).encode("utf-8")).hexdigest()[:8]
    return f"{resolved.stem}_{digest}{resolved.suffix}"


def _do_copy(resolved: Path, target: Path) -> None:
    """本体と付き添いを写す。**付き添いを先に**。

    本体を先に写すと、そのあと付き添いを写すまでのあいだに相手が
    書き進めることがあり、本体より新しい付き添いを掴みます。先に
    付き添いを取っておけば、少なくとも本体より古い側に倒れます。
    """
    for extra in SIDECARS:
        side = Path(str(resolved) + extra)
        beside = Path(str(target) + extra)
        beside.unlink(missing_ok=True)
        if side.exists():
            shutil.copyfile(side, beside)
    shutil.copyfile(resolved, target)


def _is_intact(path: Path) -> bool:
    """写しが破れていないか。**引いてみて確かめる。**

    `quick_check` は `integrity_check` より軽く、ページの壊れは拾います。
    共有の上で写しが切り取られる形の壊れ方は、ここで出ます。
    """
    try:
        conn = sqlite3.connect(str(path), timeout=BUSY_TIMEOUT_MS / 1000)
    except sqlite3.Error:
        return False
    try:
        row = conn.execute("PRAGMA quick_check(1)").fetchone()
        return bool(row) and str(row[0]).lower() == "ok"
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def local_copy(path: Path) -> Path:
    """共有のファイルを手元に写して、写しの道を返す。

    中身が変わっていなければ写し直しません(大きさと更新時刻で見ます)。
    **破れた写しは返しません** ── 引けないと分かったら写し直し、
    それでも駄目なら `SourceError` にします。黙って欠けた中身を
    読ませるより、読めないと言うほうがましです。

    【控えを先に見る ── `pending_...` が残る件】
    ここは以前、控えを見る**前に** `looks_like_sqlite()` を呼んでいました。
    あれは中身を確かめるために**共有のファイルを実際に開きます。** つまり
    写しが新しくても、読むたびに共有のファイルを開いていました ──
    GWでロットを1本引くだけで3〜4回です。

    上流は `SIKALOT.pending_20260914_091528.sqlite3` に書いてから
    `SIKALOT.sqlite3` へ置き換えます(rename)。**Windowsでは、誰かが開いて
    いるファイルは置き換えられません。** こちらの開閉とぶつかると置き換えが
    失敗し、`pending_...` が取り残されます。

    いまは**控えが効いているかを先に見ます。** 大きさと更新時刻だけ
    (`stat`。開きません)で足りるので、ふつうの読みでは共有のファイルを
    1度も開きません。開くのは、本当に写し直すときだけです。
    """
    path = Path(path)

    # 絶対の道にするだけ。**共有には問い合わせない** ── `resolve()` は
    # 実体を開いて確かめに行くので、共有の上では往復が増える
    resolved = Path(os.path.abspath(path))
    key = str(resolved)
    try:
        stat = resolved.stat()
    except FileNotFoundError:
        raise SourceError(f"ファイルが見つかりません: {path}") from None
    except OSError as exc:
        raise SourceError(f"{path.name} を確かめられません: {exc}") from exc
    stamp = (stat.st_size, stat.st_mtime_ns)

    # **ここを先に。** 効いていれば、共有のファイルは1度も開かない
    known = _COPIES.get(key)
    if known is not None and known[0] == stamp and known[1].exists():
        return known[1]

    # 【写し直しは1つずつ・写しは置き換えで入れる】(v3.96.0)
    # 画面は同じマスタを**同時に**何本も引く(VC長さ計算を開くと、計算と
    # 設定の2本)。前は写しを**その場で上書き**していたので、ほかの要求が
    # 開いて読んでいる最中の写しが一度空になり、「no such table」で落ちて
    # いた。いまは別の名前へ写して確かめてから置き換える ── 読んでいる
    # 側は、読み終わるまで前の写しを持ったまま
    with _refresh_lock(key):
        known = _COPIES.get(key)                 # 待っているあいだに写し終わった
        if known is not None and known[0] == stamp and known[1].exists():
            return known[1]
        if not looks_like_sqlite(path):
            # 中身が別物なら写しても開けない。**共有を無駄に往復させない**
            raise SourceError(f"sqlite3 のファイルではありません: {path.name}")
        target = copy_dir() / _copy_name(resolved)
        part = target.with_name(f".{target.name}.{os.getpid()}.part")
        try:
            last = ""
            for attempt in range(1, COPY_RETRY + 1):
                try:
                    _do_copy(resolved, part)
                except OSError as exc:
                    raise SourceError(f"{path.name} を手元に写せません: {exc}") from exc
                if _is_intact(part):
                    if attempt > 1:
                        log.info("%s は %s回目の写しで揃いました", path.name, attempt)
                    _swap_in(part, target, path.name)
                    _COPIES[key] = (stamp, target)
                    return target
                last = "写しが途中で切れています"
                log.warning("%s の写しが揃っていません(%s回目)。写し直します",
                            path.name, attempt)
                time.sleep(COPY_RETRY_WAIT_SEC)
        finally:
            _discard(part)

    raise SourceError(
        f"{path.name} を読める形で写せませんでした({last})。"
        "書き込みが終わってからもう一度お試しください。")


# 写し直しの鍵(元のファイルごと)。**別のマスタの写し直しは待たせない**
_REFRESH_LOCKS: Dict[str, threading.Lock] = {}
_REFRESH_GUARD = threading.Lock()

# 写しを置き換えるとき、ほかの要求がまだ前の写しを開いていれば待つ回数と間隔。
# **Windows は開いているファイルを置き換えられない。** 読みは数ミリ秒で終わる
SWAP_RETRY = 30
SWAP_RETRY_WAIT_SEC = 0.1


def _refresh_lock(key: str) -> threading.Lock:
    with _REFRESH_GUARD:
        return _REFRESH_LOCKS.setdefault(key, threading.Lock())


def _swap_in(part: Path, target: Path, name: str) -> None:
    """確かめ終えた写し(`part`)を `target` に置き換える。

    付き添いが残っていれば**先に**置く(`_do_copy` と同じ順)。前の写しの
    付き添いは消す ── 新しい本体に古い `-wal` が付くのが一番たちが悪い。
    """
    for attempt in range(1, SWAP_RETRY + 1):
        try:
            for extra in SIDECARS:
                side = Path(str(part) + extra)
                beside = Path(str(target) + extra)
                if side.exists():
                    os.replace(side, beside)
                else:
                    beside.unlink(missing_ok=True)
            os.replace(part, target)
            return
        except PermissionError:                  # Windows: まだ前の写しを読んでいる
            if attempt == SWAP_RETRY:
                break
            time.sleep(SWAP_RETRY_WAIT_SEC)
        except OSError as exc:
            raise SourceError(f"{name} の写しを置き換えられません: {exc}") from exc
    raise SourceError(f"{name} の写しを置き換えられません(ほかの読み込みが使っています)。"
                      "少し待ってからもう一度お試しください。")


def _discard(part: Path) -> None:
    """置き換えなかった(途中で断った)写しを片づける。"""
    for extra in ("", *SIDECARS):
        try:
            Path(str(part) + extra).unlink(missing_ok=True)
        except OSError:
            pass


def forget(path: Optional[Path] = None) -> None:
    """写しの控えを捨てる。次に読むとき写し直す。

    元のファイルが更新されたことを、大きさも更新時刻も変えずに
    知らせてくる場面はまず無いので、ふだんは要りません。設定で置き場所を
    変えたときと、テストのために使います。
    """
    if path is None:
        _COPIES.clear()
        return
    _COPIES.pop(str(Path(os.path.abspath(path))), None)



@contextmanager
def open_source(path: Path):
    """写しを開く。**共有のファイルは開かない。**

    読み取り専用(`query_only`)で開きます。写しを書き換えても誰にも
    届かないので、書けてしまうこと自体が間違いのもとです。
    """
    copy = local_copy(path)
    conn = sqlite3.connect(str(copy), timeout=BUSY_TIMEOUT_MS / 1000)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = 1")
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        yield conn
    except sqlite3.Error as exc:
        raise SourceError(f"{Path(path).name} を読めません: {exc}") from exc
    finally:
        conn.close()


