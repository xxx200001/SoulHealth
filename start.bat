@echo off
chcp 65001 >nul 2>&1
title SoulHealth - 一键启动
setlocal
cd /d "%~dp0"

echo.
echo ==================================================
echo   SOULHEALTH AI 健康科研平台  一键启动
echo ==================================================
echo.

:: 端口只在 .env 里配一次；这里读出来给前端代理与提示用
set SH_PORT=8001
if exist ".env" for /f "usebackq tokens=1,2 delims==" %%a in (".env") do if /i "%%a"=="SOULHEALTH_PORT" set SH_PORT=%%b

python --version >nul 2>&1
if errorlevel 1 (
  echo [错误] 未检测到 Python，请安装 Python 3.10+ 并勾选 Add Python to PATH
  echo        https://www.python.org/downloads/
  pause & exit /b 1
)
echo [OK] Python 已就绪

echo [*] 检查/安装后端依赖...
pip install -r requirements.txt -q 2>nul
echo [OK] 后端依赖已就绪

node --version >nul 2>&1
if errorlevel 1 (
  echo [错误] 未检测到 Node.js，请安装 Node.js 18+  https://nodejs.org/
  pause & exit /b 1
)
echo [OK] Node.js 已就绪

if not exist "web\\node_modules" (
  echo [*] 首次运行，正在安装前端依赖 npm install ...
  pushd web && call npm install && popd
)
echo [OK] 前端依赖已就绪

echo [*] 启动后端 (端口 %SH_PORT%)...
start "SoulHealth-Backend" cmd /k "set PYTHONIOENCODING=utf-8 & python run.py"
ping 127.0.0.1 -n 5 >nul

echo [*] 启动前端 (端口 5173)...
start "SoulHealth-Frontend" /D "%~dp0web" cmd /k "npm run dev"
ping 127.0.0.1 -n 5 >nul

echo.
echo ==================================================
echo   已启动
echo   页面入口   http://localhost:5173
echo   接口文档   http://localhost:%SH_PORT%/docs
echo   运行状态   http://localhost:%SH_PORT%/api/health
echo ==================================================
echo.
echo   首次启动的管理员密码打印在后端窗口里，请先复制保存。
echo   停止全部服务请运行 stop.bat
echo.
start http://localhost:5173
pause
