"""分析编排器：一个入口，两条互补的分析链。

为什么是一个入口
----------------
原来两套系统各有一个"开始分析"按钮：TongueDiag 的 /api/v1/full_report 走中医
辨证组方，bio 的 /api/analyze 走风险识别 + 机制链 + 生物计算。同一个人、同一批
数据要点两次，出两份互不相干的结论，还各自维护一份档案。

这里合并成单一入口 run_analysis(patient_id)：从统一档案取一次数据，两条链各自
消费，结果合成一份分析记录与一套报告。两条链定位不同、互不重复：

  中医辨证链（全离线，只依赖 data/tcm_kb.sqlite）
    化验 G 分级 + 舌象 + 面象 + 问诊打分
      → 八证型量化辨证 → 0.1g 精准组方 → 四维解释 → 毒理 → 生活干预
    产出：治疗性组方（须执业中医师复核后使用）

  现代医学链（规则部分离线；AI 解读与生物计算需密钥/联网）
    化验 + 影像所见 + 诊断提示
      → 显式规则风险识别 → 机制链 → 生物计算（AlphaFold/Ensembl/EVO2）
      → AI 综合解读
    产出：健康风险画像 + 机制解释 + 药食同源代茶饮（食养级，非治疗）

两者的"证型"分工也明确：量化辨证的八证型是主结论；自述关键词识别出的证型标签
只用于补充代茶饮选方，报告中标注"自述、非诊断"。

任一条链失败都不拖垮另一条：中医链缺知识库时如实记 skipped，现代链照常出结果。
每个节点产出一条 trace，供前端把分析过程逐步可视化。
"""
from __future__ import annotations

import time
from typing import Callable, List, Optional

from .. import config
from ..archive import repository as repo
from ..biocompute import runner as bio_runner
from ..knowledge import formula as formula_kb
from ..knowledge import tcm_syndrome
from ..reportgen import generator
from ..tcm import adapters as tcm_adapters
from ..tcm.engine import TCMEngineUnavailable, get_engine
from . import interpretation, mechanism, rules

# 八证型（量化辨证）→ 代茶饮底方证型 id。
# 量化辨证是主结论，这里只是把它翻译成食养组方引擎认识的键，
# 让代茶饮跟着辨证走，而不是另起一套判断。
SYNDROME_TO_TEA_PATTERN = {
    "湿热": "damp_heat_pattern",
    "痰湿": "spleen_damp_pattern",
    "脾虚": "spleen_damp_pattern",
    "阴虚": "yin_deficiency_pattern",
    "气血两虚": "qi_deficiency_pattern",
    "阳虚": "qi_deficiency_pattern",
    "肝郁": "insomnia_pattern",
    "血瘀": None,          # 无对应食养底方，不硬凑
}


def _trace(steps: List[dict], step: str, title: str, detail: str, t0: float,
           status: str = "done") -> None:
    steps.append({"step": step, "title": title, "detail": detail,
                  "status": status, "ms": round((time.time() - t0) * 1000, 1)})


def _tcm_inputs(snapshot: dict) -> dict:
    """从统一档案快照拼出中医引擎的入参。所有数据来自档案，无二次录入。"""
    patient = snapshot.get("patient") or {}
    sex = (patient.get("sex") or "").lower()
    inquiry = snapshot.get("tcm_inquiry") or {}
    exams = snapshot.get("tcm_exams") or {}
    return {
        "patient": {
            "age": patient.get("age_years"),
            "sex": "F" if sex in ("female", "f", "女") else "M",
            "weight_kg": patient.get("weight_kg"),
            "height_cm": patient.get("height_cm"),
            "pregnant": bool(patient.get("pregnant")),
            "allergies": patient.get("allergies") or [],
        },
        "lab_raw": tcm_adapters.labs_from_observations(
            snapshot.get("observations_timeline")),
        "tongue": ((exams.get("tongue") or {}).get("features")) or {},
        "face": ((exams.get("face") or {}).get("features")) or {},
        "symptoms": inquiry.get("symptoms") or {},
        "current_drugs": inquiry.get("drugs") or patient.get("drugs") or [],
        "raw_answers": inquiry.get("answers") or {},
    }


def run_analysis(patient_id: str,
                 on_step: Optional[Callable[[dict], None]] = None) -> dict:
    trace: List[dict] = []

    def mark(step: str, title: str, detail: str, t0: float,
             status: str = "done") -> None:
        _trace(trace, step, title, detail, t0, status)
        if on_step:
            on_step(trace[-1])

    # ── 1) 档案快照 ──────────────────────────────────────────────
    t0 = time.time()
    snapshot = repo.snapshot(patient_id)
    exams = snapshot.get("tcm_exams") or {}
    have = [n for n, k in (("舌诊", "tongue"), ("面诊", "face")) if exams.get(k)]
    inquiry_n = len((snapshot.get("tcm_inquiry") or {}).get("symptoms") or {})
    mark("LOAD_SNAPSHOT", "载入健康档案",
         f"资料 {len(snapshot['documents'])} 份，指标 "
         f"{len(snapshot['observations_timeline'])} 条，影像所见 "
         f"{len(snapshot['findings'])} 项"
         + (f"，四诊 {'、'.join(have)}" if have else "，尚无舌面诊")
         + (f"，问诊 {inquiry_n} 项" if inquiry_n else "，尚无问诊"), t0)

    # ── 2) 中医辨证链 ────────────────────────────────────────────
    t0 = time.time()
    tcm_result, tcm_error = None, None
    try:
        tcm_result = get_engine(str(config.TCM_KB_PATH)).run(**_tcm_inputs(snapshot))
    except TCMEngineUnavailable as exc:
        tcm_error = str(exc)
    except Exception as exc:                        # noqa: BLE001 — 单链失败不拖垮整体
        tcm_error = f"中医辨证链执行失败：{exc}"

    if tcm_result:
        syn = tcm_result["syndrome_result"]
        dos = tcm_result["dosage_result"]
        primary = syn.get("primary")
        if dos.get("status") == "OK":
            detail = (f"主证「{primary}」（占比 "
                      f"{(syn.get('percent') or {}).get(primary, 0)}%），"
                      f"底方《{(dos.get('base_formula') or {}).get('name')}》"
                      f"{len(dos.get('prescription') or [])} 味 / "
                      f"合计 {dos.get('total_g')}g")
        else:
            detail = (f"主证「{primary or '未定'}」；本次不出方："
                      f"{dos.get('reason') or '辨证证据不足'}")
        mark("TCM_SYNDROME", "中医辨证与精准组方", detail, t0)
    else:
        mark("TCM_SYNDROME", "中医辨证与精准组方",
             tcm_error or "未执行", t0, status="skipped")

    # ── 3) 风险识别（显式规则，可审计）───────────────────────────
    t0 = time.time()
    risk_tags = rules.identify_risks(snapshot)
    mark("IDENTIFY_RISKS", "健康风险识别",
         "识别出：" + ("；".join(t["label"] for t in risk_tags)
                    or "无显著风险标签"), t0)

    # ── 4) 机制链 + 药食同源代茶饮 ───────────────────────────────
    t0 = time.time()
    note_tags = tcm_syndrome.detect([n["text"] for n in snapshot.get("notes", [])])
    quant_tags: List[dict] = []
    # 量化证型只有在辨证本身成立时才下沉到食养立法。
    # syndrome_result.primary 为 None 表示引擎判定证据不足（见 syndrome.py 的
    # LOW_EVIDENCE_TOTAL）——此时 percent 是几个近零分之间的相对占比，
    # 50%/50% 只说明"两个弱信号打平"，不代表证候确立。若照用，会出现
    # 中医链明确"证据不足不出方"、代茶饮却按同一套证型选方的自相矛盾。
    if tcm_result and (tcm_result["syndrome_result"].get("primary")):
        percent = tcm_result["syndrome_result"].get("percent") or {}
        for name in (tcm_result["syndrome_result"].get("ranked") or [])[:2]:
            if percent.get(name, 0) < 15:           # 占比过低不作为食养立法依据
                continue
            sid = SYNDROME_TO_TEA_PATTERN.get(name)
            if sid:
                quant_tags.append({
                    "id": sid, "label": f"{name}（量化辨证）",
                    "matched_keywords": [], "source": "quantified",
                    "evidence": [f"八证型加权辨证：{name} 占比 {percent.get(name)}%"]})
    seen: set = set()
    syndrome_tags: List[dict] = []
    for tag in quant_tags + note_tags:
        if tag["id"] in seen:
            continue
        seen.add(tag["id"])
        syndrome_tags.append(tag)

    chain = mechanism.build_chain(risk_tags, snapshot, syndrome_tags=syndrome_tags)
    formula = formula_kb.build_formula(
        [t["id"] for t in risk_tags] + [s["id"] for s in syndrome_tags],
        sex=(snapshot["patient"].get("sex") or "unknown"))
    sub_note = ("；目录门禁替换 " +
                "、".join(f"{s['original']}→{s['replaced_by']}"
                          for s in formula["substitutions"])) \
        if formula["substitutions"] else ""
    mark("MATCH_KNOWLEDGE", "机制匹配与食养组方",
         f"机制实体 {len(chain['entities'])} 个；代茶饮 "
         f"{len(formula['ingredients'])} 味{sub_note}"
         + (f"；食养证型 {'、'.join(s['label'] for s in syndrome_tags)}"
            if syndrome_tags else ""), t0)

    # ── 5) 生物计算：先判断再执行 ────────────────────────────────
    t0 = time.time()
    bioplan = mechanism.plan_biocompute(chain)
    mark("PLAN_BIOCOMPUTE", "生物计算调用判断",
         ("生成调用计划 " + "、".join(sorted({b["service"] for b in bioplan}))
          + f" 共 {len(bioplan)} 项") if bioplan else "本次无需生物计算辅助",
         t0, status="done" if bioplan else "skipped")

    t0 = time.time()
    bioplan = bio_runner.execute_plan(bioplan)
    done = sum(1 for b in bioplan if b.get("status") == "done")
    pend = sum(1 for b in bioplan if b.get("status") == "pending_resolution")
    err = sum(1 for b in bioplan if b.get("status") == "error")
    mark("EXEC_BIOCOMPUTE", "生物计算执行",
         (f"完成 {done} 项" + (f"，待在线解析 {pend} 项" if pend else "")
          + (f"，失败 {err} 项" if err else "")
          + f"（{'演示缓存' if bioplan and all(b.get('source') == 'mock_cache' for b in bioplan) else '真实服务'}）")
         if bioplan else chain.get("biocompute_applicability", "无计划项"),
         t0, status="done" if bioplan else "skipped")

    # ── 6) AI 综合解读 ──────────────────────────────────────────
    t0 = time.time()
    interp = interpretation.generate(snapshot, risk_tags, chain, formula,
                                     syndrome_tags)
    mark("AI_INTERPRET", "AI 综合解读",
         (f"已生成（{interp['model']}，{len(interp['text'])} 字，过合规校验）"
          if interp.get("available")
          else f"未生成：{str(interp.get('reason', ''))[:64]}"),
         t0, status="done" if interp.get("available") else "skipped")

    # ── 7) 入库 + 报告生成 ──────────────────────────────────────
    t0 = time.time()
    analysis_id = repo.save_analysis(
        patient_id, snapshot, risk_tags, chain, bioplan,
        formula=formula, syndrome_tags=syndrome_tags,
        interpretation=interp,
        tcm=tcm_result or ({"error": tcm_error} if tcm_error else None))
    ctx = {"analysis_id": analysis_id, "patient_id": patient_id,
           "snapshot": snapshot, "risk_tags": risk_tags,
           "mechanism_chain": chain, "biocompute_plan": bioplan,
           "formula": formula, "syndrome_tags": syndrome_tags,
           "interpretation": interp, "tcm": tcm_result}
    reports = generator.generate_all(ctx)
    titles = "》《".join(dict.fromkeys(r["title"] for r in reports))
    mark("GENERATE_REPORTS", "报告生成",
         f"《{titles}》共 {len(reports)} 个文件（docx + md），均通过合规校验", t0)
    repo.update_analysis_trace(analysis_id, trace)

    return {"analysis_id": analysis_id, "patient_id": patient_id,
            "risk_tags": risk_tags, "mechanism_chain": chain,
            "biocompute_plan": bioplan, "formula": formula,
            "syndrome_tags": syndrome_tags, "interpretation": interp,
            "tcm": tcm_result, "tcm_error": tcm_error,
            "reports": reports, "trace": trace}
