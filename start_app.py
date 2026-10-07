"""ブラウザ版の起動(予備)── `Start.vbs` / `start.bat` から

デスクトップ版(CoilCalculator.exe)が使えないときの予備です。127.0.0.1 の
ポートで待ち受け、既定のブラウザで画面を開きます。計算は**デスクトップ版と同じ**
`coilcalc.web` を通ります(違うのは要求の届き方だけ)。

    Start.vbs ─▶ start_app.py ─▶ 錠(デスクトップ版と取り合う)─▶ http.server ─▶ ブラウザ

【ブラウザ版とデスクトップ版は同時に動かない】(`coilcalc/instance_lock.py`)
    デスクトップ版が開いていたら、ここは「デスクトップ版が開いています」と出して終わる。
    ブラウザ版が先に動いていたら、新しく起動せずにその画面をブラウザで開く。
    作業フォルダが壊れていても止めない(錠を一時フォルダに置く。そこも駄目なら排他無しで動く)。

【終わり方】
    - 画面の「終了」/ stop.bat
    - 画面(タブ)がすべて閉じられて、しばらく知らせが来なくなったとき(自動で終わる)。
      ブラウザ版が残っているとデスクトップ版が開けないので、置き去りにしない

**標準ライブラリだけで動きます**(Flask・waitress は要りません)。

    python start_app.py            起動してブラウザで開く
    python start_app.py --check    動かせるかだけ確かめて終わる
    python start_app.py --no-browser   ブラウザを開かない(試験・診断用)
"""
from __future__ import annotations

import argparse
import os
import socket
import socketserver
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

APP_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_ROOT))

from coilcalc import app_config, instance_lock, logging_setup, web  # noqa: E402

MIN_PYTHON = (3, 8)

#: 終わったときの番号(stop.bat・試験が見る)
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_OTHER_RUNNING = 3

log = logging_setup.get_logger("start_app")


class StartupError(Exception):
    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


# ==================================================================
# 知らせる(コンソールが無い pythonw でも見えるように)
# ==================================================================
def notify(message: str, *, title: str = "VC長さ・コイル平板 計算ツール", error: bool = False) -> None:
    """利用者に知らせる。Windows ではメッセージボックス、ほかは標準エラー。

    `Start.vbs` は pythonw(コンソール無し)で起動するので、print だけでは誰にも見えない。
    """
    print(message, file=sys.stderr)
    if os.name != "nt" or os.environ.get("COIL_TOOL_QUIET") == "1":
        return
    try:
        import ctypes
        MB_ICONWARNING, MB_ICONERROR, MB_SETFOREGROUND = 0x30, 0x10, 0x10000
        flags = (MB_ICONERROR if error else MB_ICONWARNING) | MB_SETFOREGROUND
        ctypes.windll.user32.MessageBoxW(None, message, title, flags)
    except Exception:                             # noqa: BLE001 - 知らせられなくても進む
        pass


# ==================================================================
# 待ち受け
# ==================================================================
class Handler(BaseHTTPRequestHandler):
    """http.server の要求を `coilcalc.web.App` に渡すだけ。"""

    server_version = "CoilCalculator"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    app: web.App = None  # type: ignore[assignment]

    def _answer(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 4 * 1024 * 1024:
            self.send_error(413)
            return
        body = self.rfile.read(length) if length > 0 else b""
        path, _, query = self.path.partition("?")
        req = web.Request(method=self.command, path=path, query=query,
                          headers={k.lower(): v for k, v in self.headers.items()}, body=body)
        res = self.app.handle(req)
        self.send_response(res.status)
        for k, v in res.headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(res.body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(res.body)

    do_GET = do_POST = do_HEAD = _answer

    def log_message(self, fmt: str, *args) -> None:   # 標準エラーを汚さない
        if not str(self.path).startswith("/api/heartbeat"):
            log.debug("%s - %s", self.address_string(), fmt % args)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # Windows の SO_REUSEADDR は「使われているポートにも割り込める」意味になる。
    # 2つのブラウザ版が同じポートに座らないよう、Windows では独り占めを頼む
    allow_reuse_address = os.name != "nt"

    def server_bind(self) -> None:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        # HTTPServer.server_bind は socket.getfqdn を呼ぶ。社内の名前解決が遅いと
        # それだけで数秒待たされるので、TCPServer の分だけにする
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name, self.server_port = host, port


def bind(host: str, port: int, retry: int) -> ThreadingHTTPServer:
    """決めたポートから順に試す。**同じポートを使えば、ブラウザが覚えた背景の色などが残る**
    (ブラウザはポートごとに覚える)ので、空いていれば毎回同じポートになる。"""
    last: Optional[OSError] = None
    for candidate in range(port, port + max(1, retry)):
        try:
            return Server((host, candidate), Handler)
        except OSError as exc:
            last = exc
    raise StartupError(f"待ち受けるポートが空いていません({port}〜{port + retry - 1}): {last}",
                       "ほかのアプリがポートを使っています。デスクトップ版(CoilCalculator.exe)なら"
                       "ポートを使いません。")


# ==================================================================
# 起動
# ==================================================================
def run_checks() -> None:
    if sys.version_info < MIN_PYTHON:
        raise StartupError(f"Python {sys.version.split()[0]} は古すぎます",
                           "Python 3.8 以上を入れてください。")
    for rel in ("index.html", "vc/vc.js", "coil/index.html"):
        page = app_config.STATIC_DIR / rel
        if not page.is_file():
            raise StartupError(f"画面のファイルがありません: {page}",
                               "アプリのフォルダを丸ごとコピーし直してください。")
    schema = app_config.APP_ROOT / "coilcalc" / "vc" / "schema.sql"
    if not schema.is_file():
        raise StartupError(f"VC計算マスタの表の形がありません: {schema}",
                           "アプリのフォルダを丸ごとコピーし直してください。")


def other_running(runtime: Path, *, open_browser: bool) -> int:
    """錠を取れなかった。**後から開いたこちらが止まる。**"""
    owner = instance_lock.read_owner(runtime)
    kind = (owner or {}).get("kind")
    if kind == instance_lock.KIND_BROWSER and owner.get("url"):
        # ブラウザ版どうし: 新しく起動せず、動いている画面を開く(タブを閉じてしまった人向け)
        log.info("ブラウザ版はもう動いています。その画面を開きます: %s", owner["url"])
        print(f"ブラウザ版はもう動いています: {owner['url']}", file=sys.stderr)
        if open_browser:
            webbrowser.open(owner["url"])
        return EXIT_OK
    what = instance_lock.describe(owner)
    log.warning("%s が動いているので、ブラウザ版は起動しません", what)
    if kind == instance_lock.KIND_DESKTOP:
        message = ("デスクトップ版(CoilCalculator.exe)が開いています。\n\n"
                   "ブラウザ版とデスクトップ版は同時に使えません。\n"
                   "デスクトップ版の窓をそのまま使うか、窓を閉じてからブラウザ版を開いてください。")
    else:
        message = (f"{what}が動いています。\n\n"
                   "ブラウザ版とデスクトップ版は同時に使えません。閉じてから開き直してください。")
    notify(message)
    return EXIT_OTHER_RUNNING


def serve(*, open_browser: bool = True, port: Optional[int] = None) -> int:
    conf = app_config.load()
    status, lock, place = instance_lock.take(app_config.runtime_candidates(conf))
    if status == instance_lock.BUSY:
        return other_running(place, open_browser=open_browser)
    if status == instance_lock.UNUSABLE:
        # 作業フォルダも一時フォルダも使えない。**起動は止めない**(計算だけの道具で、
        # 2つ動いても壊れるデータが無い)。デスクトップ版との排他だけが効かない
        log.warning("錠を置ける場所がありません。デスクトップ版との排他無しで起動します")
    elif place != app_config.runtime_dir(conf):
        log.warning("作業フォルダが使えないので、錠を一時フォルダに置きました: %s", place)

    server = None
    try:
        host = conf["server"]["host"]
        server = bind(host, int(port or conf["server"]["port"]), int(conf["server"]["port_retry"]))
        bound = server.server_address[1]
        url = f"http://{host}:{bound}/"
        hosts = (f"{host}:{bound}", f"localhost:{bound}")

        stopped = threading.Event()
        app = web.App(web.MODE_BROWSER, on_shutdown=stopped.set, allowed_hosts=hosts)
        Handler.app = app
        if lock is not None:
            lock.write_owner(instance_lock.KIND_BROWSER, url=url, port=bound,
                             version=conf.get("version"))
        thread = threading.Thread(target=server.serve_forever, name="http", daemon=True)
        thread.start()
        log.info("ブラウザ版 %s を始めました: %s", conf.get("version"), url)
        print(f"ブラウザ版を始めました: {url}", file=sys.stderr)
        if open_browser:
            webbrowser.open(url)
        watch_idle(app, stopped, conf["browser"])
        log.info("ブラウザ版を終わります")
        return EXIT_OK
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if lock is not None:
            lock.release()


def watch_idle(app: web.App, stopped: threading.Event, browser: dict) -> None:
    """終了の要求か、画面が居なくなるまで待つ。

    画面は数秒ごとに知らせ(heartbeat)を送る。タブが全部閉じられて
    `idle_exit_seconds` 知らせが無ければ終わる。最初に画面が来るまでは
    `first_open_grace_seconds` 待つ(ブラウザの起動が遅い PC がある)。
    """
    idle = float(browser.get("idle_exit_seconds", 90))
    grace = float(browser.get("first_open_grace_seconds", 180))
    while not stopped.wait(1.0):
        limit = idle if app.seen_page else grace
        if limit > 0 and app.idle_seconds() > limit:
            log.info("画面から %.0f 秒知らせが無いので終わります", limit)
            return


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="VC長さ・コイル平板 計算ツール(ブラウザ版)")
    parser.add_argument("--check", action="store_true", help="動かせるかだけ確かめる")
    parser.add_argument("--no-browser", action="store_true", help="ブラウザを開かない")
    parser.add_argument("--port", type=int, default=None, help="待ち受けるポート(既定は config/app.json)")
    args = parser.parse_args(argv)

    conf = app_config.load()
    logging_setup.setup(app_config.log_dir(conf), to_stderr=args.check)
    try:
        run_checks()
        if args.check:
            print(f"OK: Python {sys.version.split()[0]} / {app_config.STATIC_DIR}", file=sys.stderr)
            return EXIT_OK
        # COIL_TOOL_NO_BROWSER=1: Start.vbs から起動するときも開かない(試験・CI。Start.vbs は引数を渡さない)
        no_browser = args.no_browser or os.environ.get("COIL_TOOL_NO_BROWSER") == "1"
        return serve(open_browser=not no_browser, port=args.port)
    except StartupError as exc:
        log.error("起動できません: %s / %s", exc, exc.hint)
        notify(f"起動できません。\n\n{exc}\n\n{exc.hint}", error=True)
        return EXIT_FAILED
    except (OSError, socket.error) as exc:
        log.exception("起動できません")
        notify(f"起動できません。\n\n{exc}", error=True)
        return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
