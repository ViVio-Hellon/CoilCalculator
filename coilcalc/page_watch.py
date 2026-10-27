"""ブラウザ版の「画面が居なくなったら終わる」の見張り ── **画面ごと**に、**起きていた時間だけ**で数える

ブラウザ版は、開いている画面(タブ)が全部居なくなったら自分で終わります(残っているとデスクトップ版が
開けないため)。以前は「心拍が 90 秒途切れたら終わる」だけだったので、次の2つで**使っている最中に**
終わっていました(梱包資材総合ツール・日報で実際に起きた。同じ作りのこちらも同じ)。

    スリープ明け   Windows の time.monotonic() はスリープ中も進む。起きた瞬間「90 秒 心拍が無い」が
                   成り立ち、ブラウザが心拍を送るより先に終わる
    タブの休止     ブラウザは裏のタブのタイマーを間引く・止める(Chrome は5分で1分に1回、Edge の
                   「スリープ中のタブ」・メモリ節約では止める)。心拍が途切れて終わる

【どう数えるか】

画面は自分の番号(開くたびに決める)を添えて、様子を知らせてきます(`/api/heartbeat`)。

    visible   表にいる(数秒ごとの心拍・表に戻った・止まっていたところから戻った)
    hidden    裏に回る・ブラウザに止められる。**このあと心拍が途切れても生きているものとして数える**
    closed    閉じる(読み直しも)。少し待って、ほかに画面が無ければ終わる

    終わる = 生きている画面が1つも無い
             生きている = 閉じていない かつ (hidden と言った か 最後の知らせから idle 秒以内)
             画面がまだ1つも来ていなければ grace 秒、閉じたあとは closing 秒 待つ

タブを閉じるとブラウザは hidden と closed を続けて送るが、**届く順番は約束されない**。後から届いた
hidden で、閉じたことを打ち消さない(戻る/進むの控えから戻ったときは visible が届く)。

**眠っていた時間は数えない**: 見張り(start_app.watch_idle)は1秒ごとに回る。間が `PAUSE_SECONDS`
以上空いたら、そのあいだプロセスごと止まっていた(スリープ・休止)とみなし、`note_pause` で差し引く。

**気をつけること**: 裏に回ったままブラウザごと落ちた(closed が出なかった)ときは、ブラウザ版は
動いたまま残る。stop.bat・業務ツール統合ランチャーで止められる。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from .logging_setup import get_logger

log = get_logger("coilcalc.page_watch")

VISIBLE, HIDDEN, CLOSED = "visible", "hidden", "closed"
STATES = (VISIBLE, HIDDEN, CLOSED)

#: 見張りの間隔がこれ以上空いたら「止まっていた(スリープ)」とみなす(秒)。見張りは1秒ごと
PAUSE_SECONDS = 15.0
#: 閉じたあと、読み直した画面が来るのを待つ(秒)
CLOSING_SECONDS = 15.0
#: 古い画面の記録を捨てる(秒)。閉じたもの・途切れたものを溜め込まない
FORGET_SECONDS = 3600.0


@dataclass
class Page:
    seen: float                 # 最後に知らせが来た時刻(起きていた時間の時計)
    hidden: bool = False
    closed_at: Optional[float] = None


class PageWatch:
    def __init__(self, *, idle: float, grace: float, closing: float = CLOSING_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.idle = float(idle)
        self.grace = float(grace)
        self.closing = float(closing)
        self._clock = clock
        self._paused = 0.0
        self._lock = threading.Lock()
        self._pages: Dict[str, Page] = {}
        self._started = self._clock()
        self._activity = self._started

    # --- 時計 ---------------------------------------------------------
    def now(self) -> float:
        """起きていた時間だけの時計(止まっていた分を差し引く)。"""
        return self._clock() - self._paused

    def note_pause(self, seconds: float) -> None:
        """プロセスごと止まっていた(スリープ・休止)。その分を「知らせが無い時間」に数えない。"""
        if seconds <= 0:
            return
        with self._lock:
            self._paused += seconds
        log.info("%.0f 秒止まっていました(スリープなど)。そのあいだは画面が居なかったことに数えません", seconds)

    # --- 知らせ -------------------------------------------------------
    def activity(self) -> None:
        """画面からの要求(計算など)。画面の番号は分からないが、誰かが使っている。"""
        with self._lock:
            self._activity = self.now()

    def beat(self, page: str, state: str = VISIBLE) -> None:
        state = state if state in STATES else VISIBLE
        page = (page or "-")[:64]
        with self._lock:
            t = self.now()
            self._activity = t
            known = self._pages.get(page)
            if known is None:
                known = self._pages[page] = Page(seen=t)
                log.info("画面が開きました(%s・%s)", page, state)
            if state == CLOSED:
                if known.closed_at is None:
                    log.info("画面が閉じました(%s)", page)
                known.closed_at, known.hidden = t, False
            elif state == HIDDEN:
                if known.closed_at is not None:
                    return                      # 閉じたあとに届いた「隠れます」で打ち消さない
                known.hidden, known.seen = True, t
            else:
                known.closed_at, known.hidden, known.seen = None, False, t
            self._forget(t)

    def _forget(self, t: float) -> None:
        for key in [k for k, p in self._pages.items()
                    if (p.closed_at is not None and t - p.closed_at > FORGET_SECONDS)
                    or (not p.hidden and p.closed_at is None and t - p.seen > FORGET_SECONDS)]:
            del self._pages[key]

    # --- 終わるか -----------------------------------------------------
    @property
    def seen_page(self) -> bool:
        with self._lock:
            return bool(self._pages)

    def alive_pages(self) -> int:
        with self._lock:
            t = self.now()
            return sum(1 for p in self._pages.values() if self._alive(p, t))

    def _alive(self, p: Page, t: float) -> bool:
        return p.closed_at is None and (p.hidden or t - p.seen <= self.idle)

    def enabled(self) -> bool:
        """idle が 0 なら自動では終わらない(以前の設定の意味のまま)。"""
        return self.idle > 0

    def reason_to_exit(self) -> str:
        """終わるならその理由、まだなら空文字。"""
        if not self.enabled():
            return ""
        with self._lock:
            t = self.now()
            if not self._pages:
                if self.grace > 0 and t - self._activity > self.grace:
                    return f"最初の画面が {self.grace:.0f} 秒来ませんでした"
                return ""
            if any(self._alive(p, t) for p in self._pages.values()):
                return ""
            # 画面はみな居なくなった。閉じたばかりなら、読み直した画面が来るのを少し待つ
            closed = [p.closed_at for p in self._pages.values() if p.closed_at is not None]
            if closed and t - max(closed) <= self.closing:
                return ""
            if t - self._activity <= self.closing:
                return ""
            return "画面を閉じました" if closed and len(closed) == len(self._pages) else \
                f"画面から {self.idle:.0f} 秒知らせがありません"
