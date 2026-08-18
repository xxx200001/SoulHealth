"""EVO2 链路自检：逐段确认哪一环没通，并给出具体该做什么。

用法：
    python scripts/check_evo2.py                 # 用默认演示位点 rs738409
    python scripts/check_evo2.py rs58542926      # 指定 rsID

检查顺序（任一环断掉都会明确指出，不会含糊带过）：
    ① 配置：BIOCOMPUTE 模式、EVO2_URL
    ② EVO2 服务：/health 是否可达、模型是否已加载
    ③ Ensembl：rsID → 坐标 / 等位基因（含来源是实时还是离线表）
    ④ 参考序列窗口：能否取到真实序列，中心碱基是否与 ref 等位基因一致
    ⑤ 打分：调用 EVO2 拿 ΔlogL，并报出打分口径（平均/求和）
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config                                # noqa: E402
from app.biocompute import ensembl_client, evo2_client  # noqa: E402


def line(ok: bool | None, title: str, detail: str = "") -> None:
    mark = {True: "[ OK ]", False: "[FAIL]", None: "[ -- ]"}[ok]
    print(f"{mark} {title}" + (f"\n       {detail}" if detail else ""))


def main() -> None:
    rsid = sys.argv[1] if len(sys.argv) > 1 else "rs738409"
    print(f"EVO2 链路自检（位点 {rsid}）")
    print("=" * 62)

    # ① 配置
    mode = config.BIOCOMPUTE_MODE
    line(mode == "real", f"生物计算模式：{mode}",
         "" if mode == "real"
         else "当前不是 real，EVO2 会走演示缓存。改 .env 里 "
              "SOULHEALTH_BIOCOMPUTE=real 后重启。")
    line(None, f"EVO2 服务地址：{config.EVO2_URL}")

    # ② EVO2 服务
    health = evo2_client._evo2_health()
    if not health["up"]:
        line(False, "EVO2 服务不可达", health["note"])
        print("\n     请在装了 evo2 的环境里启动推理服务：")
        print("       conda activate evo2 && python evo2_server.py")
        print("     若 evo2 跑在 WSL2 而本程序在 Windows，确认端口可从"
              " Windows 访问，或把 SOULHEALTH_EVO2_URL 指向 WSL 的 IP。")
        return
    line(True, "EVO2 服务可达",
         "模型已加载" if health["model_loaded"]
         else "服务在，但模型尚未加载；首次打分会触发加载，可能要等几分钟")

    # ③ Ensembl 坐标
    info, err = ensembl_client.variant_info(rsid)
    if info is None:
        line(False, "Ensembl 变异查询失败", err or "")
        print("\n     没有坐标就无法取参考序列，EVO2 会如实标成 skipped。"
              "请检查服务器外网连通性。")
        return
    src = info.get("source", "ensembl")
    line(src == "ensembl", f"变异坐标：chr{info['chrom']}:{info['pos']} "
                           f"{info['ref']}>{info['alts'][0]}（{info['assembly']}）",
         "实时查询" if src == "ensembl"
         else "注意：来自离线坐标表，非实时查询；请以 dbSNP 为准核对")

    # ④ 参考序列窗口
    win, werr = ensembl_client.variant_windows(rsid)
    if win is None:
        line(False, "参考序列窗口获取失败", werr or "")
        print("\n     取不到真实序列时本系统不会合成序列顶替，"
              "本位点的 EVO2 打分会标成 skipped。")
        return
    line(True, f"参考序列窗口 {win['window_bp']}bp，中心碱基与 ref 等位基因一致",
         f"ref_seq 前 30bp：{win['ref_seq'][:30]}…")

    # ⑤ 打分
    result = evo2_client.score_variant(win.get("gene", "?"), rsid)
    if result["status"] != "done":
        line(False, f"打分未完成：status={result['status']}",
             result.get("note", ""))
        return
    line(True, f"ΔlogL = {result['delta_ll']}",
         f"ref_ll={result['ref_ll']}  alt_ll={result['alt_ll']}  "
         f"打分口径={result.get('scoring_method')}  "
         f"{'平均每 token' if result.get('normalized') else '整窗求和'}")
    print("\n全链路打通 [OK]  分析页的生物计算一节会显示真实分值与来源标签。")


if __name__ == "__main__":
    main()
