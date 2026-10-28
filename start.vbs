' zoteo-fig-db launcher (pure ASCII, no encoding dependency)
' Design: launcher does NOT duplicate process-spawn logic.
'   It delegates to watchdog.py (the single source of truth for starting both
'   services), then polls until the gallery responds, and only then opens the
'   browser -- fixing the old bug where the browser opened before the server
'   was ready (ERR_CONNECTION_REFUSED / '-- figures' on first paint).
Dim ws, fso, i
Set ws = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

Dim py, base
py = "d:\Users\chmzs\Documents\Pixi_env\.pixi\envs\geo\python.exe"
base = "D:\Zotero\fig_db\"

' 1. clear manual-stop marker so the watchdog is allowed to heal
On Error Resume Next
If fso.FileExists(base & ".manual_stop") Then fso.DeleteFile base & ".manual_stop", True
On Error GoTo 0

' 2. port probe helper
Function PortAlive(u)
    Dim h
    PortAlive = False
    On Error Resume Next
    Set h = CreateObject("MSXML2.XMLHTTP")
    h.Open "GET", u, False
    h.Send
    If Err.Number = 0 Then
        If h.Status < 500 Then PortAlive = True
    End If
    Err.Clear
    On Error GoTo 0
End Function

' 3. delegate startup to watchdog.py (starts 5173 + 23122, respects markers)
ws.Run Chr(34) & py & Chr(34) & " " & Chr(34) & base & "watchdog.py" & Chr(34), 0, False

' 4. poll gallery until it answers (first boot loads 16k-row matrix, ~5-10s; cap 50s)
i = 0
Do While i < 100
    If PortAlive("http://127.0.0.1:5173/api/stats") Then Exit Do
    WScript.Sleep 500
    i = i + 1
Loop

' 5. open browser only after the gallery is actually answering
ws.Run "cmd.exe /c start http://127.0.0.1:5173", 0, False
