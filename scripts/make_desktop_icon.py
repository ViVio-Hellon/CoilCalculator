#!/usr/bin/env python3
"""デスクトップ版(Tauri)のアイコンを作る ── **標準ライブラリだけ**

窓・タスクバー・exe に出るアイコン。紺の角丸に、白いコイルの断面(巻いた板の輪)。
作り直すときだけ流す(作ったものはリポジトリに入れてある)。

    python scripts/make_desktop_icon.py
"""
from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src-tauri" / "icons"
NAVY = (31, 58, 96)
WHITE = (255, 255, 255)
SS = 4          # 1画素を 4×4 に分けて塗り、縁をなめらかにする


def coverage(size: int, x: int, y: int) -> tuple:
    """(角丸の中か, 白で塗るか) を 0〜1 の割合で返す。"""
    inside = white = 0
    radius = size / 6
    cx = cy = size / 2
    outer, inner = size * 0.40, size * 0.16
    for sy in range(SS):
        for sx in range(SS):
            px = x + (sx + 0.5) / SS
            py = y + (sy + 0.5) / SS
            # 角丸の四角
            dx = max(radius - px, 0, px - (size - radius))
            dy = max(radius - py, 0, py - (size - radius))
            if dx * dx + dy * dy > radius * radius:
                continue
            inside += 1
            r = math.hypot(px - cx, py - cy)
            if r > outer or r < inner:
                continue
            # 巻いた板の層: 輪の中を4本の白い帯に分ける(帯の間は細い紺)
            layer = (r - inner) / (outer - inner) * 4
            if layer - math.floor(layer) < 0.78 or r > outer - size * 0.012:
                white += 1
    n = SS * SS
    return inside / n, white / n


def draw(size: int) -> bytes:
    rows = []
    for y in range(size):
        row = bytearray([0])                       # PNG の行の頭(フィルタ無し)
        for x in range(size):
            alpha, w = coverage(size, x, y)
            if alpha == 0:
                row += bytes(4)
                continue
            mix = w / alpha
            rgb = [round(NAVY[i] * (1 - mix) + WHITE[i] * mix) for i in range(3)]
            row += bytes(rgb + [round(alpha * 255)])
        rows.append(bytes(row))
    return png(size, b"".join(rows))


def png(size: int, raw: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    head = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + chunk(b"IDAT", zlib.compress(raw, 9)) \
        + chunk(b"IEND", b"")


def ico(images: dict) -> bytes:
    """PNG をそのまま入れた .ico(Windows Vista 以降が読める形)。"""
    sizes = sorted(images)
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries, blobs = b"", b""
    for s in sizes:
        data = images[s]
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    return header + entries + blobs


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    made = {s: draw(s) for s in (16, 32, 48, 128, 256, 512)}
    (OUT / "icon.png").write_bytes(made[512])
    (OUT / "32x32.png").write_bytes(made[32])
    (OUT / "128x128.png").write_bytes(made[128])
    (OUT / "icon.ico").write_bytes(ico({s: made[s] for s in (16, 32, 48, 256)}))
    print(f"作りました: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
