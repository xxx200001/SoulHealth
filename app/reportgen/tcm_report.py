"""《中医辨证与调理组方报告》生成器。

与《个性化健康分析报告》分工
----------------------------
health_report.py  写现代医学链：风险识别、机制解释、生物计算、健康管理建议。
tea_plan.py       写药食同源代茶饮（食养级，日常可自备）。
本文件            写中医辨证链：八证型量化辨证依据、0.1g 精准组方与逐味剂量
                  推导、四维解释、毒理与中西药相互作用、生活干预。

三份报告内容不重叠：代茶饮是食养建议，本报告是治疗性组方，后者明确标注
"须执业中医师复核后使用"，且组方被安全闸拦截时只出辨证与拦截理由，不出方。
"""
from __future__ import annotations

import re
from typing import List

from .. import config

_ROLE_ORDER = {"君": 0, "臣": 1, "佐": 2, "使": 3}
_ORDERED = re.compile(r"^\d+[.、)]\s+")


def available(ctx: dict) -> bool:
    """本报告的生成条件。

    两种情况不出：
      1. 无中医结果（知识库缺失或链路异常）；
      2. 舌象/面象/问诊三路证据全空且未定主证——此时报告里既没有辨证结论
         也没有方，只剩一句"证据不足"，属于凑数（generator 的原则是缺数据
         即跳过）。分析页的 TCM_SYNDROME 步骤已如实标注 skipped，用户看得到。

    只要有任一路四诊证据，即便最终被拦下不出方，也照出：辨证过程、证据贡献、
    拦截理由与还缺什么，这些对使用者是有用信息。
    """
    tcm = ctx.get("tcm")
    if not (tcm and tcm.get("syndrome_result")):
        return False
    used = tcm.get("evidence_used") or {}
    has_tcm_evidence = any(used.get(k) for k in
                           ("tongue_fields", "face_fields", "symptoms"))
    if has_tcm_evidence:
        return True
    return bool((tcm.get("syndrome_result") or {}).get("primary"))


def _syndrome_table(syndrome: dict) -> dict:
    percent = syndrome.get("percent") or {}
    ranked = syndrome.get("ranked") or list(percent.keys())
    return {
        "header": ["证型", "占比", "分值"],
        "rows": [[name, f"{percent.get(name, 0)}%",
                  (syndrome.get("scores") or {}).get(name, 0)]
                 for name in ranked if percent.get(name, 0) > 0],
    }


def _evidence_rows(syndrome: dict, limit: int = 12) -> List[list]:
    rows = []
    for item in (syndrome.get("audit") or [])[:limit]:
        contrib = "、".join(f"{k} +{v}" for k, v in (item.get("contrib") or {}).items())
        rows.append([item.get("rule", ""), str(item.get("evidence", "")),
                     contrib, item.get("basis", "")])
    return rows


def build_blocks(ctx: dict) -> List[tuple]:
    tcm = ctx["tcm"]
    snapshot = ctx["snapshot"]
    p = snapshot["patient"]
    sex = {"female": "女", "male": "男"}.get(p.get("sex"), "未录")
    syndrome = tcm.get("syndrome_result") or {}
    dosage = tcm.get("dosage_result") or {}
    explain = tcm.get("explain") or {}
    tox = tcm.get("toxicology") or {}
    lifestyle = tcm.get("lifestyle") or {}
    drug = tcm.get("drug_interaction") or {}

    name_line = ((p.get("name") or "") + "（" + p["pseudonym"] + "）") \
        if (config.REPORT_REAL_NAME and p.get("name")) else p["pseudonym"]

    blocks: List[tuple] = [
        ("title", "中医辨证与调理组方报告"),
        ("p", [("分析编号：", True), (ctx["analysis_id"], False),
               ("　生成时间：", True), (tcm.get("generated_at", ""), False)]),
        ("note", "本报告的辨证与组方由规则引擎依据教材共识权重与《中国药典》剂量区间"
                 "自动推算，属于健康管理辅助信息，不替代医生诊断；处方须经执业中医师"
                 "面诊复核后方可使用，服用期间请按医嘱随访。"),

        ("h1", "一、受检者与证据来源"),
        ("p", f"{name_line}：{sex}，{p.get('age_years', '—')} 岁；"
              f"身高 {p.get('height_cm') or '—'}cm，体重 {p.get('weight_kg') or '—'}kg。"),
    ]

    used = tcm.get("evidence_used") or {}
    blocks.append(("table", {
        "header": ["证据来源", "数量", "说明"],
        "rows": [
            ["体检指标", used.get("labs", 0), "已标准化并按 G0–G3 分级"],
            ["舌象特征", used.get("tongue_fields", 0), "舌质/舌苔/齿痕/裂纹等量化字段"],
            ["面象特征", used.get("face_fields", 0), "萎黄/晦暗/唇色/眼袋/色斑等量化字段"],
            ["问诊症状", used.get("symptoms", 0), "0–10 分症状打分"],
        ]}))

    # ---------------------------------------------------------------- 辨证
    blocks += [
        ("h1", "二、证型辨识"),
        ("p", [("主证：", True), (str(syndrome.get("primary") or "证据不足，未定主证"), False)]),
        ("table", _syndrome_table(syndrome)),
    ]
    flags = syndrome.get("flags") or []
    if flags:
        blocks.append(("h2", "需要注意的辨证提示"))
        for f in flags:
            blocks.append(("bullet", str(f)))
        blocks.append(("p", ""))
    ev_rows = _evidence_rows(syndrome)
    if ev_rows:
        blocks += [
            ("h2", "逐条证据贡献（可追溯到教材条目）"),
            ("table", {"header": ["规则", "命中证据", "证型贡献", "依据"],
                       "rows": ev_rows}),
        ]

    # ---------------------------------------------------------------- 组方
    blocks.append(("h1", "三、调理组方"))
    if dosage.get("status") == "OK":
        base = dosage.get("base_formula") or {}
        blocks += [
            ("p", [("底方：", True), (f"《{base.get('name', '定制组方')}》", False),
                   ("　出处：", True), (str(base.get("book") or "—"), False)]),
            ("p", f"适应证：{base.get('indication') or '—'}"),
            ("table", {
                "header": ["配伍", "药材", "剂量(g)", "属性"],
                "rows": [[h.get("role", ""), h.get("herb", ""), h.get("dose_g", ""),
                          "药食同源" if h.get("is_food_herb") else "常规饮片"]
                         for h in sorted(dosage.get("prescription") or [],
                                         key=lambda x: _ROLE_ORDER.get(x.get("role"), 9))]}),
            ("p", [("合计克重：", True), (f"{dosage.get('total_g')} g", False)]),
        ]
        if dosage.get("signoff"):
            blocks.append(("p", f"服用说明：{dosage['signoff']}"))

        audit = dosage.get("herb_audit") or []
        if audit:
            blocks.append(("h2", "逐味剂量推导"))
            rows = []
            for h in audit[:20]:
                steps = "；".join(f"{s.get('name')}×{s.get('factor')}"
                                  for s in (h.get("steps") or []))
                rows.append([h.get("herb", ""), h.get("ref_g", ""), steps,
                             h.get("raw_g", ""), h.get("origin", "")])
            blocks.append(("table", {
                "header": ["药材", "基准量(g)", "调幅链", "推算量(g)", "剂量出处"],
                "rows": rows}))
        glob = dosage.get("global_audit") or []
        if glob:
            blocks.append(("h2", "全局调幅依据"))
            for g in glob:
                if isinstance(g, dict):
                    blocks.append(("bullet",
                                   f"{g.get('name', '')}：×{g.get('factor', '')} "
                                   f"— {g.get('why', '')}"))
                else:
                    blocks.append(("bullet", str(g)))
            blocks.append(("p", ""))
    else:
        blocks += [
            ("p", [("本次不出方。", True), ("", False)]),
            ("p", f"原因：{dosage.get('reason') or '辨证证据不足'}"),
        ]
        # 证据不足是最常见的拦截原因，这里指名缺哪几路，用户才知道补什么；
        # 只在引擎确实未定主证时列，安全闸拦截（妊娠、配伍禁忌等）不适用。
        if not syndrome.get("primary"):
            missing = [label for key, label in
                       (("symptoms", "症状问诊（辨证的主要证据）"),
                        ("tongue_fields", "舌象（拍一张舌照即可量化）"),
                        ("face_fields", "面象（与舌象同一次拍摄）"),
                        ("labs", "体检指标（有化验单时录入，可提高分级准确度）"))
                       if not used.get(key)]
            if missing:
                blocks.append(("h2", "本次缺少的证据"))
                for m in missing:
                    blocks.append(("bullet", m))
                blocks.append(("p", ""))
        blocks.append(("p", dosage.get("advice") or
                       "补齐上述证据后重新分析即可出方；也可携带体检报告至医疗机构面诊，"
                       "由执业中医师当面辨证后开具。"))

    warnings = dosage.get("warnings") or []
    if warnings:
        blocks.append(("h2", "组方安全提示"))
        for w in warnings:
            blocks.append(("bullet", str(w)))
        blocks.append(("p", ""))

    # ---------------------------------------------------------------- 四维解释
    # 直接复用解释引擎自己的 Markdown 渲染（宏观病机/微观机制/逐克依据/排除说明
    # 四个维度都已写好排版），转成报告块，避免在这里重复实现一套渲染。
    md = tcm.get("markdown") or {}
    if md.get("explain"):
        blocks.append(("h1", "四、四维解释"))
        blocks += _md_to_blocks(md["explain"], base_level=2, drop_title=True)

    # ---------------------------------------------------------------- 毒理与相互作用
    blocks.append(("h1", "五、安全性评估"))
    if md.get("toxicology"):
        blocks += _md_to_blocks(md["toxicology"], base_level=2, drop_title=True)
    elif tox.get("conclusion"):
        blocks.append(("p", "毒理结论：" + _flatten(tox.get("conclusion"))))
    else:
        blocks.append(("p", "本次未出方，无组方毒理可评估。"))
    if drug:
        blocks.append(("h2", "中西药相互作用"))
        blocks.append(("p", f"结论：{drug.get('action') or drug.get('summary') or '未见明确风险'}"))
        pairs = drug.get("interactions") or drug.get("hits") or []
        if pairs:
            blocks.append(("table", {
                "header": ["西药", "中药", "风险", "建议"],
                "rows": [[i.get("drug", ""), i.get("herb", ""),
                          i.get("risk") or i.get("level", ""),
                          i.get("advice") or i.get("action", "")]
                         for i in pairs[:12] if isinstance(i, dict)]}))
    else:
        blocks.append(("p", "未登记在服西药，本次未做中西药相互作用核验。"))

    # ---------------------------------------------------------------- 生活干预
    if md.get("lifestyle"):
        blocks.append(("h1", "六、生活干预建议"))
        blocks += _md_to_blocks(md["lifestyle"], base_level=2, drop_title=True)
    elif lifestyle:
        blocks.append(("h1", "六、生活干预建议"))
        diet = lifestyle.get("diet") or {}
        for key, title in (("recommended", "宜"), ("avoid", "忌")):
            items = diet.get(key) or []
            if not items:
                continue
            blocks.append(("h2", title))
            for it in items[:15]:
                blocks.append(("bullet", _flatten(it)))
            blocks.append(("p", ""))

    blocks += [
        ("h1", "七、免责声明"),
        ("p", "本报告输出为健康管理辅助信息，不替代执业医师的诊断与治疗决策。"
              "方中剂量由引擎按药典区间推算，个体差异、合并用药、妊娠哺乳、肝肾功能"
              "异常等情形均需医师复核调整。指标异常者请及时就医并按医嘱随访复查。"),
    ]
    return blocks


def _flatten(item) -> str:
    """把 dict / list / str 混杂的建议项压成一行可读文本。"""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in ("text", "content", "name", "title", "item", "advice"):
            if item.get(key):
                extra = item.get("reason") or item.get("why") or item.get("note")
                return f"{item[key]}{'：' + str(extra) if extra else ''}"
        return "；".join(f"{k}={v}" for k, v in item.items())
    if isinstance(item, (list, tuple)):
        return "、".join(_flatten(i) for i in item)
    return str(item)


def _md_to_blocks(md_text: str, base_level: int = 1,
                  drop_title: bool = False) -> List[tuple]:
    """Markdown → 报告块。

    各引擎（explain / toxicology / lifestyle）都自带排好版的 Markdown 渲染，
    这里把它转成统一的块结构，好让同一份内容既能出 docx 也能出 md，
    不必在报告层再实现第二套排版。

    base_level 控制标题降级：嵌进本报告某一章时传 2，即引擎里的 ## 变成 ###。
    drop_title=True 丢掉引擎渲染的一级标题（本报告已有自己的章节标题）。
    """
    blocks: List[tuple] = []
    lines = (md_text or "").splitlines()
    table_buf: List[List[str]] = []

    def flush_table() -> None:
        if not table_buf:
            return
        header, rows = table_buf[0], table_buf[1:]
        blocks.append(("table", {"header": header, "rows": rows}))
        table_buf.clear()

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()

        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(set(c) <= set("-: ") and c for c in cells):
                continue                      # 分隔行
            table_buf.append(cells)
            continue
        flush_table()

        if not stripped:
            continue
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            text = stripped.lstrip("#").strip()
            if level == 1 and drop_title:
                continue
            out_level = min(3, max(1, level + base_level - 1))
            blocks.append((f"h{out_level}", _strip_marks(text)))
        elif stripped.startswith(("- ", "* ", "+ ")):
            blocks.append(("bullet", _strip_marks(stripped[2:].strip())))
        elif _ORDERED.match(stripped):
            blocks.append(("bullet", _strip_marks(_ORDERED.sub("", stripped, 1))))
        elif stripped.startswith(">"):
            blocks.append(("note", _strip_marks(stripped.lstrip(">").strip())))
        else:
            blocks.append(("p", _strip_marks(stripped)))
    flush_table()
    return blocks


def _strip_marks(text: str) -> str:
    """去掉行内 Markdown 强调标记：docx 段落不支持内联富文本，
    保留星号反而会在 Word 里看到一堆 **。"""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text.strip()
