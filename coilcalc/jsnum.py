"""JavaScript と**同じ文字**を出すための数の扱い

計算はもともと画面の JS(`aluminum-coil-calculator.js` / `plate-calculator.js`)が
していました。Python に移しても、画面に出る文字は1文字も変えません。そのために
JS の次の振る舞いをそのまま写します。

    parse_float(text)   `parseFloat`      先頭から読めるところまで読む。読めなければ NaN
    to_fixed(x, d)      `Number.toFixed`  0.5 ちょうどは 0 から遠い側(Python の round と違う)
    js_str(x)           `${x}`            400.0 → "400"(Python の str は "400.0")
    js_round(x)         `Math.round`      2.5 → 3、-2.5 → -2(Python の round は偶数側)
    js_div(a, b)        `a / b`           0 で割っても止まらない(0/0 = NaN、1/0 = Infinity)
    format_number(x, d) 画面の `formatNumber` toFixed の結果に3桁ごとのカンマ

`tests/test_js_equivalence.py` が、元の JS を node で動かした結果と突き合わせます。
"""
from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_UP, Decimal

NAN = float("nan")

# JS の StrWhiteSpaceChar(parseFloat が読み飛ばす空白)
_JS_SPACE = (
    "\u0009\u000a\u000b\u000c\u000d       "
    "           　﻿"
)
# StrDecimalLiteral の、先頭からいちばん長く読めるところ
_JS_DECIMAL = re.compile(
    r"[+-]?(?:Infinity|(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)"
)
# 画面の formatNumber と同じ正規表現(`/\B(?=(\d{3})+(?!\d))/g`)
_THOUSANDS = re.compile(r"\B(?=(\d{3})+(?!\d))", re.ASCII)


def parse_float(text: object) -> float:
    """JS の `parseFloat(String(text))`。"""
    s = str(text).lstrip(_JS_SPACE)
    m = _JS_DECIMAL.match(s)
    if not m:
        return NAN
    token = m.group(0)
    if token.endswith("Infinity"):
        return -math.inf if token.startswith("-") else math.inf
    return float(token)


def js_str(x: float) -> str:
    """JS の `String(x)`(テンプレートの `${x}`)。"""
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, int):
        return str(x)
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "Infinity" if x > 0 else "-Infinity"
    if x == 0:
        return "0"                                # -0 も "0"
    sign = "-" if x < 0 else ""
    # repr は JS と同じく「元の数に戻る最短の桁」を出す。並べ方だけ JS に直す
    _, raw, exponent = Decimal(repr(abs(x))).as_tuple()
    digits = "".join(map(str, raw))
    stripped = digits.rstrip("0")
    exponent += len(digits) - len(stripped)
    digits = stripped
    # k = 桁数、n = 小数点の位置(数字列の先頭から何桁目の後ろか)
    k = len(digits)
    n = k + exponent
    if k <= n <= 21:
        body = digits + "0" * (n - k)
    elif 0 < n <= 21:
        body = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        body = digits[0] + ("." + digits[1:] if k > 1 else "") + "e" + ("+" if e >= 0 else "-") + str(abs(e))
    return sign + body


def to_fixed(x: float, digits: int) -> str:
    """JS の `x.toFixed(digits)`。"""
    if math.isnan(x):
        return "NaN"
    if abs(x) >= 1e21 or math.isinf(x):
        return js_str(x)
    if x == 0:
        x = 0.0                                   # (-0).toFixed は "0…"
    # 2進の値そのもの(Decimal(float) は丸めずに写す)を、0.5 は 0 から遠い側で丸める
    q = Decimal(x).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return f"{q:.{digits}f}"


def js_round(x: float) -> float:
    """JS の `Math.round(x)`(0.5 ちょうどは +∞ 側)。"""
    if math.isnan(x) or math.isinf(x):
        return x
    r = math.floor(x)
    return float(r + 1 if x - r >= 0.5 else r)


def js_div(a: float, b: float) -> float:
    """JS の `a / b`。0 で割っても例外にしない。"""
    if b == 0:
        if a == 0 or math.isnan(a):
            return NAN
        return math.copysign(math.inf, a) * math.copysign(1.0, b)
    return a / b


def format_number(x: float, decimals: int = 1) -> str:
    """画面の `formatNumber`(toFixed + 3桁ごとのカンマ)。"""
    return _THOUSANDS.sub(",", to_fixed(x, decimals))


def json_number(x: float):
    """JSON に載せる数。NaN・∞ は JSON に無いので `null`(グラフでは線が途切れる)。"""
    if x is None or math.isnan(x) or math.isinf(x):
        return None
    return x
