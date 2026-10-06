"""移す前の JS と、移した Python が**画面に同じ文字を出す**ことを確かめる

元の JS(`tests/reference/original_js/`。日報管理ツールの
`app/static/vc/coil/` から1文字も変えずに写したもの)を node で動かし
(`tests/reference/run_original.js`)、同じ入力で Python(`coilcalc/calc.py`)が返す
ものと突き合わせます。

    範囲の確かめ    どの欄が範囲の外か
    結果            重量・長さ・巻き数 / 重量・面積・体積
    詳細計算過程    1行ずつ(式の文字と、強調する値)
    モーダル        詳細の各行
    グラフ          X 軸の欄ごとの 21 点(x と、重量・長さ・巻き数… の y)── 数値が完全一致

入力は 境目の値・JS と Python で丸めや書き方が分かれやすい値(0.5 ちょうど・
指数表記・小数の桁)・乱数(種を固定)を混ぜます。node が無い PC では飛ばします。
"""
from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from coilcalc import calc  # noqa: E402

RUNNER = ROOT / "tests" / "reference" / "run_original.js"
NODE = shutil.which("node")

COIL_KEYS = [name for name, *_ in calc.COIL_FIELDS]
PLATE_KEYS = [name for name, *_ in calc.PLATE_FIELDS]

# 書き方・丸めが分かれやすい文字
TRICKY = ["0", "0.0", "1e2", "2.5", "0.125", "1.005", "  12", "12abc", "0.05", "0.00001",
          "1.25", "3.335", "999.995", "", "-1", "abc", "1e-7", "600.0000001", ".5", "+7"]


def _number_text(rng: random.Random, lo: float, hi: float) -> str:
    """範囲の中(ときどき外)の数を、いろいろな書き方で。"""
    kind = rng.random()
    span = hi - lo
    if kind < 0.08:
        return rng.choice(TRICKY)
    if kind < 0.16:
        return rng.choice([str(lo), str(hi), repr(float(lo)), repr(float(hi))])
    if kind < 0.20:
        return repr(rng.uniform(hi, hi + span))          # 範囲の外
    value = rng.uniform(lo, hi)
    digits = rng.choice([0, 0, 1, 2, 2, 3, 5, 17])
    return f"{value:.{digits}f}"


def make_cases(seed: int, count: int):
    rng = random.Random(seed)
    coil, plate = [], []
    defaults_coil = {"thickness": "400", "inner-diameter": "557", "coil-width": "1250",
                     "specific-gravity": "2.70", "plate-thickness": "1.00"}
    defaults_plate = {"a": "1000", "b": "2000", "t": "1.00", "specific-gravity": "2.70"}
    coil.append(dict(defaults_coil))
    plate.append(dict(defaults_plate))
    # コイル幅 0(長さが 0/0 = NaN になる)・肉厚 0・境目ちょうど
    coil.append(dict(defaults_coil, **{"coil-width": "0"}))
    coil.append(dict(defaults_coil, **{"thickness": "0"}))
    coil.append({"thickness": "600", "inner-diameter": "610", "coil-width": "1800",
                 "specific-gravity": "100", "plate-thickness": "20"})
    coil.append({"thickness": "0", "inner-diameter": "250", "coil-width": "0",
                 "specific-gravity": "0.01", "plate-thickness": "0.05"})
    plate.append({"a": "0", "b": "0", "t": "0.05", "specific-gravity": "0.01"})
    plate.append({"a": "3000", "b": "10000", "t": "1000", "specific-gravity": "100"})
    for _ in range(count):
        coil.append({name: _number_text(rng, lo, hi) for name, lo, hi, *_ in calc.COIL_FIELDS})
        plate.append({name: _number_text(rng, lo, hi) for name, lo, hi, *_ in calc.PLATE_FIELDS})
    return coil, plate


@unittest.skipUnless(NODE, "node が無いので、元の JS との突き合わせは飛ばします")
class JsEquivalenceTest(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.coil_cases, cls.plate_cases = make_cases(seed=20261006, count=1500)
        payload = json.dumps({"coil": cls.coil_cases, "plate": cls.plate_cases})
        done = subprocess.run([NODE, str(RUNNER)], input=payload, capture_output=True,
                              text=True, encoding="utf-8", timeout=300)
        if done.returncode != 0:
            raise RuntimeError(f"元の JS を動かせませんでした:\n{done.stderr}")
        cls.original = json.loads(done.stdout)

    def _compare(self, shape: str, cases, view, extra=()):
        computed = 0
        for fields, js in zip(cases, self.original[shape]):
            py = view(fields)
            with self.subTest(shape=shape, fields=fields):
                self.assertEqual(sorted(py["invalid"]), sorted(js["invalid"]), "範囲の確かめ")
                if js["invalid"]:
                    self.assertFalse(py["ok"])
                    continue
                computed += 1
                self.assertEqual(py["results"], js["results"], "結果")
                self.assertEqual(py["details"], js["details"], "詳細計算過程")
                self.assertEqual(py["modal"], js["modal"], "モーダル")
                for x, line in js["chart"].items():
                    self.assertEqual(py["chart"][x]["labels"], line["labels"], f"グラフの x ({x})")
                    self.assertEqual(py["chart"][x]["series"], line["series"], f"グラフの y ({x})")
                for key in extra:
                    self.assertEqual({k: py["values"][k] for k in ("a", "b", "t")}, js[key])
        return computed

    def test_coil(self):
        computed = self._compare("coil", self.coil_cases, calc.coil_view)
        self.assertGreater(computed, 800, "計算まで進んだ組が少なすぎる(入力の作り方を見直す)")

    def test_plate(self):
        computed = self._compare("plate", self.plate_cases, calc.plate_view, extra=("event",))
        self.assertGreater(computed, 800, "計算まで進んだ組が少なすぎる(入力の作り方を見直す)")

    def test_nan_case_is_really_covered(self):
        """コイル幅 0 の組(JS は「NaN m」と出していた)を、本当に突き合わせている。"""
        js = self.original["coil"][1]
        self.assertEqual(js["results"]["length"], "NaN m")
        self.assertEqual(calc.coil_view(self.coil_cases[1])["results"]["length"], "NaN m")


if __name__ == "__main__":
    unittest.main()
