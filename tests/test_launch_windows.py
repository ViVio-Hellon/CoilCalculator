r"""起動ファイル(start.bat / stop.bat / Start.vbs)を **Windows で本当に動かす**

静的な検査(test_launch_files.py)だけでは、cmd.exe・WSH が実際にどう読むかまでは
分からない。v1.2.0 までは start.bat の塊の中の半角 `)` で bat 全体が止まり、
「start.bat で起動しない」になっていた。Windows の CI(GitHub Actions)で流す。

    start.bat --check          確かめだけして 0 で終わる
    start.bat(ブラウザを開かない)→ 起動 → stop.bat で止める → start.bat も 0 で終わる
    Start.vbs(cscript)        → pythonw で起動 → stop.bat で止める
    Start.vbs --no-browser --port N(ランチャーと同じ渡し方)→ 引数が届いて N で待ち受ける
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import unittest
import urllib.request

from tests._helpers import ROOT, child_env, free_port, temp_local_dir

WINDOWS = os.name == "nt"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
#: cmd.exe の文法エラー・コマンドが無いときの決まり文句(英語・日本語)
CMD_ERRORS = ("was unexpected at this time", "は予期されていません",
              "is not recognized", "として認識されていません")


def owner(local):
    try:
        return json.loads((local / "runtime" / "instance.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def wait_for(predicate, timeout=40.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.3)
    return False


@unittest.skipUnless(WINDOWS, "Windows の cmd.exe・WSH で動かす試験")
class LaunchFilesOnWindowsTest(unittest.TestCase):
    def setUp(self):
        self.local = temp_local_dir()
        self.env = child_env(self.local, COIL_TOOL_NO_BROWSER="1")

    def cmd(self, *args, timeout=120):
        # stdin を閉じておく(pause がすぐ抜ける)
        done = subprocess.run(["cmd", "/c", *args], cwd=str(ROOT), env=self.env,
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
        out = (done.stdout + done.stderr).decode("cp932", errors="replace")
        return done.returncode, out

    def assert_no_cmd_error(self, out):
        for marker in CMD_ERRORS:
            self.assertNotIn(marker, out, out[-2000:])

    def stop(self):
        code, out = self.cmd("stop.bat")
        self.assertEqual(code, 0, out[-2000:])
        self.assert_no_cmd_error(out)

    def test_start_bat_check(self):
        code, out = self.cmd("start.bat", "--check")
        self.assert_no_cmd_error(out)
        self.assertEqual(code, 0, out[-2000:])
        self.assertIn("OK", out)

    def test_start_bat_runs_and_stop_bat_stops(self):
        port = str(free_port())
        proc = subprocess.Popen(["cmd", "/c", "start.bat", "--port", port], cwd=str(ROOT), env=self.env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            self.assertTrue(wait_for(lambda: owner(self.local).get("url")), "start.bat で起動しませんでした")
            with OPENER.open(owner(self.local)["url"] + "api/health", timeout=10) as res:
                self.assertEqual(json.loads(res.read())["mode"], "browser")
            self.stop()
            out = proc.communicate(timeout=60)[0].decode("cp932", errors="replace")
            self.assert_no_cmd_error(out)
            self.assertEqual(proc.returncode, 0, out[-2000:])
        finally:
            if proc.poll() is None:
                proc.kill()

    def test_start_vbs_runs(self):
        done = subprocess.run(["cscript", "//nologo", "Start.vbs"], cwd=str(ROOT), env=self.env,
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
        out = (done.stdout + done.stderr).decode("cp932", errors="replace")
        self.assertEqual(done.returncode, 0, out)
        try:
            self.assertTrue(wait_for(lambda: owner(self.local).get("url")), "Start.vbs で起動しませんでした")
        finally:
            self.stop()

    def test_start_vbs_forwards_arguments(self):
        """ランチャーは Start.vbs にも --no-browser を渡す。落とすと画面が2枚開く。"""
        port = str(free_port())
        env = dict(self.env)
        env.pop("COIL_TOOL_NO_BROWSER", None)            # 引数だけでブラウザを開かないこと
        done = subprocess.run(["cscript", "//nologo", "Start.vbs", "--no-browser", "--port", port],
                              cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=120)
        out = (done.stdout + done.stderr).decode("cp932", errors="replace")
        self.assertEqual(done.returncode, 0, out)
        try:
            self.assertTrue(wait_for(lambda: owner(self.local).get("url")), "Start.vbs で起動しませんでした")
            self.assertIn(f":{port}/", owner(self.local)["url"], "--port が届いていません")
        finally:
            self.stop()


if __name__ == "__main__":
    unittest.main()
