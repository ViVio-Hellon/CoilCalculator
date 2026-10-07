@echo off
rem  --- keep this file in CP932 (Shift-JIS) with CRLF line endings ---
rem  Everything above the chcp line must stay ASCII. cmd.exe parses a .bat
rem  with the *console* code page, so the page has to be set before the
rem  first non-ASCII byte - including the bytes in these comments.
rem  tests/test_launch_files.py enforces the encoding and this ordering.
chcp 932 >nul 2>&1
rem ===================================================================
rem  VC長さ・コイル平板 計算ツール (ブラウザ版・予備) 診断起動
rem
rem  ふだんはデスクトップ版(CoilCalculator.exe)か Start.vbs を使います。
rem  こちらは「起動しないとき」に原因を見るためのもので、コンソールを
rem  開いたまま経過を表示します。
rem
rem      start.bat              起動してブラウザで開く
rem      start.bat --check      動かせるかの確認だけして終わる
rem ===================================================================
setlocal

rem  共有フォルダ(\\サーバ\...)は現在地にできないので pushd を使う
pushd "%~dp0" || (
    echo [エラー] このフォルダに移動できませんでした: %~dp0
    pause
    exit /b 1
)
title VC長さ・コイル平板 計算ツール - 診断起動 (この窓は閉じないでください)

python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo [エラー] Python が見つかりません。
    echo.
    echo   https://www.python.org/downloads/ からインストールしてください。
    echo   インストーラの最初の画面で
    echo   「Add python.exe to PATH」に必ずチェックを入れてください。
    echo   追加のパッケージ（pip install）は要りません。
    echo.
    goto :failed
)

echo === 動かせるかの確認 ===
python start_app.py --check
if errorlevel 1 (
    echo.
    echo 上のメッセージを確認してください。
    goto :failed
)

echo.
echo === 起動 ===
echo この窓を閉じるとアプリが終了します。
echo 終了するときは stop.bat を実行するか、画面の「終了」を押してください。
echo.
python start_app.py %*
if errorlevel 3 (
    echo.
    echo もう一方の版（デスクトップ版）が開いているため、起動しませんでした。
    echo 同時には使えません。デスクトップ版を閉じてから開き直してください。
    echo.
    goto :failed
)
if errorlevel 1 (
    echo.
    echo [エラー] 起動に失敗しました。上のメッセージを確認してください。
    echo          ログ: %LOCALAPPDATA%\CoilCalculator\logs\coilcalc.log
    echo.
    goto :failed
)

echo.
echo 終了しました。この窓は閉じてかまいません。
pause
popd
endlocal
exit /b 0

:failed
pause
popd
endlocal
exit /b 1
