r"""業務ツール統合ランチャー(python-business-tools-launcher)との約束

ランチャーはツールごとに分岐しない。どのツールにも同じことをする:

    起動    起動ファイル(start.bat / Start.vbs / exe)を実行する。start.bat・Start.vbs には --no-browser
    確認    GET /api/health が app_id の一致と ready を返すまで待つ(ポートの無い exe は窓とプロセス)
    停止    起動ファイルの隣の stop.bat → POST /api/shutdown {"force": …} → pid(照合してから)
    登録    起動ファイルの近くの config/app.json から app_id・表示名・版・ポートを読む

このツールの側で守ること(docs/ランチャー連携.md):
    - /api/health の形(app_id・ready・pid・port・app_root)
    - /api/shutdown {"force": false} は確かめ無しで止まる。書き込み中は 409・busy、force なら止まる
    - stop.bat は**どちらの版も**止める。デスクトップ版はポートが無いので、錠の隣の stop.request で頼む
    - Start.vbs は引数を渡す(ランチャーが渡す --no-browser を落とさない)
    - config/app.json に server.port を書かない(exe の行が「ポートで確かめる行」になってしまう)

ランチャーのリポジトリが手元にあれば(LAUNCHER_REPO、無ければこのツールの隣・vivio-hellon の下)、
**ランチャー本体のコード**で起動確認・停止・登録の読み取りまで確かめる(別プロセスで動かす)。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from tests._helpers import ROOT, child_env, free_port, temp_local_dir
from tests.test_instance_lock import hold_in_child
from coilcalc import app_config, instance_lock, stop_request, web
import process_manager

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
APP_ID = "nlm.coil-calculator"


def find_launcher() -> Path:
    for cand in (os.environ.get("LAUNCHER_REPO", ""),
                 str(ROOT.parent / "python-business-tools-launcher"),
                 str(ROOT.parent / "vivio-hellon" / "python-business-tools-launcher")):
        if cand and (Path(cand) / "launcher" / "health.py").is_file():
            return Path(cand)
    return Path()


LAUNCHER = find_launcher()


def wait_for(predicate, timeout=20.0, step=0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


def shutdown(app, body):
    data = json.dumps(body).encode("utf-8")
    res = app.handle(web.Request(method="POST", path="/api/shutdown", body=data,
                                 headers={"host": "127.0.0.1:8741", "content-type": "application/json"}))
    return res.status, json.loads(res.body.decode("utf-8"))


class HealthAndShutdownTest(unittest.TestCase):
    """/api/health と /api/shutdown の形(ランチャーの health.py・process_manager.py が読む)"""

    def setUp(self):
        self.stopped = threading.Event()
        self.app = web.App(web.MODE_BROWSER, on_shutdown=self.stopped.set,
                           allowed_hosts=("127.0.0.1:8741",))
        self.app.port = 8741

    def test_health_carries_what_the_launcher_checks(self):
        res = self.app.handle(web.Request(method="GET", path="/api/health", body=b"",
                                          headers={"host": "127.0.0.1:8741"}))
        body = json.loads(res.body.decode("utf-8"))
        conf = json.loads((ROOT / "config" / "app.json").read_text(encoding="utf-8"))
        self.assertEqual(body["app_id"], APP_ID)
        self.assertEqual(body["app_id"], conf["app_id"], "ランチャーは app.json の app_id で照合する")
        self.assertIs(body["ready"], True)
        self.assertEqual(body["pid"], os.getpid())
        self.assertEqual(body["port"], 8741)
        self.assertEqual(Path(body["app_root"]), ROOT)
        self.assertTrue(body["stage"])
        self.assertEqual(body["version"], conf["version"])

    def test_launcher_stop_needs_no_confirmation(self):
        status, body = shutdown(self.app, {"force": False})
        self.assertEqual((status, body["stopped"]), (200, True))
        self.assertTrue(self.stopped.wait(2))

    def test_busy_while_writing_unless_forced(self):
        with mock.patch.object(web.vc_db, "writing_now", return_value=True):
            status, body = shutdown(self.app, {"force": False})
            self.assertEqual(status, 409)
            self.assertEqual(body["reason"], "busy")
            self.assertEqual(body["running"], ["VC計算マスタへの書き込み"],
                             "ランチャーは running を「実行中の処理」として利用者に見せる")
            self.assertFalse(self.stopped.wait(0.4), "書き込み中は止まらない")
            status, body = shutdown(self.app, {"force": True})
            self.assertEqual((status, body["stopped"]), (200, True))
        self.assertTrue(self.stopped.wait(2))

    def test_screen_quit_still_asks(self):
        status, body = shutdown(self.app, {})
        self.assertEqual(status, 409)
        self.assertIn("confirm", body, "画面の「終了」は今までどおり確かめる")
        self.assertFalse(self.stopped.wait(0.4))


class AppJsonTest(unittest.TestCase):
    def test_no_port_in_app_json_but_default_stays(self):
        raw = json.loads((ROOT / "config" / "app.json").read_text(encoding="utf-8"))
        self.assertNotIn("port", raw.get("server", {}),
                         "書くとランチャーが exe の行にもポートを入れ、90秒待って「起動できません」になる")
        self.assertEqual(app_config.load()["server"]["port"], 8741)

    def test_start_vbs_forwards_arguments(self):
        text = (ROOT / "Start.vbs").read_bytes().decode("cp932")
        # ランチャーはこの文字の有無で「引数が届く」と判断する(tool_registry._vbs_forwards_args)
        self.assertIn("wscript.arguments", text.lower())


class StopRequestTest(unittest.TestCase):
    """stop.request(stop.bat → 動いているツール)"""

    def setUp(self):
        self.place = temp_local_dir()
        patcher = mock.patch.object(stop_request, "POLL_SECONDS", 0.05)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.called = threading.Event()

    def watch(self, pid=1234, writing_now=lambda: False):
        watcher = stop_request.Watcher(self.place, pid, self.called.set, writing_now=writing_now).start()
        self.addCleanup(watcher.close)
        return watcher

    def test_only_own_request_is_heard(self):
        self.watch(pid=1234)
        self.assertTrue(stop_request.write(self.place, 9999))
        self.assertFalse(self.called.wait(0.4), "よその pid 宛ては聞かない")
        self.assertTrue(stop_request.write(self.place, 1234))
        self.assertTrue(self.called.wait(2))
        self.assertFalse((self.place / stop_request.FILE_NAME).exists(), "受けた頼みは消す")

    def test_stale_request_from_before_is_dropped(self):
        stop_request.write(self.place, 4321)                 # 前の起動に宛てたもの
        self.watch(pid=1234)
        self.assertFalse((self.place / stop_request.FILE_NAME).exists())
        self.assertFalse(self.called.wait(0.3))

    def test_waits_for_writing_unless_forced(self):
        writing = threading.Event()
        writing.set()
        self.watch(writing_now=writing.is_set)
        stop_request.write(self.place, 1234)
        self.assertFalse(self.called.wait(0.5), "書いている間は止まらない")
        writing.clear()
        self.assertTrue(self.called.wait(2), "書き終えたら止まる")

        forced = threading.Event()
        place = temp_local_dir()
        watcher = stop_request.Watcher(place, 77, forced.set, writing_now=lambda: True).start()
        self.addCleanup(watcher.close)
        stop_request.write(place, 77, force=True)
        self.assertTrue(forced.wait(2), "force なら書き込みを待たない")


class StopBatForDesktopTest(unittest.TestCase):
    """stop.bat(process_manager.py)でデスクトップ版を止める。

    外枠(Rust)の代わりに、この試験が錠を握る子(= 外枠)と bridge.py を起こす。
    bridge が「quit」を知らせたら外枠の代役を終わらせる(本物の外枠は「quit」で終わる)。
    """

    def setUp(self):
        self.local = temp_local_dir()
        self.env = child_env(self.local)
        self.runtime = self.local / "runtime"

    def start_desktop(self):
        frame = hold_in_child(self.runtime, instance_lock.KIND_DESKTOP)
        bridge = subprocess.Popen([sys.executable, "-X", "utf8", str(ROOT / "bridge.py")],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, env=self.env, cwd=str(ROOT))
        events = []

        def frame_role():
            for line in bridge.stdout:
                head = json.loads(line.decode("utf-8"))
                events.append(head.get("event"))
                if head.get("event") == "quit":
                    frame.stdin.close()               # 外枠が終わる → 錠が空く
                    bridge.stdin.close()
                    return

        reader = threading.Thread(target=frame_role, daemon=True)
        reader.start()

        def cleanup():
            for proc in (bridge, frame):
                if proc.poll() is None:
                    proc.kill()
                proc.wait(10)
            for stream in (bridge.stdin, bridge.stdout, frame.stdin, frame.stdout):
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass
        self.addCleanup(cleanup)
        self.assertTrue(wait_for(lambda: "started" in events, 20), "bridge が起動しません")
        return frame, bridge, events

    def test_stop_bat_stops_desktop_without_asking(self):
        frame, bridge, events = self.start_desktop()
        time.sleep(0.3)                                # 頼みを見張り始めるまで
        done = subprocess.run([sys.executable, str(ROOT / "process_manager.py")], env=self.env,
                              cwd=str(ROOT), stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, encoding="utf-8", timeout=60)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("quit", events)
        self.assertEqual(frame.wait(10), 0)
        self.assertEqual(bridge.wait(10), 0)
        self.assertFalse((self.runtime / stop_request.FILE_NAME).exists())

    def run_in_process(self, *args):
        with mock.patch.dict(os.environ, {"COIL_TOOL_LOCAL_DIR": str(self.local)}), \
                mock.patch.object(process_manager, "GRACEFUL_WAIT", 1.0), \
                mock.patch.object(process_manager, "FORCE_WAIT", 1.0), \
                mock.patch("builtins.print"):
            return process_manager.main(list(args))

    def test_unanswered_desktop_is_not_killed_without_force(self):
        frame = hold_in_child(self.runtime, instance_lock.KIND_DESKTOP)   # 頼みを聞かない(古い版など)
        self.addCleanup(lambda: frame.poll() is None and frame.kill())
        self.assertEqual(self.run_in_process(), 1)
        self.assertIsNone(frame.poll(), "force でなければ落とさない")
        self.assertFalse((self.runtime / stop_request.FILE_NAME).exists(), "届かなかった頼みは取り下げる")
        self.assertEqual(self.run_in_process("--force"), 0)
        self.assertIsNotNone(frame.wait(10))
        frame.stdin.close()
        frame.stdout.close()

    def test_nothing_running(self):
        self.assertEqual(self.run_in_process(), 0)


class BrowserLauncherStyleTest(unittest.TestCase):
    """ランチャーと同じ頼み方でブラウザ版を確かめ・止める(ランチャーのコードが無くても流す)"""

    def test_health_then_force_false_stops(self):
        local = temp_local_dir()
        port = free_port()
        server = subprocess.Popen([sys.executable, str(ROOT / "start_app.py"), "--no-browser", "--port", str(port)],
                                  env=child_env(local), cwd=str(ROOT), stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: server.poll() is None and server.kill())

        def health():
            try:
                with OPENER.open(f"http://127.0.0.1:{port}/api/health", timeout=1.5) as res:
                    return json.loads(res.read().decode("utf-8"))
            except (OSError, ValueError):
                return {}
        self.assertTrue(wait_for(lambda: health().get("ready") is True, 30))
        body = health()
        self.assertEqual((body["app_id"], body["port"], body["pid"]), (APP_ID, port, server.pid))
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/shutdown", method="POST",
                                     data=b'{"force": false}', headers={"Content-Type": "application/json"})
        with OPENER.open(req, timeout=5) as res:
            self.assertIs(json.loads(res.read().decode("utf-8"))["stopped"], True)
        self.assertEqual(server.wait(15), 0)


LAUNCHER_SCRIPT = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from launcher import health, tool_registry
from launcher.runtime_state import RunningTool
import process_manager

job = json.loads(sys.argv[2])
out = {}
if job["what"] == "probe":
    out = {name: tool_registry.probe_tool_folder(path) for name, path in job["paths"].items()}
    exe = tool_registry.Tool(app_id=out["exe"].get("app_id", ""), display_name="x", port=int(out["exe"].get("port", 0)),
                             start_command=job["paths"]["exe"], ui_mode=out["exe"].get("ui_mode", ""))
    out["exe_watches_window"] = exe.watches_window
    out["vbs_forwards"] = tool_registry.Tool(app_id="x", display_name="x", start_command=job["paths"]["vbs"]).forwards_args
else:
    url = "http://127.0.0.1:%d/api/health" % job["port"]
    found = health.wait_ready(url, job["app_id"], timeout=30)
    out["ready"] = found is not None
    running = RunningTool(app_id=job["app_id"], port=job["port"], health_url=url,
                          start_command=job["start"], stop_method=job["method"],
                          pid=(found or {}).get("pid", 0), app_root=(found or {}).get("app_root", ""))
    result = process_manager.stop(running, force=job.get("force", False), timeout=20)
    out.update(stopped=result.stopped, method=result.method, busy=result.busy_jobs,
               message=result.message)
print(json.dumps(out, ensure_ascii=False))
"""


@unittest.skipUnless(LAUNCHER.parts and sys.version_info >= (3, 9),
                     "ランチャーのリポジトリが手元に無い(LAUNCHER_REPO)か、Python が古い")
class RealLauncherTest(unittest.TestCase):
    """ランチャー本体のコードで確かめる(別プロセス。名前の同じ process_manager.py がぶつかるため)"""

    def run_launcher(self, job, env=None):
        work = temp_local_dir()
        run_env = dict(env or os.environ, BUSINESS_TOOLS_LAUNCHER_LOCAL_DIR=str(work / "launcher"),
                       PYTHONIOENCODING="utf-8")
        done = subprocess.run([sys.executable, "-c", LAUNCHER_SCRIPT, str(LAUNCHER), json.dumps(job)],
                              cwd=str(LAUNCHER), env=run_env, capture_output=True, text=True,
                              encoding="utf-8", timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-3000:])
        return json.loads(done.stdout.strip().splitlines()[-1])

    def test_registration_reads_app_json(self):
        folder = temp_local_dir()
        (folder / "config").mkdir()
        (folder / "config" / "app.json").write_bytes((ROOT / "config" / "app.json").read_bytes())
        for name in ("start.bat", "Start.vbs"):
            (folder / name).write_bytes((ROOT / name).read_bytes())
        # Tauri の exe の代わり(ランチャーは中の "tauri" の文字で見分ける)
        (folder / "CoilCalculator.exe").write_bytes(b"MZ" + b"\0" * 64 + b"tauri://localhost __TAURI__")
        got = self.run_launcher({"what": "probe", "paths": {
            "bat": str(folder / "start.bat"), "vbs": str(folder / "Start.vbs"),
            "exe": str(folder / "CoilCalculator.exe")}})
        self.assertEqual(got["bat"]["app_id"], APP_ID)
        self.assertNotIn("port", got["bat"], "ブラウザ版の行のポートは設定画面で入れる(8741)")
        self.assertEqual(got["exe"]["app_id"], APP_ID)
        self.assertEqual(got["exe"].get("ui_mode"), "app")
        self.assertNotIn("port", got["exe"])
        self.assertTrue(got["exe_watches_window"], "exe の行は窓とプロセスで見る(/api/health を待たない)")
        self.assertTrue(got["vbs_forwards"], "Start.vbs は --no-browser を届ける")

    def start_browser(self, local, port):
        server = subprocess.Popen([sys.executable, str(ROOT / "start_app.py"), "--no-browser", "--port", str(port)],
                                  env=child_env(local), cwd=str(ROOT), stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: server.poll() is None and server.kill())
        return server

    def test_launcher_waits_ready_and_stops_by_api(self):
        local, port = temp_local_dir(), free_port()
        server = self.start_browser(local, port)
        got = self.run_launcher({"what": "stop", "port": port, "app_id": APP_ID, "method": "shutdown_api",
                                 "start": str(ROOT / "start.bat")})
        self.assertTrue(got["ready"], got)
        self.assertTrue(got["stopped"], got)
        self.assertEqual(got["method"], "shutdown-api")
        self.assertEqual(server.wait(15), 0)

    @unittest.skipUnless(os.name == "nt", "stop.bat は Windows の cmd.exe で動かす")
    def test_launcher_stops_by_stop_bat(self):
        local, port = temp_local_dir(), free_port()
        server = self.start_browser(local, port)
        got = self.run_launcher({"what": "stop", "port": port, "app_id": APP_ID, "method": "stop_bat",
                                 "start": str(ROOT / "start.bat")}, env=child_env(local))
        self.assertTrue(got["ready"], got)
        self.assertTrue(got["stopped"], got)
        self.assertEqual(got["method"], "stop.bat")
        self.assertEqual(server.wait(15), 0)


if __name__ == "__main__":
    unittest.main()
