"""VC長さ・コイル平板 計算ツール(Python 側)

    jsnum          JS と同じ文字を出す数の扱い(toFixed・String・Math.round・parseFloat)
    calc           コイル・平板の計算と、画面に出す文字(計算の正はここ)
    web            要求1件を答える(デスクトップ版・ブラウザ版で共通。標準ライブラリだけ)
    app_config     config/app.json と、この端末の作業フォルダ
    instance_lock  ブラウザ版とデスクトップ版を同時に動かさない錠(Rust 側と同じファイル)
    logging_setup  動作ログ

**標準ライブラリだけで動きます**(ラインPCの Python には追加のパッケージを入れられない)。
"""
