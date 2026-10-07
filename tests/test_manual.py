"""操作説明書(`app/static/manual/`)と版の表示

- 説明書の頁がそろっていて、ツールから開く頁(コイル・平板)と外枠(Rust)が開ける頁が一致する
- 写真がすべてあり、使っていない写真が無く、<img> の大きさが写真と同じ
- 説明書の版がツールの版と同じ(版を上げたら説明書も見直す)
- インターネットから読まない・HTML の中にスクリプトを書かない(CSP)・頁どうしのリンクが切れていない
- 画面に版と「操作説明」がある。版は Python(/api/health)・外枠(見出し)から出す
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

from tests._helpers import ROOT
from coilcalc import web

sys.path.insert(0, str(ROOT / "scripts"))
from make_manual_images import image_size  # noqa: E402

MANUAL = ROOT / "app" / "static" / "manual"
PAGES = ("index", "vc", "coil", "plate")
VERSION = json.loads((ROOT / "config" / "app.json").read_text(encoding="utf-8"))["version"]


def page(name: str) -> str:
    return (MANUAL / f"{name}.html").read_text(encoding="utf-8")


class ManualPagesTest(unittest.TestCase):
    def test_pages_match_what_the_tool_and_rust_open(self):
        self.assertEqual(sorted(p.stem for p in MANUAL.glob("*.html")), sorted(PAGES))
        rust = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
        listed = re.search(r'const MANUAL_PAGES: \[&str; \d+\] = \[(.*?)\];', rust).group(1)
        self.assertEqual(sorted(re.findall(r'"(\w+)"', listed)), sorted(PAGES))
        shell = (ROOT / "app" / "static" / "coil" / "app-shell.js").read_text(encoding="utf-8")
        self.assertIn("window.open(`/manual/${page}.html`", shell)
        self.assertIn("invoke('open_manual', { page })", shell)

    def test_version_is_the_tools_version(self):
        for name in PAGES:
            with self.subTest(page=name):
                shown = re.findall(r"<span data-manual-version>v([^<]+)</span>", page(name))
                self.assertTrue(shown)
                self.assertEqual(set(shown), {VERSION}, "版を上げたら説明書も見直して版を直す")

    def test_images_exist_are_used_and_sized(self):
        used = set()
        for name in PAGES:
            for tag in re.findall(r"<img [^>]*>", page(name)):
                src = re.search(r'src="([^"]+)"', tag).group(1)
                used.add(src)
                with self.subTest(page=name, src=src):
                    self.assertRegex(tag, r'alt="[^"]+"', "写真には何が写っているかを書く")
                    path = MANUAL / src
                    self.assertTrue(path.is_file(), src)
                    w = int(re.search(r'width="(\d+)"', tag).group(1))
                    h = int(re.search(r'height="(\d+)"', tag).group(1))
                    self.assertEqual((w, h), image_size(path), "make_manual_images.py で撮り直すと直る")
        files = {f"img/{p.name}" for p in (MANUAL / "img").iterdir()}
        self.assertEqual(files - used, set(), "使っていない写真がある")

    def test_local_only_no_inline_script_and_links_resolve(self):
        for name in PAGES:
            html = page(name)
            with self.subTest(page=name):
                for ref in re.findall(r'(?:src|href)="([^"]+)"', html):
                    self.assertNotRegex(ref, r"^(https?:)?//", "ラインPCはインターネットに出られない")
                    target, _, anchor = ref.partition("#")
                    target_html = page(Path(target).stem) if target.endswith(".html") else html
                    if target and not target.endswith(".html"):
                        self.assertTrue((MANUAL / target).is_file(), ref)
                    if anchor:
                        self.assertIn(f'id="{anchor}"', target_html, ref)
                for tag in re.findall(r"<script[^>]*>", html):
                    self.assertIn("src=", tag, "CSP は script-src 'self'")
                self.assertIn('aria-current="page"', html)

    def test_served_with_csp(self):
        app = web.App(web.MODE_DESKTOP)
        for name in PAGES:
            res = app.handle(web.Request("GET", f"/manual/{name}.html"))
            self.assertEqual(res.status, 200)
            self.assertIn(("Content-Security-Policy", web.CSP), res.headers)
        img = app.handle(web.Request("GET", "/manual/img/coil-overview.jpg"))
        self.assertEqual(dict(img.headers)["Content-Type"], "image/jpeg")


class VersionDisplayTest(unittest.TestCase):
    def test_health_reports_versions(self):
        app = web.App(web.MODE_DESKTOP)
        body = json.loads(app.handle(web.Request("GET", "/api/health")).body)
        self.assertEqual(body["version"], VERSION)
        self.assertEqual(body["python"], ".".join(map(str, sys.version_info[:3])))

    def test_screen_has_version_and_manual_button(self):
        html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
        for element in ('id="app-version"', 'id="app-version-text"', 'id="app-version-panel"',
                        'id="app-help"', 'id="app-quit"'):
            self.assertIn(element, html)

    def test_rust_adds_shell_version_and_window_titles(self):
        rust = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
        self.assertIn('header("X-Coil-Shell-Version", VERSION)', rust)
        self.assertIn('env!("CARGO_PKG_VERSION")', rust)
        self.assertIn('.title(format!("{TITLE} v{VERSION}"))', rust)
        shell = (ROOT / "app" / "static" / "coil" / "app-shell.js").read_text(encoding="utf-8")
        self.assertIn("res.headers.get('X-Coil-Shell-Version')", shell)

    def test_print_sheet_carries_version(self):
        js = (ROOT / "app" / "static" / "coil" / "print-sheet.js").read_text(encoding="utf-8")
        self.assertIn("document.documentElement.dataset.version", js)


if __name__ == "__main__":
    unittest.main()
