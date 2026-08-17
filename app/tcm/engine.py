"""中医辨证溯源引擎：指标解析 → 证型辨证 → 精准组方 → 四维解释 → 毒理 → 生活干预。

与原 pipeline.py 的差别
-----------------------
1. 不再内嵌 FastAPI 壳，只是一个可被任何上层调用的纯逻辑类。
2. 完整返回全部中间产物。原版把 explain / toxicology / lifestyle 的详细结果
   放进 "_" 前缀键，接口层又统一把 "_" 开头的键删掉，前端只拿得到
   {status, has_d1..d4} 这种布尔摘要，四维解释、毒理明细、逐味剂量推导
   (herb_audit) 全部拿不到——报告页只能靠 markdown 字符串硬解析。
   这里一次性给出结构化的完整结果。
3. 舌象/面象通过 adapters 做字段扁平化后再喂辨证引擎（原版键名对不上，
   舌面诊证据静默失效）。
4. 引擎实例按知识库路径缓存，避免每次请求重连 SQLite。
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Optional

from . import adapters
from .consultation import ConsultationEngine
from .drug_interaction import DrugInteractionChecker
from .lab_mapper import LabIndicatorMapper
from .lifestyle import LifestyleAdvisor

VERSION = "tcm-engine/2.0"

_ENGINES: dict = {}
_LOCK = threading.Lock()


class TCMEngineUnavailable(RuntimeError):
    """知识库缺失/损坏时抛出，由接口层转成 503 + 修复指引。"""


def _load_engines(db_path: str) -> dict:
    """惰性加载依赖 tcm_kb.sqlite 的三个引擎，同一库路径只加载一次。"""
    key = str(db_path)
    with _LOCK:
        if key in _ENGINES:
            return _ENGINES[key]
        from pathlib import Path
        if not Path(key).exists():
            raise TCMEngineUnavailable(
                f"中医知识库不存在：{key}。请确认 data/tcm_kb.sqlite 已就位，"
                f"或运行 python -m app.tcm.kb.bootstrap 自举一个最小可用库。")
        from .dosage import DosageEngine
        from .explain import ExplainEngine
        from .syndrome import SyndromeWeightEngine
        from .toxicology import ToxicologyReportEngine
        try:
            bundle = {
                "syndrome": SyndromeWeightEngine(),
                "dosage": DosageEngine(key),
                "explain": ExplainEngine(key),
                "toxicology": ToxicologyReportEngine(key),
            }
        except Exception as exc:                    # noqa: BLE001
            raise TCMEngineUnavailable(f"中医知识库加载失败：{exc}") from exc
        _ENGINES[key] = bundle
        return bundle


class TCMEngine:
    """中医辨证溯源全流程。线程安全用法：进程内共享单例即可。"""

    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        self.lab_mapper = LabIndicatorMapper()
        self.consult = ConsultationEngine()
        self.lifestyle = LifestyleAdvisor()
        self.drug_checker = DrugInteractionChecker()

    # ------------------------------------------------------------------ 采集
    def questionnaire(self, sex: str = "M") -> dict:
        return self.consult.get_questionnaire(sex)

    # ------------------------------------------------------------------ 主流程
    def run(self,
            patient: dict,
            lab_raw: Optional[list] = None,
            tongue: Optional[dict] = None,
            face: Optional[dict] = None,
            symptoms: Optional[dict] = None,
            current_drugs: Optional[list] = None,
            raw_answers: Optional[dict] = None) -> dict:
        """
        参数
        ----
        patient        {age, sex, weight_kg, height_cm, liver_grade, renal_grade,
                        pregnant, allergies:[...]}
        lab_raw        [{"name_raw": "谷丙转氨酶(ALT)", "value": 68, "unit": "U/L"}, ...]
        tongue/face    已扁平化的舌象/面象字段（adapters.tongue_to_engine 的输出）
        symptoms       已归一化的症状打分（adapters.symptoms_to_engine 的输出）
        current_drugs  在服西药 ["华法林", ...]
        raw_answers    问卷原始作答，仅用于回档留痕，不参与计算
        """
        eng = _load_engines(self.db_path)
        patient = dict(patient or {})
        report = {
            "version": VERSION,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "patient": patient,
        }

        # ── 1. 指标解析：原始录入 → 标准名 + G0–G3 异常分级 ──
        lab_result, labs_for_syndrome = None, []
        if lab_raw:
            lab_result = self.lab_mapper.parse(lab_raw)
            labs_for_syndrome = self.lab_mapper.to_syndrome_input(lab_result)
            derived = lab_result.get("derived") or {}
            patient.setdefault("liver_grade", derived.get("liver_grade"))
            patient.setdefault("renal_grade", derived.get("renal_grade"))
        report["lab_result"] = lab_result

        # ── 2. 证型辨证：舌 + 面 + 化验 + 症状 四路加权 ──
        syndrome = eng["syndrome"].evaluate(
            labs=labs_for_syndrome, tongue=tongue, face=face, symptoms=symptoms)
        report["syndrome_result"] = syndrome
        report["evidence_used"] = {
            "labs": len(labs_for_syndrome),
            "tongue_fields": len(tongue or {}),
            "face_fields": len(face or {}),
            "symptoms": len(symptoms or {}),
        }

        # ── 3. 精准组方（0.1g 级，逐味可溯源）──
        dosage = eng["dosage"].prescribe(
            syndrome, patient=patient, labs=labs_for_syndrome,
            tongue=tongue, symptoms=symptoms)
        report["dosage_result"] = {
            "status": dosage.get("status"),
            "base_formula": dosage.get("base_formula"),
            "prescription": dosage.get("prescription") or [],
            "total_g": dosage.get("total_g"),
            "warnings": dosage.get("warnings") or [],
            "signoff": dosage.get("signoff"),
            "advice": dosage.get("advice"),
            "reason": (dosage.get("block") or {}).get("reason") or dosage.get("advice"),
            "block": dosage.get("block"),
            "review_required": dosage.get("review_required"),
            # 原版丢失的两块：逐味剂量推导链 + 全局调幅审计
            "herb_audit": dosage.get("herb_audit") or [],
            "global_audit": dosage.get("global_audit") or [],
        }

        # ── 4. 中西药相互作用（出方后按实际药材复核）──
        drug_check = None
        if current_drugs:
            herbs = [h.get("herb") for h in (dosage.get("herb_audit") or [])] \
                or [h.get("herb") for h in (dosage.get("prescription") or [])]
            drug_check = self.drug_checker.check(current_drugs, herbs)
            if drug_check.get("should_block"):
                report["dosage_result"]["warnings"].append(
                    f"中西药相互作用警告：{drug_check.get('action')}")
        report["drug_interaction"] = drug_check

        # ── 5. 四维解释：宏观病机 / 微观机制 / 剂量依据 / 排除性说明 ──
        explain = eng["explain"].explain(
            syndrome, dosage, patient=patient, labs=labs_for_syndrome)
        report["explain"] = explain

        # ── 6. 毒理与安全 ──
        tox = eng["toxicology"].generate(dosage, patient=patient)
        report["toxicology"] = tox

        # ── 7. 生活干预 ──
        lifestyle = self.lifestyle.advise(
            syndrome, labs=labs_for_syndrome, patient=patient)
        report["lifestyle"] = lifestyle

        # ── 8. Markdown 渲染（供报告文档与前端预览共用）──
        markdown = {}
        if dosage.get("status") == "OK":
            try:
                markdown["explain"] = eng["explain"].render_markdown(explain)
            except Exception as exc:                # noqa: BLE001
                markdown["explain"] = f"（解释渲染失败：{exc}）"
            try:
                markdown["toxicology"] = eng["toxicology"].render_markdown(tox)
            except Exception as exc:                # noqa: BLE001
                markdown["toxicology"] = f"（毒理渲染失败：{exc}）"
        try:
            markdown["lifestyle"] = self.lifestyle.render_markdown(lifestyle)
        except Exception as exc:                    # noqa: BLE001
            markdown["lifestyle"] = f"（生活干预渲染失败：{exc}）"
        report["markdown"] = markdown

        if raw_answers:
            report["raw_answers"] = raw_answers
        return report


_SINGLETON: dict = {}


def get_engine(db_path: str) -> TCMEngine:
    key = str(db_path)
    with _LOCK:
        if key not in _SINGLETON:
            _SINGLETON[key] = TCMEngine(key)
        return _SINGLETON[key]
