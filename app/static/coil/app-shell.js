/*
  app-shell.js — 計算の処理(Python)とのやりとりと、版ごとの違い

  計算は Python(coilcalc/calc.py)がします。画面は欄の文字を送り、返ってきた文字を
  置くだけです(数値・範囲・丸めの正は Python の1か所)。

  デスクトップ版  /api/… は外枠(Rust)が受けて Python の標準入力へ渡す(ポート無し)
  ブラウザ版      /api/… は 127.0.0.1 の Python が受ける(予備)

  ブラウザ版のときだけ:
    - 右上の「終了」を出す(デスクトップ版は窓の × で閉じる)
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

    function setupBrowser(health) {
        const button = document.getElementById('app-quit');
        if (button) {
            button.hidden = false;
            button.addEventListener('click', async () => {
                if (!window.confirm('ブラウザ版を終了しますか?')) return;
                try { await post('/api/shutdown', {}); } catch (err) { /* 止まっていればそれでよい */ }
                quitted();
            });
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

    async function start() {
        try {
            const res = await fetch('/api/health', { cache: 'no-store' });
            const health = await res.json();
            document.documentElement.dataset.mode = health.mode;
            if (health.mode === 'browser') setupBrowser(health);
        } catch (err) {
            showBanner('計算の処理(Python)と繋がりません。アプリを開き直してください。');
        }
    }

    window.AppShell = { calc, report, showBanner, hideBanner };
    document.addEventListener('DOMContentLoaded', start);
})();
