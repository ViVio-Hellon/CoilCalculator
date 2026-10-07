/*
  app-shell.js — 計算の処理(Python)とのやりとりと、版ごとの違い

  計算は Python(coilcalc/calc.py)がします。画面は欄の文字を送り、返ってきた文字を
  置くだけです(数値・範囲・丸めの正は Python の1か所)。

  デスクトップ版  /api/… は外枠(Rust)が受けて Python の標準入力へ渡す(ポート無し)
  ブラウザ版      /api/… は 127.0.0.1 の Python が受ける(予備)

  左上の部品:
    - 版(アプリ・外枠(Rust)・Python・どちらの版で動いているか)。押すと詳細
    - 操作説明: いま見ている形状の説明書(manual/)を開く。デスクトップ版は外枠に
      別の窓を頼み(open_manual)、ブラウザ版は別のタブで開く

  ブラウザ版のときだけ:
    - 左上の「終了」を出す(デスクトップ版は窓の × で閉じる)
    - 画面が開いていることを数秒ごとに知らせる。タブを全部閉じるとしばらくして
      Python が自分で終わる(残っているとデスクトップ版が開けないため)

  繋がらないときは上に帯を出す(計算の欄はそのまま。繋がり直せば帯は消える)。
*/
(() => {
    const seq = { coil: 0, plate: 0 };
    const applied = { coil: 0, plate: 0 };
    let banner = null;

    function showBanner(message) {
        if (!banner) {
            banner = document.createElement('div');
            banner.className = 'app-banner';
            banner.setAttribute('role', 'alert');
            document.body.prepend(banner);
        }
        banner.textContent = message;
        banner.hidden = false;
    }

    function hideBanner() {
        if (banner) banner.hidden = true;
    }

    async function post(path, data) {
        return fetch(path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data || {})
        });
    }

    /**
     * 計算を頼む。古い答え(後から送った計算の答えが先に届いたあと)は捨てて null を返す。
     * @param {'coil'|'plate'} shape
     * @param {Object<string,string>} fields 欄の名前 → 欄の文字
     */
    async function calc(shape, fields) {
        const mine = ++seq[shape];
        let body;
        try {
            const res = await post(`/api/${shape}/calc`, { fields });
            body = await res.json();
            if (!res.ok) {
                const message = (body && body.error && body.error.message) || `応答 ${res.status}`;
                showBanner(`計算できませんでした: ${message}`);
                return null;
            }
        } catch (err) {
            showBanner('計算の処理(Python)と繋がりません。アプリを開き直してください。'
                + '(ブラウザ版なら Start.vbs をもう一度開きます)');
            return null;
        }
        if (mine < applied[shape]) return null;
        applied[shape] = mine;
        hideBanner();
        return body;
    }

    /** 画面の JS のエラーを動作ログに残す(現場で起きたことを後から追えるように)。 */
    function report(message, where) {
        post('/api/client-error', { message: String(message), where: String(where || '') })
            .catch(() => { /* 残せなくてもよい */ });
    }

    window.addEventListener('error', (e) => report(e.message, `${e.filename}:${e.lineno}`));
    window.addEventListener('unhandledrejection', (e) => report(e.reason, 'promise'));

    // --- ブラウザ版だけの「終了」と、開いている知らせ ---
    function quitted() {
        const box = document.createElement('main');
        box.className = 'app-quitted';
        const h = document.createElement('h1');
        h.textContent = '終了しました';
        const p = document.createElement('p');
        p.textContent = 'このタブ(画面)を閉じてください。もう一度使うときは Start.vbs かデスクトップ版を開きます。';
        box.append(h, p);
        document.body.replaceChildren(box);
    }

    /**
     * 「終了」。**確かめの文と「止めてよいか」の判断は Python が持つ**(デスクトップ版の
     * 窓の × と同じ確かめ)。まず確かめ無しで頼み、409 で返ってきた文を見せ、
     * 「OK」のときだけ confirmed を付けて送り直す。キャンセルなら何もしない。
     */
    async function quit() {
        let ask;
        try {
            const res = await post('/api/shutdown', {});
            if (res.ok) { quitted(); return; }             // 確かめの要らない状態(今は無い)
            ask = (await res.json()).confirm;
        } catch (err) {
            quitted();                                      // もう止まっている
            return;
        }
        if (!ask || !window.confirm(ask.message)) return;  // キャンセル・答え無し → 止めない
        try { await post('/api/shutdown', { confirmed: true }); } catch (err) { /* 止まればよい */ }
        quitted();
    }

    function setupBrowser(health) {
        const button = document.getElementById('app-quit');
        if (button) {
            button.hidden = false;
            button.addEventListener('click', quit);
        }
        const every = Math.max(3, Number(health.heartbeat_seconds) || 10) * 1000;
        const beat = () => post('/api/heartbeat', {}).then(hideBanner).catch(() => {
            showBanner('ブラウザ版の処理が終わっています。Start.vbs をもう一度開いてください。');
        });
        setInterval(beat, every);
        // タブに戻ってきたらすぐ知らせる(背景のタブは時計が間引かれる)
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) beat();
        });
    }

    // --- 版の表示 ---
    const MODE_LABEL = { desktop: 'デスクトップ版', browser: 'ブラウザ版' };

    function showVersion(health, shellVersion) {
        const root = document.documentElement;
        root.dataset.version = health.version || '';
        const mode = MODE_LABEL[health.mode] || health.mode || '';
        document.getElementById('app-version-text').textContent = `v${health.version} ${mode}`;
        const rows = [
            ['アプリ', `${health.app || ''} v${health.version}`],
            ['動き方', health.mode === 'desktop'
                ? 'デスクトップ版(CoilCalculator.exe・ポートを使わない)'
                : `ブラウザ版(Start.vbs・${location.host})`],
        ];
        if (health.mode === 'desktop') rows.push(['外枠(Rust)', shellVersion ? `v${shellVersion}` : '不明']);
        rows.push(['計算(Python)', `Python ${health.python || '不明'}`]);
        const list = document.getElementById('app-version-list');
        list.replaceChildren(...rows.flatMap(([k, v]) => {
            const dt = document.createElement('dt');
            dt.textContent = k;
            const dd = document.createElement('dd');
            dd.textContent = v;
            return [dt, dd];
        }));
    }

    function setupVersionPanel() {
        const button = document.getElementById('app-version');
        const panel = document.getElementById('app-version-panel');
        const toggle = (open) => {
            panel.hidden = !open;
            button.setAttribute('aria-expanded', open ? 'true' : 'false');
        };
        button.addEventListener('click', () => toggle(panel.hidden));
        document.addEventListener('click', (e) => {
            if (!panel.hidden && !e.target.closest('#app-version, #app-version-panel')) toggle(false);
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !panel.hidden) { toggle(false); button.focus(); }
        });
    }

    // --- 操作説明書 ---
    let mode = '';

    /** いま見ている形状(コイル / 平板)の説明書の頁 */
    function currentManualPage() {
        const active = document.querySelector('.shape-btn.active');
        return active && active.dataset.shape === 'plate' ? 'plate' : 'coil';
    }

    function openManual(page) {
        const tauri = window.__TAURI__;
        if (mode === 'desktop' && tauri && tauri.core && tauri.core.invoke) {
            // デスクトップ版の窓は新しいタブを持たないので、外枠に別の窓を開いてもらう
            tauri.core.invoke('open_manual', { page }).catch((err) => {
                report(err, 'open_manual');
                showBanner(`操作説明書を開けませんでした: ${err}`);
            });
            return;
        }
        // ブラウザ版: 同じタブを使い回す(押すたびにタブが増えないように)
        const opened = window.open(`manual/${page}.html`, 'coil-calculator-manual');
        if (!opened) showBanner('操作説明書を開けませんでした(ブラウザがポップアップを止めています)。');
    }

    async function start() {
        setupVersionPanel();
        document.getElementById('app-help').addEventListener('click', () => openManual(currentManualPage()));
        try {
            const res = await fetch('/api/health', { cache: 'no-store' });
            const health = await res.json();
            mode = health.mode;
            document.documentElement.dataset.mode = health.mode;
            showVersion(health, res.headers.get('X-Coil-Shell-Version'));
            if (health.mode === 'browser') setupBrowser(health);
        } catch (err) {
            document.getElementById('app-version-text').textContent = '版: 不明';
            showBanner('計算の処理(Python)と繋がりません。アプリを開き直してください。');
        }
    }

    window.AppShell = { calc, report, showBanner, hideBanner, openManual };
    document.addEventListener('DOMContentLoaded', start);
})();
