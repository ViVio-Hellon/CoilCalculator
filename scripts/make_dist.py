#!/usr/bin/env python3
r"""配布用フォルダを作る(日報管理ツール・python-web-tools の `scripts/make_dist.py` と同じ考え)

【なぜ要るのか】
配るときに手でフォルダをコピーすると、**配ってはいけないもの**が紛れ、
**要るもの**が抜けます。

    tests\ / scripts\ / src-tauri\ / .git / __pycache__   … 開発にしか使わないもの
    CoilCalculator.exe(デスクトップ版)                  … ソースには無い。GitHub Actions が作る

端末ごとの中身(ログ・錠・端末の設定・マスタの写し)は `%LOCALAPPDATA%\CoilCalculator`
にあり、ツールのフォルダには入っていません。**配るものだけ**を新しいフォルダへ写します。

    scripts\make_dist.bat                                  # ダブルクリック(ツールの隣に作る)
    python scripts\make_dist.py --out D:\配布\今回            # 置き場所を指定
    python scripts\make_dist.py --zip                      # zip も作る
    python scripts\make_dist.py --vc-master-dir \\サーバ\共有\参照用マスタ
                                                           # VC計算マスタの置き場所を配った先の既定にする
    python scripts\make_dist.py --exe D:\成果物\CoilCalculator.exe   # 入れる exe を指定

【デスクトップ版の exe】
GitHub Actions「デスクトップ版(Windows)」の成果物 `CoilCalculator-windows` の
`CoilCalculator.exe` を、ツールのフォルダの直下に置いてから流すと入ります
(`src-tauri\target\release\` に作ってあればそれも探します)。無くても配布フォルダは
作れます(ブラウザ版 Start.vbs で動く)。

【起動ファイルの形を保証する】
`.bat` / `.vbs` は **CP932 + CRLF** でないと現場で動きません(cmd.exe・WSH の決まり)。
git の取り出し方によっては改行が LF になることがあるので、写すときに CRLF に揃え、
CP932 として読めることと、塊の中の半角 `)` が無いことを確かめます。

【作ったあとに確かめること】
できたフォルダの `配布メモ.txt` に、版・入れた exe・マスタの置き場所・配った先で
することを書いてあります。
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import shutil
import sys
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent

#: 直下で**配るもの**。直下に何かを足したら、ここか `DEV_ONLY` のどちらかに入れる
#: (`tests/test_make_dist.py` が食い違いを見つけます)
INCLUDE: Tuple[str, ...] = (
    "README.md",
    "Start.vbs", "start.bat", "stop.bat",
    "start_app.py", "bridge.py", "process_manager.py",
    "app", "coilcalc", "config",
    # VBA の解析・設計の記録。README が指す
    "docs",
)

#: 直下にあっても**配らないもの**(開発にしか使わない・作ったもの)。exe は下で別に入れる
DEV_ONLY: Tuple[str, ...] = (
    "tests", "scripts", "src-tauri", ".github",
    ".git", ".gitignore", ".gitattributes", "__pycache__",
    "CoilCalculator.exe",
)

#: 中にあっても写さないもの(名前で見る。フォルダならその下ごと)
EXCLUDE_NAMES: Tuple[str, ...] = (
    "__pycache__", "*.pyc", "*.pyo", ".pytest_cache", ".coverage", ".coverage.*",
    "htmlcov", "*.tmp", "*.part", "*.smoke", "*.new", ".DS_Store", "Thumbs.db",
)

#: できたフォルダに**入っていてはいけない**もの(最後に確かめる)
FORBIDDEN: Tuple[str, ...] = ("tests", "scripts", "src-tauri", ".git", ".github")

#: 配るデスクトップ版の名前と、探す場所(先に見つかったもの)
EXE_NAME = "CoilCalculator.exe"
EXE_CANDIDATES: Tuple[str, ...] = (
    "CoilCalculator.exe",
    "src-tauri/target/release/CoilCalculator.exe",
)

#: 起動ファイル(CP932 + CRLF で配る)
LAUNCH_FILES: Tuple[str, ...] = ("Start.vbs", "start.bat", "stop.bat")


def _config() -> dict:
    try:
        return json.loads((ROOT / "config" / "app.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _version() -> str:
    return str(_config().get("version", "unknown"))


def _tool_name() -> str:
    return str(_config().get("display_name", "VC長さ・コイル平板 計算ツール"))


def _excluded(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in EXCLUDE_NAMES)


def _ignore(directory: str, names: List[str]) -> set:
    return {n for n in names if _excluded(n)}


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def find_exe() -> Optional[Path]:
    for name in EXE_CANDIDATES:
        path = ROOT / name
        if path.is_file():
            return path
    return None


def bare_close_paren(text: str) -> List[str]:
    """`.bat` の塊 `( … )` の中で、行の途中に出てくる半角の `)`(cmd.exe が塊の終わりと読む)。"""
    found, depth = [], 0
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        low = line.lower()
        if not line or low.startswith("rem") or line.startswith("::"):
            continue
        body = line
        if depth > 0 and body.startswith(")"):
            depth -= 1
            body = body[1:].strip()
            if body.lower().startswith("else"):
                body = body[4:].strip()
        opens = body.endswith("(")
        inner = body[:-1] if opens else body
        if depth > 0 and ")" in inner.replace("^)", ""):
            found.append(f"{no}: {line}")
        if opens:
            depth += 1
    return found


def write_launch_file(src: Path, dest: Path) -> None:
    """起動ファイルを CP932 + CRLF で書く。**読めない・壊れているものは配らない。**"""
    data = src.read_bytes()
    if any(b >= 0x80 for b in data):
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            # 日本語の CP932 が UTF-8 としても読めることはまず無い。読めたら UTF-8 で保存し直されている
            raise SystemExit(f"{src.name} が UTF-8 で保存されています。CP932(Shift-JIS)で保存し直してください。")
    try:
        text = data.decode("cp932")
    except UnicodeDecodeError as exc:
        raise SystemExit(f"{src.name} が CP932 として読めません(UTF-8 で保存し直された?): {exc}")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if src.suffix.lower() == ".bat":
        bad = bare_close_paren(text)
        if bad:
            raise SystemExit(f"{src.name} の塊の中に半角の ) があります(cmd.exe が止まる): " + " / ".join(bad))
    dest.write_bytes(text.replace("\n", "\r\n").encode("cp932"))


def build(out: Path, *, force: bool = False, make_zip: bool = False,
          exe: Optional[Path] = None, vc_master_dir: Optional[str] = None
          ) -> Tuple[Path, List[str]]:
    """配布用フォルダを作る。戻り値は (できたフォルダ, 画面に出す行)。断るときは `SystemExit`。"""
    out = out.resolve()
    if _inside(out, ROOT):
        raise SystemExit(f"ツールのフォルダの中には作れません: {out}\n"
                         "(次に作るとき、前に作ったものまで写してしまいます)")
    if out.exists() and any(out.iterdir()):
        if not force:
            raise SystemExit(f"{out} はもうあって、中身があります。\n"
                             "別の場所を --out で指定するか、--force で作り直してください。")
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    missing = []
    for name in INCLUDE:
        src = ROOT / name
        if not src.exists():
            missing.append(name)
            continue
        if name in LAUNCH_FILES:
            write_launch_file(src, out / name)
        elif src.is_dir():
            shutil.copytree(src, out / name, ignore=_ignore, dirs_exist_ok=True)
        else:
            shutil.copy2(src, out / name)
    if missing:
        shutil.rmtree(out)
        raise SystemExit("配るはずのファイルがありません: " + ", ".join(missing))

    lines = [f"配布用フォルダを作りました: {out}", f"版: VER{_version()}"]

    # デスクトップ版の exe(あれば)。無くてもブラウザ版(Start.vbs)で動く
    exe = exe if exe is not None else find_exe()
    if exe is not None:
        if not Path(exe).is_file():
            shutil.rmtree(out)
            raise SystemExit(f"指定した exe がありません: {exe}")
        shutil.copy2(exe, out / EXE_NAME)
        lines.append(f"デスクトップ版を入れました: {EXE_NAME}(元: {exe})")
    else:
        lines.append(f"デスクトップ版({EXE_NAME})は入っていません。GitHub Actions の"
                     "「デスクトップ版(Windows)」の成果物 CoilCalculator-windows の exe を、"
                     "ツールのフォルダの直下に置いてから作り直すと入ります"
                     "(無くてもブラウザ版 Start.vbs で使えます)。")

    # VC計算マスタの置き場所(配った先の既定)。端末ごとの設定があればそちらが勝つ
    conf_path = out / "config" / "app.json"
    conf = json.loads(conf_path.read_text(encoding="utf-8"))
    if vc_master_dir is not None:
        conf.setdefault("vc", {})["master_dir"] = vc_master_dir.strip()
        conf_path.write_text(json.dumps(conf, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    where = (conf.get("vc") or {}).get("master_dir", "")
    lines.append("VC計算マスタの置き場所: " + (where or
                 "未設定(各端末の作業フォルダ %LOCALAPPDATA%\\CoilCalculator\\master に作ります。"
                 "共有するなら --vc-master-dir で共有フォルダを入れて作り直すか、"
                 "配った先の 設定 → マスタの置き場所 で変えてください)"))

    # 入っていてはいけないものが無いか、最後に確かめる
    leaked = [p for p in FORBIDDEN if (out / p).exists()]
    leaked += [str(p.relative_to(out)) for p in out.rglob("*") if _excluded(p.name)]
    if leaked:
        shutil.rmtree(out)
        raise SystemExit("配ってはいけないものが入ったため、作るのをやめました: "
                         + ", ".join(sorted(set(leaked))))

    files = sum(1 for p in out.rglob("*") if p.is_file())
    lines.append(f"ファイル数: {files}")
    (out / "配布メモ.txt").write_text(_memo(lines), encoding="utf-8-sig")

    if make_zip:
        archive = shutil.make_archive(str(out), "zip", root_dir=out.parent, base_dir=out.name)
        lines.append(f"zip も作りました: {archive}")
    return out, lines


def _memo(lines: List[str]) -> str:
    today = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    return "\r\n".join([
        f"{_tool_name()} 配布メモ({today})",
        "",
        *lines,
        "",
        "配った先ですること",
        "  1. このフォルダを好きな場所に置く(以前の版のフォルダに上書きしない)",
        "  2. Python 3.8 以上が入っているか確かめる(追加のパッケージ・pip install は要りません)",
        f"  3. {EXE_NAME} で起動する(デスクトップ版。ポートを使いません)。",
        "     exe が無いとき・動かないときは Start.vbs(ブラウザ版)で起動できます。",
        "     起動しないときは start.bat で原因が出ます",
        "  4. VC計算マスタを共有するなら、設定 → マスタの置き場所 を確かめる",
        "  5. 以前の版を使っていた端末は、この端末の設定・マスタの写しがそのまま残ります",
        "     (%LOCALAPPDATA%\\CoilCalculator にあり、ツールのフォルダには入っていないため)",
        "",
        "入れていないもの: tests・scripts・src-tauri(exe のソース)・__pycache__",
        "",
    ])


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="配布用フォルダを作る")
    parser.add_argument("--out", help="作る場所(既定: ツールの隣に「<ツール名>_VER版」)")
    parser.add_argument("--force", action="store_true", help="作る場所に中身があれば消して作り直す")
    parser.add_argument("--zip", action="store_true", help="zip も作る")
    parser.add_argument("--exe", help=f"入れるデスクトップ版の exe(既定: 直下の {EXE_NAME} など)")
    parser.add_argument("--vc-master-dir", help="VC計算マスタの置き場所(配った先の既定にする)")
    args = parser.parse_args(argv)

    out = Path(args.out) if args.out else ROOT.parent / f"{_tool_name()}_VER{_version()}"
    try:
        _out, lines = build(out, force=args.force, make_zip=args.zip,
                            exe=Path(args.exe) if args.exe else None,
                            vc_master_dir=args.vc_master_dir)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
