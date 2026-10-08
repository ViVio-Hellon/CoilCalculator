#!/usr/bin/env python3
"""デスクトップ版(exe)を本当に起動して確かめる(GitHub Actions の Windows でも流す)

確かめること:
    1. 窓の画面が開き、**計算が Python から返ってくる**
       ── 動作ログに「最初の計算を返しました: vc (desktop)」が出る(最初の面は VC長さ計算)
          (WebView → 外枠(Rust)→ Python → 外枠 → WebView が1周した証拠)
    2. **どのプロセスもポートで待ち受けていない**(exe・Python・WebView の子プロセス)
    3. デスクトップ版が開いている間は、ブラウザ版を開いても**ブラウザ版が止まる**(終了コード 3)。
       デスクトップ版をもう1つ開いても、新しくは起動しない(先の窓はそのまま)
    4. exe を止めると Python も終わる(取り残さない)
    5. ブラウザ版が動いている間は、デスクトップ版を開いても**デスクトップ版が止まる**(終了コード 3)
    6. 窓の × は「終了」と同じ確かめを通る: 「やめる」なら動いたまま、「終了する」なら Python ごと終わる
       (答えは COIL_TOOL_CLOSE_ANSWER で決める。決めないと本物の確かめが出る)
    7. 動いている間に、アプリのフォルダの設定・画面のファイル・.py を差し替えられる(掴んだままにしない)
    8. 作業フォルダが壊れていても起動し、ブラウザ版との排他も保つ(錠を一時フォルダに置く)
    9. 動いている間に、VC計算マスタ(読み終えたあと)を差し替えられる(写してから読むので掴まない)
   10. stop.bat(業務ツール統合ランチャーが止めるときに使う)で、**確かめを出さずに**終わる
       (×の確かめは「やめる」にしておく ── 確かめを通ったら終わらないので分かる)
       LAUNCHER_REPO があれば(Windows)、ランチャー本体のコードで「stop.bat で止める」も確かめる

使い方:
    python scripts/desktop_smoke.py --exe src-tauri/target/release/CoilCalculator.exe
    (Linux では DISPLAY が要る。例: xvfb-run python scripts/desktop_smoke.py --exe ...)

作業用のフォルダ(錠・ログ)は一時フォルダに作る。本番の領域は触らない。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = os.name == "nt"
EXIT_OTHER_RUNNING = 3


def children(pid: int) -> list:
    """pid の子孫(孫も)。"""
    if WINDOWS:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId) $($_.ParentProcessId)\" }"],
            capture_output=True, text=True).stdout
        pairs = [tuple(map(int, line.split())) for line in out.splitlines() if line.strip()]
    else:
        pairs = []
        for name in os.listdir("/proc"):
            if name.isdigit():
                try:
                    stat = Path(f"/proc/{name}/stat").read_text()
                    pairs.append((int(name), int(stat.rsplit(")", 1)[1].split()[1])))
                except (OSError, ValueError, IndexError):
                    pass
    found, frontier = [], [pid]
    while frontier:
        parent = frontier.pop()
        for child, ppid in pairs:
            if ppid == parent and child not in found:
                found.append(child)
                frontier.append(child)
    return found


def listening_ports(pids: set) -> dict:
    """その pid たちが待ち受けている TCP ポート。"""
    result: dict = {}
    if WINDOWS:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
        out += subprocess.run(["netstat", "-ano", "-p", "TCPv6"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            cols = line.split()
            if len(cols) >= 5 and cols[3].upper() == "LISTENING" and cols[4].isdigit():
                pid = int(cols[4])
                if pid in pids:
                    result.setdefault(pid, []).append(int(cols[1].rsplit(":", 1)[1]))
        return result
    inodes: dict = {}
    for name in ("/proc/net/tcp", "/proc/net/tcp6"):
        if os.path.exists(name):
            for line in Path(name).read_text().splitlines()[1:]:
                cols = line.split()
                if cols[3] == "0A":
                    inodes[cols[9]] = int(cols[1].split(":")[1], 16)
    for pid in pids:
        try:
            fds = os.listdir(f"/proc/{pid}/fd")
        except OSError:
            continue
        for fd in fds:
            try:
                target = os.readlink(f"/proc/{pid}/fd/{fd}")
            except OSError:
                continue
            if target.startswith("socket:[") and target[8:-1] in inodes:
                result.setdefault(pid, []).append(inodes[target[8:-1]])
    return result


def alive(pid: int) -> bool:
    if WINDOWS:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"     # 終わって回収待ちのものは数えない


def request_close(pid: int) -> bool:
    """窓の × を押したのと同じ知らせを送る。送れたら True。

    Windows: taskkill(/F を付けない)= WM_CLOSE。Linux: WM_DELETE_WINDOW を X に送る
    (窓の管理をする道具の無い試験の画面でも × と同じになる。xdotool で窓を探す)。
    """
    if WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True)
        return True
    if not shutil.which("xdotool"):
        return False
    ids = subprocess.run(["xdotool", "search", "--pid", str(pid), "--name", "重量計算ツール v"],
                         capture_output=True, text=True).stdout.split()
    return bool(ids) and all(x11_close(int(w)) for w in ids)


def x11_close(window: int) -> bool:
    import ctypes
    import ctypes.util
    name = ctypes.util.find_library("X11")
    if not name:
        return False
    x = ctypes.cdll.LoadLibrary(name)
    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XInternAtom.restype = ctypes.c_ulong
    x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]

    class ClientMessage(ctypes.Structure):
        _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                    ("display", ctypes.c_void_p), ("window", ctypes.c_ulong), ("message_type", ctypes.c_ulong),
                    ("format", ctypes.c_int), ("data", ctypes.c_long * 5)]

    class XEvent(ctypes.Union):
        _fields_ = [("xclient", ClientMessage), ("pad", ctypes.c_long * 24)]

    x.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long, ctypes.POINTER(XEvent)]
    x.XFlush.argtypes = x.XCloseDisplay.argtypes = [ctypes.c_void_p]
    dpy = x.XOpenDisplay(None)
    if not dpy:
        return False
    ev = XEvent()
    ev.xclient.type = 33                                   # ClientMessage
    ev.xclient.window = window
    ev.xclient.message_type = x.XInternAtom(dpy, b"WM_PROTOCOLS", 0)
    ev.xclient.format = 32
    ev.xclient.data[0] = x.XInternAtom(dpy, b"WM_DELETE_WINDOW", 0)
    sent = x.XSendEvent(dpy, window, 0, 0, ctypes.byref(ev))
    x.XFlush(dpy)
    x.XCloseDisplay(dpy)
    return bool(sent)


def swap_files(targets) -> list:
    """ファイルを、同じ中身の新しいファイルで差し替える。できなかったものを返す。"""
    failed = []
    for target in targets:
        fresh = target.with_name(target.name + ".smoke")
        shutil.copy2(target, fresh)
        try:
            os.replace(str(fresh), str(target))
        except OSError as exc:
            failed.append(f"{target.name}: {exc}")
            fresh.unlink()
    return failed


def swap_app_files() -> list:
    """アプリのフォルダのファイルを、同じ中身の新しいファイルで差し替える。できなかったものを返す。"""
    failed = []
    for rel in ("config/app.json", "app/static/index.html", "app/static/coil/index.html",
                "app/static/coil/app-shell.js", "app/static/vc/vc.js", "coilcalc/vc_api.py",
                "app/static/vendor/three/three.min.js", "app/static/manual/img/coil-overview.jpg",
                "bridge.py", "coilcalc/web.py", "coilcalc/calc.py"):
        target = ROOT / rel
        fresh = target.with_name(target.name + ".smoke")
        shutil.copy2(target, fresh)
        try:
            os.replace(str(fresh), str(target))
        except OSError as exc:
            failed.append(f"{rel}: {exc}")
            fresh.unlink()
    return failed


def log_text(work: Path) -> str:
    path = work / "local" / "logs" / "coilcalc.log"
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def wait_for(predicate, timeout: float, step: float = 0.3) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


def stop(app: subprocess.Popen) -> None:
    if WINDOWS:
        subprocess.run(["taskkill", "/PID", str(app.pid)], capture_output=True)
        try:
            app.wait(10)
            return
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/PID", str(app.pid), "/T", "/F"], capture_output=True)
    else:
        app.terminate()
    try:
        app.wait(15)
    except subprocess.TimeoutExpired:
        app.kill()
        app.wait(5)


LAUNCHER_STOP = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from launcher.runtime_state import RunningTool
import process_manager
job = json.loads(sys.argv[2])
running = RunningTool(app_id="nlm.coil-calculator", ui_mode="app", start_command=job["exe"],
                      stop_command=job["stop"], stop_method="stop_bat", app_root=job["root"])
result = process_manager.stop(running, timeout=30)
print(json.dumps({"stopped": result.stopped, "method": result.method, "message": result.message},
                 ensure_ascii=False))
"""


def launcher_stop(repo: str, exe: Path, env: dict, work: Path) -> dict:
    """ランチャー本体の process_manager.stop で、アプリの窓の行(exe)を stop.bat で止める。"""
    job = {"exe": str(exe.resolve()), "stop": str(ROOT / "stop.bat"), "root": str(ROOT)}
    run_env = dict(env, BUSINESS_TOOLS_LAUNCHER_LOCAL_DIR=str(work / "launcher"))
    done = subprocess.run([sys.executable, "-c", LAUNCHER_STOP, repo, json.dumps(job)], cwd=repo,
                          env=run_env, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120)
    try:
        return json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": (done.stdout + done.stderr)[-1500:]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True)
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="coil_desktop_smoke_"))
    # 一時フォルダも試験用に分ける(作業フォルダが壊れたときの錠の予備の場所)
    (work / "temp").mkdir()
    env = dict(os.environ, COIL_TOOL_ROOT=str(ROOT), COIL_TOOL_LOCAL_DIR=str(work / "local"),
               COIL_TOOL_QUIET="1", COIL_TOOL_CLOSE_ANSWER="yes", PYTHONIOENCODING="utf-8",
               TEMP=str(work / "temp"), TMP=str(work / "temp"))
    if os.environ.get("SMOKE_PYTHON"):
        env["COIL_TOOL_PYTHON"] = os.environ["SMOKE_PYTHON"]
    browser_cmd = [sys.executable, str(ROOT / "start_app.py"), "--no-browser", "--port", "18741"]
    ok = True

    def check(cond: bool, good: str, bad: str) -> None:
        nonlocal ok
        print(("[OK] " + good) if cond else ("[NG] " + bad), flush=True)
        ok &= cond

    def launch(launch_env: dict) -> tuple:
        """exe を起動し、この起動で最初の計算が返るまで待つ。(プロセス, 返ったか)"""
        since = len(log_text(work))
        proc = subprocess.Popen([args.exe], env=launch_env, cwd=str(ROOT))
        ready = wait_for(lambda: "最初の計算を返しました: vc (desktop)" in log_text(work)[since:]
                         or proc.poll() is not None, args.timeout, 0.5)
        return proc, ready and proc.poll() is None

    def force_stop(proc: subprocess.Popen) -> None:
        if WINDOWS:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        else:
            proc.kill()
        proc.wait(15)

    # ---- 1〜4: デスクトップ版を開く -------------------------------------------
    started = time.monotonic()
    app, seen = launch(env)
    print(f"起動しました: pid={app.pid} 作業={work}", flush=True)
    check(seen, f"計算が Python から返ってきました({time.monotonic() - started:.1f}秒)",
          f"時間内に計算が返りませんでした(exe の終了コード {app.poll()})。ログ:\n{log_text(work)[-3000:]}")

    kids = children(app.pid)
    python_kids = [p for p in kids if alive(p)]
    check(bool(python_kids), f"子プロセス: {python_kids}", "Python が起動していません")
    ports = listening_ports({app.pid, *kids})
    check(not ports, "どのプロセスもポートで待ち受けていません", f"待ち受けているポートがあります: {ports}")

    other = subprocess.run(browser_cmd, env=env, cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
    check(other.returncode == EXIT_OTHER_RUNNING and "デスクトップ版" in other.stderr,
          "デスクトップ版が開いている間は、ブラウザ版が止まりました",
          f"ブラウザ版が止まりませんでした(終了コード {other.returncode}): {other.stderr[-500:]}")

    twin = subprocess.run([args.exe], env=env, cwd=str(ROOT), capture_output=True, timeout=60)
    check(twin.returncode == 0 and app.poll() is None,
          "デスクトップ版をもう1つ開いても、新しくは起動しませんでした(先の窓はそのまま)",
          f"2つ目のデスクトップ版の終わり方が違います(終了コード {twin.returncode}、先の exe {app.poll()})")

    # 7. 掴んだままにしない(Windows では、開いたままのファイルは差し替えられない)
    failed = swap_app_files()
    check(not failed, "動いている間に、設定・画面のファイル・.py を差し替えられました(掴んだままにしていない)",
          f"差し替えられないファイルがあります(掴んだまま): {failed}")

    # 9. VC計算マスタを掴んだままにしない(最初の面で読んだ。共有に置けば、ほかの人が差し替える)
    master = work / "local" / "master" / "VC計算マスタ.sqlite3"
    made = wait_for(master.exists, 15)
    check(made, f"VC計算マスタを初期値で作りました({master})",
          f"VC計算マスタができていません({master})")
    if made:
        failed = swap_files([master])
        check(not failed, "動いている間に、VC計算マスタを差し替えられました(写してから読む・掴まない)",
              f"VC計算マスタを差し替えられません(掴んだまま): {failed}")

    # 6. 窓の ×(「終了する」と答える)
    if request_close(app.pid):
        try:
            app.wait(20)
        except subprocess.TimeoutExpired:
            pass
        check(app.poll() is not None, "窓の × →「終了する」で、デスクトップ版が終わりました",
              "窓の × →「終了する」でも終わりません")
    else:
        print("[--] この画面では × を送れないので、止めて確かめます(xdotool が無い)", flush=True)
    stop(app)
    gone = wait_for(lambda: not any(alive(p) for p in kids), 15)
    check(gone, "exe が終わったら Python も終わりました",
          f"取り残されたプロセスがあります: {[p for p in kids if alive(p)]}")

    # 6. 窓の ×(「やめる」と答える)→ 動いたまま
    hold, ready = launch(dict(env, COIL_TOOL_CLOSE_ANSWER="no"))
    check(ready, "もう一度起動しました(「やめる」の確かめ用)", "もう一度起動できませんでした")
    if ready and request_close(hold.pid):
        time.sleep(4)
        hold_kids = [p for p in children(hold.pid) if alive(p)]
        check(hold.poll() is None and bool(hold_kids),
              "窓の × →「やめる」で、デスクトップ版も Python も動いたままでした(勝手に「はい」にならない)",
              f"「やめる」なのに終わりました(exe {hold.poll()}、Python {hold_kids})")
    force_stop(hold)

    # 8. 作業フォルダが壊れている(runtime がフォルダでなくファイル)
    broken = work / "broken"
    (broken / "local").mkdir(parents=True)
    (broken / "local" / "runtime").write_text("garbage", encoding="utf-8")
    broken_env = dict(env, COIL_TOOL_LOCAL_DIR=str(broken / "local"))
    since_work = work
    work = broken                                # ログはこちらの作業フォルダ(broken/local/logs)に出る
    damaged, ready = launch(broken_env)
    check(ready, "作業フォルダが壊れていても、デスクトップ版は起動して計算が返りました",
          f"作業フォルダが壊れていると起動しません(終了コード {damaged.poll()})")
    spare = Path(broken_env["TEMP"]) / "CoilCalculator" / "runtime" / "instance.json"
    check(spare.exists(), "錠と持ち主の印を一時フォルダに置きました", f"一時フォルダに印がありません: {spare}")
    refused = subprocess.run(browser_cmd, env=broken_env, cwd=str(ROOT), capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60)
    check(refused.returncode == EXIT_OTHER_RUNNING,
          "作業フォルダが壊れていても、ブラウザ版との排他は保たれました",
          f"作業フォルダが壊れているとブラウザ版が止まりません(終了コード {refused.returncode})")
    stop(damaged)
    work = since_work

    # ---- 10: stop.bat(ランチャーからの停止)---------------------------------------
    quiet_env = dict(env, COIL_TOOL_CLOSE_ANSWER="no")
    target, ready = launch(quiet_env)
    check(ready, "もう一度起動しました(stop.bat の確かめ用)", "もう一度起動できませんでした")
    if ready:
        target_kids = children(target.pid)
        stop_cmd = (["cmd", "/c", str(ROOT / "stop.bat")] if WINDOWS
                    else [sys.executable, str(ROOT / "process_manager.py")])
        done = subprocess.run(stop_cmd, env=quiet_env, cwd=str(ROOT), stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=90)
        try:
            target.wait(20)
        except subprocess.TimeoutExpired:
            pass
        check(done.returncode == 0 and target.poll() is not None,
              "stop.bat で、確かめを出さずにデスクトップ版が終わりました",
              f"stop.bat で終わりません(stop.bat {done.returncode}、exe {target.poll()}): "
              + (done.stdout + done.stderr).decode("cp932" if WINDOWS else "utf-8", "replace")[-800:])
        gone = wait_for(lambda: not any(alive(p) for p in target_kids), 15)
        check(gone, "stop.bat のあと Python も終わりました",
              f"取り残されたプロセスがあります: {[p for p in target_kids if alive(p)]}")
    if target.poll() is None:
        force_stop(target)

    launcher_repo = os.environ.get("LAUNCHER_REPO", "")
    if WINDOWS and launcher_repo and (Path(launcher_repo) / "launcher").is_dir():
        target, ready = launch(quiet_env)
        check(ready, "もう一度起動しました(ランチャーからの停止の確かめ用)", "もう一度起動できませんでした")
        if ready:
            got = launcher_stop(launcher_repo, Path(args.exe), quiet_env, work)
            try:
                target.wait(20)
            except subprocess.TimeoutExpired:
                pass
            check(got.get("stopped") is True and target.poll() is not None,
                  f"ランチャー本体のコードで、デスクトップ版を止められました({got.get('method')})",
                  f"ランチャーから止められません: {got}")
        if target.poll() is None:
            force_stop(target)

    # ---- 5: ブラウザ版が先に動いているとき -------------------------------------
    browser = subprocess.Popen(browser_cmd, env=env, cwd=str(ROOT),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        up = wait_for(lambda: "ブラウザ版 " in log_text(work) and "を始めました" in log_text(work), 30)
        check(up, "ブラウザ版を起動しました", "ブラウザ版が起動しませんでした")
        second = subprocess.run([args.exe], env=env, cwd=str(ROOT), capture_output=True, timeout=60)
        check(second.returncode == EXIT_OTHER_RUNNING,
              "ブラウザ版が動いている間は、デスクトップ版が止まりました",
              f"デスクトップ版が止まりませんでした(終了コード {second.returncode})")
    finally:
        subprocess.run([sys.executable, str(ROOT / "process_manager.py")], env=env, cwd=str(ROOT),
                       capture_output=True, timeout=60)
        try:
            browser.wait(15)
        except subprocess.TimeoutExpired:
            browser.kill()

    print("すべて確かめました" if ok else "確かめられなかったことがあります", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
