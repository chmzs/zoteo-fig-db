' zoteo-fig-db launcher (pure ASCII, no encoding dependency)
' Flow: clear stop-marker -> launch hidden server if not running -> poll port -> open browser
Dim ws, fso, i
Set ws = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' 1. clear manual-stop marker so watchdog can heal
On Error Resume Next
If fso.FileExists("D:\Zotero\fig_db\.manual_stop") Then fso.DeleteFile "D:\Zotero\fig_db\.manual_stop", True
On Error GoTo 0

' 2. port probe
Function PortAlive()
    Dim h
    PortAlive = False
    On Error Resume Next
    Set h = CreateObject("MSXML2.XMLHTTP")
    h.Open "GET", "http://127.0.0.1:5173/api/stats", False
    h.Send
    If Err.Number = 0 Then
        If h.Status = 200 Then PortAlive = True
    End If
    Err.Clear
    On Error GoTo 0
End Function

' 3. launch hidden server only when not running
If Not PortAlive() Then
    ws.Run Chr(34) & "d:\Users\chmzs\Documents\Pixi_env\.pixi\envs\geo\zoteo-fig-db.exe" & Chr(34) & " " & Chr(34) & "D:\Zotero\fig_db\server.py" & Chr(34), 0, False
End If

' 4. poll until ready (first boot loads 16k-row vector matrix, ~5-10s; cap 40s)
i = 0
Do While i < 80
    If PortAlive() Then Exit Do
    WScript.Sleep 500
    i = i + 1
Loop

' 5. open browser only after ready (or after timeout)
ws.Run "cmd.exe /c start http://127.0.0.1:5173", 0, False
