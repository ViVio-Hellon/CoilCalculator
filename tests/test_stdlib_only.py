"""**標準ライブラリだけ**で動く(ラインPCの Python には追加のパッケージを入れられない)

アプリの Python(試験・作業用の scripts は除く)が import しているものが、
すべて標準ライブラリかこのアプリ自身であることを確かめる。
"""
from __future__ import annotations

import ast
import sys
import unittest

from tests._helpers import ROOT

APP_FILES = ["bridge.py", "start_app.py", "process_manager.py", *sorted(
    str(p.relative_to(ROOT)) for p in (ROOT / "coilcalc").glob("*.py"))]
OWN = {"coilcalc", "start_app", "bridge", "process_manager"}
# Python 3.10 より前には sys.stdlib_module_names が無い(そのときは使っているものだけ)
FALLBACK = {"__future__", "argparse", "ast", "ctypes", "dataclasses", "decimal", "fcntl", "http",
            "json", "logging", "math", "mimetypes", "msvcrt", "os", "pathlib", "platform", "re", "signal",
            "socket", "socketserver", "subprocess", "sys", "threading", "time", "typing", "urllib",
            "webbrowser", "concurrent"}


class StdlibOnlyTest(unittest.TestCase):
    def test_imports(self):
        stdlib = set(getattr(sys, "stdlib_module_names", FALLBACK)) | {"__future__"}
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
                        self.assertTrue(top in stdlib or top in OWN, f"{rel}: {name}")

    def test_no_requirements_file(self):
        self.assertFalse((ROOT / "requirements.txt").exists(),
                         "pip install が要らないことを、ファイルが無いことでも示す")


if __name__ == "__main__":
    unittest.main()
