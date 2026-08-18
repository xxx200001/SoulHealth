"""演示患者一键就绪：建档并喂满两条分析链的输入。

原 bio 前端的「载入演示患者」按钮只喂现代医学链（化验 + 影像所见 + 提示）；
融合后中医辨证链还需要舌象/面象/问诊，缺了整条链会 skipped。本模块把
两条链的演示数据一次种齐，命令行（run_demo.py）与前端按钮
（POST /api/patients/demo）共用这一份逻辑，不各写一套。

数据口径沿用 bio 的经典案例：女，25 岁，163cm/83kg，脂肪肝 + 转氨酶升高；
中医侧补痰湿证候群（白腻厚苔、齿痕、乏力困倦腹胀），与化验相互印证。
固定身份证后四位 0000，重复调用时精确找回同一条演示档案，不会越积越多。
"""
from __future__ import annotations

import datetime
from typing import Optional

from . import config
from .archive import repository as repo
from .ingest.pipeline import ingest_document
from .tcm import adapters

DEMO_NAME = "演示患者"
DEMO_ID4 = "0000"

# ---- 现代医学链：化验 + 影像所见 + 诊断提示（bio loadDemo 的同一份案例）----
DEMO_OBSERVATIONS = [
    dict(code="ALT", display="丙氨酸氨基转移酶", value_num=97, unit="U/L",
         ref_low=0, ref_high=40, abnormal_flag="H"),
    dict(code="GGT", display="谷氨酰转肽酶", value_num=64, unit="U/L",
         ref_low=0, ref_high=45, abnormal_flag="H"),
    dict(code="TG", display="甘油三酯", value_num=2.4, unit="mmol/L",
         ref_low=0, ref_high=1.7, abnormal_flag="H"),
]
DEMO_FINDING = dict(organ="肝脏", description="肝脏体积增大，回声增强，分布欠均匀",
                    flags=["回声增强", "欠均匀"])
DEMO_IMPRESSION = "脂肪肝"

# ---- 中医辨证链：引擎扁平字段（键名对齐 syndrome.py RULES）----
DEMO_TONGUE = {"body_class": "淡红舌", "coat_class": "白苔",
               "coat_thickness": 62, "greasy_score": 66, "dry_score": 20,
               "tooth_mark_grade": 2, "crack_grade": 0, "petechiae_count": 0}
DEMO_FACE = {"sallow_index": 58, "dull_index": 40}
DEMO_ANSWERS = {"乏力": 7, "困倦": 7, "腹胀": 6, "食欲不振": 5, "口苦": 4}


def seed(owner_id: Optional[str] = None) -> dict:
    """建立/找回演示档案并种入双链数据。幂等：同日重复调用不重复记账。

    owner_id：前端按钮传当前登录用户，档案归其名下（与手工建档一致）；
    命令行演示传 None（不归属任何账号，管理员可见）。
    返回 {"patient_id", "created", "seeded": {...}} 供界面提示。
    """
    pid, created = repo.find_or_create_patient(
        name=DEMO_NAME, sex="female", age_years=25, height_cm=163,
        weight_kg=83, id_last4=DEMO_ID4, owner_id=owner_id)

    today = datetime.date.today().isoformat()
    snap = repo.snapshot(pid)
    seeded = {"documents": 0, "observations": 0, "finding": False,
              "impression": False, "tongue": False, "face": False,
              "inquiry": False, "mode": config.LLM_MODE}

    # ---- 现代医学链 ----
    if config.MOCK_MODE:
        # MOCK：走图片摄取管线，演示「上传 → 抽取 → 入档」的完整链路
        if not snap["documents"]:
            for fname in ("demo_超声报告.jpg", "demo_肝功化验.jpg"):
                f = config.UPLOAD_DIR / fname
                f.write_bytes(b"\xff\xd8\xff\xe0demo")
                ingest_document(pid, f, source_filename=fname)
                seeded["documents"] += 1
    else:
        # 真实/未配置模式：图片抽取需要真实报告或密钥，改手动录入同一案例
        have = {o["code"] for o in snap["observations_timeline"]}
        for o in DEMO_OBSERVATIONS:
            if o["code"] not in have:
                repo.add_observation(pid, observed_at=today, **o)
                seeded["observations"] += 1
        if not snap["findings"]:
            repo.add_manual_finding(pid, observed_at=today, **DEMO_FINDING)
            seeded["finding"] = True
        if not snap["impressions"]:
            repo.add_manual_impression(pid, DEMO_IMPRESSION, observed_at=today)
            seeded["impression"] = True

    # ---- 中医辨证链：缺哪样补哪样 ----
    if not snap["tcm_exams"].get("tongue"):
        repo.save_tcm_exam(pid, "tongue", DEMO_TONGUE,
                           quantified={"source": "demo_seed"})
        seeded["tongue"] = True
    if not snap["tcm_exams"].get("face"):
        repo.save_tcm_exam(pid, "face", DEMO_FACE,
                           quantified={"source": "demo_seed"})
        seeded["face"] = True
    if not snap.get("tcm_inquiry"):
        symptoms = adapters.symptoms_to_engine(DEMO_ANSWERS)
        repo.save_tcm_inquiry(pid, DEMO_ANSWERS, symptoms,
                              drugs=[], allergies=[])
        seeded["inquiry"] = True

    return {"patient_id": pid, "created": created, "seeded": seeded,
            "collection_status": repo.collection_status(pid)}
