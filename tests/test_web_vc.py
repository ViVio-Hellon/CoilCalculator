"""VC長さ計算の経路(日報管理ツール `tests/test_web_vc.py` の API の部分を、このツールの道に写したもの)

- マスタは「VC計算マスタの置き場所」の `VC計算マスタ.sqlite3`。**無ければ初期値で作る**
- vc-calculator の `vc_master.sqlite3` が置いてあれば**そちらを読む**(共有できる)
- 置き場所に届かなくても、VBA の初期値で計算は止めない(フォルダは作らない)
- 直すのは管理者だけ(鍵 = 管理者パスワード)。書いたら変更履歴と更新番号
- 置き場所を決めていなければ、この端末の作業フォルダに作る

画面(HTML・JS)の試験は `tests/test_vc_screen.py`。
"""
from __future__ import annotations

import json
import math
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Optional
from unittest import mock
from urllib.parse import quote, urlencode

from tests._helpers import ROOT  # noqa: F401  (sys.path)

from coilcalc import settings_store, source_db, web
from coilcalc.vc import db, masters, place, view
from coilcalc.vc.calc import vc_length

NITTO = "2008系/2001SR/310GH5"


class Res:
    def __init__(self, response: web.Response) -> None:
        self.status_code = response.status
        self.raw = response.body

    def get_json(self) -> Dict[str, Any]:
        return json.loads(self.raw.decode("utf-8"))


def isolate(test: unittest.TestCase) -> Path:
    """この端末の作業フォルダを一時フォルダに。読んだ中身・写し・控えの覚えも捨てる。"""
    tmp = Path(tempfile.mkdtemp(prefix="coil_vc_"))
    test.addCleanup(shutil.rmtree, tmp, True)
    local = tmp / "local"
    patcher = mock.patch.dict(os.environ, {"COIL_TOOL_LOCAL_DIR": str(local)})
    patcher.start()
    test.addCleanup(patcher.stop)

    def clear() -> None:
        masters.reset()
        source_db.forget()
        source_db._COPY_DIR = None
        db._backed_up.clear()

    clear()
    test.addCleanup(clear)
    return tmp


class VcCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = isolate(self)
        (self.tmp / "ref").mkdir()
        settings_store.save(settings_store.KEY_VC_MASTER_DIR, str(self.tmp / "ref"))
        self.app = web.App(web.MODE_DESKTOP)

    def get(self, path: str, args: Optional[Dict[str, str]] = None) -> Res:
        return Res(self.app.handle(web.Request("GET", path, urlencode(args or {}))))

    def post(self, path: str, body: Any) -> Res:
        return Res(self.app.handle(web.Request(
            "POST", path, "", {"content-type": "application/json"},
            json.dumps(body, ensure_ascii=False).encode("utf-8"))))

    def unlock(self) -> None:
        res = self.post("/api/vc/unlock", {"enable": True, "password": "nisk"})
        self.assertEqual(res.status_code, 200, res.get_json())

    def master_path(self) -> Path:
        return place.master_path()


class MasterPlaceTests(VcCase):
    def test_first_visit_creates_the_master_in_the_folder(self) -> None:
        self.assertFalse(self.master_path().exists())
        body = self.get("/api/vc/state").get_json()
        self.assertTrue(self.master_path().exists())
        self.assertEqual(self.master_path().name, "VC計算マスタ.sqlite3")
        self.assertEqual(body["state"]["master"]["source"], "db")
        self.assertEqual(len(body["state"]["products"]), 6)

    def test_no_folder_falls_back_to_vba_values(self) -> None:
        (self.tmp / "ref").rmdir()
        body = self.get("/api/vc/state").get_json()["state"]
        self.assertEqual(body["master"]["source"], "seed")
        self.assertIn("VBA に直書きされていた初期値", body["master"]["note"])
        self.assertEqual(len(body["products"]), 6)
        res = self.post("/api/vc/run", {"fields": {"coatu": "20", "vcatu": "0.10",
                                                    "inside": "87"}})
        self.assertEqual(res.get_json()["result"]["fields"]["vclen"], "67.2")
        self.assertFalse((self.tmp / "ref").exists())       # フォルダは作らない

    def test_vc_calculator_master_is_used_as_is(self) -> None:
        older = self.tmp / "ref" / "vc_master.sqlite3"
        self.assertEqual(db.ensure_database(older), "created")
        conn = sqlite3.connect(str(older))
        conn.execute("UPDATE VC品種 SET VC厚 = 0.11 WHERE 品種名 = 'V325系'")
        conn.commit()
        conn.close()
        self.assertEqual(self.master_path(), older)
        products = self.get("/api/vc/state").get_json()["state"]["products"]
        self.assertEqual(next(p for p in products if p["name"] == "V325系")["vcatu"], "0.11")
        self.assertFalse((self.tmp / "ref" / "VC計算マスタ.sqlite3").exists())

    def test_default_is_the_local_work_folder(self) -> None:
        """置き場所を決めていなければ、この端末の作業フォルダ(master)に作る。"""
        settings_store.save(settings_store.KEY_VC_MASTER_DIR, "")
        masters.reset()
        body = self.get("/api/vc/state").get_json()["state"]
        self.assertEqual(body["master"]["source"], "db")
        self.assertEqual(self.master_path(), self.tmp / "local" / "master" / "VC計算マスタ.sqlite3")
        placed = self.get("/api/vc/settings").get_json()["place"]
        self.assertEqual(placed["origin"], "default")
        self.assertEqual(placed["level"], "ok")

    def test_site_default_from_config(self) -> None:
        """配布の既定(config/app.json の vc.master_dir)。端末の設定が勝つ。"""
        site = self.tmp / "site"
        site.mkdir()
        settings_store.save(settings_store.KEY_VC_MASTER_DIR, "")
        from coilcalc import app_config
        real = app_config.load

        def with_site():
            conf = real()
            conf["vc"] = {"master_dir": str(site)}
            return conf

        with mock.patch.object(app_config, "load", with_site):
            self.assertEqual(place.configured_dir(), (str(site), "site"))
            self.assertEqual(self.master_path().parent, site)
            settings_store.save(settings_store.KEY_VC_MASTER_DIR, str(self.tmp / "ref"))
            self.assertEqual(place.configured_dir()[1], "terminal")


class CalcApiTests(VcCase):
    def test_select_choose_and_run(self) -> None:
        body = self.post("/api/vc/select", {"product": NITTO,
                                            "fields": {"coatu": "9", "prolen": "1000"}}).get_json()
        self.assertEqual(body["fields"], {"coatu": "", "vcatu": "0.10", "inside": "",
                                          "vclen": "", "prolen": "1000"})
        body = self.post("/api/vc/inside", {"product": NITTO, "inside": "87",
                                            "fields": body["fields"]}).get_json()
        self.assertEqual(body["fields"]["inside"], "87.0")
        res = self.post("/api/vc/run", {"product": NITTO,
                                        "fields": {**body["fields"], "coatu": "20"}})
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["result"]["fields"]["vclen"], "67.2")
        self.assertEqual([c["value"] for c in body["result"]["counts"]], ["33.4", "26.8", "21.9"])
        self.assertEqual([c["label"] for c in body["result"]["counts"]], ["1×2", "2×4", "5×10"])
        self.assertEqual(body["result"]["mk"], "67.2")
        self.assertTrue(body["result"]["steps"])
        self.assertAlmostEqual(body["result"]["geometry"]["outer"], 127.0)

    def test_choice_not_in_master(self) -> None:
        res = self.post("/api/vc/inside", {"product": "TF200/TF200B", "inside": "95"})
        self.assertEqual(res.status_code, 422)
        self.assertEqual(res.get_json()["error"]["code"], "no_choice")

    def test_unknown_product(self) -> None:
        res = self.post("/api/vc/select", {"product": "無い品種"})
        self.assertEqual(res.status_code, 422)
        self.assertEqual(res.get_json()["error"]["code"], "no_product")
        self.assertEqual(len(res.get_json()["state"]["products"]), 6)

    def test_reverse_is_on(self) -> None:
        body = self.post("/api/vc/run", {"fields": {"vcatu": "0.10", "inside": "87",
                                                    "vclen": "67.2"}}).get_json()
        self.assertEqual(body["result"]["fields"]["coatu"], "20.0")
        self.assertEqual(body["result"]["computed"], ["coatu"])
        self.assertTrue(body["state"]["reverse"])

    def test_refusals_carry_field_errors(self) -> None:
        res = self.post("/api/vc/run", {"fields": {"coatu": "x", "vcatu": "0.1", "inside": "87"}})
        self.assertEqual(res.status_code, 422)
        self.assertIn("coatu", res.get_json()["result"]["errors"])
        res = self.post("/api/vc/run", {"fields": {"vcatu": "0.1", "inside": "87"}})
        self.assertEqual((res.status_code, res.get_json()["error"]["code"]), (422, "missing"))
        self.assertIn("肉厚かVC長さ", res.get_json()["error"]["message"])

    def test_bad_fields_shape(self) -> None:
        self.assertEqual(self.post("/api/vc/run", {"fields": ["x"]}).status_code, 400)

    def test_bad_json_and_unknown_path(self) -> None:
        res = Res(self.app.handle(web.Request("POST", "/api/vc/run", "", {}, b"{x")))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.get("/api/vc/nothing").status_code, 404)
        self.assertEqual(self.post("/api/vc/state", {}).status_code, 404)

    def test_quick(self) -> None:
        body = self.get("/api/vc/quick").get_json()
        self.assertEqual(len(body["quick"]["blocks"]), 7)
        self.assertEqual(body["master"]["source"], "db")
        self.assertFalse(body["grid"]["can_edit"])
        self.assertEqual(len(body["grid"]["blocks"]), 7)


class KeyTests(VcCase):
    def test_unlock_and_relock(self) -> None:
        res = self.post("/api/vc/unlock", {"enable": True, "password": "違う"})
        self.assertEqual((res.status_code, res.get_json()["error"]["code"]), (403, "wrong_password"))
        self.assertFalse(self.get("/api/vc/settings").get_json()["key"]["unlocked"])
        self.unlock()
        self.assertTrue(self.get("/api/vc/settings").get_json()["key"]["unlocked"])
        self.assertTrue(self.get("/api/vc/quick").get_json()["grid"]["can_edit"])
        self.post("/api/vc/unlock", {"enable": False})
        self.assertFalse(self.get("/api/vc/quick").get_json()["grid"]["can_edit"])

    def test_admin_password_change_is_per_terminal(self) -> None:
        res = self.post("/api/vc/admin-password", {"current": "x", "new": "abcd", "confirm": "abcd"})
        self.assertEqual(res.status_code, 403)
        res = self.post("/api/vc/admin-password", {"current": "nisk", "new": "ab", "confirm": "ab"})
        self.assertEqual((res.status_code, res.get_json()["error"]["code"]), (400, "too_short"))
        res = self.post("/api/vc/admin-password", {"current": "nisk", "new": "abcd", "confirm": "abce"})
        self.assertEqual((res.status_code, res.get_json()["error"]["code"]), (400, "mismatch"))
        res = self.post("/api/vc/admin-password", {"current": "nisk", "new": "abcd", "confirm": "abcd"})
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertEqual(res.get_json()["key"]["password_origin"], "terminal")
        stored = json.loads(settings_store.path().read_text(encoding="utf-8"))
        self.assertNotIn("abcd", json.dumps(stored))                 # 平文では持たない
        self.assertEqual(self.post("/api/vc/unlock", {"enable": True, "password": "nisk"}).status_code, 403)
        self.assertEqual(self.post("/api/vc/unlock", {"enable": True, "password": "abcd"}).status_code, 200)
        res = self.post("/api/vc/admin-password", {"current": "abcd", "reset": True})
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertEqual(res.get_json()["key"]["password_origin"], "default")


class QuickGridApiTests(VcCase):
    def test_needs_the_admin_password(self) -> None:
        body = {"block": "VE系", "insides": "98", "thicknesses": "5, 999"}
        res = self.post("/api/vc/quick-grid", body)
        self.assertEqual((res.status_code, res.get_json()["error"]["code"]), (403, "need_password"))
        res = self.post("/api/vc/quick-grid", {**body, "password": "nisk"})
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertIn("1 マス足しました", res.get_json()["message"])
        ve = next(b for b in res.get_json()["grid"]["blocks"] if b["name"] == "VE系")
        self.assertIn("999", ve["thicknesses"])
        res = self.post("/api/vc/quick-grid", {**body, "thicknesses": "x", "password": "nisk"})
        self.assertEqual((res.status_code, res.get_json()["error"]["code"]), (400, "bad_value"))

    def test_unlocked_does_not_ask_again(self) -> None:
        self.unlock()
        res = self.post("/api/vc/quick-grid", {"block": "R575B", "insides": "88",
                                                "thicknesses": "6"})
        self.assertEqual(res.status_code, 200, res.get_json())

    def test_fill_from_a_product(self) -> None:
        self.unlock()
        state = self.get("/api/vc/quick").get_json()
        products = {p["name"]: p["vcatu"] for p in state["grid"]["products"]}
        self.assertEqual(products["TF200/TF200B"], "0.06")
        self.post("/api/vc/quick-grid", {"block": "R575B", "insides": "88", "thicknesses": "6, 7"})
        res = self.post("/api/vc/quick-grid", {
            "block": "R575B", "insides": "88", "thicknesses": "6, 7",
            "length": "product", "product": "TF200/TF200B"})
        body = res.get_json()
        self.assertEqual(res.status_code, 200, body)
        self.assertIn("長さが空だった 2 マスに長さを入れました", body["message"])
        block = next(b for b in body["quick"]["blocks"] if b["name"] == "R575B")
        heads = block["headers"]
        row = block["rows"][0]["cells"]
        self.assertEqual(row[heads.index("6")], str(math.floor(vc_length(6, 0.06, 88))))
        self.assertEqual(row[heads.index("5")], "26")

    def test_bad_vcatu_is_a_400(self) -> None:
        self.unlock()
        res = self.post("/api/vc/quick-grid", {"block": "R575B", "insides": "88",
                                               "thicknesses": "6", "length": "value", "vcatu": "10"})
        self.assertEqual((res.status_code, res.get_json()["error"]["code"]), (400, "bad_value"))


class QuickBlockApiTests(VcCase):
    ADD = {"new_product": "畳論マン", "new_vcatu": "0.1", "insides": "88",
           "thicknesses": "5, 20, 30", "length": "formula"}

    def blocks(self, body: dict) -> Dict[str, dict]:
        return {b["name"]: b for b in body["grid"]["blocks"]}

    def test_every_write_needs_the_key(self) -> None:
        for url, body in (("/api/vc/quick-block", self.ADD),
                          ("/api/vc/quick-block/delete", {"block": "R575B"}),
                          ("/api/vc/quick-block/source", {"block": "R575B", "product": "V325系"}),
                          ("/api/vc/quick-cells/delete", {"block": "R575B", "insides": "88"}),
                          ("/api/vc/product/delete", {"product": "V325系"}),
                          ("/api/vc/place", {"dir": str(self.tmp)})):
            with self.subTest(url=url):
                res = self.post(url, body)
                self.assertEqual((res.status_code, res.get_json()["error"]["code"]),
                                 (403, "need_password"))
        blocks = self.blocks(self.get("/api/vc/settings").get_json())
        self.assertIn("R575B", blocks)
        self.assertEqual(blocks["R575B"]["product"], "")

    def test_add_then_remove(self) -> None:
        res = self.post("/api/vc/quick-block", {**self.ADD, "password": "nisk"})
        body = res.get_json()
        self.assertEqual(res.status_code, 200, body)
        self.assertIn("早見表に「畳論マン」を足しました(マス 3)", body["message"])
        added = self.blocks(body)["畳論マン"]
        self.assertEqual((added["product"], added["cells"]), ("畳論マン", 3))
        state = self.get("/api/vc/state").get_json()["state"]
        self.assertIn("畳論マン", [p["name"] for p in state["products"]])

        self.unlock()
        res = self.post("/api/vc/quick-cells/delete", {"block": "畳論マン", "thicknesses": "30"})
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertEqual(self.blocks(res.get_json())["畳論マン"]["thicknesses"], ["5", "20"])
        res = self.post("/api/vc/quick-block/delete", {"block": "畳論マン"})
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertNotIn("畳論マン", self.blocks(res.get_json()))
        res = self.post("/api/vc/product/delete", {"product": "畳論マン"})
        self.assertEqual(res.status_code, 200, res.get_json())
        state = self.get("/api/vc/state").get_json()["state"]
        self.assertNotIn("畳論マン", [p["name"] for p in state["products"]])

    def test_switch_between_formula_and_fixed(self) -> None:
        self.unlock()
        res = self.post("/api/vc/quick-block/source", {"block": "R575B", "product": "TF200/TF200B"})
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertIn("式: VC品種「TF200/TF200B」", self.blocks(res.get_json())["R575B"]["kind"])
        res = self.post("/api/vc/quick-block/source", {"block": "R575B", "product": ""})
        self.assertIn("固定値", self.blocks(res.get_json())["R575B"]["kind"])

    def test_refusals_are_400_and_say_why(self) -> None:
        self.unlock()
        for url, body, words in (
                ("/api/vc/quick-block", {**self.ADD, "new_vcatu": ""}, "VC厚"),
                ("/api/vc/quick-block", {**self.ADD, "new_product": "", "product": "V325系"},
                 "枠はもうあります"),
                ("/api/vc/quick-cells/delete", {"block": "R575B"}, "消す内径か肉厚"),
                ("/api/vc/quick-block/delete", {"block": "無い枠"}, "ありません"),
                ("/api/vc/product/delete", {"product": "無い品種"}, "ありません")):
            with self.subTest(url=url, body=body):
                res = self.post(url, body)
                self.assertEqual((res.status_code, res.get_json()["error"]["code"]),
                                 (400, "bad_value"))
                self.assertIn(words, res.get_json()["error"]["message"])

    def test_cannot_write_when_master_is_unreachable(self) -> None:
        (self.tmp / "ref").rmdir()
        res = self.post("/api/vc/quick-block", {**self.ADD, "password": "nisk"})
        self.assertEqual((res.status_code, res.get_json()["error"]["code"]), (422, "no_source"))


class TableTests(VcCase):
    """マスタの表(日報管理ツールの マスタ管理 →「VC計算マスタ」に当たる所)。"""

    def browse(self, table: str, **args: str) -> dict:
        return self.get("/api/vc/tables", {"table": table, **args}).get_json()

    def row(self, table: str, **match) -> dict:
        rows = self.browse(table)["rows"]
        return next(r for r in rows if all(r[k] == v for k, v in match.items()))

    def save(self, table: str, key, values: dict) -> Res:
        return self.post("/api/vc/tables/save", {"table": table, "row": key, "values": values})

    def test_listed_tables(self) -> None:
        body = self.browse("VC品種")
        names = [t["table"] for t in body["tables"]]
        self.assertIn("VC品種", names)
        self.assertNotIn("_メタ", names)
        self.assertIn("VC長さ計算", next(t["note"] for t in body["tables"] if t["table"] == "VC品種"))
        self.assertFalse(body["editable"])                         # 鍵を開けるまで見るだけ
        self.assertEqual(body["total"], 6)

    def test_edit_reaches_the_calculator_with_history(self) -> None:
        self.unlock()
        before = self.get("/api/vc/state").get_json()["state"]["master"]["revision"]
        row = self.row("VC品種", 品種名="V325系")
        res = self.save("VC品種", row["__行"], {"VC厚": "0.2"})
        self.assertEqual(res.status_code, 200, res.get_json())
        state = self.get("/api/vc/state").get_json()["state"]
        self.assertEqual(next(p for p in state["products"] if p["name"] == "V325系")["vcatu"], "0.20")
        self.assertEqual(state["master"]["revision"], before + 1)
        history = self.browse("変更履歴")
        self.assertFalse(history["editable"])
        self.assertIn("直せません", history["view_only_why"])
        self.assertEqual([(r["表"], r["操作"]) for r in history["rows"]], [("VC品種", "更新")])
        self.assertIn('"VC厚": 0.13', history["rows"][0]["変更前"])

    def test_needs_the_key(self) -> None:
        row = self.row("VC品種", 品種名="V325系")
        self.assertEqual(self.save("VC品種", row["__行"], {"VC厚": "0.2"}).status_code, 403)

    def test_table_rules(self) -> None:
        self.unlock()
        v325 = self.row("VC品種", 品種名="V325系")
        res = self.save("VC品種", v325["__行"], {"VC厚": "0"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("値の範囲", res.get_json()["error"]["message"])
        nitto = self.row("VC品種", 品種名=NITTO)
        res = self.post("/api/vc/tables/delete", {"table": "VC品種", "row": nitto["__行"]})
        self.assertEqual(res.status_code, 400)
        message = res.get_json()["error"]["message"]
        self.assertIn("使われているので消せません", message)
        self.assertIn("「設定」→ 早見表の品種", message)
        res = self.post("/api/vc/tables/add", {"table": "VC内径選択肢",
                                               "values": {"品種名": "無い品種", "表示順": "1",
                                                          "表示名": "特", "内径": "90"}})
        self.assertEqual(res.status_code, 400)
        self.assertIn("親の表に無い品種名", res.get_json()["error"]["message"])

    def test_rename_follows_to_children(self) -> None:
        self.unlock()
        nitto = self.row("VC品種", 品種名=NITTO)
        res = self.save("VC品種", nitto["__行"], {"品種名": "2008系"})
        self.assertEqual(res.status_code, 200, res.get_json())
        names = {r["品種名"] for r in self.browse("VC内径選択肢")["rows"]}
        self.assertIn("2008系", names)
        self.assertNotIn(NITTO, names)

    def test_settings_rows_are_fixed_and_checked(self) -> None:
        self.unlock()
        page = self.browse("アプリ設定")
        self.assertTrue(page["editable"])
        self.assertFalse(page["can_add"])
        rounding = self.row("アプリ設定", キー="早見表の丸め")
        self.assertEqual(self.save("アプリ設定", rounding["__行"], {"値": "切り上げ"}).status_code, 400)
        res = self.save("アプリ設定", rounding["__行"], {"キー": "別の名前"})
        self.assertIn("キーは変えられません", res.get_json()["error"]["message"])
        res = self.save("アプリ設定", rounding["__行"], {"値": "四捨五入"})
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertEqual(self.get("/api/vc/quick").get_json()["quick"]["rounding"], "四捨五入")
        res = self.post("/api/vc/tables/delete", {"table": "アプリ設定", "row": rounding["__行"]})
        self.assertEqual(res.status_code, 422)

    def test_add_and_delete_a_row(self) -> None:
        self.unlock()
        res = self.post("/api/vc/tables/add", {"table": "枚数定尺", "values": {}})
        self.assertEqual(res.status_code, 400)
        before = self.browse("枚数定尺")["total"]
        values = {"表示順": "9", "記号": "M8", "表示名": "4×8", "長さmm": "2438", "有効": "1"}
        res = self.post("/api/vc/tables/add", {"table": "枚数定尺", "values": values})
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertEqual(res.get_json()["page"]["total"], before + 1)
        added = self.row("枚数定尺", 表示名="4×8")
        res = self.post("/api/vc/tables/delete", {"table": "枚数定尺", "row": added["__行"]})
        self.assertEqual(res.status_code, 200, res.get_json())
        res = self.post("/api/vc/tables/delete", {"table": "枚数定尺", "row": added["__行"]})
        self.assertEqual(res.status_code, 409)

    def test_tone_is_one_of_the_paper_colors(self) -> None:
        self.unlock()
        ve = self.row("早見表ブロック", 品種名="VE系")
        res = self.save("早見表ブロック", ve["__行"], {"枠色": "pink"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("枠色", res.get_json()["error"]["message"])

    def test_hidden_meta_table_cannot_be_opened_or_written(self) -> None:
        self.unlock()
        self.assertIn("ありません", self.browse("_メタ")["error"])
        self.assertEqual(self.save("_メタ", 1, {"値": "0"}).status_code, 404)

    def test_filter_and_sort(self) -> None:
        body = self.browse("VC品種", q="V325")
        self.assertEqual([r["品種名"] for r in body["rows"]], ["V325系"])
        body = self.browse("VC品種", sort="VC厚", dir="desc")
        values = [float(r["VC厚"]) for r in body["rows"]]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_backup_is_taken_next_to_the_master(self) -> None:
        self.unlock()
        row = self.row("VC品種", 品種名="V325系")
        self.save("VC品種", row["__行"], {"業者名": "スミロン2"})
        backups = list((self.master_path().parent / "backup").glob("VC計算マスタ_*.sqlite3"))
        self.assertEqual(len(backups), 1)


class SettingsTests(VcCase):
    def placed(self) -> dict:
        return self.get("/api/vc/settings").get_json()["place"]

    def test_priority_is_shown_in_order(self) -> None:
        self.get("/api/vc/state")
        placed = self.placed()
        self.assertEqual([n["name"] for n in placed["names"]],
                         ["VC計算マスタ.sqlite3", "vc_master.sqlite3"])
        self.assertTrue(placed["names"][0]["used"])
        self.assertFalse(placed["names"][1]["exists"])
        self.assertEqual(placed["level"], "ok")
        self.assertEqual(placed["origin"], "terminal")

    def test_neither_exists_yet(self) -> None:
        placed = view.place_view()
        self.assertEqual(placed["level"], "info")
        self.assertIn("VC計算マスタ.sqlite3 を VBA の初期値で作ります", placed["status"])

    def test_both_exist_second_is_not_read(self) -> None:
        self.get("/api/vc/state")
        db.ensure_database(self.tmp / "ref" / "vc_master.sqlite3")
        placed = self.placed()
        self.assertEqual(placed["level"], "warn")
        self.assertIn("vc_master.sqlite3 もありますが、読んでいません", placed["status"])

    def test_folder_can_point_at_vc_calculator(self) -> None:
        other = self.tmp / "vccalc"
        other.mkdir()
        db.ensure_database(other / "vc_master.sqlite3")
        res = self.post("/api/vc/place", {"dir": str(other), "password": "nisk"})
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertEqual(place.master_path(), other / "vc_master.sqlite3")
        placed = self.placed()
        self.assertEqual(placed["used"], str(other / "vc_master.sqlite3"))
        self.assertTrue(placed["names"][1]["used"])
        self.assertEqual(self.get("/api/vc/state").get_json()["state"]["master"]["source"], "db")

    def test_saving_the_folder_retries_at_once(self) -> None:
        missing = self.tmp / "まだ無い"
        res = self.post("/api/vc/place", {"dir": str(missing), "password": "nisk"})
        self.assertIn("届きません", res.get_json()["message"])
        self.assertEqual(self.get("/api/vc/state").get_json()["state"]["master"]["source"], "seed")
        good = self.tmp / "vccalc"
        good.mkdir()
        db.ensure_database(good / "vc_master.sqlite3")
        self.post("/api/vc/place", {"dir": str(good), "password": "nisk"})
        self.assertEqual(self.get("/api/vc/state").get_json()["state"]["master"]["source"], "db")

    def test_relative_folder_is_refused_and_empty_resets(self) -> None:
        res = self.post("/api/vc/place", {"dir": "master", "password": "nisk"})
        self.assertEqual((res.status_code, res.get_json()["error"]["code"]), (400, "bad_dir"))
        res = self.post("/api/vc/place", {"dir": "", "password": "nisk"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["place"]["origin"], "default")


class QuitWhileWritingTests(VcCase):
    def test_quit_confirm_mentions_writing(self) -> None:
        with mock.patch.object(db, "_active_writes", 1):
            res = self.post("/api/shutdown", {})
        self.assertEqual(res.status_code, 409)
        self.assertIn("書いている最中", res.get_json()["confirm"]["message"])
        self.assertNotIn("書いている最中", self.post("/api/shutdown", {}).get_json()["confirm"]["message"])


if __name__ == "__main__":
    unittest.main()
