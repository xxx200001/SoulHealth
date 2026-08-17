"""量化结果 → 辨证引擎输入的字段适配。

为什么需要这一层
----------------
舌诊/面诊量化引擎（tcm/vision/）为了可审计，把每个特征包成
{value, method, params, confidence, needs_review} 的嵌套结构，键名是
body_color / coat_yellow / greasy_dry / tooth_mark …

而辨证引擎（tcm/syndrome.py）的规则表读的是扁平键名：
body_class / coat_class / greasy_score / tooth_mark_grade / crack_grade …

原版把量化结果直接塞给辨证引擎，两侧键名对不上，除 coat_thickness 外
所有舌象、全部面象证据都匹配不到任何规则——舌面诊拍了也等于没拍，而且
不报错，静默失效。本模块负责这道转换，并且是唯一一处转换点。

同理，问诊量表里的分类题（大便性状、口苦、小便颜色）一个选项要落到多个
辨证键（如"干结便秘"→ 便秘），转换规则写在 consultation.py 的选项 maps
字段里，由 symptoms_to_engine() 统一展开。
"""
from __future__ import annotations

from typing import Any, Optional


def _v(node: Any) -> Any:
    """取 {value: ...} 包装里的值；已经是裸值就原样返回。"""
    if isinstance(node, dict) and "value" in node:
        return node["value"]
    return node


def _sub(node: Any, key: str) -> Any:
    val = _v(node)
    if isinstance(val, dict):
        return val.get(key)
    return None


def tongue_to_engine(raw: Optional[dict]) -> dict:
    """舌诊量化输出 → 辨证引擎扁平字段。

    输出键与 syndrome.py RULES 中 src="tongue" 的 field 一一对应：
      body_class / coat_class / coat_thickness / greasy_score /
      dry_score / tooth_mark_grade / crack_grade / petechiae_count
    另附几个展示用字段（不参与规则匹配）。
    """
    if not raw or raw.get("code") not in (0, None):
        return {}
    flat = {
        "body_class":       _sub(raw.get("body_color"), "class"),
        "coat_class":       _sub(raw.get("coat_yellow"), "class"),
        "coat_thickness":   _v(raw.get("coat_thickness")),
        "greasy_score":     _sub(raw.get("greasy_dry"), "greasy_score"),
        "dry_score":        _sub(raw.get("greasy_dry"), "dry_score"),
        "tooth_mark_grade": _sub(raw.get("tooth_mark"), "grade"),
        "crack_grade":      _sub(raw.get("crack"), "grade"),
        "petechiae_count":  _v(raw.get("petechiae")),
        # ---- 仅供前端展示 ----
        "moisture":         _v(raw.get("moisture")),
        "red_index":        _sub(raw.get("body_color"), "red_index"),
        "yellow_index":     _sub(raw.get("coat_yellow"), "yellow_index"),
        "coat_coverage":    (raw.get("segmentation") or {}).get("coat_coverage"),
    }
    return {k: v for k, v in flat.items() if v is not None}


def face_to_engine(raw: Optional[dict]) -> dict:
    """面诊量化输出 → 辨证引擎扁平字段。

    对应 syndrome.py 中 src="face" 的 field：
      sallow_index / dull_index / lip_class / eye_bag_grade / spot_grade
    """
    if not raw or raw.get("code") not in (0, None):
        return {}

    # 无 MediaPipe 时的颜色兜底分析已经是扁平结构，直接透传可用字段
    if raw.get("method") == "color_fallback":
        flat = {
            "sallow_index": raw.get("sallow_index"),
            "brightness":   raw.get("brightness"),
            "complexion":   raw.get("complexion"),
        }
        return {k: v for k, v in flat.items() if v is not None}

    flat = {
        "sallow_index":  _v(raw.get("sallow_index")),
        "dull_index":    _v(raw.get("dull_index")),
        "lip_class":     _sub(raw.get("lip_color"), "class"),
        "eye_bag_grade": _sub(raw.get("eye_bag"), "grade"),
        "spot_grade":    _sub(raw.get("spot"), "grade"),
        # ---- 仅供前端展示 ----
        "brightness":     _v(raw.get("brightness")),
        "lip_red_index":  _sub(raw.get("lip_color"), "red_index"),
    }
    return {k: v for k, v in flat.items() if v is not None}


def symptoms_to_engine(answers: Optional[dict],
                       dimensions: Optional[list] = None) -> dict:
    """问卷作答 → 辨证引擎症状打分。

    - 普通题（subjective / quantifiable）：key 与引擎键同名，原样带 0–10 分。
    - 分类题（classification）：按所选选项的 maps 展开成一个或多个引擎键，
      例如「干结便秘」→ {"便秘": 8}，「时稀时干交替」→ {"便溏": 4, "便秘": 4}。
    - 引擎不认识的键（如"入睡时长"）保留原样，引擎自会忽略，但保留后
      档案里能看到完整作答。
    """
    answers = answers or {}
    if dimensions is None:
        from .consultation import SYMPTOM_DIMENSIONS
        dimensions = SYMPTOM_DIMENSIONS
    by_key = {d["key"]: d for d in dimensions}

    out: dict = {}

    def bump(k: str, v) -> None:
        try:
            v = int(round(float(v)))
        except (TypeError, ValueError):
            return
        if v <= 0:
            return
        out[k] = max(out.get(k, 0), min(10, v))

    for key, val in answers.items():
        dim = by_key.get(key)
        if dim is None:
            bump(key, val)
            continue
        if dim.get("type") == "classification":
            opt = next((o for o in dim.get("options", [])
                        if o.get("value") == val), None)
            if opt is None:
                continue
            maps = opt.get("maps")
            if maps:
                for k, v in maps.items():
                    bump(k, v)
            else:                       # 未配置 maps 的分类题按同名键落分
                bump(key, val)
        else:
            bump(key, val)
    return out


def labs_from_observations(observations: Optional[list]) -> list:
    """档案 observations → lab_mapper 可解析的原始录入格式。

    observations 是统一档案里的指标行（code/display/value_num/unit），
    lab_mapper.parse() 吃的是 {name_raw, value, unit}。取每个 code 的最新一条。
    """
    latest: dict = {}
    for o in observations or []:
        if o.get("value_num") is None:
            continue
        code = (o.get("code") or "").strip()
        if not code:
            continue
        prev = latest.get(code)
        if prev is None or (o.get("observed_at") or "") >= (prev.get("observed_at") or ""):
            latest[code] = o
    return [{"name_raw": o.get("display") or o.get("code"),
             "value": o.get("value_num"),
             "unit": o.get("unit") or ""}
            for o in latest.values()]
