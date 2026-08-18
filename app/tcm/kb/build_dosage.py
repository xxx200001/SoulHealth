# -*- coding: utf-8 -*-
"""
批次4 数据层构建：在 tcm_kb.sqlite 上增建 0.1g 组方引擎所需的 7 张表。

数据来源分三类，血统在每张表的 source 字段里写死，便于溯源与审计：
  [KB]   从既有知识库文本抽取（药典QA / 成方制剂 / 古方图谱）—— 可复现
  [TEXT] 中医教材/药典附录通行内容（十八反十九畏、妊娠禁忌、经典方组成）
         —— 公有领域，但**必须经执业中医师/药师复核**，字段 need_review=1
  [GOV]  国家主管部门目录（药食同源、马兜铃酸禁用品种）
         —— 已置种子数据，**必须核对最新官方公告**，字段 need_review=1

用法：python build_batch4_tables.py [db_path]
"""
import sqlite3
import sys
import re
import json
import statistics
from collections import defaultdict

DB = sys.argv[1] if len(sys.argv) > 1 else "tcm_kb.sqlite"

# ======================================================================
# 0. 建表
# ======================================================================
DDL = """
DROP TABLE IF EXISTS herb_pharm;
CREATE TABLE herb_pharm (
    herb        TEXT PRIMARY KEY,   -- 饮片名（药典正名）
    dose_min_g  REAL,               -- 药典常用量下限（内服煎剂）
    dose_max_g  REAL,               -- 药典常用量上限 ← 硬钳位依据
    dose_raw    TEXT,               -- 原文，供举证
    nature      TEXT,               -- 四气
    flavor      TEXT,               -- 五味（顿号分隔）
    meridian    TEXT,               -- 归经（顿号分隔）
    toxicity    TEXT,               -- 无 / 小毒 / 有毒 / 大毒
    external_only INTEGER DEFAULT 0,-- 1=仅外用，禁止入内服方
    src         TEXT
);

DROP TABLE IF EXISTS herb_ratio;
CREATE TABLE herb_ratio (          -- 成方制剂内部配比统计（相对量，非绝对克数）
    herb TEXT PRIMARY KEY, n_formula INTEGER,
    ratio_p25 REAL, ratio_med REAL, ratio_p75 REAL, src TEXT
);

DROP TABLE IF EXISTS herb_classic_dose;
CREATE TABLE herb_classic_dose (   -- 古方折算克数统计（参考用，不作钳位）
    herb TEXT PRIMARY KEY, n_rx INTEGER,
    g_p25 REAL, g_med REAL, g_p75 REAL, era TEXT, src TEXT
);

DROP TABLE IF EXISTS safety_incompat;
CREATE TABLE safety_incompat (     -- 十八反 / 十九畏 / 现代配伍禁忌
    herb_a TEXT, herb_b TEXT, kind TEXT, level TEXT,
    note TEXT, src TEXT, need_review INTEGER DEFAULT 1
);

DROP TABLE IF EXISTS safety_flag;
CREATE TABLE safety_flag (         -- 单味药风险标记（妊娠/儿童/肝肾/禁用）
    herb TEXT, flag TEXT, level TEXT,
    note TEXT, src TEXT, need_review INTEGER DEFAULT 1
);

DROP TABLE IF EXISTS food_herb;
CREATE TABLE food_herb (           -- 药食同源目录
    herb TEXT PRIMARY KEY, catalog TEXT, src TEXT, need_review INTEGER DEFAULT 1
);

DROP TABLE IF EXISTS base_formula;
CREATE TABLE base_formula (
    fid TEXT PRIMARY KEY, name TEXT, source_book TEXT,
    indication TEXT, note TEXT, src TEXT, need_review INTEGER DEFAULT 1
);

DROP TABLE IF EXISTS base_formula_herb;
CREATE TABLE base_formula_herb (
    fid TEXT, herb TEXT, role TEXT,      -- 君/臣/佐/使
    ref_g REAL,                          -- 教材通行基准量(成人常量)
    ord INTEGER
);

DROP TABLE IF EXISTS syndrome_formula_map;
CREATE TABLE syndrome_formula_map (
    syndrome TEXT, fid TEXT, priority INTEGER, condition TEXT, note TEXT
);

DROP TABLE IF EXISTS syndrome_addon;
CREATE TABLE syndrome_addon (       -- 兼证加味（主方之外按兼证占比加药）
    syndrome TEXT, herb TEXT, role TEXT, ref_g REAL, note TEXT
);
"""


def main():
    cx = sqlite3.connect(DB)
    cx.executescript(DDL)
    cur = cx.cursor()

    # ==================================================================
    # 1. [KB] 从药典QA抽取饮片档案
    #    判定饮片的依据：**只有饮片才有"性味与归经"条目**，中成药没有。
    # ==================================================================
    qa = cur.execute("select query, response from chp_qa").fetchall()

    TOPIC = ("性状|鉴别|用法|用量|怎么用|功能|主治|性味|归经|炮制|"
             "贮藏|含量|检查|浸出物|注意|规格")
    name_re = re.compile(r"([\u4e00-\u9fa5A-Za-z0-9（）()·\-]{1,14}?)的(?:" + TOPIC + ")")

    LEAD = re.compile(
        r"^(?:说一下|讲一下|谈一下|聊一下|概括一下|概括|介绍一下|介绍|"
        r"描述一下|描述|简述一下|简述|简单说说|简单说|详细说说|说说|谈谈|"
        r"请问|如何对|怎么对|如何给|怎么给|如何|怎么|咋|关于|对于|一般)")
    TRAIL = re.compile(r"(?:一般|通常|大致|大概|具体|到底)$")

    def herb_of(q):
        m = name_re.search(q)
        if not m:
            return None
        n = m.group(1)
        for _ in range(4):                      # 前后缀可能叠加，迭代剥离
            n2 = TRAIL.sub("", LEAD.sub("", n))
            if n2 == n:
                break
            n = n2
        return n or None

    prop_qa, dose_qa = {}, {}
    for q, a in qa:
        n = herb_of(q)
        if not n:
            continue
        if "性味" in q or "性、味" in q:
            prop_qa.setdefault(n, a)
        if ("用量" in q or "怎么用" in q or "用法" in q):
            # 同名多条时取含 g 的那条
            if n not in dose_qa or ("g" in a and "g" not in dose_qa[n]):
                dose_qa[n] = a

    # --- 性味归经 + 毒性 解析 -----------------------------------------
    NATURES = ["大热", "大寒", "微温", "微寒", "平", "温", "热", "寒", "凉"]
    prop_re = re.compile(r"归([\u4e00-\u9fa5、]+?)经")

    def parse_prop(a):
        tox = "无"
        for t in ("大毒", "小毒", "有毒"):
            if t in a:
                tox = t
                break
        head = a.split("。")[0]
        nature = next((x for x in NATURES if x in head), None)
        flavor = "、".join(sorted(set(
            re.findall(r"[酸苦甘辛咸淡涩]", head.split("，")[0]))))
        m = prop_re.search(a)
        meridian = m.group(1) if m else None
        return nature, flavor or None, meridian, tox

    # --- 剂量区间解析 --------------------------------------------------
    rng_re = re.compile(r"(\d+(?:\.\d+)?)\s*[~～－—\-]\s*(\d+(?:\.\d+)?)\s*g")
    one_re = re.compile(r"(?<![~～\-])(\d+(?:\.\d+)?)\s*g")

    def parse_dose(a):
        """返回 (min,max,external_only)。取全文所有区间的最小下限/最大上限，
        因为药典常写'煎服3~9g；研末冲服0.5~1g'两种给药途径。"""
        ext = ("外用" in a and not rng_re.search(a) and not one_re.search(a))
        rs = [(float(x), float(y)) for x, y in rng_re.findall(a)]
        if rs:
            return min(r[0] for r in rs), max(r[1] for r in rs), int(ext)
        os_ = [float(x) for x in one_re.findall(a)]
        if os_:
            return min(os_), max(os_), int(ext)
        return None, None, int(ext)

    # 中成药过滤：药典对中成药写"一次x片/粒/g，一日n次"，饮片直接写"3~9g"
    CM_SUFFIX = ("片", "丸", "散", "胶囊", "颗粒", "口服液", "合剂", "糖浆",
                 "酊", "膏", "栓", "注射液", "茶", "露", "锭", "贴", "冲剂",
                 "气雾剂", "喷雾剂", "滴丸", "浸膏", "搽剂", "洗剂", "凝胶",
                 "乳膏", "滴眼液", "涂膜剂", "流浸膏", "煎膏", "口服溶液")
    nmpa_names = {r[0] for r in cur.execute(
        "select product from nmpa_product").fetchall()}
    WHITELIST = {"冰片", "陈皮", "青皮", "桔梗", "血竭", "儿茶", "阿胶",
                 "芒硝", "玄明粉", "石膏", "滑石", "琥珀", "蜂蜜"}

    def is_patent_medicine(name, resp):
        if name in WHITELIST:
            return False
        if name in nmpa_names:
            return True
        if any(name.endswith(s) for s in CM_SUFFIX) and len(name) > 3:
            return True
        return bool(resp and ("一次" in resp or "一日" in resp))

    # 入库范围 = 有性味归经 ∪ 有可解析剂量，二者互补
    all_names = set(prop_qa) | set(dose_qa)
    n_herb = 0
    for name in all_names:
        prop_a = prop_qa.get(name)
        draw = dose_qa.get(name)
        if is_patent_medicine(name, draw):
            draw = None                       # 中成药用量不能当饮片量用
        if prop_a is None and draw is None:
            continue
        if prop_a is None and is_patent_medicine(name, dose_qa.get(name)):
            continue                          # 无性味且是中成药 → 不入饮片库
        nature = flavor = meridian = None
        tox = "无"
        if prop_a:
            nature, flavor, meridian, tox = parse_prop(prop_a)
        dmin = dmax = None
        ext = 0
        if draw:
            dmin, dmax, ext = parse_dose(draw)
        if prop_a is None and dmax is None:
            continue
        cur.execute(
            "insert or replace into herb_pharm values (?,?,?,?,?,?,?,?,?,?)",
            (name, dmin, dmax, draw, nature, flavor, meridian, tox, ext,
             "[KB]05扁仓·中国药典QA(chp_qa)"))
        n_herb += 1

    # ---- 炮制名归一：炙甘草→甘草，法半夏→半夏，供基础方按通名取值 ----
    cur.execute("DROP TABLE IF EXISTS herb_alias")
    cur.execute("CREATE TABLE herb_alias (alias TEXT PRIMARY KEY, "
                "base TEXT, kind TEXT, src TEXT)")
    PROC_PRE = ["炙", "炒", "焦", "煅", "制", "生", "酒", "醋", "盐", "蜜",
                "麸炒", "土炒", "清", "姜", "法", "煨", "漂", "蒸", "熟",
                "миро"]
    PROC_PRE = [p for p in PROC_PRE if p != "миро"]
    known = {r[0] for r in cur.execute("select herb from herb_pharm")}
    alias_rows = []
    for a in list(known):
        for p in sorted(PROC_PRE, key=len, reverse=True):
            if a.startswith(p) and len(a) > len(p) + 1:
                base = a[len(p):]
                alias_rows.append((a, base, "炮制品", "[KB]药典饮片名前缀归一"))
                break
    # 反向：基础方用通名但库里只有炮制品时，把炮制品的值挂到通名下
    by_base = defaultdict(list)
    for a, b, _, _ in alias_rows:
        by_base[b].append(a)
    for base, aliases in by_base.items():
        if base in known:
            continue
        src_h = aliases[0]
        row = cur.execute(
            "select dose_min_g,dose_max_g,dose_raw,nature,flavor,meridian,"
            "toxicity,external_only from herb_pharm where herb=?",
            (src_h,)).fetchone()
        if row:
            cur.execute(
                "insert or replace into herb_pharm values (?,?,?,?,?,?,?,?,?,?)",
                (base, *row, f"[KB]继承自炮制品「{src_h}」，须药师确认生/制品差异"))
            alias_rows.append((src_h, base, "通名继承", "[KB]反向归一"))
            n_herb += 1
    cur.executemany("insert or replace into herb_alias values (?,?,?,?)",
                    alias_rows)

    # ---- 人工补录：KB样本未覆盖但基础方必用的常用药 -------------------
    # 血统独立标记，与[KB]抽取结果区分；缺钳位=安全漏洞，故必须补齐。
    SRC_MAN = "[TEXT]中国药典一部常用量(人工补录，须药师逐条核对)"
    MANUAL_DOSE = {
        "升麻": (3, 10), "木香": (3, 6), "枳壳": (3, 10), "柴胡": (3, 10),
        "生姜": (3, 10), "薏苡仁": (9, 30), "赤芍": (6, 12), "陈皮": (3, 10),
        "党参": (9, 30), "白术": (6, 12), "茯苓": (10, 15), "甘草": (2, 10),
        "当归": (6, 12), "黄芪": (9, 30), "白芍": (6, 15), "川芎": (3, 10),
        "熟地黄": (9, 15), "地黄": (10, 15), "山药": (15, 30),
        "山茱萸": (6, 12), "泽泻": (6, 10), "牡丹皮": (6, 12),
        "半夏": (3, 9), "法半夏": (3, 9), "厚朴": (3, 10), "苍术": (3, 9),
        "黄芩": (3, 10), "栀子": (6, 10), "龙胆": (3, 6), "车前子": (9, 15),
        "通草": (3, 5), "滑石": (10, 20), "淡竹叶": (6, 10),
        "苦杏仁": (5, 10), "豆蔻": (3, 6), "砂仁": (3, 6), "桔梗": (3, 10),
        "白扁豆": (9, 15), "莲子": (6, 15), "知母": (6, 12),
        "黄柏": (3, 12), "肉桂": (1, 5), "附子": (3, 15), "干姜": (3, 10),
        "龙眼肉": (9, 15), "酸枣仁": (10, 15), "远志": (3, 10),
        "桃仁": (5, 10), "红花": (3, 10), "牛膝": (5, 12),
        "竹茹": (5, 10), "枳实": (3, 10), "香附": (6, 10), "郁金": (3, 10),
        "茵陈": (6, 15), "麦冬": (6, 12), "石斛": (6, 12), "杜仲": (6, 10),
        "丹参": (10, 15), "薄荷": (3, 6), "川木通": (3, 6),
    }
    n_man = 0
    for h, (lo, hi) in MANUAL_DOSE.items():
        row = cur.execute("select dose_max_g from herb_pharm where herb=?",
                          (h,)).fetchone()
        if row and row[0] is not None:
            continue                          # KB 已有权威值，不覆盖
        if row:
            cur.execute("update herb_pharm set dose_min_g=?,dose_max_g=?,"
                        "dose_raw=?,src=? where herb=?",
                        (lo, hi, f"{lo}～{hi}g（人工补录）", SRC_MAN, h))
        else:
            cur.execute("insert into herb_pharm values (?,?,?,?,?,?,?,?,?,?)",
                        (h, lo, hi, f"{lo}～{hi}g（人工补录）",
                         None, None, None, "无", 0, SRC_MAN))
        n_man += 1
    print(f"[人工补录] 填补 {n_man} 味常用药剂量区间（血统={SRC_MAN}）")

    # ==================================================================
    # 2. [KB] 成方制剂内部配比（绝对克数是整批投料量，只有比例有意义）
    # ==================================================================
    per_f = defaultdict(list)
    for f, h, g in cur.execute(
            "select formula, herb, grams from chp_formula_herb "
            "where grams is not null and grams > 0").fetchall():
        per_f[f].append((h, g))
    ratios = defaultdict(list)
    for f, items in per_f.items():
        tot = sum(g for _, g in items)
        if tot <= 0 or len(items) < 2:
            continue
        for h, g in items:
            ratios[h].append(g / tot)
    for h, vs in ratios.items():
        if len(vs) < 2:
            continue
        vs.sort()
        cur.execute("insert or replace into herb_ratio values (?,?,?,?,?,?)",
                    (h, len(vs),
                     round(statistics.quantiles(vs, n=4)[0], 4),
                     round(statistics.median(vs), 4),
                     round(statistics.quantiles(vs, n=4)[2], 4),
                     "[KB]05扁仓·药典成方制剂配比"))

    # ==================================================================
    # 3. [KB] 古方剂量折算（dose_convert），仅作参考区间
    # ==================================================================
    conv = {}
    for unit, gmin, gmax, era, note, src in cur.execute(
            "select * from dose_convert").fetchall():
        # 同单位多值时取最保守（最小）换算，避免高估
        key = (unit, era.split("(")[0])
        if key not in conv or gmin < conv[key][0]:
            conv[key] = (gmin, gmax)
    han = {u: v for (u, e), v in conv.items() if "汉" in e}
    mq = {u: v for (u, e), v in conv.items() if "明清" in e}

    book_era = {}
    for f, b in cur.execute("select formula, book from formula_source").fetchall():
        book_era[f] = "汉" if ("伤寒" in (b or "") or "金匮" in (b or "")) else "明清"

    cd = defaultdict(list)
    for pid, herb, qty, unit in cur.execute(
            "select ph.pid, ph.herb, ph.qty, ph.unit from prescription_herb ph "
            "where ph.qty is not null and ph.unit is not null").fetchall():
        fname = cur.execute("select formula from prescription where pid=?",
                            (pid,)).fetchone()
        era = book_era.get(fname[0] if fname else "", "明清")
        tbl = han if era == "汉" else mq
        if unit in ("克", "g", "G"):
            g = qty
        elif unit in tbl:
            g = qty * tbl[unit][0]
        else:
            continue
        # 汉代经方多为一剂三服，折成单次量
        if era == "汉":
            g = g / 3.0
        if 0 < g < 500:
            cd[herb].append((g, era))
    for h, vs in cd.items():
        if len(vs) < 2:
            continue
        gs = sorted(v[0] for v in vs)
        eras = ",".join(sorted(set(v[1] for v in vs)))
        cur.execute("insert or replace into herb_classic_dose values (?,?,?,?,?,?,?)",
                    (h, len(gs),
                     round(statistics.quantiles(gs, n=4)[0], 2),
                     round(statistics.median(gs), 2),
                     round(statistics.quantiles(gs, n=4)[2], 2),
                     eras, "[KB]06方剂图谱+07古今剂量换算(汉方已除以3服)"))

    # ==================================================================
    # 4. [TEXT] 十八反 / 十九畏  —— 中药学教材通行内容，须药师复核
    # ==================================================================
    SRC_T = "[TEXT]中药学教材·十八反十九畏歌诀(须药师复核)"
    fan = {
        "甘草": ["甘遂", "大戟", "海藻", "芫花", "京大戟", "红大戟"],
        "川乌": ["半夏", "瓜蒌", "瓜蒌皮", "瓜蒌子", "天花粉", "川贝母",
                 "浙贝母", "平贝母", "湖北贝母", "伊贝母", "白蔹", "白及"],
        "草乌": ["半夏", "瓜蒌", "瓜蒌皮", "瓜蒌子", "天花粉", "川贝母",
                 "浙贝母", "白蔹", "白及"],
        "附子": ["半夏", "瓜蒌", "瓜蒌皮", "天花粉", "川贝母", "浙贝母",
                 "白蔹", "白及"],
        "藜芦": ["人参", "党参", "太子参", "南沙参", "北沙参", "丹参",
                 "玄参", "苦参", "细辛", "赤芍", "白芍"],
    }
    wei = {
        "硫黄": ["芒硝", "朴硝"], "水银": ["砒霜", "砒石"],
        "狼毒": ["密陀僧"], "巴豆": ["牵牛子"], "丁香": ["郁金"],
        "川乌": ["犀角"], "草乌": ["犀角"], "芒硝": ["三棱"],
        "肉桂": ["赤石脂"], "官桂": ["赤石脂"], "人参": ["五灵脂"],
    }
    inc = []
    for a, bs in fan.items():
        for b in bs:
            inc.append((a, b, "十八反", "forbid",
                        f"{a}反{b}，属十八反，禁止同方配伍", SRC_T))
    for a, bs in wei.items():
        for b in bs:
            inc.append((a, b, "十九畏", "warn",
                        f"{a}畏{b}，属十九畏，原则上不同用", SRC_T))
    # 现代药理配伍禁忌
    SRC_M = "[TEXT]现代中药药理·配伍风险(须药师复核)"
    inc += [("甘草", "甘遂", "现代", "forbid", "甘草与峻下逐水药同用毒性增强", SRC_M)]
    cur.executemany(
        "insert into safety_incompat(herb_a,herb_b,kind,level,note,src) "
        "values (?,?,?,?,?,?)", inc)

    # ==================================================================
    # 5. [TEXT/GOV] 单味药风险标记
    # ==================================================================
    flags = []
    # 5.1 马兜铃酸类——国家药监局明令禁用/严控，硬黑名单
    SRC_AA = "[GOV]马兜铃酸肾毒性禁用品种(须核对NMPA最新公告)"
    for h in ["关木通", "广防己", "青木香", "马兜铃", "天仙藤", "寻骨风"]:
        flags.append((h, "banned", "forbid",
                      "含马兜铃酸，具肾毒性与致癌性，禁止使用；"
                      "木通须用川木通、防己须用粉防己替代", SRC_AA))
    # 5.2 妊娠禁用 / 慎用（中药学教材·妊娠用药禁忌）
    SRC_P = "[TEXT]中药学教材·妊娠用药禁忌(须药师复核)"
    preg_forbid = ["巴豆", "牵牛子", "甘遂", "京大戟", "红大戟", "芫花",
                   "商陆", "斑蝥", "水蛭", "虻虫", "麝香", "干漆",
                   "雄黄", "轻粉", "马钱子", "川乌", "草乌", "三棱", "莪术"]
    preg_caution = ["桃仁", "红花", "牛膝", "大黄", "芒硝", "枳实", "附子",
                    "肉桂", "干姜", "半夏", "天南星", "冬葵子", "薏苡仁",
                    "王不留行", "苏木", "丹皮", "牡丹皮", "赤芍", "泽泻"]
    for h in preg_forbid:
        flags.append((h, "pregnancy", "forbid", "妊娠禁用", SRC_P))
    for h in preg_caution:
        flags.append((h, "pregnancy", "warn", "妊娠慎用", SRC_P))
    # 5.3 肝肾功能异常慎用（现代药理，常见肝肾损伤报道品种）
    SRC_LK = "[TEXT]现代中药安全性文献·肝肾损伤报道品种(须药师复核)"
    hepato = ["何首乌", "制何首乌", "雷公藤", "补骨脂", "苦楝皮", "黄药子",
              "千里光", "土三七", "菊三七", "苍耳子", "川楝子", "五倍子"]
    nephro = ["雷公藤", "斑蝥", "细辛", "苍耳子", "山慈菇", "土荆芥",
              "使君子", "巴豆", "洋金花"]
    for h in hepato:
        flags.append((h, "hepatic", "warn", "有肝损伤报道，肝功能异常者慎用并减量", SRC_LK))
    for h in nephro:
        flags.append((h, "renal", "warn", "有肾损伤报道，肾功能异常者慎用并减量", SRC_LK))
    # 5.4 儿童慎用
    SRC_C = "[TEXT]儿科用药常识(须药师复核)"
    for h in ["附子", "川乌", "草乌", "细辛", "麻黄", "马钱子", "朱砂",
              "雄黄", "轻粉", "洋金花", "半夏", "天南星"]:
        flags.append((h, "pediatric", "warn", "儿童慎用，须专科医师评估", SRC_C))
    # 5.5 从药典档案自动补毒性标记（数据驱动，血统=KB）
    for h, tox in cur.execute(
            "select herb, toxicity from herb_pharm where toxicity!='无'").fetchall():
        lvl = "forbid" if tox == "大毒" else "warn"
        flags.append((h, "toxic_" + tox, lvl,
                      f"药典标注{tox}，须严格控量并由执业医师开具",
                      "[KB]中国药典性味归经条目"))
    cur.executemany(
        "insert into safety_flag(herb,flag,level,note,src) values (?,?,?,?,?)",
        flags)

    # ==================================================================
    # 6. [GOV] 药食同源目录（种子，须核对卫健委最新公告）
    # ==================================================================
    SRC_F = "[GOV]既是食品又是中药材物质目录(种子数据，须核对卫健委最新公告)"
    food = """丁香 八角茴香 刀豆 小茴香 小蓟 山药 山楂 马齿苋 乌梅 木瓜 火麻仁
    代代花 玉竹 甘草 白芷 白果 白扁豆 白扁豆花 龙眼肉 决明子 百合 肉豆蔻 肉桂
    余甘子 佛手 杏仁 沙棘 牡蛎 芡实 花椒 赤小豆 麦芽 昆布 大枣 罗汉果 郁李仁
    金银花 青果 鱼腥草 姜 枳椇子 枸杞子 栀子 砂仁 胖大海 茯苓 香橼 香薷 桃仁
    桑叶 桑葚 桔红 桔梗 益智仁 荷叶 莱菔子 莲子 高良姜 淡竹叶 淡豆豉 菊花 菊苣
    黄芥子 黄精 紫苏 紫苏子 葛根 黑芝麻 黑胡椒 槐花 槐米 蒲公英 蜂蜜 榧子 酸枣仁
    鲜白茅根 鲜芦根 蝮蛇 橘皮 薄荷 薏苡仁 薤白 覆盆子 藿香 当归 山柰 西红花 草果
    姜黄 荜茇 党参 肉苁蓉 铁皮石斛 西洋参 黄芪 灵芝 山茱萸 天麻 杜仲叶 粉葛 布渣叶
    夏枯草 显脉旋覆花 松花粉 油松花粉 独行菜 大麦 桑白皮"""
    cur.executemany("insert or replace into food_herb values (?,?,?,1)",
                    [(h, "既是食品又是中药材的物质目录", SRC_F)
                     for h in food.split()])

    # ==================================================================
    # 7. [TEXT] 经典基础方库（方剂学教材通行组成 + 君臣佐使 + 基准量）
    # ==================================================================
    SRC_R = "[TEXT]方剂学教材通行组成(须中医师复核)"
    F = [
        ("SIJUNZI", "四君子汤", "《太平惠民和剂局方》", "脾气虚：食少便溏、气短乏力",
         [("党参", "君", 9), ("白术", "臣", 9), ("茯苓", "佐", 9), ("甘草", "使", 6)]),
        ("SLBZ", "参苓白术散", "《太平惠民和剂局方》", "脾虚夹湿：便溏、肢倦、食少",
         [("党参", "君", 9), ("白术", "臣", 9), ("茯苓", "臣", 9), ("山药", "臣", 9),
          ("白扁豆", "佐", 9), ("莲子", "佐", 6), ("薏苡仁", "佐", 9),
          ("砂仁", "佐", 3), ("桔梗", "使", 6), ("甘草", "使", 6)]),
        ("BZYQ", "补中益气汤", "《脾胃论》", "脾虚气陷：乏力、脱肛、久泻",
         [("黄芪", "君", 15), ("党参", "臣", 9), ("白术", "臣", 9),
          ("当归", "佐", 6), ("陈皮", "佐", 6), ("升麻", "使", 3),
          ("柴胡", "使", 3), ("甘草", "使", 6)]),
        ("XIAOYAO", "逍遥散", "《太平惠民和剂局方》", "肝郁脾虚：胁痛、月经不调、情志抑郁",
         [("柴胡", "君", 9), ("当归", "臣", 9), ("白芍", "臣", 9),
          ("白术", "佐", 9), ("茯苓", "佐", 9), ("薄荷", "佐", 3),
          ("生姜", "佐", 3), ("甘草", "使", 6)]),
        ("CHSG", "柴胡疏肝散", "《景岳全书》", "肝气郁滞：胁肋胀痛、嗳气",
         [("柴胡", "君", 9), ("香附", "臣", 6), ("川芎", "臣", 6),
          ("陈皮", "佐", 9), ("枳壳", "佐", 6), ("白芍", "佐", 9),
          ("甘草", "使", 3)]),
        ("ERCHEN", "二陈汤", "《太平惠民和剂局方》", "痰湿：痰多色白、胸闷、苔腻",
         [("法半夏", "君", 9), ("陈皮", "臣", 9), ("茯苓", "佐", 9),
          ("甘草", "使", 5)]),
        ("PINGWEI", "平胃散", "《太平惠民和剂局方》", "湿困脾胃：脘腹胀满、苔白厚腻",
         [("苍术", "君", 9), ("厚朴", "臣", 6), ("陈皮", "佐", 6),
          ("甘草", "使", 3)]),
        ("LDXG", "龙胆泻肝汤", "《医方集解》", "肝胆湿热：口苦、胁痛、小便黄赤",
         [("龙胆", "君", 6), ("黄芩", "臣", 9), ("栀子", "臣", 9),
          ("泽泻", "佐", 9), ("川木通", "佐", 6), ("车前子", "佐", 9),
          ("当归", "佐", 3), ("地黄", "佐", 9), ("柴胡", "使", 6),
          ("甘草", "使", 6)]),
        ("SANREN", "三仁汤", "《温病条辨》", "湿热蕴结：身重、胸闷、午后热甚",
         [("苦杏仁", "君", 9), ("豆蔻", "君", 6), ("薏苡仁", "君", 18),
          ("法半夏", "臣", 9), ("厚朴", "臣", 6), ("通草", "佐", 6),
          ("滑石", "佐", 18), ("淡竹叶", "佐", 6)]),
        ("LIUWEI", "六味地黄丸", "《小儿药证直诀》", "肾阴虚：腰膝酸软、盗汗、耳鸣",
         [("熟地黄", "君", 24), ("山茱萸", "臣", 12), ("山药", "臣", 12),
          ("泽泻", "佐", 9), ("牡丹皮", "佐", 9), ("茯苓", "佐", 9)]),
        ("ZHIBAI", "知柏地黄丸", "《医宗金鉴》", "阴虚火旺：潮热盗汗、五心烦热",
         [("熟地黄", "君", 24), ("山茱萸", "臣", 12), ("山药", "臣", 12),
          ("泽泻", "佐", 9), ("牡丹皮", "佐", 9), ("茯苓", "佐", 9),
          ("知母", "臣", 6), ("黄柏", "臣", 6)]),
        ("JGSQ", "金匮肾气丸", "《金匮要略》", "肾阳虚：畏寒肢冷、腰膝冷痛、夜尿多",
         [("熟地黄", "君", 24), ("山茱萸", "臣", 12), ("山药", "臣", 12),
          ("泽泻", "佐", 9), ("牡丹皮", "佐", 9), ("茯苓", "佐", 9),
          ("肉桂", "使", 3), ("附子", "使", 3)]),
        ("LIZHONG", "理中汤", "《伤寒论》", "脾胃虚寒：腹痛喜温、便溏、畏冷",
         [("干姜", "君", 9), ("党参", "臣", 9), ("白术", "佐", 9),
          ("甘草", "使", 9)]),
        ("BAZHEN", "八珍汤", "《瑞竹堂经验方》", "气血两虚：面色无华、乏力、心悸",
         [("党参", "君", 9), ("白术", "臣", 9), ("茯苓", "臣", 9),
          ("当归", "君", 9), ("熟地黄", "臣", 12), ("白芍", "臣", 9),
          ("川芎", "佐", 6), ("甘草", "使", 6)]),
        ("GUIPI", "归脾汤", "《济生方》", "心脾两虚：失眠健忘、心悸、食少",
         [("黄芪", "君", 12), ("党参", "君", 9), ("白术", "臣", 9),
          ("茯苓", "臣", 9), ("当归", "臣", 9), ("龙眼肉", "佐", 9),
          ("酸枣仁", "佐", 9), ("远志", "佐", 6), ("木香", "佐", 6),
          ("甘草", "使", 6)]),
        ("XFZY", "血府逐瘀汤", "《医林改错》", "血瘀：刺痛固定、舌暗有瘀斑、唇暗",
         [("桃仁", "君", 12), ("红花", "君", 9), ("当归", "臣", 9),
          ("川芎", "臣", 6), ("赤芍", "臣", 6), ("地黄", "佐", 9),
          ("牛膝", "佐", 9), ("桔梗", "佐", 5), ("枳壳", "佐", 6),
          ("柴胡", "使", 3), ("甘草", "使", 3)]),
        ("THSW", "桃红四物汤", "《医宗金鉴》", "血虚血瘀：月经不调、痛经",
         [("桃仁", "君", 9), ("红花", "君", 6), ("当归", "臣", 9),
          ("熟地黄", "臣", 12), ("白芍", "佐", 9), ("川芎", "佐", 6)]),
        ("WENDAN", "温胆汤", "《三因极一病证方论》", "痰热内扰：眩晕、失眠、口苦、苔黄腻",
         [("法半夏", "君", 6), ("竹茹", "臣", 6), ("枳实", "臣", 6),
          ("陈皮", "佐", 9), ("茯苓", "佐", 5), ("甘草", "使", 3)]),
    ]
    for fid, name, book, ind, herbs in F:
        cur.execute("insert or replace into base_formula values (?,?,?,?,?,?,1)",
                    (fid, name, book, ind, "", SRC_R))
        for i, (h, role, g) in enumerate(herbs):
            cur.execute("insert into base_formula_herb values (?,?,?,?,?)",
                        (fid, h, role, g, i))

    # 证型 → 基础方
    MAP = [
        ("脾虚", "SIJUNZI", 1, "default", "基础健脾"),
        ("脾虚", "SLBZ", 2, "湿象明显(舌苔腻)", "脾虚夹湿首选"),
        ("脾虚", "BZYQ", 3, "气陷/久泻脱肛", "升提中气"),
        ("肝郁", "XIAOYAO", 1, "default", "肝郁脾虚通用"),
        ("肝郁", "CHSG", 2, "以胀痛为主", "偏理气"),
        ("痰湿", "ERCHEN", 1, "default", "化痰祛湿基础"),
        ("痰湿", "PINGWEI", 2, "苔白厚腻、脘胀", "燥湿运脾"),
        ("湿热", "LDXG", 1, "肝胆湿热(口苦、尿黄)", "苦寒直折，中病即止"),
        ("湿热", "SANREN", 2, "default", "宣畅三焦，较平和"),
        ("阴虚", "LIUWEI", 1, "default", "滋补肾阴"),
        ("阴虚", "ZHIBAI", 2, "虚火明显(潮热盗汗)", "滋阴降火"),
        ("阳虚", "JGSQ", 1, "default", "温补肾阳"),
        ("阳虚", "LIZHONG", 2, "以中焦虚寒为主", "温中散寒"),
        ("气血两虚", "BAZHEN", 1, "default", "气血双补"),
        ("气血两虚", "GUIPI", 2, "失眠健忘心悸", "补益心脾"),
        ("血瘀", "XFZY", 1, "default", "活血化瘀"),
        ("血瘀", "THSW", 2, "妇科/血虚兼瘀", "养血活血"),
    ]
    cur.executemany("insert into syndrome_formula_map values (?,?,?,?,?)", MAP)

    # 兼证加味
    ADD = [
        ("肝郁", "香附", "佐", 6, "疏肝理气"),
        ("肝郁", "郁金", "佐", 6, "行气解郁"),
        ("脾虚", "白术", "佐", 9, "健脾益气"),
        ("脾虚", "山药", "佐", 12, "补脾养胃"),
        ("痰湿", "陈皮", "佐", 6, "理气化痰"),
        ("痰湿", "薏苡仁", "佐", 15, "利湿健脾"),
        ("湿热", "黄芩", "佐", 6, "清热燥湿"),
        ("湿热", "茵陈", "佐", 12, "清利湿热"),
        ("阴虚", "麦冬", "佐", 9, "养阴生津"),
        ("阴虚", "石斛", "佐", 9, "滋阴清热"),
        ("阳虚", "干姜", "佐", 6, "温中散寒"),
        ("阳虚", "杜仲", "佐", 9, "温补肝肾"),
        ("气血两虚", "黄芪", "佐", 12, "补气"),
        ("气血两虚", "当归", "佐", 9, "补血"),
        ("血瘀", "丹参", "佐", 9, "活血化瘀"),
        ("血瘀", "川芎", "佐", 6, "行气活血"),
    ]
    cur.executemany("insert into syndrome_addon values (?,?,?,?,?)", ADD)

    cx.commit()

    # ==================================================================
    # 校验报告
    # ==================================================================
    def one(q):
        return cur.execute(q).fetchone()[0]

    print("=" * 62)
    print("批次4 数据层构建完成")
    print("=" * 62)
    print(f"herb_pharm          {one('select count(*) from herb_pharm'):>6} 味饮片档案")
    print(f"  ├ 有药典剂量区间  {one('select count(*) from herb_pharm where dose_max_g is not null'):>6}")
    print(f"  ├ 有四气          {one('select count(*) from herb_pharm where nature is not null'):>6}")
    print(f"  ├ 有归经          {one('select count(*) from herb_pharm where meridian is not null'):>6}")
    n_tox = one("select count(*) from herb_pharm where toxicity!='无'")
    print(f"  └ 毒性标注非无    {n_tox:>6}")
    print(f"herb_ratio          {one('select count(*) from herb_ratio'):>6} 味成方配比")
    print(f"herb_classic_dose   {one('select count(*) from herb_classic_dose'):>6} 味古方折算")
    print(f"safety_incompat     {one('select count(*) from safety_incompat'):>6} 条配伍禁忌")
    print(f"safety_flag         {one('select count(*) from safety_flag'):>6} 条单味风险标记")
    print(f"food_herb           {one('select count(*) from food_herb'):>6} 味药食同源")
    print(f"base_formula        {one('select count(*) from base_formula'):>6} 首基础方 / "
          f"{one('select count(*) from base_formula_herb')} 条组成")
    print()
    print("【基础方药材的药典剂量覆盖体检】")
    miss = cur.execute(
        "select distinct b.herb from base_formula_herb b "
        "left join herb_pharm p on p.herb=b.herb "
        "where p.dose_max_g is null order by b.herb").fetchall()
    tot = one("select count(distinct herb) from base_formula_herb")
    print(f"  基础方共 {tot} 味药，缺药典剂量区间的 {len(miss)} 味："
          f"{'、'.join(m[0] for m in miss) if miss else '无'}")
    cx.close()


if __name__ == "__main__":
    main()
