@echo off
chcp 65001 >nul
cd /d "D:\Zotero\fig_db"

netstat -ano | findstr ":5173" | findstr "LISTENING" >nul
if %errorlevel% equ 0 (
    start http://127.0.0.1:5173
    exit /b 0
)

del /q "D:\Zotero\fig_db\.manual_stop" 2>nul
:: zoteo-fig-db.exe = pythonw 副本（无控制台；任务管理器进程名即品牌名）
powershell -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath 'd:\Users\chmzs\Documents\Pixi_env\.pixi\envs\geo\zoteo-fig-db.exe' -ArgumentList 'D:\Zotero\fig_db\server.py' -WorkingDirectory 'D:\Zotero\fig_db' -WindowStyle Hidden"
exit /b 0
