# コイル・平板 重量計算ツール (CoilCalculator)

アルミなどの**コイル**(肉厚・内径・幅・比重・板厚 → 重量・長さ・巻き数)と
**平板**(A・B・板厚・比重 → 重量・面積・体積)を計算するツールです。
3D 表示・パラメータ影響グラフ・計算書の印刷つき。

日報管理ツール([vba-daily-report-python-migration](https://github.com/ViVio-Hellon/vba-daily-report-python-migration))の
「VC長さ計算 → コイル・平板」を**その部分だけ丸ごと**取り出し、
[python-web-tools](https://github.com/ViVio-Hellon/python-web-tools) と同じ
**Python + Tauri/Rust のデスクトップ版**に作り替えたものです。

## 使い方

| 版 | 開き方 | ポート | 備考 |
|---|---|---|---|
| **デスクトップ版**(ふだん) | `CoilCalculator.exe` をダブルクリック | **使わない** | 専用の窓で開く。閉じるのは窓の × →「終了する」 |
| ブラウザ版(予備) | `Start.vbs` をダブルクリック | 127.0.0.1:8741〜 | 既定のブラウザで開く。閉じるのは画面左上の「終了」→ OK か `stop.bat` |

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

- **版**: 画面の左上に「v1.1.0 デスクトップ版」のように出ます。押すと、アプリ・外枠(Rust)・
  計算(Python)の版と、どちらの版で動いているかが出ます。デスクトップ版の窓の題名・印刷した計算書にも版が入ります
- **操作説明書**: 画面の左上の「操作説明」で、いま見ている形状(コイル / 平板)の説明書が開きます
  (デスクトップ版は別の窓、ブラウザ版は別のタブ)。中身は `app/static/manual/`(画面の写真入りの HTML)。
  変更の記録は [docs/変更履歴.md](docs/変更履歴.md)

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
              calc.py   計算・入力の範囲・丸め・画面に出す文字・グラフの点
              jsnum.py  JS と同じ文字を出す数の扱い(toFixed・Math.round など)
              web.py    要求1件を答える(デスクトップ版とブラウザ版で同じ関数)
        ▲
start_app.py(http.server。ブラウザ版=予備)              … Start.vbs / start.bat から

app/static/(JS)  画面の操作・3D(three.js)・グラフ(Chart.js)・印刷 … 返ってきた文字を置くだけ
```

| 担当 | 持つもの | 理由 |
|---|---|---|
| **Rust** | 窓・ファイルを返す・Python の起動と監視・多重起動と排他 | OS の窓・プロセス・ファイルロックが得意。exe 1つで配れる。600KB の three.js を Python に通さない |
| **Python** | 計算・範囲の確かめ・丸め・表示の文字・グラフの点 | デスクトップ版とブラウザ版の**両方が同じ計算を通る**(正が1か所)。標準ライブラリだけで試験できる |
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
coilcalc/          計算と答え方(Python)         app/static/                        画面(HTML/JS/CSS・同梱ライブラリ)
src-tauri/         デスクトップ版の外枠(Rust)   config/app.json                    版・ポート・自動終了の秒数
tests/             試験                          scripts/                           exe の確認・説明書の写真・アイコン作り
```

作業フォルダ(ログ・錠): `%LOCALAPPDATA%\CoilCalculator\`(`logs\coilcalc.log`、`runtime\instance.lock`)
