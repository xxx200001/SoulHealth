# -*- coding: utf-8 -*-
"""
批次5 数据层：模块6解释引擎的证据表（4张）。

铁律：解释引擎的每一句话都必须能指回一行数据。LLM 只许润色，不许添加事实。
因此机制类文案先入库、标证据级别、标 need_review，引擎只做"查表拼装"。

  herb_function      [KB]   饮片功能主治（从药典QA自动抽取，可复现）
  herb_mechanism     [TEXT] 药材→指标类别→现代药理机制（人工精选，须复核）
  herb_dose_risk     [TEXT] 超量风险知识（"多了会怎样"的依据）
  syndrome_pathology [TEXT] 八证型病机/治法/调理思路/忌用方向

用法：python build_explain_tables.py [db_path]
"""
import sqlite3
import sys
import re

DB = sys.argv[1] if len(sys.argv) > 1 else "tcm_kb.sqlite"

DDL = """
DROP TABLE IF EXISTS herb_function;
CREATE TABLE herb_function (
    herb TEXT PRIMARY KEY, text TEXT, src TEXT
);
DROP TABLE IF EXISTS herb_mechanism;
CREATE TABLE herb_mechanism (
    herb TEXT, indicator_class TEXT, direction TEXT,   -- high/low/any
    statement TEXT,
    evidence_level TEXT,      -- 临床研究 / 药理研究 / 传统经验
    src TEXT, need_review INTEGER DEFAULT 1
);
DROP TABLE IF EXISTS herb_dose_risk;
CREATE TABLE herb_dose_risk (
    herb TEXT PRIMARY KEY, over_effect TEXT, src TEXT,
    need_review INTEGER DEFAULT 1
);
DROP TABLE IF EXISTS syndrome_pathology;
CREATE TABLE syndrome_pathology (
    syndrome TEXT PRIMARY KEY,
    pathogenesis TEXT,        -- 病机
    strategy TEXT,            -- 治法
    approach TEXT,            -- 整体调理思路
    avoid TEXT,               -- 忌用方向（反向解释的依据）
    src TEXT, need_review INTEGER DEFAULT 1
);
"""


def main():
    cx = sqlite3.connect(DB)
    cx.executescript(DDL)
    cur = cx.cursor()

    # ==================================================================
    # 1. [KB] herb_function：饮片功能主治，从 chp_qa 抽取
    #    只收 herb_pharm/herb_alias 认得的名字，天然排除中成药。
    # ==================================================================
    known = {r[0] for r in cur.execute("select herb from herb_pharm")}
    alias = {r[0]: r[1] for r in cur.execute("select alias, base from herb_alias")}

    TOPIC = ("性状|鉴别|用法|用量|怎么用|功能|主治|性味|归经|炮制|"
             "贮藏|含量|检查|浸出物|注意|规格")
    name_re = re.compile(
        r"([\u4e00-\u9fa5A-Za-z0-9（）()·\-]{1,14}?)的(?:" + TOPIC + ")")
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
        for _ in range(4):
            n2 = TRAIL.sub("", LEAD.sub("", n))
            if n2 == n:
                break
            n = n2
        return n or None

    best = {}
    for q, a in cur.execute("select query, response from chp_qa"):
        if "功能" not in q and "主治" not in q:
            continue
        n = herb_of(q)
        if not n:
            continue
        if n not in known and alias.get(n) not in known:
            continue
        if n not in best or len(a) > len(best[n]):
            best[n] = a
    cur.executemany(
        "insert or replace into herb_function values (?,?,?)",
        [(h, t.strip(), "[KB]05扁仓·中国药典QA功能主治条目")
         for h, t in best.items()])

    # ==================================================================
    # 2. [TEXT] herb_mechanism：指标级现代药理证据（人工精选种子）
    #    措辞纪律：只写"研究提示/显示"，不写"能治/修复/根治"。
    #    每条 need_review=1，上线展示前须逐条补文献编号。
    # ==================================================================
    S_M = "[TEXT]现代中药药理研究综述(须逐条补文献并经医师复核后方可展示)"
    M = [
        # ---- 肝功能（ALT/AST/胆红素 偏高）----
        ("柴胡", "肝功能", "high",
         "柴胡皂苷在动物与细胞实验中显示抗肝损伤、减轻转氨酶升高的作用", "药理研究"),
        ("白芍", "肝功能", "high",
         "白芍总苷具有抗炎与保肝作用，其制剂已在临床用于免疫相关肝损的辅助治疗", "临床研究"),
        ("甘草", "肝功能", "high",
         "甘草酸类制剂在临床用于慢性肝炎辅助降酶", "临床研究"),
        ("茵陈", "肝功能", "high",
         "茵陈有利胆退黄作用，临床用于黄疸型肝病的辅助治疗", "临床研究"),
        ("栀子", "肝功能", "high",
         "栀子苷在药理研究中显示利胆、降低胆红素的作用", "药理研究"),
        ("郁金", "肝功能", "high",
         "郁金有促进胆汁分泌与保肝的药理研究报道", "药理研究"),
        ("丹参", "肝功能", "high",
         "丹参在药理与临床研究中显示抗肝纤维化倾向", "药理研究"),
        # ---- 血脂（TG/TC/LDL 偏高）----
        ("泽泻", "血脂", "high",
         "泽泻醇类成分在药理研究中显示调节血脂的作用", "药理研究"),
        ("陈皮", "血脂", "high",
         "陈皮所含橙皮苷类黄酮有调脂、抗氧化的药理研究报道", "药理研究"),
        ("薏苡仁", "血脂", "high",
         "薏苡仁有调节脂代谢的药理研究报道", "药理研究"),
        ("山楂", "血脂", "high",
         "山楂黄酮类成分调节血脂的证据较充分，相关制剂有临床应用", "临床研究"),
        ("苍术", "血脂", "high",
         "苍术挥发油与多糖有改善脂代谢的药理研究报道", "药理研究"),
        # ---- 血糖（GLU/HbA1c 偏高）----
        ("山药", "血糖", "high",
         "山药多糖在动物实验中显示降血糖作用", "药理研究"),
        ("黄芪", "血糖", "high",
         "黄芪多糖有改善胰岛素抵抗的药理研究报道", "药理研究"),
        ("麦冬", "血糖", "high",
         "麦冬多糖在药理研究中显示降糖作用", "药理研究"),
        ("知母", "血糖", "high",
         "知母皂苷有改善胰岛素敏感性的药理研究报道", "药理研究"),
        ("石斛", "血糖", "high",
         "石斛多糖在药理研究中显示降糖与保护胰岛的作用", "药理研究"),
        # ---- 炎症（CRP/白细胞/血沉 偏高）----
        ("黄芩", "炎症", "high",
         "黄芩苷抗炎、抑制炎症因子释放的证据较充分，有临床制剂应用", "临床研究"),
        ("栀子", "炎症", "high",
         "栀子提取物在药理研究中显示抗炎作用", "药理研究"),
        ("黄柏", "炎症", "high",
         "黄柏所含小檗碱类成分有抗炎、抗菌的药理作用", "药理研究"),
        ("甘草", "炎症", "high",
         "甘草酸有抗炎的药理作用", "药理研究"),
        ("龙胆", "炎症", "high",
         "龙胆苦苷在药理研究中显示抗炎作用", "药理研究"),
        ("牡丹皮", "炎症", "high",
         "丹皮酚有抗炎的药理研究报道", "药理研究"),
        ("蒲公英", "炎症", "high",
         "蒲公英提取物有抗炎、抗菌的药理研究报道", "药理研究"),
        # ---- 血液（HGB/RBC 偏低）----
        ("当归", "血液", "low",
         "当归多糖在药理研究中显示促进造血的作用；当归补血汤有长期临床应用史", "药理研究"),
        ("黄芪", "血液", "low",
         "黄芪有促进骨髓造血的药理研究报道", "药理研究"),
        ("熟地黄", "血液", "low",
         "熟地黄在药理研究中显示促进造血、改善血虚模型指标的作用", "药理研究"),
        ("龙眼肉", "血液", "low",
         "龙眼肉为传统补血食药，现代机制证据有限", "传统经验"),
        ("阿胶", "血液", "low",
         "阿胶促进造血的证据较充分，相关制剂有临床应用", "临床研究"),
        # ---- 凝血/血瘀（PLT/D二聚体/纤维蛋白原 偏高）----
        ("丹参", "凝血", "high",
         "丹参酮与丹酚酸有抗血小板聚集、改善微循环的作用，临床制剂应用广泛", "临床研究"),
        ("川芎", "凝血", "high",
         "川芎嗪有改善微循环、抗血小板聚集的作用，有临床制剂应用", "临床研究"),
        ("桃仁", "凝血", "high",
         "桃仁提取物在药理研究中显示抗凝、抗血栓作用", "药理研究"),
        ("红花", "凝血", "high",
         "红花黄色素改善微循环的证据较充分，有临床注射制剂", "临床研究"),
        ("赤芍", "凝血", "high",
         "赤芍总苷有抗血栓的药理研究报道", "药理研究"),
        # ---- 甲状腺（TSH 偏高，提示甲功低下）----
        ("附子", "甲状腺", "high",
         "附子在动物实验中显示提高基础代谢、改善甲状腺功能低下模型指标的作用", "药理研究"),
        ("肉桂", "甲状腺", "high",
         "桂皮醛有促进代谢与改善外周循环的药理研究报道", "药理研究"),
        # ---- 肾脏（肌酐/尿素氮/尿酸 偏高）----
        ("车前子", "肾脏", "high",
         "车前子有利尿、促进尿酸排泄的药理研究报道", "药理研究"),
        ("泽泻", "肾脏", "high",
         "泽泻有利尿的药理作用（注意：大剂量长期使用另有肾小管损伤的动物实验报道，本系统已控量）",
         "药理研究"),
        ("茯苓", "肾脏", "high",
         "茯苓有温和利尿的药理研究报道", "药理研究"),
        ("薏苡仁", "肾脏", "high",
         "薏苡仁为传统利湿食药，利尿相关现代证据有限", "传统经验"),
    ]
    cur.executemany(
        "insert into herb_mechanism(herb,indicator_class,direction,"
        "statement,evidence_level,src) values (?,?,?,?,?,?)",
        [(h, c, d, s, e, S_M) for h, c, d, s, e in M])

    # ==================================================================
    # 3. [TEXT] herb_dose_risk："多了会怎样"的依据
    # ==================================================================
    S_R = "[TEXT]中药学教材·用药警戒+不良反应文献(须药师复核)"
    R = [
        ("甘草", "大剂量或长期服用可致假性醛固酮增多（水肿、低血钾、血压升高），"
                 "高血压与水肿患者尤须控量"),
        ("附子", "超量或煎煮不充分可致乌头碱中毒（口舌四肢麻木、心悸、心律失常），"
                 "必须先煎久煎并严格限量"),
        ("肉桂", "辛热动血，过量易见口干咽痛、鼻衄，阴虚火旺者加重"),
        ("法半夏", "半夏生品对咽喉黏膜有强刺激性，须用炮制品并控制剂量"),
        ("半夏", "生品对咽喉黏膜有强刺激性，须用炮制品并控制剂量"),
        ("苦杏仁", "含苦杏仁苷，过量有氢氰酸中毒风险（头晕、呼吸困难），儿童尤须警惕"),
        ("桃仁", "含苦杏仁苷，过量有中毒风险，并可增加出血倾向"),
        ("红花", "过量可致出血倾向，月经过多及有出血性疾病者慎用"),
        ("黄芩", "苦寒之品，过量易伤脾胃，见腹痛便溏、食欲减退"),
        ("黄柏", "苦寒之品，过量易伤脾胃阳气"),
        ("龙胆", "大苦大寒，过量败胃伤阳，故本方剂量刻意压低且中病即止"),
        ("栀子", "苦寒滑肠，过量易致便溏、胃部不适"),
        ("泽泻", "动物实验提示大剂量长期使用有肾小管损伤风险，须控量控疗程"),
        ("干姜", "辛热助火，过量易见口干咽燥、胃中灼热感"),
        ("川芎", "辛温走窜，过量可致头胀痛、耗气伤阴"),
        ("薄荷", "辛凉发散，过量耗气，且挥发油对胃有刺激"),
    ]
    cur.executemany(
        "insert or replace into herb_dose_risk(herb,over_effect,src) "
        "values (?,?,?)", [(h, t, S_R) for h, t in R])

    # ==================================================================
    # 4. [TEXT] syndrome_pathology：八证型病机/治法/思路/忌
    #    "忌"字段就是反向排除解释（维度4）的教材依据。
    # ==================================================================
    S_P = "[TEXT]中医基础理论/方剂学教材(须中医师复核)"
    P = [
        ("肝郁", "情志不遂，肝失疏泄，气机郁滞",
         "疏肝解郁，理气和中",
         "以理气为主，佐以养血柔肝，防理气药辛燥伤阴",
         "无明显热象时忌大剂苦寒清泄（徒伤中阳），忌滋腻碍气之品"),
        ("脾虚", "脾气不足，运化失司，气血生化乏源",
         "益气健脾",
         "补气与助运并行，佐以理气之品防补而壅滞",
         "忌苦寒败胃之品，忌滋腻碍脾之品"),
        ("痰湿", "脾失健运，水湿内停，聚湿成痰",
         "燥湿化痰，理气健脾",
         "治痰先治气，气顺则痰消；健脾以绝生痰之源",
         "忌滋腻助湿之品（如大剂熟地不宜为主），忌甘甜壅滞"),
        ("湿热", "湿热内蕴，如油裹面，缠绵胶着",
         "清热利湿",
         "分消走泄，给邪以出路；中病即止，防苦寒过剂伤胃",
         "忌温燥助热之品，忌滋腻助湿之品"),
        ("阴虚", "阴液亏虚，虚热内生",
         "滋阴降火",
         "壮水之主以制阳光；滋阴为主，佐以清虚热",
         "忌辛温香燥耗伤阴液之品，忌峻猛发汗"),
        ("阳虚", "阳气亏虚，失于温煦，阴寒内盛",
         "温补肾阳，益火之源",
         "阴中求阳，温而不燥，佐以填精之品",
         "忌苦寒清热之品（更伤阳气），忌生冷"),
        ("气血两虚", "气血不足，脏腑经脉失养",
         "益气养血",
         "气血双补，且补气以助生血（气为血帅）",
         "忌攻伐克削之品，忌大剂苦寒"),
        ("血瘀", "血行不畅，瘀阻脉络，不通则痛",
         "活血化瘀，行气止痛",
         "气行则血行，活血必兼理气；久瘀酌加通络",
         "忌固涩收敛滞血之品；出血倾向及妊娠期禁用活血峻剂"),
    ]
    cur.executemany(
        "insert or replace into syndrome_pathology values (?,?,?,?,?,?,1)",
        [(s, a, b, c, d, S_P) for s, a, b, c, d in P])

    cx.commit()

    # ---- 体检 ----
    def one(q):
        return cur.execute(q).fetchone()[0]
    print("批次5 数据层构建完成")
    print(f"  herb_function      {one('select count(*) from herb_function'):>5} 味功能主治([KB]自动抽取)")
    print(f"  herb_mechanism     {one('select count(*) from herb_mechanism'):>5} 条指标级机制证据([TEXT])")
    print(f"  herb_dose_risk     {one('select count(*) from herb_dose_risk'):>5} 条超量风险([TEXT])")
    print(f"  syndrome_pathology {one('select count(*) from syndrome_pathology'):>5} 个证型病机([TEXT])")
    # 覆盖体检：18首基础方的药材，功能主治覆盖多少
    miss = cur.execute(
        "select distinct b.herb from base_formula_herb b "
        "left join herb_function f on f.herb=b.herb "
        "left join herb_alias a on a.base=b.herb "
        "left join herb_function f2 on f2.herb=a.alias "
        "where f.herb is null and f2.herb is null").fetchall()
    print(f"  基础方54味药中缺功能主治文本的：{len(miss)} 味 "
          f"{'（' + '、'.join(m[0] for m in miss) + '）' if miss else ''}")
    cx.close()


if __name__ == "__main__":
    main()
