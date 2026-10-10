"""配布用フォルダ(`scripts/make_dist.py`)

- 直下のものは、配る(INCLUDE)か配らない(DEV_ONLY)かのどちらかに必ず入っている
- できたフォルダに、配るものがそろい、配ってはいけないものが無い
- 起動ファイルは CP932 + CRLF(git の取り出しで LF になっていても直して配る)
- 塊の中に半角の ) がある .bat は配らない(start.bat が動かなかった件)
- exe・VC計算マスタの置き場所が入る
- できたフォルダだけで起動できる(start_app.py --check・bridge.py)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests._helpers import ROOT, child_env, temp_local_dir

sys.path.insert(0, str(ROOT / "scripts"))
import make_dist  # noqa: E402

#: 直下にあってよい、作業中にだけできるもの(git が追跡しない)
LOCAL_ONLY = {".pytest_cache", ".coverage", "htmlcov"}


def tracked_top_level() -> set:
    out = subprocess.run(["git", "-c", "core.quotepath=off", "ls-files", "-z"], cwd=str(ROOT),
                         capture_output=True, text=True, encoding="utf-8").stdout
    names = {line.split("/", 1)[0] for line in out.split("\0") if line.strip()}
    # git を使えない環境(配ったフォルダなど)では、直下を見る
    return names or {p.name for p in ROOT.iterdir() if p.name not in LOCAL_ONLY}


class ClassificationTest(unittest.TestCase):
    def test_every_top_level_entry_is_classified(self):
        unknown = sorted(n for n in tracked_top_level()
                         if n not in make_dist.INCLUDE and n not in make_dist.DEV_ONLY)
        self.assertEqual(unknown, [], "直下に足したものは INCLUDE か DEV_ONLY に入れる")
        both = set(make_dist.INCLUDE) & set(make_dist.DEV_ONLY)
        self.assertEqual(both, set())

    def test_bat_wrapper_is_ascii_crlf(self):
        data = (ROOT / "scripts" / "make_dist.bat").read_bytes()
        data.decode("ascii")
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"))
        self.assertIn(b"python scripts\\make_dist.py %*", data)


class BuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix="coil_dist_test_"))
        fake_exe = cls.base / "CoilCalculator.exe"
        fake_exe.write_bytes(b"MZ fake")
        cls.out, cls.lines = make_dist.build(cls.base / "dist", exe=fake_exe,
                                             vc_master_dir="\\\\srv\\share\\参照用マスタ",
                                             admin_password="genba-2026")

    def test_contents(self):
        for name in make_dist.INCLUDE:
            self.assertTrue((self.out / name).exists(), name)
        for name in make_dist.FORBIDDEN:
            self.assertFalse((self.out / name).exists(), name)
        self.assertEqual([p for p in self.out.rglob("__pycache__")], [])
        self.assertTrue((self.out / make_dist.EXE_NAME).is_file())
        memo = (self.out / "配布メモ.txt").read_bytes()
        self.assertTrue(memo.startswith(b"\xef\xbb\xbf"), "メモ帳で開ける UTF-8(BOM つき)")
        self.assertIn("CoilCalculator.exe", memo.decode("utf-8-sig"))

    def test_launch_files_are_cp932_crlf(self):
        for name in make_dist.LAUNCH_FILES:
            data = (self.out / name).read_bytes()
            data.decode("cp932")
            self.assertEqual(data.count(b"\n"), data.count(b"\r\n"), name)

    def test_master_dir_goes_into_config(self):
        conf = json.loads((self.out / "config" / "app.json").read_text(encoding="utf-8"))
        self.assertEqual(conf["vc"]["master_dir"], "\\\\srv\\share\\参照用マスタ")
        original = json.loads((ROOT / "config" / "app.json").read_text(encoding="utf-8"))
        self.assertEqual(conf["version"], original["version"])

    def test_admin_password_is_stored_hashed(self):
        text = (self.out / "config" / "app.json").read_text(encoding="utf-8")
        self.assertNotIn("genba-2026", text, "平文で残さない")
        stored = json.loads(text)["admin"]["password_hash"]
        self.assertTrue(stored.startswith("pbkdf2$"))
        from coilcalc import admin_password
        self.assertTrue(admin_password._matches("genba-2026", stored))
        self.assertFalse(admin_password._matches("nisk", stored))
        memo = (self.out / "配布メモ.txt").read_text(encoding="utf-8-sig")
        self.assertNotIn("genba-2026", memo)
        self.assertIn("管理者パスワード: 配布で決めた値", memo)

    def test_vc_screen_and_manual_are_included(self):
        for rel in ("app/static/index.html", "app/static/vc/vc.js", "app/static/vc/vc.css",
                    "app/static/coil/index.html", "app/static/manual/vc.html", "coilcalc/vc_api.py",
                    "coilcalc/vc/schema.sql", "coilcalc/vc/tables.py"):
            self.assertTrue((self.out / rel).is_file(), rel)

    def test_dist_folder_starts_on_its_own(self):
        env = child_env(temp_local_dir())
        done = subprocess.run([sys.executable, str(self.out / "start_app.py"), "--check"],
                              cwd=str(self.out), env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        proc = subprocess.Popen([sys.executable, "-X", "utf8", str(self.out / "bridge.py")],
                                cwd=str(self.out), env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            head = json.loads(proc.stdout.readline())
            self.assertEqual(head["event"], "started")
        finally:
            proc.stdin.close()
            proc.wait(10)
            proc.stdout.close()


class ShortcutScriptTest(unittest.TestCase):
    """配った先で押す `scripts\\make_shortcuts.vbs`(Start.vbs と exe のショートカットを、押したときの場所で作る)。
    作りは python-web-tools(梱包資材総合ツール)の同じ名前のファイルと同じ。"""

    PATH = ROOT / "scripts" / "make_shortcuts.vbs"
    NAME = "VC長さ・コイル平板 計算ツール"

    def text(self) -> str:
        return self.PATH.read_bytes().decode("cp932")

    def names(self) -> dict:
        """`NAME = U("0056 …")` を文字にもどす(.vbs の中では文字の番号で持つ)。"""
        import re
        out = {}
        for name, codes in re.findall(r'^(\w+) = U\("([0-9A-F ]+)"\)', self.text(), re.M):
            out[name] = "".join(chr(int(c, 16)) for c in codes.split())
        return out

    def test_cp932_crlf_no_bom(self):
        data = self.PATH.read_bytes()
        self.assertNotEqual(data[:3], b"\xef\xbb\xbf")
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"), "改行は CRLF だけ")
        with self.assertRaises(UnicodeDecodeError, msg="UTF-8 で保存し直されていない"):
            data.decode("utf-8")
        self.assertIn(self.NAME, self.text())

    def test_names_are_built_from_code_points(self):
        """英語の Windows でも名前が化けないように(python-web-tools の CI で実際に化けた)。"""
        self.assertEqual(self.names(), {"APP_NAME": self.NAME, "BROWSER": "(ブラウザ版)",
                                        "DESKTOP": "(デスクトップ版)"})
        self.assertEqual(self.NAME, json.loads((ROOT / "config" / "app.json").read_text(
            encoding="utf-8"))["display_name"], "ショートカットの名前はツールの表示名")
        self.assertIn(f'EXE_NAME = "{make_dist.EXE_NAME}"', self.text())
        for line in self.text().splitlines():
            code = line.split("'", 1)[0]
            quoted = code.split('"')[1::2]
            self.assertFalse(any(".lnk" in q and not q.isascii() for q in quoted), line)

    def test_points_at_start_vbs_and_exe_from_where_it_is_run(self):
        text = self.text()
        self.assertIn('MakeLink APP_NAME & BROWSER & ".lnk", "Start.vbs", False', text)
        self.assertIn('MakeLink APP_NAME & DESKTOP & ".lnk", EXE_NAME, True', text)
        self.assertIn("fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))", text)
        self.assertIn('lnk.IconLocation = target & ",0"', text, "デスクトップ版は exe のアイコン")
        self.assertNotIn("msgbox", text.lower(), "結果は WScript.Echo(cscript では文字で出て止まらない)")

    def test_only_this_script_goes_into_the_dist_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = make_dist.build(Path(tmp) / "dist")
            self.assertEqual(sorted(p.name for p in (out / "scripts").iterdir()), ["make_shortcuts.vbs"])
            self.assertEqual((out / "scripts" / "make_shortcuts.vbs").read_bytes(), self.PATH.read_bytes())
            memo = (out / "配布メモ.txt").read_text(encoding="utf-8-sig")
            self.assertIn("scripts\\make_shortcuts.vbs", memo)

    @unittest.skipUnless(sys.platform == "win32", "Windows の cscript で本当に作る")
    def test_windows_makes_the_shortcuts(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            tool = Path(tmp) / "VC長さ・コイル平板 計算ツール_VER9"
            (tool / "scripts").mkdir(parents=True)
            shutil.copy2(self.PATH, tool / "scripts" / "make_shortcuts.vbs")
            (tool / "Start.vbs").write_bytes(b"' x\r\n")

            def run():
                return subprocess.run(["cscript", "//nologo", str(tool / "scripts" / "make_shortcuts.vbs")],
                                      capture_output=True, timeout=60)
            browser = tool / f"{self.NAME}(ブラウザ版).lnk"
            desktop = tool / f"{self.NAME}(デスクトップ版).lnk"
            # exe が無いフォルダ: デスクトップ版は作らず、そのことを知らせる
            done = run()
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertTrue(browser.exists())
            self.assertFalse(desktop.exists())
            self.assertIn(b"CoilCalculator.exe", done.stdout)
            # exe を置いて押し直す: 2つになる(何度押しても作り直すだけ)
            (tool / make_dist.EXE_NAME).write_bytes(b"MZ")
            for _ in range(2):
                done = run()
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertTrue(browser.exists())
            self.assertTrue(desktop.exists())
            # 指す先は押したときのフォルダ
            ps = subprocess.run(["powershell", "-NoProfile", "-Command",
                                 "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
                                 "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $s.TargetPath"],
                                env=dict(os.environ, LNK=str(desktop)), capture_output=True, timeout=60)
            self.assertEqual(ps.stdout.decode("utf-8", "replace").strip(), str(tool / make_dist.EXE_NAME))


class GuardTest(unittest.TestCase):
    def test_lf_launch_file_is_fixed_to_crlf(self):
        tmp = Path(tempfile.mkdtemp())
        src = tmp / "start.bat"
        src.write_bytes("@echo off\nchcp 932 >nul\necho テスト\n".encode("cp932"))
        make_dist.write_launch_file(src, tmp / "out.bat")
        data = (tmp / "out.bat").read_bytes()
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"))

    def test_bat_with_bare_close_paren_is_refused(self):
        tmp = Path(tempfile.mkdtemp())
        src = tmp / "start.bat"
        src.write_bytes("@echo off\r\nif errorlevel 1 (\r\n    echo 追加(pip install)は要りません\r\n)\r\n"
                        .encode("cp932"))
        with self.assertRaises(SystemExit):
            make_dist.write_launch_file(src, tmp / "out.bat")
        self.assertEqual(make_dist.bare_close_paren("if x (\r\n echo ok ^) fine\r\n)\r\n"), [])

    def test_utf8_launch_file_is_refused(self):
        tmp = Path(tempfile.mkdtemp())
        src = tmp / "Start.vbs"
        src.write_bytes("' これは UTF-8 で保存し直されたもの\r\n".encode("utf-8"))
        with self.assertRaises(SystemExit):
            make_dist.write_launch_file(src, tmp / "out.vbs")

    def test_refuses_inside_tool_folder_and_non_empty(self):
        with self.assertRaises(SystemExit):
            make_dist.build(ROOT / "配布テスト")
        busy = Path(tempfile.mkdtemp())
        (busy / "x.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(SystemExit):
            make_dist.build(busy)


if __name__ == "__main__":
    unittest.main()
