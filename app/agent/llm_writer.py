"""LLM 文字润色钩子（可选增强，模板文案为主、LLM 为辅）。

设计原则：报告内容由结构化数据 + 模板确定性生成（保证合规、可复现），
LLM 仅用于润色个别叙述段落。MOCK / unconfigured 模式直接透传模板文案。
润色输出会再过一遍 compliance.lint，任何违规词直接回退原文——
即使模型"发挥"，也出不了合规红线。

默认关闭：报告的可复现性优先于文采。需要时置 SOULHEALTH_POLISH=1 开启，
generator 会在写盘前对纯叙述段落逐段调用 polish_blocks()。开关状态由
config.REPORT_POLISH 提供，不在本模块二次读环境变量。
"""
from __future__ import annotations

from typing import Iterable, List, Tuple

from .. import config

_SYSTEM = (
    "你是医疗健康文案润色助手。仅对给定段落做语言润色：更通顺、更易读。"
    "硬性红线：不得新增任何疗效承诺、时间承诺、数字承诺；不得出现"
    "速效/根治/治愈/彻底/无任何副作用/保证 等绝对化表述；"
    "不得删除任何就医、随访、禁忌相关内容。只输出润色后的文本。"
)

# 短句润色收益低、风险高（容易被改写成承诺句），低于此长度直接跳过
_MIN_CHARS = 40


def available() -> bool:
    """当前配置下润色是否可用。不可用时 polish() 恒等透传。"""
    return config.LLM_MODE == "real" and bool(config.ANTHROPIC_API_KEY)


def polish(text: str) -> str:
    """润色单段文本。任何异常、违规或空结果都回退原文，绝不阻断报告生成。"""
    if not available() or not (text or "").strip():
        return text
    try:
        import anthropic
        from ..reportgen import compliance

        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY,
                                     base_url=config.ANTHROPIC_BASE_URL)
        resp = client.messages.create(
            model=config.LLM_MODEL, max_tokens=1200, system=_SYSTEM,
            messages=[{"role": "user", "content": text}],
        )
        out = "".join(b.text for b in resp.content
                      if getattr(b, "type", "") == "text").strip()
        if not out or compliance.lint(out):
            return text  # 润色结果违规或为空 → 回退模板原文
        return out
    except Exception:
        return text  # 任何异常都不阻断报告生成


def polish_blocks(blocks: Iterable[tuple]) -> List[tuple]:
    """按 docx_writer 的 block 列表逐段润色。

    只处理 ("p", str) 且长度达标的纯叙述段：标题、表格、要点、提示框
    都承载结构化事实与合规声明，一律原样保留。
    """
    out: List[tuple] = []
    for block in blocks:
        if (block[0] == "p" and isinstance(block[1], str)
                and len(block[1]) >= _MIN_CHARS):
            out.append(("p", polish(block[1])))
        else:
            out.append(block)
    return out


def describe() -> Tuple[bool, str]:
    """(是否启用, 人话说明) —— 供 /api/health 与报告脚注如实标注。"""
    if not config.REPORT_POLISH:
        return False, "未开启（报告文案由模板确定性生成）"
    if not available():
        return False, "已开启但当前无可用模型密钥，本次按模板原文输出"
    return True, f"已开启（{config.LLM_MODEL}，润色结果仍过合规闸）"
