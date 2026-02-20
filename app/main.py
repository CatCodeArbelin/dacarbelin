from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.routers.web import router as web_router

app = FastAPI(title=settings.app_name)
# Подключаем роуты сайта.
app.include_router(web_router)
# Подключаем статику (css/js/images).
app.mount("/static", StaticFiles(directory="app/static"), name="static")
