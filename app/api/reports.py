"""报告：/api/reports/*。

报告文档统一由后端生成（docx + md，过合规闸），前端只负责列表、预览与下载。
原前端 utils/exportDoc.js 自己拼 HTML 导出 .doc 的那套已移除——同一份内容
两处生成、格式与合规校验各不相同，是典型的重复实现。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse

from .. import auth as auth_lib
from ..archive import repository as repo
from ..deps import current_user, scoped_patient
from ..reportgen.generator import TITLES

router = APIRouter(tags=["报告"])

_MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "md": "text/markdown; charset=utf-8",
}


@router.get("/patients/{pid}/reports", summary="档案下全部报告")
def list_reports(pid: str, user: dict = Depends(current_user)) -> dict:
    scoped_patient(pid, user)
    rows = repo.list_reports(pid)
    return {"patient_id": pid, "reports": [
        {**r, "title": TITLES.get(r["report_type"], r["report_type"]),
         "download_url": f"/api/reports/{r['id']}/download"} for r in rows]}


@router.get("/reports/{rid}/preview", summary="报告 Markdown 预览")
def preview(rid: str, user: dict = Depends(current_user)) -> dict:
    r = repo.get_report(rid)
    if r is None:
        raise HTTPException(404, f"报告不存在: {rid}")
    scoped_patient(r["patient_id"], user)
    path = Path(r["path"])
    if r["format"] != "md":
        path = path.with_suffix(".md")
    if not path.exists():
        raise HTTPException(404, "该报告没有可预览的 Markdown 版本")
    return {"report_id": rid, "report_type": r["report_type"],
            "title": TITLES.get(r["report_type"], r["report_type"]),
            "markdown": path.read_text(encoding="utf-8")}


@router.get("/reports/{rid}/download", summary="报告下载")
def download(rid: str, token: Optional[str] = None,
             authorization: Optional[str] = Header(default=None)):
    """浏览器直接点链接下载时带不上 Authorization 头，
    因此额外支持 ?token= 查询参数（前端下载按钮用这条路径）。"""
    r = repo.get_report(rid)
    if r is None or not Path(r["path"]).exists():
        raise HTTPException(404, f"报告不存在: {rid}")

    user_id, role = None, "guest"
    header = authorization or (f"Bearer {token}" if token else None)
    if header:
        try:
            payload = auth_lib.decode_token(auth_lib.extract_bearer_token(header))
            u = repo.get_user(payload["uid"])
            if u and not u.get("disabled"):
                user_id, role = u["id"], u.get("role", "user")
        except Exception:                           # noqa: BLE001
            pass
    if role == "guest":
        raise HTTPException(401, "请先登录后再下载报告")
    if role != "admin":
        p = repo.get_patient(r["patient_id"])
        if p and p.get("owner_id") and p["owner_id"] != user_id:
            raise HTTPException(403, "无权访问该报告")

    path = Path(r["path"])
    return FileResponse(str(path),
                        media_type=_MEDIA.get(r["format"], "application/octet-stream"),
                        filename=path.name)
