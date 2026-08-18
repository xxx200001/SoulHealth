"""EVO2 序列打分核心。

单独抽出来的原因：原先内联在 evo2_server 里的打分逻辑对 evo2 官方 API
是靠猜的，且有一处会**静默算出错误分数**——

    base_to_idx = {'A': 0, 'C': 1, 'G': 2, 'T': 3}
    total_ll += log_probs[i, idx].item()

Evo2 用的是字节级词表，碱基 token id 就是其 ASCII 码（A=65、C=67、G=71、
T=84），不是 0–3。拿 0–3 去索引 log_probs 取到的是词表里另外四个不相干
token 的对数概率，累加出来的 ΔlogL 看着像模像样，其实与该变异无关。
这类"跑得通但数值是错的"比直接报错更危险，所以按官方接口重写。

打分优先级
----------
1. ``model.score_sequences([...])``——官方推荐接口，BRCA1 变异效应示例即用此法，
   返回每条序列的平均每 token 对数似然。
2. 手动前向：``tokenizer.tokenize`` 拿真实 token id，用这些 id 去索引
   ``log_softmax`` 的结果，teacher-forcing 累加。与 1 的差别只在
   平均/求和，故一并回报 ``scoring_method`` 与 ``normalized``，
   让上层知道 ΔlogL 的量纲。

两条路径都拿不到时抛异常，由服务层转成 500，**不返回任何兜底分数**。
"""
from __future__ import annotations

import logging
from typing import List, Tuple

log = logging.getLogger("evo2_scoring")


def score_sequences(model, seqs: List[str]) -> Tuple[List[float], str, bool]:
    """给一批序列打分。

    返回 (scores, scoring_method, normalized)：
      scores          每条序列的对数似然
      scoring_method  实际走的哪条路径，回给调用方如实标注
      normalized      True 表示"平均每 token"，False 表示整条序列求和
    """
    # ---- 路径 1：官方 score_sequences ----
    if hasattr(model, "score_sequences"):
        try:
            scores = model.score_sequences(list(seqs))
            out = [float(s.item() if hasattr(s, "item") else s) for s in scores]
            if len(out) == len(seqs):
                return out, "evo2.score_sequences", True
            log.warning("score_sequences 返回条数不匹配，改走手动前向")
        except Exception as exc:                      # noqa: BLE001
            log.warning("score_sequences 调用失败（%s），改走手动前向", exc)

    # ---- 路径 2：手动前向 + teacher forcing ----
    return [_manual_ll(model, s) for s in seqs], "manual_forward_sum", False


def _manual_ll(model, seq: str) -> float:
    """teacher-forcing 累加整条序列的 log-likelihood。

    关键点：用 tokenizer 自己产出的 token id 去索引 log_probs，
    不再手搓 A/C/G/T→0/1/2/3 的映射（那是错的，见模块开头说明）。
    """
    import torch
    import torch.nn.functional as F

    if not hasattr(model, "tokenizer"):
        raise RuntimeError("模型对象没有 tokenizer，无法手动打分")

    ids = model.tokenizer.tokenize(seq)
    if hasattr(ids, "tolist"):
        ids = ids.tolist()
    ids = list(ids)
    if len(ids) < 2:
        raise ValueError(f"序列过短，token 数 ={len(ids)}")

    device = getattr(model, "device", None) or "cuda:0"
    input_ids = torch.tensor(ids, dtype=torch.int).unsqueeze(0).to(device)

    with torch.no_grad():
        outputs = model(input_ids)
        logits = outputs[0] if isinstance(outputs, (tuple, list)) else outputs
        if isinstance(logits, dict):
            logits = logits.get("logits", logits.get("output"))
        if logits is None:
            raise RuntimeError("模型前向未返回 logits")
        if logits.dim() == 3:
            logits = logits[0]                        # [seq_len, vocab]

        log_probs = F.log_softmax(logits[:-1].float(), dim=-1)
        targets = torch.tensor(ids[1:], dtype=torch.long,
                               device=log_probs.device)
        n = min(log_probs.shape[0], targets.shape[0])
        picked = log_probs[:n].gather(1, targets[:n].unsqueeze(1)).squeeze(1)
        return float(picked.sum().item())
