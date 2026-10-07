/*
  vc_tables.js — 「マスタの表」の面。VC計算マスタの表を見る・1行ずつ直す(管理者)

  日報管理ツールでは 設定・管理者 → マスタ → マスタ管理 の「VC計算マスタ」が受け持って
  いた所です。**決めるのはサーバ**(coilcalc/vc/tables.py):

    - どの表を出すか(_メタ は出さない)・見るだけの表(変更履歴)・値だけ直す表(アプリ設定)
    - 入れた値の形(整数・小数・文字)と、決まった言葉しか効かない値(早見表の丸め・枠色)
    - 書く・変更履歴・更新番号を1つの取引で

  ここは表を描いて、直した行の値を送るだけ。鍵(管理者パスワード)は「設定」と同じ鍵です。
*/
import { api } from "./api.js";
import { toast } from "./toast.js";

const $ = (id) => document.getElementById(id);

let page = null;          // サーバが返した表1枚ぶん
let wanted = "";          // 見たい表
let sortCol = "";
let sortDir = "asc";
let onChanged = () => {};
let loaded = false;
// 読み込みの番号。**後から頼んだ表を、先に頼んだ表の返事で上書きしない**
// (面を開いた直後に表を選び替えると、2つの返事が逆の順に届くことがある)
let asked = 0;

export function start(options = {}) {
  const signal = options.signal;
  onChanged = options.onChanged || onChanged;
  $("vc-tables-pick").addEventListener("change", () => {
    wanted = $("vc-tables-pick").value;
    sortCol = "";
    load();
  }, { signal });
  let timer = 0;
  $("vc-tables-q").addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(load, 250);
  }, { signal });
  $("vc-tables-reload").addEventListener("click", () => load(), { signal });
  $("vc-tables-unlock").addEventListener("click", () => setKey(true), { signal });
  $("vc-tables-relock").addEventListener("click", () => setKey(false), { signal });
  $("vc-tables-password").addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); setKey(true); }
  }, { signal });
}

/** 面を開いた。初めてなら読む、2度目からは読み直す(ほかで直されているかもしれない)。 */
export function show() {
  load();
}

/** 鍵が変わった(「設定」で開け閉めした)。開いていれば描き直す。 */
export function refresh() {
  if (loaded) load();
}

function note(text, kind = "info") {
  const box = $("vc-tables-msg");
  box.hidden = !text;
  box.textContent = text || "";
  box.className = `msg msg--${kind}`;
}

async function load() {
  const mine = ++asked;
  const args = new URLSearchParams({ table: wanted, q: $("vc-tables-q").value.trim(),
                                     sort: sortCol, dir: sortDir });
  try {
    const body = await api.get(`/api/vc/tables?${args}`);
    if (mine !== asked) return;                  // もっと新しい読み込みがある
    note("");                                    // 前の表・前の操作の知らせを残さない
    render(body);
    loaded = true;
  } catch (err) {
    if (mine === asked) note(err.message, "error");
  }
}

async function setKey(enable) {
  note("");
  try {
    const body = await api.post("/api/vc/unlock",
      enable ? { enable: true, password: $("vc-tables-password").value } : { enable: false });
    $("vc-tables-password").value = "";          // 合言葉は画面に残さない
    toast(body.message, "ok");
    await load();
  } catch (err) {
    note(err.message, "error");
    $("vc-tables-password").focus();
  }
}

function render(body) {
  page = body;
  wanted = body.table;
  sortCol = body.sort || "";
  sortDir = body.sort_dir || "asc";
  const pick = $("vc-tables-pick");
  pick.replaceChildren(...body.tables.map((t) => new Option(t.table, t.table)));
  pick.value = body.table;
  // 直せない・行を足せない理由があれば、それを先に(出さないのではなく、理由を出す)
  $("vc-tables-note").textContent = [body.view_only_why || body.fixed_why, body.table_note]
    .filter(Boolean).join(" ");
  $("vc-tables-more").textContent = body.note || "";
  $("vc-tables-source").textContent = body.master
    ? `${body.master.source_label || ""} ${body.master.path || ""}`.trim() : "";

  // 鍵
  const open = Boolean(body.unlocked);
  $("vc-tables-password").hidden = open;
  $("vc-tables-password-label").hidden = open;
  $("vc-tables-unlock").hidden = open;
  $("vc-tables-relock").hidden = !open;
  $("vc-tables-lock").textContent = open
    ? (body.editable ? "鍵が開いています。欄を直して「保存」を押すと、マスタに書きます。"
       : "鍵が開いています(この表は直せません)。")
    : "見るだけです。直すときは管理者パスワードで「鍵を開ける」を押してください。";
  if (body.master && body.master.source !== "db") {
    note(body.master.note || "マスタを読めないので、表を出せません。", "warn");
  } else if (body.error) {
    note(body.error, "error");
  }
  drawTable(body);
}

function drawTable(body) {
  const grid = $("vc-tables-grid");
  const cols = body.columns || [];
  const head = document.createElement("tr");
  for (const c of cols) {
    const th = document.createElement("th");
    const b = document.createElement("button");
    b.type = "button";
    b.className = "vc-tables__sort";
    const mark = sortCol === c.name ? (sortDir === "desc" ? " ▼" : " ▲") : "";
    b.textContent = c.name + mark;
    b.title = `${c.kind_label}${c.required ? "・空にできない" : ""}。押すと並べ替えます`;
    b.addEventListener("click", () => {
      sortDir = sortCol === c.name && sortDir === "asc" ? "desc" : "asc";
      sortCol = c.name;
      load();
    });
    th.append(b);
    head.append(th);
  }
  if (body.editable) head.append(document.createElement("th"));
  const thead = document.createElement("thead");
  thead.append(head);

  const tbody = document.createElement("tbody");
  for (const row of body.rows || []) tbody.append(rowLine(body, cols, row));
  if (body.can_add) tbody.append(addLine(body, cols));
  if (!(body.rows || []).length && !body.can_add) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = Math.max(1, cols.length);
    td.className = "lead";
    td.textContent = "行がありません。";
    tr.append(td);
    tbody.append(tr);
  }
  grid.replaceChildren(thead, tbody);
}

function cellInput(column, value) {
  const input = document.createElement("input");
  input.type = "text";
  input.value = value ?? "";
  input.dataset.col = column.name;
  input.dataset.was = value ?? "";
  input.size = Math.min(28, Math.max(6, String(value ?? "").length + 2));
  if (column.kind !== "text") input.inputMode = "decimal";
  input.setAttribute("aria-label", column.name);
  return input;
}

function rowLine(body, cols, row) {
  const tr = document.createElement("tr");
  const key = row[body.row_key];
  const inputs = [];
  for (const c of cols) {
    const td = document.createElement("td");
    if (body.editable && !c.readonly) {
      const input = cellInput(c, row[c.name]);
      inputs.push(input);
      td.append(input);
    } else {
      td.textContent = row[c.name] ?? "";
      if (c.kind !== "text") td.className = "num";
    }
    tr.append(td);
  }
  if (body.editable) {
    const act = document.createElement("td");
    act.className = "vc-tables__act";
    const save = document.createElement("button");
    save.type = "button";
    save.className = "btn btn--sm";
    save.textContent = "保存";
    save.disabled = true;
    const changedOnes = () => inputs.filter((i) => i.value !== i.dataset.was);
    for (const i of inputs) {
      i.addEventListener("input", () => {
        save.disabled = !changedOnes().length;
        tr.classList.toggle("is-dirty", !save.disabled);
      });
      i.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !save.disabled) { event.preventDefault(); save.click(); }
      });
    }
    save.addEventListener("click", () => {
      const values = {};
      for (const i of changedOnes()) values[i.dataset.col] = i.value;
      write("/api/vc/tables/save", { row: key, values });
    });
    act.append(save);
    if (body.can_delete) {
      const drop = document.createElement("button");
      drop.type = "button";
      drop.className = "btn btn--sm vc-btn-danger";
      drop.textContent = "消す";
      drop.addEventListener("click", () => {
        const label = cols.slice(0, 3).map((c) => row[c.name]).filter(Boolean).join(" / ");
        if (!confirm(`${body.table} の行「${label}」を消します。よろしいですか?`)) return;
        write("/api/vc/tables/delete", { row: key });
      });
      act.append(drop);
    }
    tr.append(act);
  }
  return tr;
}

function addLine(body, cols) {
  const tr = document.createElement("tr");
  tr.className = "vc-tables__add";
  const inputs = [];
  for (const c of cols) {
    const td = document.createElement("td");
    if (!c.readonly) {
      const input = cellInput(c, "");
      input.placeholder = c.required ? "必須" : "";
      inputs.push(input);
      td.append(input);
    }
    tr.append(td);
  }
  const act = document.createElement("td");
  act.className = "vc-tables__act";
  const add = document.createElement("button");
  add.type = "button";
  add.className = "btn btn--sm btn--primary";
  add.textContent = "足す";
  add.addEventListener("click", () => {
    const values = {};
    for (const i of inputs) values[i.dataset.col] = i.value;
    write("/api/vc/tables/add", { values });
  });
  act.append(add);
  tr.append(act);
  return tr;
}

async function write(url, payload) {
  note("");
  try {
    const mine = ++asked;
    const body = await api.post(url, { table: page.table, q: $("vc-tables-q").value.trim(),
                                       sort: sortCol, dir: sortDir, ...payload });
    if (mine === asked) render(body.page);
    toast(body.message, "ok");
    onChanged();
  } catch (err) {
    if (err.body && err.body.page) render(err.body.page);
    note(err.message, "error");
  }
}
