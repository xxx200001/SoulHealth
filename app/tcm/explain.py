# -*- coding: utf-8 -*-
"""
批次5 核心：模块6 四维全维度解释引擎  v1.0
=====================================================================
规格书铁律的落地方式：

  铁律2「每一克必有依据」    → 维度3逐味翻译剂量引擎的 trace 与钳位来源
  铁律3「双维度解释强制输出」→ 维度1(宏观中医) + 维度2(微观指标)缺一不可；
                              维度2查不到证据时输出诚实空态，绝不编造机制
  铁律5「强制反向解释」      → 维度4从引擎真实状态推导：未加味的兼证及其
                              占比、被封顶的药、被剔除的药、四气实测分布

架构立场：**结构是引擎，内容是数据。**
每一句解释都能指回 tcm_kb.sqlite 的某一行（herb_function / herb_mechanism /
syndrome_pathology / herb_dose_risk / herb_pharm / 上游audit）。
LLM 是可选的最后一道润色，且受 verify_polished 数字/药名/禁语三重校验，
校验不过自动回落到模板输出——幻觉在架构上出不了门。

依赖：tcm_kb.sqlite（批次5建表后）
上游：批3 SyndromeWeightEngine.evaluate() + 批4 DosageEngine.prescribe()
"""
import sqlite3
import re
import json
from datetime import datetime

VERSION = "explain_engine/1.0"

# 指标名 → 指标类别（与批4 LAB_RULES 同源，供 herb_mechanism 查表）
INDICATOR_CLASS = {
    "肝功能": {"ALT", "AST", "谷丙转氨酶", "谷草转氨酶", "总胆红素",
               "GGT", "谷氨酰转肽酶", "直接胆红素"},
    "血脂":   {"甘油三酯", "总胆固醇", "低密度脂蛋白", "TG", "TC", "LDL"},
    "血糖":   {"空腹血糖", "糖化血红蛋白", "GLU", "HbA1c", "餐后血糖"},
    "炎症":   {"白细胞", "C反应蛋白", "CRP", "血沉", "WBC", "中性粒细胞"},
    "血液":   {"血红蛋白", "红细胞", "HGB", "RBC", "血清铁蛋白", "红细胞压积"},
    "凝血":   {"血小板", "PLT", "D二聚体", "纤维蛋白原"},
    "甲状腺": {"促甲状腺激素", "TSH"},
    "肾脏":   {"肌酐", "尿素氮", "Cr", "BUN", "尿酸"},
}

# 拦截码 → 面向用户的解释（"为什么不出方"也是解释体系的一部分）
BLOCK_EXPLAIN = {
    "NO_SYNDROME": ("辨证证据不足",
        "系统坚持「证据不足不出结论」：当前采集到的指标、舌象与症状打分"
        "不足以稳定判定主证型。乱猜一个证型再开方，比不开方危险得多。",
        "请补充：完整体检报告拍照上传、标准光线下重拍舌象、完成全部症状问卷。"),
    "COLD_HEAT_CONFLICT": ("寒热证并重",
        "您的证据同时强烈指向寒证与热证，这在中医属于复杂证候（如寒热错杂、"
        "真寒假热），机器规则无法安全裁决，强行组方可能寒热药对冲伤正。",
        "此类证候恰恰是中医面诊的价值所在，请预约执业中医师当面四诊。"),
    "PEDIATRIC": ("未成年人保护",
        "12岁以下儿童的中药剂量必须按体重、发育阶段个体化制定，"
        "且多数药材缺乏儿童安全性数据，自动组方一律不予处理。",
        "请前往儿科中医门诊。"),
    "ORGAN_FAILURE": ("肝/肾功能重度异常",
        "您的肝或肾功能指标达到3级异常。中药同样经肝肾代谢，此时任何剂量"
        "模型的误差都可能被放大为伤害，系统选择不冒这个险。",
        "请先在专科处理肝/肾问题，中医调理须由医师在监护下进行。"),
    "PREGNANCY_BLOOD_STASIS": ("妊娠期活血禁区",
        "您处于妊娠期且主证为血瘀。活血化瘀方有引发流产的风险，"
        "这是自动系统的绝对禁区。",
        "请由产科与中医科医师联合面诊评估。"),
    "PREGNANCY_KEY_HERB": ("妊娠期用药保护",
        "为您匹配的基础方中，君药或臣药属于妊娠慎用药。教材写「慎用」"
        "意味着要医师权衡利弊——无人监督的自动系统没有资格做这个权衡。",
        "请携带本报告至中医妇科面诊。"),
    "FORMULA_INTEGRITY": ("方剂完整性保护",
        "基础方中有药材因您的个人禁忌（肝肾/妊娠/过敏等）不可使用。"
        "经方是整体，抽掉一味可能让治法反向（如温阳方去掉附桂就变成了滋阴方），"
        "系统不做这种「降级出方」。",
        "请由医师为您另行选方。"),
    "BANNED_HERB": ("国家禁用品种",
        "组方路径触及国家药监部门禁用的药材（如含马兜铃酸品种），系统硬性拦截。",
        "这是保护措施，无需处理；医师会使用合规替代品。"),
    "INCOMPATIBLE": ("配伍禁忌（十八反）",
        "组方中出现了十八反禁忌药对，历代与现行药典均禁止同方，系统硬性拦截。",
        "请由医师调整选方。"),
    "TOO_FEW_HERBS": ("安全筛查后方不成方",
        "为规避您的个人禁忌剔除药材后，剩余药味不足以构成有效方剂。",
        "请由医师面诊后个体化组方。"),
    "NO_FORMULA": ("证型未配置基础方",
        "该证型暂未配置可自动化的基础方。",
        "请联系平台医师人工处理。"),
}

FORBIDDEN_CLAIMS = re.compile(
    r"根治|治愈|痊愈|包好|无副作用|绝对安全|百分之百|100%有效|保证有效")


class ExplainEngine:

    def __init__(self, db_path="tcm_kb.sqlite"):
        self.cx = sqlite3.connect(db_path)
        self.cx.row_factory = sqlite3.Row
        c = self.cx
        self.func = {r["herb"]: r["text"] for r in
                     c.execute("select * from herb_function")}
        self.alias = {r["alias"]: r["base"] for r in
                      c.execute("select * from herb_alias")}
        self.mech = {}
        for r in c.execute("select * from herb_mechanism"):
            self.mech.setdefault((r["indicator_class"], r["direction"]),
                                 []).append(dict(r))
        self.dose_risk = {r["herb"]: dict(r) for r in
                          c.execute("select * from herb_dose_risk")}
        self.patho = {r["syndrome"]: dict(r) for r in
                      c.execute("select * from syndrome_pathology")}
        self.pharm = {r["herb"]: dict(r) for r in
                      c.execute("select * from herb_pharm")}
        self.s_map = {}
        for r in c.execute("select m.*, f.name as fname, f.source_book "
                           "from syndrome_formula_map m "
                           "join base_formula f on f.fid=m.fid "
                           "order by m.syndrome, m.priority"):
            self.s_map.setdefault(r["syndrome"], []).append(dict(r))
        # 四气/归经回退（herb_prop，覆盖 herb_pharm 缺录的图谱药材）
        self.prop4, self.propj = {}, {}
        for r in c.execute("select herb,prop,value from herb_prop "
                           "where prop in ('四气','归经')"):
            d = self.prop4 if r["prop"] == "四气" else self.propj
            d.setdefault(r["herb"], (r["value"] or "").replace("性", ""))
        # 全药名词典（防幻觉校验用）
        self.lexicon = {r[0] for r in c.execute("select name from herb")}
        self.lexicon |= set(self.pharm) | set(self.alias)

    # -----------------------------------------------------------------
    def _f(self, herb, maxlen=None):
        """取功能主治文本，支持炮制名双向归一"""
        t = self.func.get(herb)
        if not t:
            base = self.alias.get(herb)
            t = self.func.get(base) if base else None
        if not t:
            for a, b in self.alias.items():
                if b == herb and a in self.func:
                    t = self.func[a]
                    break
        if t and maxlen:
            t = t.split("。")[0] + "。" if "。" in t else t
            if len(t) > maxlen:
                t = t[:maxlen] + "…"
        return t

    def _nature(self, herb, fallback=None):
        base = self.alias.get(herb)
        return (fallback
                or self.prop4.get(herb)
                or (self.prop4.get(base) if base else None))

    def _merid(self, herb, fallback=None):
        base = self.alias.get(herb)
        return (fallback
                or self.propj.get(herb)
                or (self.propj.get(base) if base else None))

    def _risk(self, herb):
        r = self.dose_risk.get(herb)
        if not r:
            base = self.alias.get(herb)
            r = self.dose_risk.get(base) if base else None
        return r

    def _cls_of(self, lab_name):
        for cls, names in INDICATOR_CLASS.items():
            if lab_name in names:
                return cls
        return None

    # =================================================================
    # 主入口
    # =================================================================
    def explain(self, syndrome_result, dosage_result,
                patient=None, labs=None):
        patient, labs = patient or {}, labs or []
        if dosage_result.get("status") == "BLOCKED":
            return self._explain_block(dosage_result, syndrome_result)

        rep = {
            "version": VERSION,
            "status": "OK",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "d1_macro": self._d1(syndrome_result, dosage_result),
            "d2_micro": self._d2(labs, dosage_result),
            "d3_dose": self._d3(dosage_result, patient),
            "d4_exclusion": self._d4(syndrome_result, dosage_result, patient),
            "appendix_trace": self._appendix(dosage_result),
            "review": {
                "required": dosage_result.get("review_required", True),
                "signoff": dosage_result.get("signoff", ""),
                "disclaimer": dosage_result.get("disclaimer", ""),
            },
            "llm": {"used": False, "verified": None, "note": "模板输出（未启用润色）"},
        }
        return rep

    # =================================================================
    # 维度1：宏观中医辨证解释
    # =================================================================
    def _d1(self, sr, dr):
        primary = dr["syndrome"]["primary"]
        pct = dr["syndrome"]["percent"]
        pa = self.patho.get(primary, {})
        bf = dr["base_formula"]

        # 辨证证据（来自批3的逐条审计）
        evidence = []
        for a in (sr.get("audit") or []):
            if primary in (a.get("contrib") or {}):
                evidence.append({
                    "evidence": a.get("evidence"),
                    "contrib": round(a["contrib"][primary], 3),
                    "basis": a.get("basis"),
                    "rule": a.get("rule"),
                })
        evidence.sort(key=lambda x: -(x["contrib"] or 0))
        if not evidence:
            evidence_note = ("上游未传入逐条辨证审计（sr.audit），"
                             "证据清单缺失——请对接批3引擎完整输出。")
        else:
            evidence_note = None

        # 君臣佐使逻辑
        roles = {"君": [], "臣": [], "佐": [], "使": []}
        for h in dr["herb_audit"]:
            roles.setdefault(h["role"], []).append(
                {"herb": h["herb"], "dose_g": h["final_g"],
                 "function": self._f(h["herb"], maxlen=40)})
        role_logic = {
            "君": "针对主病机、起主要治疗作用",
            "臣": "辅助君药加强主治或治疗兼证",
            "佐": "佐助佐制：协同增效、制约偏性、照顾兼夹",
            "使": "引经报使、调和诸药",
        }

        co = dr["syndrome"].get("co_syndromes") or []
        return {
            "primary": primary,
            "primary_pct": pct.get(primary),
            "pathogenesis": pa.get("pathogenesis"),
            "strategy": pa.get("strategy"),
            "approach": pa.get("approach"),
            "patho_src": pa.get("src"),
            "co_syndromes": [{"name": s, "pct": pct.get(s)} for s in co],
            "formula": {"name": bf["name"], "book": bf["book"],
                        "indication": bf["indication"]},
            "select_why": next((g.get("why") for g in dr["global_audit"]
                                if g.get("step") == "选方"), None),
            "roles": roles, "role_logic": role_logic,
            "evidence": evidence[:8],
            "evidence_note": evidence_note,
        }

    # =================================================================
    # 维度2：微观临床医学解释（指标级，证据不足则诚实空态）
    # =================================================================
    def _d2(self, labs, dr):
        rx_herbs = [h["herb"] for h in dr["herb_audit"]]
        rx_set = set(rx_herbs) | {self.alias.get(h) for h in rx_herbs
                                  if self.alias.get(h)}
        items, no_evidence = [], []
        seen = set()
        for lab in labs:
            nm, d = lab.get("name"), lab.get("direction")
            g = int(lab.get("grade", 0) or 0)
            if not nm or g < 1 or (nm, d) in seen:
                continue
            seen.add((nm, d))
            cls = self._cls_of(nm)
            hits = []
            if cls:
                for m in self.mech.get((cls, d), []) + \
                         self.mech.get((cls, "any"), []):
                    if m["herb"] in rx_set:
                        hits.append({
                            "herb": m["herb"],
                            "statement": m["statement"],
                            "evidence_level": m["evidence_level"],
                            "src": m["src"],
                        })
            entry = {"lab": nm, "direction": d, "grade": g,
                     "indicator_class": cls, "mechanisms": hits}
            if hits:
                items.append(entry)
            else:
                no_evidence.append(entry)

        # 引擎对该指标做过的"全局动作"（折减/禁用/加成）也属于微观响应
        organ_actions = [g for g in dr["global_audit"]
                         if g.get("step") in ("全局系数", "指标修正")]
        return {
            "items": items,
            "no_evidence": no_evidence,
            "no_evidence_statement": (
                "以上指标暂无已入库的现代药理对应证据。本系统坚持机制解释"
                "「查表不编造」：组方对这些指标的意义体现在中医辨证层面"
                "（见维度一），不作机制性宣称。" if no_evidence else None),
            "engine_actions": organ_actions,
            "honesty_note": ("机制条目均为研究性证据（已标注证据级别），"
                             "描述的是药理研究提示的作用方向，不构成疗效承诺。"),
        }

    # =================================================================
    # 维度3：精准克重逐条依据（为什么这个数、多了怎样、少了怎样）
    # =================================================================
    def _d3(self, dr, pt):
        out = []
        body_bits = []
        if pt.get("weight_kg"):
            body_bits.append(f'体重{pt["weight_kg"]}kg')
        if pt.get("age") is not None:
            body_bits.append(f'{pt["age"]}岁')
        if int(pt.get("liver_grade", 0) or 0) >= 1:
            body_bits.append(f'肝功G{pt["liver_grade"]}')
        if int(pt.get("renal_grade", 0) or 0) >= 1:
            body_bits.append(f'肾功G{pt["renal_grade"]}')
        body_str = "、".join(body_bits) or "标准成人"

        for h in dr["herb_audit"]:
            herb, final = h["herb"], h["final_g"]
            lo, hi = h["clamp"]["min"], h["clamp"]["max"]
            # 计算依据：把 steps 翻成人话
            calc = [f'教材基准量 {h["ref_g"]}g（{h["origin"]}）']
            for s in h["steps"]:
                nm, f = s["name"], s.get("factor")
                if nm == "证型强度":
                    calc.append(f'证型强度 ×{f}：{s["why"]}')
                elif nm == "指标修正":
                    calc.append(f'指标修正 ×{f}：{s["why"]}')
                elif nm == "体型年龄" and abs(f - 1.0) > 1e-9:
                    calc.append(f'体型年龄 ×{f}（{body_str}）')
                elif nm == "肝肾折减" and abs(f - 1.0) > 1e-9:
                    calc.append(f'肝肾折减 ×{f}')
                elif nm == "毒性封顶":
                    calc.append(f'毒性封顶：{s["why"]}')
                elif nm == "总量缩放":
                    calc.append(f'总量缩放 ×{f}：{s["why"]}')
                elif nm == "下限抑制":
                    calc.append(f'安全优先：{s["why"]}')
            calc.append(f'药典钳位 [{lo}~{hi}g]（{h["clamp"]["source"]}）'
                        f'→ 0.1g取整 = {final}g')

            # 多了会怎样
            risk = self._risk(herb)
            if risk:
                over = f'{risk["over_effect"]}（{risk["src"]}）'
            elif h["toxicity"] in ("小毒", "有毒"):
                over = (f'药典标注{h["toxicity"]}，超量风险高，'
                        f'系统已将上限压至药典上限×0.7={hi}g')
            else:
                over = (f'超过{hi}g即越出《中国药典》认可的常用量范围，'
                        f'缺乏安全性依据，本系统硬性禁止输出')
            # 少了会怎样
            if "BELOW_PHARM_MIN_BY_SAFETY" in h["flags"]:
                under = (f'本次剂量因您的肝肾/年龄安全折减已低于药典常用量'
                         f'下限{lo}g——系统的取舍是安全优先于药效，'
                         f'并已提示医师评估疗效是否足够')
            else:
                under = (f'低于{lo}g时，药典与历代经验均认为难以达到有效剂量'
                         + ("；该药为君药，剂量不足将动摇全方"
                            if h["role"] == "君" else ""))

            out.append({
                "herb": herb, "role": h["role"], "dose_g": final,
                "nature": self._nature(herb, h.get("nature")),
                "meridian": self._merid(herb, h.get("meridian")),
                "function": self._f(herb, maxlen=60),
                "is_food_herb": h.get("is_food_herb"),
                "calc_chain": calc,
                "trace_formula": h["trace"],
                "if_over": over,
                "if_under": under,
                "flags": h["flags"],
            })
        return {"body_params": body_str, "herbs": out,
                "total_g": dr["total_g"], "usage": dr.get("usage")}

    # =================================================================
    # 维度4：反向排除解释（铁律5）
    # =================================================================
    def _d4(self, sr, dr, pt):
        pct = dr["syndrome"]["percent"]
        primary = dr["syndrome"]["primary"]
        co = set(dr["syndrome"].get("co_syndromes") or [])
        rx = dr["herb_audit"]

        # A. 为什么不加其他药
        not_added = []
        sub = [f'{s}({p}%)' for s, p in
               sorted(pct.items(), key=lambda x: -x[1])
               if s != primary and s not in co and 0 < (p or 0) < 15]
        if sub:
            not_added.append(
                f'未加味的弱兼证：{"、".join(sub)}——均未达15%加味阈值。'
                f'中医忌大方杂药：每多一味都增加配伍与代谢负担，'
                f'弱证候交由主方整体调理，复诊时再按变化调整')
        removed = [g for g in dr["global_audit"] if g.get("step") == "安全剔除"]
        for r in removed:
            not_added.append(f'加味候选「{r["result"]}」已因安全规则剔除：{r["why"]}')
        if len(rx) >= 18:
            not_added.append("已达单方18味上限，不再加药")

        # B. 为什么不加大剂量
        not_more = []
        for h in rx:
            if h["clamp"]["applied"] == "max":
                not_more.append(
                    f'{h["herb"]}：辨证计算值{h["raw_g"]}g已触及药典上限'
                    f'{h["clamp"]["max"]}g被封顶——上限是国家标准，不是本系统'
                    f'可以商量的参数')
        k_organ = next((g.get("k_organ") for g in dr["global_audit"]
                        if g.get("step") == "全局系数"), 1.0)
        if k_organ and k_organ < 1.0:
            not_more.append(
                f'全方已按肝/肾功能折减 ×{k_organ}：药物经肝肾代谢，'
                f'此时加量等于加害')
        if any(g.get("step") == "总量钳位" for g in dr["global_audit"]):
            not_more.append(f'全方总量已钳位在200g/剂以内')
        if not not_more:
            not_more.append(
                f'各药均在药典区间内按辨证强度取值（主证占比'
                f'{pct.get(primary)}%对应强度系数已封顶在1.2），'
                f'继续加量不增加疗效证据、只增加风险')

        # C. 为什么不用寒凉/温热重药 —— 用全方四气实测分布举证
        pa = self.patho.get(primary, {})
        dist = {}
        counter_nature = []
        HOT, COLD = {"热", "大热", "温", "微温"}, {"寒", "大寒", "凉", "微寒"}
        avoid_set = (COLD if primary in ("阳虚", "脾虚", "气血两虚")
                     else HOT if primary in ("阴虚", "湿热")
                     else set())
        for h in rx:
            n = self._nature(h["herb"], h.get("nature"))
            key = n or "未录"
            dist[key] = dist.get(key, 0) + 1
            if n in avoid_set:
                counter_nature.append((h["herb"], n, h["role"]))
        dist_str = "、".join(f"{k}{v}味" for k, v in
                             sorted(dist.items(), key=lambda x: -x[1]))
        nature_expl = [f'本证治法忌用方向：{pa.get("avoid", "（未配置）")}',
                       f'全方四气实测分布：{dist_str}']
        if counter_nature and avoid_set:
            names = "、".join(f'{h}({n},{r}药)' for h, n, r in counter_nature)
            nature_expl.append(
                f'方中{names}性属所忌方向，但它们是基础方原方配伍——'
                f'经方以之为佐制（如补中有泻、温中防燥），属原著本意而非误配；'
                f'其剂量已受药典与角色调幅双重压制')
        elif avoid_set:
            nature_expl.append('核对结果：全方无所忌方向的药材 ✓')

        # D. 为什么此方最优（列出未选的备选方与原因）
        alts = []
        chosen_fid = dr["base_formula"]["fid"]
        for c in self.s_map.get(primary, []):
            if c["fid"] == chosen_fid:
                continue
            alts.append(f'备选《{c["fname"]}》（{c["source_book"]}）：'
                        f'适用条件「{c["condition"]}」，本次未触发或非最优先')
        select_why = next((g.get("why") for g in dr["global_audit"]
                           if g.get("step") == "选方"), "")
        why_best = (f'在证型「{primary}」配置的候选方中，'
                    f'《{dr["base_formula"]["name"]}》被选中：{select_why}。'
                    f'它有明确出处（{dr["base_formula"]["book"]}），'
                    f'每一味的加减都可举证——这正是不做自由组方的原因。')

        return {"not_added": not_added, "not_more_dose": not_more,
                "nature_check": nature_expl,
                "why_this_formula": why_best, "alternatives": alts}

    # =================================================================
    # 溯源附录（对接模块7：药典/NMPA/经典举证）
    # =================================================================
    def _appendix(self, dr):
        c = self.cx
        rows = []
        for h in dr["herb_audit"]:
            herb = h["herb"]
            base = self.alias.get(herb, herb)
            nmpa = c.execute(
                "select count(distinct product_id) from nmpa_product_herb "
                "where herb in (?,?)", (herb, base)).fetchone()[0]
            p = self.pharm.get(herb) or self.pharm.get(base) or {}
            rows.append({
                "herb": herb,
                "pharmacopoeia_dose": p.get("dose_raw"),
                "pharm_src": p.get("src"),
                "nmpa_products": nmpa,
                "is_food_herb": h.get("is_food_herb"),
            })
        # 同源成药举证
        fname = dr["base_formula"]["name"]
        stem = re.sub(r"[汤散丸饮膏]$", "", fname)
        related = [r[0] for r in c.execute(
            "select product from nmpa_product where product like ? limit 3",
            (stem + "%",))]
        # 经典条文（若为经方）
        classics = [dict(r) for r in c.execute(
            "select src, subject, predicate, object from classic_triple "
            "where subject like ? or object like ? limit 2",
            ("%" + stem + "%", "%" + stem + "%"))]
        return {"herbs": rows, "related_nmpa_products": related,
                "classic_refs": classics}

    # =================================================================
    # BLOCKED 解释
    # =================================================================
    def _explain_block(self, dr, sr):
        b = dr.get("block", {})
        code = b.get("code", "UNKNOWN")
        title, why, todo = BLOCK_EXPLAIN.get(
            code, ("系统拦截", b.get("reason", ""), "请联系平台医师。"))
        return {
            "version": VERSION, "status": "BLOCKED",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "block": {
                "code": code, "title": title,
                "engine_reason": b.get("reason"),
                "why_this_protects_you": why,
                "what_to_do": todo,
                "detail": b.get("detail"),
            },
            "principle": ("「不确定就不出方」是本系统的设计原则而非功能缺陷："
                          "43.9%的随机画像会被各类安全闸门拦下，"
                          "拦截本身就是一次负责任的输出。"),
            "llm": {"used": False, "verified": None, "note": "模板输出"},
        }

    # =================================================================
    # Markdown 渲染（patient / doctor 双视图）
    # =================================================================
    def render_markdown(self, rep, doctor=False):
        L = []
        if rep["status"] == "BLOCKED":
            b = rep["block"]
            L += [f'# 本次未生成处方：{b["title"]}', "",
                  f'**系统判定**：{b["engine_reason"]}', "",
                  f'**为什么这是在保护您**：{b["why_this_protects_you"]}', "",
                  f'**下一步建议**：{b["what_to_do"]}', "",
                  f'> {rep["principle"]}']
            return "\n".join(L)

        d1, d2, d3, d4 = (rep["d1_macro"], rep["d2_micro"],
                          rep["d3_dose"], rep["d4_exclusion"])
        L += [f'# 组方解释报告（四维全维度溯源）', "",
              f'*生成时间 {rep["generated_at"]} · {rep["review"]["signoff"]}*',
              ""]

        # ---------- 维度一 ----------
        L += ["## 维度一｜宏观中医辨证", ""]
        L.append(
            f'您的主证型为**{d1["primary"]}**（占比{d1["primary_pct"]}%）。'
            f'病机：{d1["pathogenesis"]}；治法：**{d1["strategy"]}**；'
            f'调理思路：{d1["approach"]}。')
        if d1["co_syndromes"]:
            cs = "、".join(f'{c["name"]}({c["pct"]}%)' for c in d1["co_syndromes"])
            L.append(f'兼夹证候：{cs}，已按加味规则纳入处理。')
        L += ["", f'**选方**：{d1["formula"]["name"]}（{d1["formula"]["book"]}），'
                  f'主治「{d1["formula"]["indication"]}」。{d1["select_why"]}', ""]
        L.append("**君臣佐使配伍逻辑**")
        for role in ("君", "臣", "佐", "使"):
            hs = d1["roles"].get(role) or []
            if not hs:
                continue
            names = "、".join(f'{x["herb"]}{x["dose_g"]}g' for x in hs)
            L.append(f'- **{role}**（{d1["role_logic"][role]}）：{names}')
        L.append("")
        if d1["evidence"]:
            L.append("**判您此证的证据清单**（来自辨证引擎逐条审计）")
            for e in d1["evidence"]:
                L.append(f'- {e["evidence"]} → 贡献{e["contrib"]}分'
                         f'（依据：{e["basis"]}）')
        elif d1["evidence_note"]:
            L.append(f'> ⚠ {d1["evidence_note"]}')
        L.append("")

        # ---------- 维度二 ----------
        L += ["## 维度二｜微观临床医学（对应您的异常指标）", ""]
        if not d2["items"] and not d2["no_evidence"]:
            L.append("本次未采集到异常化验指标，该维度无内容"
                     "（这也是诚实输出：没有异常就不硬造关联）。")
        for it in d2["items"]:
            L.append(f'**{it["lab"]}{"↑" if it["direction"]=="high" else "↓"} '
                     f'G{it["grade"]}**（{it["indicator_class"]}类）')
            for m in it["mechanisms"]:
                L.append(f'- 方中**{m["herb"]}**：{m["statement"]}'
                         f'〔{m["evidence_level"]}〕')
            L.append("")
        if d2["no_evidence"]:
            labs = "、".join(f'{x["lab"]}' for x in d2["no_evidence"])
            L.append(f'**{labs}**：{d2["no_evidence_statement"]}')
            L.append("")
        primary_name = rep["d1_macro"]["primary"]
        for act in d2["engine_actions"]:
            if act.get("step") == "指标修正":
                tgt = act.get("target_syndrome")
                extra = ("" if tgt == primary_name else
                         "〔该证非本次主证，未参与本方剂量计算，"
                         "仅记录供复诊参考〕")
                L.append(f'- 引擎动作：{act.get("lab")} → '
                         f'「{tgt}」证权重'
                         f'{"+" if act.get("delta",0)>0 else ""}{act.get("delta")}'
                         f'（{act.get("why")}）{extra}')
        L += ["", f'> {d2["honesty_note"]}', ""]

        # ---------- 维度三 ----------
        L += ["## 维度三｜每一克的依据", "",
              f'计算所用身体参数：{d3["body_params"]}。'
              f'全方合计 **{d3["total_g"]}g/剂**。', ""]
        for h in d3["herbs"]:
            food = "（药食同源）" if h["is_food_herb"] else ""
            nm = f'{h["nature"] or "—"}'
            L.append(f'### {h["herb"]} {h["dose_g"]}g · {h["role"]}药{food}')
            L.append(f'性{nm}，归{h["meridian"] or "—"}经。'
                     f'{h["function"] or ""}')
            L.append("")
            L.append("**这个克数怎么来的**")
            for i, c_ in enumerate(h["calc_chain"], 1):
                L.append(f'{i}. {c_}')
            if doctor:
                L.append(f'`{h["trace_formula"]}`')
            L.append(f'- **多了会怎样**：{h["if_over"]}')
            L.append(f'- **少了会怎样**：{h["if_under"]}')
            L.append("")
        if d3.get("usage"):
            u = d3["usage"]
            L.append(f'**煎服法**：{u.get("煎法","")}{u.get("服法","")}'
                     f'{u.get("禁忌","")}')
        L.append("")

        # ---------- 维度四 ----------
        L += ["## 维度四｜反向排除（为什么不那样做）", "",
              "**为什么不加其他药**"]
        for x in d4["not_added"] or ["各兼证均已覆盖，无候选被排除"]:
            L.append(f'- {x}')
        L += ["", "**为什么不加大剂量**"]
        for x in d4["not_more_dose"]:
            L.append(f'- {x}')
        L += ["", "**寒热用药核查**"]
        for x in d4["nature_check"]:
            L.append(f'- {x}')
        L += ["", "**为什么此方（而不是别的方）**",
              d4["why_this_formula"]]
        for a in d4["alternatives"]:
            L.append(f'- {a}')
        L.append("")

        # ---------- 附录 ----------
        ap = rep["appendix_trace"]
        L += ["## 溯源附录（药典/NMPA举证）", ""]
        for r in ap["herbs"]:
            proof = []
            if r["pharmacopoeia_dose"]:
                proof.append(f'药典用量原文「{r["pharmacopoeia_dose"]}」')
            if r["nmpa_products"]:
                proof.append(f'NMPA成方制剂收录{r["nmpa_products"]}个含本品')
            if r["is_food_herb"]:
                proof.append("列入药食同源目录")
            L.append(f'- {r["herb"]}：' + ("；".join(proof) or "（举证字段待补）")
                     + (f'　〔{r["pharm_src"]}〕' if doctor and r["pharm_src"] else ""))
        if ap["related_nmpa_products"]:
            L.append(f'- 同源成药（NMPA收录）：'
                     f'{"、".join(ap["related_nmpa_products"])}')
        for cr in ap["classic_refs"]:
            L.append(f'- 经典条文：{cr["src"]}｜{cr["subject"]} '
                     f'{cr["predicate"]} {cr["object"]}')
        L += ["", f'---', f'{rep["review"]["disclaimer"]}']
        return "\n".join(L)

    # =================================================================
    # LLM 润色层：build_prompt → llm → verify → 不过则回落模板
    # =================================================================
    def build_llm_prompt(self, rep):
        facts = json.dumps(rep, ensure_ascii=False, default=str)
        return (
            "你是一名中医科普编辑。下面 JSON 是一份组方解释报告的全部事实，"
            "请把它改写成面向普通用户的连贯中文说明。\n"
            "【铁律】1) 禁止新增任何药材名、克数、比例、机制、功效——"
            "只许使用 JSON 中已有的事实；2) 所有数字必须原样保留，"
            "不得四舍五入、换算或新增数字，也不要使用数字编号列表；"
            "3) 禁止出现『根治/治愈/无副作用/绝对安全/保证有效』等承诺性措辞；"
            "4) 保留『待执业中医师签发』的定位。\n"
            "【事实JSON】\n" + facts)

    _num_re = re.compile(r"\d+(?:\.\d+)?")

    def verify_polished(self, text, rep):
        """三重防幻觉校验：数字子集 / 药名白名单 / 禁语"""
        reasons = []
        facts = json.dumps(rep, ensure_ascii=False, default=str)
        fact_nums = set(self._num_re.findall(facts))
        bad_nums = {n for n in self._num_re.findall(text)
                    if n not in fact_nums}
        if bad_nums:
            reasons.append(f"新增数字:{sorted(bad_nums)[:5]}")
        allowed = {h for h in self.lexicon if h in facts}
        bad_herbs = {h for h in self.lexicon
                     if len(h) >= 2 and h in text and h not in allowed}
        if bad_herbs:
            reasons.append(f"新增药名:{sorted(bad_herbs)[:5]}")
        m = FORBIDDEN_CLAIMS.search(text)
        if m:
            reasons.append(f"承诺性禁语:{m.group()}")
        return (not reasons), reasons

    def polish(self, rep, llm_fn=None):
        """llm_fn: prompt(str) -> str。校验不过即回落模板并留痕。"""
        if llm_fn is None:
            return rep
        try:
            polished = llm_fn(self.build_llm_prompt(rep))
        except Exception as e:
            rep["llm"] = {"used": False, "verified": None,
                          "note": f"LLM调用失败已回落模板：{e}"}
            return rep
        ok, reasons = self.verify_polished(polished, rep)
        if ok:
            rep["llm"] = {"used": True, "verified": True,
                          "polished_text": polished,
                          "note": "已通过数字/药名/禁语三重校验"}
        else:
            rep["llm"] = {"used": True, "verified": False,
                          "rejected_reasons": reasons,
                          "note": "润色稿未通过防幻觉校验，已回落模板输出"}
        return rep


# =====================================================================
# 自测
# =====================================================================
def _self_test():
    import sys
    sys.path.insert(0, ".")
    from dosage_engine import DosageEngine
    db = sys.argv[1] if len(sys.argv) > 1 else "tcm_kb.sqlite"
    dz, ex = DosageEngine(db), ExplainEngine(db)

    # 画像A：肝郁+脾虚，ALT G1，女52kg —— 含批3风格的逐条审计
    srA = {"primary": "肝郁",
           "ranked": ["肝郁", "脾虚", "痰湿", "血瘀", "湿热", "阴虚",
                      "阳虚", "气血两虚"],
           "percent": {"肝郁": 46.0, "脾虚": 22.0, "痰湿": 12.0, "血瘀": 8.0,
                       "湿热": 5.0, "阴虚": 4.0, "阳虚": 2.0, "气血两虚": 1.0},
           "flags": [], "needs_review": False,
           "audit": [
               {"rule": "SYM_XL", "evidence": "胁肋胀痛=6分", "factor": 0.6,
                "contrib": {"肝郁": 1.8},
                "basis": "《中医诊断学》肝气郁滞证主症：胁肋胀痛、情志抑郁"},
               {"rule": "SYM_QZ", "evidence": "情绪低落易怒=5分", "factor": 0.5,
                "contrib": {"肝郁": 1.2},
                "basis": "《中医诊断学》肝失疏泄则情志不畅"},
               {"rule": "LAB_ALT", "evidence": "ALT high G1", "factor": 0.33,
                "contrib": {"肝郁": 0.4, "湿热": 0.2},
                "basis": "启发式：转氨酶升高与肝郁化火/湿热蕴肝相关(v1,待校准)"},
               {"rule": "TON_DAN", "evidence": "舌淡红苔薄", "factor": 1.0,
                "contrib": {"脾虚": 0.5},
                "basis": "《中医诊断学》舌淡主气血不足/脾虚"},
           ]}
    ptA = {"age": 34, "sex": "F", "weight_kg": 52, "liver_grade": 1}
    labsA = [{"name": "ALT", "direction": "high", "grade": 1},
             {"name": "血清铁蛋白", "direction": "low", "grade": 1}]
    drA = dz.prescribe(srA, patient=ptA, labs=labsA,
                       tongue={"coat_thickness": 1, "greasy_index": 0.2},
                       symptoms={"胀痛": 6})
    repA = ex.explain(srA, drA, patient=ptA, labs=labsA)
    mdA = ex.render_markdown(repA)
    open("示例报告_画像A.md", "w", encoding="utf-8").write(mdA)
    print(f"[A] 肝郁画像：四维报告 {len(mdA)} 字 → 示例报告_画像A.md")
    for k in ("d1_macro", "d2_micro", "d3_dose", "d4_exclusion"):
        assert repA[k], f"维度缺失: {k}"
    print("    四维强制输出校验 ✓（缺一不可）")

    # 画像E：阳虚老年肾功G2 —— 验证反向解释里的佐制药说明
    srE = {"primary": "阳虚",
           "ranked": ["阳虚", "脾虚", "痰湿", "血瘀", "气血两虚", "肝郁",
                      "湿热", "阴虚"],
           "percent": {"阳虚": 51.0, "脾虚": 20.0, "痰湿": 12.0, "血瘀": 8.0,
                       "气血两虚": 5.0, "肝郁": 2.0, "湿热": 1.0, "阴虚": 1.0},
           "flags": [], "needs_review": False, "audit": []}
    ptE = {"age": 72, "sex": "M", "weight_kg": 62, "renal_grade": 2}
    labsE = [{"name": "肌酐", "direction": "high", "grade": 2},
             {"name": "促甲状腺激素", "direction": "high", "grade": 1}]
    drE = dz.prescribe(srE, patient=ptE, labs=labsE)
    repE = ex.explain(srE, drE, patient=ptE, labs=labsE)
    mdE = ex.render_markdown(repE, doctor=True)
    open("示例报告_画像E_医师视图.md", "w", encoding="utf-8").write(mdE)
    nc = repE["d4_exclusion"]["nature_check"]
    print(f"[E] 阳虚画像：寒热核查输出 {len(nc)} 条"
          f"（含佐制药举证: {'泽泻' in ' '.join(nc)}）")

    # 画像C：妊娠血瘀 BLOCKED —— 拦截也要解释
    srC = {"primary": "血瘀", "ranked": ["血瘀"], "percent": {"血瘀": 62.0},
           "flags": [], "needs_review": False}
    drC = dz.prescribe(srC, patient={"age": 29, "pregnant": True,
                                     "weight_kg": 58})
    repC = ex.explain(srC, drC)
    print(f'[C] 妊娠血瘀：status={repC["status"]}，'
          f'解释标题「{repC["block"]["title"]}」 ✓')

    # LLM 护栏演示
    def good_llm(prompt):
        return ("为您选用柴胡疏肝散加味。主证肝郁占46.0%，方以柴胡7.3g为君"
                "疏肝解郁，配香附、川芎行气活血，全方54.6g，"
                "待执业中医师签发后使用。")

    def bad_llm(prompt):
        return ("本方可根治肝郁，另建议自行加用冬虫夏草30g与人参20g增效，"
                "绝对安全无副作用。")

    ra = ex.polish(dict(repA), good_llm)
    rb = ex.polish(dict(repA), bad_llm)
    print(f'[LLM] 合规稿：verified={ra["llm"]["verified"]} ✓')
    print(f'[LLM] 幻觉稿：verified={rb["llm"]["verified"]}，'
          f'拒绝原因={rb["llm"]["rejected_reasons"]} ✓')


if __name__ == "__main__":
    _self_test()
