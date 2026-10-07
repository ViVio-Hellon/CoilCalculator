"""共有の VC計算マスタ ── 掴まない・差し替えに付いていく・壊れていても止まらない

    - 読み終えたら、共有のマスタを掴んでいない(Windows では掴んでいるあいだ、ほかの人が
      マスタを差し替えられない)。写してから読む(source_db)
    - 動いているあいだにマスタが差し替えられたら、次の操作で新しい中身を読む
    - マスタが壊れている・SQLite でない → 最後に読めた中身(控え)か VBA の初期値で計算は続ける。
      書く操作は断る
    - 控え(JSON)が壊れている・端末の設定(settings.json)が壊れている → 止まらない
    - 作業フォルダが壊れていても、共有のマスタは読める(写しを一時フォルダに置く)
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import time
import unittest
from pathlib import Path

from tests._helpers import ROOT  # noqa: F401  (sys.path)
from tests.test_web_vc import VcCase

from coilcalc import settings_store, source_db
from coilcalc.vc import masters, place


def open_paths() -> set:
    """このプロセスが開いているファイル(Linux の /proc。ほかでは空 = 確かめない)。"""
    fd_dir = Path("/proc/self/fd")
    if not fd_dir.is_dir():
        return set()
    out = set()
    for fd in fd_dir.iterdir():
        try:
            out.add(os.path.realpath(os.readlink(str(fd))))
        except OSError:
            pass
    return out


class NotHeldTests(VcCase):
    def assert_not_held(self) -> None:
        master = os.path.realpath(str(place.master_path()))
        held = {p for p in open_paths() if p.startswith(master)}
        self.assertEqual(held, set(), "共有のマスタ(と -journal)を掴んだまま")
        # どの OS でも: 同じ中身の新しいファイルで差し替えられる(Windows では掴んでいると失敗する)
        fresh = place.master_path().with_name("差し替え.sqlite3")
        shutil.copy2(str(place.master_path()), str(fresh))
        os.replace(str(fresh), str(place.master_path()))

    def test_reading_and_writing_do_not_hold_the_master(self):
        self.get("/api/vc/state")
        self.assert_not_held()
        self.get("/api/vc/quick")
        self.get("/api/vc/settings")
        self.get("/api/vc/tables", {"table": "VC品種"})
        self.post("/api/vc/run", {"fields": {"coatu": "20", "vcatu": "0.1", "inside": "87"}})
        self.assert_not_held()
        self.unlock()
        res = self.post("/api/vc/quick-grid", {"block": "VE系", "insides": "98", "thicknesses": "999"})
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assert_not_held()

    def test_reads_are_from_a_local_copy(self):
        self.get("/api/vc/state")
        copies = list(source_db.copy_dir().glob("*.sqlite3"))
        self.assertTrue(copies, "写しが無い(共有を直接開いている)")
        self.assertFalse(any(str(c).startswith(str(place.master_dir())) for c in copies))


class ReplacedWhileRunningTests(VcCase):
    def test_follows_a_replaced_master(self):
        state = self.get("/api/vc/state").get_json()["state"]
        v325 = next(p for p in state["products"] if p["name"] == "V325系")
        self.assertEqual(v325["vcatu"], "0.13")
        # ほかの人が、手元で直したマスタを置き直した(同じ名前・同じ大きさのこともある)
        work = place.master_path().with_name("直したもの.sqlite3")
        shutil.copy2(str(place.master_path()), str(work))
        conn = sqlite3.connect(str(work))
        conn.execute("UPDATE VC品種 SET VC厚 = 0.15 WHERE 品種名 = 'V325系'")
        conn.execute("UPDATE _メタ SET 値 = CAST(CAST(値 AS INTEGER) + 1 AS TEXT) WHERE キー = 'revision'")
        conn.commit()
        conn.close()
        time.sleep(0.05)
        os.replace(str(work), str(place.master_path()))
        st = place.master_path().stat()
        os.utime(str(place.master_path()), ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
        state = self.get("/api/vc/state").get_json()["state"]
        self.assertEqual(next(p for p in state["products"] if p["name"] == "V325系")["vcatu"], "0.15")


class BrokenTests(VcCase):
    def break_master(self) -> None:
        place.master_path().write_bytes(b"this is not a sqlite database" * 100)
        source_db.forget()
        masters.invalidate()

    def test_broken_master_falls_back_to_the_last_good_copy(self):
        self.assertEqual(self.get("/api/vc/state").get_json()["state"]["master"]["source"], "db")
        self.break_master()
        state = self.get("/api/vc/state").get_json()["state"]
        self.assertEqual(state["master"]["source"], "cache")
        self.assertIn("最後に読めた中身", state["master"]["note"])
        res = self.post("/api/vc/run", {"fields": {"coatu": "20", "vcatu": "0.10", "inside": "87"}})
        self.assertEqual(res.get_json()["result"]["fields"]["vclen"], "67.2")
        # 書く操作は断る(壊れたマスタに書き足さない)
        res = self.post("/api/vc/quick-block/delete", {"block": "R575B", "password": "nisk"})
        self.assertEqual((res.status_code, res.get_json()["error"]["code"]), (422, "no_source"))

    def test_broken_master_and_no_copy_uses_vba_values(self):
        place.master_path().parent.mkdir(parents=True, exist_ok=True)
        place.master_path().write_bytes(b"\x00" * 4096)
        state = self.get("/api/vc/state").get_json()["state"]
        self.assertEqual(state["master"]["source"], "seed")
        self.assertEqual(len(state["products"]), 6)
        body = self.get("/api/vc/tables", {"table": "VC品種"}).get_json()
        self.assertEqual(body["master"]["source"], "seed")       # 表の面も落ちない

    def test_broken_cache_json_is_ignored(self):
        self.get("/api/vc/state")
        for junk in ("{x", "[1, 2]", json.dumps({"products": [{"name": 1}]})):
            with self.subTest(junk=junk):
                masters.cache_path().write_text(junk, encoding="utf-8")
                masters.reset()
                self.break_master()
                state = self.get("/api/vc/state").get_json()["state"]
                self.assertEqual(state["master"]["source"], "seed")
                self.assertEqual(len(state["products"]), 6)
                db_path = place.master_path()
                db_path.unlink()
                masters.reset()
                self.get("/api/vc/state")                       # 作り直して次へ

    def test_broken_settings_file_is_set_aside(self):
        settings_store.path().write_text("{ 壊れている", encoding="utf-8")
        masters.reset()
        body = self.get("/api/vc/settings").get_json()
        self.assertEqual(body["place"]["origin"], "default")      # 既定で動く
        aside = list(settings_store.path().parent.glob("settings.broken-*.json"))
        self.assertEqual(len(aside), 1)
        self.assertEqual(aside[0].read_text(encoding="utf-8"), "{ 壊れている")

    @unittest.skipIf(sys.platform == "win32", "フォルダの代わりにファイルを置く試し方は POSIX で")
    def test_broken_work_folder_still_reads_the_shared_master(self):
        """作業フォルダ(写しの置き場)が作れなくても、共有のマスタは一時フォルダに写して読む。

        作業フォルダが壊れていると、この端末の設定(settings.json)も読めない。置き場所は
        配布の既定(config/app.json の vc.master_dir)で決まる ── 共有を配る現場はこちら。
        """
        from unittest import mock
        from coilcalc import app_config
        self.get("/api/vc/state")                                 # 共有にマスタを作る
        local = Path(os.environ["COIL_TOOL_LOCAL_DIR"])
        shutil.rmtree(str(local))
        local.write_text("フォルダではない", encoding="utf-8")
        temp = self.tmp / "temp"
        temp.mkdir()
        real = app_config.load

        def with_site():
            conf = real()
            conf["vc"] = {"master_dir": str(self.tmp / "ref")}
            return conf

        with mock.patch.dict(os.environ, {"TEMP": str(temp)}), \
                mock.patch.object(app_config, "load", with_site):
            source_db._COPY_DIR = None
            source_db.forget()
            masters.reset()
            state = self.get("/api/vc/state").get_json()["state"]
        self.assertEqual(state["master"]["source"], "db")
        self.assertTrue(list((temp / "CoilCalculator" / "cache" / "source").glob("*.sqlite3")))


if __name__ == "__main__":
    unittest.main()
