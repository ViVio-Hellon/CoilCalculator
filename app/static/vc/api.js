/*
  api.js — 処理(Python)とのやりとり(日報管理ツール `api.js` の、このツールに要る分だけ)

  JS が持つのは「呼ぶ」「受け取ったものを描く」だけ。**業務の判断はサーバ**(coilcalc/vc_api.py)。
  デスクトップ版は /api/… を外枠(Rust)が受けて Python の標準入力へ渡し、
  ブラウザ版は 127.0.0.1 の Python が受ける。どちらも同じ道・同じ答え。
*/

/**
 * サーバが返したエラーを、そのまま画面に出せる形で持つ。
 *
 *   入力の形の誤り   … `{"error": {"code", "message"}}`
 *   業務としての断り … 画面ぜんぶ + `error`(早見表・状態一式も入っている)
 */
export class ApiError extends Error {
  constructor(status, body) {
    const info = (body && body.error) || {};
    super(info.message || (body && body.message)
          || `処理(Python)から答えがありません (HTTP ${status})`);
    this.name = "ApiError";
    this.status = status;
    this.code = info.code || "";
    this.body = body;
  }
}

/*
  押した本人に「いま処理している」と伝え、**二度押しで同じ書き込みを2回送らない**
  (日報管理ツールの busy.js の役目を、要るところだけ)。書く要求(POST)のとき、
  直前に押されたボタンを返事が来るまで押せなくする。
*/
let pressed = null;
let pressedAt = 0;
document.addEventListener("click", (event) => {
  const button = event.target.closest && event.target.closest("button");
  if (!button) return;
  if (button.dataset.busy === "1") {
    // 返事を待っているボタン。押しても何もしない(押せる・押せないは画面が決めたまま触らない)
    event.preventDefault();
    event.stopPropagation();
    return;
  }
  pressed = button;
  pressedAt = Date.now();
}, true);

function holdPressed() {
  const button = pressed;
  if (!button || Date.now() - pressedAt > 1000) return () => {};
  pressed = null;
  button.dataset.busy = "1";
  button.setAttribute("aria-busy", "true");
  return () => { delete button.dataset.busy; button.removeAttribute("aria-busy"); };
}

async function request(path, options = {}) {
  const release = options.method === "POST" ? holdPressed() : () => {};
  try {
    return await send(path, options);
  } finally {
    release();
  }
}

async function send(path, options) {
  let res;
  try {
    res = await fetch(path, {
      ...options,
      cache: "no-store",
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {}),
      },
    });
  } catch (err) {
    throw new ApiError(0, { error: { code: "offline",
      message: "処理(Python)と繋がりません。アプリを開き直してください。" } });
  }
  let body = null;
  if ((res.headers.get("Content-Type") || "").includes("application/json")) {
    body = await res.json();
  }
  if (!res.ok) throw new ApiError(res.status, body);
  return body;
}

export const api = {
  get: (path) => request(path),
  post: (path, data) => request(path, { method: "POST", body: JSON.stringify(data ?? {}) }),
};

/** 誰も押していない通信(見張り)。いまは api と同じ(待機の姿を出す仕組みが無いため)。 */
export const background = api;
