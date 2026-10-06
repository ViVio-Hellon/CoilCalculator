"""config/app.json と、この端末の作業フォルダ(ログ・錠)

作業フォルダの決め方は Rust 側(`src-tauri/src/main.rs` の `local_root`)と同じです。
**2つが違う場所を見ると、ブラウザ版とデスクトップ版の排他が効かなくなります**
(`tests/test_instance_lock.py` が両方の決め方を突き合わせます)。

    1. 環境変数 COIL_TOOL_LOCAL_DIR
    2. %LOCALAPPDATA%\\<local_dir_name>
    3. $XDG_DATA_HOME/<local_dir_name>
    4. ~/.local/share/<local_dir_name>
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

APP_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = APP_ROOT / "config" / "app.json"
STATIC_DIR = APP_ROOT / "app" / "static"

_DEFAULTS: Dict[str, Any] = {
    "app_id": "coil-calculator",
    "display_name": "コイル・平板 重量計算ツール",
    "version": "0.0.0",
    "local_dir_name": "CoilCalculator",
    "server": {"host": "127.0.0.1", "port": 8741, "port_retry": 5},
    "browser": {"heartbeat_seconds": 10, "idle_exit_seconds": 90,
                "first_open_grace_seconds": 180},
}


def load() -> Dict[str, Any]:
    """設定を読む。読めない項目は既定値で埋める(設定が壊れていても起動はする)。"""
    conf = json.loads(json.dumps(_DEFAULTS))
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return conf
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(conf.get(key), dict):
            conf[key].update(value)
        else:
            conf[key] = value
    return conf


def local_root(conf: Dict[str, Any] = None) -> Path:
    env = os.environ.get("COIL_TOOL_LOCAL_DIR", "").strip()
    if env:
        return Path(env)
    name = (conf or load()).get("local_dir_name") or "CoilCalculator"
    for var in ("LOCALAPPDATA", "XDG_DATA_HOME"):
        base = os.environ.get(var, "").strip()
        if base:
            return Path(base) / name
    return Path.home() / ".local" / "share" / name


def runtime_dir(conf: Dict[str, Any] = None) -> Path:
    return local_root(conf) / "runtime"


def log_dir(conf: Dict[str, Any] = None) -> Path:
    return local_root(conf) / "logs"
