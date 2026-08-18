# -*- coding: utf-8 -*-
"""
consultation_engine.py —— 模块②：双向智能问诊系统
=====================================================================
1. 被动问诊：用户主动回答症状量表（11维度0-10分）
2. 主动随访：按慢病标签 + 配置周期自动推送问卷
3. 输出：结构化症状打分，直接喂批次3证型引擎

自测：python consultation_engine.py
"""
import json
from datetime import datetime, timedelta

VERSION = "0.1.0"

# ===== 三种问诊题型 =====
# type="subjective"      → 五级主观选择，后台映射 0/2/5/7/10
# type="quantifiable"    → 事实量化，自带 options
# type="classification"  → 分类选择（非严重度），自带 options
SYMPTOM_DIMENSIONS = [
    # ---- 睡眠 ----
    {"key": "入睡困难", "label": "入睡困难", "type": "subjective",
     "prompt": "过去 7 天，你入睡困难的情况有多明显？", "category": "睡眠"},
    {"key": "入睡时长", "label": "入睡所需时间", "type": "quantifiable",
     "prompt": "通常需要多久才能入睡？", "category": "睡眠",
     "options": [
         {"label": "≤15 分钟", "value": 0},
         {"label": "16–30 分钟", "value": 2},
         {"label": "31–60 分钟", "value": 5},
         {"label": "1–2 小时", "value": 7},
         {"label": ">2 小时", "value": 10},
     ]},
    {"key": "夜尿多", "label": "夜间起夜", "type": "quantifiable",
     "prompt": "平均每晚起夜几次？", "category": "睡眠",
     "options": [
         {"label": "0 次", "value": 0},
         {"label": "1 次", "value": 2},
         {"label": "2 次", "value": 5},
         {"label": "3 次", "value": 7},
         {"label": "4 次及以上", "value": 10},
     ]},
    # ---- 消化 ----
    {"key": "食欲差", "label": "食欲减退", "type": "subjective",
     "prompt": "过去 7 天，你的食欲减退有多明显？", "category": "消化"},
    {"key": "腹胀", "label": "腹胀", "type": "subjective",
     "prompt": "过去 7 天，你的腹胀感有多明显？", "category": "消化"},
    # ---- 二便 ----
    {"key": "大便性状", "label": "大便情况", "type": "classification",
     "prompt": "最近一周，你的大便更接近哪种情况？", "category": "二便",
     "options": [
         {"label": "正常成形", "value": 0, "maps": {}},
         {"label": "偏稀/不成形", "value": 3, "maps": {"便溏": 5}},
         {"label": "水样泄泻", "value": 7, "maps": {"便溏": 9}},
         {"label": "偏干/费力", "value": 4, "maps": {"便秘": 5}},
         {"label": "干结便秘", "value": 8, "maps": {"便秘": 9}},
         {"label": "时稀时干交替", "value": 5, "maps": {"便溏": 4, "便秘": 4}},
     ]},
    {"key": "尿黄", "label": "小便颜色", "type": "classification",
     "prompt": "最近一周，你的小便颜色更接近？", "category": "二便",
     "options": [
         {"label": "清澈透明", "value": 0, "maps": {}},
         {"label": "淡黄正常", "value": 1, "maps": {}},
         {"label": "深黄", "value": 5, "maps": {"尿黄": 5}},
         {"label": "浓茶色", "value": 8, "maps": {"尿黄": 8}},
         {"label": "偏红/带血", "value": 10, "maps": {"尿黄": 10}},
     ]},
    # ---- 寒热 ----
    {"key": "怕冷", "label": "畏寒怕冷", "type": "subjective",
     "prompt": "过去 7 天，你的畏寒怕冷感觉有多明显？", "category": "寒热"},
    {"key": "怕热", "label": "怕热烦热", "type": "subjective",
     "prompt": "过去 7 天，你的怕热或手足心发热有多明显？", "category": "寒热"},
    # ---- 情志 ----
    {"key": "情绪抑郁", "label": "情绪低落", "type": "subjective",
     "prompt": "过去 7 天，你心情低落或闷闷不乐的程度有多明显？", "category": "情志"},
    {"key": "烦躁易怒", "label": "急躁易怒", "type": "subjective",
     "prompt": "过去 7 天，你急躁、容易发怒的情况有多明显？", "category": "情志"},
    # ---- 体能 ----
    {"key": "疲劳", "label": "疲劳乏力", "type": "subjective",
     "prompt": "过去 7 天，你的疲劳感有多明显？", "category": "体能"},
    # ---- 汗出 ----
    {"key": "自汗", "label": "白天出汗", "type": "subjective",
     "prompt": "过去 7 天，白天不因运动也出汗的情况有多明显？", "category": "汗出"},
    {"key": "盗汗", "label": "夜间盗汗", "type": "subjective",
     "prompt": "过去 7 天，睡后出汗、醒后汗止的情况有多明显？", "category": "汗出"},
    # ---- 疼痛 ----
    {"key": "刺痛固定", "label": "固定刺痛", "type": "subjective",
     "prompt": "过去 7 天，你有固定位置的针刺样疼痛吗？", "category": "疼痛"},
    {"key": "胀痛走窜", "label": "走窜胀痛", "type": "subjective",
     "prompt": "过去 7 天，你有位置不固定的胀痛吗？", "category": "疼痛"},
    # ---- 口味 ----
    {"key": "口苦", "label": "口苦口干", "type": "classification",
     "prompt": "最近一周晨起时，你的口腔感觉更接近？", "category": "口味",
     "options": [
         {"label": "正常", "value": 0, "maps": {}},
         {"label": "口干", "value": 3, "maps": {"口苦": 2}},
         {"label": "口苦", "value": 5, "maps": {"口苦": 6}},
         {"label": "口干且口苦", "value": 7, "maps": {"口苦": 8}},
         {"label": "口中黏腻", "value": 6, "maps": {"口苦": 4}},
     ]},
    # ---- 经期（仅女性） ----
    {"key": "经期血块", "label": "月经血块", "type": "subjective",
     "prompt": "近一周期，经血中出现血块的情况有多明显？", "category": "经期(女)", "sex": "F"},
    {"key": "经量少色淡", "label": "经量稀少", "type": "subjective",
     "prompt": "近一周期，月经量减少或色淡的情况有多明显？", "category": "经期(女)", "sex": "F"},
    {"key": "经前乳胀", "label": "经前乳胀", "type": "subjective",
     "prompt": "经前乳房胀痛不适的感觉有多明显？", "category": "经期(女)", "sex": "F"},
]

# 随访周期配置（按慢病标签）
FOLLOWUP_SCHEDULE = {
    "default":       {"days": [7, 30]},
    "血糖异常":      {"days": [3, 7, 14, 30]},
    "肝功能异常":    {"days": [3, 7, 14]},
    "肾功能异常":    {"days": [3, 7, 14]},
    "血脂异常":      {"days": [7, 30]},
    "甲状腺异常":    {"days": [7, 14, 30]},
    "贫血":          {"days": [7, 14]},
}


class ConsultationEngine:
    """双向问诊引擎"""

    def get_questionnaire(self, sex="M", chronic_tags=None):
        """根据性别返回症状问诊量表（三种题型）"""
        items = [d for d in SYMPTOM_DIMENSIONS
                 if "sex" not in d or d["sex"] == sex]
        return {
            "version": VERSION,
            "dimensions": items,
            "total": len(items),
            "instruction": "请根据过去 7 天的实际情况完成以下问题。"
                           "没有标准答案，选择最符合你的情况即可。",
        }

    def validate_answers(self, answers: dict, sex="M") -> dict:
        """校验用户提交的症状打分"""
        q = self.get_questionnaire(sex)
        valid_keys = {d["key"] for d in q["dimensions"]}
        errors, cleaned = [], {}
        for key, val in answers.items():
            if key not in valid_keys:
                continue
            try:
                v = int(val)
                if not 0 <= v <= 10:
                    errors.append(f"{key}: 分值{v}超出0-10范围")
                    continue
                cleaned[key] = v
            except (ValueError, TypeError):
                errors.append(f"{key}: 非法值{val}")
        missing = valid_keys - set(cleaned)
        return {
            "valid": not errors and not missing,
            "symptoms": cleaned,
            "missing": sorted(missing),
            "errors": errors,
        }

    def compute_risk_weight(self, current: dict, previous: dict = None) -> dict:
        """计算症状加重风险权重（当前 vs 上一次随访）"""
        if not previous:
            return {"delta": {}, "worsened": [], "improved": [],
                    "risk_flag": False}
        delta = {}
        worsened, improved = [], []
        for key in current:
            prev_val = previous.get(key, 0)
            cur_val = current[key]
            d = cur_val - prev_val
            delta[key] = d
            if d >= 3:
                worsened.append({"key": key, "delta": d,
                                 "note": f"{key}加重{d}分，下次调方自动加权修正"})
            elif d <= -3:
                improved.append({"key": key, "delta": d})
        return {
            "delta": delta,
            "worsened": worsened,
            "improved": improved,
            "risk_flag": len(worsened) >= 2,
        }

    def schedule_followup(self, chronic_tags=None, last_followup=None):
        """根据慢病标签生成下次随访时间列表"""
        now = datetime.now()
        base = last_followup or now
        tags = chronic_tags or []
        all_days = set()
        for tag in tags:
            sched = FOLLOWUP_SCHEDULE.get(tag, FOLLOWUP_SCHEDULE["default"])
            all_days.update(sched["days"])
        if not all_days:
            all_days = set(FOLLOWUP_SCHEDULE["default"]["days"])
        return {
            "scheduled": sorted([
                {"date": (base + timedelta(days=d)).strftime("%Y-%m-%d"),
                 "days_from_now": d, "tags": tags}
                for d in all_days
            ], key=lambda x: x["days_from_now"]),
            "chronic_tags": tags,
        }


# ----------------------------------------------------------------------
# 自测
# ----------------------------------------------------------------------
def _self_test():
    eng = ConsultationEngine()

    # 男性量表
    q = eng.get_questionnaire("M")
    male_keys = {d["key"] for d in q["dimensions"]}
    assert "经期血块" not in male_keys, "男性不应有经期维度"
    assert "怕冷" in male_keys

    # 女性量表
    q2 = eng.get_questionnaire("F")
    female_keys = {d["key"] for d in q2["dimensions"]}
    assert "经期血块" in female_keys

    # 校验
    answers = {d["key"]: 5 for d in q["dimensions"]}
    v = eng.validate_answers(answers, "M")
    assert v["valid"], v

    # 症状加重
    prev = {"怕冷": 3, "疲劳": 4, "便溏": 2}
    curr = {"怕冷": 8, "疲劳": 2, "便溏": 6}
    risk = eng.compute_risk_weight(curr, prev)
    assert len(risk["worsened"]) >= 1
    assert risk["risk_flag"] is True

    # 随访调度
    sched = eng.schedule_followup(["血糖异常", "肝功能异常"])
    assert len(sched["scheduled"]) >= 3

    print("=== 模块② 自测全部通过 ===")
    print(f"男性量表: {len(male_keys)} 维度")
    print(f"女性量表: {len(female_keys)} 维度")
    print(f"风险检测: 加重{len(risk['worsened'])}项, 改善{len(risk['improved'])}项")
    print(f"随访计划: {json.dumps(sched['scheduled'][:3], ensure_ascii=False)}")


if __name__ == "__main__":
    _self_test()
