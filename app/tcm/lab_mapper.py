# -*- coding: utf-8 -*-
"""
lab_indicator_mapper.py —— 批次1核心：体检指标标准化 + 异常分级 + 方向标记
=====================================================================
定位：规格书模块①的计算内核。OCR识别出的原始文本经本模块标准化后，
输出结构化指标列表，供批次3证型引擎 / 批次4剂量引擎 / 批次5解释引擎消费。

输入：OCR原始文本 或 手动录入的指标列表
    [{"name_raw": "谷丙转氨酶(ALT)", "value": 68, "unit": "U/L"}, ...]

输出：每条指标附带：
    name        标准化名称（归一到INDICATOR_CATALOG里的正名）
    value       数值
    unit        单位
    ref_low     参考范围下限
    ref_high    参考范围上限
    direction   "high" / "low" / "normal"
    grade       0(正常) / 1(轻度) / 2(中度) / 3(重度)
    category    指标类别（肝功能/肾功能/血脂/血糖/血常规/炎症/甲状腺/凝血）
    audit       溯源（参考范围来源、分级依据）

自测：python lab_indicator_mapper.py
"""

import json
import re

VERSION = "0.1.0-batch1"

# ----------------------------------------------------------------------
# 指标目录：标准名 → (别名集, 单位, 参考下限, 参考上限, 类别, 分级阈值)
# 分级阈值: [(G1上界倍率, G2上界倍率)] 或 [(G1下界倍率, G2下界倍率)]
# 偏高时: value > ref_high * 倍率; 偏低时: value < ref_low * 倍率
# ----------------------------------------------------------------------
INDICATOR_CATALOG = {
    # ---- 肝功能 ----
    "ALT": {
        "aliases": ["谷丙转氨酶", "丙氨酸氨基转移酶", "SGPT", "谷丙"],
        "unit": "U/L", "ref": (0, 40), "category": "肝功能",
        "grade_high": [(1.0, 80), (2.0, 200), (5.0, 9999)],  # >40=G1, >80=G2, >200=G3
    },
    "AST": {
        "aliases": ["谷草转氨酶", "天门冬氨酸氨基转移酶", "SGOT", "谷草"],
        "unit": "U/L", "ref": (0, 40), "category": "肝功能",
        "grade_high": [(1.0, 80), (2.0, 200), (5.0, 9999)],
    },
    "GGT": {
        "aliases": ["谷氨酰转肽酶", "γ-谷氨酰转肽酶", "γ-GT", "r-GT"],
        "unit": "U/L", "ref": (0, 50), "category": "肝功能",
        "grade_high": [(1.0, 100), (2.0, 300), (6.0, 9999)],
    },
    "TBIL": {
        "aliases": ["总胆红素"],
        "unit": "μmol/L", "ref": (3.4, 20.5), "category": "肝功能",
        "grade_high": [(1.0, 34.2), (2.0, 171), (10.0, 9999)],
    },
    "DBIL": {
        "aliases": ["直接胆红素", "结合胆红素"],
        "unit": "μmol/L", "ref": (0, 6.8), "category": "肝功能",
        "grade_high": [(1.0, 13.6), (2.0, 68), (10.0, 9999)],
    },
    "ALB": {
        "aliases": ["白蛋白", "血清白蛋白"],
        "unit": "g/L", "ref": (35, 55), "category": "肝功能",
        "grade_low": [(35, 30), (30, 25), (25, 0)],  # <35=G1, <30=G2, <25=G3
    },
    # ---- 肾功能 ----
    "Cr": {
        "aliases": ["肌酐", "血肌酐", "Crea", "SCr"],
        "unit": "μmol/L", "ref": (44, 106), "category": "肾功能",
        "grade_high": [(1.0, 133), (1.5, 177), (3.0, 9999)],
    },
    "BUN": {
        "aliases": ["尿素氮", "尿素", "血尿素氮"],
        "unit": "mmol/L", "ref": (2.9, 8.2), "category": "肾功能",
        "grade_high": [(1.0, 14.3), (2.0, 28.6), (4.0, 9999)],
    },
    "UA": {
        "aliases": ["尿酸", "血尿酸"],
        "unit": "μmol/L", "ref": (150, 416), "category": "肾功能",
        "grade_high": [(1.0, 480), (1.5, 540), (2.0, 9999)],
    },
    # ---- 血脂 ----
    "TG": {
        "aliases": ["甘油三酯", "三酰甘油"],
        "unit": "mmol/L", "ref": (0, 1.7), "category": "血脂",
        "grade_high": [(1.0, 2.3), (2.3, 5.6), (5.6, 9999)],
    },
    "TC": {
        "aliases": ["总胆固醇"],
        "unit": "mmol/L", "ref": (0, 5.2), "category": "血脂",
        "grade_high": [(1.0, 6.2), (1.5, 7.2), (2.0, 9999)],
    },
    "LDL": {
        "aliases": ["低密度脂蛋白", "低密度脂蛋白胆固醇", "LDL-C"],
        "unit": "mmol/L", "ref": (0, 3.4), "category": "血脂",
        "grade_high": [(1.0, 4.1), (1.5, 4.9), (2.0, 9999)],
    },
    "HDL": {
        "aliases": ["高密度脂蛋白", "高密度脂蛋白胆固醇", "HDL-C"],
        "unit": "mmol/L", "ref": (1.0, 999), "category": "血脂",
        "grade_low": [(1.0, 0.9), (0.9, 0.7), (0.7, 0)],
    },
    # ---- 血糖 ----
    "GLU": {
        "aliases": ["空腹血糖", "FPG", "血糖", "葡萄糖"],
        "unit": "mmol/L", "ref": (3.9, 6.1), "category": "血糖",
        "grade_high": [(1.0, 7.0), (7.0, 11.1), (11.1, 9999)],
        "grade_low": [(3.9, 3.0), (3.0, 2.2), (2.2, 0)],
    },
    "HbA1c": {
        "aliases": ["糖化血红蛋白", "糖化"],
        "unit": "%", "ref": (4.0, 6.0), "category": "血糖",
        "grade_high": [(1.0, 6.5), (6.5, 8.0), (8.0, 9999)],
    },
    # ---- 血常规 ----
    "HGB": {
        "aliases": ["血红蛋白", "Hb"],
        "unit": "g/L", "ref": (120, 160), "category": "血常规",
        "grade_low": [(120, 90), (90, 60), (60, 0)],
    },
    "RBC": {
        "aliases": ["红细胞", "红细胞计数"],
        "unit": "×10¹²/L", "ref": (4.0, 5.5), "category": "血常规",
        "grade_low": [(4.0, 3.5), (3.5, 3.0), (3.0, 0)],
    },
    "WBC": {
        "aliases": ["白细胞", "白细胞计数"],
        "unit": "×10⁹/L", "ref": (4.0, 10.0), "category": "血常规",
        "grade_high": [(1.0, 15.0), (15.0, 20.0), (20.0, 9999)],
        "grade_low": [(4.0, 3.0), (3.0, 2.0), (2.0, 0)],
    },
    "PLT": {
        "aliases": ["血小板", "血小板计数"],
        "unit": "×10⁹/L", "ref": (100, 300), "category": "血常规",
        "grade_high": [(1.0, 400), (400, 600), (600, 9999)],
        "grade_low": [(100, 50), (50, 20), (20, 0)],
    },
    # ---- 炎症 ----
    "CRP": {
        "aliases": ["C反应蛋白", "hs-CRP", "超敏C反应蛋白"],
        "unit": "mg/L", "ref": (0, 5), "category": "炎症",
        "grade_high": [(1.0, 10), (2.0, 50), (10.0, 9999)],
    },
    "ESR": {
        "aliases": ["血沉", "红细胞沉降率"],
        "unit": "mm/h", "ref": (0, 20), "category": "炎症",
        "grade_high": [(1.0, 40), (2.0, 80), (4.0, 9999)],
    },
    # ---- 甲状腺 ----
    "TSH": {
        "aliases": ["促甲状腺激素", "促甲状腺素"],
        "unit": "mIU/L", "ref": (0.35, 4.94), "category": "甲状腺",
        "grade_high": [(1.0, 10.0), (2.0, 20.0), (4.0, 9999)],
        "grade_low": [(0.35, 0.1), (0.1, 0.01), (0.01, 0)],
    },
    # ---- 凝血 ----
    "D-Dimer": {
        "aliases": ["D二聚体", "D-二聚体"],
        "unit": "mg/L", "ref": (0, 0.5), "category": "凝血",
        "grade_high": [(1.0, 1.0), (2.0, 5.0), (10.0, 9999)],
    },
    "FIB": {
        "aliases": ["纤维蛋白原"],
        "unit": "g/L", "ref": (2.0, 4.0), "category": "凝血",
        "grade_high": [(1.0, 5.0), (5.0, 7.0), (7.0, 9999)],
    },
    # ---- 铁代谢 ----
    "SF": {
        "aliases": ["血清铁蛋白", "铁蛋白"],
        "unit": "ng/mL", "ref": (20, 200), "category": "血常规",
        "grade_low": [(20, 12), (12, 5), (5, 0)],
    },
}

# 构建别名 → 标准名 映射
_ALIAS_MAP = {}
for std, info in INDICATOR_CATALOG.items():
    _ALIAS_MAP[std] = std
    _ALIAS_MAP[std.lower()] = std
    for a in info["aliases"]:
        _ALIAS_MAP[a] = std
        _ALIAS_MAP[a.lower()] = std

# 清洗正则
_CLEAN_RE = re.compile(r"[（(].*?[)）]|[:：]|^\s+|\s+$")


def normalize_name(raw_name: str) -> str:
    """将OCR识别的指标名归一到标准名，找不到返回None"""
    cleaned = _CLEAN_RE.sub("", raw_name).strip()
    if cleaned in _ALIAS_MAP:
        return _ALIAS_MAP[cleaned]
    if cleaned.lower() in _ALIAS_MAP:
        return _ALIAS_MAP[cleaned.lower()]
    # 模糊匹配：去空格后包含关系
    c2 = cleaned.replace(" ", "").replace("-", "").replace("_", "")
    for alias, std in _ALIAS_MAP.items():
        a2 = alias.replace(" ", "").replace("-", "").replace("_", "")
        if c2 == a2 or (len(c2) >= 3 and c2 in a2) or (len(a2) >= 3 and a2 in c2):
            return std
    return None


def grade_indicator(name: str, value: float) -> dict:
    """对单个标准化指标进行异常分级"""
    info = INDICATOR_CATALOG.get(name)
    if not info:
        return {"name": name, "value": value, "grade": 0,
                "direction": "unknown", "category": "未知",
                "audit": {"method": "未收录指标，无法分级"}}

    ref_low, ref_high = info["ref"]
    direction, grade = "normal", 0

    # 偏高判定
    if "grade_high" in info and value > ref_high:
        direction = "high"
        thresholds = info["grade_high"]
        for g, (_, upper) in enumerate(thresholds, 1):
            if value <= upper:
                grade = g
                break
        else:
            grade = 3

    # 偏低判定
    if "grade_low" in info and value < ref_low:
        direction = "low"
        thresholds = info["grade_low"]
        for g, (upper, lower) in enumerate(thresholds, 1):
            if value >= lower:
                grade = g
                break
        else:
            grade = 3

    grade_labels = {0: "正常", 1: "轻度异常", 2: "中度异常", 3: "重度异常"}
    return {
        "name": name,
        "value": value,
        "unit": info["unit"],
        "ref_low": ref_low,
        "ref_high": ref_high,
        "direction": direction,
        "grade": grade,
        "grade_label": grade_labels[grade],
        "category": info["category"],
        "audit": {
            "method": "参考范围分级",
            "ref_source": "临床检验学通行参考范围(v1启发式，须校准)",
            "needs_clinical_calibration": True,
        },
    }


class LabIndicatorMapper:
    """体检指标标准化 + 异常分级 + 方向标记（批次1核心）"""

    def parse(self, raw_items: list) -> dict:
        """
        输入: [{"name_raw": "谷丙转氨酶(ALT)", "value": 68, "unit": "U/L"}, ...]
        输出: {"indicators": [...], "summary": {...}, "audit": {...}}
        """
        results = []
        unknown = []
        for item in raw_items:
            raw_name = item.get("name_raw", "")
            value = item.get("value")
            if value is None:
                continue
            try:
                value = float(value)
            except (ValueError, TypeError):
                continue

            std_name = normalize_name(raw_name)
            if std_name is None:
                unknown.append(raw_name)
                continue

            graded = grade_indicator(std_name, value)
            graded["name_raw"] = raw_name
            results.append(graded)

        # 按类别分组汇总
        by_cat = {}
        abnormal = [r for r in results if r["grade"] > 0]
        for r in results:
            by_cat.setdefault(r["category"], []).append(r)

        # 肝肾等级（供下游剂量引擎直接消费）
        liver_grade = max(
            (r["grade"] for r in results
             if r["category"] == "肝功能" and r["direction"] == "high"), default=0)
        renal_grade = max(
            (r["grade"] for r in results
             if r["category"] == "肾功能" and r["direction"] == "high"), default=0)

        return {
            "version": VERSION,
            "indicators": results,
            "abnormal_count": len(abnormal),
            "total_count": len(results),
            "unknown_names": unknown,
            "by_category": {cat: len(items) for cat, items in by_cat.items()},
            "derived": {
                "liver_grade": liver_grade,
                "renal_grade": renal_grade,
            },
            "audit": {
                "catalog_size": len(INDICATOR_CATALOG),
                "needs_clinical_calibration": True,
            },
        }

    def to_syndrome_input(self, parsed: dict) -> list:
        """转换为批次3 SyndromeWeightEngine.evaluate(labs=...) 的输入格式"""
        return [
            {"name": r["name"], "grade": r["grade"], "direction": r["direction"]}
            for r in parsed["indicators"] if r["grade"] > 0
        ]


# ----------------------------------------------------------------------
# 自测
# ----------------------------------------------------------------------
def _self_test():
    mapper = LabIndicatorMapper()
    raw = [
        {"name_raw": "谷丙转氨酶(ALT)", "value": 68, "unit": "U/L"},
        {"name_raw": "谷草转氨酶", "value": 42, "unit": "U/L"},
        {"name_raw": "总胆红素", "value": 22.5, "unit": "μmol/L"},
        {"name_raw": "肌酐", "value": 135, "unit": "μmol/L"},
        {"name_raw": "甘油三酯", "value": 2.8, "unit": "mmol/L"},
        {"name_raw": "空腹血糖", "value": 5.5, "unit": "mmol/L"},
        {"name_raw": "血红蛋白", "value": 95, "unit": "g/L"},
        {"name_raw": "C反应蛋白", "value": 12, "unit": "mg/L"},
        {"name_raw": "促甲状腺激素", "value": 8.5, "unit": "mIU/L"},
        {"name_raw": "血清铁蛋白", "value": 10, "unit": "ng/mL"},
        {"name_raw": "不认识的指标XYZ", "value": 99},
    ]
    result = mapper.parse(raw)
    assert result["total_count"] == 10, result["total_count"]
    assert result["abnormal_count"] >= 7
    assert result["unknown_names"] == ["不认识的指标XYZ"]
    assert result["derived"]["liver_grade"] >= 1
    assert result["derived"]["renal_grade"] >= 1

    labs = mapper.to_syndrome_input(result)
    assert all("name" in l and "grade" in l and "direction" in l for l in labs)
    assert any(l["name"] == "ALT" and l["direction"] == "high" for l in labs)

    # 名称归一测试
    assert normalize_name("谷丙转氨酶(ALT)") == "ALT"
    assert normalize_name("hs-CRP") == "CRP"
    assert normalize_name("糖化血红蛋白") == "HbA1c"
    assert normalize_name("D二聚体") == "D-Dimer"

    print("=== 批次1 自测全部通过 ===")
    print(f"识别 {result['total_count']} 项，异常 {result['abnormal_count']} 项")
    print(f"肝功等级: G{result['derived']['liver_grade']}  "
          f"肾功等级: G{result['derived']['renal_grade']}")
    for r in result["indicators"]:
        if r["grade"] > 0:
            print(f"  {r['name']:>6} = {r['value']:>8} {r['unit']:<10} "
                  f"→ {r['direction']} G{r['grade']} ({r['grade_label']})")
    print(json.dumps(labs[:3], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    _self_test()
