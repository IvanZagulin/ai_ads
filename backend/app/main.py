from contextlib import asynccontextmanager
import logging
import os
import sys

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.routes import router as api_router
from app.config import settings
from app.database import close_db


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN201  # FastAPI signature
    import asyncpg

    configure_logging()
    logger = logging.getLogger(__name__)
    logger.info("Запуск AI Ads Manager...")

    db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    try:
        conn = await asyncpg.connect(db_url)
        await conn.fetchval("SELECT 1")
        await conn.close()
        logger.info("База данных подключена")
    except Exception as e:
        logger.warning(f"База данных недоступна при старте: {e}")

    try:
        yield
    finally:
        logger.info("Остановка AI Ads Manager...")
        close_db()
        logger.info("Соединение закрыто")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


def create_app() -> FastAPI:
    configure_logging()

    _extra_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
    _allowed_origins = ["https://qvaz.quasar-x.ru"] + _extra_origins

    app = FastAPI(
        title="AI Ads Manager",
        description="Управление рекламой на Wildberries и Ozon с помощью ИИ",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.add_middleware(SecurityHeadersMiddleware)

    app.include_router(api_router)

    return app


app = create_app()
