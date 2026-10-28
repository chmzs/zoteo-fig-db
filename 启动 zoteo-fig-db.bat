@echo off
chcp 65001 >nul
setlocal
cd /d "D:\Zotero\fig_db"

rem 1. clear manual-stop marker so watchdog may heal
del /q "D:\Zotero\fig_db\.manual_stop" 2>nul

rem 2. delegate startup to watchdog.py (single source of truth: starts 5173 + 23122)
"d:\Users\chmzs\Documents\Pixi_env\.pixi\envs\geo\python.exe" -u "D:\Zotero\fig_db\watchdog.py"

rem 3. poll gallery until it answers (ping = portable 1s sleep; max 50s)
set /a n=0
:waitloop
curl -s -m 1 -o nul http://127.0.0.1:5173/api/stats 2>nul
if %errorlevel% equ 0 goto ready
set /a n+=1
if %n% geq 50 goto ready
ping -n 2 127.0.0.1 >nul
goto waitloop

:ready
rem 4. open browser only after ready
start http://127.0.0.1:5173
exit /b 0
