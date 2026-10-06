"""ブラウザ版(`start_app.py`)── 起動・2つ目・デスクトップ版との排他・止め方・自動終了"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import unittest
import urllib.request

from tests._helpers import ROOT, child_env, free_port, temp_local_dir
from tests.test_instance_lock import hold_in_child
from coilcalc import instance_lock, web
import start_app

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def wait_for(predicate, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


class BrowserVersionTest(unittest.TestCase):
    def setUp(self):
        self.local = temp_local_dir()
        self.env = child_env(self.local)
        self.port = free_port()

    def start(self):
        return subprocess.Popen([sys.executable, str(ROOT / "start_app.py"), "--no-browser",
                                 "--port", str(self.port)], env=self.env, cwd=str(ROOT),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding="utf-8")

    def run_cmd(self, *args):
        return subprocess.run([sys.executable, *args], env=self.env, cwd=str(ROOT),
                              capture_output=True, text=True, encoding="utf-8", timeout=60)

    def get(self, path):
        with OPENER.open(f"http://127.0.0.1:{self.port}{path}", timeout=5) as res:
            return res.status, res.read()

    def test_serves_reuses_and_stops(self):
        server = self.start()
        self.addCleanup(lambda: server.poll() is None and server.kill())
        runtime = self.local / "runtime"
        self.assertTrue(wait_for(lambda: (instance_lock.read_owner(runtime, wait=0) or {}).get("url")))
        status, body = self.get("/api/health")
        self.assertEqual(json.loads(body)["mode"], "browser")
        status, page = self.get("/")
        self.assertIn("コイル・平板 重量計算ツール".encode("utf-8"), page)

        # 2つ目のブラウザ版: 新しく起動せず、動いている画面を案内して終わる
        second = self.run_cmd(str(ROOT / "start_app.py"), "--no-browser", "--port", str(free_port()))
        self.assertEqual(second.returncode, start_app.EXIT_OK)
        self.assertIn(f"127.0.0.1:{self.port}", second.stderr)

        stopped = self.run_cmd(str(ROOT / "process_manager.py"))
        self.assertEqual(stopped.returncode, 0, stopped.stdout)
        self.assertEqual(server.wait(15), 0)
        server.stdout.close()
        server.stderr.close()
        self.assertIsNone(instance_lock.read_owner(runtime, wait=0), "終わったら持ち主の印を消す")
        self.assertIn("動いていません", self.run_cmd(str(ROOT / "process_manager.py")).stdout)

    def test_refuses_while_desktop_is_open(self):
        desktop = hold_in_child(self.local / "runtime", instance_lock.KIND_DESKTOP)
        try:
            done = self.run_cmd(str(ROOT / "start_app.py"), "--no-browser", "--port", str(self.port))
            self.assertEqual(done.returncode, start_app.EXIT_OTHER_RUNNING)
            self.assertIn("デスクトップ版", done.stderr)
            self.assertIn("同時に使えません", done.stderr)
            status = self.run_cmd(str(ROOT / "process_manager.py"))
            self.assertEqual(status.returncode, 1, "デスクトップ版は窓の × で閉じる(--force 以外では止めない)")
            self.assertIn("窓の ×", status.stdout)
        finally:
            desktop.stdin.close()
            desktop.wait(10)
            desktop.stdout.close()

    def test_check_only(self):
        done = self.run_cmd(str(ROOT / "start_app.py"), "--check")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("OK", done.stderr)


class IdleExitTest(unittest.TestCase):
    """タブを全部閉じたら、しばらくして自分で終わる(残るとデスクトップ版が開けない)。"""

    def test_waits_for_first_page_then_ends_when_idle(self):
        app = web.App(web.MODE_BROWSER)
        stopped = threading.Event()
        browser = {"idle_exit_seconds": 0.4, "first_open_grace_seconds": 30}
        t = threading.Thread(target=start_app.watch_idle, args=(app, stopped, browser))
        t.start()
        time.sleep(1.5)
        self.assertTrue(t.is_alive(), "画面が来るまでは長めに待つ")
        app.touch()                               # 画面が来た(計算・知らせ)
        t.join(5)
        self.assertFalse(t.is_alive(), "知らせが途絶えたら終わる")

    def test_shutdown_request_ends_immediately(self):
        app = web.App(web.MODE_BROWSER)
        stopped = threading.Event()
        t = threading.Thread(target=start_app.watch_idle,
                             args=(app, stopped, {"idle_exit_seconds": 999, "first_open_grace_seconds": 999}))
        t.start()
        stopped.set()
        t.join(5)
        self.assertFalse(t.is_alive())


if __name__ == "__main__":
    unittest.main()
