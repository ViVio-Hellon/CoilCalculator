"""JS と同じ文字を出す数の扱い(`coilcalc/jsnum.py`)

期待値は Chrome / Edge / node(V8)で実際に出る文字。node が無くても走るよう、
ここには書き写した値を置く(node での突き合わせは test_js_equivalence.py)。
"""
from __future__ import annotations

import math
import unittest

from tests._helpers import ROOT  # noqa: F401  (sys.path を整える)
from coilcalc.jsnum import format_number, js_div, js_round, js_str, json_number, parse_float, to_fixed


class ToFixedTest(unittest.TestCase):
    def test_half_goes_away_from_zero_on_exact_binary_value(self):
        # 2.5 は2進でちょうど → 0 から遠い側(Python の round/format は偶数側で "2")
        self.assertEqual(to_fixed(2.5, 0), "3")
        self.assertEqual(to_fixed(0.125, 2), "0.13")
        # 1.005 は2進で 1.00499… → 切り捨て側(JS も "1.00")
        self.assertEqual(to_fixed(1.005, 2), "1.00")
        self.assertEqual(to_fixed(-2.5, 0), "-3")

    def test_zero_nan_inf_and_huge(self):
        self.assertEqual(to_fixed(-0.0, 1), "0.0")
        self.assertEqual(to_fixed(-0.04, 1), "-0.0")
        self.assertEqual(to_fixed(math.nan, 1), "NaN")
        self.assertEqual(to_fixed(math.inf, 2), "Infinity")
        self.assertEqual(to_fixed(1e21, 2), "1e+21")


class JsStrTest(unittest.TestCase):
    def test_like_template_literal(self):
        cases = {400.0: "400", 0.05: "0.05", 1e-05: "0.00001", 1.5e-07: "1.5e-7",
                 1e16: "10000000000000000", 1e21: "1e+21", 1.2345e20: "123450000000000000000",
                 0.1 + 0.2: "0.30000000000000004", 1e-6: "0.000001", 1e-7: "1e-7",
                 -2.5: "-2.5", -0.0: "0", 5e-324: "5e-324", math.nan: "NaN", -math.inf: "-Infinity"}
        for value, text in cases.items():
            with self.subTest(value=value):
                self.assertEqual(js_str(value), text)
        self.assertEqual(js_str(3), "3")


class RoundDivParseTest(unittest.TestCase):
    def test_math_round(self):
        self.assertEqual(js_round(2.5), 3)
        self.assertEqual(js_round(-2.5), -2)
        self.assertEqual(js_round(0.49999999999999994), 0)
        self.assertTrue(math.isnan(js_round(math.nan)))

    def test_division_never_raises(self):
        self.assertTrue(math.isnan(js_div(0.0, 0.0)))
        self.assertEqual(js_div(1.0, 0.0), math.inf)
        self.assertEqual(js_div(-1.0, 0.0), -math.inf)
        self.assertEqual(js_div(1.0, -0.0), -math.inf)
        self.assertEqual(js_div(3.0, 2.0), 1.5)

    def test_parse_float_reads_leading_number(self):
        self.assertEqual(parse_float("  12abc"), 12)
        self.assertEqual(parse_float(".5e3x"), 500)
        self.assertEqual(parse_float("1e"), 1)
        self.assertEqual(parse_float("+7"), 7)
        self.assertEqual(parse_float("　 3.5"), 3.5)
        self.assertEqual(parse_float("-Infinityx"), -math.inf)
        for text in ("", "abc", "-", ".", "e5"):
            with self.subTest(text=text):
                self.assertTrue(math.isnan(parse_float(text)))


class FormatNumberTest(unittest.TestCase):
    def test_commas_like_the_screen(self):
        self.assertEqual(format_number(1234567.891), "1,234,567.9")
        self.assertEqual(format_number(1506051306.4, 0), "1,506,051,306")
        self.assertEqual(format_number(2.0, 3), "2.000")
        self.assertEqual(format_number(math.nan), "NaN")
        # 小数が4桁以上だと小数の側にもカンマが入る(元の正規表現のまま。画面は3桁まで)
        self.assertEqual(format_number(1.23456, 5), "1.23,456")

    def test_json_number(self):
        self.assertIsNone(json_number(math.nan))
        self.assertIsNone(json_number(math.inf))
        self.assertEqual(json_number(1.5), 1.5)


if __name__ == "__main__":
    unittest.main()
