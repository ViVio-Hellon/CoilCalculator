"""要求1件の答え方(`coilcalc/web.py`)── デスクトップ版・ブラウザ版で共通"""
from __future__ import annotations

import json
import threading
import unittest

from tests._helpers import ROOT  # noqa: F401
from coilcalc import web

HOSTS = ("127.0.0.1:8741", "localhost:8741")
COIL = {"thickness": "400", "inner-diameter": "557", "coil-width": "1250",
        "specific-gravity": "2.70", "plate-thickness": "1.00"}


def req(method, path, body=None, **headers):
    data = b"" if body is None else json.dumps(body).encode("utf-8")
    h = {"host": HOSTS[0]}
    if method == "POST":
        h["content-type"] = "application/json"
    h.update({k.replace("_", "-"): v for k, v in headers.items()})
    return web.Request(method=method, path=path, headers=h, body=data)


def payload(res):
    return json.loads(res.body.decode("utf-8"))


class DesktopModeTest(unittest.TestCase):
    def setUp(self):
        self.stopped = threading.Event()
        self.app = web.App(web.MODE_DESKTOP, on_shutdown=self.stopped.set)

    def test_health_and_spec(self):
        body = payload(self.app.handle(req("GET", "/api/health")))
        self.assertEqual(body["mode"], "desktop")
        self.assertTrue(body["version"])
        self.assertIn("coil", payload(self.app.handle(req("GET", "/api/spec"))))

    def test_calc_routes(self):
        res = self.app.handle(req("POST", "/api/coil/calc", {"fields": COIL}))
        self.assertEqual(res.status, 200)
        self.assertEqual(payload(res)["results"]["windings"], "400 巻")
        res = self.app.handle(req("POST", "/api/plate/calc", {"fields": {"a": "1"}}))
        self.assertEqual(res.status, 200, "範囲の外はふつうの答え(断りにしない)")
        self.assertFalse(payload(res)["ok"])

    def test_bad_bodies_are_400(self):
        bad = web.Request("POST", "/api/coil/calc", headers={"content-type": "application/json"},
                          body=b"{not json")
        self.assertEqual(self.app.handle(bad).status, 400)
        self.assertEqual(self.app.handle(req("POST", "/api/coil/calc", {"fields": [1]})).status, 400)
        self.assertEqual(self.app.handle(req("POST", "/api/coil/calc", [1])).status, 400)
        self.assertEqual(self.app.handle(req("GET", "/api/nothing")).status, 404)
        self.assertEqual(self.app.handle(req("POST", "/api/nothing", {})).status, 404)

    def test_shutdown_never_stops_without_a_real_yes(self):
        """「終了」の確かめが、いつの間にか「はい」になっていないか。

        確かめ無し・「やめる」相当・true 以外の値では**止まらない**。止まるのは
        画面か外枠が利用者に訊いて「終了する」を選び、confirmed: true を付けたときだけ。
        """
        for body in ({}, {"confirmed": False}, {"confirmed": "yes"}, {"confirmed": 1},
                     {"confirmed": "true"}, {"forced": True}, None):
            with self.subTest(body=body):
                res = self.app.handle(req("POST", "/api/shutdown", body))
                self.assertEqual(res.status, 409)
                ask = payload(res)["confirm"]
                self.assertEqual(ask["message"], web.QUIT_CONFIRM[web.MODE_DESKTOP])
                self.assertEqual((ask["yes"], ask["no"]), ("終了する", "やめる"))
        self.assertFalse(self.stopped.wait(0.5), "確かめ無しで止まってはいけない")
        self.assertFalse(self.app.stopping)

    def test_shutdown_after_confirmation_calls_back_once(self):
        res = self.app.handle(req("POST", "/api/shutdown", {"confirmed": True}))
        self.assertEqual(res.status, 200)
        self.assertTrue(self.stopped.wait(2))
        self.assertTrue(self.app.stopping)

    def test_browser_and_desktop_ask_with_their_own_words_from_one_place(self):
        browser = web.App(web.MODE_BROWSER, allowed_hosts=HOSTS)
        res = browser.handle(req("POST", "/api/shutdown", {}))
        self.assertEqual(res.status, 409)
        self.assertEqual(payload(res)["confirm"]["message"], web.QUIT_CONFIRM[web.MODE_BROWSER])
        self.assertFalse(browser.stopping)

    def test_static_files_stay_inside(self):
        res = self.app.handle(req("GET", "/"))
        self.assertEqual(res.status, 200)
        self.assertIn(("Content-Security-Policy", web.CSP), res.headers)
        js = self.app.handle(req("GET", "/coil/app-shell.js"))
        self.assertEqual(dict(js.headers)["Content-Type"], "text/javascript; charset=utf-8")
        for path in ("/../config/app.json", "/%2e%2e/config/app.json", "/coil/..%5C..%5Cbridge.py",
                     "/nothing.js", "/coil/%00x"):
            with self.subTest(path=path):
                self.assertEqual(self.app.handle(req("GET", path)).status, 404)
        self.assertEqual(self.app.handle(req("POST", "/index.html", {})).status, 405)

    def test_client_error_is_logged(self):
        with self.assertLogs("coilcalc.web", "WARNING") as logs:
            self.app.handle(req("POST", "/api/client-error", {"message": "boom", "where": "x.js:1"}))
        self.assertIn("boom", logs.output[0])

    def test_heartbeat_touches(self):
        self.assertFalse(self.app.seen_page)
        self.app.handle(req("POST", "/api/heartbeat", {}))
        self.assertTrue(self.app.seen_page)
        self.assertLess(self.app.idle_seconds(), 1)


class BrowserGuardTest(unittest.TestCase):
    """ブラウザ版の守り(127.0.0.1 で待ち受けるので、よその画面から叩かれうる)"""

    def setUp(self):
        self.app = web.App(web.MODE_BROWSER, allowed_hosts=HOSTS)

    def test_same_origin_passes(self):
        res = self.app.handle(req("POST", "/api/coil/calc", {"fields": COIL},
                                  origin="http://127.0.0.1:8741"))
        self.assertEqual(res.status, 200)
        self.assertEqual(self.app.handle(req("GET", "/api/health", host="localhost:8741")).status, 200)

    def test_foreign_host_is_refused(self):
        # DNS リバインディング: 名前は他所、届く先は 127.0.0.1
        self.assertEqual(self.app.handle(req("GET", "/", host="evil.example:8741")).status, 403)

    def test_foreign_origin_and_non_json_are_refused(self):
        res = self.app.handle(req("POST", "/api/shutdown", {"confirmed": True}, origin="http://evil.example"))
        self.assertEqual(res.status, 403)
        self.assertFalse(self.app.stopping)
        plain = req("POST", "/api/shutdown", {"confirmed": True})
        plain.headers["content-type"] = "text/plain"
        self.assertEqual(self.app.handle(plain).status, 400)
        self.assertFalse(self.app.stopping)


if __name__ == "__main__":
    unittest.main()
