#!/usr/bin/env bash
# Linux / macOS 一键启动：后端 + 前端开发服务器
set -e
cd "$(dirname "$0")"

PORT=$(grep -E '^SOULHEALTH_PORT=' .env 2>/dev/null | cut -d= -f2)
PORT=${PORT:-8001}

echo "=================================================="
echo "  SOULHEALTH AI 健康科研平台"
echo "=================================================="

command -v python3 >/dev/null || { echo "[错误] 未检测到 python3"; exit 1; }
echo "[*] 检查后端依赖…"
python3 -m pip install -r requirements.txt -q

if command -v npm >/dev/null; then
  [ -d web/node_modules ] || { echo "[*] 安装前端依赖…"; (cd web && npm install); }
  (cd web && npm run dev) &
  FRONT_PID=$!
  trap 'kill $FRONT_PID 2>/dev/null || true' EXIT
  echo "[OK] 前端 http://localhost:5173"
else
  echo "[提示] 未检测到 npm，仅启动后端；若已执行过 npm run build，"
  echo "       可直接访问 http://localhost:$PORT/"
fi

echo "[OK] 后端 http://localhost:$PORT/docs"
python3 run.py
