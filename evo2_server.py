"""EVO2 本地推理服务（运行在 WSL2 / Linux 上，包装 evo2 Python 库）。

用法（在 WSL2 Ubuntu 终端中）：
    conda activate evo2
    python evo2_server.py [--port 8899] [--host 0.0.0.0]

首次启动会自动从 HuggingFace 下载 evo2_7b 权重（~14GB），
或从 EVO2_MODEL_DIR 环境变量指定的本地目录加载。

API 端点：
    POST /v1/evo2/score
    Body: {"ref_seq": "ACGT...", "alt_seq": "ACGT..."}
    Response: {"ref_ll": -123.4, "alt_ll": -125.6, "delta_ll": -2.2, "status": "done"}

    GET /health
    Response: {"status": "ok", "model": "evo2_7b", "device": "cuda:0"}
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.biocompute import evo2_scoring          # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("evo2_server")

# ---------------------------------------------------------------------------
# 延迟导入 evo2（加载模型很慢，服务器启动后才做）
# ---------------------------------------------------------------------------
_model = None
_model_name = os.getenv("EVO2_MODEL_NAME", "evo2_7b")


def _load_model():
    """首次请求时（或启动时）加载模型到 GPU。"""
    global _model
    if _model is not None:
        return _model

    log.info("正在加载 EVO2 模型 '%s' ...", _model_name)
    t0 = time.time()

    try:
        from evo2 import Evo2
        model_dir = os.getenv("EVO2_MODEL_DIR", "").strip()
        if not model_dir:
            for candidate in (
                "/mnt/c/Users/Administrator/Desktop/新建文件夹/evo2_7b/evo2_7b.pt",
                "/home/user/models/evo2_7b.pt",
                "/home/user/models/evo2_7b",
            ):
                if os.path.exists(candidate):
                    model_dir = candidate
                    break

        if model_dir:
            log.info("从本地权重路径加载 (local_path): %s", model_dir)
            _model = Evo2(_model_name, local_path=model_dir)
        else:
            log.info("从 HuggingFace/镜像 加载: %s", _model_name)
            _model = Evo2(_model_name)
    except Exception as exc:
        log.error("EVO2 模型加载失败: %s", exc)
        raise

    elapsed = time.time() - t0
    log.info("EVO2 模型加载完成，耗时 %.1f 秒", elapsed)
    return _model


def _score_pair(ref_seq: str, alt_seq: str) -> dict:
    """给 ref / alt 两条序列打分。

    打分实现在 app/biocompute/evo2_scoring.py：优先走官方
    ``score_sequences``，退化路径用 tokenizer 真实 token id 做
    teacher-forcing 累加。原先内联的实现把碱基硬编码成 0/1/2/3 去索引
    词表，而 Evo2 是字节级词表（A=65…），会算出与该变异无关的分数，
    已一并修正。
    """
    model = _load_model()
    scores, method, normalized = evo2_scoring.score_sequences(
        model, [ref_seq, alt_seq])
    ref_ll, alt_ll = scores[0], scores[1]
    return {
        "ref_ll": round(ref_ll, 6),
        "alt_ll": round(alt_ll, 6),
        "delta_ll": round(alt_ll - ref_ll, 6),
        "scoring_method": method,
        # normalized=True 时 ΔlogL 是"平均每 token"，量纲与求和不同，
        # 上层展示与阈值判断都要按这个标志区分，不能混着比
        "normalized": normalized,
    }


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------
try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
except ImportError:
    log.error("需要安装 fastapi 和 uvicorn：pip install fastapi uvicorn")
    sys.exit(1)

app = FastAPI(title="EVO2 Local Inference Service", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


class ScoreRequest(BaseModel):
    ref_seq: str
    alt_seq: str


class ScoreResponse(BaseModel):
    ref_ll: float
    alt_ll: float
    delta_ll: float
    status: str = "done"
    model: str = ""
    scoring_method: str = ""
    normalized: bool = False
    note: str = ""


@app.get("/health")
def health():
    """model_loaded=False 表示服务在、模型还没加载完（首次请求会触发加载）。
    调用方据此区分"服务没起来"和"模型还在热身"。"""
    device = "pending"
    if _model is not None:
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:                             # noqa: BLE001
            device = "unknown"
    return {
        "status": "ok",
        "model": _model_name,
        "model_loaded": _model is not None,
        "device": device,
    }


@app.post("/v1/evo2/score", response_model=ScoreResponse)
def score_variant(req: ScoreRequest):
    if not req.ref_seq or not req.alt_seq:
        raise HTTPException(400, "ref_seq 和 alt_seq 不能为空")
    if len(req.ref_seq) != len(req.alt_seq):
        raise HTTPException(400, f"ref_seq({len(req.ref_seq)}) 和 alt_seq({len(req.alt_seq)}) 长度不一致")

    try:
        r = _score_pair(req.ref_seq, req.alt_seq)
        return ScoreResponse(status="done", model=_model_name, **r)
    except Exception as exc:
        # 打分失败就报 500，绝不返回兜底分数——上游会如实标成 error
        log.exception("打分失败")
        raise HTTPException(500, f"EVO2 打分失败: {exc}")


@app.on_event("startup")
async def startup_preload():
    """服务启动时预加载模型（避免首次请求等太久）。"""
    preload = os.getenv("EVO2_PRELOAD", "1").strip()
    if preload == "1":
        log.info("预加载 EVO2 模型...")
        try:
            _load_model()
        except Exception:
            log.warning("预加载失败，首次请求时重试")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EVO2 本地推理服务")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8899, help="监听端口")
    parser.add_argument("--no-preload", action="store_true",
                        help="不在启动时预加载模型")
    args = parser.parse_args()

    if args.no_preload:
        os.environ["EVO2_PRELOAD"] = "0"

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
