@echo off
chcp 65001 >nul 2>&1
title SoulHealth - 公网穿透
cd /d "%~dp0"
python scripts\start_tunnel.py 5173
pause
