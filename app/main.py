"""SOULHEALTH AI 健康科研平台 —— FastAPI 装配入口。

启动：python run.py（推荐，含知识库自检）
     或 uvicorn app.main:app --host 0.0.0.0 --port 8001

本文件只做装配：中间件、路由挂载、静态托管、启动自检。
业务逻辑全在 app/api/* 与各引擎模块里。

接口总览
--------
  认证      POST /api/auth/login|register|change_password   GET /api/auth/me
  管理员    GET|POST /api/admin/users   PATCH|DELETE /api/admin/users/{uid}
  档案      GET|POST /api/patients      GET|PATCH|DELETE /api/patients/{pid}
            POST /api/patients/demo（载入演示患者）
            GET  /api/patients/{pid}/timeline
            POST /api/patients/{pid}/notes|observations|findings|impressions
  四诊      GET  /api/tcm/questionnaire
            POST /api/tcm/{pid}/tongue|face|inquiry
            GET  /api/tcm/{pid}/exams   DELETE /api/tcm/{pid}/exams/{exam_id}
  资料      POST /api/documents/upload  GET /api/documents/{doc_id}
            GET  /api/selftest/vision
  分析      POST /api/analysis/run      GET /api/analysis/patient/{pid}
            GET  /api/analysis/{aid}
  报告      GET  /api/patients/{pid}/reports
            GET  /api/reports/{rid}/preview|download
  问答      POST /api/qa/{pid}
  状态      GET  /api/health
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config
from .api import analysis, auth, documents, patients, qa, reports, tcm
from .archive import repository as repo
from .tcm.kb import bootstrap as kb_bootstrap

app = FastAPI(
    title="SOULHEALTH AI 健康科研平台",
    version=config.VERSION,
    description="中医辨证溯源 × 生物计算健康分析，统一档案、统一分析、统一报告。",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

for _router in (auth.router, patients.router, tcm.router, documents.router,
                analysis.router, reports.router, qa.router):
    app.include_router(_router, prefix="/api")

_KB_REPORT: dict = {}


@app.on_event("startup")
def _startup() -> None:
    global _KB_REPORT
    repo.init()
    _KB_REPORT = kb_bootstrap.ensure(config.TCM_KB_PATH,
                                     autobuild=config.TCM_KB_AUTOBUILD)


@app.get("/api/health", tags=["状态"], summary="运行状态与能力自检")
def health() -> dict:
    """前端启动时调用：一次拿到服务状态、模型配置、知识库就绪情况，
    界面据此决定哪些能力可用、哪些需要提示配置。"""
    kb = _KB_REPORT or kb_bootstrap.check(config.TCM_KB_PATH)
    return {
        "status": "ok",
        **config.runtime_info(),
        "tcm_kb": {"ready": kb.get("ready"), "level": kb.get("level"),
                   "message": kb.get("message"), "stats": kb.get("stats", {})},
        "capabilities": {
            "tcm_syndrome": bool(kb.get("ready")),      # 辨证组方（离线）
            "tongue_face": True,                        # 舌面诊量化（离线）
            "risk_rules": True,                         # 风险识别（离线）
            "vision_extract": config.LLM_MODE == "real",  # 图片抽取（需密钥）
            "ai_interpret": config.LLM_MODE == "real",    # AI 解读（需密钥）
            "qa": config.LLM_MODE == "real",              # 健康问答（需密钥）
            "biocompute": config.BIOCOMPUTE_MODE != "off",
        },
    }


# ---------------------------------------------------------------- 前端托管
# web/dist 存在（npm run build 之后）即由后端直接托管，单进程单端口即可访问；
# 开发期用 vite dev server（5173）并由其代理 /api 到本服务。
if config.WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=str(config.WEB_DIST), html=True),
              name="web")
