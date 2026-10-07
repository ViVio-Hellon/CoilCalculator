"""要求1件を答える ── デスクトップ版とブラウザ版で**同じ関数**を通る

    デスクトップ版  画面 ─app://─▶ 外枠(Rust) ─標準入力─▶ bridge.py ─▶ handle()
    ブラウザ版      画面 ─http://127.0.0.1─▶ start_app.py(http.server)─▶ handle()

Flask は使いません(ラインPCの Python に追加のパッケージを入れられないため)。
経路が数本なので、振り分けは下の表だけで足ります。

    GET  /api/health          動いているか・版・どちらの版か
    GET  /api/spec            入力の範囲(数値の正は coilcalc/calc.py)
    POST /api/coil/calc       コイルの計算 → 画面に出す文字一式
    POST /api/plate/calc      平板の計算 → 画面に出す文字一式
    POST /api/heartbeat       画面が開いている知らせ(ブラウザ版の自動終了に使う)
    POST /api/shutdown        終了。**{"confirmed": true} のときだけ止まる**。無ければ 409 で確かめの文を返す
                              (ブラウザ版の「終了」もデスクトップ版の窓の × も、この同じ確かめを通る)
    POST /api/client-error    画面の JS のエラーを動作ログに残す
    GET|POST /api/vc/…        VC長さ計算(計算・早見表・設定・マスタの表。coilcalc/vc_api.py)
    GET  /…                   画面のファイル(ブラウザ版だけ。デスクトップ版は Rust が返す)

【答え方の約束】
    200  計算した / 範囲の外の欄があるので計算しなかった(`ok: false` と `invalid`)
         ── 打っている途中に範囲を外れるのはふつうのことなので、断りにしない
    400  本文の形が違う(JSON でない・fields が無い)
    403  よその画面からの要求(ブラウザ版の守り)
    409  終了の確かめがまだ(画面・外枠が利用者に訊いてから confirmed を付けて送り直す)
    404  そんな経路は無い
"""
from __future__ import annotations

import json
import mimetypes
import platform
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import unquote

from . import app_config, calc
from .vc import db as vc_db
from .vc_api import VcApi
from .logging_setup import get_logger

log = get_logger("coilcalc.web")

MODE_DESKTOP = "desktop"
MODE_BROWSER = "browser"

#: 終了の確かめ(文の正はここ1か所)。ブラウザ版の「終了」も、デスクトップ版の窓の × も、
#: これを利用者に見せて「終了する」を選んだときだけ confirmed を付けて送り直す。
#: 「やめる」・閉じる・答えが無い ときは送り直さない(= 止まらない)
QUIT_CONFIRM = {
    MODE_DESKTOP: "VC長さ・コイル平板 計算ツールを終了しますか?\n入力した値は保存されません。",
    MODE_BROWSER: "ブラウザ版を終了しますか?\n入力した値は保存されません。",
}
#: VC計算マスタへ書いている最中に終了を押したとき、確かめの文に足す
WRITING_NOTE = "いま VC計算マスタへ書いている最中です。少し待ってから終了してください。"

# 画面のファイルの種類。Windows はレジストリの関連付けで .js が text/plain に
# なっていることがあり、そのままだとブラウザがスクリプトを動かさない
_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".md": "text/plain; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}

#: 画面に付ける守り。スクリプトは同じ所からだけ(HTML の中のスクリプトは動かさない)。
#: 3D の図を印刷に入れるとき data: の画像を使う。Rust 側(`static_files.rs`)と同じ
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
       "object-src 'none'; base-uri 'self'; frame-ancestors 'self'")


@dataclass
class Request:
    method: str
    path: str
    query: str = ""
    headers: Dict[str, str] = field(default_factory=dict)   # 名前は小文字
    body: bytes = b""

    def header(self, name: str, default: str = "") -> str:
        return self.headers.get(name.lower(), default)


@dataclass
class Response:
    status: int
    headers: List[Tuple[str, str]]
    body: bytes


def json_response(status: int, data: Any) -> Response:
    body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
    return Response(status, [("Content-Type", "application/json; charset=utf-8"),
                             ("Cache-Control", "no-store")], body)


def error(status: int, code: str, message: str) -> Response:
    return json_response(status, {"ok": False, "error": {"code": code, "message": message}})


class App:
    """1つのプロセスに1つ。どちらの版で動いているか・終わり方・最後に画面が居た時刻を持つ。"""

    def __init__(self, mode: str, *, on_shutdown: Optional[Callable[[], None]] = None,
                 static_dir: Path = app_config.STATIC_DIR,
                 allowed_hosts: Tuple[str, ...] = ()) -> None:
        self.mode = mode
        self.conf = app_config.load()
        self.static_dir = Path(static_dir)
        self.allowed_hosts = tuple(h.lower() for h in allowed_hosts)
        self._on_shutdown = on_shutdown
        self._lock = threading.Lock()
        self.last_seen = time.monotonic()
        self.seen_page = False
        self.stopping = False
        self._answered: set = set()
        self.vc = VcApi(json_response, error)

    # ------------------------------------------------------------------
    def touch(self) -> None:
        with self._lock:
            self.last_seen = time.monotonic()
            self.seen_page = True

    def idle_seconds(self) -> float:
        with self._lock:
            return time.monotonic() - self.last_seen

    # ------------------------------------------------------------------
    def handle(self, req: Request) -> Response:
        try:
            denied = self._guard(req)
            if denied is not None:
                return denied
            if req.path.startswith("/api/"):
                return self._api(req)
            if req.method not in ("GET", "HEAD"):
                return error(405, "method", "この経路は読むだけです。")
            return self._static(req.path)
        except Exception as exc:                  # noqa: BLE001 - 1件の失敗で止めない
            log.exception("要求を処理できませんでした: %s %s", req.method, req.path)
            return error(500, "internal", f"内部エラー: {exc}")

    def _guard(self, req: Request) -> Optional[Response]:
        """ブラウザ版の守り。デスクトップ版は標準入出力(親子だけの通り道)なので要らない。

        - Host が自分(127.0.0.1:ポート)でなければ断る(DNS リバインディング対策)
        - 書く要求(POST)は、よその画面から来たら断る(Origin が自分でない)。
          さらに JSON でなければ断る ── よその画面が JSON を送るには事前の問い合わせが
          要り、こちらは答えないので、そもそも届かない
        """
        if self.mode != MODE_BROWSER:
            return None
        host = req.header("host").lower()
        if self.allowed_hosts and host not in self.allowed_hosts:
            return error(403, "bad_host", "このアドレスからは使えません。")
        if req.method == "POST":
            origin = req.header("origin").lower()
            if origin and origin not in tuple(f"http://{h}" for h in self.allowed_hosts):
                return error(403, "bad_origin", "よその画面からは使えません。")
            if not req.header("content-type").lower().startswith("application/json"):
                return error(400, "bad_type", "本文は JSON で送ってください。")
        return None

    # ------------------------------------------------------------------
    def _body(self, req: Request) -> Optional[Dict[str, Any]]:
        if not req.body:
            return {}
        try:
            data = json.loads(req.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _api(self, req: Request) -> Response:
        path, method = req.path, req.method
        if method == "GET" and path == "/api/health":
            # 版の表示(画面左上・操作説明書)に使う。外枠(Rust)の版は外枠が見出しに足す
            return json_response(200, {"ok": True, "app": self.conf.get("display_name"),
                                       "version": self.conf.get("version"), "mode": self.mode,
                                       "python": platform.python_version(),
                                       "heartbeat_seconds": self.conf["browser"]["heartbeat_seconds"]})
        if method == "GET" and path == "/api/spec":
            return json_response(200, calc.spec())
        if path.startswith("/api/vc/"):
            self.touch()
            answer = self.vc.handle(method, path, req.query,
                                    self._body(req) if method == "POST" else {})
            if answer is None:
                return error(404, "not_found", "そんな経路はありません。")
            if path == "/api/vc/state" and answer.status == 200 and "vc" not in self._answered:
                # 画面 → (外枠)→ Python → 画面 が1周した印(試験 desktop_smoke.py が見る)。
                # 最初に開く面は「計算」なので、品種の一覧を返したときに出す
                self._answered.add("vc")
                log.info("最初の計算を返しました: vc (%s)", self.mode)
            return answer
        if method != "POST":
            return error(404, "not_found", "そんな経路はありません。")

        body = self._body(req)
        if body is None:
            return error(400, "bad_json", "本文が JSON ではありません。")
        if path in ("/api/coil/calc", "/api/plate/calc"):
            fields = body.get("fields")
            if not isinstance(fields, dict):
                return error(400, "bad_fields", "fields の形が違います。")
            self.touch()
            view = calc.coil_view if path == "/api/coil/calc" else calc.plate_view
            body = view(fields)
            if body["shape"] not in self._answered:
                # 画面 → (外枠)→ Python → 画面 が1周した印(試験 desktop_smoke.py が見る)
                self._answered.add(body["shape"])
                log.info("最初の計算を返しました: %s (%s)", body["shape"], self.mode)
            return json_response(200, body)
        if path == "/api/heartbeat":
            self.touch()
            return json_response(200, {"ok": True})
        if path == "/api/shutdown":
            if body.get("confirmed") is not True:
                # 確かめがまだ。**止めずに**訊く文を返す(true 以外 ── "yes" や 1 も止めない)
                message = QUIT_CONFIRM.get(self.mode, QUIT_CONFIRM[MODE_BROWSER])
                if vc_db.writing_now():
                    message += "\n\n" + WRITING_NOTE
                return json_response(409, {
                    "ok": False,
                    "confirm": {"title": self.conf.get("display_name"),
                                "message": message,
                                "yes": "終了する", "no": "やめる"},
                    "error": {"code": "need_confirm", "message": "終了してよいか確かめてください。"}})
            log.info("終了の要求を受けました(%s・確かめ済み)", self.mode)
            self.request_shutdown()
            return json_response(200, {"ok": True, "message": "終了します。"})
        if path == "/api/client-error":
            text = str(body.get("message", ""))[:2000]
            where = str(body.get("where", ""))[:200]
            log.warning("画面のエラー: %s (%s)", text, where)
            return json_response(200, {"ok": True})
        return error(404, "not_found", "そんな経路はありません。")

    def request_shutdown(self) -> None:
        with self._lock:
            if self.stopping:
                return
            self.stopping = True
        if self._on_shutdown is not None:
            # 答えを返してから止める(止める処理が答えを待たせない)
            threading.Timer(0.2, self._on_shutdown).start()

    # ------------------------------------------------------------------
    def _static(self, path: str) -> Response:
        """画面のファイル。**画面のフォルダの外は見せない。**"""
        rel = unquote(path.split("?", 1)[0]).lstrip("/") or "index.html"
        if "\\" in rel or "\x00" in rel:
            return error(404, "not_found", "ありません。")
        root = self.static_dir.resolve()
        target = (root / rel).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return error(404, "not_found", "ありません。")
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            return error(404, "not_found", "ありません。")
        ctype = _TYPES.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] \
            or "application/octet-stream"
        headers = [("Content-Type", ctype), ("Cache-Control", "no-cache"),
                   ("X-Content-Type-Options", "nosniff")]
        if ctype.startswith("text/html"):
            headers.append(("Content-Security-Policy", CSP))
        return Response(200, headers, target.read_bytes())
