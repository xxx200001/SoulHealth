"""中医四诊采集：/api/tcm/*。

三个采集入口，结果一律写入统一档案（tcm_exams / tcm_inquiries），
分析时自动取最近一次，不需要用户在分析前再填一遍。

  POST /api/tcm/{pid}/tongue      舌诊：base64 图片 → 质量闸 → 量化 → 入档
  POST /api/tcm/{pid}/face        面诊：同上
  GET  /api/tcm/questionnaire     问诊量表（按性别裁剪）
  POST /api/tcm/{pid}/inquiry     问诊作答 → 归一化为辨证打分 → 入档

原 /api/v1/ocr_lab 已移除：它内嵌了一个硬编码的 API Key，且识别失败时
返回一组固定的伪造化验值（ALT 68 / 甘油三酯 2.8 / 血红蛋白 95）当兜底。
医疗场景不能这么做。化验单识别统一走 /api/documents/upload 的视觉抽取，
未配置密钥时明确报错并给出配置指引，绝不给假数据。
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from .. import config
from ..archive import repository as repo
from ..deps import current_user, scoped_patient
from ..tcm import adapters
from ..tcm.consultation import ConsultationEngine
from ..tcm.vision import analyze_face, analyze_tongue, b64_to_rgb

router = APIRouter(prefix="/tcm", tags=["中医四诊"])
_consult = ConsultationEngine()


def _save_image(image_b64: str, prefix: str) -> Optional[str]:
    """把采集到的图片落盘，便于复核与复诊对比；失败不影响主流程。"""
    try:
        import cv2
        rgb = b64_to_rgb(image_b64)
        path = config.UPLOAD_DIR / f"{prefix}_{uuid.uuid4().hex}.jpg"
        cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        return str(path)
    except Exception:                               # noqa: BLE001
        return None


@router.get("/questionnaire", summary="问诊量表")
def questionnaire(sex: str = "M") -> dict:
    """量表由后端下发（含分类题选项到辨证键的映射），
    避免前端与辨证引擎各维护一份题库而对不上。"""
    return _consult.get_questionnaire(sex)


@router.get("/indicators", summary="可录入的体检指标目录")
def indicators() -> dict:
    """指标目录由后端下发，前端不再维护第二份硬编码清单——
    否则新增指标要改两处，且随时可能与解析器的别名表对不上。"""
    from ..tcm.lab_mapper import INDICATOR_CATALOG
    groups: dict = {}
    for code, spec in INDICATOR_CATALOG.items():
        cat = spec.get("category") or "其他"
        ref_low, ref_high = spec.get("ref", (None, None))
        groups.setdefault(cat, []).append({
            "code": code.upper(),
            "name": (spec.get("aliases") or [code])[0],
            "aliases": spec.get("aliases") or [],
            "unit": spec.get("unit"),
            "ref_low": ref_low, "ref_high": ref_high,
        })
    return {"groups": [{"group": g, "items": items} for g, items in groups.items()]}


@router.post("/{pid}/tongue", summary="舌诊拍摄分析并入档")
def tongue(pid: str, payload: dict = Body(...),
           user: dict = Depends(current_user)) -> dict:
    scoped_patient(pid, user)
    image = payload.get("image") or ""
    if not image:
        raise HTTPException(400, "缺少图片内容")
    result = analyze_tongue(image)
    if result.get("code") != 0:
        return result                                # 质量不合格等，交前端提示重拍
    # 分割置信度低时先不入档：这些数值会进辨证加权并影响组方，
    # 与其悄悄写进档案，不如让用户看过量化结果后确认一次。
    if result.get("needs_confirmation") and not payload.get("confirmed"):
        return {**result, "archived": False,
                "hint": "本次舌体识别置信度偏低，请核对下方量化结果；"
                        "确认无误后再入档，或重拍一张更清晰的舌象。"}
    image_path = _save_image(image, "tongue") if payload.get("keep_image", True) else None
    exam_id = repo.save_tcm_exam(pid, "tongue", result["features"],
                                 quantified=result.get("quantified"),
                                 quality=result.get("quality_metrics"),
                                 image_path=image_path)
    return {**result, "archived": True, "exam_id": exam_id,
            "collection_status": repo.collection_status(pid)}


@router.post("/{pid}/face", summary="面诊拍摄分析并入档")
def face(pid: str, payload: dict = Body(...),
         user: dict = Depends(current_user)) -> dict:
    scoped_patient(pid, user)
    image = payload.get("image") or ""
    if not image:
        raise HTTPException(400, "缺少图片内容")
    result = analyze_face(image)
    if result.get("code") != 0:
        return result
    if result.get("needs_confirmation") and not payload.get("confirmed"):
        return {**result, "archived": False,
                "hint": "未安装 mediapipe，本次为人脸区域颜色近似分析，精度有限；"
                        "请核对结果后再确认入档。"}
    image_path = _save_image(image, "face") if payload.get("keep_image", True) else None
    exam_id = repo.save_tcm_exam(pid, "face", result["features"],
                                 quantified=result.get("quantified"),
                                 image_path=image_path)
    return {**result, "archived": True, "exam_id": exam_id,
            "collection_status": repo.collection_status(pid)}


@router.post("/{pid}/inquiry", summary="提交问诊作答")
def inquiry(pid: str, payload: dict = Body(...),
            user: dict = Depends(current_user)) -> dict:
    """answers 为原始作答（分类题给选项 value）；服务端负责归一化成
    辨证引擎认识的 0–10 分打分（如「干结便秘」→ 便秘 9）。"""
    scoped_patient(pid, user)
    answers = payload.get("answers") or {}
    if not answers:
        raise HTTPException(400, "问诊作答为空")
    symptoms = adapters.symptoms_to_engine(answers)
    inquiry_id = repo.save_tcm_inquiry(
        pid, answers, symptoms,
        drugs=payload.get("drugs") or [],
        allergies=payload.get("allergies") or [])
    # 在服西药与过敏源同时落到档案主表，组方安全闸直接读档案
    updates = {}
    if payload.get("drugs") is not None:
        updates["drugs"] = payload["drugs"]
    if payload.get("allergies") is not None:
        updates["allergies"] = payload["allergies"]
    if updates:
        repo.update_patient(pid, **updates)
    return {"inquiry_id": inquiry_id, "symptoms": symptoms,
            "collection_status": repo.collection_status(pid)}


@router.get("/{pid}/exams", summary="四诊留档记录")
def exams(pid: str, exam_type: Optional[str] = None,
          user: dict = Depends(current_user)) -> dict:
    scoped_patient(pid, user)
    return {"exams": repo.list_exams(pid, exam_type),
            "inquiries": repo.list_inquiries(pid)}


@router.delete("/{pid}/exams/{exam_id}", summary="删除一次四诊留档")
def delete_exam(pid: str, exam_id: str,
                user: dict = Depends(current_user)) -> dict:
    scoped_patient(pid, user)
    if not repo.delete_exam(pid, exam_id):
        raise HTTPException(404, "记录不存在")
    return {"deleted": exam_id,
            "collection_status": repo.collection_status(pid)}
