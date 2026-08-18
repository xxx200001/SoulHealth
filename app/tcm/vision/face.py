# -*- coding: utf-8 -*-
"""
face_quant_features.py —— 模块③面诊量化层（自研）
=====================================================================
定位：03开源包只有舌诊、没有面诊。面诊底座选 MediaPipe FaceLandmarker
（Google官方维护、Apache-2.0、pip即装、478点含虹膜、可端侧运行——
比自训人脸分割模型省一整条训练管线，且商用许可干净）。

管线：手机拍照 → MediaPipe 检出478个landmark → 本文件按landmark锚点
取"左颊/右颊/额头/唇/眶下"5类区域 → 输出规格书模块③要求的6个量化字段：

  1. 面色亮度  brightness      （颊+额 L* 均值 → 0-100）
  2. 萎黄值    sallow_index    （b*升高且a*不升的复合指标 0-100）
  3. 暗沉值    dull_index      （低明度+低饱和复合 0-100）
  4. 唇色数值  lip_color       （Lab均值 + red_index + 淡白/淡红/红/紫暗）
  5. 眼袋等级  eye_bag_grade   （眶下区与颊区 L* 差 → 0-3级）
  6. 色斑等级  spot_grade      （颊区黑帽形态学暗斑密度 → 0-3级）

landmark 索引为 MediaPipe FaceMesh 标准编号（跨版本稳定）。
所有阈值 v1 启发式，needs_clinical_calibration=True，上线前用标注面
诊集校准。审计结构与批次1/舌诊层一致。

依赖：numpy, opencv-python（推理端另需 pip install mediapipe）
自测：python face_quant_features.py → 合成人脸+合成landmark 跑断言
"""

import json
import numpy as np
import cv2

VERSION = "0.1.0-batch2"

# ---- MediaPipe FaceMesh 标准索引（锚点） -----------------------------
LEFT_CHEEK = [50, 101, 118, 205]
RIGHT_CHEEK = [280, 330, 347, 425]
FOREHEAD = [10, 67, 109, 151, 297, 338]
LIPS_RING = [0, 37, 39, 40, 185, 61, 146, 91, 181, 84, 17,
             314, 405, 321, 375, 291, 409, 270, 269, 267]
L_EYE_CORNERS = (33, 133)
R_EYE_CORNERS = (362, 263)
L_LOWER_LID = [145, 153]
R_LOWER_LID = [374, 380]


def _audit(value, method, params, confidence=0.7, needs_review=False):
    return {"value": value, "method": method, "params": params,
            "confidence": confidence, "needs_review": needs_review,
            "needs_clinical_calibration": True}


def _clip01(x):
    return float(max(0.0, min(100.0, x)))


def _centroid(lm, ids):
    pts = np.array([lm[i] for i in ids], np.float32)
    return pts.mean(axis=0)


def _circle_mask(shape, center, r):
    m = np.zeros(shape[:2], np.uint8)
    cv2.circle(m, (int(center[0]), int(center[1])), int(r), 255, -1)
    return m.astype(bool)


class FaceQuantizer:
    THRESH = {
        "cheek_r": 0.16, "ue_r": 0.10, "fh_r": 0.13,     # 半径/瞳距比例
        "ue_shift": 1.1,                                  # 眶下区下移·r倍
        "eyebag_dL": (8, 16, 26),                         # 0/1/2/3级分界
        "spot_blackhat_thr": 16, "spot_area": (10, 400),
        "spot_density": (0.004, 0.015, 0.04),
        "lip_pale_a": 140, "lip_red_a": 158,
        "lip_purple_b": 120, "lip_purple_L": 145,
    }

    def analyze(self, img_rgb: np.ndarray, landmarks: dict) -> dict:
        """img_rgb: HxWx3 uint8；landmarks: {index:(x,y)} 像素坐标
        （MediaPipe 输出的归一化坐标请先 ×宽高 转像素）"""
        T = self.THRESH
        need = set(LEFT_CHEEK + RIGHT_CHEEK + FOREHEAD + LIPS_RING
                   + list(L_EYE_CORNERS) + list(R_EYE_CORNERS)
                   + L_LOWER_LID + R_LOWER_LID)
        missing = [i for i in need if i not in landmarks]
        if missing:
            return {"code": 401, "error": f"缺少landmark索引: {missing[:8]}..."}

        lab = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
        hsv = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
        L, A, B = lab[..., 0], lab[..., 1], lab[..., 2]
        S = hsv[..., 1]

        # 瞳距（尺度基准）
        le = _centroid(landmarks, list(L_EYE_CORNERS))
        re = _centroid(landmarks, list(R_EYE_CORNERS))
        iod = float(np.linalg.norm(le - re))
        if iod < 20:
            return {"code": 402, "error": "瞳距过小，人脸不合格"}

        shape = img_rgb.shape
        cheekL = _circle_mask(shape, _centroid(landmarks, LEFT_CHEEK),
                              T["cheek_r"] * iod)
        cheekR = _circle_mask(shape, _centroid(landmarks, RIGHT_CHEEK),
                              T["cheek_r"] * iod)
        fore = _circle_mask(shape, _centroid(landmarks, FOREHEAD),
                            T["fh_r"] * iod)
        skin = cheekL | cheekR | fore

        r_ue = T["ue_r"] * iod
        ueL_c = _centroid(landmarks, L_LOWER_LID) + [0, T["ue_shift"] * r_ue]
        ueR_c = _centroid(landmarks, R_LOWER_LID) + [0, T["ue_shift"] * r_ue]
        under_eye = (_circle_mask(shape, ueL_c, r_ue)
                     | _circle_mask(shape, ueR_c, r_ue))

        lip_pts = np.array([landmarks[i] for i in LIPS_RING], np.int32)
        lip_mask = np.zeros(shape[:2], np.uint8)
        cv2.fillConvexPoly(lip_mask, cv2.convexHull(lip_pts), 255)
        lip_mask = lip_mask.astype(bool)

        # ---- 1) 面色亮度 --------------------------------------------
        skL = float(L[skin].mean())
        brightness = _audit(round(skL / 255 * 100, 1),
                            "颊×2+额 L*均值/255×100",
                            {"regions": "cheekL,cheekR,forehead"})

        # ---- 2) 萎黄值 ----------------------------------------------
        skA, skB = float(A[skin].mean()), float(B[skin].mean())
        sallow = _clip01(((skB - 128) - 0.6 * (skA - 128)) / 30.0 * 100)
        sallow_i = _audit(round(sallow, 1),
                          "(b*-128 − 0.6·(a*-128))/30×100：黄升红不升",
                          {"a_mean": round(skA, 1), "b_mean": round(skB, 1)})

        # ---- 3) 暗沉值 ----------------------------------------------
        skS = float(S[skin].mean())
        dull = _clip01(100 * (0.65 * (1 - skL / 210) + 0.35 * (1 - skS / 130)))
        dull_i = _audit(round(dull, 1), "0.65·低明度 + 0.35·低饱和 复合",
                        {"L_mean": round(skL, 1), "S_mean": round(skS, 1)})

        # ---- 4) 唇色数值 --------------------------------------------
        lL, lA_, lB_ = (float(L[lip_mask].mean()), float(A[lip_mask].mean()),
                        float(B[lip_mask].mean()))
        lip_red = _clip01((lA_ - 128) / 60 * 100)
        if lB_ < T["lip_purple_b"] and lL < T["lip_purple_L"]:
            lip_cls = "紫暗"
        elif lA_ < T["lip_pale_a"]:
            lip_cls = "淡白"
        elif lA_ < T["lip_red_a"]:
            lip_cls = "淡红"
        else:
            lip_cls = "红"
        lip = _audit({"L": round(lL, 1), "a": round(lA_, 1), "b": round(lB_, 1),
                      "red_index": round(lip_red, 1), "class": lip_cls},
                     "唇环landmark凸包区 Lab均值+阈值分类",
                     {"lip_pale_a": T["lip_pale_a"], "lip_red_a": T["lip_red_a"]})

        # ---- 5) 眼袋等级 --------------------------------------------
        cheek_L_mean = float(L[cheekL | cheekR].mean())
        ue_L_mean = float(L[under_eye].mean())
        dL = cheek_L_mean - ue_L_mean
        g1, g2, g3 = T["eyebag_dL"]
        eb_grade = 0 if dL < g1 else 1 if dL < g2 else 2 if dL < g3 else 3
        eye_bag = _audit({"grade": eb_grade, "delta_L": round(dL, 1)},
                         "眶下区较颊区的L*暗沉差分级",
                         {"cut": T["eyebag_dL"]},
                         needs_review=(eb_grade >= 2))

        # ---- 6) 色斑等级 --------------------------------------------
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17))
        blackhat = cv2.morphologyEx(L.astype(np.uint8), cv2.MORPH_BLACKHAT, k)
        cheeks = cheekL | cheekR
        spot_bin = ((blackhat > T["spot_blackhat_thr"]) & cheeks).astype(np.uint8)
        n, _, stats, _ = cv2.connectedComponentsWithStats(spot_bin, 8)
        lo, hi = T["spot_area"]
        spot_area = sum(int(stats[i, 4]) for i in range(1, n)
                        if lo <= stats[i, 4] <= hi)
        density = spot_area / max(int(cheeks.sum()), 1)
        d1, d2, d3 = T["spot_density"]
        sp_grade = 0 if density < d1 else 1 if density < d2 else 2 if density < d3 else 3
        spots = _audit({"grade": sp_grade, "density": round(float(density), 5)},
                       "颊区黑帽形态学暗斑面积密度分级",
                       {"cut": T["spot_density"]},
                       needs_review=(sp_grade >= 2))

        return {"code": 0, "version": VERSION, "iod_px": round(iod, 1),
                "brightness": brightness,       # 1 面色亮度
                "sallow_index": sallow_i,       # 2 萎黄值
                "dull_index": dull_i,           # 3 暗沉值
                "lip_color": lip,               # 4 唇色数值
                "eye_bag": eye_bag,             # 5 眼袋等级
                "spot": spots}                  # 6 色斑等级


# ----------------------------------------------------------------------
# 自测：合成人脸 + 合成landmark
# ----------------------------------------------------------------------
def _make_synthetic():
    img = np.full((512, 512, 3), (215, 180, 160), np.uint8)   # 基础肤色
    # 左右颊涂偏黄肤色（萎黄）
    cv2.circle(img, (165, 300), 34, (212, 192, 138), -1)
    cv2.circle(img, (347, 300), 34, (212, 192, 138), -1)
    # 眶下暗区（眼袋）
    cv2.circle(img, (190, 254), 20, (150, 124, 114), -1)
    cv2.circle(img, (322, 254), 20, (150, 124, 114), -1)
    # 唇
    cv2.ellipse(img, (256, 360), (55, 20), 0, 0, 360, (196, 92, 104), -1)
    # 左颊色斑×5
    for (px, py) in ((155, 292), (172, 305), (160, 315), (178, 292), (168, 322)):
        cv2.circle(img, (px, py), 3, (118, 88, 78), -1)

    lm = {}
    # 眼角（瞳距≈132）
    lm[33], lm[133] = (172, 210), (208, 210)
    lm[362], lm[263] = (304, 210), (340, 210)
    lm[145], lm[153] = (186, 226), (194, 226)   # 左下睑
    lm[374], lm[380] = (318, 226), (326, 226)   # 右下睑
    for i in LEFT_CHEEK:
        lm[i] = (165 + (i % 5) * 2, 300 + (i % 3) * 2)
    for i in RIGHT_CHEEK:
        lm[i] = (347 - (i % 5) * 2, 300 + (i % 3) * 2)
    for i in FOREHEAD:
        lm[i] = (236 + (i % 7) * 6, 130 + (i % 3) * 4)
    n = len(LIPS_RING)
    for k_, i in enumerate(LIPS_RING):          # 唇环按椭圆均匀布点
        th = 2 * np.pi * k_ / n
        lm[i] = (int(256 + 55 * np.cos(th)), int(360 + 20 * np.sin(th)))
    return img, lm


def _self_test():
    img, lm = _make_synthetic()
    r = FaceQuantizer().analyze(img, lm)
    assert r["code"] == 0, r
    assert 30 <= r["brightness"]["value"] <= 95, r["brightness"]
    assert r["sallow_index"]["value"] > 25, r["sallow_index"]
    assert r["dull_index"]["value"] < 75, r["dull_index"]
    assert r["lip_color"]["value"]["class"] in ("淡红", "红"), r["lip_color"]
    assert r["eye_bag"]["value"]["grade"] >= 1, r["eye_bag"]
    assert r["spot"]["value"]["grade"] >= 1, r["spot"]
    print("=== 自测全部通过 ===")
    print(json.dumps(r, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    _self_test()
