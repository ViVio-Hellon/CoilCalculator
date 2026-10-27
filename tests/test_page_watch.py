"""ブラウザ版の「画面が居なくなったら終わる」(`coilcalc/page_watch.py`・`start_app.watch_idle`)

スリープ明け・タブの休止で、使っている最中に終わってしまう不具合(梱包資材総合ツール・日報で
実際に起きた。同じ作りのこちらも、時計を飛ばすと再現した)を、時計を差し替えて確かめる。
"""
from __future__ import annotations

import threading
import time
import unittest
from unittest import mock

from tests._helpers import ROOT  # noqa: F401
from coilcalc import page_watch, web
from coilcalc.page_watch import CLOSED, HIDDEN, VISIBLE, PageWatch
import start_app


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def go(self, seconds: float) -> None:
        self.t += seconds


def watch(clock: Clock, *, idle=90, grace=180, closing=15) -> PageWatch:
    return PageWatch(idle=idle, grace=grace, closing=closing, clock=clock)


class DecideTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.w = watch(self.clock)

    def test_waits_for_the_first_page(self):
        self.clock.go(170)
        self.assertEqual(self.w.reason_to_exit(), "")
        self.clock.go(20)
        self.assertIn("最初の画面", self.w.reason_to_exit())

    def test_visible_page_that_stops_beating_ends_after_idle(self):
        self.w.beat("a", VISIBLE)
        self.clock.go(89)
        self.assertEqual(self.w.reason_to_exit(), "")
        self.clock.go(2)
        self.assertIn("知らせがありません", self.w.reason_to_exit())

    def test_hidden_page_is_alive_even_without_beats(self):
        """裏に回したタブ(Edge のスリープ中のタブ・Chrome の間引き)で終わらない"""
        self.w.beat("a", VISIBLE)
        self.w.beat("a", HIDDEN)
        self.clock.go(6 * 3600)
        self.assertEqual(self.w.reason_to_exit(), "")
        self.assertEqual(self.w.alive_pages(), 1)
        # 表に戻れば、また心拍で数える
        self.w.beat("a", VISIBLE)
        self.clock.go(91)
        self.assertIn("知らせがありません", self.w.reason_to_exit())

    def test_closing_ends_after_a_short_wait(self):
        self.w.beat("a", VISIBLE)
        self.w.beat("a", CLOSED)
        self.clock.go(10)
        self.assertEqual(self.w.reason_to_exit(), "", "読み直した画面が来るのを待つ")
        self.clock.go(10)
        self.assertEqual(self.w.reason_to_exit(), "画面を閉じました")

    def test_hidden_arriving_after_closed_does_not_revive(self):
        """タブを閉じると hidden と closed が続けて届き、順番は約束されない"""
        self.w.beat("a", VISIBLE)
        self.w.beat("a", CLOSED)
        self.w.beat("a", HIDDEN)
        self.clock.go(20)
        self.assertEqual(self.w.reason_to_exit(), "画面を閉じました")

    def test_reload_does_not_end(self):
        self.w.beat("old", VISIBLE)
        self.w.beat("old", CLOSED)
        self.clock.go(1)
        self.w.beat("new", VISIBLE)
        self.clock.go(60)
        self.assertEqual(self.w.reason_to_exit(), "")

    def test_closing_one_of_two_pages_does_not_end(self):
        self.w.beat("a", VISIBLE)
        self.w.beat("b", HIDDEN)
        self.w.beat("a", CLOSED)
        self.clock.go(3600)
        self.assertEqual(self.w.reason_to_exit(), "", "もう1つ(裏のタブ)が開いている")
        self.w.beat("b", CLOSED)
        self.clock.go(20)
        self.assertEqual(self.w.reason_to_exit(), "画面を閉じました")

    def test_back_forward_cache_revives(self):
        self.w.beat("a", CLOSED)
        self.w.beat("a", VISIBLE)
        self.clock.go(30)
        self.assertEqual(self.w.reason_to_exit(), "")

    def test_paused_time_is_not_counted(self):
        """Windows はスリープ中も時計が進む。止まっていた分を差し引く"""
        self.w.beat("a", VISIBLE)
        self.clock.go(5)
        self.clock.go(600)                       # 10分スリープ
        self.assertNotEqual(self.w.reason_to_exit(), "", "差し引かなければ終わってしまう")
        self.w.note_pause(600)
        self.assertEqual(self.w.reason_to_exit(), "")
        self.clock.go(80)
        self.assertEqual(self.w.reason_to_exit(), "", "眠る前の続きから数える(5 + 80 秒)")
        self.clock.go(10)
        self.assertNotEqual(self.w.reason_to_exit(), "")

    def test_zero_idle_means_never(self):
        w = watch(self.clock, idle=0)
        w.beat("a", CLOSED)
        self.clock.go(10 ** 6)
        self.assertEqual(w.reason_to_exit(), "")

    def test_old_pages_without_number_still_count(self):
        """古い画面(読み直す前のタブ)は番号なし・本文なしで心拍を送る"""
        app = web.App(web.MODE_BROWSER, allowed_hosts=("127.0.0.1:8741",))
        app.pages = watch(self.clock)
        app.handle(web.Request(method="POST", path="/api/heartbeat", body=b"{}",
                               headers={"host": "127.0.0.1:8741", "content-type": "application/json"}))
        self.assertTrue(app.seen_page)
        self.clock.go(60)
        self.assertEqual(app.pages.reason_to_exit(), "")


class WatcherTest(unittest.TestCase):
    """start_app.watch_idle: 見張りの間隔が空いたら止まっていたとみなす"""

    def run_watch(self, app, browser, during):
        stopped = threading.Event()
        t = threading.Thread(target=start_app.watch_idle, args=(app, stopped, browser), daemon=True)
        t.start()
        try:
            during(t)
        finally:
            stopped.set()
            t.join(5)

    def test_sleep_and_wake_does_not_end(self):
        clock = Clock()
        app = web.App(web.MODE_BROWSER)
        app.pages = watch(clock)
        app.pages.beat("a", VISIBLE)

        def during(t):
            time.sleep(1.5)
            clock.go(600)                        # 10分スリープ(Windows は時計が進む)
            time.sleep(2.5)
            self.assertTrue(t.is_alive(), "起きた瞬間に終わってはいけない")
        with mock.patch.object(start_app.time, "monotonic", clock):
            self.run_watch(app, {"idle_exit_seconds": 90, "first_open_grace_seconds": 180}, during)

    def test_hidden_page_survives_and_closing_ends(self):
        app = web.App(web.MODE_BROWSER)
        app.pages.beat("a", HIDDEN)
        browser = {"idle_exit_seconds": 0.5, "first_open_grace_seconds": 30, "closed_exit_seconds": 0.5}

        def during(t):
            time.sleep(2.5)
            self.assertTrue(t.is_alive(), "裏のタブは心拍が無くても生きている")
            app.pages.beat("a", CLOSED)
            t.join(5)
            self.assertFalse(t.is_alive(), "閉じたら終わる")
        self.run_watch(app, browser, during)

    def test_pause_threshold(self):
        self.assertGreaterEqual(page_watch.PAUSE_SECONDS, 10)


if __name__ == "__main__":
    unittest.main()
