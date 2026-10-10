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
    Dim target, finalPath, reason
    target = fso.BuildPath(here, targetName)
    If Not fso.FileExists(target) Then
        missing = missing & vbCrLf & "  " & targetName
        Exit Sub
    End If
    finalPath = fso.BuildPath(here, linkName)
    reason = WriteLink(finalPath, linkName, target, useIcon)
    If reason = "" And Not fso.FileExists(finalPath) Then reason = "保存したはずのファイルがありません"
    If reason <> "" Then
        failed = failed & vbCrLf & "  " & linkName & "(" & reason & ")"
        Exit Sub
    End If
    made = made & vbCrLf & "  " & linkName & " → " & targetName
End Sub

' ショートカットを書く。書けなければ理由を返す(書けたら "")。
' WScript.Shell のショートカットは**システムの文字コード**で名前と場所を扱うので、その文字コードに無い文字
' (英語の Windows での日本語など)があると保存できない。そこで、
'   1. WScript.Shell で一時フォルダに英字の名前の .lnk を作り(中身は仮)
'   2. 本来の場所・名前へ写し(ファイルの操作は Unicode で通る)
'   3. Shell.Application(Unicode で扱える)で指す先・作業フォルダ・アイコンを書き直す
Function WriteLink(finalPath, linkName, target, useIcon)
    Dim tmp, lnk, app, folder, item, link
    On Error Resume Next
    tmp = fso.BuildPath(fso.GetSpecialFolder(2), "coilcalc_shortcut_" & fso.GetTempName() & ".lnk")
    Set lnk = shell.CreateShortcut(tmp)
    lnk.TargetPath = fso.BuildPath(fso.GetSpecialFolder(1), "cmd.exe")
    lnk.Save
    If Err.Number <> 0 Then WriteLink = Why(): Exit Function
    If fso.FileExists(finalPath) Then fso.DeleteFile finalPath, True
    fso.CopyFile tmp, finalPath, True
    fso.DeleteFile tmp, True
    If Err.Number <> 0 Then WriteLink = Why(): Exit Function
    Set app = CreateObject("Shell.Application")
    Set folder = app.NameSpace(here)
    Set item = folder.ParseName(linkName)
    Set link = item.GetLink
    link.Path = target
    link.WorkingDirectory = here
    link.Description = APP_NAME & "を起動する"
    If useIcon Then link.SetIconLocation target, 0
    link.Save
    If Err.Number <> 0 Then WriteLink = Why(): Exit Function
    WriteLink = ""
End Function

Function Why()
    Why = "エラー " & Hex(Err.Number) & " " & Err.Description
End Function
