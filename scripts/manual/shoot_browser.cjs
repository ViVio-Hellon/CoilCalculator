/*
  shoot_browser.cjs — 操作説明書の写真を撮る(ブラウザ版の画面を Chromium で開いて撮る)

  scripts/make_manual_images.py から呼ぶ(ブラウザ版を起動し、URL と出し先を渡す)。
  作業用の道具なので Playwright を使う(アプリ本体は使わない。ラインPCには要らない)。

      node scripts/manual/shoot_browser.cjs <URL> <出し先フォルダ>

  写真に番号の札(①②…)を重ねるときは、画面に札の要素を足してから撮る
  (番号は説明書の本文の番号と同じ)。
*/
'use strict';
const path = require('path');
const { chromium } = require('playwright');

const [url, outDir, positionsFile] = process.argv.slice(2);
const out = (name) => path.join(outDir, name);

/** 番号の札を、要素の左上に重ねる。marks = [[番号, CSSセレクタ, 位置], ...] */
async function mark(page, marks) {
  await page.evaluate((marks) => {
    document.querySelectorAll('.manual-mark').forEach((n) => n.remove());
    for (const [num, selector, where] of marks) {
      const el = document.querySelector(selector);
      if (!el) throw new Error('見つからない: ' + selector);
      const r = el.getBoundingClientRect();
      const box = document.createElement('div');
      box.className = 'manual-mark';
      box.style.cssText = `position:fixed;left:${r.left - 3}px;top:${r.top - 3}px;width:${r.width + 6}px;`
        + `height:${r.height + 6}px;border:3px solid #e8590c;border-radius:6px;z-index:9998;pointer-events:none;`;
      const tag = document.createElement('div');
      tag.className = 'manual-mark';
      const x = where === 'right' ? r.right - 14 : r.left - 14;
      const y = where === 'bottom' ? r.bottom - 14 : r.top - 14;
      tag.style.cssText = `position:fixed;left:${x}px;top:${y}px;width:30px;height:30px;border-radius:50%;`
        + 'background:#e8590c;color:#fff;font:700 17px/30px sans-serif;text-align:center;z-index:9999;'
        + 'box-shadow:0 1px 4px rgba(0,0,0,.35);pointer-events:none;';
      tag.textContent = String(num);
      document.body.append(box, tag);
    }
  }, marks);
}

async function unmark(page) {
  await page.evaluate(() => document.querySelectorAll('.manual-mark').forEach((n) => n.remove()));
}

async function settle(page, ms = 700) {
  await page.waitForTimeout(ms);
}

async function crop(page, selector, name, pad = 8) {
  const box = await page.locator(selector).first().boundingBox();
  await page.screenshot({
    path: out(name),
    clip: { x: Math.max(0, box.x - pad), y: Math.max(0, box.y - pad), width: box.width + pad * 2, height: box.height + pad * 2 },
  });
}

async function fill(page, id, value, waitFor) {
  await page.fill('#' + id, value);
  if (waitFor) await page.waitForFunction(waitFor);
  await settle(page, 300);
}

(async () => {
  const browser = await chromium.launch({ args: ['--use-gl=swiftshader', '--enable-unsafe-swiftshader', '--lang=ja-JP'] });
  const context = await browser.newContext({ viewport: { width: 1600, height: 950 }, locale: 'ja-JP', colorScheme: 'light' });
  await context.addInitScript(() => {
    try {
      localStorage.setItem('vc-calculator.coil.theme', 'light');
      localStorage.setItem('vc-calculator.coil.shape', 'coil');
    } catch (e) { /* 覚えられなくてもよい */ }
  });
  const page = await context.newPage();
  page.on('dialog', (d) => d.accept());
  await page.goto(url);
  await page.waitForFunction(() => document.getElementById('weight-result').textContent !== '—'
    && /v\d/.test(document.getElementById('app-version-text').textContent));
  await settle(page, 1500);

  // デスクトップ版の窓(1500×940)で、左上の「版」「操作説明」がどこにあるか
  // (make_manual_images.py が xdotool で押すのに使う。文字はデスクトップ版のものに替えてはかる)
  if (positionsFile) {
    await page.setViewportSize({ width: 1500, height: 940 });
    await page.evaluate(() => {
      document.getElementById('app-version-text').textContent = document.getElementById('app-version-text')
        .textContent.replace('ブラウザ版', 'デスクトップ版');
      document.getElementById('app-quit').hidden = true;
    });
    const center = async (sel) => {
      const b = await page.locator(sel).boundingBox();
      return { x: Math.round(b.x + b.width / 2), y: Math.round(b.y + b.height / 2) };
    };
    const positions = { version: await center('#app-version'), help: await center('#app-help') };
    require('fs').writeFileSync(positionsFile, JSON.stringify(positions));
    await page.reload();
    await page.setViewportSize({ width: 1600, height: 950 });
    await page.waitForFunction(() => document.getElementById('weight-result').textContent !== '—'
      && /v\d/.test(document.getElementById('app-version-text').textContent));
    await settle(page, 1500);
  }

  // ---- コイル: 全体と番号 ----
  await mark(page, [
    [1, '.shape-switch'], [2, '#material-preset'], [3, '.input-panel .form-group', 'right'],
    [4, '[id="3d-container"]'], [5, '.graph-card'], [6, '#weight-result'],
    [7, '[data-tab="details-tab"]'], [8, '#coil-print', 'right'], [9, '.app-tools'], [10, '.theme-switch', 'right'],
  ]);
  await page.screenshot({ path: out('coil-overview.jpg'), type: 'jpeg', quality: 82 });
  await unmark(page);

  // 範囲の外
  await fill(page, 'thickness', '700', () => document.getElementById('thickness').classList.contains('error'));
  await crop(page, '#coil-section .input-panel', 'coil-input-error.png');
  await fill(page, 'thickness', '400', () => !document.getElementById('thickness').classList.contains('error'));

  // 3D(詳細表示を出す)とグラフ
  await page.click('#toggle-details');
  await settle(page);
  await crop(page, '#coil-section .visual-panel', 'coil-3d.png');
  await page.click('#toggle-details');
  await page.selectOption('#x-axis-param', 'thickness');
  await page.selectOption('#y-axis-result', 'weight');
  await settle(page);
  await crop(page, '#coil-section .graph-card', 'coil-chart.png');
  await crop(page, '#coil-section .results > .result-card:nth-child(2)', 'coil-result-weight.png');

  // 詳細計算過程・モーダル
  await page.click('[data-tab="details-tab"]');
  await settle(page);
  await page.screenshot({ path: out('coil-details.jpg'), type: 'jpeg', quality: 82 });
  await page.click('[data-tab="main-tab"]');
  await page.click('[data-modal="weight-modal"]');
  await settle(page, 500);
  await page.screenshot({ path: out('coil-modal.jpg'), type: 'jpeg', quality: 82 });
  await page.click('#weight-modal .modal-close');

  // 版の詳細(ブラウザ版)
  await page.click('#app-version');
  await page.mouse.move(1500, 900);
  await settle(page, 300);
  await page.screenshot({ path: out('version-browser.png'), clip: { x: 0, y: 0, width: 560, height: 300 } });
  await page.click('#app-version');

  // 印刷の計算書(印刷の見た目で撮る)
  await page.evaluate(() => window.buildPrintSheet('coil'));
  await page.emulateMedia({ media: 'print' });
  await page.setViewportSize({ width: 794, height: 1123 });
  await settle(page, 800);
  await page.screenshot({ path: out('coil-print.jpg'), type: 'jpeg', quality: 82 });
  await page.emulateMedia({ media: 'screen' });
  await page.setViewportSize({ width: 1600, height: 950 });
  await settle(page, 800);

  // ---- ダーク ----
  await page.click('[data-theme-choice="dark"]');
  await settle(page, 900);
  await page.screenshot({ path: out('coil-dark.jpg'), type: 'jpeg', quality: 82 });
  await page.click('[data-theme-choice="light"]');
  await settle(page, 600);

  // ---- 平板 ----
  await page.click('[data-shape="plate"]');
  await page.waitForFunction(() => document.getElementById('plate-weight-result').textContent !== '—');
  await settle(page, 1500);
  await mark(page, [
    [1, '#plate-material-preset'], [2, '.plate-figure'], [3, '#plate-section .input-panel .form-group', 'right'],
    [4, '#plate-3d-container'], [5, '#plate-section .graph-card'], [6, '#plate-weight-result'],
    [7, '[data-ptab="plate-details-tab"]'], [8, '#plate-print', 'right'],
  ]);
  await page.screenshot({ path: out('plate-overview.jpg'), type: 'jpeg', quality: 82 });
  await unmark(page);

  await fill(page, 'plate-t', '0.01', () => document.getElementById('plate-t').classList.contains('error'));
  await crop(page, '#plate-section .input-panel', 'plate-input-error.png');
  await fill(page, 'plate-t', '1.00', () => !document.getElementById('plate-t').classList.contains('error'));

  await page.click('#plate-toggle-details');
  await settle(page);
  await crop(page, '#plate-section .visual-panel', 'plate-3d.png');
  await page.click('#plate-toggle-details');
  await crop(page, '#plate-section .graph-card', 'plate-chart.png');

  await page.click('[data-ptab="plate-details-tab"]');
  await settle(page);
  await page.screenshot({ path: out('plate-details.jpg'), type: 'jpeg', quality: 82 });
  await page.click('[data-ptab="plate-main-tab"]');
  await page.click('[data-modal="plate-area-modal"]');
  await settle(page, 500);
  await page.screenshot({ path: out('plate-modal.jpg'), type: 'jpeg', quality: 82 });
  await page.click('#plate-area-modal .modal-close');

  await page.evaluate(() => window.buildPrintSheet('plate'));
  await page.emulateMedia({ media: 'print' });
  await page.setViewportSize({ width: 794, height: 1123 });
  await settle(page, 800);
  await page.screenshot({ path: out('plate-print.jpg'), type: 'jpeg', quality: 82 });
  await page.emulateMedia({ media: 'screen' });
  await page.setViewportSize({ width: 1600, height: 950 });
  await page.click('[data-shape="coil"]');
  await settle(page, 800);

  // ---- ブラウザ版の「終了」と、終わったあとの画面 ----
  await page.screenshot({ path: out('browser-tools.png'), clip: { x: 0, y: 0, width: 480, height: 60 } });
  await page.click('#app-quit');
  await page.waitForSelector('.app-quitted');
  await page.screenshot({ path: out('browser-quitted.png'), clip: { x: 400, y: 330, width: 800, height: 260 } });

  await browser.close();
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
