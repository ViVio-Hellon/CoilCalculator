"""VC長さ計算の画面(外の枠 index.html と vc/*.js)── ブラウザが無くても見られる配線

日報管理ツールの `tests/test_web_vc.py`(ScreenTests・WiringTests・SettingsTabTests の画面の部分)と
`tests/test_vc_quick_window.py` を、このツールの画面(静的な HTML + JS)に写したもの。
実際にブラウザで押して確かめるのは scripts/manual/shoot_browser.cjs(説明書の写真を撮るときに
計算・早見表・設定・マスタの表・コイル・平板を一通り押す)と desktop_smoke.py。
"""
from __future__ import annotations

import re
import unittest

from tests._helpers import ROOT

from coilcalc.vc import view

STATIC = ROOT / "app" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
VC_JS = (STATIC / "vc" / "vc.js").read_text(encoding="utf-8")
CSS = (STATIC / "vc" / "vc.css").read_text(encoding="utf-8")


def panel(key: str) -> str:
    start = HTML.index(f'data-panel="{key}"')
    nxt = HTML.find('data-panel="', start + 10)
    return HTML[start:nxt if nxt > 0 else len(HTML)]


class ShellTests(unittest.TestCase):
    def test_tabs_follow_the_server_order(self):
        keys = re.findall(r'<button class="tab" type="button" role="tab" data-key="(\w+)"', HTML)
        self.assertEqual(keys[:4], [k for k, _l, _n in view.TABS])
        self.assertEqual(keys, ["calc", "quick", "coil", "settings", "master"])
        for key in keys:
            self.assertIn(f'id="panel-{key}"', HTML)
        self.assertIn('data-key="calc" data-default="1"', HTML)

    def test_coil_is_loaded_when_opened(self):
        """コイル・平板は開いたときに読み込む(3D とグラフのライブラリは大きい)。"""
        self.assertRegex(panel("coil"), r'<iframe class="vc-coilframe" id="vc-coil-frame"[^>]*data-src="coil/index.html"')
        self.assertNotRegex(panel("coil"), r'<iframe[^>]*\ssrc=')
        self.assertIn('frame.setAttribute("src", frame.dataset.src)', VC_JS)

    def test_framed_coil_hides_its_own_tools(self):
        shell_js = (STATIC / "coil" / "app-shell.js").read_text(encoding="utf-8")
        self.assertIn("window.parent.document.getElementById('vcTabs')", shell_js)
        css = (STATIC / "coil" / "app-shell.css").read_text(encoding="utf-8")
        self.assertIn("html.is-framed .app-tools", css)
        theme = (STATIC / "coil" / "coil-theme.js").read_text(encoding="utf-8")
        self.assertIn("window.addEventListener('storage'", theme)

    def test_manual_page_follows_the_tab(self):
        shell_js = (STATIC / "coil" / "app-shell.js").read_text(encoding="utf-8")
        self.assertIn("if (!on || on.dataset.key !== 'coil') return 'vc';", shell_js)


class CalcAndQuickTests(unittest.TestCase):
    def test_calc_parts(self):
        for id_ in ("vc-products", "vc-insides", "vc-inside-choices", "vc-form", "vc-coatu", "vc-vcatu",
                    "vc-inside", "vc-vclen", "vc-prolen", "vc-run", "vc-open-quick", "vc-out-length",
                    "vc-counts", "vc-explain", "vc-roll", "vc-steps", "vc-calc-error"):
            self.assertIn(f'id="{id_}"', panel("calc"), id_)

    def test_grid_maker_is_in_settings_not_quick(self):
        self.assertNotIn('id="vc-grid"', panel("quick"))
        self.assertIn('data-vc-tab="settings"', panel("quick"))
        self.assertIn('id="vc-grid"', panel("settings"))
        self.assertIn('id="vc-place"', panel("settings"))

    def test_tab_select_is_not_shadowed(self):
        """vc.js には品種を選ぶ `select` がある。面を替える `select` と取り違えない。"""
        self.assertIn("select as selectTab", VC_JS)
        self.assertIn("selectTab(root, link.dataset.vcTab)", VC_JS)

    def test_quick_window_is_quick_only(self):
        """早見表だけの窓: 見出しも面の札も出さない(VBA の UFquick)。"""
        main = (STATIC / "vc" / "main.js").read_text(encoding="utf-8")
        self.assertIn('params.get("window") === "quick"', main)
        self.assertIn("body.is-bare .vc-top, body.is-bare #vcTabs > .tabs__bar", CSS)
        self.assertIn('window.open("/index.html?window=quick&tab=quick"', VC_JS)
        self.assertIn('invoke("open_quick")', VC_JS)
        rust = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
        self.assertIn('app_url("/index.html?window=quick&tab=quick")', rust)
        self.assertIn("generate_handler![open_manual, open_quick]", rust)
        caps = (ROOT / "src-tauri" / "capabilities" / "default.json").read_text(encoding="utf-8")
        self.assertIn('"quick"', caps)


class SettingsAndMasterTests(unittest.TestCase):
    def test_settings_parts(self):
        settings = panel("settings")
        for id_ in ("vc-place-status", "vc-place-names", "vc-place-used", "vc-place-origin", "vc-place-dir",
                    "vc-place-save", "vc-place-reset", "vc-blocks", "vc-add-product", "vc-add-make",
                    "vc-add-tone", "vc-edit-kind", "vc-edit-source", "vc-edit-insides", "vc-edit-delete",
                    "vc-del-product", "vc-del-product-go", "vc-grid-make", "vc-grid-length", "vc-grid-vcatu",
                    "vc-grid-fill", "vc-grid-overwrite", "vc-grid-unlock", "vc-grid-relock",
                    "vc-admin-current", "vc-admin-new", "vc-admin-confirm", "vc-admin-change", "vc-admin-reset"):
            self.assertIn(f'id="{id_}"', settings, id_)
        self.assertIn("早見表の品種(枠とマス)", settings)
        # 消す前に、何が消えるかを数で言う
        self.assertIn("の枠とマス ${b.cells} を消します", VC_JS)
        self.assertIn("固定値(打った長さ)", VC_JS)
        self.assertIn('fill_empty: $("vc-grid-fill").checked', VC_JS)

    def test_master_parts(self):
        master = panel("master")
        for id_ in ("vc-tables-password", "vc-tables-unlock", "vc-tables-relock", "vc-tables-pick",
                    "vc-tables-q", "vc-tables-grid", "vc-tables-msg"):
            self.assertIn(f'id="{id_}"', master, id_)

    def test_every_api_the_screen_calls_exists(self):
        """画面が呼ぶ /api/vc/… は、どれもサーバにある(綴りの違いで 404 にならない)。"""
        names = set()
        for js in (STATIC / "vc").glob("*.js"):
            names |= set(re.findall(r'"(/api/vc/[a-z\-/]+)', js.read_text(encoding="utf-8")))
        self.assertGreaterEqual(len(names), 15)
        source = (ROOT / "coilcalc" / "vc_api.py").read_text(encoding="utf-8")
        for name in sorted(names):
            with self.subTest(api=name):
                self.assertIn(f'"{name[len("/api/vc/"):].rstrip("?")}"', source)


class TablesScreenTests(unittest.TestCase):
    """マスタの表(vc_tables.js)── 読み合わせで見つかった不具合が戻らないように。"""

    JS = (STATIC / "vc" / "vc_tables.js").read_text(encoding="utf-8")

    def test_stale_reply_does_not_overwrite_newer_choice(self):
        self.assertIn("const mine = ++asked;", self.JS)
        self.assertIn("if (mine !== asked) return;", self.JS)

    def test_message_is_cleared_when_a_table_is_loaded(self):
        load = self.JS[self.JS.index("async function load()"):self.JS.index("async function setKey")]
        self.assertIn('note("");', load)

    def test_writes_keep_the_sort(self):
        self.assertIn("sort: sortCol, dir: sortDir, ...payload", self.JS)

    def test_fixed_rows_reason_is_shown(self):
        self.assertIn("body.fixed_why", self.JS)


class DoublePressTests(unittest.TestCase):
    def test_pressed_button_waits_for_the_reply(self):
        api = (STATIC / "vc" / "api.js").read_text(encoding="utf-8")
        self.assertIn('options.method === "POST" ? holdPressed()', api)
        self.assertIn('button.dataset.busy === "1"', api)

    def test_quick_window_does_not_depend_on_the_version_reply(self):
        """デスクトップ版の起動直後(版の返事より前)に押しても、外枠に窓を頼む。"""
        self.assertIn('typeof tauri.core.invoke === "function"', VC_JS)
        self.assertNotIn('dataset.mode === "desktop" && tauri', VC_JS)


class CoilFitTests(unittest.TestCase):
    """コイル・平板を切り替えると画面が揺れ続けた件(画面に収める仕組みの行き来)。

    カード・入力欄の余白は 0.3 秒かけて変わる。動いている途中の高さをはかっていたので、
    枠の高さがある幅(例: 1920×950 の窓で 818px、デスクトップ版の窓で約 808px)に入ると
    「そのまま」と「詰める」を毎コマ行き来した。窓の大きさを 10px 刻みで総当たりして
    落ち着くことはブラウザで確かめた(Playwright。ヘッドレスでは動きの時計が止まるので、
    動きの途中の値で止まったまま = 揺れがいちばん出やすい形で確かめている)。
    """

    def test_measuring_stops_transitions(self):
        css = (STATIC / "coil" / "coil-fit.css").read_text(encoding="utf-8")
        block = css[css.index("html.fit-measure,\nhtml.fit-measure *,"):]
        self.assertIn("transition: none !important;", block[:300])

    def test_flip_guard(self):
        js = (STATIC / "coil" / "coil-fit.js").read_text(encoding="utf-8")
        self.assertIn("const FLIP_LIMIT = 4;", js)
        self.assertIn("heldUntil = now + FLIP_WINDOW_MS;", js)
        # 窓の大きさを変えたら歯止めを外す(新しい大きさで決め直す)
        self.assertIn("window.addEventListener('resize', () => { heldUntil = 0; flips = []; later(); });", js)


class WiringTests(unittest.TestCase):
    def test_class_names_do_not_collide(self):
        """VC の部品は `vc-` で始める(コイル・平板の .tab / .result-card などと混ざらない)。"""
        for name in re.findall(r'className = "([^"]+)"', VC_JS):
            for part in name.split():
                if part in ("btn", "lead", "corner", "num", "badge", "badge--done", "badge--todo"):
                    continue
                self.assertTrue(part.startswith("vc-") or part.startswith("msg"), part)

    def test_print_is_scoped(self):
        """早見表の紙の形はほかの印刷に効かせない(名前つきの頁・刷るあいだだけ)。"""
        self.assertIn("@page vcquick{", CSS)
        self.assertNotRegex(CSS, r"@page\s*\{\s*size:\s*A4 landscape")
        self.assertIn('document.body.classList.add("vc-printing")', VC_JS)
        self.assertIn("onLeave(endPrint)", VC_JS)

    def test_colors_come_from_tokens(self):
        """色は変数に寄せる。ライトとダークの2か所にある。"""
        light = CSS[CSS.index(":root{"):CSS.index("}", CSS.index(":root{"))]
        start = CSS.index(':root[data-theme="dark"]{')
        dark = CSS[start:CSS.index("}", start)]
        for name in ("--vc-roll-hl", "--vc-tone-navy", "--vc-choose-bg", "--surface", "--ink"):
            self.assertIn(f"{name}:", light, name)
            self.assertIn(f"{name}:", dark, name)

    def test_css_blocks_are_balanced(self):
        """CSS の { } が釣り合っている(途中で切れると、そこから下が全部効かない)。"""
        text = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
        self.assertNotIn("/*", text)
        depth = 0
        for ch in text:
            depth += {"{": 1, "}": -1}.get(ch, 0)
            self.assertGreaterEqual(depth, 0)
        self.assertEqual(depth, 0)


if __name__ == "__main__":
    unittest.main()
