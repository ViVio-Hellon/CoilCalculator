"""この端末の設定(%LOCALAPPDATA%\\CoilCalculator\\settings.json)

端末ごとに変えられる値だけを持ちます。いまは2つ:

    vc_master_dir   VC計算マスタの置き場所(フォルダ)。設定 → マスタの置き場所 で変える
    admin_password  管理者パスワード(撹拌済み。`admin_password.py`)

**無い・壊れていても起動は止めません。** 読めなければ既定(config/app.json)で動き、
壊れたファイルは `settings.broken-<日時>.json` に退けて残します(何が入っていたか
後から見られるように)。書くときは隣に書いてから置き換えるので、書いている最中に
落ちても半端なファイルは残りません。
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from . import app_config
from .logging_setup import get_logger

log = get_logger("coilcalc.settings_store")

FILE_NAME = "settings.json"
KEY_VC_MASTER_DIR = "vc_master_dir"
KEY_ADMIN_PASSWORD = "admin_password"

_lock = threading.Lock()


def path() -> Path:
    return app_config.local_root() / FILE_NAME


def load_all() -> Dict[str, Any]:
    target = path()
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        log.warning("端末の設定を読めません(既定で動きます): %s", exc)
        return {}
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("中身が {} の形ではありません")
        return data
    except ValueError as exc:
        _set_aside(target, exc)
        return {}


def _set_aside(target: Path, why: Exception) -> None:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    aside = target.with_name(f"settings.broken-{stamp}.json")
    try:
        os.replace(str(target), str(aside))
        log.warning("端末の設定が壊れていたので退けました(既定で動きます): %s → %s (%s)",
                    target, aside.name, why)
    except OSError as exc:
        log.warning("端末の設定が壊れていて、退けることもできません(既定で動きます): %s (%s)", why, exc)


def get(key: str, default: Optional[Any] = None) -> Any:
    return load_all().get(key, default)


def save(key: str, value: Any) -> None:
    """1つの値を書く。空文字なら消す(既定に戻る)。"""
    with _lock:
        data = load_all()
        if value in ("", None):
            data.pop(key, None)
        else:
            data[key] = value
        target = path()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{FILE_NAME}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(str(tmp), str(target))
