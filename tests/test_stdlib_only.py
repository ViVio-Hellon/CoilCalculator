"""**標準ライブラリだけ**で動く(ラインPCの Python には追加のパッケージを入れられない)

アプリの Python(試験・作業用の scripts は除く)が import しているものが、
すべて標準ライブラリかこのアプリ自身であることを確かめる。
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

from tests._helpers import ROOT

APP_FILES = ["bridge.py", "start_app.py", "process_manager.py", *sorted(
    str(p.relative_to(ROOT)) for p in (ROOT / "coilcalc").glob("*.py"))]
OWN = {"coilcalc", "start_app", "bridge", "process_manager"}


def is_stdlib(top: str) -> bool:
    """標準ライブラリか。3.10 以上は sys.stdlib_module_names、それより前は置き場所で見る
    (手書きの一覧は、使うものが増えるたびに古くなるので持たない)。"""
    names = getattr(sys, "stdlib_module_names", None)
    if names is not None:
        return top in names or top == "__future__"
    import importlib.util
    import sysconfig
    if top in sys.builtin_module_names:
        return True
    try:
        spec = importlib.util.find_spec(top)
    except (ImportError, ValueError):
        spec = None
    if spec is None:
        return top in ("msvcrt", "fcntl")                 # 別の OS にしか無い標準ライブラリ
    origin = spec.origin or ""
    if origin in ("built-in", "frozen"):
        return True
    stdlib = Path(sysconfig.get_paths()["stdlib"]).resolve()
    path = Path(origin).resolve()
    return stdlib in path.parents and "site-packages" not in path.parts


class StdlibOnlyTest(unittest.TestCase):
    def test_imports(self):
        for rel in APP_FILES:
            tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    top = name.split(".")[0]
                    with self.subTest(file=rel, module=name):
                        self.assertTrue(is_stdlib(top) or top in OWN, f"{rel}: {name}")

    def test_no_requirements_file(self):
        self.assertFalse((ROOT / "requirements.txt").exists(),
                         "pip install が要らないことを、ファイルが無いことでも示す")


if __name__ == "__main__":
    unittest.main()
