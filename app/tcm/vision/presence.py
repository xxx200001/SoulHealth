"""舌体分割与存在性门禁。

为什么单独一个文件
------------------
原实现把"分割"做成一句固定 HSV 红色域阈值（色相 0–25 / 160–180，S≥40），
再只判 `mask.sum() >= 500` 就交给量化器出数。这个组合有个要命的后果：
**任何暖色调图片都会被当成舌头量化出一整套数值**。实测一张泛黄纸张上的
门诊病历照片，14% 像素落进红色域，量化器照样输出"红舌 / 白苔 / 苔厚度 92.1 /
燥度 70.0 / 齿痕 1 级"并入档，而该区域的 Lab a* 均值是 128.4——中性灰，
一点红都没有。这些数字随后进入辨证加权，直接影响证型与组方。

所以分割之后必须再问一句"这到底是不是舌头"，答不上来就退回重拍，
不能出数。本模块负责这一步。

判据（全部为可解释的几何与色度量，无需模型权重）
------------------------------------------------
  redness    候选区 Lab a* 均值——舌头是真的红，纸张、墙面、桌面不是
  fill       候选区占画面比例——过大说明没把舌体从背景里分出来
  dominance  最大连通域 / 全部候选像素——舌头是一整块，不是散点
  solidity   面积 / 凸包面积——舌体接近凸形，散乱文字区不是
  aspect     宽高比——舌头有固定的长圆形态
  edges      区域内 Canny 边缘密度——印刷文字会显著偏高
  borders    触及画面边缘的条数——四边都触到通常是背景而非舌体

阈值全部集中在 GATE，标注 needs_clinical_calibration=True：
这是启发式判据，上线前应当用标注舌象集重新标定，或直接换成
分割模型（见 segment 的 external_mask 入口）。
"""
from __future__ import annotations

from typing import Optional, Tuple

import cv2
import numpy as np

VERSION = "1.0.0-presence-gate"

GATE = {
    "min_redness_a": 137.0,     # a* 均值下限（OpenCV Lab 中 128 为中性）
    "warn_redness_a": 141.0,    # 低于此值判为低置信度
    "min_fill": 0.04,           # 舌体至少占画面 4%
    "max_fill": 0.85,           # 超过 85% 视为未能与背景分离
    "min_dominance": 0.55,      # 最大连通域须占候选像素过半
    "min_solidity": 0.78,       # 舌体近凸形
    "aspect_range": (0.40, 2.40),
    "max_edge_density": 0.075,  # 区域内边缘密度上限（印刷文字远超此值）
    "min_texture_std": 2.0,     # 区域内 L 标准差下限：纯色填充块不是照片
    "max_border_sides": 2,      # 触边不超过两条
    "min_pixels": 1500,
}


def _largest_component(mask: np.ndarray) -> Tuple[np.ndarray, int]:
    m8 = mask.astype(np.uint8)
    n, lbl, stats, _ = cv2.connectedComponentsWithStats(m8, 8)
    if n <= 1:
        return np.zeros_like(mask, dtype=bool), 0
    idx = 1 + int(np.argmax(stats[1:, 4]))
    return (lbl == idx), int(stats[idx, 4])


def segment(rgb: np.ndarray, external_mask: Optional[np.ndarray] = None) -> np.ndarray:
    """分割舌体候选区。

    external_mask 非空时直接采用（接 SAM / U-Net 等真实分割模型的入口，
    有模型就别用下面的启发式）。

    启发式路径改用 Lab a*（红度）做 Otsu 双峰切分，而不是固定 HSV 红域：
    舌头是画面中最红的那块，用相对阈值比用绝对色相区间稳——后者会把
    泛黄纸张、木色桌面、暖光墙面整片收进来。
    """
    if external_mask is not None:
        return external_mask.astype(bool)

    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    a = lab[..., 1]
    # Otsu 找"比画面整体更红"的一侧
    thr, _ = cv2.threshold(a, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # 至少要比中性红一点，避免整幅中性图被从中间劈开
    thr = max(float(thr), 132.0)
    mask = a > thr

    # 同时要求有基本饱和度与亮度，滤掉暗角与高光死白
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    mask &= (hsv[..., 1] > 35) & (hsv[..., 2] > 45) & (hsv[..., 2] < 250)

    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    m8 = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, k)
    m8 = cv2.morphologyEx(m8, cv2.MORPH_OPEN, k)
    big, _ = _largest_component(m8.astype(bool))
    # 填掉舌面高光/裂纹造成的内部空洞，保持舌体为实心块
    filled = big.astype(np.uint8)
    cnts, _ = cv2.findContours(filled, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if cnts:
        cv2.drawContours(filled, cnts, -1, 1, thickness=cv2.FILLED)
    return filled.astype(bool)


def presence_gate(rgb: np.ndarray, mask: np.ndarray) -> dict:
    """判断 mask 圈出的是不是一条舌头。

    返回 {"pass", "confidence", "reasons", "metrics"}。
    pass=False 时调用方必须退回重拍，不得出量化数值。
    """
    H, W = mask.shape
    total = float(H * W)


    if mask.sum() < GATE["min_pixels"]:
        return {"pass": False, "confidence": 0.0, "verdict": "not_tongue",
                "reasons": ["画面中没有舌体特有的红色区域（可能拍到的是纸张、"
                            "桌面或其他物体），请正对镜头充分伸出舌头后重拍"],
                "metrics": {"pixels": int(mask.sum())}}

    big, area = _largest_component(mask)
    dominance = area / float(mask.sum())
    fill = area / total

    cnts, _ = cv2.findContours(big.astype(np.uint8), cv2.RETR_EXTERNAL,
                               cv2.CHAIN_APPROX_SIMPLE)
    c = max(cnts, key=cv2.contourArea)
    hull_area = cv2.contourArea(cv2.convexHull(c))
    solidity = area / hull_area if hull_area > 0 else 0.0
    x, y, w, h = cv2.boundingRect(c)
    aspect = w / float(h) if h else 0.0

    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    redness = float(lab[..., 1][big].mean())
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    saturation = float(hsv[..., 1][big].mean())

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edge_density = float((cv2.Canny(gray, 60, 160) > 0)[big].mean())
    texture_std = float(lab[..., 0][big].std())

    borders = int(big[0, :].any()) + int(big[-1, :].any()) \
        + int(big[:, 0].any()) + int(big[:, -1].any())

    metrics = {
        "redness_a": round(redness, 1), "saturation": round(saturation, 1),
        "fill_ratio": round(fill, 3), "dominance": round(dominance, 2),
        "solidity": round(solidity, 2), "aspect": round(aspect, 2),
        "edge_density": round(edge_density, 4), "border_sides": borders,
        "texture_std": round(texture_std, 2),
    }

    # ---- 判据分两层：先答"是不是舌象"，再答"取景对不对"。
    # 顺序决定前端首行提示，把"拍错了东西"排在"拍得不够好"前面，
    # 否则用户拍了张病历只会看到"靠近一些重拍"，照做一次还是错。
    not_tongue: list[str] = []
    framing: list[str] = []

    if redness < GATE["min_redness_a"]:
        not_tongue.append("画面中没有舌体特有的红色区域（可能拍到的是纸张、"
                          "桌面或其他物体），请对着镜头拍摄舌头")
    if edge_density > GATE["max_edge_density"]:
        not_tongue.append("画面内含大量文字或细密纹理，不像舌象照片，"
                          "请确认拍的是舌头")
    if texture_std < GATE["min_texture_std"]:
        not_tongue.append("画面为纯色块、没有舌面应有的质地变化，"
                          "请拍摄真实舌象而非图片或色卡")
    if solidity < GATE["min_solidity"]:
        not_tongue.append("检出区域形状不像舌体，请正对镜头、舌面完整入镜")
    if not (GATE["aspect_range"][0] <= aspect <= GATE["aspect_range"][1]):
        not_tongue.append("检出区域比例不像舌体，请正对镜头拍摄完整舌面")

    if fill > GATE["max_fill"]:
        framing.append("未能把舌体从背景中分出来，请让舌头充满画面中央、"
                       "背景尽量简单")
    if fill < GATE["min_fill"]:
        framing.append("舌体在画面中过小，请靠近一些重拍")
    if dominance < GATE["min_dominance"]:
        framing.append("检出的红色区域零散不成整块，请正对镜头充分伸出舌头")
    if borders > GATE["max_border_sides"]:
        framing.append("舌体贴边或背景占满画面，请让舌头居中且四周留出边距")

    reasons = not_tongue + framing
    if reasons:
        return {"pass": False, "confidence": 0.0,
                "reasons": reasons, "metrics": metrics,
                "verdict": "not_tongue" if not_tongue else "bad_framing"}

    # 通过但红度偏低 → 低置信度，量化结果须人工确认后才入档
    confidence = 0.55 if redness < GATE["warn_redness_a"] else 0.85
    return {"pass": True, "confidence": confidence, "reasons": [],
            "metrics": metrics,
            "needs_clinical_calibration": True}
