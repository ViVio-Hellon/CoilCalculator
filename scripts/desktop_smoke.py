#!/usr/bin/env python3
"""デスクトップ版(exe)を本当に起動して確かめる(GitHub Actions の Windows でも流す)

確かめること:
    1. 窓の画面が開き、**計算が Python から返ってくる**
       ── 動作ログに「最初の計算を返しました: coil (desktop)」が出る
          (WebView → 外枠(Rust)→ Python → 外枠 → WebView が1周した証拠)
    2. **どのプロセスもポートで待ち受けていない**(exe・Python・WebView の子プロセス)
    3. デスクトップ版が開いている間は、ブラウザ版を開いても**ブラウザ版が止まる**(終了コード 3)。
       デスクトップ版をもう1つ開いても、新しくは起動しない(先の窓はそのまま)
    4. exe を止めると Python も終わる(取り残さない)
    5. ブラウザ版が動いている間は、デスクトップ版を開いても**デスクトップ版が止まる**(終了コード 3)

使い方:
    python scripts/desktop_smoke.py --exe src-tauri/target/release/CoilCalculator.exe
    (Linux では DISPLAY が要る。例: xvfb-run python scripts/desktop_smoke.py --exe ...)

作業用のフォルダ(錠・ログ)は一時フォルダに作る。本番の領域は触らない。
"""
from __future__ import annotations

import argparse
import os
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True)
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="coil_desktop_smoke_"))
    env = dict(os.environ, COIL_TOOL_ROOT=str(ROOT), COIL_TOOL_LOCAL_DIR=str(work / "local"),
               COIL_TOOL_QUIET="1", PYTHONIOENCODING="utf-8")
    if os.environ.get("SMOKE_PYTHON"):
        env["COIL_TOOL_PYTHON"] = os.environ["SMOKE_PYTHON"]
    browser_cmd = [sys.executable, str(ROOT / "start_app.py"), "--no-browser", "--port", "18741"]
    ok = True

    def check(cond: bool, good: str, bad: str) -> None:
        nonlocal ok
        print(("[OK] " + good) if cond else ("[NG] " + bad), flush=True)
        ok &= cond

    # ---- 1〜4: デスクトップ版を開く -------------------------------------------
    started = time.monotonic()
    app = subprocess.Popen([args.exe], env=env, cwd=str(ROOT))
    print(f"起動しました: pid={app.pid} 作業={work}", flush=True)
    seen = wait_for(lambda: "最初の計算を返しました: coil (desktop)" in log_text(work)
                    or app.poll() is not None, args.timeout, 0.5)
    seen = seen and app.poll() is None
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

    stop(app)
    gone = wait_for(lambda: not any(alive(p) for p in kids), 15)
    check(gone, "exe を止めたら Python も終わりました",
          f"取り残されたプロセスがあります: {[p for p in kids if alive(p)]}")

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
