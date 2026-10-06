"""ブラウザ版とデスクトップ版の排他(`coilcalc/instance_lock.py` と `src-tauri/src/instance.rs`)

Rust 側と**同じファイルを同じ決め方で**見ていないと排他が効きません。
ここでは Python 同士の取り合い(別プロセス)と、Rust 側の決め方が食い違っていないかを確かめます。
Rust の exe と Python の取り合いは scripts/desktop_smoke.py が本物で確かめます。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from tests._helpers import ROOT, temp_local_dir
from coilcalc import app_config, instance_lock

RUST = (ROOT / "src-tauri" / "src" / "instance.rs").read_text(encoding="utf-8")

HOLDER = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, {root!r})
    from coilcalc import instance_lock
    lock = instance_lock.InstanceLock({runtime!r})
    assert lock.acquire()
    lock.write_owner({kind!r}, url="http://127.0.0.1:1/")
    print("held", flush=True)
    sys.stdin.readline()
    lock.release()
""")


def hold_in_child(runtime: Path, kind: str) -> subprocess.Popen:
    code = HOLDER.format(root=str(ROOT), runtime=str(runtime), kind=kind)
    proc = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "held"
    return proc


class LockTest(unittest.TestCase):
    def setUp(self):
        self.runtime = temp_local_dir() / "runtime"

    def test_only_one_holder_and_released_on_exit(self):
        child = hold_in_child(self.runtime, instance_lock.KIND_DESKTOP)
        try:
            mine = instance_lock.InstanceLock(self.runtime)
            self.assertFalse(mine.acquire(), "別のプロセスが握っている間は取れない")
            owner = instance_lock.read_owner(self.runtime)
            self.assertEqual(owner["kind"], "desktop")
            self.assertIn("デスクトップ版", instance_lock.describe(owner))
        finally:
            child.stdin.close()
            child.wait(10)
            child.stdout.close()
        self.assertTrue(mine.acquire(), "握っていたプロセスが終われば取れる")
        mine.release()

    def test_killed_holder_does_not_leave_lock(self):
        child = hold_in_child(self.runtime, instance_lock.KIND_BROWSER)
        child.kill()
        child.wait(10)
        child.stdin.close()
        child.stdout.close()
        mine = instance_lock.InstanceLock(self.runtime)
        self.assertTrue(mine.acquire(), "落ちても錠は残らない(OS が外す)")
        mine.write_owner(instance_lock.KIND_BROWSER, url="x")
        mine.release()
        self.assertIsNone(instance_lock.read_owner(self.runtime, wait=0), "自分の持ち主の印は消す")

    def test_release_keeps_someone_elses_owner_file(self):
        lock = instance_lock.InstanceLock(self.runtime)
        self.assertTrue(lock.acquire())
        (self.runtime / instance_lock.OWNER_NAME).write_text('{"kind": "desktop", "pid": -1}',
                                                             encoding="utf-8")
        lock.release()
        self.assertEqual(instance_lock.read_owner(self.runtime, wait=0)["pid"], -1)


class SameRulesAsRustTest(unittest.TestCase):
    """Rust 側(instance.rs)と、ファイル名・作業フォルダの決め方が同じか。"""

    def test_file_names(self):
        self.assertIn(f'LOCK_NAME: &str = "{instance_lock.LOCK_NAME}"', RUST)
        self.assertIn(f'OWNER_NAME: &str = "{instance_lock.OWNER_NAME}"', RUST)
        self.assertIn(f'KIND_DESKTOP: &str = "{instance_lock.KIND_DESKTOP}"', RUST)
        self.assertIn(f'KIND_BROWSER: &str = "{instance_lock.KIND_BROWSER}"', RUST)
        self.assertIn('local_root(app_root).join("runtime")', RUST)

    def test_local_root_order(self):
        # Rust: COIL_TOOL_LOCAL_DIR → LOCALAPPDATA → XDG_DATA_HOME → ~/.local/share
        order = [m.start() for m in (re.search(p, RUST) for p in
                 ("COIL_TOOL_LOCAL_DIR", '"LOCALAPPDATA", "XDG_DATA_HOME"', r'"\.local"'))]
        self.assertEqual(order, sorted(order))
        self.assertIn('unwrap_or_else(|| "CoilCalculator".into())', RUST)
        conf = {"local_dir_name": "コイルテスト"}
        with mock.patch.dict(os.environ, {"COIL_TOOL_LOCAL_DIR": "", "LOCALAPPDATA": "/L",
                                          "XDG_DATA_HOME": "/X"}):
            self.assertEqual(app_config.local_root(conf), Path("/L") / "コイルテスト")
        with mock.patch.dict(os.environ, {"COIL_TOOL_LOCAL_DIR": "", "LOCALAPPDATA": "",
                                          "XDG_DATA_HOME": "/X"}):
            self.assertEqual(app_config.local_root(conf), Path("/X") / "コイルテスト")
        with mock.patch.dict(os.environ, {"COIL_TOOL_LOCAL_DIR": " /D "}):
            self.assertEqual(app_config.local_root(conf), Path("/D"))

    def test_exit_code_for_refusal_is_the_same(self):
        import start_app
        self.assertIn(f"const EXIT_OTHER_RUNNING: i32 = {start_app.EXIT_OTHER_RUNNING};",
                      (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
