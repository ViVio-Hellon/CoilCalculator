/*
  nav.js — 画面の寿命(日報管理ツールの `nav.js` のうち、VC長さ計算が使う2つだけ)

  日報管理ツールは画面を読み直さずに移るので「画面を出たら配線を外す」仕組みが
  要りました。このツールの画面は1枚きりなので、外すのはページを閉じるときだけです。
*/
const controller = new AbortController();
const leaving = [];

window.addEventListener("pagehide", () => {
  for (const fn of leaving.splice(0)) {
    try { fn(); } catch (err) { /* 閉じるときなので黙る */ }
  }
  controller.abort();
});

/** 画面を閉じたら外れる配線の印(addEventListener の signal に渡す)。 */
export function pageSignal() {
  return controller.signal;
}

/** 画面を閉じるときにすること(見張りの時計を止める など)。 */
export function onLeave(fn) {
  leaving.push(fn);
}
