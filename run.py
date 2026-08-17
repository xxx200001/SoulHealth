#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一键启动后端：环境自检 → 数据库初始化 → 知识库自检 → uvicorn。

    python run.py              默认 0.0.0.0:8001
    python run.py --port 9000  指定端口
    python run.py --reload     开发模式（改代码自动重启）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    parser = argparse.ArgumentParser(description="SOULHEALTH AI 健康科研平台")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print("[错误] 未安装依赖。请先执行：pip install -r requirements.txt")
        return 1

    from app import config
    from app.archive import repository as repo
    from app.tcm.kb import bootstrap as kb_bootstrap

    host = args.host or config.HOST
    port = args.port or config.PORT

    print("=" * 62)
    print("  SOULHEALTH AI 健康科研平台  v" + config.VERSION)
    print("=" * 62)
    repo.init()
    kb = kb_bootstrap.ensure(config.TCM_KB_PATH, autobuild=config.TCM_KB_AUTOBUILD)

    print(f"[模型] 大模型模式：{config.LLM_MODE}"
          + ("（图片抽取 / AI 解读 / 健康问答可用）" if config.LLM_MODE == "real"
             else "（未配置 ANTHROPIC_API_KEY：图片抽取、AI 解读、健康问答不可用；"
                  "辨证组方与风险识别不受影响）"))
    print(f"[生物计算] {config.BIOCOMPUTE_MODE}"
          + ("" if config.NVIDIA_API_KEY or "localhost" in config.EVO2_URL
             else "（EVO2 未配置，将如实标记 skipped）"))
    if config.SECRET_KEY_IS_DEFAULT:
        print("[安全] 正在使用默认令牌密钥，仅适合本机演示。"
              "对外部署请设置 SOULHEALTH_SECRET_KEY。")
    if not kb.get("ready"):
        print("[警告] 中医知识库不可用，辨证与组方功能将报错，其余功能正常。")

    print("-" * 62)
    print(f"  后端 API   http://127.0.0.1:{port}/docs")
    print(f"  健康检查   http://127.0.0.1:{port}/api/health")
    if config.WEB_DIST.exists():
        print(f"  前端页面   http://127.0.0.1:{port}/")
    else:
        print("  前端页面   开发模式请另开终端：cd web && npm run dev  → :5173")
    print("=" * 62)

    uvicorn.run("app.main:app", host=host, port=port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
