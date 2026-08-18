"""分析：/api/analysis/*。

单一入口 POST /api/analysis/run —— 内部同时跑中医辨证链与现代医学链，
合成一份分析记录与一套报告。原来的 /api/v1/full_report 与 /api/analyze
两个入口已合并，前端不再需要"生成调理方案"和"开始智能分析"两个按钮。
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from ..agent import orchestrator
from ..archive import repository as repo
from ..deps import current_user, scoped_patient
from ..reportgen.generator import TITLES

router = APIRouter(prefix="/analysis", tags=["分析"])


@router.post("/run", summary="运行完整分析（中医辨证链 + 现代医学链）")
def run(payload: dict = Body(...), user: dict = Depends(current_user)) -> dict:
    pid = payload.get("patient_id")
    if not pid:
        raise HTTPException(400, "缺少 patient_id")
    scoped_patient(pid, user)
    status = repo.collection_status(pid)
    if not status["ready_for_analysis"]:
        missing = []
        if not status["profile"]:
            missing.append("基础信息（年龄/身高/体重）")
        if not status["inquiry"]:
            missing.append("症状问诊")
        raise HTTPException(400, "采集尚未完成，还缺：" + "、".join(missing))
    try:
        return orchestrator.run_analysis(pid)
    except Exception as exc:                        # noqa: BLE001
        raise HTTPException(500, f"分析失败：{exc}")


@router.get("/patient/{pid}", summary="历次分析列表")
def list_analyses(pid: str, user: dict = Depends(current_user)) -> dict:
    scoped_patient(pid, user)
    return {"patient_id": pid, "analyses": repo.list_analyses(pid)}


@router.get("/{aid}", summary="单次分析详情（可回放）")
def detail(aid: str, user: dict = Depends(current_user)) -> dict:
    a = repo.get_analysis(aid)
    if a is None:
        raise HTTPException(404, f"分析不存在: {aid}")
    scoped_patient(a["patient_id"], user)
    reports = [
        {"report_id": r["id"], "report_type": r["report_type"],
         "title": TITLES.get(r["report_type"], r["report_type"]),
         "format": r["format"], "path": r["path"],
         "download_url": f"/api/reports/{r['id']}/download"}
        for r in repo.list_reports(a["patient_id"], analysis_id=aid)
    ]
    return {"analysis_id": a["id"], "patient_id": a["patient_id"],
            "created_at": a["created_at"], "status": a["status"],
            "risk_tags": a["risk_tags"] or [],
            "mechanism_chain": a["mechanism_chain"] or {},
            "biocompute_plan": a["biocompute"] or [],
            "formula": a["formula"], "syndrome_tags": a["syndrome_tags"] or [],
            "interpretation": a["interpretation"],
            "tcm": a.get("tcm"),
            "trace": a["trace"] or [], "reports": reports}
