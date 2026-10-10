' ===================================================================
'  VC長さ・コイル平板 計算ツール ショートカットを作る
'
'  配布フォルダを配ったあと、その PC でこのファイルをダブルクリックすると、
'  ツールのフォルダ(この scripts の1つ上)に次の2つを作ります。
'    VC長さ・コイル平板 計算ツール(ブラウザ版).lnk     … Start.vbs
'    VC長さ・コイル平板 計算ツール(デスクトップ版).lnk … CoilCalculator.exe(あれば。アイコンも exe のもの)
'  指す先は**いまのフォルダの場所**です。フォルダを移したら、もう一度押してください。
'  何度押しても作り直すだけです。exe が無いフォルダでは、デスクトップ版のショートカットは作らず、
'  そのことを結果の窓で知らせます。Windows の機能(WSH)だけで動きます(Python は要りません)。
'
'  --- keep this file in CP932 (Shift-JIS) with CRLF line endings ---
'  WSH reads a .vbs with the system ANSI code page (932 on Japanese Windows).
'  Messages use WScript.Echo: a dialog when double-clicked, text under cscript.
' ===================================================================
Option Explicit

' ファイルの名前は文字の番号(Unicode)で組み立てる。.vbs はシステムの文字コードで読まれるので、
' 日本語をそのまま書くと、日本語でない Windows では名前が化ける(結果の文は化けても困らない)
Dim APP_NAME, EXE_NAME, BROWSER, DESKTOP
APP_NAME = U("0056 0043 9577 3055 30FB 30B3 30A4 30EB 5E73 677F 0020 8A08 7B97 30C4 30FC 30EB")   ' VC長さ・コイル平板 計算ツール
EXE_NAME = "CoilCalculator.exe"
BROWSER = U("0028 30D6 30E9 30A6 30B6 7248 0029")                       ' (ブラウザ版)
DESKTOP = U("0028 30C7 30B9 30AF 30C8 30C3 30D7 7248 0029")             ' (デスクトップ版)

Dim shell, fso, here, made, missing, failed
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
made = ""
missing = ""
failed = ""

MakeLink APP_NAME & BROWSER & ".lnk", "Start.vbs", False
MakeLink APP_NAME & DESKTOP & ".lnk", EXE_NAME, True

Dim msg
If made <> "" Then
    msg = "ショートカットを作りました(場所: " & here & "):" & made
Else
    msg = "ショートカットは1つも作れませんでした(場所: " & here & ")。"
End If
If missing <> "" Then
    msg = msg & vbCrLf & vbCrLf & "次は見つからないので作っていません:" & missing
End If
If failed <> "" Then
    msg = msg & vbCrLf & vbCrLf & "次は保存できませんでした:" & failed
End If
WScript.Echo msg
If failed <> "" Then WScript.Quit 1

' "0056 0043" のような文字の番号の並びを文字列にする
Function U(codes)
    Dim parts, i, s
    parts = Split(codes, " ")
    s = ""
    For i = 0 To UBound(parts)
        s = s & ChrW(CLng("&H" & parts(i)))
    Next
    U = s
End Function

Sub MakeLink(linkName, targetName, useIcon)
    Dim target, lnk
    target = fso.BuildPath(here, targetName)
    If Not fso.FileExists(target) Then
        missing = missing & vbCrLf & "  " & targetName
        Exit Sub
    End If
    ' 保存できないとき(書けないフォルダ・名前に使えない文字)は、理由を結果の窓に出す
    On Error Resume Next
    Set lnk = shell.CreateShortcut(fso.BuildPath(here, linkName))
    lnk.TargetPath = target
    lnk.WorkingDirectory = here
    lnk.Description = APP_NAME & "を起動する"
    If useIcon Then lnk.IconLocation = target & ",0"
    lnk.Save
    If Err.Number <> 0 Then
        failed = failed & vbCrLf & "  " & linkName & "(" & Err.Description & ")"
        Err.Clear
        On Error GoTo 0
        Exit Sub
    End If
    On Error GoTo 0
    If Not fso.FileExists(fso.BuildPath(here, linkName)) Then
        failed = failed & vbCrLf & "  " & linkName & "(保存したはずのファイルがありません)"
        Exit Sub
    End If
    made = made & vbCrLf & "  " & linkName & " → " & targetName
End Sub
