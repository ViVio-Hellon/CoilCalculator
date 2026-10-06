#!/usr/bin/env python3
"""操作説明書の写真を撮り直す(画面を変えたら流す)

    xvfb-run -a -s "-screen 0 1600x1000x24" python scripts/make_manual_images.py \\
        --exe src-tauri/target/release/CoilCalculator

    1. ブラウザ版を起動し、Chromium(Playwright)で画面を開いて撮る(scripts/manual/shoot_browser.cjs)
    2. --exe があれば、デスクトップ版の窓を本当に開いて撮る(画面全体・版の詳細・
       操作説明書の窓・ブラウザ版と同時に開いたときの知らせ・Python が無いときの画面)
       押すのは xdotool。画面は ImageMagick の import で撮る

出し先: app/static/manual/img/。作業用の道具なので node・Playwright・xdotool・ImageMagick を使う
(アプリ本体は使わない。ラインPCには要らない)。作業フォルダは一時フォルダに作る。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "static" / "manual" / "img"
SHOOTER = ROOT / "scripts" / "manual" / "shoot_browser.cjs"


def image_size(path: Path) -> tuple:
    """PNG・JPEG の幅と高さ(標準ライブラリだけで読む)。"""
    data = path.read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    i = 2
    while i < len(data):
        marker, size = data[i + 1], int.from_bytes(data[i + 2:i + 4], "big")
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
        i += 2 + size
    raise ValueError(f"大きさが読めません: {path}")


def sync_sizes() -> None:
    """説明書の <img> の width / height を、撮った写真の大きさに合わせる(読み込み中に頁が動かない)。"""
    import re
    for html in sorted(OUT.parent.glob("*.html")):
        text = html.read_text(encoding="utf-8")

        def fix(m):
            w, h = image_size(OUT.parent / m.group(1))
            tag = re.sub(r'\s(width|height)="\d+"', "", m.group(0))
            return tag.replace(f'src="{m.group(1)}"', f'src="{m.group(1)}"') [:-1] + f' width="{w}" height="{h}">'
        new = re.sub(r'<img src="(img/[^"]+)"[^>]*>', fix, text)
        if new != text:
            html.write_text(new, encoding="utf-8")


def wait_for(predicate, timeout: float = 30.0, step: float = 0.3) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


def owner(local: Path) -> dict:
    try:
        return json.loads((local / "runtime" / "instance.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def start_browser_version(env: dict, port: int) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, str(ROOT / "start_app.py"), "--no-browser", "--port", str(port)],
                            env=env, cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop_browser_version(env: dict, proc: subprocess.Popen) -> None:
    subprocess.run([sys.executable, str(ROOT / "process_manager.py")], env=env, cwd=str(ROOT),
                   capture_output=True, timeout=60)
    try:
        proc.wait(15)
    except subprocess.TimeoutExpired:
        proc.kill()


def snap(name: str, crop: str = "") -> None:
    """画面全体を撮る。crop は ImageMagick の形(幅x高さ+x+y)。"""
    raw = OUT / "_raw.png"
    subprocess.run(["import", "-window", "root", str(raw)], check=True)
    args = ["convert", str(raw)]
    if crop:
        args += ["-crop", crop, "+repage"]
    if name.endswith(".jpg"):
        args += ["-quality", "82"]
    subprocess.run(args + [str(OUT / name)], check=True)
    raw.unlink()


def window_origin(title_part: str) -> tuple:
    """窓の左上(窓の管理をする道具が無いので、外枠が置いた場所そのまま)。"""
    ids = subprocess.run(["xdotool", "search", "--name", title_part], capture_output=True, text=True).stdout.split()
    if not ids:
        return 50, 30
    geo = subprocess.run(["xdotool", "getwindowgeometry", "--shell", ids[-1]], capture_output=True, text=True).stdout
    values = dict(line.split("=", 1) for line in geo.splitlines() if "=" in line)
    return int(values.get("X", 50)), int(values.get("Y", 30))


def click(x: int, y: int) -> None:
    subprocess.run(["xdotool", "mousemove", str(x), str(y), "click", "1"], check=True)
    # 押したあとはマウスを窓の外へ(ボタンの説明の吹き出しが写らないように)
    subprocess.run(["xdotool", "mousemove", "1599", "999"], check=True)


def desktop_shots(exe: str, env: dict, positions: dict, local: Path) -> None:
    log = local / "logs" / "coilcalc.log"
    ready = lambda: log.exists() and "最初の計算を返しました: coil (desktop)" in log.read_text(encoding="utf-8")

    # 1. ふだんの窓・版の詳細・操作説明書の窓
    app = subprocess.Popen([exe], env=env, cwd=str(ROOT))
    try:
        if not wait_for(ready, 60):
            raise RuntimeError("デスクトップ版で計算が返りませんでした")
        time.sleep(3)
        snap("desktop-window.jpg", "1500x940+50+30")
        ox, oy = window_origin("重量計算ツール v")
        click(ox + positions["version"]["x"], oy + positions["version"]["y"])
        time.sleep(1)
        snap("version-desktop.png", f"560x300+{ox}+{oy}")
        click(ox + positions["version"]["x"], oy + positions["version"]["y"])
        time.sleep(0.5)
        click(ox + positions["help"]["x"], oy + positions["help"]["y"])
        if not wait_for(lambda: bool(subprocess.run(["xdotool", "search", "--name", "操作説明書"],
                                                     capture_output=True, text=True).stdout.strip()), 20):
            raise RuntimeError("「操作説明」を押しても、操作説明書の窓が開きませんでした")
        time.sleep(3)
        mx, my = window_origin("操作説明書")
        snap("desktop-manual.jpg", f"1100x860+{mx}+{my}")
    finally:
        app.terminate()
        app.wait(15)

    # 2. ブラウザ版が先に動いているときの知らせ
    browser = start_browser_version(env, 18751)
    try:
        wait_for(lambda: owner(local).get("kind") == "browser", 30)
        noisy = dict(env)
        noisy.pop("COIL_TOOL_QUIET", None)
        refused = subprocess.Popen([exe], env=noisy, cwd=str(ROOT))
        time.sleep(4)
        snap("desktop-refused.png", "720x230+0+0")
        refused.terminate()
        refused.wait(15)
    finally:
        stop_browser_version(env, browser)

    # 3. Python が見つからないときの画面
    broken = dict(env, COIL_TOOL_PYTHON=str(local / "no-python" / "python.exe"))
    app = subprocess.Popen([exe], env=broken, cwd=str(ROOT))
    try:
        time.sleep(6)
        snap("desktop-failure.jpg", "1500x940+50+30")
    finally:
        app.terminate()
        app.wait(15)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", help="デスクトップ版の exe(無ければブラウザ版の写真だけ撮る)")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    local = Path(tempfile.mkdtemp(prefix="coil_manual_"))
    env = dict(os.environ, COIL_TOOL_LOCAL_DIR=str(local), COIL_TOOL_QUIET="1", COIL_TOOL_ROOT=str(ROOT),
               PYTHONIOENCODING="utf-8")
    npm_root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, shell=os.name == "nt").stdout.strip()
    node_env = dict(env, NODE_PATH=npm_root)
    positions_file = local / "positions.json"

    browser = start_browser_version(env, 18750)
    try:
        if not wait_for(lambda: owner(local).get("url"), 30):
            raise RuntimeError("ブラウザ版が起動しませんでした")
        subprocess.run([shutil.which("node") or "node", str(SHOOTER), owner(local)["url"], str(OUT),
                        str(positions_file)], env=node_env, check=True, timeout=600)
        print("ブラウザ版の写真を撮りました")
    finally:
        stop_browser_version(env, browser)

    if args.exe:
        desktop_shots(args.exe, env, json.loads(positions_file.read_text(encoding="utf-8")), local)
        print("デスクトップ版の写真を撮りました")
    sync_sizes()
    for f in sorted(OUT.iterdir()):
        print(f"  {f.name:28} {f.stat().st_size // 1024:5} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
