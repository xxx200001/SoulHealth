# -*- coding: utf-8 -*-
"""
批次4 核心：0.1g 精准组方引擎  v1.0
=====================================================================
设计立场（决定了这个引擎为什么可以上生产）：

1. **剂量不由大模型生成。** 全流程是确定性的加权乘法 + 硬钳位，
   同样的输入永远得到同样的克数，可复算、可审计、可追责。
   LLM 只在模块6负责把本引擎输出的 audit 翻译成人话，不参与算数。

2. **基础方加减，不自由组方。** 主证型选经典基础方，兼证型按占比加味。
   自由组药无法举证，基础方有出处（《方剂学》《伤寒论》）。

3. **药典是天花板，不是参考值。** 任何系数链算出的结果都要被
   herb_pharm.dose_max_g 硬钳。系数只能在药典区间内浮动，永不突破。

4. **不确定就不出方。** 证据不足、寒热并重、大毒药、妊娠禁用、
   十八反、肝肾3级、儿童——命中即 BLOCK，返回原因而非返回处方。

5. **默认需要执业中医师签发。** REQUIRE_SIGNOFF=True 时，输出标记为
   "处方建议(待签发)"，不是可直接抓药的处方。

依赖：tcm_kb.sqlite（批次4建表后）
上游：syndrome_weight_engine.evaluate() 的返回值
"""
import sqlite3
import math
import json
from datetime import datetime

VERSION = "dosage_engine/1.0"

# ---------------------------------------------------------------------
# 全局安全配置（上线前由医学负责人确认，不要在代码里随意改）
# ---------------------------------------------------------------------
REQUIRE_SIGNOFF = True          # 输出是否必须经执业中医师签发
MAX_TOTAL_G = 200.0             # 单剂总量上限(g)，超出等比缩放
MIN_DOSE_G = 0.5                # 单味最低有效量，低于此则剔除该药
MAX_HERBS = 18                  # 单方最多味数
TOXIC_CAP_RATIO = 0.7           # 小毒/有毒药封顶为药典上限的比例
PEDIATRIC_AGE = 12              # 低于此年龄强制转人工
GERIATRIC_AGE = 65


def primary_peek(sr):
    """在闸门阶段安全读取主证型"""
    return sr.get("primary")


class Block(Exception):
    """硬闸门：命中即不出方"""
    def __init__(self, code, msg, detail=None):
        self.code, self.msg, self.detail = code, msg, detail or {}
        super().__init__(f"[{code}] {msg}")


# =====================================================================
# 指标 → 剂量修正规则表（批次1的指标等级在这里换算成系数）
# 每条规则独立成行，供中医师/药师校准而不必改代码。
# =====================================================================
LAB_RULES = [
    # (指标名集合, 方向, 作用对象type, 作用对象, 每级系数, 说明)
    ({"ALT", "AST", "谷丙转氨酶", "谷草转氨酶", "总胆红素"}, "high",
     "global_organ", "hepatic", -0.08,
     "转氨酶升高提示肝负荷，全方按级递减并禁用肝毒性药材"),
    ({"肌酐", "尿素氮", "Cr", "BUN", "尿酸"}, "high",
     "global_organ", "renal", -0.08,
     "肾功能指标升高，全方按级递减并禁用肾毒性药材"),
    ({"甘油三酯", "总胆固醇", "低密度脂蛋白", "TG", "TC", "LDL"}, "high",
     "syndrome", "痰湿", +0.10,
     "血脂升高支持痰湿证，化痰祛湿类药加强"),
    ({"血红蛋白", "红细胞", "HGB", "RBC", "血清铁蛋白"}, "low",
     "syndrome", "气血两虚", +0.10,
     "血红蛋白偏低支持血虚，补血药加强"),
    ({"空腹血糖", "糖化血红蛋白", "GLU", "HbA1c"}, "high",
     "syndrome", "阴虚", +0.08,
     "血糖升高常见阴虚燥热，养阴药加强"),
    ({"白细胞", "C反应蛋白", "CRP", "血沉"}, "high",
     "syndrome", "湿热", +0.08,
     "炎症指标升高支持湿热，清热药加强"),
    ({"促甲状腺激素", "TSH"}, "high",
     "syndrome", "阳虚", +0.08,
     "TSH升高提示甲功低下，温阳药加强"),
    ({"血小板", "PLT", "D二聚体", "纤维蛋白原"}, "high",
     "syndrome", "血瘀", +0.08,
     "凝血相关指标异常支持血瘀，活血药加强"),
]

# 角色调幅：证型强度变化时，君药响应最大，使药（调和）几乎不动
ROLE_AMP = {"君": 1.00, "臣": 0.70, "佐": 0.50, "使": 0.20}
ROLE_ORDER = {"君": 0, "臣": 1, "佐": 2, "使": 3}


class DosageEngine:

    def __init__(self, db_path="tcm_kb.sqlite"):
        self.cx = sqlite3.connect(db_path)
        self.cx.row_factory = sqlite3.Row
        self._load()

    # -----------------------------------------------------------------
    def _load(self):
        c = self.cx
        self.pharm = {r["herb"]: dict(r) for r in
                      c.execute("select * from herb_pharm")}
        self.alias = {r["alias"]: r["base"] for r in
                      c.execute("select * from herb_alias")}
        self.food = {r["herb"] for r in c.execute("select herb from food_herb")}
        self.incompat = []
        for r in c.execute("select * from safety_incompat"):
            self.incompat.append(dict(r))
        self.flags = {}
        for r in c.execute("select * from safety_flag"):
            self.flags.setdefault(r["herb"], []).append(dict(r))
        self.formulas = {r["fid"]: dict(r) for r in
                         c.execute("select * from base_formula")}
        self.f_herbs = {}
        for r in c.execute("select * from base_formula_herb order by fid, ord"):
            self.f_herbs.setdefault(r["fid"], []).append(dict(r))
        self.s_map = {}
        for r in c.execute(
                "select * from syndrome_formula_map order by syndrome, priority"):
            self.s_map.setdefault(r["syndrome"], []).append(dict(r))
        self.addon = {}
        for r in c.execute("select * from syndrome_addon"):
            self.addon.setdefault(r["syndrome"], []).append(dict(r))

    # -----------------------------------------------------------------
    def _p(self, herb):
        """取药典档案，支持炮制名归一"""
        if herb in self.pharm:
            return self.pharm[herb]
        base = self.alias.get(herb)
        if base and base in self.pharm:
            return self.pharm[base]
        return None

    def _herb_flags(self, herb):
        out = list(self.flags.get(herb, []))
        base = self.alias.get(herb)
        if base:
            out += self.flags.get(base, [])
        return out

    # =================================================================
    # 主入口
    # =================================================================
    def prescribe(self, syndrome_result, patient=None, labs=None,
                  tongue=None, symptoms=None):
        patient = patient or {}
        labs = labs or []
        tongue = tongue or {}
        audit_global = []
        warnings = []

        try:
            return self._run(syndrome_result, patient, labs, tongue,
                             symptoms or {}, audit_global, warnings)
        except Block as b:
            return {
                "version": VERSION,
                "status": "BLOCKED",
                "block": {"code": b.code, "reason": b.msg, "detail": b.detail},
                "prescription": [],
                "advice": "本次不生成处方。请携带体检报告至医疗机构面诊，"
                          "由执业中医师当面辨证后开具。",
                "global_audit": audit_global,
                "warnings": warnings,
                "review_required": True,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
            }

    # -----------------------------------------------------------------
    def _run(self, sr, pt, labs, tongue, symptoms, ga, warnings):
        # ---------- 闸门 0：上游辨证是否可用 ----------
        if not sr.get("primary"):
            raise Block("NO_SYNDROME", "辨证证据不足，无法确定主证型",
                        {"flags": sr.get("flags", [])})
        if "cold_heat_conflict" in " ".join(sr.get("flags", [])):
            raise Block("COLD_HEAT_CONFLICT",
                        "寒热证并重，属复杂证候，机器不予组方")

        # ---------- 闸门 1：人群禁忌 ----------
        age = pt.get("age")
        if age is not None and age < PEDIATRIC_AGE:
            raise Block("PEDIATRIC",
                        f"{age}岁属儿童，中药剂量须由儿科中医师按体重个体化制定")
        if pt.get("pregnant"):
            ga.append({"step": "人群", "note": "妊娠状态，启用妊娠禁忌全表"})
            if primary_peek(sr) in ("血瘀",):
                raise Block(
                    "PREGNANCY_BLOOD_STASIS",
                    "妊娠期主证为血瘀，活血化瘀方有致流产风险，"
                    "自动组方一律不予处理，须产科与中医科联合面诊")
        liver = int(pt.get("liver_grade", 0) or 0)
        renal = int(pt.get("renal_grade", 0) or 0)
        if liver >= 3 or renal >= 3:
            raise Block("ORGAN_FAILURE",
                        "肝或肾功能重度异常（3级），中药代谢风险不可控",
                        {"liver_grade": liver, "renal_grade": renal})

        # ---------- 第1步：选基础方 ----------
        primary = sr["primary"]
        pct = sr.get("percent", {})
        fid, fsel_why = self._pick_formula(primary, tongue, symptoms)
        f = self.formulas[fid]
        ga.append({
            "step": "选方",
            "result": f["name"],
            "why": f"主证型「{primary}」占比{pct.get(primary, 0)}%；{fsel_why}",
            "source": f'{f["source_book"]} / {f["src"]}',
        })

        # ---------- 第2步：兼证加味 ----------
        members = []          # [(herb, role, ref_g, origin)]
        for h in self.f_herbs[fid]:
            members.append((h["herb"], h["role"], float(h["ref_g"]),
                            f'基础方《{f["name"]}》{h["role"]}药'))
        co_synd = [s for s in sr["ranked"][1:]
                   if pct.get(s, 0) >= 15 and s != primary]
        exist = {m[0] for m in members}
        for s in co_synd[:2]:
            for a in self.addon.get(s, []):
                if a["herb"] in exist or len(members) >= MAX_HERBS:
                    continue
                members.append((a["herb"], "佐", float(a["ref_g"]),
                                f'兼证「{s}」({pct.get(s,0)}%)加味：{a["note"]}'))
                exist.add(a["herb"])
            ga.append({"step": "加味", "result": s,
                       "why": f'兼证占比{pct.get(s,0)}%≥15%，按加味表加药'})

        # ---------- 第3步：配伍禁忌与人群禁忌筛查 ----------
        members = self._safety_filter(members, pt, ga, warnings)

        # ---------- 第4步：计算全局系数 ----------
        k_syn = self._k_syndrome(pct.get(primary, 0))
        k_body, body_why = self._k_body(pt)
        k_organ, organ_why = self._k_organ(liver, renal, labs)
        lab_syn_boost, lab_notes = self._lab_syndrome_boost(labs)
        ga.append({"step": "全局系数",
                   "k_syndrome": k_syn, "k_body": k_body, "k_organ": k_organ,
                   "why": f"证型强度{k_syn}；{body_why}；{organ_why}"})
        for n in lab_notes:
            ga.append({"step": "指标修正", **n})

        # ---------- 第5步：逐味算克数 ----------
        rx = []
        for herb, role, ref_g, origin in members:
            rx.append(self._one_herb(herb, role, ref_g, origin, primary,
                                     k_syn, k_body, k_organ,
                                     lab_syn_boost, pt, sr))
        rx = [r for r in rx if r["final_g"] >= MIN_DOSE_G]
        if len(rx) < 3:
            raise Block("TOO_FEW_HERBS", "安全筛查后有效药味不足3味，方不成方")

        # 钳位失真上报：系数链算出的值被天花板/地板改写，医师必须知情
        capped = [r["herb"] for r in rx if r["clamp"]["applied"] == "max"]
        floored = [r["herb"] for r in rx
                   if r["clamp"]["applied"] == "min_suppressed"]
        if capped:
            warnings.append(
                f"以下药材计算值已超药典上限被封顶，实际强度低于辨证所需，"
                f"请医师评估是否需换方：{'、'.join(capped)}")
        if floored:
            warnings.append(
                f"以下药材因肝肾/年龄安全折减已低于药典常用量下限，"
                f"疗效可能不足：{'、'.join(floored)}")

        # ---------- 第6步：总量钳位 ----------
        total = sum(r["final_g"] for r in rx)
        if total > MAX_TOTAL_G:
            scale = MAX_TOTAL_G / total
            for r in rx:
                before = r["final_g"]
                r["final_g"] = self._round01(
                    max(MIN_DOSE_G, before * scale), r["clamp"]["max"])
                r["steps"].append({
                    "name": "总量缩放", "factor": round(scale, 3),
                    "why": f"全方{total:.1f}g超单剂上限{MAX_TOTAL_G}g，等比缩放"})
            total = sum(r["final_g"] for r in rx)
            ga.append({"step": "总量钳位", "result": f"{total:.1f}g",
                       "why": f"原{sum(1 for _ in rx)}味合计超限，已等比缩放"})

        rx.sort(key=lambda r: (ROLE_ORDER.get(r["role"], 9), -r["final_g"]))

        # ---------- 第7步：出参 ----------
        need_review = bool(
            REQUIRE_SIGNOFF or sr.get("needs_review") or warnings
            or any(r["flags"] for r in rx))
        return {
            "version": VERSION,
            "status": "OK",
            "base_formula": {"fid": fid, "name": f["name"],
                             "book": f["source_book"],
                             "indication": f["indication"]},
            "syndrome": {"primary": primary,
                         "percent": pct,
                         "co_syndromes": co_synd[:2]},
            "prescription": [
                {"herb": r["herb"], "role": r["role"],
                 "dose_g": r["final_g"],
                 "is_food_herb": r["is_food_herb"],
                 "flags": r["flags"]} for r in rx],
            "total_g": round(total, 1),
            "usage": self._usage_text(pt, rx),
            "warnings": warnings,
            "review_required": need_review,
            "signoff": ("处方建议（待执业中医师签发）"
                        if need_review else "已通过自动校验"),
            "global_audit": ga,
            "herb_audit": rx,
            "disclaimer": (
                "本结果由确定性规则引擎计算，每一味药的克数均可回溯到"
                "《中国药典》剂量区间与教材基准方；但辨证依据来自自助采集数据，"
                "不能替代面诊。用药前须经执业中医师复核。"),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }

    # =================================================================
    # 各步骤实现
    # =================================================================
    def _pick_formula(self, syndrome, tongue, symptoms):
        cands = self.s_map.get(syndrome)
        if not cands:
            raise Block("NO_FORMULA", f"证型「{syndrome}」未配置基础方")
        coat = (tongue or {}).get("coat_thickness", 0) or 0
        greasy = (tongue or {}).get("greasy_index", 0) or 0
        for c in cands:
            cond = c["condition"]
            if cond == "default":
                continue
            if "湿象" in cond and (coat >= 2 or greasy >= 0.5):
                return c["fid"], f'触发条件「{cond}」（苔厚{coat}/腻度{greasy}）'
            if "苔白厚腻" in cond and coat >= 2 and greasy >= 0.5:
                return c["fid"], f'触发条件「{cond}」'
            for k in ("口苦", "潮热盗汗", "失眠健忘心悸", "胀痛"):
                if k in cond and (symptoms or {}).get(k, 0) >= 5:
                    return c["fid"], f'症状「{k}」≥5分，触发「{cond}」'
        dflt = next((c for c in cands if c["condition"] == "default"), cands[0])
        return dflt["fid"], "未触发特异条件，取该证型默认方"

    # -----------------------------------------------------------------
    def _safety_filter(self, members, pt, ga, warnings):
        """禁用药剔除 + 十八反筛查。君臣药命中禁忌 → 直接 BLOCK。"""
        kept = []
        names = {m[0] for m in members}
        liver = int(pt.get("liver_grade", 0) or 0)
        renal = int(pt.get("renal_grade", 0) or 0)
        allergies = set(pt.get("allergies", []) or [])
        age = pt.get("age")

        for herb, role, ref_g, origin in members:
            drop, reason = False, None
            for fl in self._herb_flags(herb):
                k, lv = fl["flag"], fl["level"]
                if k == "banned":
                    raise Block("BANNED_HERB",
                                f"「{herb}」属国家禁用品种：{fl['note']}",
                                {"herb": herb, "src": fl["src"]})
                if k.startswith("toxic_大毒"):
                    drop, reason = True, f"药典标注大毒，自动组方一律不用"
                if k == "pregnancy" and pt.get("pregnant"):
                    if lv == "forbid":
                        drop, reason = True, "妊娠禁用"
                    elif role in ("君", "臣"):
                        # 教材记"慎用"，但无人监督的自动系统不得把慎用药
                        # 放在方剂骨架上给孕妇——一律硬拦，转人工。
                        raise Block(
                            "PREGNANCY_KEY_HERB",
                            f"妊娠期，而基础方{role}药「{herb}」属妊娠慎用药，"
                            f"自动组方不予处理",
                            {"herb": herb, "role": role, "src": fl["src"]})
                    else:
                        drop, reason = True, "妊娠慎用，自动组方一律剔除"
                if k == "hepatic" and liver >= 1:
                    drop, reason = True, f"肝功能异常G{liver}，禁用肝损伤报道品种"
                if k == "renal" and renal >= 1:
                    drop, reason = True, f"肾功能异常G{renal}，禁用肾损伤报道品种"
                if k == "pediatric" and age is not None and age < 18:
                    warnings.append(f"{herb}：未成年人慎用")
            if herb in allergies:
                drop, reason = True, "患者过敏史命中"
            if drop:
                # 方剂完整性：基础方是"有出处"的经方，一旦原方药材被剔除，
                # 剩下的组合既无出处、治法也可能反向（如金匮肾气丸去附桂
                # 就退化成滋阴的六味地黄丸，对阳虚证完全不对）。
                # 因此原方任意一味被剔除即 BLOCK，转人工换方；
                # 只有兼证"加味药"允许被安全剔除。
                if origin.startswith("基础方"):
                    raise Block(
                        "FORMULA_INTEGRITY",
                        f"基础方{role}药「{herb}」因「{reason}」不可用。"
                        f"去掉后方剂失去出处且治法可能改变，"
                        f"自动组方不予降级处理，须医师另行选方",
                        {"herb": herb, "role": role, "reason": reason})
                ga.append({"step": "安全剔除", "result": herb,
                           "why": f"{reason}（加味药，可安全去除）"})
                warnings.append(f"已剔除加味药{herb}（{reason}）")
                continue
            kept.append((herb, role, ref_g, origin))

        # 十八反 / 十九畏
        kn = {m[0] for m in kept}
        for rule in self.incompat:
            a, b = rule["herb_a"], rule["herb_b"]
            if a in kn and b in kn:
                if rule["level"] == "forbid":
                    raise Block("INCOMPATIBLE",
                                f"「{a}」与「{b}」属{rule['kind']}，禁止同方",
                                {"pair": [a, b], "src": rule["src"]})
                warnings.append(f"{a}与{b}属{rule['kind']}，需医师确认后使用")
        return kept

    # -----------------------------------------------------------------
    @staticmethod
    def _k_syndrome(p):
        """主证型占比 → 强度系数。20%→0.80，60%以上→1.20，线性。"""
        norm = max(0.0, min(1.0, (p - 20.0) / 40.0))
        return round(0.80 + 0.40 * norm, 3)

    @staticmethod
    def _k_body(pt):
        w = pt.get("weight_kg")
        age = pt.get("age")
        k = 1.0
        why = []
        if w:
            k *= max(0.70, min(1.30, (w / 60.0) ** 0.75))
            why.append(f"体重{w}kg（按体表面积0.75次幂折算）")
        if age is not None and age >= GERIATRIC_AGE:
            k *= 0.85
            why.append(f"{age}岁属老年，×0.85")
        return round(k, 3), ("；".join(why) or "体型年龄无修正")

    @staticmethod
    def _k_organ(liver, renal, labs):
        k = 1.0
        why = []
        if liver >= 1:
            f = 1.0 - 0.15 * liver
            k = min(k, f)
            why.append(f"肝功G{liver}→×{f:.2f}")
        if renal >= 1:
            f = 1.0 - 0.15 * renal
            k = min(k, f)
            why.append(f"肾功G{renal}→×{f:.2f}")
        return round(k, 3), ("；".join(why) or "肝肾功能无异常，不折减")

    def _lab_syndrome_boost(self, labs):
        boost, notes = {}, []
        for item in labs:
            nm = item.get("name")
            d = item.get("direction")
            g = int(item.get("grade", 0) or 0)
            if not nm or g < 1:
                continue
            for names, direc, typ, target, per, note in LAB_RULES:
                if nm in names and d == direc and typ == "syndrome":
                    inc = per * min(g, 3)
                    boost[target] = boost.get(target, 0.0) + inc
                    notes.append({"lab": f"{nm} {d} G{g}",
                                  "target_syndrome": target,
                                  "delta": round(inc, 3), "why": note})
        return boost, notes

    # -----------------------------------------------------------------
    def _one_herb(self, herb, role, ref_g, origin, primary,
                  k_syn, k_body, k_organ, lab_boost, pt, sr):
        p = self._p(herb)
        steps = []
        flags = []

        # 角色调幅后的证型系数
        amp = ROLE_AMP.get(role, 0.5)
        k_syn_role = 1.0 + (k_syn - 1.0) * amp
        steps.append({"name": "证型强度", "factor": round(k_syn_role, 3),
                      "why": f'主证「{primary}」强度{k_syn}，{role}药调幅{amp}'})

        # 指标对本证型的加成（只作用于主证型对应的方）
        k_lab = 1.0 + lab_boost.get(primary, 0.0) * amp
        if abs(k_lab - 1.0) > 1e-9:
            steps.append({"name": "指标修正", "factor": round(k_lab, 3),
                          "why": f'体检指标支持「{primary}」，按{role}药调幅加成'})

        steps.append({"name": "体型年龄", "factor": k_body, "why": "见全局审计"})
        steps.append({"name": "肝肾折减", "factor": k_organ, "why": "见全局审计"})

        raw = ref_g * k_syn_role * k_lab * k_body * k_organ

        # ------- 药典硬钳位 -------
        if p and p.get("dose_max_g"):
            lo = p.get("dose_min_g") or MIN_DOSE_G
            hi = float(p["dose_max_g"])
            csrc = p["src"]
        else:
            # 无药典区间：保守取基准量 ±30%，并强制标记
            lo, hi = ref_g * 0.7, ref_g * 1.3
            csrc = "无药典区间，按教材基准量±30%保守限幅"
            flags.append("NO_PHARMACOPOEIA_RANGE")

        # 有毒药额外封顶
        tox = (p or {}).get("toxicity", "无")
        if tox in ("小毒", "有毒"):
            hi = min(hi, hi * TOXIC_CAP_RATIO)
            flags.append(f"TOXIC_{tox}")
            steps.append({"name": "毒性封顶", "factor": TOXIC_CAP_RATIO,
                          "why": f"药典标注{tox}，上限压至{hi:.1f}g"})

        # ---- 钳位：上限是硬天花板，下限只是"有效量提示"，绝不反向抬升 ----
        # 安全反转防护：若本味药是被安全系数(肝肾/老年/低体重/低证型强度)
        # 压下来的，下限不得把它抬回去——否则减量逻辑被自己的钳位打败。
        reducing = (k_organ < 1.0 or k_body < 1.0 or k_syn_role < 1.0)
        applied = "none"
        clamped = raw
        if raw > hi:
            clamped, applied = hi, "max"
        elif raw < lo:
            if reducing:
                clamped, applied = max(raw, MIN_DOSE_G), "min_suppressed"
                flags.append("BELOW_PHARM_MIN_BY_SAFETY")
                steps.append({
                    "name": "下限抑制", "factor": 1.0,
                    "why": f"计算值{raw:.2f}g低于药典下限{lo:.1f}g，"
                           f"但系因肝肾/年龄/体重安全折减所致，"
                           f"保留低量并提示医师评估疗效是否足够"})
            else:
                clamped, applied = lo, "min"

        final = self._round01(clamped, hi)
        if p and p.get("external_only"):
            flags.append("EXTERNAL_ONLY")

        return {
            "herb": herb, "role": role,
            "ref_g": ref_g, "origin": origin,
            "steps": steps,
            "raw_g": round(raw, 3),
            "clamp": {"min": round(lo, 1), "max": round(hi, 1),
                      "applied": applied, "source": csrc},
            "final_g": final,
            "toxicity": tox,
            "is_food_herb": herb in self.food,
            "meridian": (p or {}).get("meridian"),
            "nature": (p or {}).get("nature"),
            "flags": flags,
            "trace": (f'{ref_g}g × {round(k_syn_role,3)} × {round(k_lab,3)} '
                      f'× {k_body} × {k_organ} = {round(raw,2)}g '
                      f'→ 钳[{lo:.1f},{hi:.1f}] → {final}g'),
        }

    @staticmethod
    def _round01(v, cap=None):
        """0.1g 取整；贴近上限时向下取整，保证永不越过药典天花板。"""
        r = math.floor(v * 10 + 0.5) / 10.0
        if cap is not None and r > cap:
            r = math.floor(cap * 10) / 10.0
        return round(r, 1)

    @staticmethod
    def _usage_text(pt, rx):
        n = 7
        return {
            "剂数": f"{n}剂",
            "煎法": "冷水浸泡30分钟，武火煮沸后文火煎25分钟，"
                    "取汁；二煎加水再煎20分钟，两煎混合分2次温服。",
            "服法": "每日1剂，早晚饭后30分钟温服。",
            "复诊": f"服完{n}剂后复诊或重新采集舌象与症状评分再评估。",
            "禁忌": "服药期间忌生冷、油腻、辛辣；勿与浓茶同服。",
        }


# =====================================================================
# 自测
# =====================================================================
def _self_test():
    import sys
    eng = DosageEngine(sys.argv[1] if len(sys.argv) > 1 else "tcm_kb.sqlite")

    def show(title, out):
        print("=" * 66)
        print(title)
        print("=" * 66)
        if out["status"] == "BLOCKED":
            print(f'  ✋ BLOCKED [{out["block"]["code"]}] {out["block"]["reason"]}')
            return
        bf = out["base_formula"]
        print(f'  基础方：{bf["name"]}（{bf["book"]}）  '
              f'主证：{out["syndrome"]["primary"]} '
              f'{out["syndrome"]["percent"][out["syndrome"]["primary"]]}%')
        if out["syndrome"]["co_syndromes"]:
            print(f'  兼证加味：{"、".join(out["syndrome"]["co_syndromes"])}')
        print(f'  {"药材":<8}{"角色":<5}{"克数":>7}   {"食药同源":<9}溯源')
        for r in out["herb_audit"]:
            fd = "是" if r["is_food_herb"] else "—"
            print(f'  {r["herb"]:<8}{r["role"]:<5}{r["final_g"]:>6.1f}g   '
                  f'{fd:<9}{r["trace"]}')
        print(f'  合计 {out["total_g"]}g / 剂    {out["signoff"]}')
        if out["warnings"]:
            print("  ⚠ " + "；".join(out["warnings"]))

    # ---- 画像A：肝郁为主，轻度转氨酶升高，女性52kg ----
    srA = {"primary": "肝郁", "ranked": ["肝郁", "脾虚", "痰湿", "血瘀",
                                        "湿热", "阴虚", "阳虚", "气血两虚"],
           "percent": {"肝郁": 46.0, "脾虚": 22.0, "痰湿": 12.0, "血瘀": 8.0,
                       "湿热": 5.0, "阴虚": 4.0, "阳虚": 2.0, "气血两虚": 1.0},
           "flags": [], "needs_review": False}
    show("画像A｜肝郁46%+脾虚22%，ALT轻度升高，女52kg",
         eng.prescribe(srA,
                       patient={"age": 34, "sex": "F", "weight_kg": 52,
                                "liver_grade": 1},
                       labs=[{"name": "ALT", "direction": "high", "grade": 1}],
                       tongue={"coat_thickness": 1, "greasy_index": 0.2},
                       symptoms={"胀痛": 6}))

    # ---- 画像B：痰湿为主，血脂高，男85kg ----
    srB = {"primary": "痰湿", "ranked": ["痰湿", "脾虚", "湿热", "肝郁",
                                        "血瘀", "阳虚", "阴虚", "气血两虚"],
           "percent": {"痰湿": 58.0, "脾虚": 18.0, "湿热": 10.0, "肝郁": 6.0,
                       "血瘀": 4.0, "阳虚": 2.0, "阴虚": 1.0, "气血两虚": 1.0},
           "flags": [], "needs_review": False}
    show("画像B｜痰湿58%，甘油三酯↑G2，男85kg",
         eng.prescribe(srB,
                       patient={"age": 45, "sex": "M", "weight_kg": 85},
                       labs=[{"name": "甘油三酯", "direction": "high",
                              "grade": 2}],
                       tongue={"coat_thickness": 3, "greasy_index": 0.8}))

    # ---- 画像C：血瘀为主 + 妊娠 → 应被拦 ----
    srC = {"primary": "血瘀", "ranked": ["血瘀", "肝郁", "气血两虚", "脾虚",
                                        "痰湿", "湿热", "阴虚", "阳虚"],
           "percent": {"血瘀": 62.0, "肝郁": 15.0, "气血两虚": 10.0,
                       "脾虚": 6.0, "痰湿": 3.0, "湿热": 2.0, "阴虚": 1.0,
                       "阳虚": 1.0},
           "flags": [], "needs_review": False}
    show("画像C｜血瘀62% + 妊娠（预期拦截：桃仁红花为君药且妊娠禁用）",
         eng.prescribe(srC, patient={"age": 29, "sex": "F", "weight_kg": 58,
                                     "pregnant": True}))

    # ---- 画像D：证据不足 → 应被拦 ----
    show("画像D｜辨证证据不足（预期拦截）",
         eng.prescribe({"primary": None, "ranked": [], "percent": {},
                        "flags": ["low_evidence:证据不足"],
                        "needs_review": True}))

    # ---- 画像E：老年 + 肾功2级 → 减量 ----
    srE = {"primary": "阳虚", "ranked": ["阳虚", "脾虚", "痰湿", "血瘀",
                                        "气血两虚", "肝郁", "湿热", "阴虚"],
           "percent": {"阳虚": 51.0, "脾虚": 20.0, "痰湿": 12.0, "血瘀": 8.0,
                       "气血两虚": 5.0, "肝郁": 2.0, "湿热": 1.0, "阴虚": 1.0},
           "flags": [], "needs_review": False}
    show("画像E｜阳虚51%，72岁，肾功G2（预期：附子受毒性封顶+肝肾折减）",
         eng.prescribe(srE,
                       patient={"age": 72, "sex": "M", "weight_kg": 62,
                                "renal_grade": 2},
                       labs=[{"name": "肌酐", "direction": "high",
                              "grade": 2}]))


if __name__ == "__main__":
    _self_test()
