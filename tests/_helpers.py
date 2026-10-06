"""試験の共通部品"""
from __future__ import annotations

import os
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def temp_local_dir() -> Path:
    """本番の作業フォルダ(%LOCALAPPDATA%)を汚さない一時フォルダ。"""
    return Path(tempfile.mkdtemp(prefix="coil_test_"))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def child_env(local: Path, **extra: str) -> dict:
    env = dict(os.environ, COIL_TOOL_LOCAL_DIR=str(local), COIL_TOOL_QUIET="1",
               PYTHONIOENCODING="utf-8")
    env.update(extra)
    return env
