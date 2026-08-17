"""健康问答：/api/qa/*。

基于当前档案的真实数据作答（含历次分析趋势与四诊结论）。
未配置模型密钥时明确拒答并给出配置指引，不用规则模板冒充 AI 回答。
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from ..agent import qa as qa_agent
from ..deps import current_user, scoped_patient

router = APIRouter(prefix="/qa", tags=["健康问答"])


@router.post("/{pid}", summary="就当前档案提问")
def ask(pid: str, payload: dict = Body(...),
        user: dict = Depends(current_user)) -> dict:
    scoped_patient(pid, user)
    try:
        return qa_agent.ask(pid, payload.get("question") or "")
    except qa_agent.QAUnavailable as exc:
        raise HTTPException(422, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:                        # noqa: BLE001
        raise HTTPException(502, f"问答失败：{exc}")
