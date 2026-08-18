# -*- coding: utf-8 -*-
"""
syndrome_weight_engine.py —— 证型权重引擎（自研第三块，行业无现成开源）
=====================================================================
定位：规格书模块③"输出标准证型（量化占比）" + DOC原稿"库3证型权重库"
的计算内核。消费三路已量化证据，输出八证型分数与占比：

  输入A  labs      批次1 lab_indicator_mapper 的输出（指标名+异常等级0-3+方向）
  输入B  tongue    批次2 tongue_quant_features 的量化字段
  输入C  face      批次2 face_quant_features 的量化字段
  输入D  symptoms  模块2问诊的症状打分 0-10（睡眠/怕冷怕热/疲劳/大小便…）

  输出   八证型：肝郁 脾虚 痰湿 湿热 阴虚 阳虚 气血两虚 血瘀
         每证型 score + percent + 逐条证据贡献审计（哪条舌象/指标/症状
         贡献了多少分，依据教材条目），外加：
         · low_evidence      证据总量不足 → 不出结论，提示补充问诊
         · cold_heat_conflict 寒热证并列靠前（真寒假热等复杂证）→ 强制人审
         · 灰黑苔等疑难征    → 强制人审

设计原则（对齐铁律2/3/5）：
  1. 规则表数据驱动（RULES），每条带教材依据note，全部进审计——这就是
     "为什么判你脾虚"的可解释来源，也是第4批组方引擎"证型轻重权重"的输入。
  2. 权重为v1教材共识启发式，needs_clinical_calibration=True；RULES表
     独立成数据结构就是为了让中医师逐条校准而不动代码。
  3. 引擎只做辨证权重，不开方——组方在模块5，且过人审闸门后才生效。

自测：python syndrome_weight_engine.py  → 三个典型病例断言
"""

import json

VERSION = "0.1.0-batch3"
SYNDROMES = ["肝郁", "脾虚", "痰湿", "湿热", "阴虚", "阳虚", "气血两虚", "血瘀"]

# ----------------------------------------------------------------------
# 规则表：src=证据来源, match=匹配条件, w=各证型基础权重, scale=按程度缩放
# ----------------------------------------------------------------------
RULES = [
    # ---- 舌诊 ----
    dict(id="T01", src="tongue", field="body_class", eq="淡白舌",
         w={"阳虚": 2.0, "气血两虚": 2.0, "脾虚": 1.0}, note="舌淡白主虚寒、气血不足"),
    dict(id="T02", src="tongue", field="body_class", eq="红舌",
         w={"湿热": 1.5, "阴虚": 1.5}, note="舌红主热证（实热/虚热）"),
    dict(id="T03", src="tongue", field="body_class", eq="绛舌",
         w={"阴虚": 2.0, "湿热": 1.0, "血瘀": 0.5}, note="舌绛热入营血、阴伤"),
    dict(id="T04", src="tongue", field="body_class", eq="青紫舌",
         w={"血瘀": 3.0, "阳虚": 0.5}, note="舌青紫主瘀血、寒凝"),
    dict(id="T05", src="tongue", field="coat_class", eq="黄苔",
         cofield="greasy_score", comin=55,
         w={"湿热": 2.5}, note="黄腻苔主湿热内蕴"),
    dict(id="T06", src="tongue", field="coat_class", eq="白苔",
         cofield="greasy_score", comin=55,
         w={"痰湿": 2.5}, note="白腻苔主痰湿/寒湿"),
    dict(id="T07", src="tongue", field="coat_class", eq="黄苔",
         w={"湿热": 1.5}, note="黄苔主热", skip_if_fired="T05"),
    dict(id="T08", src="tongue", field="coat_class", eq="少苔/无苔",
         w={"阴虚": 2.0}, note="少苔无苔主阴虚津亏"),
    dict(id="T09", src="tongue", field="coat_thickness", minv=55, scale_max=100,
         w={"痰湿": 1.0}, note="苔厚主痰湿食积"),
    dict(id="T10", src="tongue", field="tooth_mark_grade", minv=1, scale_max=3,
         w={"脾虚": 1.5, "痰湿": 1.0, "阳虚": 0.5}, note="齿痕舌主脾虚湿盛"),
    dict(id="T11", src="tongue", field="crack_grade", minv=1, scale_max=3,
         w={"阴虚": 1.5}, note="裂纹舌主阴血亏虚"),
    dict(id="T12", src="tongue", field="dry_score", minv=60, scale_max=100,
         w={"阴虚": 1.0}, note="苔燥津亏"),
    dict(id="T13", src="tongue", field="petechiae_count", minv=1, scale_max=5,
         w={"血瘀": 2.0}, note="瘀点瘀斑主血瘀"),
    dict(id="T14", src="tongue", field="coat_class", eq="灰黑苔",
         w={"阳虚": 0.5, "湿热": 0.5}, note="灰黑苔寒热俱可、须人审",
         force_review=True),
    # ---- 面诊 ----
    dict(id="F01", src="face", field="sallow_index", minv=50, scale_max=100,
         w={"脾虚": 1.5, "气血两虚": 1.5}, note="面色萎黄主脾虚、气血不足"),
    dict(id="F02", src="face", field="dull_index", minv=55, scale_max=100,
         w={"血瘀": 1.0, "阳虚": 0.5}, note="面色晦暗主瘀、主肾阳不足"),
    dict(id="F03", src="face", field="lip_class", eq="淡白",
         w={"气血两虚": 1.5, "阳虚": 0.5}, note="唇淡白主气血亏虚"),
    dict(id="F04", src="face", field="lip_class", eq="紫暗",
         w={"血瘀": 2.0}, note="唇紫暗主血瘀"),
    dict(id="F05", src="face", field="eye_bag_grade", minv=1, scale_max=3,
         w={"脾虚": 1.0, "痰湿": 1.0}, note="眼袋主脾虚水湿不化"),
    dict(id="F06", src="face", field="spot_grade", minv=1, scale_max=3,
         w={"血瘀": 1.0, "肝郁": 1.0}, note="面部色斑主肝郁血瘀"),
    # ---- 体检指标（批次1输出：name+grade0-3+direction） ----
    dict(id="L01", src="lab", names=("ALT", "AST"), direction="high",
         w={"肝郁": 1.0, "湿热": 1.0}, note="转氨酶升高·肝失疏泄/肝胆湿热"),
    dict(id="L02", src="lab", names=("GGT", "TBIL", "DBIL"), direction="high",
         w={"湿热": 1.5}, note="胆系指标升高·肝胆湿热"),
    dict(id="L03", src="lab", names=("TG", "TC", "LDL", "脂肪肝"), direction="high",
         w={"痰湿": 1.5}, note="血脂异常/脂肪肝·痰湿内蕴"),
    dict(id="L04", src="lab", names=("GLU", "FPG", "HbA1c"), direction="high",
         w={"阴虚": 1.0, "湿热": 0.5}, note="血糖升高·消渴阴虚燥热"),
    dict(id="L05", src="lab", names=("HGB", "RBC"), direction="low",
         w={"气血两虚": 2.0}, note="血红蛋白/红细胞低·血虚"),
    dict(id="L06", src="lab", names=("TSH",), direction="high",
         w={"阳虚": 1.5}, note="TSH升高(甲减倾向)·阳虚"),
    dict(id="L07", src="lab", names=("TSH",), direction="low",
         w={"阴虚": 1.0, "肝郁": 0.5}, note="TSH降低(甲亢倾向)·阴虚火旺"),
    dict(id="L08", src="lab", names=("CRP", "hs-CRP", "IL-6"), direction="high",
         w={"湿热": 1.0}, note="炎症指标升高·湿热/热毒"),
    dict(id="L09", src="lab", names=("UA",), direction="high",
         w={"痰湿": 1.0, "湿热": 1.0}, note="尿酸升高·湿浊内停"),
    dict(id="L10", src="lab", names=("CR", "Crea", "BUN"), direction="high",
         w={"阳虚": 0.8}, note="肾功能指标升高·肾阳亏（联动模块5风控降剂量）",
         force_review=True),
    # ---- 问诊症状（0-10分） ----
    dict(id="S01", src="symptom", key="怕冷", w={"阳虚": 2.0}, note="畏寒肢冷主阳虚"),
    dict(id="S02", src="symptom", key="怕热", w={"阴虚": 1.0, "湿热": 1.0},
         note="恶热主实热或阴虚内热"),
    dict(id="S03", src="symptom", key="疲劳",
         w={"脾虚": 1.0, "气血两虚": 1.0, "阳虚": 0.5}, note="神疲乏力主气虚"),
    dict(id="S04", src="symptom", key="食欲差", w={"脾虚": 1.5}, note="纳呆主脾失健运"),
    dict(id="S05", src="symptom", key="腹胀", w={"脾虚": 1.0, "肝郁": 1.0},
         note="腹胀主脾虚气滞/肝郁犯脾"),
    dict(id="S06", src="symptom", key="便溏", w={"脾虚": 1.5, "阳虚": 0.5},
         note="大便溏薄主脾阳不足"),
    dict(id="S07", src="symptom", key="便秘", w={"阴虚": 0.8, "湿热": 0.4},
         note="便秘·肠燥津亏或湿热"),
    dict(id="S08", src="symptom", key="尿黄", w={"湿热": 1.5}, note="小便黄赤主湿热"),
    dict(id="S09", src="symptom", key="夜尿多", w={"阳虚": 1.0}, note="夜尿频主肾阳虚"),
    dict(id="S10", src="symptom", key="情绪抑郁", w={"肝郁": 2.0}, note="情志抑郁主肝气郁结"),
    dict(id="S11", src="symptom", key="烦躁易怒", w={"肝郁": 1.5, "阴虚": 0.5},
         note="急躁易怒主肝郁化火"),
    dict(id="S12", src="symptom", key="入睡困难", w={"肝郁": 1.0, "阴虚": 1.0},
         note="不寐主肝郁化火/阴虚火旺"),
    dict(id="S13", src="symptom", key="刺痛固定", w={"血瘀": 2.0},
         note="痛如针刺固定不移主血瘀"),
    dict(id="S14", src="symptom", key="胀痛走窜", w={"肝郁": 1.0}, note="胀痛走窜主气滞"),
    dict(id="S15", src="symptom", key="自汗", w={"脾虚": 1.0, "气血两虚": 0.5},
         note="自汗主气虚不固"),
    dict(id="S16", src="symptom", key="盗汗", w={"阴虚": 2.0}, note="盗汗主阴虚内热"),
    dict(id="S17", src="symptom", key="经期血块", w={"血瘀": 1.5}, note="经血有块主血瘀"),
    dict(id="S18", src="symptom", key="经量少色淡", w={"气血两虚": 1.5},
         note="经少色淡主血虚"),
    dict(id="S19", src="symptom", key="经前乳胀", w={"肝郁": 1.5}, note="经前乳胀主肝郁"),
    dict(id="S20", src="symptom", key="口苦", w={"湿热": 1.0, "肝郁": 0.5},
         note="口苦主肝胆湿热"),
]


class SyndromeWeightEngine:
    LOW_EVIDENCE_TOTAL = 3.0     # 总分低于此不出结论
    CONFLICT_MARGIN = 0.75       # 寒/热阵营分数比值超此视为并列→人审

    def evaluate(self, labs=None, tongue=None, face=None, symptoms=None):
        labs, tongue = labs or [], tongue or {}
        face, symptoms = face or {}, symptoms or {}
        scores = {s: 0.0 for s in SYNDROMES}
        audit, fired, force_review = [], set(), False

        def add(rule, factor, evid):
            nonlocal force_review
            contrib = {s: round(wt * factor, 3) for s, wt in rule["w"].items()}
            for s, v in contrib.items():
                scores[s] += v
            fired.add(rule["id"])
            if rule.get("force_review"):
                force_review = True
            audit.append({"rule": rule["id"], "evidence": evid,
                          "factor": round(factor, 3),
                          "contrib": contrib, "basis": rule["note"]})

        for r in RULES:
            if r.get("skip_if_fired") in fired:
                continue
            if r["src"] in ("tongue", "face"):
                data = tongue if r["src"] == "tongue" else face
                val = data.get(r["field"])
                if val is None:
                    continue
                if "eq" in r:
                    if val != r["eq"]:
                        continue
                    if "cofield" in r and (data.get(r["cofield"], 0) or 0) < r["comin"]:
                        continue
                    add(r, 1.0, f'{r["field"]}={val}')
                elif "minv" in r:
                    if val < r["minv"]:
                        continue
                    add(r, min(1.0, val / r["scale_max"]),
                        f'{r["field"]}={val}')
            elif r["src"] == "lab":
                for item in labs:
                    if (item.get("name") in r["names"]
                            and item.get("direction") == r["direction"]
                            and (item.get("grade", 0) or 0) >= 1):
                        add(r, min(1.0, item["grade"] / 3.0),
                            f'{item["name"]} {r["direction"]} G{item["grade"]}')
            elif r["src"] == "symptom":
                sc = symptoms.get(r["key"], 0) or 0
                if sc >= 3:
                    add(r, min(1.0, sc / 10.0), f'{r["key"]}={sc}分')

        total = sum(scores.values())
        flags = []
        if total < self.LOW_EVIDENCE_TOTAL:
            flags.append("low_evidence:证据不足，请补充问诊/舌面诊后再辨证")
        cold = scores["阳虚"]
        heat = max(scores["湿热"], scores["阴虚"])
        if cold > 1.5 and heat > 1.5 and min(cold, heat) / max(cold, heat) \
                >= self.CONFLICT_MARGIN:
            flags.append("cold_heat_conflict:寒热证并重，疑复杂证候，强制人审")
            force_review = True
        percent = {s: round(v / total * 100, 1) if total > 0 else 0.0
                   for s, v in scores.items()}
        ranked = sorted(SYNDROMES, key=lambda s: -scores[s])
        return {
            "version": VERSION,
            "scores": {s: round(v, 3) for s, v in scores.items()},
            "percent": percent,
            "ranked": ranked,
            "primary": None if total < self.LOW_EVIDENCE_TOTAL else ranked[0],
            "flags": flags,
            "needs_review": force_review or bool(flags),
            "needs_clinical_calibration": True,
            "audit": audit,
        }


# ----------------------------------------------------------------------
# 自测：三个典型画像
# ----------------------------------------------------------------------
def _self_test():
    eng = SyndromeWeightEngine()

    p1 = eng.evaluate(  # 阳虚脾虚（畏寒疲劳便溏+舌淡白齿痕+甲减倾向）
        tongue={"body_class": "淡白舌", "coat_class": "白苔",
                "greasy_score": 60, "tooth_mark_grade": 2},
        symptoms={"怕冷": 8, "疲劳": 7, "便溏": 6},
        labs=[{"name": "TSH", "grade": 2, "direction": "high"}])
    assert p1["primary"] == "阳虚", p1["ranked"]
    assert "脾虚" in p1["ranked"][:3], p1["ranked"]

    p2 = eng.evaluate(  # 肝胆湿热（舌红黄腻+转氨酶胆系炎症+口苦尿黄）
        tongue={"body_class": "红舌", "coat_class": "黄苔", "greasy_score": 70},
        labs=[{"name": "ALT", "grade": 2, "direction": "high"},
              {"name": "GGT", "grade": 2, "direction": "high"},
              {"name": "CRP", "grade": 1, "direction": "high"},
              {"name": "UA", "grade": 1, "direction": "high"}],
        symptoms={"口苦": 6, "尿黄": 7, "怕热": 5})
    assert p2["primary"] == "湿热", p2["ranked"]

    p3 = eng.evaluate(  # 血瘀（舌青紫瘀点+唇紫暗色斑+刺痛经血块）
        tongue={"body_class": "青紫舌", "petechiae_count": 5},
        face={"lip_class": "紫暗", "spot_grade": 2},
        symptoms={"刺痛固定": 8, "经期血块": 7})
    assert p3["primary"] == "血瘀" and p3["percent"]["血瘀"] > 30, p3["percent"]

    p4 = eng.evaluate(symptoms={"疲劳": 4})   # 证据不足
    assert p4["primary"] is None and p4["needs_review"]

    print("=== 自测全部通过 ===")
    print("画像1(阳虚脾虚) top3:", p1["ranked"][:3], p1["percent"][p1["ranked"][0]], "%")
    print("画像2(肝胆湿热) top3:", p2["ranked"][:3], p2["percent"]["湿热"], "%")
    print("画像3(血瘀)     top3:", p3["ranked"][:3], p3["percent"]["血瘀"], "%")
    print("画像2审计样条:", json.dumps(p2["audit"][0], ensure_ascii=False))


if __name__ == "__main__":
    _self_test()
