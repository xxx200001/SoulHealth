"""认证与用户管理：/api/auth/* 与 /api/admin/*。

融合说明：全系统只保留这一套认证。原 TongueDiag 的 auth_module.py
（手机号 + bcrypt + PyJWT，独立的 users.db）与本套功能完全重叠，
且缺少角色与档案归属，已整体移除。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException

from .. import auth as auth_lib
from .. import db as _db
from ..archive import repository as repo
from ..deps import current_admin, current_user, public_user

router = APIRouter(tags=["认证与用户"])


@router.post("/auth/login", summary="登录")
def login(payload: dict = Body(...)) -> dict:
    try:
        user = repo.authenticate(payload.get("username") or "",
                                 payload.get("password") or "")
    except auth_lib.AuthError as exc:
        raise HTTPException(401, str(exc))
    token = auth_lib.create_token(user["id"], user["username"], user["role"])
    return {"token": token, "user": public_user(user)}


@router.post("/auth/register", summary="自助注册（固定为普通用户）")
def register(payload: dict = Body(...)) -> dict:
    """角色固定 user；管理员账号只能由已有管理员创建，
    防止任何人通过公开接口给自己开管理员权限。"""
    try:
        uid = repo.create_user(payload.get("username") or "",
                               payload.get("password") or "",
                               role="user",
                               display_name=payload.get("display_name"))
    except (ValueError, auth_lib.AuthError) as exc:
        raise HTTPException(400, str(exc))
    user = repo.get_user(uid)
    token = auth_lib.create_token(user["id"], user["username"], user["role"])
    return {"token": token, "user": public_user(user)}


@router.get("/auth/me", summary="当前登录用户")
def whoami(user: dict = Depends(current_user)) -> dict:
    return {"user": public_user(user)}


@router.post("/auth/change_password", summary="修改自己的密码")
def change_password(payload: dict = Body(...),
                    user: dict = Depends(current_user)) -> dict:
    if not auth_lib.verify_password(payload.get("old_password") or "",
                                    user["password_hash"]):
        raise HTTPException(400, "原密码不正确")
    try:
        new_hash = auth_lib.hash_password(payload.get("new_password") or "")
    except auth_lib.AuthError as exc:
        raise HTTPException(400, str(exc))
    with _db.get_conn() as conn:
        conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                     (new_hash, user["id"]))
    return {"ok": True}


# ------------------------------------------------------------------ 管理员

@router.get("/admin/users", summary="用户列表（仅管理员）")
def admin_list_users(_: dict = Depends(current_admin)) -> dict:
    return {"users": repo.list_users()}


@router.post("/admin/users", summary="创建用户（仅管理员）")
def admin_create_user(payload: dict = Body(...),
                      _: dict = Depends(current_admin)) -> dict:
    try:
        uid = repo.create_user(payload.get("username") or "",
                               payload.get("password") or "",
                               role=payload.get("role") or "user",
                               display_name=payload.get("display_name"))
    except (ValueError, auth_lib.AuthError) as exc:
        raise HTTPException(400, str(exc))
    return {"user": public_user(repo.get_user(uid))}


@router.patch("/admin/users/{uid}", summary="启用/停用用户（仅管理员）")
def admin_update_user(uid: str, payload: dict = Body(...),
                      admin: dict = Depends(current_admin)) -> dict:
    if uid == admin["id"] and payload.get("disabled"):
        raise HTTPException(400, "不能停用自己当前登录的账号")
    try:
        if "disabled" in payload:
            repo.set_user_disabled(uid, bool(payload["disabled"]))
    except KeyError:
        raise HTTPException(404, f"用户不存在: {uid}")
    return {"user": public_user(repo.get_user(uid))}


@router.delete("/admin/users/{uid}", summary="删除用户（仅管理员）")
def admin_delete_user(uid: str, admin: dict = Depends(current_admin)) -> dict:
    if uid == admin["id"]:
        raise HTTPException(400, "不能删除自己当前登录的账号")
    try:
        repo.delete_user(uid)
    except KeyError:
        raise HTTPException(404, f"用户不存在: {uid}")
    return {"deleted": uid}
