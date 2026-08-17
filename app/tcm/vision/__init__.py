"""舌诊 / 面诊图像分析入口（多模态大模型视觉 + 严格形态学质量闸门双轨驱动）。

对外暴露 analyze_tongue(image) 与 analyze_face(image)，两者均接受
base64 图片（支持带 data:image/...;base64, 前缀），返回：

    {"code": 0, "quantified": {...}, "features": {...}, "clinical_notes": "...", ...}

code 约定
  0   成功（真实舌象/面象并通过量化）
  300 拍摄质量不合格（模糊/过暗/过曝等，reasons 给出原因）
  301 未检测到有效舌体/人脸（上传了病历单、文档、日常物品、风景等非目标图片）
  302 图片无法解码

设计理念：
1. 真实优先：配置 ANTHROPIC_API_KEY 时优先调用视觉大模型进行场景真实性鉴别与专业中医量化；
   绝不将病历单、化验单、日常物品等伪造成舌象！
2. 离线双保险：离线/无网络时，本地 OpenCV 质量闸门强化了文档/文本高频过滤与舌体形态学面积校验，
   防止局部红色印章/杂色被误当成舌头。
"""
from __future__ import annotations

import base64
import json
import re
from typing import Optional, Tuple

import cv2
import numpy as np

from ... import config
from .. import adapters
from .deep_engine import get_deep_engine
from .face import FaceQuantizer
from .tongue import TongueQuantizer, quality_gate as tongue_quality_gate

_tongue_q = TongueQuantizer()
_face_q = FaceQuantizer()
_deep_engine = get_deep_engine()


def b64_to_rgb(b64str: str) -> np.ndarray:
    if not b64str:
        raise ValueError("图片内容为空")
    if "," in b64str:
        b64str = b64str.split(",", 1)[1]
    raw = base64.b64decode(b64str)
    arr = np.frombuffer(raw, np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("无法解码图片，请换一张 jpg/png 重试")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _detect_document_like(rgb: np.ndarray) -> bool:
    """检测是否为纸质文档、病历单、化验单或高密度文字图片。"""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    if h < 50 or w < 50:
        return False
    
    # 纸质文档特征：大面积高亮/近白背景 + 高对比度黑色/深色文字
    bright_ratio = float((gray > 200).mean())
    dark_ratio = float((gray < 60).mean())
    
    # 边缘密度（文字会有大量密集短边缘）
    edges = cv2.Canny(gray, 80, 200)
    edge_density = float(edges.mean() / 255.0)
    
    # 如果背景大面积白（>45%）且有一定暗色文字（>3%）且边缘密集，极大概率是纸张/病历文档
    if bright_ratio > 0.45 and dark_ratio > 0.02 and edge_density > 0.035:
        return True
    return False


def _tongue_mask_cv(rgb: np.ndarray) -> Tuple[np.ndarray, bool]:
    """严格的 HSV 红色域舌体分割 + 形态学与几何紧凑度校验。"""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    # 舌质正常红色域 (包含淡红、红、绛红、暗红)
    m1 = cv2.inRange(hsv, np.array([0, 30, 40]), np.array([22, 255, 255]))
    m2 = cv2.inRange(hsv, np.array([160, 30, 40]), np.array([180, 255, 255]))
    mask_u8 = (m1 | m2)
    
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    mask_u8 = cv2.morphologyEx(mask_u8, cv2.MORPH_CLOSE, kernel)
    mask_u8 = cv2.morphologyEx(mask_u8, cv2.MORPH_OPEN, kernel)
    
    # 连通域分析：寻找位于画面中部的最大舌体区域
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask_u8, 8)
    if num_labels <= 1:
        return np.zeros_like(mask_u8, dtype=bool), False

    h, w = rgb.shape[:2]
    total_pixels = h * w
    cx_img, cy_img = w / 2.0, h / 2.0
    
    best_idx = -1
    best_score = -1.0
    
    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        # 面积必须占整图至少 3% 以上，且不超过 85%
        area_ratio = area / float(total_pixels)
        if area_ratio < 0.03 or area_ratio > 0.85:
            continue
        
        bw = stats[i, cv2.CC_STAT_WIDTH]
        bh = stats[i, cv2.CC_STAT_HEIGHT]
        aspect = bw / float(bh) if bh > 0 else 0
        if aspect < 0.4 or aspect > 2.5: # 排除细长线条/文字横条
            continue
            
        cx, cy = centroids[i]
        # 距离图像中心的偏移归一化（舌头通常在画面中中央）
        dist_center = np.sqrt(((cx - cx_img) / w) ** 2 + ((cy - cy_img) / h) ** 2)
        if dist_center > 0.45: # 偏离中心过远
            continue
            
        # 评分：面积大且靠近中心
        score = area_ratio * (1.0 - dist_center)
        if score > best_score:
            best_score = score
            best_idx = i
            
    if best_idx == -1:
        return np.zeros_like(mask_u8, dtype=bool), False
        
    final_mask = (labels == best_idx)
    return final_mask, True


# ---------------------------------------------------------------- 多模态 LLM 视觉引擎

_TONGUE_VISION_PROMPT = """你是一位专业的中医望诊与舌诊 AI 专家。请对用户上传的图像进行专业中医舌象视觉分析。
首先进行严格的【有效性与场景真实性校验】：
1. 判断当前图像是否为真实的人体舌部照片/舌象特写？
2. 如果用户上传的是：门诊病历单、体检化验单、纸质文档、风景、动物宠物、药物药盒、日常生活用品、纯文字图片等非舌头内容，你必须果断判定为无效！

请输出严格的 JSON 格式（不要包含任何 markdown 代码块外部的多余废话）：
若不是真实的舌部照片：
{
  "is_valid_tongue": false,
  "error_reason": "未检测到有效人体舌部（检测到您上传的是门诊病历/文档/其他图片）。请正对镜头自然伸出舌头，拍摄清晰的舌象特写照片。"
}

若是真实的舌部照片：
{
  "is_valid_tongue": true,
  "body_class": "淡红舌" | "淡白舌" | "红舌" | "绛舌" | "青紫舌",
  "coat_class": "白苔" | "黄苔" | "灰黑苔" | "少苔/无苔",
  "coat_thickness": 28.0, // 苔厚度数值 0.0-100.0 (薄苔15-35, 适中40-60, 厚苔70-95, 无苔0)
  "greasy_score": 20.0, // 腻度 0.0-100.0 (滑润清爽0-30, 稍腻35-60, 腐腻厚腻70-100)
  "dry_score": 15.0, // 燥度 0.0-100.0 (润泽0-25, 稍干30-55, 干燥无津60-100)
  "tooth_mark_grade": 0, // 齿痕等级 (0: 无齿痕, 1: 轻度, 2: 明显, 3: 重度)
  "crack_grade": 0, // 裂纹等级 (0: 无裂纹, 1: 浅裂纹, 2: 明显裂纹, 3: 深裂纹)
  "petechiae_count": 0, // 瘀点瘀斑数量 (0-20 整数)
  "moisture": 65.0, // 津液润泽度数值 0.0-100.0
  "red_index": 55.0, // 舌质红度 0.0-100.0
  "yellow_index": 12.0, // 苔色黄度 0.0-100.0
  "clinical_notes": "舌质淡红，苔薄白而润，舌体大小适中，无明显齿痕及裂纹，神气充沛。"
}
"""

_FACE_VISION_PROMPT = """你是一位专业的中医望诊与面诊 AI 专家。请对用户上传的面部图像进行中医望面色与局部特征视觉分析。
首先进行严格的【有效性与真实人脸校验】：
1. 判断当前图像是否为清晰的真实人体正面面部照片？
2. 如果用户上传的是文档、病历、局部杂物、风景、非人脸物体等，必须判定无效！

请输出严格 JSON 格式：
若非真实人脸：
{
  "is_valid_face": false,
  "error_reason": "未检测到有效的人体正面面部（检测到您上传的是病历单/其他图片）。请上传清晰、光线均匀的正面人脸照片。"
}

若是真实人脸：
{
  "is_valid_face": true,
  "complexion": "红润" | "面色萎黄" | "面色晦暗" | "面色苍白",
  "brightness": 70.0, // 面色明亮度 0.0-100.0
  "sallow_index": 15.0, // 萎黄指数 0.0-100.0
  "dull_index": 10.0, // 暗沉指数 0.0-100.0
  "lip_class": "淡红" | "淡白" | "深红" | "紫暗", // 唇色
  "eye_bag_grade": 0, // 眼袋等级 0-3
  "spot_grade": 0, // 色斑等级 0-3
  "clinical_notes": "面色红润有神，唇色淡红，目下无明显暗沉。"
}
"""


def _clean_json_str(text: str) -> str:
    """去除 LLM 回复中的 markdown 代码包裹。"""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t)
    return t.strip()


def _analyze_tongue_llm(b64_clean: str) -> Optional[dict]:
    """通过大模型多模态视觉进行舌象智能辨析。"""
    if config.MOCK_MODE or not config.ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(
            api_key=config.ANTHROPIC_API_KEY,
            base_url=config.ANTHROPIC_BASE_URL or None,
        )
        resp = client.messages.create(
            model=config.LLM_MODEL,
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": b64_clean,
                        }
                    },
                    {"type": "text", "text": _TONGUE_VISION_PROMPT}
                ]
            }]
        )
        raw_text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        data = json.loads(_clean_json_str(raw_text))
        return data
    except Exception:  # noqa: BLE001
        return None


def _analyze_face_llm(b64_clean: str) -> Optional[dict]:
    """通过大模型多模态视觉进行面象智能辨析。"""
    if config.MOCK_MODE or not config.ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(
            api_key=config.ANTHROPIC_API_KEY,
            base_url=config.ANTHROPIC_BASE_URL or None,
        )
        resp = client.messages.create(
            model=config.LLM_MODEL,
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": b64_clean,
                        }
                    },
                    {"type": "text", "text": _FACE_VISION_PROMPT}
                ]
            }]
        )
        raw_text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        data = json.loads(_clean_json_str(raw_text))
        return data
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- 对外接口

def analyze_tongue(image_b64: str) -> dict:
    try:
        rgb = b64_to_rgb(image_b64)
    except ValueError as exc:
        return {"code": 302, "error": str(exc)}

    # 提取纯 clean base64 数据
    clean_b64 = image_b64.split(",", 1)[1] if "," in image_b64 else image_b64

    # 1. 基础图像质量检查（模糊/极度过暗/过曝）
    gate = tongue_quality_gate(rgb)
    if not gate["pass"]:
        return {"code": 300, "quality_pass": False,
                "reasons": gate["reasons"], "quality_metrics": gate["metrics"]}

    # 2. 纸质文档/病历高频过滤（双重防线之一）
    if _detect_document_like(rgb):
        return {"code": 301, "quality_pass": True,
                "quality_metrics": gate["metrics"],
                "error": "未检测到有效舌象：系统识别到您上传的是纸质病历/文档，请上传真实的舌部正面特写照片。"}

    # 3. 视觉大模型深度辨识（优先链路）
    llm_res = _analyze_tongue_llm(clean_b64)
    if llm_res is not None:
        if not llm_res.get("is_valid_tongue"):
            return {
                "code": 301,
                "quality_pass": True,
                "quality_metrics": gate["metrics"],
                "error": llm_res.get("error_reason") or "未检测到有效舌体区域，请正对镜头充分伸出舌头后重拍",
            }

        # 大模型识别通过，构建规范的量化结构与引擎输入
        features = {
            "body_class": llm_res.get("body_class", "淡红舌"),
            "coat_class": llm_res.get("coat_class", "白苔"),
            "coat_thickness": float(llm_res.get("coat_thickness", 25.0)),
            "greasy_score": float(llm_res.get("greasy_score", 20.0)),
            "dry_score": float(llm_res.get("dry_score", 15.0)),
            "tooth_mark_grade": int(llm_res.get("tooth_mark_grade", 0)),
            "crack_grade": int(llm_res.get("crack_grade", 0)),
            "petechiae_count": int(llm_res.get("petechiae_count", 0)),
            "moisture": float(llm_res.get("moisture", 65.0)),
            "red_index": float(llm_res.get("red_index", 50.0)),
            "yellow_index": float(llm_res.get("yellow_index", 10.0)),
        }
        
        quantified = {
            "code": 0,
            "method": "vision_llm",
            "body_color": {"value": {"class": features["body_class"], "red_index": features["red_index"]}},
            "coat_yellow": {"value": {"class": features["coat_class"], "yellow_index": features["yellow_index"]}},
            "coat_thickness": {"value": features["coat_thickness"]},
            "greasy_dry": {"value": {"greasy_score": features["greasy_score"], "dry_score": features["dry_score"]}},
            "tooth_mark": {"value": {"grade": features["tooth_mark_grade"]}},
            "crack": {"value": {"grade": features["crack_grade"]}},
            "petechiae": {"value": features["petechiae_count"]},
            "moisture": {"value": features["moisture"]},
            "clinical_notes": llm_res.get("clinical_notes", ""),
        }

        return {
            "code": 0,
            "method": "vision_llm",
            "quality_pass": True,
            "quality_metrics": gate["metrics"],
            "quantified": quantified,
            "features": features,
            "clinical_notes": llm_res.get("clinical_notes", ""),
            "note": "由中医视觉大模型完成真实舌象解剖识别与四诊量化，已过真实性校验",
        }

    # 4. 离线/Fallback 本地 OpenCV 形态学分割与量化
    mask, valid = _tongue_mask_cv(rgb)
    if not valid or mask.sum() < 3000:
        return {"code": 301, "quality_pass": True,
                "quality_metrics": gate["metrics"],
                "error": "未检测到有效舌体区域，请正对镜头充分伸出舌头后重拍"}

    quantified = _tongue_q.analyze(rgb, mask)
    if quantified.get("code") not in (0, None):
        return {"code": quantified.get("code", 301),
                "error": quantified.get("error", "舌象量化失败"),
                "quality_metrics": gate["metrics"]}

    return {
        "code": 0,
        "method": "opencv_cv",
        "quality_pass": True,
        "quality_metrics": gate["metrics"],
        "quantified": quantified,
        "features": adapters.tongue_to_engine(quantified),
        "mask_ratio": round(float(mask.sum()) / mask.size, 4),
    }


def analyze_face(image_b64: str) -> dict:
    try:
        rgb = b64_to_rgb(image_b64)
    except ValueError as exc:
        return {"code": 302, "error": str(exc)}

    clean_b64 = image_b64.split(",", 1)[1] if "," in image_b64 else image_b64

    # 1. 纸质文档/病历高频过滤
    if _detect_document_like(rgb):
        return {"code": 301,
                "error": "未检测到有效人脸：系统识别到您上传的是纸质病历/文档，请上传正面面部照片。"}

    # 2. 视觉大模型深度辨识（优先链路）
    llm_res = _analyze_face_llm(clean_b64)
    if llm_res is not None:
        if not llm_res.get("is_valid_face"):
            return {
                "code": 301,
                "error": llm_res.get("error_reason") or "未检测到有效人脸，请上传清晰正面面部照片",
            }

        features = {
            "complexion": llm_res.get("complexion", "红润"),
            "brightness": float(llm_res.get("brightness", 70.0)),
            "sallow_index": float(llm_res.get("sallow_index", 15.0)),
            "dull_index": float(llm_res.get("dull_index", 10.0)),
            "lip_class": llm_res.get("lip_class", "淡红"),
            "eye_bag_grade": int(llm_res.get("eye_bag_grade", 0)),
            "spot_grade": int(llm_res.get("spot_grade", 0)),
        }

        quantified = {
            "code": 0,
            "method": "vision_llm",
            "complexion": features["complexion"],
            "brightness": {"value": features["brightness"]},
            "sallow_index": {"value": features["sallow_index"]},
            "dull_index": {"value": features["dull_index"]},
            "lip_color": {"value": {"class": features["lip_class"]}},
            "eye_bag": {"value": {"grade": features["eye_bag_grade"]}},
            "spot": {"value": {"grade": features["spot_grade"]}},
            "clinical_notes": llm_res.get("clinical_notes", ""),
        }

        return {
            "code": 0,
            "method": "vision_llm",
            "quantified": quantified,
            "features": features,
            "clinical_notes": llm_res.get("clinical_notes", ""),
            "note": "由中医视觉大模型完成真实人脸望诊与面色量化，已过真实性校验",
        }

    # 3. MediaPipe 478 关键点分析（若安装）
    try:
        import mediapipe as mp                       # noqa: PLC0415
        mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True, max_num_faces=1,
            refine_landmarks=True, min_detection_confidence=0.5)
        res = mesh.process(rgb)
        if res.multi_face_landmarks:
            h, w = rgb.shape[:2]
            landmarks = {i: (int(p.x * w), int(p.y * h))
                         for i, p in enumerate(res.multi_face_landmarks[0].landmark)}
            quantified = _face_q.analyze(rgb, landmarks)
            if quantified.get("code") in (0, None):
                return {"code": 0, "method": "mediapipe_478",
                        "quantified": quantified,
                        "features": adapters.face_to_engine(quantified)}
    except ImportError:
        pass
    except Exception:                                # noqa: BLE001
        pass

    # 4. 若大模型与 MediaPipe 均无法检出人脸，直接报错拦截，杜绝将非人脸图误判
    return {
        "code": 301,
        "error": "未检测到有效人脸轮廓，请确保正对镜头、光线充足并拍摄清晰的面部照片。",
    }
