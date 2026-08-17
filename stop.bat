@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo 正在停止 SoulHealth 所有服务...

set SH_PORT=8001
if exist ".env" for /f "usebackq tokens=1,2 delims==" %%a in (".env") do if /i "%%a"=="SOULHEALTH_PORT" set SH_PORT=%%b

taskkill /f /fi "WINDOWTITLE eq SoulHealth-Backend*"  >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq SoulHealth-Frontend*" >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq SoulHealth-Tunnel*"   >nul 2>&1
taskkill /f /im cloudflared.exe >nul 2>&1

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%SH_PORT% ^| findstr LISTENING') do taskkill /f /pid %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5173 ^| findstr LISTENING') do taskkill /f /pid %%a >nul 2>&1

echo [OK] 所有服务已停止
pause
