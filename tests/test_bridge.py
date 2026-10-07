"""デスクトップ版の入口(`bridge.py`)── **ソケットを1つも開かずに**答える

外枠(Rust)の代わりに、この試験が bridge.py を子として起動し、標準入出力で
要求を渡します。子には「ソケットを作ると落ちる」仕掛けを入れておきます。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests._helpers import ROOT, child_env, temp_local_dir

NO_SOCKET = textwrap.dedent("""
    import socket
    def _refuse(*a, **k):
        raise RuntimeError("bridge はソケットを開いてはいけない")
    socket.socket = _refuse
    socket.create_connection = _refuse
""")


class Bridge:
    def __init__(self):
        self.hook = Path(tempfile.mkdtemp(prefix="coil_hook_"))
        (self.hook / "sitecustomize.py").write_text(NO_SOCKET, encoding="utf-8")
        env = child_env(temp_local_dir(), PYTHONPATH=str(self.hook))
        self.proc = subprocess.Popen([sys.executable, "-X", "utf8", str(ROOT / "bridge.py")],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, env=env, cwd=str(ROOT))
        self.next_id = 1

    def read(self):
        head = json.loads(self.proc.stdout.readline().decode("utf-8"))
        body = self.proc.stdout.read(head.get("len", 0)) if head.get("len") else b""
        return head, body

    def send(self, method, path, body=None):
        data = b"" if body is None else json.dumps(body).encode("utf-8")
        head = {"id": self.next_id, "method": method, "path": path, "query": "",
                "headers": [["Content-Type", "application/json"]], "len": len(data)}
        self.next_id += 1
        self.proc.stdin.write(json.dumps(head).encode("utf-8") + b"\n" + data)
        self.proc.stdin.flush()
        return head["id"]


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.b = Bridge()
        self.addCleanup(self._close)

    def _close(self):
        if self.b.proc.poll() is None:
            self.b.proc.kill()
        self.b.proc.wait(5)
        for stream in (self.b.proc.stdin, self.b.proc.stdout, self.b.proc.stderr):
            stream.close()

    def test_started_answers_and_ends_when_stdin_closes(self):
        head, _ = self.b.read()
        self.assertEqual(head["event"], "started")
        sent = self.b.send("POST", "/api/coil/calc", {"fields": {
            "thickness": "400", "inner-diameter": "557", "coil-width": "1250",
            "specific-gravity": "2.70", "plate-thickness": "1.00"}})
        head, body = self.b.read()
        self.assertEqual((head["id"], head["status"]), (sent, 200))
        self.assertEqual(json.loads(body)["results"]["weight"], "4,058.8 kg")
        # 応答の順は要求の順(1つずつ答える)
        ids = [self.b.send("GET", "/api/health") for _ in range(5)]
        self.assertEqual([self.b.read()[0]["id"] for _ in ids], ids)
        self.b.proc.stdin.close()
        self.assertEqual(self.b.proc.wait(10), 0, self.b.proc.stderr.read().decode("utf-8", "replace"))

    def test_shutdown_needs_confirmation_then_sends_quit(self):
        self.b.read()
        # 確かめ無し(窓の × を押しただけ): 止めずに確かめの文を返す
        self.b.send("POST", "/api/shutdown", {})
        head, body = self.b.read()
        self.assertEqual(head["status"], 409)
        self.assertIn("終了しますか", json.loads(body)["confirm"]["message"])
        self.assertIsNone(self.b.proc.poll(), "確かめ無しでは止まらない")
        # 「終了する」を選んだ
        self.b.send("POST", "/api/shutdown", {"confirmed": True})
        heads = [self.b.read()[0], self.b.read()[0]]
        self.assertIn("quit", [h.get("event") for h in heads])
        # 外枠は「quit」を受けて標準入力を閉じる
        self.b.proc.stdin.close()
        self.assertEqual(self.b.proc.wait(10), 0)

    def test_broken_frame_ends_with_error(self):
        self.b.read()
        self.b.proc.stdin.write(b'{"id": 1, "len": -5}\n')
        self.b.proc.stdin.flush()
        self.assertEqual(self.b.proc.wait(10), 1)


if __name__ == "__main__":
    unittest.main()
