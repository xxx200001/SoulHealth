"""真实性回归：非舌象 / 无人脸的图片，绝不能产出量化数值。

起因是一个线上事故：用户把一张门诊病历的照片传进舌诊，系统给出
"红舌 / 白苔 / 苔厚度 92.5 / 燥度 70.2 / 齿痕 1 级"并标记"已入档"，
这些数字随后进入辨证加权、影响组方。根因有两处：
  1. "舌体分割"只是一句固定 HSV 红色域阈值，泛黄纸张整片落进红色域；
  2. 分割之后只判"红色像素够不够 500 个"，从不问"这是不是舌头"。
面诊侧同样：兜底路径对整幅图求 Lab 均值，无条件给出"面色红润/萎黄"。

本测试把这两条路钉死。零依赖、零网络。

运行：python tests/test_vision_integrity.py
"""
import base64
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests import sandbox                                    # noqa: E402
sandbox.isolate()

from app.tcm.vision import analyze_face, analyze_tongue      # noqa: E402
from app.tcm.vision.presence import presence_gate, segment   # noqa: E402
from app.tcm.vision.tongue import _make_synthetic            # noqa: E402

PASSED = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        sys.exit(1)
    PASSED += 1


def b64(rgb: np.ndarray) -> str:
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    return base64.b64encode(cv2.imencode(".jpg", bgr)[1]).decode()


def make_document(w: int = 760, h: int = 1000) -> np.ndarray:
    """仿真实拍摄的纸质病历：泛黄纸底 + 成行黑字 + 轻微光照渐变。"""
    img = np.full((h, w, 3), (228, 220, 205), np.uint8)
    rng = np.random.default_rng(7)
    for y in range(90, h - 120, 30):
        for x in range(56, w - 90, 8):
            if rng.random() < 0.6:
                cv2.rectangle(img, (x, y), (x + 5, y + 13), (38, 34, 30), -1)
    grad = np.linspace(1.0, 0.82, w).astype(np.float32)[None, :, None]
    img = np.clip(img.astype(np.float32) * grad, 0, 255).astype(np.uint8)
    return np.clip(img.astype(np.float32)
                   + rng.normal(0, 3, img.shape), 0, 255).astype(np.uint8)


def make_tongue(bg=(62, 46, 46), tone=(198, 118, 120)) -> np.ndarray:
    img = np.full((760, 620, 3), bg, np.uint8)
    mk = np.zeros((760, 620), np.uint8)
    cv2.ellipse(mk, (310, 420), (170, 240), 0, 0, 360, 255, -1)
    img[mk.astype(bool)] = tone
    cv2.ellipse(img, (310, 320), (92, 108), 0, 0, 360, (222, 206, 168), -1)
    rng = np.random.default_rng(11)
    return np.clip(img.astype(np.float32)
                   + rng.normal(0, 3, img.shape), 0, 255).astype(np.uint8)


def main() -> None:
    # ---------- 一、病历照片：必须拒绝，且不含任何量化字段 ----------
    doc = make_document()
    r = analyze_tongue(b64(doc))
    check("病历照片跑舌诊 → 拒绝（code 301）", r["code"] == 301,
          f"code={r['code']}")
    check("拒绝时不返回任何量化数值",
          "quantified" not in r and "features" not in r,
          f"返回字段：{sorted(r.keys())}")
    check("拒绝理由首条指出「拍错了东西」而非「拍得不好」",
          any(k in r["reasons"][0] for k in ("文字", "红色", "纯色", "形状", "比例")),
          r["reasons"][0])

    # ---------- 二、其他非舌象画面 ----------
    for name, img in (
        ("纯白纸", np.full((700, 700, 3), (242, 240, 236), np.uint8)),
        ("木色桌面", np.full((700, 700, 3), (203, 176, 148), np.uint8)),
        ("蓝色墙面", np.full((700, 700, 3), (120, 150, 200), np.uint8)),
    ):
        rr = analyze_tongue(b64(img))
        check(f"{name} → 拒绝且无数值",
              rr["code"] != 0 and "quantified" not in rr, f"code={rr['code']}")

    # ---------- 三、正常舌象仍要放行（不能矫枉过正） ----------
    syn, _ = _make_synthetic()
    ok = analyze_tongue(b64(syn))
    check("合成标准舌象 → 通过", ok["code"] == 0, f"code={ok['code']}")
    check("通过时带置信度与分割方法",
          ok.get("confidence", 0) > 0 and ok.get("segmentation_method"),
          f"conf={ok.get('confidence')} method={ok.get('segmentation_method')}")
    check("通过时给出可喂辨证引擎的特征", bool(ok.get("features")))

    for tone, nm in (((198, 118, 120), "偏淡红"), ((176, 92, 98), "偏暗红"),
                     ((214, 136, 132), "偏亮红")):
        t = analyze_tongue(b64(make_tongue(tone=tone)))
        check(f"舌象·{nm} → 通过", t["code"] == 0, f"code={t['code']}")

    # ---------- 四、外部分割 mask 入口（接 SAM/U-Net 时不走启发式） ----------
    mask = np.zeros(syn.shape[:2], bool)
    cv2.ellipse(mask.view(np.uint8), (320, 360), (180, 230), 0, 0, 360, 1, -1)
    ext = analyze_tongue(b64(syn), external_mask=mask)
    check("传入外部 mask 时标注 segmentation_method=external_mask",
          ext.get("segmentation_method") == "external_mask",
          str(ext.get("segmentation_method")))

    # ---------- 五、面诊：没有人脸就不给面色结论 ----------
    f = analyze_face(b64(doc))
    check("病历照片跑面诊 → 拒绝（code 303）", f["code"] == 303, f"code={f['code']}")
    check("面诊拒绝时不返回面色/萎黄值",
          "quantified" not in f and "features" not in f,
          f"返回字段：{sorted(f.keys())}")
    for name, img in (("纯色墙", np.full((600, 600, 3), (150, 178, 205), np.uint8)),
                      ("木色桌面", np.full((600, 600, 3), (203, 176, 148), np.uint8))):
        fr = analyze_face(b64(img))
        check(f"{name}跑面诊 → 拒绝且无面色",
              fr["code"] != 0 and "quantified" not in fr, f"code={fr['code']}")

    # ---------- 六、门禁指标本身可解释 ----------
    # 用一张"有大片暖色但不是舌头"的图走完整判据链（病历图红度过低会在
    # 像素数这一关就早退，拿不到后续指标，另行断言）。
    warm = np.full((760, 620, 3), (150, 140, 132), np.uint8)
    cv2.rectangle(warm, (60, 80), (560, 700), (206, 150, 140), -1)
    rng = np.random.default_rng(5)
    warm = np.clip(warm.astype(np.float32) + rng.normal(0, 4, warm.shape),
                   0, 255).astype(np.uint8)
    g = presence_gate(warm, segment(warm))
    check("门禁回传可解释指标（红度/填充/实心度/纹理）",
          all(k in g["metrics"] for k in
              ("redness_a", "fill_ratio", "solidity", "texture_std")),
          str(g["metrics"]))

    gd = presence_gate(doc, segment(doc))
    check("病历照在门禁处判为 not_tongue（原实现正是在这里判成红舌）",
          gd["pass"] is False and gd.get("verdict") == "not_tongue",
          f"verdict={gd.get('verdict')} metrics={gd['metrics']}")

    print(f"\n全部 {PASSED} 项通过 ✔")


if __name__ == "__main__":
    main()
