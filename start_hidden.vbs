Dim ws
Set ws = CreateObject("WScript.Shell")
On Error Resume Next
ws.Run chr(34) & "d:\Users\chmzs\Documents\Pixi_env\.pixi\envs\geo\zoteo-fig-db.exe" & chr(34) & " " & chr(34) & "D:\Zotero\fig_db\server.py" & chr(34), 0, False
ws.Run "cmd.exe /c start http://127.0.0.1:5173", 0, False
