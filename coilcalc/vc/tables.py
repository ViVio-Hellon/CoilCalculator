"""マスタの表 ── VC計算マスタの表を見る・1行ずつ直す(管理者)

日報管理ツールでは「設定・管理者 → マスタ → マスタ管理」の「VC計算マスタ」が受け持って
いた部分(`nippou/master_admin.py` の VC 向けの決まり)を、VC計算マスタだけに絞って
写したものです。早見表の品種を1回で足す・消すのは `grid.py`(設定 → 早見表の品種)。

    見せない表    _メタ(版・更新番号。画面に出さない内部の値)
    見るだけの表  変更履歴(直すたびに自動で増える記録)
    値だけ直す表  アプリ設定(キーは読む側が名前で引くので、足す・消すはできない)

【1回の取引で】(日報管理ツールより1歩進めた所)
書く・変更履歴に残す・更新番号を上げる、を**1つの取引**でします(`db.writing`)。
あちらは元のファイルへ書いてから別の取引で履歴を残していたので、間で落ちると
「書いたのに履歴が無い・更新番号が上がらない(ほかの端末が古い写しで計算し続ける)」
が起こりえました。その日の最初の書き込みの前に控え(`backup/`)も取ります。

【読むとき】
写してから開きます(`source_db.open_source`)。共有のマスタを掴んだままにしない
── 掴んでいるあいだ、ほかの人がマスタを差し替えられないため。
"""
from __future__ import annotations

import sqlite3
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .. import source_db
from ..logging_setup import get_logger
from . import db, masters
from .db import quote

log = get_logger("vc.tables")

#: 行を指す隠しの列名。`rowid` をこの名前で持ち回る(業務の列と衝突しない名前)
ROW_KEY = "__行"
#: 一度に出す行数。**黙って切らない**(出さなかったぶんは数で言う)
ROW_LIMIT = 200

REFUSE_LOCKED = "locked"
REFUSE_NOT_EDITABLE = "not_editable"
REFUSE_BAD_VALUE = "bad_value"
REFUSE_NO_FILE = "no_file"
REFUSE_NO_TABLE = "no_table"
REFUSE_NO_ROW = "no_row"
REFUSE_WRITE_FAILED = "write_failed"

KIND_LABEL = {"int": "整数", "real": "小数", "text": "文字"}

HIDDEN_TABLES = frozenset({db.META})
VIEW_ONLY_TABLES: Dict[str, str] = {
    db.AUDIT: "マスタを直すたびに自動で増える記録です。直せません。",
}
FIXED_ROWS: Dict[str, str] = {
    "アプリ設定": "アプリ設定は決まったキーの行だけです。値を直してください"
                  "(足す・消すはできません)。",
}

#: 表の一覧に添える短い説明。**名前から読めないものだけ**(画面にそのまま出る字)
TABLE_NOTES: Dict[str, str] = {
    "VC品種": "VC長さ計算の品種一覧と、選んだときに入る VC厚・内径。"
              "内径選択=1 なら内径は選択肢から選ぶ",
    "VC内径選択肢": "内径を選ぶ品種の選択肢(大 95.0 / 小 87.0 など)",
    "枚数定尺": "定尺ごとの枚数を出すときの長さ(mm)",
    "早見表ブロック": "早見表の枠。計算品種の VC厚 で長さを式から出す(空なら固定値)。"
                      "足す・消す・式/固定値の切り替えは 設定 → 早見表の品種 が1回で済む",
    "早見表値": "早見表のマス(内径 × 肉厚)。固定値の枠は長さもここに入る。"
                "行・列ごと消すのは 設定 → 早見表の品種 で",
    "アプリ設定": "肉厚の逆算(1 / 0)・早見表の丸め(切り捨て / 四捨五入)",
    db.AUDIT: "VC計算マスタを直すたびに自動で1行増える記録",
}


@dataclass
class Column:
    name: str
    kind: str = "text"
    required: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "kind": self.kind,
                "kind_label": KIND_LABEL.get(self.kind, self.kind),
                "required": self.required}


@dataclass
class Page:
    table: str = ""
    tables: List[Dict[str, str]] = field(default_factory=list)
    columns: List[Dict[str, Any]] = field(default_factory=list)
    rows: List[Dict[str, str]] = field(default_factory=list)
    total: int = 0
    note: str = ""
    error: str = ""
    editable: bool = False
    can_add: bool = False
    can_delete: bool = False
    view_only_why: str = ""
    table_note: str = ""
    query: str = ""
    sort: str = ""
    sort_dir: str = "asc"
    row_key: str = ROW_KEY

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Result:
    ok: bool = True
    message: str = ""
    reason: str = ""


# ------------------------------------------------------------------
# 見る
# ------------------------------------------------------------------
def _kind_of(declared: str) -> str:
    upper = (declared or "").upper()
    if "INT" in upper:
        return "int"
    if "REAL" in upper or "FLOA" in upper or "DOUB" in upper:
        return "real"
    return "text"


def table_names(path: Path) -> List[str]:
    with source_db.open_source(path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'"
                            " AND name NOT LIKE 'sqlite_%' ORDER BY rowid").fetchall()
    return [str(r[0]) for r in rows if str(r[0]) not in HIDDEN_TABLES]


def columns(path: Path, table: str) -> List[Column]:
    """その表の、打ち込める列。**本当にある列だけ**(`PRAGMA table_info`)。

    INTEGER PRIMARY KEY は `rowid` の別名なので外す(打ち替えると別の行になる)。
    """
    with source_db.open_source(path) as conn:
        rows = conn.execute(f"PRAGMA table_info({quote(table)})").fetchall()
    out: List[Column] = []
    for row in rows:
        kind = _kind_of(str(row["type"]))
        if row["pk"] and kind == "int":
            continue
        out.append(Column(name=str(row["name"]), kind=kind,
                          required=bool(row["notnull"]) and row["dflt_value"] is None))
    return out


def _order(names: List[str], sort: str, sort_dir: str) -> Tuple[str, str]:
    """見出しを押したときの並び替え。数は数として並べ、空は最後。無い列なら既定の順。"""
    if sort and sort in names:
        direction = "DESC" if sort_dir == "desc" else "ASC"
        col = quote(sort)
        text = f"trim({col})"
        numeric = (f"(typeof({col}) IN ('integer', 'real') OR "
                   f"({text} GLOB '*[0-9]*' AND {text} NOT GLOB '*[^0-9.+-]*'))")
        return (f"ORDER BY CASE WHEN {col} IS NULL OR {text} = '' THEN 2"
                f" WHEN {numeric} THEN 0 ELSE 1 END,"
                f" CASE WHEN {numeric} THEN CAST({text} AS REAL) END {direction},"
                f" {col} {direction}, rowid ASC", sort)
    return "ORDER BY rowid ASC", ""


def _filter(names: List[str], query: str) -> Tuple[str, List[Any]]:
    text = (query or "").strip()
    if not text:
        return "", []
    conds = " OR ".join(f"CAST({quote(n)} AS TEXT) LIKE ?" for n in names)
    return f" WHERE ({conds})", [f"%{text}%"] * len(names)


def page(path: Path, table: str = "", *, query: str = "", sort: str = "",
         sort_dir: str = "asc", unlocked: bool = False, limit: int = ROW_LIMIT) -> Page:
    view = Page(query=query, sort_dir="desc" if sort_dir == "desc" else "asc")
    try:
        names = table_names(path)
    except source_db.SourceError as exc:
        view.error = str(exc)
        return view
    view.tables = [{"table": n, "note": TABLE_NOTES.get(n, "")} for n in names]
    if not names:
        view.error = "マスタに表がありません。"
        return view
    if table and table not in names:
        # 見せない表(_メタ)・もう無い表。**黙って別の表を出さない**
        view.error = f"{table} という表はありません。"
    view.table = table if table in names else names[0]
    view.table_note = TABLE_NOTES.get(view.table, "")
    if view.table in VIEW_ONLY_TABLES:
        view.view_only_why = VIEW_ONLY_TABLES[view.table]
    view.editable = unlocked and not view.view_only_why
    view.can_add = view.can_delete = view.editable and view.table not in FIXED_ROWS
    try:
        cols = columns(path, view.table)
        with source_db.open_source(path) as conn:
            all_names = [str(r["name"]) for r in
                         conn.execute(f"PRAGMA table_info({quote(view.table)})").fetchall()]
            where, params = _filter(all_names, query)
            order, view.sort = _order(all_names, sort, sort_dir)
            quoted = quote(view.table)
            view.total = int(conn.execute(f"SELECT COUNT(*) FROM {quoted}{where}",
                                          params).fetchone()[0])
            rows = conn.execute(f'SELECT rowid AS "{ROW_KEY}", * FROM {quoted}{where}'
                                f" {order} LIMIT ?", [*params, max(1, int(limit))]).fetchall()
    except (source_db.SourceError, sqlite3.Error) as exc:
        view.error = f"{view.table} を読めません: {exc}"
        return view
    view.columns = [c.to_dict() for c in cols]
    # 見るだけの列(INTEGER PRIMARY KEY)も一覧には出す
    shown = {c.name for c in cols}
    for name in all_names:
        if name not in shown:
            view.columns.insert(0, {"name": name, "kind": "int", "kind_label": "番号",
                                    "required": False, "readonly": True})
    view.rows = [{k: "" if row[k] is None else str(row[k]) for k in row.keys()} for row in rows]
    hidden = view.total - len(view.rows)
    if hidden > 0:
        head = "並び替えた上から " if view.sort else ""
        view.note = (f"{view.total}件のうち {head}{len(view.rows)}件を出しています"
                     f"(ほか {hidden}件)。絞り込むと目当ての行が出ます。")
    return view


# ------------------------------------------------------------------
# 直す
# ------------------------------------------------------------------
def _row_key(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return -1


def _ready(path: Path, table: str, unlocked: bool, *, adding_or_deleting: bool = False
           ) -> Optional[Result]:
    """書く前の関門。**表 → 鍵 → 届くか → 表が本当にあるか** の順。"""
    if table in HIDDEN_TABLES:
        return Result(False, f"{table} という表はありません。", REFUSE_NO_TABLE)
    if table in VIEW_ONLY_TABLES:
        return Result(False, VIEW_ONLY_TABLES[table], REFUSE_NOT_EDITABLE)
    if not unlocked:
        return Result(False, "マスタを直すには「鍵を開ける」で管理者パスワードを入れてください。",
                      REFUSE_LOCKED)
    if adding_or_deleting and table in FIXED_ROWS:
        return Result(False, FIXED_ROWS[table], REFUSE_NOT_EDITABLE)
    try:
        if not path.is_file():
            return Result(False, f"マスタが見つかりません: {path}", REFUSE_NO_FILE)
        names = table_names(path)
    except (OSError, source_db.SourceError) as exc:
        return Result(False, f"マスタに届きません: {exc}", REFUSE_NO_FILE)
    if table not in names:
        return Result(False, f"{table} という表はありません。", REFUSE_NO_TABLE)
    return None


def _clean(path: Path, table: str, values: Dict[str, Any], *,
           filling: bool) -> Tuple[Dict[str, Any], str]:
    """画面から来た値を書ける形に。書き換えは**送られてきた列だけ**を触る。"""
    out: Dict[str, Any] = {}
    for column in columns(path, table):
        if column.name not in values and not filling:
            continue
        raw = str(values.get(column.name, "") if values.get(column.name) is not None
                  else "").strip()
        if raw == "":
            if column.required:
                return {}, f"「{column.name}」は空にできません。"
            out[column.name] = None
            continue
        if column.kind in ("int", "real"):
            number = unicodedata.normalize("NFKC", raw).replace(",", "")
            try:
                out[column.name] = int(float(number)) if column.kind == "int" else float(number)
            except ValueError:
                return {}, f"「{column.name}」は{KIND_LABEL[column.kind]}で入れてください。"
        else:
            out[column.name] = raw
    return out, ""


def _problem(conn: sqlite3.Connection, table: str, clean: Dict[str, Any], *,
             row_key: Optional[int]) -> str:
    """表ごとの決まり。**決まった言葉しか効かない値**を見る(範囲は表の CHECK が守る)。

    違う言葉が入ると、読む側は黙って既定に倒す(直したのに効かない)。
    """
    from .seed import TONES

    if table == "アプリ設定":
        found = (conn.execute('SELECT "キー" FROM "アプリ設定" WHERE rowid = ?',
                              [row_key]).fetchone() if row_key is not None else None)
        key = str(found[0]) if found else ""
        if "キー" in clean and str(clean["キー"] or "") != key:
            return "アプリ設定のキーは変えられません(読む側が名前で引いています)。値を直してください。"
        if "値" in clean:
            value = unicodedata.normalize("NFKC", str(clean["値"] or "")).strip()
            if key == "肉厚の逆算" and value not in ("0", "1"):
                return "「肉厚の逆算」は 1(使う)か 0(使わない)で入れてください。"
            if key == "早見表の丸め" and value not in ("切り捨て", "四捨五入"):
                return "「早見表の丸め」は 切り捨て か 四捨五入 で入れてください。"
            clean["値"] = value
    if table == "早見表ブロック" and clean.get("枠色") is not None:
        tone = str(clean["枠色"]).strip()
        if tone not in TONES:
            return f"「枠色」は {' / '.join(TONES)} のどれかで入れてください。"
        clean["枠色"] = tone
    return ""


def _row(conn: sqlite3.Connection, table: str, row: int) -> Optional[Dict[str, Any]]:
    found = conn.execute(f"SELECT * FROM {quote(table)} WHERE rowid = ?", [row]).fetchone()
    return None if found is None else {k: found[k] for k in found.keys()}


def _write(path: Path, table: str, operation: str, work) -> Result:
    """書く・変更履歴・更新番号を1つの取引で。書けたら写しの控えと読んだ中身を捨てる。"""
    try:
        with db.writing(path) as conn:
            result = work(conn)
            if result.ok:
                db.bump_revision(conn)
            else:
                raise _Refused(result)
    except _Refused as refused:
        return refused.result
    except db.DbLocked as exc:
        return Result(False, str(exc), REFUSE_WRITE_FAILED)
    except sqlite3.IntegrityError as exc:
        return Result(False, db.integrity_message(operation, str(exc), table), REFUSE_BAD_VALUE)
    except (db.DbError, sqlite3.Error) as exc:
        log.warning("%s へ書けませんでした: %s", table, exc)
        return Result(False, f"書けませんでした: {exc}", REFUSE_WRITE_FAILED)
    finally:
        source_db.forget(path)
    masters.invalidate()
    return result


class _Refused(Exception):
    def __init__(self, result: Result) -> None:
        super().__init__(result.message)
        self.result = result


def save_row(path: Path, table: str, row_key: Any, values: Dict[str, Any], *,
             unlocked: bool = False) -> Result:
    refused = _ready(path, table, unlocked)
    if refused:
        return refused
    clean, problem = _clean(path, table, values or {}, filling=False)
    if problem:
        return Result(False, problem, REFUSE_BAD_VALUE)
    if not clean:
        return Result(False, "変える値がありません。", REFUSE_BAD_VALUE)
    row = _row_key(row_key)

    def work(conn: sqlite3.Connection) -> Result:
        problem = _problem(conn, table, clean, row_key=row)
        if problem:
            return Result(False, problem, REFUSE_BAD_VALUE)
        before = _row(conn, table, row)
        if before is None:
            return Result(False, "その行はもうありません。一覧を出し直してください。", REFUSE_NO_ROW)
        sets = ", ".join(f"{quote(k)} = ?" for k in clean)
        conn.execute(f"UPDATE {quote(table)} SET {sets} WHERE rowid = ?", [*clean.values(), row])
        db.record_change(conn, table, "更新", row,
                         {k: before.get(k) for k in clean}, clean)
        return Result(True, f"{table} の1行を直しました。")

    result = _write(path, table, "更新", work)
    if result.ok:
        log.info("マスタを直しました: %s rowid=%s %s", table, row, sorted(clean))
    return result


def add_row(path: Path, table: str, values: Dict[str, Any], *, unlocked: bool = False) -> Result:
    refused = _ready(path, table, unlocked, adding_or_deleting=True)
    if refused:
        return refused
    clean, problem = _clean(path, table, values or {}, filling=True)
    if problem:
        return Result(False, problem, REFUSE_BAD_VALUE)
    if all(value is None for value in clean.values()):
        return Result(False, "入れる値がありません。", REFUSE_BAD_VALUE)

    def work(conn: sqlite3.Connection) -> Result:
        problem = _problem(conn, table, clean, row_key=None)
        if problem:
            return Result(False, problem, REFUSE_BAD_VALUE)
        cols = ", ".join(quote(k) for k in clean)
        marks = ", ".join("?" for _ in clean)
        cur = conn.execute(f"INSERT INTO {quote(table)} ({cols}) VALUES ({marks})",
                           list(clean.values()))
        db.record_change(conn, table, "追加", int(cur.lastrowid or 0) or None, None, clean)
        return Result(True, f"{table} に1行足しました。")

    result = _write(path, table, "追加", work)
    if result.ok:
        log.info("マスタに足しました: %s %s", table, sorted(clean))
    return result


def delete_row(path: Path, table: str, row_key: Any, *, unlocked: bool = False) -> Result:
    refused = _ready(path, table, unlocked, adding_or_deleting=True)
    if refused:
        return refused
    row = _row_key(row_key)

    def work(conn: sqlite3.Connection) -> Result:
        before = _row(conn, table, row)
        if before is None:
            return Result(False, "その行はもうありません。一覧を出し直してください。", REFUSE_NO_ROW)
        conn.execute(f"DELETE FROM {quote(table)} WHERE rowid = ?", [row])
        db.record_change(conn, table, "削除", row, before, None)
        return Result(True, f"{table} の1行を消しました。")

    result = _write(path, table, "削除", work)
    if result.ok:
        log.info("マスタから消しました: %s rowid=%s", table, row)
    return result
