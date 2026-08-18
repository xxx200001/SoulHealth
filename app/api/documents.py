"""资料上传与视觉抽取：/api/documents/*。

化验单 / 超声报告 / 病历图片上传后由视觉模型抽取结构化数据并入档，
是化验指标的第二个入口（第一个是 /api/patients/{pid}/observations 手动录入）。
两者写同一张 observations 表，不会产生两份互不相干的指标。
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from fastapi import (APIRouter, Depends, File, Form, HTTPException, UploadFile)

from .. import config
from ..archive import repository as repo
from ..deps import current_user, scoped_patient
from ..ingest.pipeline import ingest_document
from ..ingest.vision_llm import ExtractionError, vision_selftest

router = APIRouter(tags=["资料上传"])

_ALLOWED_SUFFIX = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}


@router.post("/documents/upload", summary="上传报告图片并抽取入档")
async def upload_document(
    file: UploadFile = File(...),
    patient_id: str = Form(...),
    doc_type_hint: Optional[str] = Form(default=None),
    engine: Optional[str] = Form(default=None),
    user: dict = Depends(current_user),
) -> dict:
    scoped_patient(patient_id, user)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_SUFFIX:
        raise HTTPException(400, f"暂不支持的文件类型 {suffix}，"
                                 f"支持：{sorted(_ALLOWED_SUFFIX)}")
    stored = config.UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    stored.write_bytes(await file.read())
    try:
        result = ingest_document(patient_id, stored, doc_type_hint, engine,
                                 source_filename=file.filename)
    except ExtractionError as exc:
        # 未配置密钥 / 模型没收到图像：明确指引，绝不返回编造的指标
        raise HTTPException(422, str(exc))
    except Exception as exc:                        # noqa: BLE001
        raise HTTPException(500, f"抽取失败：{exc}")
    result["collection_status"] = repo.collection_status(patient_id)
    return result


@router.get("/documents/{doc_id}", summary="单份资料的抽取结果")
def get_document(doc_id: str, user: dict = Depends(current_user)) -> dict:
    doc = repo.get_document(doc_id)
    if doc is None:
        raise HTTPException(404, f"资料不存在: {doc_id}")
    scoped_patient(doc["patient_id"], user)
    return doc


@router.get("/selftest/vision", summary="视觉链路自检")
def selftest_vision(_: dict = Depends(current_user)) -> dict:
    """发一张已知颜色的探测图，确认所配模型确实能收到图像。
    上传报告图片报「模型没收到图像」时先跑这个。"""
    return vision_selftest()
