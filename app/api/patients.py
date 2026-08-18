"""健康档案：/api/patients/*。

档案是全系统唯一的数据主体——基础信息、化验指标、影像所见、诊断提示、
症状备注、舌面诊、问诊作答、历次分析、报告，全部挂在同一个 patient_id 下。
原版"前端 localStorage 存一份 + 服务端存另一份"的双轨已取消。
"""
from __future__ import annotations

import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from ..archive import repository as repo
from ..deps import current_user, scoped_patient
from .. import demo

router = APIRouter(prefix="/patients", tags=["健康档案"])


@router.get("", summary="档案列表 / 检索")
def list_patients(query: Optional[str] = None,
                  user: dict = Depends(current_user)) -> dict:
    owner = None if user["role"] == "admin" else user["id"]
    return {"patients": repo.list_patients(query, owner_id=owner)}


@router.post("", summary="建立 / 找回档案")
def create_or_find(payload: dict = Body(default={}),
                   user: dict = Depends(current_user)) -> dict:
    """身份匹配唯一依据：姓名 + 身份证后四位精确匹配；
    未提供后四位则始终新建（不做模糊猜测）。档案归属当前登录用户。"""
    pid, created = repo.find_or_create_patient(
        name=payload.get("name"), sex=payload.get("sex"),
        age_years=payload.get("age_years"),
        height_cm=payload.get("height_cm"), weight_kg=payload.get("weight_kg"),
        id_last4=payload.get("id_last4"), owner_id=user["id"])
    return {"patient_id": pid, "created": created, "patient": repo.get_patient(pid)}


@router.post("/demo", summary="载入演示患者（建档并种入双链演示数据）")
def load_demo(user: dict = Depends(current_user)) -> dict:
    """一键得到可直接分析的演示档案：现代链（化验/所见/提示或演示图片摄取）
    与中医链（舌象/面象/问诊）的数据一次种齐。幂等——重复点按找回同一份
    档案、只补缺项。种子逻辑在 app/demo.py，与 run_demo.py 共用。"""
    return demo.seed(owner_id=user["id"])


@router.get("/{pid}", summary="档案快照（含四诊与指标时间序列）")
def snapshot(pid: str, user: dict = Depends(current_user)) -> dict:
    scoped_patient(pid, user)
    snap = repo.snapshot(pid)
    snap["collection_status"] = repo.collection_status(pid)
    return snap


@router.patch("/{pid}", summary="更新基础信息、过敏源与在服西药")
def update(pid: str, payload: dict = Body(...),
           user: dict = Depends(current_user)) -> dict:
    scoped_patient(pid, user)
    payload.pop("owner_id", None)      # 归属只能由管理员操作变更，不接受客户端直传
    try:
        repo.update_patient(pid, **payload)
    except KeyError:
        raise HTTPException(404, f"档案不存在: {pid}")
    return {"patient": repo.get_patient(pid)}


@router.delete("/{pid}", summary="删除档案（级联）")
def delete(pid: str, user: dict = Depends(current_user)) -> dict:
    scoped_patient(pid, user)
    repo.delete_patient(pid)
    return {"deleted": pid}


@router.get("/{pid}/timeline", summary="指标时间序列")
def timeline(pid: str, code: Optional[str] = None,
             user: dict = Depends(current_user)) -> dict:
    scoped_patient(pid, user)
    return {"patient_id": pid, "code": code, "series": repo.get_timeline(pid, code)}


@router.post("/{pid}/notes", summary="添加症状/主诉备注")
def add_note(pid: str, payload: dict = Body(...),
             user: dict = Depends(current_user)) -> dict:
    scoped_patient(pid, user)
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "备注内容不能为空")
    nid = repo.add_note(pid, text)
    return {"note_id": nid, "notes": repo.list_notes(pid)}


def _auto_flag(value_num, ref_low, ref_high) -> Optional[str]:
    if value_num is None:
        return None
    if ref_high is not None and value_num > ref_high:
        return "H"
    if ref_low is not None and value_num < ref_low:
        return "L"
    if ref_low is not None or ref_high is not None:
        return "N"
    return None


@router.post("/{pid}/observations", summary="录入化验指标（手动或批量）")
def add_observations(pid: str, payload: dict = Body(...),
                     user: dict = Depends(current_user)) -> dict:
    """单条：{code, display, value_num, unit, ref_low, ref_high, observed_at}
    批量：{items: [ ...同上... ]} —— 体检单一次录入多项时用批量，少发多次请求。"""
    scoped_patient(pid, user)
    items = payload.get("items")
    if items is None:
        items = [payload]
    if not isinstance(items, list) or not items:
        raise HTTPException(400, "没有可录入的指标")

    saved, errors = [], []
    for raw in items:
        code = (raw.get("code") or "").strip().upper()
        if not code:
            errors.append(f"缺少指标代码：{raw}")
            continue
        value_num = raw.get("value_num")
        ref_low, ref_high = raw.get("ref_low"), raw.get("ref_high")
        flag = raw.get("abnormal_flag") or _auto_flag(value_num, ref_low, ref_high)
        oid = repo.add_observation(
            pid, code=code, display=raw.get("display"), value_num=value_num,
            value_text=raw.get("value_text"), unit=raw.get("unit"),
            ref_low=ref_low, ref_high=ref_high, abnormal_flag=flag,
            observed_at=raw.get("observed_at") or datetime.date.today().isoformat())
        saved.append({"observation_id": oid, "code": code, "abnormal_flag": flag})
    return {"saved": saved, "errors": errors,
            "collection_status": repo.collection_status(pid)}


@router.post("/{pid}/findings", summary="录入影像/查体所见")
def add_finding(pid: str, payload: dict = Body(...),
                user: dict = Depends(current_user)) -> dict:
    scoped_patient(pid, user)
    organ = (payload.get("organ") or "").strip()
    description = (payload.get("description") or "").strip()
    if not organ or not description:
        raise HTTPException(400, "脏器与所见描述均不能为空")
    flags = payload.get("flags") or []
    if isinstance(flags, str):
        flags = [f.strip() for f in flags.split("、") if f.strip()]
    fid = repo.add_manual_finding(pid, organ, description, flags,
                                  observed_at=payload.get("observed_at"))
    return {"finding_id": fid}


@router.post("/{pid}/impressions", summary="录入诊断提示 / 超声印象")
def add_impression(pid: str, payload: dict = Body(...),
                   user: dict = Depends(current_user)) -> dict:
    scoped_patient(pid, user)
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "诊断提示内容不能为空")
    iid = repo.add_manual_impression(pid, text,
                                     observed_at=payload.get("observed_at"))
    return {"impression_id": iid}
