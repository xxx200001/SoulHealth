"""中医知识库自检与自举。

问题背景
--------
原 TongueDiag 的 pipeline.py 在第一次调用组方时才去找 tcm_kb.sqlite，找不到就抛
FileNotFoundError，接口直接 500；而 start.bat 从不建库，仓库里也没有这个文件。
结果是"装好就报错"。

本模块把这件事提前到启动阶段并给出确定性结果：

1. check()      —— 检查库是否存在、关键表是否齐、数据量是否够，返回结构化诊断。
2. ensure()     —— 启动时调用。库齐全则直接返回；缺失且允许自举，则用三个 build
                   脚本里的内置种子建一个最小可用库（无方剂图谱与药典 QA，
                   辨证/组方/毒理/剂量校验全部可用，只是解释链条会短一截）。

完整库（约 20 MB）由 data/tcm_kb.sqlite 提供，随仓库分发。
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Optional

# 组方与解释链路真正读取的表；缺任何一张即视为库不可用
REQUIRED_TABLES = (
    "herb_pharm",           # 饮片药典剂量档案
    "base_formula",         # 基础方
    "base_formula_herb",    # 基础方组成
    "safety_incompat",      # 十八反十九畏等配伍禁忌
    "safety_flag",          # 单味风险标记（妊娠禁忌/毒性/马兜铃酸）
    "food_herb",            # 药食同源目录
    "syndrome_formula_map",  # 证型→基础方映射
    "syndrome_pathology",   # 证型病机（解释引擎 D1）
    "herb_mechanism",       # 指标级机制证据（解释引擎 D2）
    "herb_dose_risk",       # 超量风险（解释引擎 D3）
)

# 完整库特有的表：有则解释链条完整，无则降级但不报错
RICH_TABLES = ("chp_qa", "prescription_herb", "herb_function", "nmpa_product",
               "classic_triple", "herb_ratio", "herb_classic_dose")

_KB_DIR = Path(__file__).resolve().parent


def _tables(db_path: Path) -> set:
    with sqlite3.connect(str(db_path)) as con:
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


def _count(db_path: Path, table: str) -> int:
    try:
        with sqlite3.connect(str(db_path)) as con:
            return con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    except sqlite3.Error:
        return 0


def check(db_path) -> dict:
    """返回知识库诊断。ready=False 时 missing 列出缺失的表。"""
    db_path = Path(db_path)
    if not db_path.exists():
        return {"ready": False, "exists": False, "path": str(db_path),
                "missing": list(REQUIRED_TABLES), "level": "none",
                "stats": {}, "message": "知识库文件不存在"}

    have = _tables(db_path)
    missing = [t for t in REQUIRED_TABLES if t not in have]
    rich_missing = [t for t in RICH_TABLES if t not in have]
    stats = {t: _count(db_path, t) for t in REQUIRED_TABLES if t in have}
    stats.update({t: _count(db_path, t) for t in RICH_TABLES if t in have})

    if missing:
        level, message = "broken", f"缺少必需表：{'、'.join(missing)}"
    elif rich_missing or stats.get("chp_qa", 0) == 0:
        level, message = "minimal", "最小可用库（缺方剂图谱/药典原文，解释链条较短）"
    else:
        level, message = "full", "完整知识库"

    return {"ready": not missing, "exists": True, "path": str(db_path),
            "missing": missing, "level": level, "stats": stats,
            "message": message}


def _build_minimal(db_path: Path) -> None:
    """用三个 build 脚本的内置种子建最小可用库。

    build_base.py 的六路外部数据源（方剂图谱/药典 QA/NMPA 名录/经典本体…）
    在分发包里不存在，因此这里只取它的 DDL 建空 schema，再依次跑
    build_dosage / build_explain —— 这两个脚本的数据来自脚本内置的
    [TEXT]/[GOV] 种子，不依赖外部文件。
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)

    ddl_src = (_KB_DIR / "build_base.py").read_text(encoding="utf-8")
    m = re.search(r'^DDL\s*=\s*"""(.*?)"""', ddl_src, re.S | re.M)
    if not m:
        raise RuntimeError("build_base.py 中未找到 DDL 定义，无法自举知识库")
    with sqlite3.connect(str(db_path)) as con:
        con.executescript(m.group(1))
        con.commit()

    # 两个 build 脚本以模块级 DB 常量取库路径，用 runpy 注入 argv 执行
    import runpy
    import sys

    for script in ("build_dosage.py", "build_explain.py"):
        old_argv = sys.argv
        sys.argv = [str(_KB_DIR / script), str(db_path)]
        try:
            runpy.run_path(str(_KB_DIR / script), run_name="__main__")
        finally:
            sys.argv = old_argv


def ensure(db_path, autobuild: bool = True, verbose: bool = True) -> dict:
    """启动期调用。返回 check() 的诊断结果（自举后重新体检）。"""
    db_path = Path(db_path)
    report = check(db_path)
    if report["ready"]:
        if verbose:
            n = report["stats"]
            print(f"[知识库] {report['message']}："
                  f"饮片 {n.get('herb_pharm', 0)} 味 / 基础方 {n.get('base_formula', 0)} 首 / "
                  f"配伍禁忌 {n.get('safety_incompat', 0)} 条 / 药食同源 {n.get('food_herb', 0)} 味")
        return report

    if not autobuild:
        if verbose:
            print(f"[知识库] 不可用：{report['message']}；已关闭自举"
                  f"（SOULHEALTH_TCM_KB_AUTOBUILD=0），中医链路将不可用。")
        return report

    if verbose:
        print(f"[知识库] {report['message']}，正在用内置种子自举最小可用库…")
    try:
        if report["exists"] and report["level"] == "broken":
            db_path.rename(db_path.with_suffix(".sqlite.broken"))
        _build_minimal(db_path)
    except Exception as exc:                       # noqa: BLE001 — 启动期不因此崩溃
        if verbose:
            print(f"[知识库] 自举失败：{exc}")
        return check(db_path)

    report = check(db_path)
    if verbose:
        print(f"[知识库] 自举完成：{report['message']}")
    return report


if __name__ == "__main__":                          # python -m app.tcm.kb.bootstrap
    import json
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        Path(__file__).resolve().parents[3] / "data" / "tcm_kb.sqlite"
    print(json.dumps(ensure(target), ensure_ascii=False, indent=2))
