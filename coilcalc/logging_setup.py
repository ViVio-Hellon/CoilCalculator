"""動作ログ。%LOCALAPPDATA%\\CoilCalculator\\logs\\coilcalc.log(1MB × 5 世代)"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional

FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_configured = False


def setup(log_dir: Path, *, to_stderr: bool = False, level: int = logging.INFO) -> Optional[Path]:
    """ログの行き先を決める。**書けない場所でも起動は止めない**(画面の計算は使える)。"""
    global _configured
    root = logging.getLogger()
    if _configured:
        return None
    _configured = True
    root.setLevel(level)
    path: Optional[Path] = None
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "coilcalc.log"
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=1024 * 1024, backupCount=5, encoding="utf-8")
        handler.setFormatter(logging.Formatter(FORMAT))
        root.addHandler(handler)
    except OSError as exc:
        print(f"ログを書けません: {exc}", file=sys.stderr)
        path = None
    if to_stderr or path is None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter(FORMAT))
        root.addHandler(stream)
    return path


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
