from contextlib import asynccontextmanager
import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title="AI Ads Manager",
        description="Управление рекламой на Wildberries и Ozon с помощью ИИ",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    return app


app = create_app()
