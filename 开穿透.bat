@echo off
chcp 65001 >nul 2>&1
title SoulHealth - 公网穿透与远程演示
setlocal
cd /d "%~dp0"

echo.
echo ==================================================
echo   SOULHEALTH AI 平台 - 开启 Cloudflare 公网穿透
echo ==================================================
echo.

python scripts\start_tunnel.py 5173
pause
