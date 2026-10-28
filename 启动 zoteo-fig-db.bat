@echo off
chcp 65001 >nul
setlocal
cd /d "D:\Zotero\fig_db"

rem 1. clear manual-stop marker
del /q "D:\Zotero\fig_db\.manual_stop" 2>nul

rem 2. already listening -> just open browser
netstat -ano | findstr ":5173" | findstr "LISTENING" >nul
if %errorlevel% equ 0 (
    start http://127.0.0.1:5173
    exit /b 0
)

rem 3. launch hidden server (zoteo-fig-db.exe = pythonw clone)
powershell -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath 'd:\Users\chmzs\Documents\Pixi_env\.pixi\envs\geo\zoteo-fig-db.exe' -ArgumentList 'D:\Zotero\fig_db\server.py' -WorkingDirectory 'D:\Zotero\fig_db' -WindowStyle Hidden"

rem 4. poll until ready (ping = portable 1s sleep, avoids timeout.exe PATH conflicts)
set /a n=0
:waitloop
netstat -ano | findstr ":5173" | findstr "LISTENING" >nul
if %errorlevel% equ 0 goto ready
set /a n+=1
if %n% geq 40 goto ready
ping -n 2 127.0.0.1 >nul
goto waitloop

:ready
start http://127.0.0.1:5173
exit /b 0
