# -*- coding: utf-8 -*-
"""
tongue_quant_features.py —— 模块③舌诊量化层（自研，行业无现成开源）
=====================================================================
定位：接在 03_TongueDiagnosis 管线的 SAM 分割之后。
     该开源项目只输出 4 个"分类标签"（舌色5类/苔色3类/厚薄2类/腐腻2类），
     而规格书要求 8 个"量化数值字段"入库参与组方加权。本文件补齐这一层。

输入：原图 RGB ndarray + SAM 舌体二值 mask
输出（规格书模块③"必须入库的量化字段"逐条对应）：
  1. 舌质颜色数值  body_color        （Lab/HSV均值 + red_index 0-100 + 五分类）
  2. 舌苔厚度数值  coat_thickness    （覆盖率×透底度合成 0-100）
  3. 黄白度        coat_yellow_index （Lab b*通道 0-100 + 白/黄/灰黑分类）
  4. 腻燥度        greasy / dry      （纹理平滑度+镜面高光合成，各0-100）
  5. 齿痕等级      tooth_mark_grade  （轮廓凸包缺陷分析 0-3级）
  6. 裂纹等级      crack_grade       （黑帽形态学+长条形连通域 0-3级）
  7. 津液数值      moisture          （镜面高光占比 0-100）
  8. 瘀点数量      petechiae_count   （紫暗小连通域计数）

每个字段附带 audit（方法/阈值/置信度/是否需人审），与批次1的
lab_indicator_mapper 溯源审计风格一致；分类阈值为 v1 启发式，
标注 needs_clinical_calibration=True，上线前须用标注舌象集校准。

依赖：numpy, opencv-python（03项目环境本来就有）
自测：python tongue_quant_features.py  → 合成舌象跑全部断言
"""

import json
import numpy as np
import cv2

VERSION = "0.1.0-batch2"


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------
def _to_lab_hsv(img_rgb):
    lab = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    hsv = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    return lab, hsv


def _mean_of(chan, mask):
    v = chan[mask]
    return float(v.mean()) if v.size else float("nan")


def _clip01(x):
    return float(max(0.0, min(100.0, x)))


def _audit(value, method, params, confidence=0.7, needs_review=False):
    return {
        "value": value,
        "method": method,
        "params": params,
        "confidence": confidence,
        "needs_review": needs_review,
        "needs_clinical_calibration": True,
    }


# ----------------------------------------------------------------------
# 主类
# ----------------------------------------------------------------------
class TongueQuantizer:
    """所有阈值集中在 THRESH，方便后续用标注数据整体校准。"""

    THRESH = {
        # 舌质五分类（OpenCV Lab: a,b 已 +128 偏置；L 为 L*255/100）
        "body_pale_a": 138, "body_pale_L": 150,      # 淡白
        "body_lightred_a": 152,                      # 淡红上限
        "body_red_a": 168,                           # 红上限，超过且L低→绛
        "body_crimson_L": 145,
        "body_purple_b": 120, "body_purple_L": 140,  # 青紫：偏蓝紫且暗
        # 苔色
        "coat_yellow_b": 150, "coat_dark_L": 110,
        # 齿痕：凸包缺陷深度阈（占舌短轴比例）
        "tm_depth_ratio": 0.055, "tm_severe_ratio": 0.12,
        # 裂纹
        "crack_blackhat_thr": 18, "crack_elong": 3.0,
        # 津液（镜面高光）
        "spec_V": 235, "spec_S": 40, "spec_full_ratio": 0.02,
        # 瘀点
        "pet_L_max": 130, "pet_b_max": 118, "pet_area": (6, 150),
        # 苔/质分离兜底
        "coat_min_frac": 0.02,
    }

    # ------------------------------------------------------------------
    def analyze(self, img_rgb: np.ndarray, tongue_mask: np.ndarray) -> dict:
        """img_rgb: HxWx3 uint8 (RGB)；tongue_mask: HxW bool/0-1（SAM输出）"""
        T = self.THRESH
        mask = tongue_mask.astype(bool)
        if mask.sum() < 500:
            return {"code": 301, "error": "舌体mask过小，图片不合格"}

        lab, hsv = _to_lab_hsv(img_rgb)
        L, A, B = lab[..., 0], lab[..., 1], lab[..., 2]
        H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]

        # -------- 1) 苔/质分离：舌体内对 a* 通道做 Otsu 双峰切分 ------
        a_in = A[mask].astype(np.uint8)
        otsu_thr, _ = cv2.threshold(a_in, 0, 255,
                                    cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        body = mask & (A > otsu_thr)          # 高a* = 偏红 = 舌质
        coat = mask & (A <= otsu_thr)         # 低a* = 苔
        coat_frac = coat.sum() / mask.sum()
        body_frac = body.sum() / mask.sum()
        degenerate = coat_frac < T["coat_min_frac"] or body_frac < T["coat_min_frac"]
        if degenerate:  # 少苔/无苔或全苔：退化为整舌统计
            body, coat = mask, np.zeros_like(mask)
            coat_frac = 0.0

        # -------- 2) 舌质颜色数值 + 分类 ------------------------------
        bL, bA, bB = _mean_of(L, body), _mean_of(A, body), _mean_of(B, body)
        red_index = _clip01((bA - 128.0) / 60.0 * 100.0)
        if bB < T["body_purple_b"] and bL < T["body_purple_L"]:
            body_cls = "青紫舌"
        elif bA < T["body_pale_a"] and bL > T["body_pale_L"]:
            body_cls = "淡白舌"
        elif bA < T["body_lightred_a"]:
            body_cls = "淡红舌"
        elif bA < T["body_red_a"] or bL >= T["body_crimson_L"]:
            body_cls = "红舌"
        else:
            body_cls = "绛舌"
        body_color = _audit(
            {"L": round(bL, 1), "a": round(bA, 1), "b": round(bB, 1),
             "red_index": round(red_index, 1), "class": body_cls},
            "Lab均值(舌质像素)+阈值分类", {k: T[k] for k in
             ("body_pale_a", "body_lightred_a", "body_red_a")})

        # -------- 3) 黄白度（苔色） -----------------------------------
        if coat_frac > 0:
            cL, cB = _mean_of(L, coat), _mean_of(B, coat)
            yellow_index = _clip01((cB - 128.0) / 40.0 * 100.0)
            if cL < T["coat_dark_L"]:
                coat_cls = "灰黑苔"
            elif cB > T["coat_yellow_b"]:
                coat_cls = "黄苔"
            else:
                coat_cls = "白苔"
        else:
            cL = cB = float("nan")
            yellow_index, coat_cls = 0.0, "少苔/无苔"
        coat_yellow = _audit(
            {"yellow_index": round(yellow_index, 1), "class": coat_cls},
            "Lab b*均值(苔区像素)", {"coat_yellow_b": T["coat_yellow_b"]})

        # -------- 4) 舌苔厚度数值 -------------------------------------
        if coat_frac > 0:
            see_through = (_mean_of(A, coat) - 128.0) / max(bA - 128.0, 1e-3)
            see_through = max(0.0, min(1.0, see_through))  # 越高越透底=越薄
            thickness = _clip01(100 * (0.7 * coat_frac + 0.3 * (1 - see_through)))
        else:
            thickness = 0.0
        coat_thickness = _audit(
            round(thickness, 1), "覆盖率0.7+透底度0.3加权",
            {"coverage": round(coat_frac, 3)},
            needs_review=True)  # 2D单图测厚为代理指标，强制人审+与ResNet头交叉验证

        # -------- 5) 腻燥度 -------------------------------------------
        gx = cv2.Sobel(L, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(L, cv2.CV_32F, 0, 1, ksize=3)
        gmag = np.sqrt(gx ** 2 + gy ** 2)
        region = coat if coat_frac > 0 else body
        rough = float(gmag[region].std()) if region.sum() else 0.0
        spec = (V > T["spec_V"]) & (S < T["spec_S"]) & mask
        spec_ratio = spec.sum() / mask.sum()
        smooth = 1.0 / (1.0 + rough / 25.0)
        greasy = _clip01(100 * (0.6 * smooth + 0.4 * min(1.0, spec_ratio / 0.01))
                         * (min(1.0, coat_frac / 0.15) if coat_frac > 0 else 0.3))
        dry = _clip01(100 * (0.7 * min(1.0, rough / 60.0)
                             + 0.3 * (1 - min(1.0, spec_ratio / 0.005))))
        greasy_dry = _audit(
            {"greasy_score": round(greasy, 1), "dry_score": round(dry, 1),
             "texture_roughness": round(rough, 2)},
            "苔区Sobel纹理粗糙度+镜面高光占比合成",
            {"spec_ratio": round(float(spec_ratio), 5)})

        # -------- 6) 齿痕等级：凸包缺陷 -------------------------------
        # 凸包填充 − 舌体mask = 各"咬口"独立连通域（同侧多齿痕不会像
        # convexityDefects 那样共享一条凸包边被合并成1个）
        m8 = (mask.astype(np.uint8)) * 255
        cnts, _ = cv2.findContours(m8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        tooth_cnt, tooth_depths = 0, []
        if cnts:
            c = max(cnts, key=cv2.contourArea)
            x, y, w, h = cv2.boundingRect(c)
            minor = min(w, h)
            cx = x + w / 2.0
            hull_pts = cv2.convexHull(c)
            hull_mask = np.zeros_like(m8)
            cv2.fillConvexPoly(hull_mask, hull_pts, 255)
            bite = ((hull_mask > 0) & (~mask)).astype(np.uint8)
            nb, _, bstats, bcent = cv2.connectedComponentsWithStats(bite, 8)
            for i in range(1, nb):
                bw, bh, barea = bstats[i, 2], bstats[i, 3], bstats[i, 4]
                depth = min(bw, bh)
                lateral = abs(bcent[i][0] - cx) > 0.30 * w  # 只数两侧缘
                if (lateral and barea > 120
                        and depth > T["tm_depth_ratio"] * minor):
                    tooth_cnt += 1
                    tooth_depths.append(depth / minor)
        if tooth_cnt == 0:
            tm_grade = 0
        elif tooth_cnt <= 2:
            tm_grade = 1
        elif tooth_cnt <= 4 and max(tooth_depths) < self.THRESH["tm_severe_ratio"]:
            tm_grade = 2
        else:
            tm_grade = 3
        tooth_mark = _audit(
            {"grade": tm_grade, "notch_count": tooth_cnt,
             "max_depth_ratio": round(max(tooth_depths), 3) if tooth_depths else 0},
            "外轮廓凸包缺陷·侧缘深度过滤", {"depth_thr": T["tm_depth_ratio"]})

        # -------- 7) 裂纹等级：黑帽 + 长条形连通域 --------------------
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
        blackhat = cv2.morphologyEx(L.astype(np.uint8), cv2.MORPH_BLACKHAT, k)
        crack_bin = ((blackhat > T["crack_blackhat_thr"]) & body).astype(np.uint8)
        n, lbl, stats, _ = cv2.connectedComponentsWithStats(crack_bin, 8)
        crack_len, crack_n = 0.0, 0
        crack_mask = np.zeros_like(crack_bin, dtype=bool)
        for i in range(1, n):
            cw, ch, area = stats[i, 2], stats[i, 3], stats[i, 4]
            long_ = max(cw, ch); short_ = max(min(cw, ch), 1)
            if long_ / short_ >= T["crack_elong"] and long_ > 12 and area > 20:
                crack_n += 1
                crack_len += long_
                crack_mask |= (lbl == i)
        norm_len = crack_len / max(np.sqrt(mask.sum()), 1)
        crack_grade = 0 if crack_n == 0 else 1 if norm_len < 0.5 else 2 if norm_len < 1.2 else 3
        crack = _audit(
            {"grade": crack_grade, "crack_count": crack_n,
             "norm_length": round(float(norm_len), 3)},
            "L通道黑帽形态学+长宽比≥3连通域", {"thr": T["crack_blackhat_thr"]})

        # -------- 8) 津液数值 -----------------------------------------
        moisture = _clip01(100 * spec_ratio / T["spec_full_ratio"])
        moist = _audit(round(moisture, 1), "镜面高光像素占比线性映射",
                       {"spec_ratio": round(float(spec_ratio), 5)})

        # -------- 9) 瘀点数量 -----------------------------------------
        pet_bin = ((L < T["pet_L_max"]) & (B < T["pet_b_max"]) & body
                   & (~crack_mask)).astype(np.uint8)
        n2, _, stats2, _ = cv2.connectedComponentsWithStats(pet_bin, 8)
        lo, hi = T["pet_area"]
        pet_count = sum(1 for i in range(1, n2) if lo <= stats2[i, 4] <= hi)
        petechiae = _audit(pet_count, "紫暗色域(L低&b*低)小连通域计数",
                           {"area_range": T["pet_area"]})

        return {
            "code": 0,
            "version": VERSION,
            "body_color": body_color,          # 1 舌质颜色数值
            "coat_thickness": coat_thickness,  # 2 舌苔厚度数值
            "coat_yellow": coat_yellow,        # 3 黄白度
            "greasy_dry": greasy_dry,          # 4 腻燥度
            "tooth_mark": tooth_mark,          # 5 齿痕等级
            "crack": crack,                    # 6 裂纹等级
            "moisture": moist,                 # 7 津液数值
            "petechiae": petechiae,            # 8 瘀点数量
            "segmentation": {"coat_coverage": round(float(coat_frac), 3),
                             "otsu_a_thr": float(otsu_thr),
                             "degenerate": bool(degenerate)},
        }


# ----------------------------------------------------------------------
# 拍摄强制校验（规格书：自然光/清晰/不过曝，不合格直接拦截禁止上传）
# 部署位置：APP端拍照后本地先跑一次 + 后端上传接口再跑一次（双保险）
# ----------------------------------------------------------------------
def quality_gate(img_rgb: np.ndarray) -> dict:
    gray = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)
    mean_v = float(gray.mean())
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    over = float((gray > 250).mean())
    hsv = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2HSV)
    sat = float(hsv[..., 1].mean())
    fails = []
    if mean_v < 60:
        fails.append("光线过暗，请在自然光下拍摄")
    if mean_v > 215:
        fails.append("光线过亮/过曝")
    if over > 0.10:
        fails.append("存在大面积过曝（可能开了闪光灯或强滤镜）")
    if blur < 20:
        fails.append("图像模糊，请对焦后重拍")
    if sat < 18:
        fails.append("色彩饱和度异常（疑似滤镜/黑白模式）")
    return {"pass": not fails, "reasons": fails,
            "metrics": {"brightness": round(mean_v, 1),
                        "blur_var": round(blur, 1),
                        "overexposed_ratio": round(over, 4),
                        "saturation": round(sat, 1)}}


# ----------------------------------------------------------------------
# 自测：合成舌象（无网环境可跑）
# ----------------------------------------------------------------------
def _make_synthetic():
    img = np.full((640, 640, 3), (30, 30, 30), np.uint8)
    mask = np.zeros((640, 640), np.uint8)
    cv2.ellipse(mask, (320, 360), (180, 230), 0, 0, 360, 255, -1)
    # 侧缘齿痕：左右各3个半圆咬口（x取该高度上椭圆的真实边缘）
    for side in (-1, 1):
        for yy in (250, 370, 480):
            edge = int(180 * np.sqrt(max(0.0, 1 - ((yy - 360) / 230) ** 2)))
            cv2.circle(mask, (320 + side * edge, yy), 24, 0, -1)
    m = mask.astype(bool)
    img[m] = (200, 120, 125)                       # 舌质淡红-红
    coat = np.zeros_like(mask)
    cv2.ellipse(coat, (320, 250), (95, 105), 0, 0, 360, 255, -1)
    cm = coat.astype(bool) & m
    img[cm] = (225, 212, 158)                      # 黄白苔
    cv2.line(img, (320, 400), (322, 545), (90, 40, 45), 4)   # 裂纹
    for (px, py) in ((250, 430), (390, 450), (280, 520), (360, 520)):
        cv2.circle(img, (px, py), 4, (70, 35, 80), -1)       # 瘀点×4
    for (px, py) in ((300, 300), (345, 330), (310, 470),
                     (335, 500), (290, 380), (355, 410)):
        cv2.circle(img, (px, py), 2, (252, 252, 252), -1)    # 津液高光
    return img, m


def _self_test():
    img, mask = _make_synthetic()
    # 质量闸门：正常图放行；压暗图、纯模糊图必须拦截
    assert quality_gate(img)["pass"] is True
    dark = (img.astype(np.float32) * 0.15).astype(np.uint8)
    assert quality_gate(dark)["pass"] is False
    blurry = cv2.GaussianBlur(img, (51, 51), 0)
    assert quality_gate(blurry)["pass"] is False
    r = TongueQuantizer().analyze(img, mask)
    assert r["code"] == 0, r
    assert r["body_color"]["value"]["class"] in ("淡红舌", "红舌"), r["body_color"]
    assert r["coat_yellow"]["value"]["class"] == "黄苔", r["coat_yellow"]
    assert 5 < r["coat_thickness"]["value"] < 90, r["coat_thickness"]
    assert r["tooth_mark"]["value"]["grade"] >= 2, r["tooth_mark"]
    assert r["crack"]["value"]["grade"] >= 1, r["crack"]
    assert 3 <= r["petechiae"]["value"] <= 5, r["petechiae"]
    assert 0 <= r["moisture"]["value"] <= 100
    g = r["greasy_dry"]["value"]
    assert 0 <= g["greasy_score"] <= 100 and 0 <= g["dry_score"] <= 100
    print("=== 自测全部通过 ===")
    print(json.dumps(r, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    _self_test()
