"""VC長さ計算の経路(日報管理ツール `app/routes/vc.py` の移植。Flask を使わない形)

    GET  /api/vc/state                品種・定尺・マスタの状態
    POST /api/vc/select               品種を選んだ(VBA `List選択`)
    POST /api/vc/inside               内径の選択肢を押した(`Big_Click` / `Small_Click`)
    POST /api/vc/run                  計算(`CommandButton1_Click`)
    GET  /api/vc/quick                早見表(`UFquick`)
    GET  /api/vc/settings             設定の面(置き場所・どの名前を読んでいるか・早見表の品種・鍵)

管理者(鍵を開けてあるか、その場の管理者パスワード):

    POST /api/vc/unlock               鍵を開ける {enable: true, password} / 閉める {enable: false}
    POST /api/vc/place                マスタの置き場所を変える {dir, password}(空 = 既定に戻す)
    POST /api/vc/admin-password       管理者パスワードを変える {current, new, confirm} / 戻す {current, reset: true}
    POST /api/vc/quick-grid           早見表のマスをまとめて作る
    POST /api/vc/quick-block          早見表に品種(枠)を足す
    POST /api/vc/quick-block/delete   枠をマスごと消す
    POST /api/vc/quick-block/source   長さの出し方(式 / 固定値)を変える
    POST /api/vc/quick-cells/delete   枠の中の行(内径)・列(肉厚)を消す
    POST /api/vc/product/delete       VC品種を、使っている枠・マス・内径の選択肢ごと消す
    GET  /api/vc/tables               マスタの表を見る ?table=&q=&sort=&dir=
    POST /api/vc/tables/save|add|delete  マスタの表を1行ずつ直す(鍵を開けてあるときだけ)

**判断はサーバ。** 画面は欄の文字を送り、返ってきた欄と結果を描くだけです。
断ったときも同じ形(状態一式)で返し、理由は `error.code` が運びます。

鍵は**このプロセスに1つ**(日報管理ツールの「鍵を開ける」と同じ役目)。ブラウザ版と
デスクトップ版は同時に動かないので、開いている画面は1つです。終了すれば閉じます。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import parse_qs

from . import admin_password, settings_store, source_db
from .logging_setup import get_logger
from .vc import grid, masters, place, tables
from .vc import view
from .vc.calc import Fields, calculate, select_product
from .vc.masters import Snapshot
from .vc.vba_compat import parse_number, vba_format_fixed

log = get_logger("coilcalc.vc_api")

Reply = Any          # web.Response(循環を避けて型だけ緩く)


class VcApi:
    """App が1つ持つ。鍵(管理者)の状態もここ。"""

    def __init__(self, json_response: Callable[[int, Any], Reply],
                 error: Callable[[int, str, str], Reply]) -> None:
        self._json = json_response
        self._error = error
        self.unlocked = False

    # ------------------------------------------------------------------
    def handle(self, method: str, path: str, query: str,
               body: Optional[Dict[str, Any]]) -> Optional[Reply]:
        """この経路でなければ None(呼ぶ側が 404 にする)。"""
        if not path.startswith("/api/vc/"):
            return None
        name = path[len("/api/vc/"):]
        if method == "GET":
            getter = {
                "state": lambda: self._json(200, {"state": view.state(masters.current())}),
                "quick": lambda: self._json(200, self._quick_body()),
                "settings": self._settings,
                "tables": lambda: self._tables(parse_qs(query or "")),
            }.get(name)
            return getter() if getter else None
        if method != "POST":
            return None
        if body is None:
            return self._error(400, "bad_json", "本文が JSON ではありません。")
        poster = {
            "select": self._select,
            "inside": self._inside,
            "run": self._run,
            "unlock": self._unlock,
            "place": self._place,
            "admin-password": self._admin_password,
            "quick-grid": self._quick_grid,
            "quick-block": self._quick_block_add,
            "quick-block/delete": self._quick_block_delete,
            "quick-block/source": self._quick_block_source,
            "quick-cells/delete": self._quick_cells_delete,
            "product/delete": self._product_delete,
            "tables/save": self._table_save,
            "tables/add": self._table_add,
            "tables/delete": self._table_delete,
        }.get(name)
        return poster(body) if poster else None

    # ------------------------------------------------------------------
    # 計算
    # ------------------------------------------------------------------
    @staticmethod
    def _fields(body: dict) -> Optional[Fields]:
        raw = body.get("fields")
        if raw is not None and not isinstance(raw, dict):
            return None
        return Fields.from_dict(raw or {})

    def _bad_fields(self) -> Reply:
        return self._error(400, "bad_request", "fields の形が違います。")

    def _reply(self, snap: Snapshot, *, fields: Fields, product: Optional[str],
               status: int = 200, **extra: Any) -> Reply:
        body = {"state": view.state(snap), "fields": fields.to_dict(), "product": product}
        body.update(extra)
        return self._json(status, body)

    def _select(self, body: dict) -> Reply:
        """品種を選んだ(`VCList_Click` → `List選択`)。"""
        fields = self._fields(body)
        if fields is None:
            return self._bad_fields()
        name = str(body.get("product") or "")
        snap = masters.current()
        product = snap.product(name)
        if product is None:
            return self._reply(snap, fields=fields, product=None, status=422, error={
                "code": view.REFUSE_NO_PRODUCT,
                "message": f"「{name}」はいまのマスタにありません。一覧を読み直しました。"})
        new = select_product(fields, vcatu=product.vcatu,
                             inside=None if product.chooses_inside else product.inside)
        return self._reply(snap, fields=new, product=product.name, cleared=True)

    def _inside(self, body: dict) -> Reply:
        """内径の選択肢を押した(`Big_Click` / `Small_Click`)。"""
        fields = self._fields(body)
        if fields is None:
            return self._bad_fields()
        name = str(body.get("product") or "")
        wanted = parse_number(str(body.get("inside") or ""))
        snap = masters.current()
        product = snap.product(name)
        choice = None
        if product is not None and wanted is not None:
            choice = next((c for c in product.choices
                           if vba_format_fixed(c.inside, 1) == vba_format_fixed(wanted, 1)), None)
        if choice is None:
            return self._reply(snap, fields=fields, product=product.name if product else None,
                               status=422, error={
                                   "code": view.REFUSE_NO_CHOICE,
                                   "message": "その内径はいまのマスタの選択肢にありません。"
                                              "一覧を読み直しました。"})
        fields.inside = vba_format_fixed(choice.inside, 1)
        return self._reply(snap, fields=fields, product=product.name,
                           choice=vba_format_fixed(choice.inside, 1))

    def _run(self, body: dict) -> Reply:
        """計算ボタン(`CommandButton1_Click`)。"""
        fields = self._fields(body)
        if fields is None:
            return self._bad_fields()
        snap = masters.current()
        result = calculate(fields, snap.sheets, reverse=snap.reverse_enabled())
        payload: Dict[str, Any] = {"result": result.to_dict()}
        status = 200
        if not result.ran:
            status = 422
            payload["error"] = {"code": result.reason, "message": result.message}
        product = str(body.get("product") or "") or None
        return self._reply(snap, fields=result.fields, product=product, status=status, **payload)

    # ------------------------------------------------------------------
    # 早見表・設定
    # ------------------------------------------------------------------
    def _quick_body(self, message: str = "") -> Dict[str, Any]:
        snap = masters.current()
        body = view.quick(snap)
        body["grid"] = {"can_edit": self.unlocked, "blocks": [], "products": [],
                        "message": message}
        if snap.source == "db":
            try:
                body["grid"]["blocks"] = grid.quick_blocks(masters.master_path())
                body["grid"]["products"] = grid.products(masters.master_path())
            except Exception as exc:              # noqa: BLE001 - 表は出す
                log.warning("早見表の枠の一覧を読めませんでした: %s", exc)
        return body

    def _key_view(self) -> Dict[str, Any]:
        origin = admin_password.origin()
        return {"unlocked": self.unlocked, "password_origin": origin,
                "password_origin_label": {
                    "terminal": "この端末で変えたパスワード",
                    "site": "配布のときに決めたパスワード",
                    "default": "既定のパスワード(日報管理ツールと同じ)"}.get(origin, origin)}

    def _settings(self) -> Reply:
        body = self._quick_body()
        return self._json(200, {"place": view.place_view(), "grid": body["grid"],
                                "master": body["master"], "key": self._key_view(),
                                "tones": grid.tones()})

    def _need_key(self, body: dict, what: str) -> Optional[Reply]:
        if self.unlocked or admin_password.verify(str(body.get("password", ""))):
            return None
        return self._error(403, "need_password",
                           f"{what}には管理者パスワードが要ります"
                           "(設定の「鍵を開ける」でも開けられます)。")

    def _unlock(self, body: dict) -> Reply:
        if body.get("enable") is not True:
            self.unlocked = False
            log.info("マスタの鍵を閉めました")
            return self._json(200, {"ok": True, "unlocked": False,
                                    "message": "鍵を閉めました。"})
        if not admin_password.verify(str(body.get("password", ""))):
            log.warning("マスタの鍵を開けられませんでした(パスワードが違う)")
            return self._error(403, "wrong_password", "管理者パスワードが違います。")
        self.unlocked = True
        log.info("マスタの鍵を開けました")
        return self._json(200, {"ok": True, "unlocked": True,
                                "message": "鍵を開けました。終了するか「鍵を閉める」まで、"
                                           "マスタを直せます。"})

    def _place(self, body: dict) -> Reply:
        """マスタの置き場所を変える。**読みに行く相手そのものが変わる**ので鍵が要る。"""
        denied = self._need_key(body, "マスタの置き場所を変える")
        if denied is not None:
            return denied
        text = str(body.get("dir", "")).strip().strip('"')
        if text and not Path(text).is_absolute():
            return self._error(400, "bad_dir",
                               "フォルダは C:\\… や \\\\サーバ\\共有\\… のように、"
                               "始めから全部入れてください。")
        try:
            settings_store.save(settings_store.KEY_VC_MASTER_DIR, text)
        except OSError as exc:
            log.warning("置き場所を保存できません: %s", exc)
            return self._error(500, "save_failed",
                               f"この端末の設定に書けませんでした({settings_store.path()}): {exc}")
        source_db.forget()
        masters.reset()
        log.info("VC計算マスタの置き場所を変えました: %s", text or "(既定に戻す)")
        placed = view.place_view()
        message = ("VC計算マスタの置き場所を保存しました。" if text
                   else "VC計算マスタの置き場所を既定に戻しました。")
        if not placed["dir_exists"] and placed["origin"] != "default":
            message += " ただし、いまはそのフォルダに届きません(下の状態を見てください)。"
        return self._json(200, {"ok": True, "message": message, "place": placed})

    def _admin_password(self, body: dict) -> Reply:
        current = str(body.get("current", ""))
        if body.get("reset") is True:
            result = admin_password.reset(current)
        else:
            result = admin_password.change(current, str(body.get("new", "")),
                                           str(body.get("confirm", "")))
        if not result.ok:
            status = 403 if result.reason == admin_password.REFUSE_WRONG else 400
            return self._error(status, result.reason, result.message)
        return self._json(200, {"ok": True, "message": result.message, "key": self._key_view()})

    # ------------------------------------------------------------------
    # 早見表の品種を書く
    # ------------------------------------------------------------------
    def _grid_write(self, body: dict, what: str, run: Callable[[Path], Any]) -> Reply:
        denied = self._need_key(body, what)
        if denied is not None:
            return denied
        snap = masters.current()
        if snap.source != "db":
            reply = self._quick_body()
            reply["error"] = {"code": grid.REFUSE_NO_SOURCE,
                              "message": f"マスタに書けないので{what}ません。{snap.problem}"}
            return self._json(422, reply)
        result = run(masters.master_path())
        log.info("%s: %s", what, result.message[:120])
        reply = self._quick_body(result.message if result.ok else "")
        if result.ok:
            reply["message"] = result.message
            return self._json(200, reply)
        reply["error"] = {"code": result.reason, "message": result.message}
        status = {grid.REFUSE_BAD_VALUE: 400, grid.REFUSE_LOCKED: 409}.get(result.reason, 422)
        return self._json(status, reply)

    def _quick_grid(self, body: dict) -> Reply:
        return self._grid_write(body, "早見表のマスを足す", lambda path: grid.make_grid(
            path, str(body.get("block", "")),
            str(body.get("insides", "")), str(body.get("thicknesses", "")),
            length_mode=str(body.get("length", grid.LENGTH_NONE)),
            product=str(body.get("product", "")),
            vcatu_text=str(body.get("vcatu", "")),
            fill_empty=body.get("fill_empty", True) is not False,
            overwrite=body.get("overwrite") is True))

    def _quick_block_add(self, body: dict) -> Reply:
        return self._grid_write(body, "早見表に品種を足す", lambda path: grid.add_block(
            path, product=str(body.get("product", "")),
            new_product=str(body.get("new_product", "")),
            new_vcatu=str(body.get("new_vcatu", "")),
            new_vendor=str(body.get("new_vendor", "")),
            block_name=str(body.get("block", "")),
            formula=body.get("length", "formula") != "fixed",
            insides_text=str(body.get("insides", "")),
            thicknesses_text=str(body.get("thicknesses", "")),
            tone=str(body.get("tone", ""))))

    def _quick_block_delete(self, body: dict) -> Reply:
        return self._grid_write(body, "早見表の枠を消す",
                                lambda path: grid.delete_block(path, str(body.get("block", ""))))

    def _quick_block_source(self, body: dict) -> Reply:
        return self._grid_write(body, "長さの出し方を変える",
                                lambda path: grid.set_source(path, str(body.get("block", "")),
                                                             str(body.get("product", ""))))

    def _quick_cells_delete(self, body: dict) -> Reply:
        return self._grid_write(body, "早見表のマスを消す",
                                lambda path: grid.delete_cells(path, str(body.get("block", "")),
                                                               str(body.get("insides", "")),
                                                               str(body.get("thicknesses", ""))))

    def _product_delete(self, body: dict) -> Reply:
        return self._grid_write(body, "VC品種を消す",
                                lambda path: grid.delete_product(path, str(body.get("product", ""))))

    # ------------------------------------------------------------------
    # マスタの表
    # ------------------------------------------------------------------
    def _tables(self, args: Dict[str, Any]) -> Reply:
        def one(key: str) -> str:
            values = args.get(key) or [""]
            return str(values[0])

        snap = masters.current()                     # 無ければ作る(初めて開いたとき)
        page = tables.page(masters.master_path(), one("table"), query=one("q"),
                           sort=one("sort"), sort_dir=one("dir"), unlocked=self.unlocked)
        body = page.to_dict()
        body["master"] = view.master_view(snap)
        body["unlocked"] = self.unlocked
        return self._json(200, body)

    def _table_write(self, body: dict, run: Callable[[Path, str], tables.Result]) -> Reply:
        table = str(body.get("table", ""))
        masters.current()
        result = run(masters.master_path(), table)
        page = tables.page(masters.master_path(), table, query=str(body.get("q", "")),
                           unlocked=self.unlocked).to_dict()
        if result.ok:
            return self._json(200, {"ok": True, "message": result.message, "page": page})
        status = {tables.REFUSE_LOCKED: 403, tables.REFUSE_BAD_VALUE: 400,
                  tables.REFUSE_NO_TABLE: 404, tables.REFUSE_NO_ROW: 409,
                  tables.REFUSE_WRITE_FAILED: 409}.get(result.reason, 422)
        return self._json(status, {"ok": False, "page": page,
                                   "error": {"code": result.reason, "message": result.message}})

    def _values(self, body: dict) -> Dict[str, Any]:
        values = body.get("values")
        return values if isinstance(values, dict) else {}

    def _table_save(self, body: dict) -> Reply:
        return self._table_write(body, lambda path, table: tables.save_row(
            path, table, body.get("row"), self._values(body), unlocked=self.unlocked))

    def _table_add(self, body: dict) -> Reply:
        return self._table_write(body, lambda path, table: tables.add_row(
            path, table, self._values(body), unlocked=self.unlocked))

    def _table_delete(self, body: dict) -> Reply:
        return self._table_write(body, lambda path, table: tables.delete_row(
            path, table, body.get("row"), unlocked=self.unlocked))
