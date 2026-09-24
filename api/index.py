"""Vercel FastAPI entrypoint for the ZZU.Py web client."""

from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

# Vercel imports this file from its function runtime directory, where the
# repository root is not guaranteed to be present in sys.path.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from zzupy.app import CASClient, UndergradEASClient
from zzupy.exception import ZZUError
from zzupy.web import StudentWebEASClient

app = FastAPI(title="郑大生活助手 API", docs_url=None, redoc_url=None)
COOKIE_NAME = "zzu_web_session"
DEVELOPMENT_SECRET = "ZZU.Py local development only - change on Vercel"


class LoginBody(BaseModel):
    account: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    device_id: str = Field(default="ZZU.Py Web", max_length=128)
    remember: bool = False


class MfaBody(BaseModel):
    ticket: str
    code: str = Field(min_length=4, max_length=12)


def _secret() -> bytes:
    configured = os.environ.get("ZZU_WEB_SESSION_SECRET", "")
    if not configured and os.environ.get("VERCEL"):
        raise HTTPException(
            status_code=503,
            detail="部署尚未配置 ZZU_WEB_SESSION_SECRET。",
        )
    return hashlib.sha256((configured or DEVELOPMENT_SECRET).encode()).digest()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _seal(payload: dict[str, Any]) -> str:
    nonce = os.urandom(12)
    encrypted = AESGCM(_secret()).encrypt(
        nonce,
        json.dumps(payload, ensure_ascii=False).encode(),
        b"ZZU.Py/web/v1",
    )
    return _b64encode(nonce + encrypted)


def _open(ticket: str) -> dict[str, Any]:
    try:
        raw = _b64decode(ticket)
        decrypted = AESGCM(_secret()).decrypt(
            raw[:12], raw[12:], b"ZZU.Py/web/v1"
        )
        payload = json.loads(decrypted)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="登录会话无效或已损坏。") from exc
    if not isinstance(payload, dict) or payload.get("exp", 0) < time.time():
        raise HTTPException(status_code=401, detail="登录会话已过期，请重新登录。")
    return payload


def _session(request: Request) -> dict[str, Any]:
    ticket = request.cookies.get(COOKIE_NAME)
    if not ticket:
        raise HTTPException(status_code=401, detail="请先登录。")
    return _open(ticket)


def _set_session_cookie(
    response: Response, payload: dict[str, Any], remember: bool
) -> None:
    max_age = 30 * 24 * 60 * 60 if remember else None
    payload["exp"] = time.time() + (max_age or 12 * 60 * 60)
    response.set_cookie(
        COOKIE_NAME,
        _seal(payload),
        max_age=max_age,
        httponly=True,
        secure=bool(os.environ.get("VERCEL")),
        samesite="lax",
        path="/",
    )


def _raise_upstream(exc: BaseException) -> None:
    if isinstance(exc, ZZUError):
        detail = exc.message
        if validation := exc.context.get("validation_errors"):
            detail += f"\n解析详情：{validation}"
    else:
        detail = str(exc) or type(exc).__name__
    raise HTTPException(status_code=502, detail=detail) from exc


def _cas_from_session(session: dict[str, Any]) -> CASClient:
    cas = CASClient(session["account"], session.get("password", ""))
    cas.set_device(session.get("device_id", "ZZU.Py Web"))
    cas.mfa.state = session.get("mfa_state") or "verified-web-token-session"
    cas.mfa.required = bool(session.get("mfa_required", False))
    cas.mfa.verified = bool(session.get("mfa_verified", True))
    cas.set_token(session["user_token"], session["refresh_token"])
    cas.login()
    return cas


def _numeric_score(value: str | None) -> float:
    if not value:
        return float("-inf")
    match = re.search(r"\d+(?:\.\d+)?", value)
    return float(match.group()) if match else float("-inf")


def _best_attempts(values: list[Any]) -> list[Any]:
    """按课程代码保留最高绩点记录；缺少代码时退回课程名。"""
    selected: dict[str, Any] = {}
    for grade in values:
        key = grade.lesson_code.strip() or grade.course_name_zh.strip()
        current = selected.get(key)
        grade_key = (
            grade.gp if grade.gp is not None else float("-inf"),
            _numeric_score(grade.final_grade),
            grade.semester.name_zh,
        )
        if current is None:
            selected[key] = grade
            continue
        current_key = (
            current.gp if current.gp is not None else float("-inf"),
            _numeric_score(current.final_grade),
            current.semester.name_zh,
        )
        if grade_key > current_key:
            selected[key] = grade
    return list(selected.values())


def _gpa_summary(values: list[Any]) -> dict[str, Any]:
    best = _best_attempts(values)
    included = [item for item in best if item.gp is not None and item.credits > 0]
    credits = sum(item.credits for item in included)
    weighted_points = sum(float(item.gp) * item.credits for item in included)
    return {
        "gpa": round(weighted_points / credits, 4) if credits else None,
        "credits": round(credits, 2),
        "weighted_points": round(weighted_points, 4),
        "course_count": len(values),
        "best_attempt_course_count": len(best),
        "included_course_count": len(included),
        "method": "每门课程保留最高绩点后，按学分加权；无绩点课程不计入",
        "official": False,
    }


def _web_eas_from_session(session: dict[str, Any]) -> tuple[CASClient, StudentWebEASClient]:
    cas = _cas_from_session(session)
    web_eas: StudentWebEASClient | None = None
    try:
        web_eas = StudentWebEASClient(cas)
        web_eas.login()
        return cas, web_eas
    except BaseException:
        if web_eas is not None:
            web_eas.close()
        cas.close()
        raise


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "session_secret_configured": bool(os.environ.get("ZZU_WEB_SESSION_SECRET")),
    }


@app.post("/api/auth/login")
def login(body: LoginBody, response: Response) -> dict[str, Any]:
    cas = CASClient(body.account.strip(), body.password)
    try:
        cas.set_device(body.device_id.strip() or "ZZU.Py Web")
        if cas.mfa.is_required():
            cas.mfa.send_sms()
            ticket = _seal(
                {
                    "purpose": "mfa",
                    "exp": time.time() + 10 * 60,
                    "account": body.account.strip(),
                    "password": body.password,
                    "device_id": body.device_id,
                    "remember": body.remember,
                    "state": cas.mfa.state,
                    "gid": cas.mfa.gid,
                    "attest_server_url": cas.mfa.attest_server_url,
                }
            )
            return {"ok": True, "mfa_required": True, "ticket": ticket}
        cas.login()
        session = {
            "account": body.account.strip(),
            "password": body.password,
            "device_id": body.device_id,
            "user_token": cas.user_token,
            "refresh_token": cas.refresh_token,
            "mfa_state": cas.mfa.state,
            "mfa_required": cas.mfa.required,
            "mfa_verified": cas.mfa.verified,
        }
        _set_session_cookie(response, session, body.remember)
        return {"ok": True, "mfa_required": False, "account": body.account.strip()}
    except BaseException as exc:
        _raise_upstream(exc)
    finally:
        cas.close()


@app.post("/api/auth/mfa")
def verify_mfa(body: MfaBody, response: Response) -> dict[str, Any]:
    payload = _open(body.ticket)
    if payload.get("purpose") != "mfa":
        raise HTTPException(status_code=400, detail="MFA 会话类型不正确。")
    cas = CASClient(payload["account"], payload["password"])
    try:
        cas.set_device(payload.get("device_id", "ZZU.Py Web"))
        cas.mfa.state = payload["state"]
        cas.mfa.gid = payload["gid"]
        cas.mfa.attest_server_url = payload.get("attest_server_url", "")
        cas.mfa.required = True
        cas.mfa.secure_phone_available = True
        cas.mfa.verify_sms(body.code.strip())
        cas.login()
        session = {
            "account": payload["account"],
            "password": payload["password"],
            "device_id": payload.get("device_id", "ZZU.Py Web"),
            "user_token": cas.user_token,
            "refresh_token": cas.refresh_token,
            "mfa_state": cas.mfa.state,
            "mfa_required": cas.mfa.required,
            "mfa_verified": cas.mfa.verified,
        }
        _set_session_cookie(response, session, bool(payload.get("remember")))
        return {"ok": True, "account": payload["account"]}
    except BaseException as exc:
        _raise_upstream(exc)
    finally:
        cas.close()


@app.get("/api/session")
def session_status(request: Request) -> dict[str, Any]:
    session = _session(request)
    return {"authenticated": True, "account": session["account"]}


@app.post("/api/auth/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@app.get("/api/grades")
def grades(request: Request) -> dict[str, Any]:
    session = _session(request)
    cas: CASClient | None = None
    try:
        cas = _cas_from_session(session)
        with UndergradEASClient(cas) as eas:
            eas.login()
            values = eas.get_grades()
        return {
            "grades": [
                {
                    "semester": grade.semester.name_zh,
                    "course": grade.course_name_zh,
                    "course_code": grade.lesson_code,
                    "score": grade.final_grade,
                    "level": grade.grade_level,
                    "usual_score": grade.usual_grade,
                    "paper_score": grade.paper_grade,
                    "experiment_score": grade.experiment_grade,
                    "gp": grade.gp,
                    "credits": grade.credits,
                    "passed": grade.passed,
                    "detail": grade.grade_detail,
                }
                for grade in values
            ]
        }
    except BaseException as exc:
        _raise_upstream(exc)
    finally:
        if cas is not None:
            cas.close()


@app.get("/api/academic-summary")
def academic_summary(request: Request) -> dict[str, Any]:
    """计算当前学生的累计绩点，并使用最好成绩口径去除重复修读。"""
    session = _session(request)
    cas: CASClient | None = None
    try:
        cas = _cas_from_session(session)
        with UndergradEASClient(cas) as eas:
            eas.login()
            values = eas.get_grades()
        return _gpa_summary(values)
    except BaseException as exc:
        _raise_upstream(exc)
    finally:
        if cas is not None:
            cas.close()


@app.get("/api/transcript")
def transcript(request: Request) -> Response:
    """生成可打印的个人成绩汇总，避免旧教务网页登录跳转超时。"""
    session = _session(request)
    cas: CASClient | None = None
    try:
        cas = _cas_from_session(session)
        with UndergradEASClient(cas) as eas:
            eas.login()
            values = eas.get_grades()
        summary = _gpa_summary(values)
        rows = "".join(
            "<tr>"
            f"<td>{html.escape(grade.semester.name_zh)}</td>"
            f"<td>{html.escape(grade.course_name_zh)}</td>"
            f"<td>{html.escape(grade.final_grade or '--')}</td>"
            f"<td>{'--' if grade.gp is None else grade.gp:g}</td>"
            f"<td>{grade.credits:g}</td>"
            "</tr>"
            for grade in values
        )
        content = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>个人成绩汇总</title><style>
body{{font-family:system-ui,sans-serif;color:#172a25;max-width:1000px;margin:32px auto;padding:0 22px}}
h1{{color:#08483c}} .note{{color:#65746f}} .summary{{display:flex;gap:28px;padding:16px;background:#edf6f1;border-radius:12px}}
table{{border-collapse:collapse;width:100%;margin-top:22px}}th,td{{padding:9px;border-bottom:1px solid #d7e1dc;text-align:left}}
@media print{{button{{display:none}}body{{margin:0;max-width:none}}}}
</style></head><body><button onclick="window.print()">打印 / 保存 PDF</button>
<h1>个人成绩汇总</h1><p class="note">由本科教务成绩接口实时生成，仅供个人核对，不等同于教务处盖章成绩单。</p>
<div class="summary"><b>参考累计绩点：{summary['gpa'] if summary['gpa'] is not None else '--'}</b><b>计入学分：{summary['credits']:g}</b></div>
<table><thead><tr><th>学期</th><th>课程</th><th>成绩</th><th>绩点</th><th>学分</th></tr></thead><tbody>{rows}</tbody></table>
</body></html>""".encode()
        return Response(
            content=content,
            media_type="text/html",
            headers={"Content-Disposition": 'inline; filename="zzu-grade-summary.html"'},
        )
    except BaseException as exc:
        _raise_upstream(exc)
    finally:
        if cas is not None:
            cas.close()


@app.get("/api/grade-rank-report")
def grade_rank_report(request: Request) -> Response:
    """代理当前学生的官方累计成绩排名 PDF。"""
    session = _session(request)
    cas: CASClient | None = None
    web_eas: StudentWebEASClient | None = None
    try:
        cas, web_eas = _web_eas_from_session(session)
        content = web_eas.get_grade_rank_report()
        return Response(
            content=content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": 'attachment; filename="zzu-grade-rank.pdf"'
            },
        )
    except BaseException as exc:
        _raise_upstream(exc)
    finally:
        if web_eas is not None:
            web_eas.close()
        if cas is not None:
            cas.close()


@app.get("/api/semesters")
def semesters(request: Request) -> dict[str, Any]:
    session = _session(request)
    cas: CASClient | None = None
    try:
        cas = _cas_from_session(session)
        with UndergradEASClient(cas) as eas:
            eas.login()
            values = eas.get_semesters()
        return {
            "semesters": [
                {
                    "id": item.id,
                    "name": item.name_zh,
                    "school_year": item.school_year,
                    "start_date": str(item.start_date),
                    "end_date": str(item.end_date),
                    "weeks": max(item.week_indices, default=1),
                }
                for item in values
            ]
        }
    except BaseException as exc:
        _raise_upstream(exc)
    finally:
        if cas is not None:
            cas.close()


@app.get("/api/schedule")
def schedule(
    request: Request,
    semester_id: int = Query(gt=0),
    week: int = Query(ge=1, le=30),
) -> dict[str, Any]:
    session = _session(request)
    cas: CASClient | None = None
    try:
        cas = _cas_from_session(session)
        with UndergradEASClient(cas) as eas:
            eas.login()
            teaching_week = eas.get_teaching_week(week, semester_id)
        unique: dict[tuple[Any, ...], Any] = {}
        for lesson in teaching_week.lessons.values():
            item = lesson.schedule
            key = (
                item.schedule_group_id,
                str(item.date),
                item.start_unit,
                item.end_unit,
                lesson.course.code,
            )
            unique[key] = lesson
        lessons = []
        for lesson in sorted(
            unique.values(),
            key=lambda value: (value.schedule.weekday, value.schedule.start_unit),
        ):
            item = lesson.schedule
            room = item.room
            place = item.custom_place or ""
            if room is not None:
                place = " ".join(
                    part
                    for part in (
                        room.campus.name_zh,
                        room.building.name_zh,
                        room.name_zh,
                    )
                    if part
                )
            lessons.append(
                {
                    "weekday": item.weekday,
                    "date": str(item.date),
                    "start_unit": item.start_unit,
                    "end_unit": item.end_unit,
                    "course": lesson.course.name_zh,
                    "teacher": item.teacher_name,
                    "place": place,
                }
            )
        return {"week": week, "lessons": lessons}
    except BaseException as exc:
        _raise_upstream(exc)
    finally:
        if cas is not None:
            cas.close()


@app.get("/api/calendar")
def calendar_file(request: Request, semester_id: int = Query(gt=0)) -> Response:
    session = _session(request)
    cas: CASClient | None = None
    try:
        cas = _cas_from_session(session)
        with UndergradEASClient(cas) as eas:
            eas.login()
            teaching_weeks = eas.get_teaching_weeks(semester_id)
        content = teaching_weeks.to_calendar().to_ical()
        return Response(
            content=content,
            media_type="text/calendar; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="zzu-schedule-{semester_id}.ics"'
                )
            },
        )
    except BaseException as exc:
        _raise_upstream(exc)
    finally:
        if cas is not None:
            cas.close()


@app.get("/api/network-devices")
def network_devices() -> JSONResponse:
    return JSONResponse(
        status_code=501,
        content={
            "detail": (
                "校园网设备服务位于 10.2.7.16 内网，Vercel 无法访问。"
                "请继续使用桌面版管理在线设备。"
            )
        },
    )
