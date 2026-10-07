@echo off
rem  --- keep this file in CP932 (Shift-JIS) with CRLF line endings ---
rem  Keep everything above the chcp line ASCII; see start.bat for why.
chcp 932 >nul 2>&1
rem ===================================================================
rem  VC長さ・コイル平板 計算ツール (ブラウザ版) 停止
rem
rem  このアプリだけを止めます。同じPCで動くほかの Python アプリは
rem  影響を受けません。デスクトップ版は窓の × で閉じます
rem  (強制的に止めるときだけ stop.bat --force)。
rem ===================================================================
setlocal

pushd "%~dp0" || (
    echo [エラー] このフォルダに移動できませんでした: %~dp0
    pause
    exit /b 1
)
title VC長さ・コイル平板 計算ツール - 停止

python --version >nul 2>&1
if errorlevel 1 (
    echo [エラー] Python が見つかりません。
    goto :failed
)

python process_manager.py %*
if errorlevel 1 (
    echo.
    echo 止められなかったものがあります。上のメッセージを確認してください。
    goto :failed
)
popd
endlocal
exit /b 0

:failed
pause
popd
endlocal
exit /b 1
