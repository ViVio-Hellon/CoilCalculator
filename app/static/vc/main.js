/*
  main.js — 外の枠(index.html)の始まり

  ?window=quick … **早見表だけの窓**(計算の画面の「早見表を別の窓で開く」)。
                  見出しも面の札も出さない(VBA `UFquick` はモードレスの小窓)
*/
import { start } from "./vc.js";

const params = new URLSearchParams(location.search);
if (params.get("window") === "quick") {
  document.body.classList.add("is-bare");
  document.title = `VCフィルム長さ早見表 ─ ${document.title}`;
  for (const tab of document.querySelectorAll("#vcTabs > .tabs__bar > .tab")) {
    if (tab.dataset.key === "quick") tab.dataset.default = "1";
    else delete tab.dataset.default;
  }
}
start();
