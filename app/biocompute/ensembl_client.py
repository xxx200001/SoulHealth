"""Ensembl REST 客户端：按 rsID 真实查询变异位点、等位基因与参考序列窗口。

- GET {ENSEMBL_API}/variation/human/{rsid}   → 染色体位置、allele_string（如 C/G）
- GET {ENSEMBL_API}/sequence/region/human/{chr}:{start}..{end} → 参考序列
公开接口、免密钥。EVO2 打分即使不可用（无 NVIDIA key），变异的
真实基因组位置与等位基因也能如实展示。具备请求重试、标准 User-Agent 及离线降级保障。

仅标准库 urllib；所有失败路径优雅处理，不抛异常、不阻断分析。
"""
from __future__ import annotations

import json
import ssl
import time
import urllib.request
from typing import Optional, Tuple

from .. import config

_TIMEOUT = 15
FLANK = 60  # 变异位点两侧各取 60bp → 121bp 窗口

# 证书校验保持开启。原实现关掉了 hostname 与证书校验（CERT_NONE），
# 等于放弃了对 Ensembl 域名的身份验证——中间人可以任意替换返回的
# 基因组坐标与序列，而这些数据会直接进 EVO2 打分。
_SSL_CTX = ssl.create_default_context()

# 离线坐标表：仅在 Ensembl 不可达时提供位点坐标，**不含参考序列**。
#
# 原实现在这里还放了两条"ref_seq"，并在序列接口失败时拿它顶替真实窗口，
# 同时把 source 标成 "ensembl"、note 留空。那两条序列是把一段 34–38bp 的
# motif 平铺重复出来的，长度也不是声称的 121bp，根本不是 GRCh38 的实际序列。
# 拿它送进 EVO2 打分，得到的 ΔlogL 与该变异毫无关系，却会被当成真实结果
# 展示和入库。序列已全部删除：拿不到真序列就不打分。
#
# 坐标本身是可核对的公开事实，保留作降级用途，但会如实标注
# source=offline_table，且这些坐标未经本地核验，请以 dbSNP 为准。
_FALLBACK_VARIANTS = {
    "rs738409": {
        "chrom": "22", "pos": 43928847, "ref": "C", "alts": ["G"],
        "allele_string": "C/G", "assembly": "GRCh38",
    },
    "rs58542926": {
        "chrom": "19", "pos": 19269707, "ref": "C", "alts": ["T"],
        "allele_string": "C/T", "assembly": "GRCh38",
    },
}


def _http_json(url: str):
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    req = urllib.request.Request(url, headers=headers)
    last_exc = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_SSL_CTX) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last_exc = exc
            time.sleep(0.5)
    raise last_exc


def variant_info(rsid: str) -> Tuple[Optional[dict], Optional[str]]:
    """rsID → {chrom, pos, ref, alts, allele_string}（GRCh38）。"""
    try:
        data = _http_json(f"{config.ENSEMBL_API}/variation/human/{rsid}"
                          "?content-type=application/json")
        mappings = data.get("mappings") or []
        if mappings:
            m = mappings[0]
            alleles = str(m.get("allele_string") or "").split("/")
            if len(alleles) >= 2 and len(alleles[0]) == 1 and len(alleles[1]) == 1:
                return {
                    "chrom": str(m.get("seq_region_name")),
                    "pos": int(m.get("start")),
                    "ref": alleles[0].upper(),
                    "alts": [a.upper() for a in alleles[1:]],
                    "allele_string": m.get("allele_string"),
                    "assembly": m.get("assembly_name") or "GRCh38",
                    "source": "ensembl",
                }, None
    except Exception:
        pass

    # Ensembl 不可达时退到离线坐标表，并如实标注来源——调用方据此决定
    # 要不要展示"实时解析"字样，不能让降级数据冒充线上查询结果
    fb = _FALLBACK_VARIANTS.get(rsid)
    if fb:
        return {**{k: v for k, v in fb.items()},
                "source": "offline_table"}, None

    return None, f"Ensembl 变异查询暂不可用 ({rsid})"


def region_sequence(chrom: str, start: int, end: int) -> Tuple[Optional[str], Optional[str]]:
    try:
        data = _http_json(
            f"{config.ENSEMBL_API}/sequence/region/human/{chrom}:{start}..{end}"
            "?content-type=application/json")
        seq = (data.get("seq") or "").upper()
        if seq:
            return seq, None
    except Exception:
        pass

    return None, "Ensembl 序列服务暂不可用"


def variant_windows(rsid: str, flank: int = FLANK) -> Tuple[Optional[dict], Optional[str]]:
    """rsID → 变异位点真实上下文序列窗口（ref_seq / alt_seq）。"""
    info, err = variant_info(rsid)
    if info is None:
        return None, err

    seq, seq_err = region_sequence(info["chrom"], info["pos"] - flank,
                                   info["pos"] + flank)
    if seq is None:
        # 没有真实序列就不造一条顶替。上层会据此把 EVO2 标成 skipped，
        # 位点坐标照常返回给用户看。
        return None, (seq_err or "无法获取基因组参考序列窗口")

    center = flank
    if len(seq) <= center:
        center = len(seq) // 2

    # 一致性核验：窗口中心的碱基必须等于该 rsID 声明的 ref 等位基因。
    # 对不上说明坐标、组装版本或链方向有问题，此时替换出来的 alt_seq
    # 是错的，宁可不打分也不能拿去算 ΔlogL。
    center_base = seq[center] if center < len(seq) else ""
    if center_base.upper() != str(info["ref"]).upper():
        return None, (f"参考序列窗口中心碱基为 {center_base}，"
                      f"与 {rsid} 声明的参考等位基因 {info['ref']} 不一致"
                      f"（可能是坐标或组装版本不匹配），本次不做序列打分")

    alt = info["alts"][0]
    alt_seq = seq[:center] + alt + seq[center + 1:]
    note = None
    if info.get("source") == "offline_table":
        note = ("变异坐标取自离线表（Ensembl 变异接口当时不可达），"
                "非实时查询结果")
    return {
        "rsid": rsid, "chrom": info["chrom"], "pos": info["pos"],
        "ref": info["ref"], "alt": alt, "assembly": info["assembly"],
        "ref_seq": seq, "alt_seq": alt_seq, "window_bp": len(seq),
        "note": note, "source": info.get("source", "ensembl"),
    }, None
