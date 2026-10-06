"""コイル・平板の計算(`coilcalc/calc.py`)── 知っている答えで確かめる"""
from __future__ import annotations

import json
import unittest

from tests._helpers import ROOT  # noqa: F401
from coilcalc import calc

COIL = {"thickness": "400", "inner-diameter": "557", "coil-width": "1250",
        "specific-gravity": "2.70", "plate-thickness": "1.00"}
PLATE = {"a": "1000", "b": "2000", "t": "1.00", "specific-gravity": "2.70"}


class CoilTest(unittest.TestCase):
    def test_default_inputs(self):
        body = calc.coil_view(COIL)
        self.assertTrue(body["ok"])
        self.assertEqual(body["results"], {"weight": "4,058.8 kg", "length": "1,202.6 m",
                                           "windings": "400 巻"})
        self.assertEqual(body["details"]["dimensions-detailed"][0],
                         {"text": "大円柱半径 = (肉厚 × 2 + 内径) / 2 = (400 × 2 + 557) / 2 = ",
                          "value": "678.5 mm"})
        self.assertEqual(body["modal"]["modal-windings"], "= 400 / 1.00 = 400.0 ≈ 400 巻")

    def test_out_of_range_is_not_calculated(self):
        body = calc.coil_view(dict(COIL, thickness="700", **{"plate-thickness": ""}))
        self.assertFalse(body["ok"])
        self.assertEqual(body["invalid"], ["thickness", "plate-thickness"])
        self.assertNotIn("results", body)
        self.assertIsNone(body["values"]["plate-thickness"])   # NaN は JSON に載らない

    def test_zero_width_gives_nan_like_js(self):
        body = calc.coil_view(dict(COIL, **{"coil-width": "0"}))
        self.assertEqual(body["results"]["length"], "NaN m")
        self.assertEqual(body["results"]["weight"], "0.0 kg")
        json.dumps(body, allow_nan=False)                      # 画面へ送れる

    def test_chart_has_21_points_per_axis(self):
        chart = calc.coil_view(COIL)["chart"]
        self.assertEqual(list(chart), list(calc.COIL_CHART_X))
        for x, line in chart.items():
            self.assertEqual(len(line["labels"]), calc.CHART_STEPS + 1)
            self.assertEqual(line["labels"][0], line["min"])
            self.assertAlmostEqual(line["labels"][-1], line["max"])
            self.assertEqual(sorted(line["series"]), sorted(calc.COIL_CHART_Y))
        # コイル幅 0 の点は長さが NaN → null(グラフでは線が途切れる。JS と同じ見た目)
        self.assertIsNone(chart["coil-width"]["series"]["length"][0])


class PlateTest(unittest.TestCase):
    def test_default_inputs(self):
        body = calc.plate_view(PLATE)
        self.assertEqual(body["results"], {"weight": "5.40 kg", "area": "2.000 m²",
                                           "volume": "2,000.0 cm³"})
        self.assertEqual(body["modal"]["plate-modal-area-m"], "= 2,000,000 / 1,000,000 = 2.000 m²")
        self.assertEqual(body["values"]["a"], 1000)

    def test_out_of_range(self):
        body = calc.plate_view(dict(PLATE, t="0.01"))
        self.assertEqual(body["invalid"], ["t"])
        self.assertFalse(body["ok"])


class SpecTest(unittest.TestCase):
    def test_spec_lists_every_field(self):
        spec = calc.spec()
        self.assertEqual([f["name"] for f in spec["coil"]["fields"]],
                         ["thickness", "inner-diameter", "coil-width", "specific-gravity", "plate-thickness"])
        self.assertEqual([f["name"] for f in spec["plate"]["fields"]], ["a", "b", "t", "specific-gravity"])


if __name__ == "__main__":
    unittest.main()
