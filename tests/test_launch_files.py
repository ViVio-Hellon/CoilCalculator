r"""起動ファイル(.bat / .vbs)の作りを固定する

**Linux 上で編集して、Windows で実行する**組み合わせなので、文字コードと改行は
ここで機械的に押さえる。壊れると現場で「ダブルクリックしても何も起きない」になる。

- `.bat` は cmd.exe がコンソールのコードページ(日本語 Windows は 932)で読む
- `.vbs` は WSH がシステム ANSI(932)で読む
- CP932 の2バイト目には `\`(0x5C)などが現れる(`表` = 0x95 0x5C)。コードページが
  ずれると解釈まで変わるので、`.bat` では `chcp 932` を非 ASCII より前に置く
"""
from __future__ import annotations

import unittest

from tests._helpers import ROOT

BATCH_FILES = ("start.bat", "stop.bat")
VBS_FILES = ("Start.vbs",)
MARKER = "コイル・平板 重量計算ツール"


class LaunchFilesTest(unittest.TestCase):
    def read(self, name):
        return (ROOT / name).read_bytes()

    def test_cp932_with_crlf(self):
        for name in BATCH_FILES + VBS_FILES:
            with self.subTest(name=name):
                data = self.read(name)
                text = data.decode("cp932")              # CP932 として読める
                self.assertIn(MARKER, text)
                self.assertNotIn(b"\xef\xbb\xbf", data[:3], "BOM を付けない")
                self.assertEqual(data.count(b"\n"), data.count(b"\r\n"), "改行は CRLF だけ")
                with self.assertRaises(UnicodeDecodeError, msg="UTF-8 で保存し直されていない"):
                    data.decode("utf-8")

    def test_chcp_before_first_non_ascii(self):
        for name in BATCH_FILES:
            with self.subTest(name=name):
                data = self.read(name)
                first = next(i for i, b in enumerate(data) if b >= 0x80)
                self.assertIn(b"chcp 932", data[:first])

    def test_entry_points(self):
        vbs = self.read("Start.vbs").decode("cp932")
        self.assertIn('"start_app.py"', vbs)
        self.assertIn('"pythonw "', vbs)
        start = self.read("start.bat").decode("cp932")
        self.assertIn("python start_app.py --check", start)
        self.assertIn("python start_app.py %*", start)
        self.assertIn("errorlevel 3", start, "もう一方の版が動いているときの案内")
        self.assertIn("python process_manager.py %*", self.read("stop.bat").decode("cp932"))

    def test_gitattributes_keeps_crlf(self):
        attrs = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("*.bat text eol=crlf", attrs)
        self.assertIn("*.vbs text eol=crlf", attrs)


if __name__ == "__main__":
    unittest.main()
