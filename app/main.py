"""Создаёт FastAPI-приложение, подключает маршруты и middleware."""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.admin_session import (
    ADMIN_SESSION_COOKIE,
    consume_judge_login_token,
    create_admin_session_cookie,
    is_admin_session,
)
from sqlalchemy import select
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.settings import SiteSetting
from app.routers.web import router as web_router

app = FastAPI(title=settings.app_name)


async def consume_persisted_judge_token(token: str | None) -> bool:
    if not token:
        return False

    async with SessionLocal() as session:
        row = await session.scalar(select(SiteSetting).where(SiteSetting.key == "judge_login_token"))
        if not row or row.value != token:
            return False

        if not consume_judge_login_token(token):
            return False

        row.value = ""
        await session.commit()
        return True



@app.middleware("http")
async def admin_auth_middleware(request: Request, call_next):
    normalized_path = request.url.path.rstrip("/") or "/"

    if normalized_path == "/admin" and not is_admin_session(request.cookies.get(ADMIN_SESSION_COOKIE)):
        admin_key = request.query_params.get("admin_key")
        judge_token = request.query_params.get("judge_token")

        is_valid_entry = (admin_key and admin_key == settings.admin_key) or await consume_persisted_judge_token(judge_token)
        if is_valid_entry:
            response = RedirectResponse(url="/admin", status_code=303)
            response.set_cookie(
                ADMIN_SESSION_COOKIE,
                create_admin_session_cookie(),
                httponly=True,
                samesite="lax",
                max_age=60 * 60 * 12,
            )
            return response

        if admin_key or judge_token:
            return RedirectResponse(url="/admin/login?msg=msg_admin_login_failed", status_code=303)
        return HTMLResponse("Forbidden", status_code=403)

    if normalized_path.startswith("/admin") and normalized_path not in {"/admin/login", "/admin/logout"}:
        if not is_admin_session(request.cookies.get(ADMIN_SESSION_COOKIE)):
            if request.method == "GET":
                return RedirectResponse(url="/admin/login", status_code=303)
            return HTMLResponse("Forbidden", status_code=403)
    return await call_next(request)


# Подключаем роуты сайта.
app.include_router(web_router)
# Подключаем статику (css/js/images).
app.mount("/static", StaticFiles(directory="app/static"), name="static")
