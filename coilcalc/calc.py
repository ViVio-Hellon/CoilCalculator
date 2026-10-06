"""コイル・平板の重量計算 ── 画面の JS から移した計算の本体

元は日報管理ツールの「VC長さ計算 → コイル・平板」で、画面の JS が計算していました
(`aluminum-coil-calculator.js` / `plate-calculator.js` / 2つのグラフ)。ここへ移して、
**計算・入力の範囲・丸め・画面に出す文字**を Python の1か所に集めます。
画面(JS)は返ってきた文字を置くだけです。

    コイル  大円柱半径 = (肉厚 × 2 + 内径) / 2      小円柱半径 = 内径 / 2
            コイル体積 = π × 大円柱半径² × 幅 − π × 小円柱半径² × 幅
            重量(kg)   = コイル体積 / 1000 × 比重 / 1000
            長さ(m)    = コイル体積 / 板厚 / 幅 / 1000
            巻き数     = 肉厚 / 板厚(整数に四捨五入)
    平板    面積 = A × B   体積 = 面積 × 板厚   重量 = 体積 / 1000 × 比重 / 1000

**式・計算の順序・丸めは JS から1つも変えていません。** 浮動小数の足し算・掛け算は
順序で結果が変わるので、JS と同じ順に書いています(`tests/test_js_equivalence.py` が
元の JS を node で動かした結果と、画面に出る文字単位で突き合わせます)。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .jsnum import format_number, js_div, js_round, js_str, json_number, parse_float, to_fixed

PI = math.pi

#: グラフの点の数(範囲を 20 等分した 21 点)。JS の `steps = 20`
CHART_STEPS = 20

# ------------------------------------------------------------------
# 入力の範囲(画面の「※0〜600」・min/max・エラーの文・グラフの X 軸と同じ)
# `tests/test_spec_consistency.py` が index.html と食い違わないことを確かめる
# ------------------------------------------------------------------
#: (欄の名前, 下限, 上限, 画面の見出し, 単位)
COIL_FIELDS: Tuple[Tuple[str, float, float, str, str], ...] = (
    ("thickness", 0, 600, "肉厚", "mm"),
    ("inner-diameter", 250, 610, "内径", "mm"),
    ("coil-width", 0, 1800, "コイル幅", "mm"),
    ("specific-gravity", 0.01, 100, "比重", "g/cm³"),
    ("plate-thickness", 0.05, 20, "板厚", "mm"),
)
#: コイルのグラフで X 軸に選べる欄(並びは画面の選択肢と同じ)
COIL_CHART_X = ("thickness", "inner-diameter", "coil-width", "plate-thickness")
COIL_CHART_Y = ("weight", "length", "windings")

PLATE_FIELDS: Tuple[Tuple[str, float, float, str, str], ...] = (
    ("a", 0, 3000, "A", "mm"),
    ("b", 0, 10000, "B", "mm"),
    ("t", 0.05, 1000, "板厚", "mm"),
    ("specific-gravity", 0.01, 100, "比重", "g/cm³"),
)
PLATE_CHART_X = ("a", "b", "t")
PLATE_CHART_Y = ("weight", "area", "volume")


def _ranges(fields) -> Dict[str, Tuple[float, float]]:
    return {name: (lo, hi) for name, lo, hi, _, _ in fields}


COIL_RANGES = _ranges(COIL_FIELDS)
PLATE_RANGES = _ranges(PLATE_FIELDS)


def spec() -> Dict[str, Any]:
    """入力の範囲(画面が確かめに使う。数値の正はここ)。"""
    def view(fields):
        return [{"name": n, "min": lo, "max": hi, "label": label, "unit": unit}
                for n, lo, hi, label, unit in fields]
    return {"coil": {"fields": view(COIL_FIELDS), "chart_x": list(COIL_CHART_X),
                     "chart_y": list(COIL_CHART_Y)},
            "plate": {"fields": view(PLATE_FIELDS), "chart_x": list(PLATE_CHART_X),
                      "chart_y": list(PLATE_CHART_Y)}}


def read_fields(raw: Mapping[str, Any], ranges: Mapping[str, Tuple[float, float]]
                ) -> Tuple[Dict[str, float], List[str]]:
    """欄の文字を数にして、範囲の外の欄を挙げる(JS の `validateInput` と同じ判定)。"""
    values: Dict[str, float] = {}
    invalid: List[str] = []
    for name, (lo, hi) in ranges.items():
        v = parse_float(raw.get(name, ""))
        values[name] = v
        if math.isnan(v) or v < lo or v > hi:
            invalid.append(name)
    return values, invalid


def _line(text: str, value: str) -> Dict[str, str]:
    """計算の経過の1行。画面では `text` の後ろに `value` を強調して出す。"""
    return {"text": text, "value": value}


# ==================================================================
# コイル
# ==================================================================
def coil_numbers(thickness: float, inner_diameter: float, coil_width: float,
                 specific_gravity: float, plate_thickness: float) -> Dict[str, float]:
    """コイルの計算の途中と結果(JS `CoilCalculator.calculate` と同じ順序)。"""
    large_radius = (thickness * 2 + inner_diameter) / 2
    small_radius = inner_diameter / 2
    # Math.pow(r, 2) は r * r と同じ値(V8 の pow は y = 2 のとき x * x を返す)
    large_volume = PI * (large_radius * large_radius) * coil_width
    small_volume = PI * (small_radius * small_radius) * coil_width
    coil_volume = large_volume - small_volume
    coil_volume_cm = coil_volume / 1000
    weight_grams = coil_volume_cm * specific_gravity
    weight_kg = weight_grams / 1000
    cross_section = PI * (large_radius * large_radius - small_radius * small_radius)
    length_area = js_div(coil_volume, plate_thickness)
    length_mm = js_div(length_area, coil_width)       # 幅 0 のとき 0/0 = NaN(JS と同じ)
    length_m = length_mm / 1000
    winding_count = js_div(thickness, plate_thickness)
    return {
        "large_radius": large_radius, "small_radius": small_radius,
        "large_volume": large_volume, "small_volume": small_volume,
        "coil_volume": coil_volume, "coil_volume_cm": coil_volume_cm,
        "weight_grams": weight_grams, "weight_kg": weight_kg,
        "cross_section": cross_section, "length_area": length_area,
        "length_mm": length_mm, "length_m": length_m,
        "winding_count": winding_count, "rounded_winding_count": js_round(winding_count),
    }


def _coil_chart(v: Mapping[str, float]) -> Dict[str, Any]:
    """X 軸の欄だけを範囲いっぱいに動かした線(JS `CoilParameterChart.generateChartData`)。"""
    keys = {"thickness": 0, "inner-diameter": 1, "coil-width": 2, "plate-thickness": 4}
    base = [v["thickness"], v["inner-diameter"], v["coil-width"],
            v["specific-gravity"], v["plate-thickness"]]
    chart: Dict[str, Any] = {}
    for x in COIL_CHART_X:
        lo, hi = COIL_RANGES[x]
        step = (hi - lo) / CHART_STEPS
        labels: List[float] = []
        series: Dict[str, List[Optional[float]]] = {y: [] for y in COIL_CHART_Y}
        for i in range(CHART_STEPS + 1):
            point = lo + (step * i)
            labels.append(point)
            args = list(base)
            args[keys[x]] = point
            r = coil_numbers(*args)
            series["weight"].append(json_number(r["weight_kg"]))
            series["length"].append(json_number(r["length_m"]))
            series["windings"].append(json_number(r["rounded_winding_count"]))
        chart[x] = {"min": lo, "max": hi, "labels": labels, "series": series}
    return chart


def coil_view(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """コイルの画面に出すもの一式。範囲の外の欄があれば計算しない(`ok: false`)。"""
    v, invalid = read_fields(raw, COIL_RANGES)
    body: Dict[str, Any] = {"shape": "coil", "ok": not invalid, "invalid": invalid,
                            "values": {k: json_number(x) for k, x in v.items()}}
    if invalid:
        return body

    th, d, w = v["thickness"], v["inner-diameter"], v["coil-width"]
    sg, pt = v["specific-gravity"], v["plate-thickness"]
    r = coil_numbers(th, d, w, sg, pt)
    f = format_number
    s = js_str
    rounded = s(r["rounded_winding_count"])
    sg2, pt2 = to_fixed(sg, 2), to_fixed(pt, 2)
    lr, sr = f(r["large_radius"]), f(r["small_radius"])
    lv, sv, cv = f(r["large_volume"], 0), f(r["small_volume"], 0), f(r["coil_volume"], 0)
    cm, g, kg = f(r["coil_volume_cm"]), f(r["weight_grams"]), f(r["weight_kg"])
    cs, la = f(r["cross_section"]), f(r["length_area"], 0)
    lmm, lm = f(r["length_mm"], 0), f(r["length_m"])
    wc = f(r["winding_count"], 1)

    body["results"] = {"weight": f"{kg} kg", "length": f"{lm} m", "windings": f"{rounded} 巻"}
    body["details"] = {
        "dimensions-detailed": [
            _line(f"大円柱半径 = (肉厚 × 2 + 内径) / 2 = ({s(th)} × 2 + {s(d)}) / 2 = ", f"{lr} mm"),
            _line(f"小円柱半径 = 内径 / 2 = {s(d)} / 2 = ", f"{sr} mm"),
        ],
        "volume-detailed": [
            _line(f"大円柱体積 = π × 大円柱半径² × コイル幅 = π × {lr}² × {s(w)} = ", f"{lv} mm³"),
            _line(f"小円柱体積 = π × 小円柱半径² × コイル幅 = π × {sr}² × {s(w)} = ", f"{sv} mm³"),
            _line(f"コイル体積 = 大円柱体積 - 小円柱体積 = {lv} - {sv} = ", f"{cv} mm³"),
            _line(f"コイル体積(cm³) = コイル体積(mm³) / 1000 = {cv} / 1000 = ", f"{cm} cm³"),
        ],
        "weight-detailed": [
            _line(f"重量(g) = 体積(cm³) × 比重(g/cm³) = {cm} × {sg2} = ", f"{g} g"),
            _line(f"重量(kg) = 重量(g) / 1000 = {g} / 1000 = ", f"{kg} kg"),
        ],
        "length-detailed": [
            _line(f"断面積 = π × (大円柱半径² - 小円柱半径²) = π × ({lr}² - {sr}²) = ", f"{cs} mm²"),
            _line(f"面積 = コイル体積(mm³) / 板厚(mm) = {cv} / {pt2} = ", f"{la} mm²"),
            _line(f"長さ(mm) = 面積(mm²) / コイル幅(mm) = {la} / {s(w)} = ", f"{lmm} mm"),
            _line(f"長さ(m) = 長さ(mm) / 1000 = {lmm} / 1000 = ", f"{lm} m"),
        ],
        "windings-detailed": [
            _line(f"巻き数 = 肉厚(mm) / 板厚(mm) = {s(th)} / {pt2} = ", f"{wc} ≈ {rounded} 巻"),
        ],
    }
    body["modal"] = {
        "modal-large-radius": f"= ({s(th)} × 2 + {s(d)}) / 2 = {lr} mm",
        "modal-small-radius": f"= {s(d)} / 2 = {sr} mm",
        "modal-large-volume": f"= π × {lr}² × {s(w)} = {lv} mm³",
        "modal-small-volume": f"= π × {sr}² × {s(w)} = {sv} mm³",
        "modal-coil-volume": f"= {lv} - {sv} = {cv} mm³",
        "modal-coil-volume-cm": f"= {cv} / 1000 = {cm} cm³",
        "modal-weight-g": f"= {cm} × {sg2} = {g} g",
        "modal-weight-kg": f"= {g} / 1000 = {kg} kg",
        "modal-cross-section": f"= π × ({lr}² - {sr}²) = {cs} mm²",
        "modal-length-area": f"= {cv} / {pt2} = {la} mm²",
        "modal-length-mm": f"= {la} / {s(w)} = {lmm} mm",
        "modal-length-m": f"= {lmm} / 1000 = {lm} m",
        "modal-windings": f"= {s(th)} / {pt2} = {wc} ≈ {rounded} 巻",
    }
    body["chart"] = _coil_chart(v)
    return body


# ==================================================================
# 平板
# ==================================================================
def plate_numbers(a: float, b: float, t: float, specific_gravity: float) -> Dict[str, float]:
    """平板の計算の途中と結果(JS `PlateCalculator.compute` と同じ順序)。"""
    area_mm = a * b
    area_m = area_mm / 1000000
    volume_mm = area_mm * t
    volume_cm = volume_mm / 1000
    weight_grams = volume_cm * specific_gravity
    weight_kg = weight_grams / 1000
    return {"area_mm": area_mm, "area_m": area_m, "volume_mm": volume_mm,
            "volume_cm": volume_cm, "weight_grams": weight_grams, "weight_kg": weight_kg}


_PLATE_Y_KEY = {"weight": "weight_kg", "area": "area_m", "volume": "volume_cm"}


def _plate_chart(v: Mapping[str, float]) -> Dict[str, Any]:
    """JS `PlateParameterChart.generateChartData` と同じ点(x, y)。"""
    chart: Dict[str, Any] = {}
    for x in PLATE_CHART_X:
        lo, hi = PLATE_RANGES[x]
        step = (hi - lo) / CHART_STEPS
        labels: List[float] = []
        series: Dict[str, List[Optional[float]]] = {y: [] for y in PLATE_CHART_Y}
        for i in range(CHART_STEPS + 1):
            point = lo + step * i
            labels.append(point)
            args = dict(v)
            args[x] = point
            r = plate_numbers(args["a"], args["b"], args["t"], args["specific-gravity"])
            for y in PLATE_CHART_Y:
                series[y].append(json_number(r[_PLATE_Y_KEY[y]]))
        chart[x] = {"min": lo, "max": hi, "labels": labels, "series": series}
    return chart


def plate_view(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """平板の画面に出すもの一式。範囲の外の欄があれば計算しない(`ok: false`)。"""
    v, invalid = read_fields(raw, PLATE_RANGES)
    body: Dict[str, Any] = {"shape": "plate", "ok": not invalid, "invalid": invalid,
                            "values": {k: json_number(x) for k, x in v.items()}}
    if invalid:
        return body

    a, b, t, sg = v["a"], v["b"], v["t"], v["specific-gravity"]
    r = plate_numbers(a, b, t, sg)
    f = format_number
    s = js_str
    t2, sg2 = to_fixed(t, 2), to_fixed(sg, 2)
    amm, am = f(r["area_mm"], 0), f(r["area_m"], 3)
    vmm, vcm = f(r["volume_mm"], 0), f(r["volume_cm"], 1)
    g, kg = f(r["weight_grams"], 1), f(r["weight_kg"], 2)

    body["results"] = {"weight": f"{kg} kg", "area": f"{am} m²", "volume": f"{vcm} cm³"}
    body["details"] = {
        "plate-area-detailed": [
            _line(f"面積(mm²) = A × B = {s(a)} × {s(b)} = ", f"{amm} mm²"),
            _line(f"面積(m²) = 面積(mm²) / 1,000,000 = {amm} / 1,000,000 = ", f"{am} m²"),
        ],
        "plate-volume-detailed": [
            _line(f"体積(mm³) = A × B × 板厚 = {s(a)} × {s(b)} × {t2} = ", f"{vmm} mm³"),
            _line(f"体積(cm³) = 体積(mm³) / 1000 = {vmm} / 1000 = ", f"{vcm} cm³"),
        ],
        "plate-weight-detailed": [
            _line(f"重量(g) = 体積(cm³) × 比重(g/cm³) = {vcm} × {sg2} = ", f"{g} g"),
            _line(f"重量(kg) = 重量(g) / 1000 = {g} / 1000 = ", f"{kg} kg"),
        ],
    }
    body["modal"] = {
        "plate-modal-volume-mm": f"= {s(a)} × {s(b)} × {t2} = {vmm} mm³",
        "plate-modal-volume-cm": f"= {vmm} / 1000 = {vcm} cm³",
        "plate-modal-weight-g": f"= {vcm} × {sg2} = {g} g",
        "plate-modal-weight-kg": f"= {g} / 1000 = {kg} kg",
        "plate-modal-area-mm": f"= {s(a)} × {s(b)} = {amm} mm²",
        "plate-modal-area-m": f"= {amm} / 1,000,000 = {am} m²",
        "plate-modal-volume-mm2": f"= {amm} × {t2} = {vmm} mm³",
        "plate-modal-volume-cm2": f"= {vmm} / 1000 = {vcm} cm³",
    }
    body["numbers"] = {k: json_number(x) for k, x in r.items()}
    body["chart"] = _plate_chart(v)
    return body
