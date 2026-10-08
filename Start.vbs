' ===================================================================
'  VC長さ・コイル平板 計算ツール (ブラウザ版・予備) 起動
'
'  ふだんはデスクトップ版(CoilCalculator.exe)を使います。こちらは
'  デスクトップ版が使えないときの予備で、ブラウザで画面を開きます。
'  **このファイル1つをダブルクリックするだけ**です。
'  起動しないときは start.bat を使うと原因が表示されます。
'
'  ブラウザ版とデスクトップ版は同時に動きません。後から開いたほうが
'  「もう一方が動いています」と出して止まります(start_app.py)。
'
'  --- keep this file in CP932 (Shift-JIS) with CRLF line endings ---
'  WSH reads a .vbs with the system ANSI code page, which is 932 on the
'  Japanese Windows this tool runs on. tests/test_launch_files.py checks it.
' ===================================================================
Option Explicit

Const APP_NAME = "VC長さ・コイル平板 計算ツール"

Dim shell, fso, here, script, cmd
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
script = fso.BuildPath(here, "start_app.py")

' 本体が同じフォルダにあるか。pythonw はコンソールを出さないので、
' 無いまま起動すると本当に「何も起きない」。ここで気づけるようにする
' (このファイルだけをデスクトップにコピーすると、この状態になる)
If Not fso.FileExists(script) Then
    MsgBox "start_app.py が見つかりません。" & vbCrLf & vbCrLf & _
           "探した場所: " & script & vbCrLf & vbCrLf & _
           "このファイルは、アプリ一式が入ったフォルダの中から" & vbCrLf & _
           "実行してください(ショートカットを作るのは大丈夫です)。", _
           vbCritical, APP_NAME
    WScript.Quit 1
End If

' Python があるかを先に確かめる。無いまま起動すると、
' コンソールが出ないぶん「何も起きない」ように見えてしまう
If shell.Run("cmd /c python --version", 0, True) <> 0 Then
    MsgBox "Python が見つかりません。" & vbCrLf & vbCrLf & _
           "https://www.python.org/downloads/ からインストールし、" & vbCrLf & _
           "インストーラの最初の画面で「Add python.exe to PATH」に" & vbCrLf & _
           "チェックを入れてください(追加のパッケージは要りません)。" & vbCrLf & vbCrLf & _
           "詳しい原因を見るには start.bat を実行してください。", _
           vbCritical, APP_NAME
    WScript.Quit 1
End If

' 実際に使うのは pythonw のほう。python はあるのに pythonw だけ無いことが
' あるので、走らせる前に確かめる(黙って失敗しないように)
If shell.Run("cmd /c pythonw --version", 0, True) <> 0 Then
    MsgBox "pythonw が見つかりません。" & vbCrLf & vbCrLf & _
           "Python は入っていますが、画面を出さずに起動するための" & vbCrLf & _
           "pythonw.exe がありません。" & vbCrLf & _
           "start.bat から起動してください(コンソールが開きます)。", _
           vbCritical, APP_NAME
    WScript.Quit 1
End If

' pythonw はコンソールを出さない。起動の結果は待たずに抜ける(False)。
' デスクトップ版が開いているなどで起動しないときは、start_app.py が
' メッセージの窓で知らせる。
' パスは絶対パスで渡す。共有フォルダから実行されることもある
shell.CurrentDirectory = here
cmd = "pythonw " & Chr(34) & script & Chr(34)
' 渡された引数はそのまま start_app.py へ渡す(ランチャーが --no-browser を付けて呼ぶと、
' 画面はランチャーが開き、止めるときに閉じられる)。ふだんのダブルクリックは引数なし
Dim i
For i = 0 To WScript.Arguments.Count - 1
    cmd = cmd & " " & Chr(34) & WScript.Arguments(i) & Chr(34)
Next
shell.Run cmd, 0, False
