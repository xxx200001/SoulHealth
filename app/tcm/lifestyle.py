# -*- coding: utf-8 -*-
"""
lifestyle_advisor.py —— 模块⑧：精准建设性干预方案生成
=====================================================================
规格书要求根据用户体质+指标自动输出：
1. 专属作息养生方案
2. 专属运动方案（痰湿/气虚/阴虚差异化）
3. 饮食宜忌、四季养生建议
4. 情绪疏导、肝郁解压方案

输入：证型权重结果 + 体检指标 + 患者档案
输出：结构化个性化干预方案

自测：python lifestyle_advisor.py
"""
import json
from datetime import datetime

VERSION = "0.1.0"

# 证型→体质调养知识库（教材通行内容，need_review）
LIFESTYLE_KB = {
    "肝郁": {
        "diet_good": ["玫瑰花茶", "佛手", "香橼", "金桔", "绿叶蔬菜", "柑橘类水果",
                       "百合", "莲子"],
        "diet_bad": ["辛辣刺激", "酗酒", "高脂油腻", "浓咖啡（晚间）"],
        "exercise": "推荐有氧舒展运动：散步、太极拳、瑜伽、八段锦。"
                    "重点在「舒展胸胁、调畅气机」，避免竞技性强的剧烈运动",
        "sleep": "建议23:00前入睡（子时肝经当令），保证7-8小时。"
                 "睡前避免看负面新闻或工作邮件。可泡脚15分钟辅助入眠",
        "emotion": "肝郁体质最需情志调摄。建议：①定期社交，倾诉释压；"
                   "②培养音乐、书画等兴趣爱好；③腹式深呼吸练习（4-7-8法）；"
                   "④必要时寻求专业心理咨询",
        "seasonal": {
            "春": "春应肝，宜踏青舒展，食青色蔬菜（菠菜、芹菜）",
            "夏": "心火旺助肝火，宜清淡、避暴怒",
            "秋": "肺金克肝木，宜润燥、保持心情开朗",
            "冬": "阳气内收，宜温和运动、早睡晚起",
        },
    },
    "脾虚": {
        "diet_good": ["山药", "莲子", "薏苡仁", "大枣", "小米粥", "南瓜",
                       "鸡肉", "鲫鱼", "芡实"],
        "diet_bad": ["生冷寒凉（冰饮、刺身）", "甜腻（蛋糕、奶茶）",
                     "肥甘厚味", "过量水果（尤其寒性水果）"],
        "exercise": "推荐温和有氧：散步30分钟/日、八段锦（重点第三势「调理脾胃须单举」）。"
                    "避免大汗淋漓的剧烈运动（耗气伤脾）",
        "sleep": "脾主四肢，午间小憩20分钟有助脾运。"
                 "避免饭后立即躺卧（影响运化）",
        "emotion": "思虑伤脾。建议减少过度思虑，遇事不反复纠结。"
                   "可练习正念冥想，每日10分钟",
        "seasonal": {
            "春": "湿气渐生，宜薏苡仁赤小豆水祛湿",
            "夏": "长夏脾旺，但湿热交蒸最伤脾，忌贪凉",
            "秋": "宜平补，山药莲子粥",
            "冬": "宜温补脾阳，羊肉小米粥",
        },
    },
    "痰湿": {
        "diet_good": ["薏苡仁", "冬瓜", "赤小豆", "陈皮泡水", "荷叶茶",
                       "玉米须茶", "白萝卜"],
        "diet_bad": ["甜食甜饮", "肥肉猪蹄", "啤酒", "油炸食品",
                     "乳酪奶油", "糯米制品"],
        "exercise": "**痰湿体质最需要运动**。推荐中等强度有氧：快走、游泳、骑行，"
                    "每次30-45分钟，每周5次。目标微微出汗（促进水湿代谢），"
                    "但不要大汗导致气脱",
        "sleep": "避免久卧（越躺越湿）。建议早起，不赖床",
        "emotion": "痰湿蒙蔽清阳可致头昏沉。运动本身是最好的「化痰祛湿」情绪疗法",
        "seasonal": {
            "春": "春季湿气重，薏苡仁+茯苓代茶饮",
            "夏": "三伏天祛湿最佳时机，加大运动量",
            "秋": "燥气当令有助化湿，但勿过度进补",
            "冬": "少食膏腴肥甘，保持运动不可中断",
        },
    },
    "湿热": {
        "diet_good": ["绿豆", "冬瓜", "苦瓜", "莲藕", "马齿苋", "金银花茶",
                       "菊花茶", "蒲公英茶"],
        "diet_bad": ["辛辣火锅", "牛羊肉（过食）", "酒精", "油炸烧烤",
                     "芒果榴莲（湿热水果）"],
        "exercise": "有氧运动+拉伸，避免高温环境下运动。游泳尤佳（水性清凉）。"
                    "运动后及时补水",
        "sleep": "湿热扰心易致夜热难眠。室温保持凉爽，寝具选择透气面料",
        "emotion": "湿热上扰易烦躁。建议少接触易引发愤怒的信息源",
        "seasonal": {
            "春": "宜疏风清热",
            "夏": "暑湿最重，避免暴晒，多食清淡",
            "秋": "燥气有助化湿，宜清淡平补",
            "冬": "湿热体质冬令不宜大补（越补越热）",
        },
    },
    "阴虚": {
        "diet_good": ["银耳", "百合", "枸杞", "桑葚", "梨", "甘蔗",
                       "黑芝麻", "蜂蜜", "鸭肉", "甲鱼"],
        "diet_bad": ["辛辣燥热（干锅、麻辣）", "煎炸", "浓酒", "羊肉（过食）",
                     "花椒八角（过量）"],
        "exercise": "推荐柔和运动：太极、瑜伽、散步。避免长时间高强度运动（大汗伤阴）。"
                    "运动时间选早晚凉爽时段",
        "sleep": "阴虚多见五心烦热、盗汗影响睡眠。建议睡前温水泡脚，"
                 "卧室保持凉爽湿润",
        "emotion": "阴虚火旺易焦躁。建议静心养性，可练习冥想或听舒缓音乐",
        "seasonal": {
            "春": "春燥易伤阴，多饮水，食百合银耳",
            "夏": "暑热伤津，西瓜翠衣煮水代茶",
            "秋": "秋燥当令，重点滋阴润燥（梨、蜂蜜）",
            "冬": "宜滋阴填精，忌温燥大补",
        },
    },
    "阳虚": {
        "diet_good": ["生姜", "大枣", "桂圆", "羊肉", "牛肉", "韭菜",
                       "核桃", "板栗", "肉桂粉"],
        "diet_bad": ["冰冷食物（冰淇淋、冷饮）", "生食（刺身、沙拉）",
                     "寒性水果（西瓜、柿子）过量", "绿茶过量"],
        "exercise": "推荐温和运动，以不过度出汗为度。八段锦、慢跑、快走。"
                    "运动时间选上午阳气升发时段。避免冬泳、雨中运动",
        "sleep": "宜早睡（21:30-22:00），保暖。脚底涌泉穴艾灸或热水泡脚",
        "emotion": "阳虚者情绪易低沉。多晒太阳（上午9-10点最佳），有助振奋阳气",
        "seasonal": {
            "春": "阳气始生，宜适度户外活动，助阳升发",
            "夏": "三伏灸/晒背，借天阳温补体阳（冬病夏治）",
            "秋": "阳气收敛，早添衣保暖",
            "冬": "重点温阳，姜枣茶、当归生姜羊肉汤",
        },
    },
    "气血两虚": {
        "diet_good": ["大枣", "龙眼肉", "黑芝麻", "红糖", "阿胶",
                       "乌鸡", "猪肝（适量）", "菠菜"],
        "diet_bad": ["浓茶（妨碍铁吸收）", "生冷", "过度节食", "辛辣耗气"],
        "exercise": "运动量不宜过大。推荐散步、太极、八段锦。"
                    "以微微出汗为度，避免剧烈运动耗气伤血",
        "sleep": "气血两虚者最需充足睡眠。建议每晚7-8小时，可午睡20分钟",
        "emotion": "气血不足者易心悸、健忘、多梦。建议规律作息，培养平和心态",
        "seasonal": {
            "春": "肝血春生，食菠菜、枸杞叶",
            "夏": "暑热耗气，宜西洋参泡水",
            "秋": "宜平补气血，当归炖鸡",
            "冬": "最佳进补季节，阿胶膏、十全大补汤",
        },
    },
    "血瘀": {
        "diet_good": ["山楂", "玫瑰花", "红花（少量泡茶）", "黑木耳",
                       "洋葱", "生姜", "桃仁", "醋"],
        "diet_bad": ["高脂肪食物", "动物内脏过量", "烟酒"],
        "exercise": "运动是「活血化瘀」的最佳非药物手段。推荐每日30-45分钟有氧运动"
                    "（快走、游泳、骑行），促进血液循环。"
                    "久坐者每小时起身活动5分钟",
        "sleep": "血瘀者常伴睡眠不佳。睡前热水泡脚（加红花少许）可促进末梢循环",
        "emotion": "气滞则血瘀，保持情志通畅有助活血。避免生闷气",
        "seasonal": {
            "春": "春季升发，有助血行。加强户外活动",
            "夏": "血行较畅，保持运动",
            "秋": "秋凉血易凝，注意保暖",
            "冬": "冬寒凝血，保暖+运动不可中断，可热敷关节",
        },
    },
}

# 指标相关饮食建议
LAB_DIET = {
    "血脂": {
        "high": {"good": ["深海鱼（omega-3）", "燕麦", "坚果（适量）", "豆制品"],
                 "bad": ["动物内脏", "油炸食品", "奶油蛋糕", "椰子油过量"]},
    },
    "血糖": {
        "high": {"good": ["粗粮杂粮", "绿叶蔬菜", "苦瓜", "低GI水果"],
                 "bad": ["精制糖", "白米白面过量", "含糖饮料", "蜂蜜过量"]},
    },
    "肝功能": {
        "high": {"good": ["护肝蔬菜（西兰花、洋蓟）", "优质蛋白（鱼肉、豆腐）"],
                 "bad": ["酒精（严格戒酒）", "高脂肪食物", "加工食品"]},
    },
}


class LifestyleAdvisor:
    """精准建设性干预方案引擎"""

    def advise(self, syndrome_result, labs=None, patient=None):
        """根据证型+指标+档案生成个性化干预方案"""
        patient = patient or {}
        labs = labs or []
        primary = syndrome_result.get("primary")
        if not primary:
            return {"version": VERSION, "status": "NO_SYNDROME",
                    "note": "证型未确定，无法生成干预方案"}

        pct = syndrome_result.get("percent", {})
        ranked = syndrome_result.get("ranked", [])

        # 获取主证型+次要证型的建议
        kb = LIFESTYLE_KB.get(primary, {})
        co_kbs = []
        for s in ranked[1:3]:
            if pct.get(s, 0) >= 15 and s in LIFESTYLE_KB:
                co_kbs.append((s, LIFESTYLE_KB[s]))

        # 当前季节
        month = datetime.now().month
        season = "春" if 3 <= month <= 5 else "夏" if 6 <= month <= 8 \
            else "秋" if 9 <= month <= 11 else "冬"

        # 饮食方案
        diet = self._build_diet(kb, co_kbs, labs, primary)
        # 运动方案
        exercise = self._build_exercise(kb, co_kbs, patient, primary)
        # 作息方案
        sleep = self._build_sleep(kb, co_kbs, primary)
        # 情绪方案
        emotion = self._build_emotion(kb, co_kbs, primary)
        # 四季养生
        seasonal = kb.get("seasonal", {}).get(season, "")
        for s, ckb in co_kbs:
            extra = ckb.get("seasonal", {}).get(season, "")
            if extra:
                seasonal += f"；兼{s}体质：{extra}"

        return {
            "version": VERSION,
            "status": "OK",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "primary_syndrome": primary,
            "primary_pct": pct.get(primary),
            "diet": diet,
            "exercise": exercise,
            "sleep": sleep,
            "emotion": emotion,
            "seasonal": {"season": season, "advice": seasonal},
            "disclaimer": "以上为基于中医体质辨识的一般性养生建议，"
                          "不替代医嘱。有基础疾病者请遵医嘱调整。",
        }

    def _build_diet(self, kb, co_kbs, labs, primary):
        good = list(kb.get("diet_good", []))
        bad = list(kb.get("diet_bad", []))
        for s, ckb in co_kbs:
            good.extend(ckb.get("diet_good", [])[:3])
            bad.extend(ckb.get("diet_bad", [])[:2])
        # 指标相关
        lab_tips = []
        for lab in labs:
            cat = lab.get("category")
            d = lab.get("direction")
            if cat in LAB_DIET and d in LAB_DIET[cat]:
                good.extend(LAB_DIET[cat][d].get("good", []))
                bad.extend(LAB_DIET[cat][d].get("bad", []))
                lab_tips.append(f"{cat}{d}: 建议多食{LAB_DIET[cat][d]['good'][:2]}")
        # 去重
        good = list(dict.fromkeys(good))
        bad = list(dict.fromkeys(bad))
        return {"recommended": good, "avoid": bad, "lab_specific": lab_tips,
                "principle": f"基于「{primary}」体质的饮食宜忌"}

    def _build_exercise(self, kb, co_kbs, patient, primary):
        main = kb.get("exercise", "")
        extras = [f"兼{s}：{ckb.get('exercise', '')[:40]}" for s, ckb in co_kbs]
        age = patient.get("age")
        note = ""
        if age and age >= 65:
            note = "老年人运动需缓和，避免跌倒风险。建议家人陪同"
        return {"main": main, "co_syndrome_tips": extras,
                "age_note": note, "principle": f"基于「{primary}」体质的运动处方"}

    def _build_sleep(self, kb, co_kbs, primary):
        main = kb.get("sleep", "")
        extras = [f"兼{s}注意：{ckb.get('sleep', '')[:40]}" for s, ckb in co_kbs]
        return {"main": main, "co_syndrome_tips": extras,
                "principle": f"基于「{primary}」体质的作息养生"}

    def _build_emotion(self, kb, co_kbs, primary):
        main = kb.get("emotion", "")
        extras = [f"兼{s}：{ckb.get('emotion', '')[:40]}" for s, ckb in co_kbs]
        return {"main": main, "co_syndrome_tips": extras,
                "principle": f"基于「{primary}」体质的情绪疏导"}

    def render_markdown(self, advice):
        if advice["status"] != "OK":
            return f"# 干预方案未生成\n\n{advice.get('note','')}"
        L = ["# 个人专属健康干预方案", "",
             f"主体质：**{advice['primary_syndrome']}**"
             f"（占比{advice['primary_pct']}%）", ""]

        d = advice["diet"]
        L += ["## 🥗 饮食宜忌", "", f"**{d['principle']}**", "",
              f"**宜食**：{'、'.join(d['recommended'][:10])}", "",
              f"**忌食**：{'、'.join(d['avoid'][:8])}", ""]
        if d["lab_specific"]:
            L += ["**指标相关**："] + [f"- {t}" for t in d["lab_specific"]] + [""]

        e = advice["exercise"]
        L += ["## 🏃 运动方案", "", f"**{e['principle']}**", "", e["main"], ""]
        if e["age_note"]:
            L.append(f"> ⚠️ {e['age_note']}")

        s = advice["sleep"]
        L += ["## 😴 作息养生", "", s["main"], ""]

        em = advice["emotion"]
        L += ["## 🧘 情绪疏导", "", em["main"], ""]

        ss = advice["seasonal"]
        L += [f"## 🌿 当季养生（{ss['season']}季）", "", ss["advice"], ""]

        L += ["---", advice["disclaimer"]]
        return "\n".join(L)


# ----------------------------------------------------------------------
# 自测
# ----------------------------------------------------------------------
def _self_test():
    adv = LifestyleAdvisor()
    sr = {"primary": "肝郁",
          "ranked": ["肝郁", "脾虚", "痰湿", "血瘀", "湿热",
                     "阴虚", "阳虚", "气血两虚"],
          "percent": {"肝郁": 46.0, "脾虚": 22.0, "痰湿": 12.0,
                      "血瘀": 8.0, "湿热": 5.0, "阴虚": 4.0,
                      "阳虚": 2.0, "气血两虚": 1.0}}
    labs = [{"category": "肝功能", "direction": "high"}]
    result = adv.advise(sr, labs=labs, patient={"age": 34})
    assert result["status"] == "OK"
    assert len(result["diet"]["recommended"]) >= 5
    assert len(result["diet"]["avoid"]) >= 3
    assert "太极" in result["exercise"]["main"] or "散步" in result["exercise"]["main"]

    md = adv.render_markdown(result)
    assert "个人专属健康干预方案" in md
    print("=== 模块⑧ 自测全部通过 ===")
    print(f"饮食宜: {result['diet']['recommended'][:5]}")
    print(f"饮食忌: {result['diet']['avoid'][:5]}")
    print(f"Markdown: {len(md)} 字")


if __name__ == "__main__":
    _self_test()
