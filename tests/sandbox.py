"""测试沙箱：把数据库与报告目录改到临时路径。

移植自 bio 的几个测试原本直接读写 data/soulhealth.db，其中 test_auth 与
test_stage5 还会先 unlink 它来"验证建库+迁移"——在开发机上跑一次测试就把
真实档案删了。这里统一改成临时目录，测试之间也互不串数据。

用法：在导入任何 app.* 之前 import 本模块并调用 isolate()。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def isolate(mock: bool = True, biocompute: str = "mock") -> Path:
    """把本次测试的库/上传/报告目录切到临时沙箱，返回沙箱根目录。"""
    if mock:
        os.environ.setdefault("SOULHEALTH_MOCK", "1")
    os.environ.setdefault("SOULHEALTH_BIOCOMPUTE", biocompute)

    from app import config                      # 延迟导入：环境变量要先就位

    box = Path(tempfile.mkdtemp(prefix="soulhealth_test_"))
    config.DB_PATH = box / "test.db"
    config.REPORT_DIR = box / "reports"
    config.UPLOAD_DIR = box / "uploads"
    for d in (config.REPORT_DIR, config.UPLOAD_DIR):
        d.mkdir(parents=True, exist_ok=True)
    return box
