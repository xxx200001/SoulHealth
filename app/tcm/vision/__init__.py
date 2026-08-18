"""舌诊 / 面诊图像分析入口。

对外只暴露 analyze_tongue(image) 与 analyze_face(image)，两者都接受
base64 图片（可带 data:image/...;base64, 前缀），返回：

    {"code": 0, "quantified": {...原始可审计结构...},
     "features": {...已扁平化、可直接喂辨证引擎...}, ...}

code 约定
  0   成功
  300 拍摄质量不合格（reasons 给出逐条原因，前端提示重拍）
  301 未检出有效舌体区域，或检出区域不像舌体（reasons 说明是拍错了还是没取好景）
  302 图片无法解码
  303 面诊未检出人脸

依赖 opencv 与 numpy；面诊在装有 mediapipe 时用 478 点关键点做分区量化，
未装则用 OpenCV 自带 Haar 级联先确认人脸存在，再只对两颊区域做颜色近似分析
（如实标注 method=color_fallback、needs_confirmation=True）。
"""
from __future__ import annotations

import base64
from typing import Optional

import cv2
import numpy as np

from .. import adapters
from . import presence
from .face import FaceQuantizer
from .tongue import TongueQuantizer, quality_gate as tongue_quality_gate

_tongue_q = TongueQuantizer()
_face_q = FaceQuantizer()
_face_cascades: Optional[list] = None


def _detect_face_box(rgb: np.ndarray) -> Optional[tuple]:
    """用 OpenCV 自带 Haar 级联找最大的一张正脸，找不到返回 None。

    这不是为了做人脸识别，只是回答"画面里到底有没有脸"——没有就不该
    输出任何面色结论。级联文件随 opencv-python 分发，无需联网或额外权重。

    依次试 default 与 alt2 两套级联、minNeighbors 取 3：宁可对"疑似人脸"
    放行（后续本来就标了 needs_confirmation 要人工确认），也不要把用户
    正常的正脸照判成"没有脸"逼他反复重拍。真正要拦的是病历、墙面、
    桌面这类画面里根本没有脸的图。
    """
    global _face_cascades
    if _face_cascades is None:
        _face_cascades = []
        for xml in ("haarcascade_frontalface_default.xml",
                    "haarcascade_frontalface_alt2.xml"):
            c = cv2.CascadeClassifier(cv2.data.haarcascades + xml)
            if not c.empty():
                _face_cascades.append(c)
    if not _face_cascades:
        return None

    gray = cv2.equalizeHist(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY))
    short_side = min(rgb.shape[:2])
    min_size = max(60, int(short_side * 0.12))
    for cascade in _face_cascades:
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=3,
                                         minSize=(min_size, min_size))
        if len(faces):
            return tuple(int(v) for v in max(faces, key=lambda f: f[2] * f[3]))
    return None


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


def _tongue_mask(rgb: np.ndarray) -> np.ndarray:
    """兼容旧调用：转发到 presence.segment（Lab a* 相对阈值 + 最大连通域）。

    原实现是固定 HSV 红色域阈值，会把泛黄纸张、木色桌面、暖光背景整片
    当成舌体，详见 presence.py 开头的说明。
    """
    return presence.segment(rgb)


def analyze_tongue(image_b64: str, external_mask: Optional[np.ndarray] = None) -> dict:
    """舌象量化。

    三道闸依次过：能否解码 → 拍摄质量 → **舌体是否真的存在**。
    第三道是本次补上的：此前只判「红色像素够不够 500 个」，导致任何暖色调
    照片（实测一张门诊病历照）都能量化出一整套舌象数值并入档。

    external_mask：有 SAM / U-Net 等分割模型时把 mask 传进来，跳过启发式分割。
    """
    try:
        rgb = b64_to_rgb(image_b64)
    except ValueError as exc:
        return {"code": 302, "error": str(exc)}

    gate = tongue_quality_gate(rgb)
    if not gate["pass"]:
        return {"code": 300, "quality_pass": False,
                "reasons": gate["reasons"], "quality_metrics": gate["metrics"]}

    mask = presence.segment(rgb, external_mask)
    pres = presence.presence_gate(rgb, mask)
    if not pres["pass"]:
        return {"code": 301, "quality_pass": True,
                "quality_metrics": gate["metrics"],
                "presence_metrics": pres["metrics"],
                "reasons": pres["reasons"],
                "error": pres["reasons"][0]}

    quantified = _tongue_q.analyze(rgb, mask)
    if quantified.get("code") not in (0, None):
        return {"code": quantified.get("code", 301),
                "error": quantified.get("error", "舌象量化失败"),
                "quality_metrics": gate["metrics"]}

    return {
        "code": 0,
        "quality_pass": True,
        "quality_metrics": gate["metrics"],
        "presence_metrics": pres["metrics"],
        # 置信度低于 0.7 时前端要求人工确认后才入档，不自动写进档案
        "confidence": pres["confidence"],
        "needs_confirmation": pres["confidence"] < 0.7,
        "segmentation_method": "external_mask" if external_mask is not None
                               else "lab_a_otsu_heuristic",
        "quantified": quantified,
        "features": adapters.tongue_to_engine(quantified),
        "mask_ratio": round(float(mask.sum()) / mask.size, 4),
    }


def analyze_face(image_b64: str) -> dict:
    try:
        rgb = b64_to_rgb(image_b64)
    except ValueError as exc:
        return {"code": 302, "error": str(exc)}

    try:
        import mediapipe as mp                       # noqa: PLC0415 — 可选依赖
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
    except Exception:                                # noqa: BLE001 — 关键点失败即降级
        pass

    # ---- 兜底：先确认画面里真有人脸，再只在人脸区域内做颜色分析 ----
    # 原实现无条件对整幅图求 Lab 均值就给出"面色红润/萎黄"，一张病历照片
    # 也能得到"面色红润、萎黄指数 15.1"并喂进辨证引擎。两个问题都要修：
    # 没有人脸就不该出结论；有人脸也不该把背景和衣服一起平均进去。
    box = _detect_face_box(rgb)
    if box is None:
        return {"code": 303,
                "error": "未在画面中检出人脸，请正对镜头、光线充足后重拍；"
                         "若只想做舌诊，可跳过面诊。",
                "method": "haar_frontalface"}

    x, y, w, h = box
    # 取人脸中部横条（两颊 + 鼻梁），避开发际、眉眼与下巴阴影
    cheek = rgb[y + int(0.35 * h): y + int(0.72 * h),
                x + int(0.10 * w): x + int(0.90 * w)]
    lab = cv2.cvtColor(cheek, cv2.COLOR_RGB2LAB).astype(np.float32)
    L_mean = float(lab[..., 0].mean())
    a_mean = float(lab[..., 1].mean())
    b_mean = float(lab[..., 2].mean())
    brightness = round(L_mean / 255 * 100, 1)
    sallow = round(max(0.0, min(100.0,
                                ((b_mean - 128) - 0.6 * (a_mean - 128)) / 30 * 100)), 1)
    # 面色分档只在命中明确判据时下结论。原实现的 else 分支把所有"哪条都
    # 没命中"的情况一律判成"面色苍白"——一张亮度 72.9、萎黄 35 的脸会被
    # 判成苍白。苍白本应由低红度判定，而这个阈值并未标定，与其硬安一个
    # 结论，不如如实说没测到明显偏色。complexion 仅用于展示，辨证引擎读的
    # 是 sallow_index / dull_index 两个数值，故不影响证型判定。
    if brightness > 60 and sallow < 20:
        complexion, basis = "红润", "亮度 > 60 且萎黄值 < 20"
    elif sallow > 40:
        complexion, basis = "面色萎黄", "萎黄值 > 40"
    elif brightness < 40:
        complexion, basis = "面色晦暗", "亮度 < 40"
    else:
        complexion, basis = "未见明显偏色", "各项指标均未达判定阈值"
    quantified = {"code": 0, "method": "color_fallback",
                  "brightness": brightness, "sallow_index": sallow,
                  "complexion": complexion, "complexion_basis": basis,
                  "face_box": [int(v) for v in box],
                  "lab": {"L": round(L_mean, 1), "a": round(a_mean, 1),
                          "b": round(b_mean, 1)}}
    return {"code": 0, "method": "color_fallback",
            "confidence": 0.5,
            "needs_confirmation": True,
            "note": "未安装 mediapipe，本次仅对检出的人脸两颊区域做颜色近似分析，"
                    "精度有限、结果需人工确认；安装 mediapipe 后可获得唇色、"
                    "眼袋、色斑的分区量化",
            "quantified": quantified,
            "features": adapters.face_to_engine(quantified)}
