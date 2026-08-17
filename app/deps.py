"""请求依赖：当前登录用户、角色校验、档案越权校验。

原来这些辅助函数散在 main.py 里，路由拆分后收拢到这里，
所有路由文件共用同一套鉴权口径，避免各写各的。
"""
from __future__ import annotations

from typing import Optional

from fastapi import Header, HTTPException

from . import auth
from .archive import repository as repo


def current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    """FastAPI 依赖：解析 Bearer 令牌 → 用户行。令牌无效/账号停用一律 401。"""
    try:
        token = auth.extract_bearer_token(authorization)
        payload = auth.decode_token(token)
    except auth.AuthError as exc:
        raise HTTPException(401, str(exc))
    user = repo.get_user(payload["uid"])
    if user is None or user.get("disabled"):
        raise HTTPException(401, "账号不存在或已被停用，请重新登录")
    return user


def current_admin(authorization: Optional[str] = Header(default=None)) -> dict:
    user = current_user(authorization)
    if user["role"] != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user


def owns_or_admin(patient: dict, user: dict) -> None:
    if user["role"] == "admin":
        return
    if patient.get("owner_id") and patient["owner_id"] != user["id"]:
        raise HTTPException(403, "无权访问该档案（不属于当前登录用户）")


def scoped_patient(pid: str, user: dict) -> dict:
    """取档案并做归属校验。所有涉及 patient_id 的接口都走这里。"""
    p = repo.get_patient(pid)
    if p is None:
        raise HTTPException(404, f"档案不存在: {pid}")
    owns_or_admin(p, user)
    return p


def public_user(user: dict) -> dict:
    return {"id": user["id"], "username": user["username"], "role": user["role"],
            "display_name": user.get("display_name")}
