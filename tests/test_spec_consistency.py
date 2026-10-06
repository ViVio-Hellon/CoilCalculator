"""同じ事実を2か所に持たない ── 持つしかないところは、食い違わないことを試験で押さえる

- 入力の範囲: 正は coilcalc/calc.py。画面(index.html)の「※0〜600」・min/max・エラーの文
- グラフの軸の選択肢: calc.py の COIL_CHART_X/Y・PLATE_CHART_X/Y
- 計算の経過・モーダルを置く場所(id): calc.py が返す id が index.html にある
- 版: config/app.json・src-tauri/Cargo.toml・src-tauri/tauri.conf.json
- 画面が読むファイルがすべてある・インターネットから読まない・HTML の中にスクリプトを書かない(CSP)
- CSP: Python(web.py)と Rust(static_files.rs)で同じ
"""
from __future__ import annotations

import json
import re
import unittest

from tests._helpers import ROOT
from coilcalc import calc, web

STATIC = ROOT / "app" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")


def num(text: str) -> float:
    return float(text)


class RangesTest(unittest.TestCase):
    def check_fields(self, fields, prefix):
        for name, lo, hi, label, unit in fields:
            element = prefix + name if prefix and name != "specific-gravity" else (
                "plate-specific-gravity" if prefix else name)
            with self.subTest(field=element):
                tag = re.search(rf'<input type="number" id="{element}"[^>]*>', HTML).group(0)
                self.assertEqual(num(re.search(r'min="([^"]+)"', tag).group(1)), lo)
                self.assertEqual(num(re.search(r'max="([^"]+)"', tag).group(1)), hi)
                lab = re.search(rf'<label for="{element}">(.*?)</label>', HTML).group(1)
                self.assertIn(label, lab)
                self.assertIn(unit, lab)
                shown = re.search(r"※([\d.]+)〜([\d.]+)", lab)
                self.assertEqual((num(shown.group(1)), num(shown.group(2))), (lo, hi))
                err = re.search(rf'id="{element}-error"[^>]*>([\d.]+)〜([\d.]+)の範囲', HTML)
                self.assertEqual((num(err.group(1)), num(err.group(2))), (lo, hi))

    def test_coil(self):
        self.check_fields(calc.COIL_FIELDS, "")

    def test_plate(self):
        self.check_fields(calc.PLATE_FIELDS, "plate-")

    def test_chart_axes(self):
        def options(select_id):
            block = re.search(rf'<select id="{select_id}".*?</select>', HTML, re.S).group(0)
            return re.findall(r'<option value="([^"]+)"', block)
        self.assertEqual(options("x-axis-param"), list(calc.COIL_CHART_X))
        self.assertEqual(options("y-axis-result"), list(calc.COIL_CHART_Y))
        self.assertEqual(options("plate-x-axis-param"), list(calc.PLATE_CHART_X))
        self.assertEqual(options("plate-y-axis-result"), list(calc.PLATE_CHART_Y))

    def test_returned_ids_exist_in_page(self):
        coil = calc.coil_view({"thickness": "1", "inner-diameter": "300", "coil-width": "1",
                               "specific-gravity": "1", "plate-thickness": "1"})
        plate = calc.plate_view({"a": "1", "b": "1", "t": "1", "specific-gravity": "1"})
        for body in (coil, plate):
            for key in list(body["details"]) + list(body["modal"]):
                with self.subTest(id=key):
                    self.assertIn(f'id="{key}"', HTML)


class PageFilesTest(unittest.TestCase):
    def test_every_referenced_file_exists_and_is_local(self):
        refs = re.findall(r'(?:src|href)="([^"]+)"', HTML)
        self.assertTrue(refs)
        for ref in refs:
            with self.subTest(ref=ref):
                self.assertNotRegex(ref, r"^(https?:)?//", "ラインPCはインターネットに出られない")
                self.assertTrue((STATIC / ref).is_file(), ref)

    def test_no_inline_script(self):
        for tag in re.findall(r"<script[^>]*>", HTML):
            self.assertIn("src=", tag, "CSP は script-src 'self'。HTML の中のスクリプトは動かない")
        self.assertNotRegex(HTML, r"\son[a-z]+=\"", "onclick なども CSP で動かない")

    def test_csp_is_the_same_in_python_and_rust(self):
        rust = (ROOT / "src-tauri" / "src" / "static_files.rs").read_text(encoding="utf-8")
        m = re.search(r'pub const CSP: &str = "(.*?)";', rust, re.S)
        rust_csp = re.sub(r"\\\n\s*", "", m.group(1))
        self.assertEqual(rust_csp, web.CSP)

    def test_app_shell_is_loaded_before_calculators(self):
        self.assertLess(HTML.index('src="coil/app-shell.js"'),
                        HTML.index('src="coil/aluminum-coil-calculator.js"'))
        self.assertLess(HTML.index('src="coil/aluminum-coil-calculator.js"'),
                        HTML.index('src="coil/plate-calculator.js"'), "平板は CoilCalculator.lines を使う")


class VersionTest(unittest.TestCase):
    def test_three_places_agree(self):
        conf = json.loads((ROOT / "config" / "app.json").read_text(encoding="utf-8"))["version"]
        tauri = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))["version"]
        cargo = re.search(r'^version = "([^"]+)"', (ROOT / "src-tauri" / "Cargo.toml")
                          .read_text(encoding="utf-8"), re.M).group(1)
        self.assertEqual({conf, tauri, cargo}, {conf}, "版は3か所。揃えて上げる")


if __name__ == "__main__":
    unittest.main()
