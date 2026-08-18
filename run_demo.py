"""一键端到端演示（命令行版）。

真实模式：配置 ANTHROPIC_API_KEY 后运行，图片抽取 / 问答 / AI 解读走真实模型；
离线演示：未配置密钥时本脚本自动显式开启 SOULHEALTH_MOCK=1 并提示。

演示数据的种入逻辑在 app/demo.py（与前端「载入演示患者」按钮共用一份），
本脚本只负责：定模式 → 种数据 → 跑单入口分析 → 打印 trace 与报告产物。

用法：
  python run_demo.py            # 找回/建立演示患者档案并分析
  python run_demo.py --fresh    # 先清空数据库再演示
图形界面请运行 python run.py 后打开 http://127.0.0.1:8001/
"""
import os
import sys

# 必须在导入 app 之前决定模式（config 在导入时读取环境变量）
if not os.getenv("ANTHROPIC_API_KEY", "").strip() and \
   os.getenv("SOULHEALTH_MOCK", "").strip() != "1":
    os.environ["SOULHEALTH_MOCK"] = "1"
    print("[提示] 未配置 ANTHROPIC_API_KEY：本次演示自动显式开启 MOCK 模式"
          "（演示样例数据，报告会如实标注）。配置密钥后重跑即为真实抽取。\n")

from app import config, demo                      # noqa: E402
from app.agent import orchestrator                # noqa: E402
from app.archive import repository as repo        # noqa: E402
from app.tcm.kb import bootstrap as kb_bootstrap  # noqa: E402


def main() -> None:
    if "--fresh" in sys.argv and config.DB_PATH.exists():
        config.DB_PATH.unlink()

    repo.init()
    kb = kb_bootstrap.ensure(config.TCM_KB_PATH, autobuild=config.TCM_KB_AUTOBUILD)
    print(f"运行环境：{config.runtime_info()}")
    print(f"中医知识库：{kb.get('level')} —— {kb.get('message')}\n")

    # ① 建档并种入双链演示数据（幂等，重复运行找回同一份档案）
    r = demo.seed()
    p = repo.get_patient(r["patient_id"])
    s = r["seeded"]
    print(f"① {'建档完成' if r['created'] else '找回既有档案'}："
          f"{p['name']}（{p['pseudonym']}）")
    fed = []
    if s["documents"]:
        fed.append(f"演示图片摄取 {s['documents']} 份")
    if s["observations"]:
        fed.append(f"化验指标 {s['observations']} 条")
    if s["finding"]:
        fed.append("影像所见 1 项")
    if s["impression"]:
        fed.append("诊断提示 1 条")
    for k, label in (("tongue", "舌象"), ("face", "面象"), ("inquiry", "问诊")):
        if s[k]:
            fed.append(label)
    print(f"② 本次种入：{'、'.join(fed) if fed else '档案数据已齐备，无需补种'}")

    # ② 单入口分析：中医辨证链 + 现代医学链一次跑完
    result = orchestrator.run_analysis(r["patient_id"])
    print("\n③ 分析 trace：")
    for st in result["trace"]:
        flag = "" if st.get("status", "done") == "done" else f" [{st['status']}]"
        print(f"   [{st['step']:<17}] {st['title']}：{st['detail']}"
              f"（{st['ms']} ms）{flag}")

    print("\n④ 报告产物：")
    for rep in result["reports"]:
        if rep.get("error"):
            print(f"   {rep['title']}：{rep['error']}")
        else:
            print(f"   {rep['title']}（{rep['format']}）→ {rep['path']}")

    print("\n完成 ✔  图形界面：python run.py 后访问 "
          f"http://127.0.0.1:{config.PORT}/")


if __name__ == "__main__":
    main()
