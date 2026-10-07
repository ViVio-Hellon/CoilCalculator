"""日報管理ツールと同じ VC計算マスタを読み書きし合う(相手の**実物のコード**を別のプロセスで動かす)

日報管理ツールのリポジトリ(vba-daily-report-python-migration)が手元にあるときだけ流す。
置き場所は環境変数 NIPPOU_REPO、無ければこのツールの隣のフォルダを探す。無ければ飛ばす
(GitHub Actions には無い)。

確かめること(2台の端末が1つの共有マスタを使う場面):
    1. 日報管理ツールが作ったマスタを、このツールがそのまま読む(逆も)
    2. このツールで直す → 日報管理ツールに効く(値・更新番号・変更履歴)
    3. 日報管理ツールで早見表の品種を足す → このツールの計算・早見表に出る
    4. 片方が書いている最中に、もう片方が書く → 待ってから書けるか、断られて壊れない
    5. 控え(backup)は同じ名前の1つ。変更履歴は同じ表に同じ形で積まれる
    6. vc-calculator の名前(vc_master.sqlite3)を両方が同じように選ぶ
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import textwrap
import time
import unittest
from pathlib import Path

from tests._helpers import ROOT
from tests.test_web_vc import VcCase

from coilcalc.vc import db, place


def find_nippou() -> Path:
    for cand in (os.environ.get("NIPPOU_REPO", ""), str(ROOT.parent / "vba-daily-report-python-migration")):
        if cand and (Path(cand) / "nippou" / "vc" / "db.py").is_file():
            return Path(cand)
    return Path()


NIPPOU = find_nippou()

#: 日報管理ツール側で動かす前置き。マスタの道を差し替える(相手の試験 test_vc_master.py と同じやり方)
PRELUDE = textwrap.dedent('''
    import json, sys, time
    from pathlib import Path
    from unittest import mock
    sys.path.insert(0, {repo!r})
    from nippou import source_db
    from nippou.vc import db, grid, masters
    path = Path({path!r})
    work = Path({work!r})
    (work / "copies").mkdir(parents=True, exist_ok=True)
    mock.patch.object(masters, "master_path", lambda: path).start()
    mock.patch.object(masters, "cache_path", lambda: work / "snap.json").start()
    mock.patch.object(source_db, "copy_dir", lambda: work / "copies").start()
''')


@unittest.skipUnless(NIPPOU.parts, "日報管理ツールのリポジトリが手元に無い(NIPPOU_REPO)")
class InteropTests(VcCase):
    def nippou(self, body: str, *, wait: bool = True, timeout: float = 60):
        """日報管理ツールのコードを別のプロセスで動かす。最後の print(json) を返す。"""
        code = PRELUDE.format(repo=str(NIPPOU), path=str(self.master_path()),
                              work=str(self.tmp / "nippou_work")) + textwrap.dedent(body)
        env = dict(os.environ, NIPPOU_LOCAL_DIR=str(self.tmp / "nippou_local"), PYTHONIOENCODING="utf-8")
        proc = subprocess.Popen([sys.executable, "-c", code], cwd=str(NIPPOU), env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding="utf-8")
        if not wait:
            return proc
        out, err = proc.communicate(timeout=timeout)
        self.assertEqual(proc.returncode, 0, err[-2000:])
        return json.loads(out.strip().splitlines()[-1])

    def state(self) -> dict:
        return self.get("/api/vc/state").get_json()["state"]

    def vcatu(self, name: str) -> str:
        return next(p["vcatu"] for p in self.state()["products"] if p["name"] == name)

    # ------------------------------------------------------------------
    def test_master_made_by_nippou_is_read_here(self):
        made = self.nippou('print(json.dumps({"done": db.ensure_database(path)}))')
        self.assertEqual(made["done"], "created")
        state = self.state()
        self.assertEqual(state["master"]["source"], "db")
        self.assertEqual(len(state["products"]), 6)

    def test_master_made_here_is_read_by_nippou(self):
        self.state()                                             # このツールが作る
        seen = self.nippou('''
            snap = masters.current()
            print(json.dumps({"source": snap.source, "n": len(snap.products), "rev": snap.revision}))
        ''')
        self.assertEqual((seen["source"], seen["n"]), ("db", 6))
        self.assertEqual(seen["rev"], self.state()["master"]["revision"])

    def test_edit_here_reaches_nippou_with_history(self):
        self.state()
        self.unlock()
        rows = self.get("/api/vc/tables", {"table": "VC品種"}).get_json()["rows"]
        row = next(r for r in rows if r["品種名"] == "V325系")
        res = self.post("/api/vc/tables/save", {"table": "VC品種", "row": row["__行"], "values": {"VC厚": "0.2"}})
        self.assertEqual(res.status_code, 200, res.get_json())
        mine = self.state()["master"]["revision"]
        seen = self.nippou('''
            snap = masters.current()
            p = next(p for p in snap.products if p.name == "V325系")
            with source_db.open_source(path) as conn:
                hist = [dict(r) for r in conn.execute('SELECT 表, 操作, 変更前, 変更後 FROM "変更履歴"')]
            print(json.dumps({"vcatu": p.vcatu, "rev": snap.revision, "hist": hist}, ensure_ascii=False))
        ''')
        self.assertEqual(seen["vcatu"], 0.2)
        self.assertEqual(seen["rev"], mine)
        self.assertEqual([(h["表"], h["操作"]) for h in seen["hist"]], [("VC品種", "更新")])
        self.assertEqual(json.loads(seen["hist"][0]["変更前"]), {"VC厚": 0.13})

    def test_block_added_by_nippou_shows_here(self):
        self.state()
        before = self.state()["master"]["revision"]
        done = self.nippou('''
            r = grid.add_block(path, new_product="連携テスト品", new_vcatu="0.1", insides_text="88",
                               thicknesses_text="5, 10", formula=True)
            print(json.dumps({"ok": r.ok, "message": r.message}, ensure_ascii=False))
        ''')
        self.assertTrue(done["ok"], done["message"])
        state = self.state()
        self.assertIn("連携テスト品", [p["name"] for p in state["products"]])
        self.assertGreater(state["master"]["revision"], before)
        quick = self.get("/api/vc/quick").get_json()["quick"]
        self.assertIn("連携テスト品", [b["name"] for b in quick["blocks"]])
        res = self.post("/api/vc/run", {"product": "連携テスト品",
                                        "fields": {"coatu": "20", "vcatu": "0.10", "inside": "88"}})
        self.assertEqual(res.status_code, 200)

    def test_edit_by_nippou_is_picked_up_without_restart(self):
        self.assertEqual(self.vcatu("V325系"), "0.13")
        self.nippou('''
            with db.writing(path) as conn:
                conn.execute('UPDATE "VC品種" SET "VC厚" = 0.16 WHERE "品種名" = ?', ["V325系"])
                db.record_change(conn, "VC品種", "更新", None, {"VC厚": 0.13}, {"VC厚": 0.16})
                db.bump_revision(conn)
            print(json.dumps({"ok": True}))
        ''')
        self.assertEqual(self.vcatu("V325系"), "0.16")

    def test_writer_lock_is_respected_both_ways(self):
        """日報管理ツールが書き込みの鍵を握っているあいだ、このツールの書き込みは待つか断られる。壊れない。"""
        self.state()
        self.unlock()
        holder = self.nippou('''
            conn = db._begin_immediate(path)
            conn.execute('UPDATE "VC品種" SET "備考" = ? WHERE "品種名" = ?', ["日報側", "V325系"])
            print("locked", flush=True)
            time.sleep(4)
            db.bump_revision(conn)
            db._commit(conn)
            conn.close()
            print(json.dumps({"ok": True}))
        ''', wait=False)
        self.assertEqual(holder.stdout.readline().strip(), "locked")
        rows = self.get("/api/vc/tables", {"table": "VC品種"}).get_json()["rows"]
        row = next(r for r in rows if r["品種名"] == "V325系")
        started = time.monotonic()
        res = self.post("/api/vc/tables/save", {"table": "VC品種", "row": row["__行"],
                                                "values": {"業者名": "このツール側"}})
        waited = time.monotonic() - started
        out, err = holder.communicate(timeout=30)
        self.assertEqual(holder.returncode, 0, err[-2000:])
        if res.status_code == 200:
            self.assertGreater(waited, 1.0, "鍵を待たずに書けてしまった")
        else:
            self.assertEqual(res.status_code, 409, res.get_json())
            self.assertIn("書き込み中", res.get_json()["error"]["message"])
            res = self.post("/api/vc/tables/save", {"table": "VC品種", "row": row["__行"],
                                                    "values": {"業者名": "このツール側"}})
            self.assertEqual(res.status_code, 200, res.get_json())
        conn = sqlite3.connect(str(self.master_path()))
        try:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            got = conn.execute('SELECT "備考", "業者名" FROM "VC品種" WHERE "品種名" = ?', ["V325系"]).fetchone()
        finally:
            conn.close()
        self.assertEqual(got, ("日報側", "このツール側"), "どちらの書き込みも残る")

    def test_one_backup_per_day_and_same_history_table(self):
        self.state()
        self.unlock()
        self.post("/api/vc/quick-grid", {"block": "VE系", "insides": "98", "thicknesses": "999"})
        self.nippou('''
            r = grid.make_grid(path, "VE系", "98", "998")
            print(json.dumps({"ok": r.ok}))
        ''')
        backups = sorted((self.master_path().parent / "backup").glob("*.sqlite3"))
        self.assertEqual(len(backups), 1, backups)
        self.assertRegex(backups[0].name, r"^VC計算マスタ_\d{8}\.sqlite3$")
        conn = sqlite3.connect(str(self.master_path()))
        try:
            ops = conn.execute('SELECT 表, 操作 FROM "変更履歴" ORDER BY rowid').fetchall()
        finally:
            conn.close()
        self.assertEqual(ops, [("早見表値", "まとめて足す"), ("早見表値", "まとめて足す")])

    def test_both_pick_the_same_file_name(self):
        older = self.tmp / "ref" / "vc_master.sqlite3"
        self.nippou(f'''
            print(json.dumps({{"done": db.ensure_database(Path({str(older)!r}))}}))
        ''')
        self.assertEqual(place.master_path(), older)
        picked = self.nippou(f'''
            from nippou import config
            print(json.dumps({{"p": str(config._pick_source(Path({str(older.parent)!r}), "VC計算マスタ.sqlite3"))}}))
        ''')
        self.assertEqual(picked["p"], str(older))
        self.assertEqual(self.state()["master"]["source"], "db")

    def test_schema_versions_agree(self):
        seen = self.nippou('print(json.dumps({"v": db.SCHEMA_VERSION, "req": list(db.REQUIRED_TABLES)}, ensure_ascii=False))')
        self.assertEqual(seen["v"], db.SCHEMA_VERSION)
        self.assertEqual(seen["req"], list(db.REQUIRED_TABLES))


if __name__ == "__main__":
    unittest.main()
