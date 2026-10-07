"""VC計算マスタの置き場所

    フォルダ   1. この端末の設定(設定 → マスタの置き場所。settings.json の vc_master_dir)
               2. 配布の既定(config/app.json の vc.master_dir。scripts/make_dist.py --vc-master-dir)
               3. どちらも空なら、この端末の作業フォルダ(%LOCALAPPDATA%\\CoilCalculator\\master)
    ファイル   そのフォルダで **VC計算マスタ → vc_master** の順に探す(`.sqlite3` → `.db`)。
               vc-calculator(単独のツール)が作った `vc_master.sqlite3` があればそれを読む
               ── 表の形は同じなので、日報管理ツール・vc-calculator と1つのマスタを共有できる。
               どちらも無ければ `VC計算マスタ.sqlite3`(初めて使うとき VBA の初期値で作る)

日報管理ツールの `config.SETTINGS.vc_master_path` / `_pick_source` / `OLDER_NAMES` と同じ決め方。
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from .. import app_config, settings_store

MASTER_FILENAME = "VC計算マスタ.sqlite3"
#: 旧名。新しい名前が無ければこちらを読む
OLDER_NAMES = {"VC計算マスタ": ("vc_master",)}
SUFFIXES = (".sqlite3", ".db")


def configured_dir() -> Tuple[str, str]:
    """(設定されているフォルダの文字, どこで決まったか: terminal / site / default)。"""
    stored = str(settings_store.get(settings_store.KEY_VC_MASTER_DIR) or "").strip()
    if stored:
        return stored, "terminal"
    site = str((app_config.load().get("vc") or {}).get("master_dir") or "").strip()
    if site:
        return site, "site"
    return "", "default"


def default_dir() -> Path:
    return app_config.local_root() / "master"


def master_dir() -> Path:
    text, _origin = configured_dir()
    return Path(text) if text else default_dir()


def pick(directory: Path, filename: str = MASTER_FILENAME) -> Path:
    """そのフォルダで実際に使うファイル。**見つからなくても、その道を返す**(作る側が使う)。"""
    stem = Path(filename).stem
    for name in (stem, *OLDER_NAMES.get(stem, ())):
        for suffix in SUFFIXES:
            candidate = directory / f"{name}{suffix}"
            try:
                if candidate.exists():
                    return candidate
            except OSError:                           # 共有に届かない
                return directory / filename
    return directory / filename


def master_path() -> Path:
    return pick(master_dir())


def candidates() -> List[Path]:
    """探す名前を優先の順に(画面で関係を見せるため)。"""
    folder = master_dir()
    stem = Path(MASTER_FILENAME).stem
    return [folder / f"{name}.sqlite3" for name in (stem, *OLDER_NAMES.get(stem, ()))]


def cache_path() -> Path:
    """最後に読めたマスタの控え(端末の作業フォルダ。共有もアプリのフォルダも汚さない)。"""
    return app_config.local_root() / "cache" / "vc_master_snapshot.json"
