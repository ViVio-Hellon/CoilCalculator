@echo off
rem  --- keep this file in CP932 (Shift-JIS) with CRLF line endings ---
rem  Keep everything above the chcp line ASCII; see start.bat for why.
chcp 932 >nul 2>&1
rem ===================================================================
rem  VC長さ・コイル平板 計算ツール 終了の入口 (業務ツール統合ランチャー 1.7.0)
rem
rem  ランチャーの［ツール停止］・切り替えで実行します。stop.bat と同じく
rem  デスクトップ版もブラウザ版も確かめを出さずに止めます。VC計算マスタへ
rem  書いている最中なら書き終えてから止まります。
rem  終了コード: 0 = 止めた / 1 = 止めなかった (最後の1行が理由。ランチャーが
rem  利用者に出し、強制終了を選んだときだけランチャーが stop.bat --force で続けます)。
rem  ほかのツールの Python・exe には触りません。pause は置きません。
rem ===================================================================
setlocal
set PYTHONIOENCODING=utf-8
python "%~dp0process_manager.py" %*
exit /b %errorlevel%
