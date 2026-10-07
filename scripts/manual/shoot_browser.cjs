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

/**
 * 番号の札を、要素の左上に重ねる。marks = [[番号, CSSセレクタ, 位置], ...]
 * target は頁(外の枠)か、コイル・平板の枠(frame)。札はその文書の中に置く(枠の中なら枠の中に出る)
 */
async function mark(target, marks, keep = false) {
  await target.evaluate(([marks, keep]) => {
    if (!keep) document.querySelectorAll('.manual-mark').forEach((n) => n.remove());
    for (const [num, selector, where] of marks) {
      const el = document.querySelector(selector);
      if (!el) throw new Error('見つからない: ' + selector);
      // コイル・平板の枠は画面に収めるため html ごと縮めて描く(coil-fit の zoom)。札の位置は縮める前の値で置く
      const z = parseFloat(getComputedStyle(document.documentElement).zoom) || 1;
      const b = el.getBoundingClientRect();
      const r = { left: b.left / z, top: b.top / z, right: b.right / z, bottom: b.bottom / z,
                  width: b.width / z, height: b.height / z };
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
  }, [marks, keep]);
}

async function unmark(...targets) {
  for (const t of targets) {
    await t.evaluate(() => document.querySelectorAll('.manual-mark').forEach((n) => n.remove()));
  }
}

async function settle(page, ms = 700) {
  await page.waitForTimeout(ms);
}

/** 要素のまわりを撮る(枠の中の要素でも、頁の座標で返ってくる) */
async function crop(page, locator, name, pad = 8) {
  const box = await locator.first().boundingBox();
  const vp = page.viewportSize();
  const x = Math.max(0, box.x - pad);
  const y = Math.max(0, box.y - pad);
  await page.screenshot({
    path: out(name), quality: name.endsWith('.jpg') ? 82 : undefined,
    clip: { x, y, width: Math.min(box.width + pad * 2, vp.width - x), height: Math.min(box.height + pad * 2, vp.height - y) },
  });
}

async function shot(page, name) {
  await page.screenshot({ path: out(name), type: name.endsWith('.jpg') ? 'jpeg' : 'png',
                          quality: name.endsWith('.jpg') ? 82 : undefined });
}

/** 外の枠の面を選ぶ */
async function tab(page, key) {
  await page.click(`#tab-${key}`);
  await settle(page, 500);
}

(async () => {
  const browser = await chromium.launch({ args: ['--use-gl=swiftshader', '--enable-unsafe-swiftshader', '--lang=ja-JP'] });
  const context = await browser.newContext({ viewport: { width: 1600, height: 950 }, locale: 'ja-JP', colorScheme: 'light' });
  // 撮るときだけ、画面の動き(ふわっと出る・色が移る)を止める。この Chromium(ヘッドレス・
  // ソフトウェア描画)では CSS の動きの時計が進まず、結果のカードが透明のまま・3D が出ないまま写る
  await context.addInitScript(() => {
    document.addEventListener('DOMContentLoaded', () => {
      const still = document.createElement('style');
      still.textContent = '*,*::before,*::after{animation:none!important;transition:none!important}';
      document.head.append(still);
    });
  });
  await context.addInitScript(() => {
    try {
      localStorage.setItem('vc-calculator.coil.theme', 'light');
      localStorage.setItem('vc-calculator.coil.shape', 'coil');
      sessionStorage.removeItem('tab:vc');
    } catch (e) { /* 覚えられなくてもよい */ }
  });
  const page = await context.newPage();
  page.on('dialog', (d) => d.accept());
  const ready = () => page.waitForFunction(() => document.querySelectorAll('.vc-product').length > 0
    && /v\d/.test(document.getElementById('app-version-text').textContent));
  await page.goto(url);
  await ready();
  await settle(page, 800);

  // デスクトップ版の窓(1500×940)で、右上の「版」「操作説明」がどこにあるか
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
    await ready();
    await settle(page, 800);
  }

  // ================= VC長さ計算 =================
  await page.click('.vc-product[data-name="2008系/2001SR/310GH5"]');
  await page.waitForSelector('#vc-inside-choices button');
  await page.click('#vc-inside-choices button[data-inside="87.0"]');
  await page.fill('#vc-coatu', '20');
  await page.click('#vc-run');
  await page.waitForFunction(() => document.getElementById('vc-out-length').textContent !== '—');
  await page.mouse.move(1599, 940);
  await settle(page, 600);
  await mark(page, [
    [1, '#vcTabs > .tabs__bar'], [2, '#vc-products', 'right'], [3, '#vc-insides', 'right'],
    [4, '#vc-form .vc-field', 'right'], [5, '#vc-run'], [6, '.vc-hero'], [7, '#vc-counts'],
    [8, '#vc-explain'], [9, '.app-tools'], [10, '.theme-switch', 'right'],
  ]);
  await shot(page, 'vc-overview.jpg');
  await unmark(page);

  // 足りない欄があるとき
  await page.fill('#vc-coatu', '');
  await page.fill('#vc-vclen', '');
  await page.click('#vc-run');
  await page.waitForSelector('#vc-calc-error:not([hidden])');
  await settle(page, 300);
  await crop(page, page.locator('.vc-result'), 'vc-error.png', 4);
  await page.fill('#vc-coatu', '20');
  await page.click('#vc-run');
  await settle(page, 500);

  // 計算の経過(段にカーソルを当てると、図のその部分が光る)
  await page.locator('.vc-stepline[data-part="outer"]').first().hover();
  await settle(page, 300);
  await crop(page, page.locator('#vc-explain'), 'vc-explain.png', 4);
  await page.mouse.move(1599, 940);

  // 早見表
  await tab(page, 'quick');
  await page.waitForSelector('.vc-qblock');
  await settle(page, 500);
  await mark(page, [[1, '#vc-print', 'right'], [2, '.vc-qblock'], [3, '.vc-quick__rev', 'right']]);
  await shot(page, 'vc-quick.jpg');
  await unmark(page);

  // 設定(縦に長いので、窓を高くして撮る)
  await page.setViewportSize({ width: 1600, height: 2400 });
  await tab(page, 'settings');
  await page.waitForFunction(() => document.querySelectorAll('#vc-place-names tr').length === 2
    && document.querySelectorAll('#vc-blocks tr').length > 0);
  await settle(page, 500);
  await crop(page, page.locator('#vc-place'), 'vc-place.png', 4);
  await mark(page, [[1, '.vc-grid__key'], [2, '.vc-blocks-wrap'], [3, '#vc-add'], [4, '#vc-grid-block'],
                    [5, '#vc-del-product']]);
  await crop(page, page.locator('#vc-grid'), 'vc-grid.jpg', 4);
  await unmark(page);
  await crop(page, page.locator('#vc-admin'), 'vc-admin.png', 4);
  await page.setViewportSize({ width: 1600, height: 950 });

  // マスタの表(鍵を開けたところ)
  await tab(page, 'master');
  await page.waitForSelector('#vc-tables-grid tbody tr');
  await page.fill('#vc-tables-password', 'nisk');
  await page.click('#vc-tables-unlock');
  await page.waitForSelector('#vc-tables-grid input');
  const vcatu = page.locator('#vc-tables-grid tbody tr').nth(3).locator('input').nth(3);
  await vcatu.fill('0.14');
  await page.locator('.toast__close').first().click().catch(() => {});
  await settle(page, 400);
  await mark(page, [[1, '#vc-tables-relock'], [2, '#vc-tables-pick'], [3, '#vc-tables-q'],
                    [4, '#vc-tables-grid tbody tr.is-dirty', 'right'],
                    [5, '#vc-tables-grid tbody tr.is-dirty .btn', 'right'], [6, '.vc-tables__add', 'right']]);
  await shot(page, 'vc-master.jpg');
  await unmark(page);
  await vcatu.fill(await vcatu.getAttribute('data-was'));
  await page.click('#vc-tables-relock');
  await settle(page, 400);

  // ================= コイル・平板(外の枠の面に載っている)=================
  await tab(page, 'coil');
  await page.waitForFunction(() => {
    const f = document.getElementById('vc-coil-frame');
    const d = f && f.contentDocument;
    return d && d.getElementById('weight-result') && d.getElementById('weight-result').textContent !== '—';
  });
  const frame = page.frame({ url: /coil\/index\.html/ });
  const inFrame = (sel) => page.frameLocator('#vc-coil-frame').locator(sel);
  // 枠の中は画面に収めるために縮めて描く(coil-fit.js)ので、座標で押すとずれる。要素そのものを押す
  const press = (sel) => frame.$eval(sel, (el) => el.click());
  await settle(page, 1800);

  await mark(frame, [
    [1, '.shape-switch'], [2, '#material-preset'], [3, '.input-panel .form-group', 'right'],
    [4, '[id="3d-container"]'], [5, '.graph-card'], [6, '#weight-result'],
    [7, '[data-tab="details-tab"]'], [8, '#coil-print', 'right'],
  ]);
  await mark(page, [[9, '.app-tools'], [10, '.theme-switch', 'right'], [11, '#tab-coil']]);
  await shot(page, 'coil-overview.jpg');
  await unmark(page, frame);

  // 範囲の外
  await inFrame('#thickness').fill('700');
  await frame.waitForFunction(() => document.getElementById('thickness').classList.contains('error'));
  await settle(page, 300);
  await crop(page, inFrame('#coil-section .input-panel'), 'coil-input-error.png');
  await inFrame('#thickness').fill('400');
  await frame.waitForFunction(() => !document.getElementById('thickness').classList.contains('error'));

  // 3D(詳細表示を出す)とグラフ
  await press('#toggle-details');
  await settle(page);
  await crop(page, inFrame('#coil-section .visual-panel'), 'coil-3d.png');
  await press('#toggle-details');
  await inFrame('#x-axis-param').selectOption('thickness');
  await inFrame('#y-axis-result').selectOption('weight');
  await settle(page);
  await crop(page, inFrame('#coil-section .graph-card'), 'coil-chart.png');
  await crop(page, inFrame('#coil-section .results > .result-card:nth-child(2)'), 'coil-result-weight.png');

  // 詳細計算過程・モーダル
  await press('[data-tab="details-tab"]');
  await settle(page);
  await shot(page, 'coil-details.jpg');
  await press('[data-tab="main-tab"]');
  await press('[data-modal="weight-modal"]');
  await settle(page, 500);
  await shot(page, 'coil-modal.jpg');
  await press('#weight-modal .modal-close');

  // 版の詳細(ブラウザ版)。版の札は右上
  await page.click('#app-version');
  await page.mouse.move(800, 900);
  await settle(page, 300);
  await page.screenshot({ path: out('version-browser.png'), clip: { x: 1600 - 760, y: 0, width: 760, height: 330 } });
  await page.click('#app-version');

  // ---- ダーク(外の枠と枠の中が一緒に替わる)----
  await page.click('[data-theme-choice="dark"]');
  await settle(page, 1200);
  await shot(page, 'coil-dark.jpg');
  await page.click('[data-theme-choice="light"]');
  await settle(page, 800);

  // ---- 平板 ----
  await press('[data-shape="plate"]');
  await frame.waitForFunction(() => document.getElementById('plate-weight-result').textContent !== '—');
  await settle(page, 1500);
  await mark(frame, [
    [1, '#plate-material-preset'], [2, '.plate-figure'], [3, '#plate-section .input-panel .form-group', 'right'],
    [4, '#plate-3d-container'], [5, '#plate-section .graph-card'], [6, '#plate-weight-result'],
    [7, '[data-ptab="plate-details-tab"]'], [8, '#plate-print', 'right'],
  ]);
  await shot(page, 'plate-overview.jpg');
  await unmark(frame);

  await inFrame('#plate-t').fill('0.01');
  await frame.waitForFunction(() => document.getElementById('plate-t').classList.contains('error'));
  await settle(page, 300);
  await crop(page, inFrame('#plate-section .input-panel'), 'plate-input-error.png');
  await inFrame('#plate-t').fill('1.00');
  await frame.waitForFunction(() => !document.getElementById('plate-t').classList.contains('error'));

  await press('#plate-toggle-details');
  await settle(page);
  await crop(page, inFrame('#plate-section .visual-panel'), 'plate-3d.png');
  await press('#plate-toggle-details');
  await crop(page, inFrame('#plate-section .graph-card'), 'plate-chart.png');

  await press('[data-ptab="plate-details-tab"]');
  await settle(page);
  await shot(page, 'plate-details.jpg');
  await press('[data-ptab="plate-main-tab"]');
  await press('[data-modal="plate-area-modal"]');
  await settle(page, 500);
  await shot(page, 'plate-modal.jpg');
  await press('#plate-area-modal .modal-close');
  await press('[data-shape="coil"]');
  await settle(page, 600);

  // ---- 印刷の計算書(印刷の見た目で撮る。紙はコイル・平板の頁そのものなので、単独で開いて撮る)----
  const sheet = await context.newPage();
  await sheet.goto(new URL('coil/index.html', url).href);
  await sheet.waitForFunction(() => document.getElementById('weight-result').textContent !== '—');
  await settle(sheet, 1500);
  for (const shape of ['coil', 'plate']) {
    if (shape === 'plate') {
      await sheet.click('[data-shape="plate"]');
      await sheet.waitForFunction(() => document.getElementById('plate-weight-result').textContent !== '—');
      await settle(sheet, 1200);
    }
    await sheet.evaluate((s) => window.buildPrintSheet(s), shape);
    await sheet.emulateMedia({ media: 'print' });
    await sheet.setViewportSize({ width: 794, height: 1123 });
    await settle(sheet, 800);
    await sheet.screenshot({ path: out(`${shape}-print.jpg`), type: 'jpeg', quality: 82 });
    await sheet.emulateMedia({ media: 'screen' });
    await sheet.setViewportSize({ width: 1600, height: 950 });
    await settle(sheet, 600);
  }
  await sheet.close();

  // ---- ブラウザ版の「終了」と、終わったあとの画面 ----
  await tab(page, 'calc');
  await page.screenshot({ path: out('browser-tools.png'), clip: { x: 1600 - 520, y: 0, width: 520, height: 46 } });
  await page.click('#app-quit');
  await page.waitForSelector('.app-quitted');
  await page.screenshot({ path: out('browser-quitted.png'), clip: { x: 400, y: 330, width: 800, height: 260 } });

  await browser.close();
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
