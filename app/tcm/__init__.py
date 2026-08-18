"""中医辨证溯源引擎包。

模块分工
  lab_mapper        体检指标标准化 + G0–G3 异常分级
  consultation      问诊量表（三种题型）与作答校验
  syndrome          八证型加权辨证（舌/面/化验/症状四路证据）
  dosage            0.1g 级精准组方（药典剂量 + 配伍禁忌 + 肝肾折减）
  explain           四维解释（宏观病机/微观机制/剂量依据/排除性说明）
  toxicology        毒理与安全边界
  drug_interaction  中西药相互作用
  lifestyle         饮食起居运动干预
  vision/           舌诊、面诊图像量化
  adapters          量化结果 → 辨证引擎的字段适配（唯一转换点）
  engine            全流程编排（TCMEngine）
  kb/               知识库构建与自检自举
"""
from .engine import TCMEngine, TCMEngineUnavailable, get_engine  # noqa: F401
