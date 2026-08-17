# -*- coding: utf-8 -*-
"""
drug_interaction.py —— 中西药相互作用规则表
=====================================================================
批次4遗留：patient.current_drugs 字段已预留但规则表为空。
华法林×丹参、他汀×红曲这类是真出事的临床风险。

本模块提供：
1. 中西药相互作用规则表（种子数据，need_review=1）
2. 组方前置校验接口：检查患者正在服用的西药是否与候选中药冲突

自测：python drug_interaction.py
"""
import json

VERSION = "0.1.0"

# 中西药相互作用规则（种子数据，须药师+临床药学专家复核）
# 格式: (西药, 中药, 级别, 机制, 后果, 来源)
INTERACTION_RULES = [
    # ---- 抗凝血药 ----
    ("华法林", "丹参", "forbid",
     "丹参抑制血小板聚集+华法林抗凝，协同增效",
     "出血风险显著增加，有临床出血事件报道",
     "[TEXT]中西药相互作用·抗凝类(须药师复核)"),
    ("华法林", "当归", "warn",
     "当归含香豆素类成分，可能增强华法林抗凝效应",
     "INR升高、出血风险增加",
     "[TEXT]中西药相互作用·抗凝类(须药师复核)"),
    ("华法林", "红花", "forbid",
     "红花活血化瘀+华法林抗凝，双重出血风险",
     "出血风险显著增加",
     "[TEXT]中西药相互作用·抗凝类(须药师复核)"),
    ("华法林", "桃仁", "warn",
     "桃仁含苦杏仁苷+抗凝作用",
     "可能增加出血风险",
     "[TEXT]中西药相互作用·抗凝类(须药师复核)"),
    ("华法林", "川芎", "warn",
     "川芎嗪有抗血小板聚集作用",
     "可能增强抗凝效应",
     "[TEXT]中西药相互作用·抗凝类(须药师复核)"),
    ("阿司匹林", "丹参", "warn",
     "双重抗血小板聚集",
     "胃肠道出血风险增加",
     "[TEXT]中西药相互作用·抗凝类(须药师复核)"),
    # ---- 降压药 ----
    ("降压药", "甘草", "warn",
     "甘草致假性醛固酮增多症，升高血压",
     "拮抗降压效果，血压控制不佳",
     "[TEXT]中西药相互作用·降压类(须药师复核)"),
    ("降压药", "麻黄", "forbid",
     "麻黄含伪麻黄碱，升高血压",
     "严重拮抗降压药，血压骤升风险",
     "[TEXT]中西药相互作用·降压类(须药师复核)"),
    # ---- 降糖药 ----
    ("二甲双胍", "黄芪", "info",
     "黄芪有降糖趋势",
     "可能增强降糖效应，需监测血糖",
     "[TEXT]中西药相互作用·降糖类(须药师复核)"),
    ("胰岛素", "人参", "warn",
     "人参有降血糖作用",
     "可能增强降糖效应，有低血糖风险",
     "[TEXT]中西药相互作用·降糖类(须药师复核)"),
    # ---- 他汀类 ----
    ("他汀", "红曲", "forbid",
     "红曲含洛伐他汀，与口服他汀叠加等同双倍用量",
     "横纹肌溶解风险显著增加，有致死病例报道",
     "[TEXT]中西药相互作用·他汀类(须药师复核)"),
    ("他汀", "柚子", "warn",
     "柚子含呋喃香豆素，抑制CYP3A4代谢他汀",
     "他汀血药浓度升高，肌病风险",
     "[TEXT]中西药相互作用·他汀类(须药师复核)"),
    # ---- 洋地黄类 ----
    ("地高辛", "甘草", "warn",
     "甘草致低钾血症增加地高辛敏感性",
     "洋地黄中毒风险（心律失常）",
     "[TEXT]中西药相互作用·强心苷类(须药师复核)"),
    ("地高辛", "麻黄", "forbid",
     "麻黄增加心肌兴奋性",
     "叠加地高辛，心律失常风险",
     "[TEXT]中西药相互作用·强心苷类(须药师复核)"),
    # ---- 免疫抑制剂 ----
    ("环孢素", "甘草", "warn",
     "甘草酸影响环孢素代谢",
     "环孢素血药浓度波动",
     "[TEXT]中西药相互作用·免疫类(须药师复核)"),
    # ---- 含金属药物 ----
    ("铁剂", "茶叶", "warn",
     "鞣酸与铁形成不溶性沉淀",
     "铁吸收率降低，补铁效果差",
     "[TEXT]中西药相互作用·矿物质类(须药师复核)"),
    ("铁剂", "大黄", "warn",
     "大黄鞣质与铁结合",
     "影响铁吸收",
     "[TEXT]中西药相互作用·矿物质类(须药师复核)"),
]

# 西药名→别名/通用名映射
DRUG_ALIASES = {
    "华法林": ["warfarin", "coumadin", "法华令"],
    "阿司匹林": ["aspirin", "拜阿司匹灵", "阿司匹灵"],
    "他汀": ["阿托伐他汀", "瑞舒伐他汀", "辛伐他汀", "匹伐他汀",
             "氟伐他汀", "洛伐他汀", "atorvastatin", "rosuvastatin",
             "simvastatin", "statin", "立普妥"],
    "二甲双胍": ["metformin", "格华止"],
    "胰岛素": ["insulin"],
    "降压药": ["氨氯地平", "硝苯地平", "缬沙坦", "厄贝沙坦",
               "氯沙坦", "依那普利", "卡托普利", "美托洛尔",
               "比索洛尔", "amlodipine", "valsartan"],
    "地高辛": ["digoxin"],
    "环孢素": ["cyclosporine"],
    "铁剂": ["硫酸亚铁", "富马酸亚铁", "琥珀酸亚铁", "蔗糖铁"],
}

# 构建西药别名→标准名映射
_DRUG_MAP = {}
for std, aliases in DRUG_ALIASES.items():
    _DRUG_MAP[std] = std
    _DRUG_MAP[std.lower()] = std
    for a in aliases:
        _DRUG_MAP[a] = std
        _DRUG_MAP[a.lower()] = std


def normalize_drug(name: str) -> str:
    """将患者录入的西药名归一化"""
    cleaned = name.strip()
    if cleaned in _DRUG_MAP:
        return _DRUG_MAP[cleaned]
    if cleaned.lower() in _DRUG_MAP:
        return _DRUG_MAP[cleaned.lower()]
    # 包含匹配
    for alias, std in _DRUG_MAP.items():
        if len(alias) >= 3 and alias in cleaned:
            return std
    return cleaned


class DrugInteractionChecker:
    """中西药相互作用校验器"""

    def check(self, current_drugs: list, candidate_herbs: list) -> dict:
        """
        current_drugs: 患者当前服用的西药列表 ["华法林", "阿托伐他汀"]
        candidate_herbs: 候选中药列表 ["丹参", "红花", "甘草"]
        返回: 冲突列表 + 是否应拦截
        """
        normalized = [normalize_drug(d) for d in current_drugs]
        conflicts = []
        for drug_raw, drug_norm in zip(current_drugs, normalized):
            for rule in INTERACTION_RULES:
                r_drug, r_herb, level, mechanism, consequence, src = rule
                if r_drug != drug_norm:
                    continue
                if r_herb in candidate_herbs:
                    conflicts.append({
                        "drug": drug_raw,
                        "drug_normalized": drug_norm,
                        "herb": r_herb,
                        "level": level,
                        "mechanism": mechanism,
                        "consequence": consequence,
                        "src": src,
                        "need_review": True,
                    })

        has_forbid = any(c["level"] == "forbid" for c in conflicts)
        has_warn = any(c["level"] == "warn" for c in conflicts)
        return {
            "version": VERSION,
            "current_drugs": current_drugs,
            "candidate_herbs": candidate_herbs,
            "conflicts": conflicts,
            "should_block": has_forbid,
            "has_warnings": has_warn,
            "action": ("BLOCK：存在严重中西药相互作用，须药师评估后方可用药"
                       if has_forbid else
                       "WARN：存在潜在相互作用，已标注提醒医师关注"
                       if has_warn else
                       "PASS：未发现已知中西药相互作用"),
        }


# ----------------------------------------------------------------------
# 自测
# ----------------------------------------------------------------------
def _self_test():
    checker = DrugInteractionChecker()

    # 华法林 + 丹参 → forbid
    r1 = checker.check(["华法林"], ["丹参", "柴胡", "甘草"])
    assert r1["should_block"] is True
    assert any(c["herb"] == "丹参" and c["level"] == "forbid" for c in r1["conflicts"])

    # 他汀 + 红曲 → forbid
    r2 = checker.check(["阿托伐他汀"], ["红曲", "山楂"])
    assert r2["should_block"] is True

    # 降压药 + 甘草 → warn
    r3 = checker.check(["氨氯地平"], ["甘草", "白术"])
    assert r3["has_warnings"] is True
    assert r3["should_block"] is False

    # 无冲突
    r4 = checker.check(["维生素C"], ["柴胡", "白芍"])
    assert not r4["conflicts"]
    assert r4["action"].startswith("PASS")

    # 别名归一
    assert normalize_drug("立普妥") == "他汀"
    assert normalize_drug("warfarin") == "华法林"

    print("=== 中西药相互作用 自测全部通过 ===")
    print(f"规则库: {len(INTERACTION_RULES)} 条")
    print(f"华法林+丹参: {r1['action'][:20]}")
    print(f"他汀+红曲: {r2['action'][:20]}")


if __name__ == "__main__":
    _self_test()
