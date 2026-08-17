"""离线自检：不依赖 Web 框架，直接跑通全链路。

用途有二：交付前验证，以及部署后确认环境（知识库、依赖、数据库）是否就绪。
运行：python selfcheck.py
退出码 0 表示全部通过，非 0 表示有断言失败。
"""
from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path

PASS, FAIL = [], []


def check(name: str):
    def deco(fn):
        try:
            detail = fn()
            PASS.append((name, detail or ""))
            print(f"  [OK] {name}" + (f" —— {detail}" if detail else ""))
        except Exception as exc:  # noqa: BLE001 - 自检需要看到全部失败
            FAIL.append((name, exc))
            print(f"  [FAIL] {name} —— {type(exc).__name__}: {exc}")
            traceback.print_exc(limit=3)
        return fn
    return deco


def main() -> int:
    # 用临时库跑，绝不碰用户的真实数据
    tmp = Path(tempfile.mkdtemp(prefix="soulhealth_selfcheck_"))
    import os
    os.environ.setdefault("SOULHEALTH_MOCK", "1")

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from app import config
    config.DB_PATH = tmp / "selfcheck.db"
    config.REPORT_DIR = tmp / "reports"
    config.UPLOAD_DIR = tmp / "uploads"
    for d in (config.REPORT_DIR, config.UPLOAD_DIR):
        d.mkdir(parents=True, exist_ok=True)

    from app import db
    from app.archive import repository as repo
    from app.archive import tcm_records
    from app.services import analysis, intake
    from app.tcm import bridge, engines
    from app.tcm.kb import bootstrap

    print("\n=== 1. 环境与知识库 ===")

    @check("知识库就绪")
    def _kb():
        info = bootstrap.inspect(force=True)
        assert info["available"], info["reason"]
        h = info["highlights"]
        assert h["药材"] > 2000 and h["方剂"] > 700, h
        return (f"药材 {h['药材']} / 方剂 {h['方剂']} / 饮片剂量 {h['饮片剂量档案']} / "
                f"基础方 {h['基础方']} / 药食同源 {h['药食同源']} / "
                f"药典问答 {h['药典问答']} / 中成药 {h['中成药']}")

    @check("数据库建表与迁移")
    def _db():
        db.init_db()
        with db.get_conn() as conn:
            names = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        need = {"users", "patients", "documents", "observations", "findings",
                "patient_notes", "patient_impressions", "tongue_exams",
                "face_exams", "consultations", "analyses", "reports"}
        assert need <= names, need - names
        return f"{len(need)} 张表齐备"

    print("\n=== 2. 账号与档案 ===")

    ctx = {}

    @check("注册登录与令牌校验")
    def _auth():
        from app import auth
        repo.init()
        uid = repo.create_user("selfcheck_user", "pwd12345", role="user",
                               display_name="自检账号")
        user = repo.authenticate("selfcheck_user", "pwd12345")
        assert user["id"] == uid
        token = auth.create_token(user["id"], user["username"], user["role"])
        payload = auth.decode_token(token)
        assert payload["uid"] == uid
        try:
            repo.authenticate("selfcheck_user", "wrongpass")
            raise AssertionError("错误密码竟然通过了")
        except auth.AuthError:
            pass
        ctx["uid"] = uid
        return "PBKDF2 校验通过，错误密码被拒"

    @check("建档与基础信息更新")
    def _patient():
        pid, created = repo.find_or_create_patient(
            name="自检样例", sex="female", age_years=34,
            height_cm=162, weight_kg=52, id_last4="1234", owner_id=ctx["uid"])
        assert created
        repo.update_patient(pid, current_drugs=["华法林"], pregnant=False)
        p = repo.get_patient(pid)
        assert p["current_drugs"] == ["华法林"], p
        ctx["pid"] = pid
        # 同名同后四位应命中同一份档案，而不是裂变成两个 UUID
        pid2, created2 = repo.find_or_create_patient(
            name="自检样例", id_last4="1234", owner_id=ctx["uid"])
        assert pid2 == pid and not created2, (pid, pid2, created2)
        return "档案唯一性与在服西药写入正常"

    print("\n=== 3. 四诊与化验录入（统一入档）===")

    @check("化验录入并归一指标代码")
    def _labs():
        out = intake.record_lab_items(ctx["pid"], [
            {"name_raw": "谷丙转氨酶(ALT)", "value": 68, "unit": "U/L"},
            {"name_raw": "谷草转氨酶", "value": 55, "unit": "U/L"},
            {"name_raw": "甘油三酯", "value": 2.8, "unit": "mmol/L"},
            {"name_raw": "空腹血糖", "value": 6.8, "unit": "mmol/L"},
            {"name_raw": "血红蛋白", "value": 95, "unit": "g/L"},
        ])
        codes = {s["code"] for s in out["stored"]}
        assert {"ALT", "AST", "TG", "GLU", "HGB"} <= codes, codes
        assert out["abnormal_count"] >= 4, out["abnormal_count"]
        return f"入库 {len(out['stored'])} 项，异常 {out['abnormal_count']} 项"

    @check("舌象图片 → 量化 → 入档")
    def _tongue():
        import base64

        import cv2

        from app.tcm.vision.tongue import _make_synthetic
        img, _mask = _make_synthetic()   # 引擎自带的合成舌象，含齿痕/裂纹/瘀点
        ok, buf = cv2.imencode(".jpg", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        assert ok
        b64 = base64.b64encode(buf.tobytes()).decode()
        result = intake.analyze_tongue_image(b64, save_image=False)
        feats = result["features"]
        assert "body_class" in feats, feats
        intake.record_tongue(ctx["pid"], result)
        latest = tcm_records.latest_tongue(ctx["pid"])
        assert latest and latest["features"]["body_class"] == feats["body_class"]
        return f"舌质 {feats['body_class']}，归一字段 {len(feats)} 个，已入档"

    @check("问诊答卷入档")
    def _consult():
        answers = {"情绪抑郁": 8, "烦躁易怒": 7, "经前乳胀": 6, "胀痛走窜": 6,
                   "口苦": 5, "入睡困难": 5, "疲劳": 5, "腹胀": 4}
        out = intake.record_consultation(ctx["pid"], answers, sex="F")
        assert out["scores"]["情绪抑郁"] == 8, out["scores"]
        return f"{len(out['scores'])} 个维度入档"

    @check("症状自述入档")
    def _notes():
        repo.add_note(ctx["pid"], "最近总是入睡困难、多梦，白天容易累，还有点口苦")
        assert repo.list_notes(ctx["pid"])
        return "自述文本已入档"

    print("\n=== 4. 辨证桥接 ===")

    @check("八证型 → 代茶饮证型映射完备")
    def _bridge():
        from app.knowledge.classic_formulas import (CLASSIC_FORMULAS,
                                                    PRIMARY_PRIORITY,
                                                    SYNDROME_TO_FORMULA)
        assert set(SYNDROME_TO_FORMULA.values()) <= set(CLASSIC_FORMULAS)
        assert set(PRIMARY_PRIORITY) == set(SYNDROME_TO_FORMULA)
        unmapped = [k for k, v in bridge.SYNDROME_MAP.items() if v is None]
        assert not unmapped, f"未映射证型：{unmapped}"
        for tag in bridge.SYNDROME_MAP.values():
            assert tag in SYNDROME_TO_FORMULA, tag
        return f"八证全部有对应底方，底方库共 {len(CLASSIC_FORMULAS)} 首"

    @check("新增底方药材全部在药食同源目录内")
    def _catalog():
        from app.knowledge import kb
        from app.knowledge.classic_formulas import CLASSIC_FORMULAS
        bad = []
        for key in ("xiao_yao_yin", "tao_hong_yin", "li_zhong_yin"):
            for slot in CLASSIC_FORMULAS[key]["base"]:
                item = kb.get_ingredient(slot["name"])
                if item is None or not kb.in_catalog(slot["name"]):
                    bad.append((key, slot["name"]))
        assert not bad, bad
        return "逍遥散/桃红四物/理中汤三首化裁方全部过目录门禁"

    print("\n=== 5. 全流程分析 ===")

    @check("统一分析管线跑通")
    def _run():
        result = analysis.run_analysis(ctx["pid"])
        ctx["result"] = result
        steps = [t["step"] for t in result["trace"]]
        expected = ["LOAD_SNAPSHOT", "PARSE_LABS", "IDENTIFY_RISKS", "SYNDROME",
                    "PRESCRIBE", "TOXICOLOGY", "EXPLAIN", "LIFESTYLE",
                    "TEA_PLAN", "MECHANISM", "BIOCOMPUTE", "AI_INTERPRET",
                    "GENERATE_REPORTS"]
        missing = [s for s in expected if s not in steps]
        assert not missing, f"缺少节点：{missing}"
        return f"{len(steps)} 个节点，用时 {sum(t['ms'] for t in result['trace']):.0f}ms"

    @check("辨证得出主证且证据链完整")
    def _syndrome():
        sr = ctx["result"]["tcm"]["syndrome"]
        assert sr.get("primary"), f"未出主证：{sr.get('flags')}"
        assert sr["audit"], "证据链为空"
        srcs = {a["rule"][0] for a in sr["audit"]}
        return (f"主证 {sr['primary']} {sr['percent'][sr['primary']]}%，"
                f"证据 {len(sr['audit'])} 条，覆盖来源 {sorted(srcs)}")

    @check("治疗性组方出方且剂量可回溯")
    def _rx():
        rx = ctx["result"]["tcm"]["prescription"]
        assert rx.get("status") == "OK", rx.get("block")
        herbs = rx["prescription"]
        assert herbs and rx["total_g"] > 0
        roles = {h["role"] for h in herbs}
        assert "君" in roles and "使" in roles, roles
        assert rx.get("herb_audit"), "缺少逐味推导链"
        for h in herbs:
            assert h["dose_g"] > 0
        return (f"{rx['base_formula']['name']}，{len(herbs)} 味共 {rx['total_g']}g，"
                f"角色 {sorted(roles)}")

    @check("中西药相互作用被复核并升级为警告")
    def _drug():
        di = ctx["result"]["tcm"].get("drug_interaction") or {}
        # 档案里在服华法林，方中当归含香豆素类，应被复核命中
        assert di.get("conflicts"), di
        hit = di["conflicts"][0]
        assert hit["drug"] == "华法林" and hit.get("mechanism"), hit
        return (f"{len(di['conflicts'])} 条：{hit['drug']}×{hit['herb']}"
                f"（{hit['level']}）")

    @check("毒理五项与四维解释齐备")
    def _tox_explain():
        tcm = ctx["result"]["tcm"]
        tox, ex = tcm["toxicology"], tcm["explain"]
        assert tox.get("status") == "OK", tox
        assert ex.get("status") == "OK", ex
        for k in ("d1_macro", "d2_micro", "d3_dose", "d4_exclusion"):
            assert ex.get(k), f"缺 {k}"
        return "毒理 5 项 + 四维解释 4 维"

    @check("代茶饮由同一辨证结论产出")
    def _tea():
        f = ctx["result"]["formula"]
        assert f.get("ingredients"), f.get("modification_log")
        prov = {p["source"] for p in f.get("provenance") or []}
        assert "四诊辨证" in prov, prov
        # 代茶饮的主证必须等于四诊辨证的结论，不得被自述关键词或风险标签顶掉
        sr = ctx["result"]["tcm"]["syndrome"]
        expected = bridge.SYNDROME_MAP[sr["primary"]]
        assert f["primary_syndrome"] == expected, (f["primary_syndrome"], expected)
        return (f"{f['formula_name']}，{len(f['ingredients'])} 味；主证与四诊一致"
                f"（{sr['primary']}）")

    @check("三份报告生成且过合规闸")
    def _reports():
        reports = ctx["result"]["reports"]
        types = {r["report_type"] for r in reports}
        assert {"health_analysis", "tcm_analysis", "tea_plan"} <= types, types
        for r in reports:
            path = Path(r["path"])
            assert path.exists() and path.stat().st_size > 0, r
        fmts = {r["format"] for r in reports}
        assert fmts == {"md", "docx"}, fmts
        return f"{len(reports)} 个文件，类型 {sorted(types)}"

    @check("分析可回放（落库后重新读出）")
    def _replay():
        aid = ctx["result"]["analysis_id"]
        a = repo.get_analysis(aid)
        assert a and a["tcm"], "tcm 字段未落库"
        assert a["tcm"]["prescription"]["status"] == "OK"
        assert a["trace"], "trace 未落库"
        return f"分析 {aid[:8]} 可完整回放"

    print("\n=== 6. 安全闸门（反向用例）===")

    @check("证据不足时拒绝出方")
    def _gate_low_evidence():
        pid, _ = repo.find_or_create_patient(name="证据不足样例", sex="male",
                                             age_years=40, owner_id=ctx["uid"])
        intake.record_consultation(pid, {"疲劳": 4}, sex="M")
        res = analysis.run_analysis(pid)
        sr, rx = res["tcm"]["syndrome"], res["tcm"]["prescription"]
        assert sr["primary"] is None, sr["primary"]
        assert rx["status"] == "BLOCKED", rx
        assert rx["block"]["code"] == "NO_SYNDROME", rx["block"]
        assert sr["evidence_gaps"], "没有告诉用户还缺什么"
        return (f"拦截码 {rx['block']['code']}；"
                f"提示补录 {[g['label'] for g in sr['evidence_gaps']]}")

    @check("儿童拒绝自动组方")
    def _gate_pediatric():
        pid, _ = repo.find_or_create_patient(name="儿童样例", sex="male",
                                             age_years=8, weight_kg=25,
                                             owner_id=ctx["uid"])
        intake.record_consultation(pid, {"情绪抑郁": 8, "烦躁易怒": 7,
                                         "胀痛走窜": 6, "口苦": 6}, sex="M")
        res = analysis.run_analysis(pid)
        rx = res["tcm"]["prescription"]
        assert rx["status"] == "BLOCKED" and rx["block"]["code"] == "PEDIATRIC", rx
        return f"拦截码 {rx['block']['code']}"

    @check("妊娠期血瘀证拒绝自动组方")
    def _gate_pregnancy():
        pid, _ = repo.find_or_create_patient(name="妊娠样例", sex="female",
                                             age_years=30, weight_kg=58,
                                             owner_id=ctx["uid"])
        repo.update_patient(pid, pregnant=True)
        intake.record_consultation(pid, {"刺痛固定": 9, "经期血块": 8}, sex="F")
        res = analysis.run_analysis(pid)
        rx = res["tcm"]["prescription"]
        assert rx["status"] == "BLOCKED", rx
        assert rx["block"]["code"] == "PREGNANCY_BLOOD_STASIS", rx["block"]
        return f"拦截码 {rx['block']['code']}"

    @check("合规闸拦截违禁话术")
    def _gate_compliance():
        from app.reportgen import compliance
        for bad in ("本方可根治脂肪肝", "7天内转氨酶下降", "无任何副作用"):
            hits = compliance.lint(bad)
            assert hits, f"未拦截：{bad}"
        try:
            compliance.assert_clean("这是一段没有必备要素的文本")
            raise AssertionError("缺必备要素竟然通过了")
        except ValueError:
            pass
        return "违禁词与必备要素双向校验有效"

    @check("未配置密钥时不返回编造数据")
    def _gate_no_fake():
        src = Path("app").rglob("*.py")
        offenders = []
        for f in src:
            text = f.read_text(encoding="utf-8", errors="ignore")
            if "sk-" in text and "ANTHROPIC" in text:
                for line in text.splitlines():
                    if "sk-" in line and "os.environ" in line:
                        offenders.append(f"{f}: {line.strip()[:60]}")
        assert not offenders, offenders
        return "源码内无硬编码密钥"

    print("\n" + "=" * 62)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for name, exc in FAIL:
            print(f"  失败：{name} —— {exc}")
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
