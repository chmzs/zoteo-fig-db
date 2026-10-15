' 隐藏窗口启动"启动 zoteo-fig-db.bat"（开始菜单快捷方式调用，避免黑框闪烁）
Dim ws
Set ws = CreateObject("WScript.Shell")
ws.Run "cmd /c ""D:\Zotero\fig_db\启动 zoteo-fig-db.bat""", 0, False
