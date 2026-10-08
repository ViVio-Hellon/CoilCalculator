@echo off
rem  --- keep this file in CP932 (Shift-JIS) with CRLF line endings ---
rem  Keep everything above the chcp line ASCII; see start.bat for why.
chcp 932 >nul 2>&1
rem ===================================================================
rem  VC長さ・コイル平板 計算ツール 起動確認の入口 (業務ツール統合ランチャー 1.7.0)
rem
rem  ランチャーが起動を待つあいだ毎秒、動いているあいだは見回りのたびに実行します。
rem  終了コード: 0 = 使える / 2 = 準備中 / 1 = 動いていない。
rem  最後の1行に今の様子を出します (ランチャーの起動中の窓に出る)。
rem  デスクトップ版でもブラウザ版でも同じに答えます。錠には触りません。
rem  画面は出ません。pause は置きません。
rem ===================================================================
setlocal
set PYTHONIOENCODING=utf-8
python "%~dp0process_manager.py" --check
exit /b %errorlevel%
