from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import settings
from app.routers.web import router as web_router

app = FastAPI(title=settings.app_name)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)


@app.middleware("http")
async def admin_auth_middleware(request: Request, call_next):
    if request.url.path.startswith("/admin") and request.url.path not in {"/admin/login", "/admin/logout"}:
        if not request.session.get("is_admin"):
            if request.method == "GET":
                return RedirectResponse(url="/admin/login", status_code=303)
            return HTMLResponse("Forbidden", status_code=403)
    return await call_next(request)


# Подключаем роуты сайта.
app.include_router(web_router)
# Подключаем статику (css/js/images).
app.mount("/static", StaticFiles(directory="app/static"), name="static")
