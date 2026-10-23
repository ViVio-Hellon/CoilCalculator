"""動作ログの置き場所と名前(`coilcalc/logging_setup.py`・`app_config.log_dir`)

いろいろなツールのログを1か所に集めたり、ファイルだけ取り出したりしても、**開かずに**
何のツール・どの端末のものか分かるように、ファイル名にもフォルダ名にもツールの名前を入れる。

    <作業フォルダ>\\logs\\CoilCalculator\\CoilCalculator_<端末名>.log
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest
from unittest import mock

from tests._helpers import ROOT, child_env, free_port, temp_local_dir
from coilcalc import app_config


class LogPlaceTest(unittest.TestCase):
    def test_folder_and_file_carry_the_tool_name(self):
        local = temp_local_dir()
        with mock.patch.dict(os.environ, {"COIL_TOOL_LOCAL_DIR": str(local), "COMPUTERNAME": "NLM-NGY-240638"}):
            self.assertEqual(app_config.log_dir(), local / "logs" / "CoilCalculator")
            self.assertEqual(app_config.log_file_name(), "CoilCalculator_NLM-NGY-240638.log")

    def test_terminal_name_is_safe_for_a_file_name(self):
        for raw, want in (("PC 01", "PC_01"), ("現場/PC\\1", "PC_1"), ("", None)):
            with self.subTest(raw=raw), mock.patch.dict(os.environ, {"COMPUTERNAME": raw}):
                got = app_config.terminal_name()
                self.assertRegex(got, r"^[0-9A-Za-z._-]+$")
                if want:
                    self.assertEqual(got, want)

    def test_desktop_shell_points_at_the_same_folder(self):
        """理由の画面に出すログの場所(Rust)も同じフォルダ"""
        main_rs = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
        self.assertIn(f'.join("logs").join("{app_config.TOOL_NAME}")', main_rs)

    def test_browser_version_writes_there(self):
        local = temp_local_dir()
        env = child_env(local, COMPUTERNAME="LINE-PC-7")
        port = free_port()
        server = subprocess.Popen([sys.executable, str(ROOT / "start_app.py"), "--no-browser", "--port", str(port)],
                                  env=env, cwd=str(ROOT), stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            path = local / "logs" / "CoilCalculator" / "CoilCalculator_LINE-PC-7.log"
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not (path.exists() and "を始めました" in path.read_text("utf-8")):
                time.sleep(0.1)
            self.assertIn("ブラウザ版", path.read_text(encoding="utf-8"))
            self.assertFalse((local / "logs" / "coilcalc.log").exists(), "前の名前では書かない")
        finally:
            subprocess.run([sys.executable, str(ROOT / "process_manager.py")], env=env, cwd=str(ROOT),
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
            try:
                server.wait(15)
            except subprocess.TimeoutExpired:
                server.kill()


if __name__ == "__main__":
    unittest.main()
