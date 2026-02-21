"""Создаёт FastAPI-приложение, подключает маршруты и middleware."""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.admin_session import ADMIN_SESSION_COOKIE, create_admin_session_cookie, is_admin_session
from app.core.config import settings
from app.routers.web import router as web_router

app = FastAPI(title=settings.app_name)


@app.middleware("http")
async def admin_auth_middleware(request: Request, call_next):
    normalized_path = request.url.path.rstrip("/") or "/"

    if normalized_path == "/admin" and not is_admin_session(request.cookies.get(ADMIN_SESSION_COOKIE)):
        admin_key = request.query_params.get("admin_key")
        if admin_key and admin_key == settings.admin_key:
            response = RedirectResponse(url="/admin", status_code=303)
            response.set_cookie(
                ADMIN_SESSION_COOKIE,
                create_admin_session_cookie(),
                httponly=True,
                samesite="lax",
                max_age=60 * 60 * 12,
            )
            return response
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
