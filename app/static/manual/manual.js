/*
  manual.js — 操作説明書の小さな動き
    - 背景(ライト / ダーク)をツールで選んだ方に揃える(ツールと同じ覚え場所を読む)
    - いま動いているツールの版を出す(ツールから開いたときだけ。説明書だけ開いたときは出さない)
*/
(() => {
    const root = document.documentElement;
    try {
        const saved = localStorage.getItem('vc-calculator.coil.theme');
        const dark = saved ? saved === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
        root.dataset.theme = dark ? 'dark' : 'light';
    } catch (err) {
        root.dataset.theme = 'light';
    }

    document.addEventListener('DOMContentLoaded', async () => {
        const live = document.getElementById('live-version');
        if (!live) return;
        try {
            const res = await fetch('/api/health', { cache: 'no-store' });
            if (!res.ok) return;
            const health = await res.json();
            const mode = health.mode === 'desktop' ? 'デスクトップ版' : 'ブラウザ版';
            live.textContent = `いま動いているツール: v${health.version} ${mode}`;
            live.hidden = false;
        } catch (err) {
            /* ツールの外で開いたとき。版は説明書の版だけ出す */
        }
    });
})();
