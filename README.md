# VC長さ・コイル平板 計算ツール (CoilCalculator)

日報管理ツール([vba-daily-report-python-migration](https://github.com/ViVio-Hellon/vba-daily-report-python-migration))の
**「VC長さ計算」の面をまるごと**(計算・早見表・コイル・平板・設定)取り出し、
[python-web-tools](https://github.com/ViVio-Hellon/python-web-tools) と同じ
**Python + Tauri/Rust のデスクトップ版**に作り替えたものです。

| 面 | すること |
|---|---|
| **計算** | 紙管に巻かれた VC フィルムの肉厚から**残りの長さ**と定尺(1×2・2×4・5×10)ごとの枚数(VBA `UFVC計算`)。図と計算の経過つき |
| **早見表** | 肉厚 → 長さの表(VBA `UFquick`)。A4 横で印刷。早見表だけの窓でも開ける |
| **コイル・平板** | コイル(肉厚・内径・幅・比重・板厚 → 重量・長さ・巻き数)と平板(A・B・板厚・比重 → 重量・面積・体積)。3D・グラフ・計算書の印刷 |
| **設定** | VC計算マスタの置き場所・早見表の品種を足す/消す・管理者パスワード(管理者) |
| **マスタの表** | VC計算マスタの表を見る・1行ずつ直す(管理者。日報管理ツールの マスタ管理 →「VC計算マスタ」に当たる) |

VC長さ計算は **VC計算マスタ**(`VC計算マスタ.sqlite3`。日報管理ツール・vc-calculator と同じ表の形)を読みます。
置き場所を共有フォルダにすれば、日報管理ツールと**1つのマスタを共有**できます。

## 使い方

| 版 | 開き方 | ポート | 備考 |
|---|---|---|---|
| **デスクトップ版**(ふだん) | `CoilCalculator.exe` をダブルクリック | **使わない** | 専用の窓で開く。閉じるのは窓の × →「終了する」 |
| ブラウザ版(予備) | `Start.vbs` をダブルクリック | 127.0.0.1:8741〜 | 既定のブラウザで開く。閉じるのは画面右上の「終了」→ OK か `stop.bat` |

- 起動しないときは `start.bat`(コンソールに原因が出ます)
- **ブラウザ版とデスクトップ版は同時に動きません。後から開いたほうが止まります。**

  | 先に動いている | 後から開いた | 後から開いたほうの動き |
  |---|---|---|
  | ブラウザ版 | デスクトップ版 | 「ブラウザ版が動いています」と出して終わる |
  | デスクトップ版 | ブラウザ版 | 「デスクトップ版が開いています」と出して終わる |
  | デスクトップ版 | デスクトップ版 | 新しく起動せず、開いている窓を前に出す |
  | ブラウザ版 | ブラウザ版 | 新しく起動せず、動いている画面をブラウザで開く |

  ブラウザ版はタブを全部閉じると 1〜2 分で自動的に終わります(残っているとデスクトップ版が開けないため)。
  窓の × と「終了」は同じ確かめを通ります(確かめの文と判断は Python の1か所)。
  作業フォルダ(%LOCALAPPDATA%\CoilCalculator)が壊れていても起動は止まりません(錠を一時フォルダに置きます)。

- **版**: 画面の右上に「v2.0.0 デスクトップ版」のように出ます。押すと、アプリ・外枠(Rust)・
  計算(Python)の版と、どちらの版で動いているかが出ます。デスクトップ版の窓の題名・印刷した計算書にも版が入ります
- **操作説明書**: 画面の右上の「操作説明」で、いま見ている面(VC長さ計算 / コイル / 平板)の説明書が開きます
  (デスクトップ版は別の窓、ブラウザ版は別のタブ)。中身は `app/static/manual/`(画面の写真入りの HTML)。
  変更の記録は [docs/変更履歴.md](docs/変更履歴.md)

## VC計算マスタ(共有のマスタ)

| | |
|---|---|
| 置き場所 | ① この端末の設定(設定 → マスタの置き場所。`%LOCALAPPDATA%\CoilCalculator\settings.json`)② 配布の既定(`config/app.json` の `vc.master_dir`。`make_dist.bat --vc-master-dir`)③ どちらも無ければ `%LOCALAPPDATA%\CoilCalculator\master` |
| ファイル名 | 同じフォルダで `VC計算マスタ.sqlite3` → `vc_master.sqlite3`(vc-calculator の名前)の順に探す。どちらも無ければ初めて使うときに VBA の初期値で作る |
| 読むとき | **手元に写してから読む**(`coilcalc/source_db.py`)。読んでいるあいだも共有のファイルを掴まない ── ほかの人がマスタを差し替えられる。差し替えられたら次の操作で読み直す |
| 書くとき | `BEGIN IMMEDIATE` の1つの取引で「書く・変更履歴・更新番号」。journal は DELETE(共有フォルダで WAL を使わない)。その日の最初に書く前にマスタの隣の `backup/` へ控え(30日分) |
| 読めないとき | 共有に届かない・壊れている → 最後に読めた中身(控え JSON)か VBA の初期値で**計算は続ける**(画面の上にそう出る)。書く操作は断る |
| 鍵 | 管理者パスワード(既定は日報管理ツールと同じ。`make_dist.bat --admin-password` で配布の既定、設定 → 管理者パスワード で端末ごと。PBKDF2 で撹拌して持つ) |

## 要るもの

- **Python 3.8 以上だけ**。`pip install` は要りません(標準ライブラリだけで動きます。
  ラインPCの Python に追加のパッケージを入れられないため)
- デスクトップ版: Windows 10/11 の WebView2(Edge と一緒に入っています)
- インターネットは要りません(three.js・Chart.js・アイコンの字はアプリに同梱)

## 作り(各言語が得意なことをする)

```
CoilCalculator.exe(Rust / Tauri)                       … src-tauri/
 ├─ 窓・多重起動の防止・ブラウザ版との排他(OS のファイルロック)
 ├─ 画面のファイル(HTML/JS/CSS/three.js/Chart.js)をディスクから返す
 └─ 計算の要求(/api/…)だけを Python の標準入力へ ── ポートを使わない
        │ 標準入出力(1件 = 見出し1行 + 本文。python-web-tools と同じ形)
        ▼
bridge.py ─▶ coilcalc/(Python・標準ライブラリだけ)        … 計算の正はここ1か所
              web.py      要求1件を答える(デスクトップ版とブラウザ版で同じ関数)
              vc_api.py   VC長さ計算の経路(計算・早見表・設定・マスタの表・鍵)
              vc/         VC長さ計算(VBA と同じ式・丸め)・VC計算マスタ(sqlite3)・早見表・表の編集
              source_db.py 共有のマスタを写してから読む(掴まない)
              calc.py     コイル・平板の計算・入力の範囲・丸め・画面に出す文字・グラフの点
              jsnum.py    JS と同じ文字を出す数の扱い(toFixed・Math.round など)
        ▲
start_app.py(http.server。ブラウザ版=予備)              … Start.vbs / start.bat から

app/static/       index.html(外の枠・VC長さ計算。vc/*.js)と coil/index.html(コイル・平板。枠で載せる)
                  画面の操作・3D(three.js)・グラフ(Chart.js)・印刷 … 返ってきた文字を置くだけ
```

| 担当 | 持つもの | 理由 |
|---|---|---|
| **Rust** | 窓・ファイルを返す・Python の起動と監視・多重起動と排他 | OS の窓・プロセス・ファイルロックが得意。exe 1つで配れる。600KB の three.js を Python に通さない |
| **Python** | 計算・範囲の確かめ・丸め・表示の文字・グラフの点・VC計算マスタ(sqlite3。標準ライブラリ) | デスクトップ版とブラウザ版の**両方が同じ計算を通る**(正が1か所)。標準ライブラリだけで試験できる |
| **JS** | 入力・3D・グラフの描画・印刷・テーマ | ブラウザでしか描けないもの |

詳しくは [docs/デスクトップ版.md](docs/デスクトップ版.md)、移す前の確認(現在の機能を維持できるか)は
[docs/移植と機能維持の確認.md](docs/移植と機能維持の確認.md)。

## 試験

```
python -m unittest discover -s tests -t .          # Python(node があれば元の JS との突き合わせも)
cd src-tauri && cargo test --release               # Rust
xvfb-run python scripts/desktop_smoke.py --exe src-tauri/target/release/CoilCalculator   # exe を本当に起動
```

- `tests/test_js_equivalence.py` … **移す前の JS**(`tests/reference/original_js/`、日報管理ツールから
  1文字も変えずに写したもの)を node で動かし、同じ入力で Python が画面に**同じ文字**を出すことを
  約 3,000 組(うち計算まで進む約 2,200 組)で確かめる(範囲の判定・結果・詳細計算過程・モーダル・グラフの点)
- `scripts/desktop_smoke.py` … exe を起動して、計算が返る・**どのプロセスもポートで待ち受けない**・
  止めたら Python も終わる・ブラウザ版との排他(両方向)を確かめる
- `tests/test_vc_*.py`・`tests/test_web_vc.py` … 日報管理ツールの VC の試験を写したもの(VBA 互換の丸め・
  マスタの作成と移行・早見表・経路・鍵・表の編集の決まり)
- `tests/test_vc_shared_master.py` … 共有のマスタを掴まない・差し替えに付いていく・壊れていても止まらない
- `tests/test_vc_interop.py` … 日報管理ツールの実物のコードと同じマスタを読み書きし合う(相手のリポジトリが手元にあるときだけ。`NIPPOU_REPO`)
- `tests/test_manual.py` … 説明書の頁・写真がそろっている・写真の大きさ・説明書の版がツールの版と同じ

画面を変えたら、説明書の写真を撮り直します(作業用。node・Playwright・xdotool・ImageMagick を使う):

```
xvfb-run -a -s "-screen 0 1600x1000x24" python scripts/make_manual_images.py --exe src-tauri/target/release/CoilCalculator
```

Windows の exe は GitHub Actions が作ります(`.github/workflows/desktop-windows.yml`。
成果物 `CoilCalculator-windows`)。exe はアプリのフォルダの直下(`bridge.py` と同じ場所)に置きます。

## フォルダ

```
CoilCalculator.exe  (Actions の成果物を置く)    Start.vbs / start.bat / stop.bat  ブラウザ版の起動・停止
bridge.py          デスクトップ版の入口         start_app.py / process_manager.py  ブラウザ版の起動・停止の本体
coilcalc/          計算と答え方(Python)         app/static/                        画面(HTML/JS/CSS・同梱ライブラリ・説明書)
src-tauri/         デスクトップ版の外枠(Rust)   config/app.json                    版・ポート・自動終了の秒数・マスタの置き場所の既定
tests/             試験                          scripts/                           exe の確認・説明書の写真・アイコン作り
```

作業フォルダ: `%LOCALAPPDATA%\CoilCalculator\`(`logs\coilcalc.log`、`runtime\instance.lock`、`settings.json`、
`master\`(既定のマスタ)、`cache\`(マスタの写しと控え))

配るときは `scripts\make_dist.bat`(配るものだけを新しいフォルダへ写す。起動ファイルは CP932 + CRLF を保証)。
