"""読み終えたファイルを掴んだままにしない(動いている間に差し替えられる)

Windows では、ほかのプロセスが開いたままのファイルは差し替え(上書き・名前の付け替え)が
できません。アプリのフォルダを共有フォルダに置いて配る運用では、動いている誰かが
ファイルを掴んだままだと、**新しい版や設定を置けなくなります**。

このツールが読むアプリのフォルダのファイルは、設定(config/app.json)・画面のファイル
(HTML・JS・CSS・説明書の写真)・Python のファイルだけです(共有のマスタ・DB は持ちません)。
ここでは、アプリのフォルダの**写し**からブラウザ版とデスクトップ版の Python(bridge.py)を
起動して使い、動いたまま、そのファイルを差し替えられることを確かめます。
Windows の CI で流すのが本番の確かめです(Linux ではもともと差し替えられるので、
代わりに開いたままの記述子が無いことを /proc で見ます)。

デスクトップ版の外枠(Rust)が返す画面のファイルは scripts/desktop_smoke.py が同じように確かめます。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

from tests._helpers import ROOT, child_env, free_port, temp_local_dir

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

#: 差し替えを試すファイル(アプリのフォルダからの相対)
SWAP = [
    "config/app.json",
    "app/static/index.html",
    "app/static/coil/app-shell.js",
    "app/static/coil/aluminum-coil-calculator.css",
    "app/static/vendor/three/three.min.js",
    "app/static/manual/coil.html",
    "app/static/manual/img/coil-overview.jpg",
    "coilcalc/calc.py",
    "coilcalc/web.py",
    "start_app.py",
    "bridge.py",
]
COIL = {"thickness": "400", "inner-diameter": "557", "coil-width": "1250",
        "specific-gravity": "2.70", "plate-thickness": "1.00"}


def copy_app() -> Path:
    """アプリのフォルダの写し(差し替えで本物を汚さない)。"""
    dest = Path(tempfile.mkdtemp(prefix="coil_app_copy_"))
    for name in ("coilcalc", "app", "config"):
        shutil.copytree(ROOT / name, dest / name, ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("start_app.py", "bridge.py", "process_manager.py"):
        shutil.copy2(ROOT / name, dest / name)
    return dest


def swap_all(app: Path) -> list:
    """同じ中身の新しいファイルで差し替える。差し替えられなかったものを返す。"""
    failed = []
    for rel in SWAP:
        target = app / rel
        fresh = target.with_name(target.name + ".new")
        shutil.copy2(target, fresh)
        try:
            os.replace(str(fresh), str(target))
        except OSError as exc:
            failed.append(f"{rel}: {exc}")
            fresh.unlink()
    return failed


def open_files_under(pid: int, folder: Path) -> list:
    """Linux: そのプロセスが開いたままのファイルのうち、folder の下にあるもの。"""
    found = []
    fd_dir = Path(f"/proc/{pid}/fd")
    for fd in fd_dir.iterdir():
        try:
            target = os.readlink(fd)
        except OSError:
            continue
        if target.startswith(str(folder)):
            found.append(target)
    return found


class BrowserServerHoldsNothingTest(unittest.TestCase):
    def test_files_can_be_replaced_while_running(self):
        app = copy_app()
        local = temp_local_dir()
        port = free_port()
        server = subprocess.Popen([sys.executable, str(app / "start_app.py"), "--no-browser", "--port", str(port)],
                                  env=child_env(local), cwd=str(app),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: server.poll() is None and server.kill())
        base = f"http://127.0.0.1:{port}"

        def get(path):
            with OPENER.open(base + path, timeout=5) as res:
                return res.read()

        deadline = time.monotonic() + 20
        while True:
            try:
                get("/api/health")
                break
            except OSError:
                if time.monotonic() > deadline:
                    self.fail("ブラウザ版が起動しませんでした")
                time.sleep(0.2)
        # ひととおり使う(画面・JS・CSS・ライブラリ・説明書・写真・計算)
        for path in ("/", "/coil/app-shell.js", "/coil/aluminum-coil-calculator.css",
                     "/vendor/three/three.min.js", "/manual/coil.html", "/manual/img/coil-overview.jpg"):
            self.assertTrue(get(path))
        req = urllib.request.Request(base + "/api/coil/calc", method="POST",
                                     data=json.dumps({"fields": COIL}).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with OPENER.open(req, timeout=5) as res:
            self.assertEqual(json.loads(res.read())["results"]["windings"], "400 巻")

        if sys.platform.startswith("linux"):
            self.assertEqual(open_files_under(server.pid, app), [], "アプリのフォルダのファイルを開いたまま")
        self.assertEqual(swap_all(app), [], "動いている間に差し替えられない(掴んだまま)")
        self.assertTrue(get("/"), "差し替えたあとも動く")

        stop = urllib.request.Request(base + "/api/shutdown", method="POST", data=b'{"confirmed": true}',
                                      headers={"Content-Type": "application/json"})
        with OPENER.open(stop, timeout=5):
            pass
        self.assertEqual(server.wait(15), 0)


class BridgeHoldsNothingTest(unittest.TestCase):
    """デスクトップ版の Python(bridge.py)も同じ。"""

    def test_files_can_be_replaced_while_running(self):
        app = copy_app()
        proc = subprocess.Popen([sys.executable, "-X", "utf8", str(app / "bridge.py")],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                env=child_env(temp_local_dir()), cwd=str(app))
        self.addCleanup(lambda: proc.poll() is None and proc.kill())

        def read():
            head = json.loads(proc.stdout.readline().decode("utf-8"))
            return head, proc.stdout.read(head["len"]) if head.get("len") else b""

        self.assertEqual(read()[0]["event"], "started")
        for i, (method, path, body) in enumerate([("GET", "/api/health", b""),
                                                  ("POST", "/api/coil/calc", json.dumps({"fields": COIL}).encode()),
                                                  ("GET", "/api/spec", b"")]):
            head = {"id": i + 1, "method": method, "path": path, "query": "",
                    "headers": [["Content-Type", "application/json"]], "len": len(body)}
            proc.stdin.write(json.dumps(head).encode("utf-8") + b"\n" + body)
            proc.stdin.flush()
            self.assertEqual(read()[0]["status"], 200)

        if sys.platform.startswith("linux"):
            self.assertEqual(open_files_under(proc.pid, app), [], "アプリのフォルダのファイルを開いたまま")
        self.assertEqual(swap_all(app), [], "動いている間に差し替えられない(掴んだまま)")
        proc.stdin.close()
        self.assertEqual(proc.wait(10), 0)
        proc.stdout.close()


if __name__ == "__main__":
    unittest.main()
