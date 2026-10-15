@echo off
chcp 65001 >nul
title 停止 zoteo-fig-db
powershell -NoProfile -Command "Get-Process zoteo-fig-db,GeoFigureServer -ErrorAction SilentlyContinue | Stop-Process -Force"
echo [成功] zoteo-fig-db 服务已停止。
timeout /t 2 /nobreak >nul
