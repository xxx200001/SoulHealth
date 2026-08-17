# -*- coding: utf-8 -*-
"""端到端自检：不依赖 pytest、不依赖网络，直接 python tests/test_pipeline.py 运行。

覆盖融合后最容易出问题的几处：
  1. 知识库自检
  2. 舌象/面象量化结果 → 辨证引擎的字段适配（原版这里键名对不上，证据静默失效）
  3. 问诊分类题 → 辨证键的映射（原版「大便性状」进不了引擎）
  4. 档案是唯一数据主体：四诊、指标、问诊都能落库并被快照带出
  5. 双链分析跑通，两份报告都能生成且过合规闸
  6. 组方的安全闸：妊娠状态能拦下禁忌
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 用临时库跑，不污染真实数据
_tmp = tempfile.mkdtemp(prefix="soulhealth_test_")
os.environ["SOULHEALTH_MOCK"] = "1"          # 不调外部服务
os.environ["SOULHEALTH_BIOCOMPUTE"] = "mock"

from app import config                                          # noqa: E402
config.DB_PATH = Path(_tmp) / "test.db"
config.REPORT_DIR = Path(_tmp) / "reports"
config.REPORT_DIR.mkdir(parents=True, exist_ok=True)

from app.archive import repository as repo                      # noqa: E402
from app.agent import orchestrator                              # noqa: E402
from app.tcm import adapters                                    # noqa: E402
from app.tcm.kb import bootstrap                                # noqa: E402

PASS, FAIL = 0, 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {extra}")


def main() -> int:
    print("\n[1] 中医知识库")
    kb = bootstrap.check(config.TCM_KB_PATH)
    check("知识库可用", kb["ready"], kb["message"])
    check("基础方已入库", kb["stats"].get("base_formula", 0) >= 18)
    check("饮片剂量档案已入库", kb["stats"].get("herb_pharm", 0) >= 60)

    print("\n[2] 舌面诊 → 辨证引擎字段适配")
    raw_tongue = {
        "code": 0,
        "body_color": {"value": {"class": "淡白舌", "red_index": 20.0}},
        "coat_yellow": {"value": {"class": "白苔"}},
        "coat_thickness": {"value": 70.0},
        "greasy_dry": {"value": {"greasy_score": 66.0, "dry_score": 15.0}},
        "tooth_mark": {"value": {"grade": 2}},
        "crack": {"value": {"grade": 1}},
        "petechiae": {"value": 3},
        "segmentation": {"coat_coverage": 0.3},
    }
    feat = adapters.tongue_to_engine(raw_tongue)
    # 这几个键名正是 syndrome.py RULES 里 src="tongue" 的 field
    for key in ("body_class", "coat_class", "coat_thickness", "greasy_score",
                "tooth_mark_grade", "crack_grade", "petechiae_count"):
        check(f"舌象字段 {key}", key in feat, f"实际：{list(feat)}")
    check("舌质分类正确", feat.get("body_class") == "淡白舌")

    raw_face = {
        "code": 0,
        "sallow_index": {"value": 62.0}, "dull_index": {"value": 58.0},
        "lip_color": {"value": {"class": "淡白", "red_index": 18.0}},
        "eye_bag": {"value": {"grade": 2}}, "spot": {"value": {"grade": 1}},
        "brightness": {"value": 45.0},
    }
    fface = adapters.face_to_engine(raw_face)
    for key in ("sallow_index", "dull_index", "lip_class", "eye_bag_grade", "spot_grade"):
        check(f"面象字段 {key}", key in fface, f"实际：{list(fface)}")

    print("\n[3] 问诊分类题 → 辨证键映射")
    check("干结便秘 → 便秘",
          adapters.symptoms_to_engine({"大便性状": 8}).get("便秘") == 9)
    check("偏稀不成形 → 便溏",
          adapters.symptoms_to_engine({"大便性状": 3}).get("便溏") == 5)
    check("时稀时干 → 便溏+便秘",
          set(adapters.symptoms_to_engine({"大便性状": 5})) == {"便溏", "便秘"})
    check("普通主观题原样带分",
          adapters.symptoms_to_engine({"怕冷": 7}).get("怕冷") == 7)

    print("\n[4] 统一档案：四诊与指标同库")
    repo.init()
    uid = repo.create_user("tester", "testpass123")
    pid, created = repo.find_or_create_patient(
        name="测试甲", sex="female", age_years=36, height_cm=160,
        weight_kg=55, id_last4="0001", owner_id=uid)
    check("建档成功", created and bool(pid))
    pid2, created2 = repo.find_or_create_patient(
        name="测试甲", id_last4="0001", owner_id=uid)
    check("同名同后四位找回同一档案", pid2 == pid and not created2)

    repo.update_patient(pid, allergies=["青霉素"], drugs=["华法林"], pregnant=False)
    p = repo.get_patient(pid)
    check("过敏源已落库", p["allergies"] == ["青霉素"])
    check("在服西药已落库", p["drugs"] == ["华法林"])

    for code, disp, val, unit, hi in (("ALT", "谷丙转氨酶(ALT)", 75, "U/L", 40),
                                      ("TG", "甘油三酯", 2.6, "mmol/L", 1.7)):
        repo.add_observation(pid, code=code, display=disp, value_num=val,
                             unit=unit, ref_high=hi, abnormal_flag="H",
                             observed_at="2026-08-01")
    repo.save_tcm_exam(pid, "tongue", feat, quantified=raw_tongue)
    answers = {"疲劳": 7, "食欲差": 6, "腹胀": 5, "大便性状": 3, "怕冷": 6, "自汗": 5}
    repo.save_tcm_inquiry(pid, answers, adapters.symptoms_to_engine(answers))

    snap = repo.snapshot(pid)
    check("快照带出舌诊", bool(snap["tcm_exams"]["tongue"]))
    check("快照带出问诊", bool(snap["tcm_inquiry"]))
    status = repo.collection_status(pid)
    check("采集进度可用", status["ready_for_analysis"], str(status))

    print("\n[5] 双链分析与报告")
    out = orchestrator.run_analysis(pid)
    tcm = out["tcm"]
    check("中医链已执行", tcm is not None, out.get("tcm_error") or "")
    check("辨出主证", bool(tcm and tcm["syndrome_result"].get("primary")))
    check("舌象证据参与了辨证",
          any(a["rule"].startswith("T") for a in tcm["syndrome_result"]["audit"]),
          "舌象规则未命中，说明字段适配失效")
    dos = tcm["dosage_result"]
    check("出方或给出明确拦截理由",
          dos["status"] == "OK" or bool(dos.get("reason")))
    if dos["status"] == "OK":
        check("处方非空", len(dos["prescription"]) > 0)
        check("逐味推导链非空", len(dos["herb_audit"]) > 0)
        check("总克重合理", 10 < (dos["total_g"] or 0) < 300, str(dos["total_g"]))
    check("风险识别已执行", isinstance(out["risk_tags"], list))
    check("分析步骤有留痕", len(out["trace"]) >= 6)

    types = {r["report_type"] for r in out["reports"] if r.get("report_id")}
    check("生成健康分析报告", "health_analysis" in types)
    check("生成中医组方报告", "tcm_prescription" in types, str(types))
    errs = [r for r in out["reports"] if r.get("error")]
    check("所有报告均无生成错误", not errs, str(errs))
    for r in out["reports"]:
        if r.get("path"):
            check(f"报告文件已落盘 {Path(r['path']).name}", Path(r["path"]).exists())
            break

    print("\n[6] 组方安全闸：妊娠禁忌")
    pidp, _ = repo.find_or_create_patient(name="测试乙", sex="female", age_years=29,
                                          height_cm=163, weight_kg=57,
                                          id_last4="0002", owner_id=uid)
    repo.update_patient(pidp, pregnant=True)
    repo.save_tcm_inquiry(pidp, answers, adapters.symptoms_to_engine(answers))
    outp = orchestrator.run_analysis(pidp)
    dosp = (outp["tcm"] or {})["dosage_result"]
    pregnant_handled = (dosp["status"] != "OK"
                        or bool(dosp.get("warnings"))
                        or all("妊娠" not in str(h.get("flags"))
                               for h in dosp["prescription"]))
    check("妊娠状态被组方引擎识别并处理", pregnant_handled, str(dosp.get("warnings")))

    print(f"\n{'=' * 46}\n  通过 {PASS} 项，失败 {FAIL} 项\n{'=' * 46}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
