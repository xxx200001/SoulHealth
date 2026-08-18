"""报告生成入口：由分析上下文产出多份文档 × 两种格式（docx + md），
经合规闸校验后写盘并登记 reports 表。

三份报告分工互不重叠：
  health_analysis  《个性化健康分析报告》—— 现代医学链：风险、机制、生物计算
  tcm_prescription 《中医辨证与调理组方报告》—— 中医链：辨证、精准组方、四维解释
  tea_plan         《药食同源代茶饮建议》—— 食养级日常调理

每份报告只在其数据齐备时生成，缺数据即跳过（不硬凑内容）。
"""
from __future__ import annotations

from .. import config
from ..agent import llm_writer
from ..archive import repository as repo
from . import compliance, docx_writer, health_report, tcm_report, tea_plan

TITLES = {
    "health_analysis": "个性化健康分析报告",
    "tcm_prescription": "中医辨证与调理组方报告",
    "tea_plan": "药食同源代茶饮建议",
}

# (类型, 标题, 构建函数, 生成条件)
_BUILDERS = [
    ("health_analysis", TITLES["health_analysis"], health_report.build_blocks,
     lambda ctx: True),
    ("tcm_prescription", TITLES["tcm_prescription"], tcm_report.build_blocks,
     tcm_report.available),
    ("tea_plan", TITLES["tea_plan"], tea_plan.build_blocks,
     lambda ctx: bool((ctx.get("formula") or {}).get("ingredients"))),
]


def generate_all(ctx: dict) -> list:
    """ctx 需含 analysis_id / patient_id / snapshot / risk_tags / mechanism_chain /
    biocompute_plan / formula / tcm。返回 reports 行列表（含 report_id 与下载地址）。"""
    out = []
    aid8 = ctx["analysis_id"][:8]
    for rtype, title, builder, condition in _BUILDERS:
        try:
            if not condition(ctx):
                continue
            blocks = builder(ctx)
        except Exception as exc:                      # noqa: BLE001
            # 单份报告构建失败不影响其余报告；错误留在返回值里，前端可见
            out.append({"report_id": None, "report_type": rtype, "title": title,
                        "format": None, "path": None, "download_url": None,
                        "error": f"生成失败：{exc}"})
            continue

        # 可选润色：只动纯叙述段，失败或违规自动回退模板原文（见 llm_writer）
        if config.REPORT_POLISH:
            blocks = llm_writer.polish_blocks(blocks)

        md_text = docx_writer.blocks_to_markdown(blocks)
        compliance.assert_clean(md_text, doc_name=title)   # 合规闸：违规即阻断

        md_path = config.REPORT_DIR / f"{rtype}_{aid8}.md"
        md_path.write_text(md_text, encoding="utf-8")
        docx_path = config.REPORT_DIR / f"{rtype}_{aid8}.docx"
        docx_writer.blocks_to_docx(blocks, docx_path, title=title)

        for fmt, path in (("md", md_path), ("docx", docx_path)):
            rid = repo.save_report(ctx["analysis_id"], ctx["patient_id"],
                                   rtype, fmt, str(path))
            out.append({"report_id": rid, "report_type": rtype, "title": title,
                        "format": fmt, "path": str(path),
                        "download_url": f"/api/reports/{rid}/download"})
    return out
