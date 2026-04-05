"""Database setup — sync (psycopg2) for FastAPI, async (asyncpg) for Celery."""
import os

import psycopg2
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Env-aware defaults so Docker (postgres host) and dev (localhost:5433) both work
HOST = os.getenv("DB_HOST", "127.0.0.1")
PORT = int(os.getenv("DB_PORT", "5433"))
USER = os.getenv("DB_USER", "postgres")
PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DBNAME = os.getenv("DB_NAME", "ai_ads_db")


# ── Sync engine (psycopg2) — used by FastAPI endpoints with Depends ──

def _creator():
    return psycopg2.connect(host=HOST, port=PORT, user=USER, password=PASSWORD, dbname=DBNAME)

engine = create_engine(
    "postgresql+psycopg2://", creator=_creator, echo=False,
    pool_size=5, max_overflow=10, pool_pre_ping=True, pool_recycle=300,
)
session_factory = sessionmaker(engine, expire_on_commit=False)


# ── Async engine (asyncpg) — used by Celery tasks ──

async_engine = create_async_engine(
    f"postgresql+asyncpg://{USER}:{PASSWORD}@{HOST}:{PORT}/{DBNAME}",
    echo=False, pool_size=5, max_overflow=10, pool_pre_ping=True, pool_recycle=300,
)
async_session_factory = async_sessionmaker(
    async_engine, class_=AsyncSession, expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


def get_db():
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def close_db() -> None:
    engine.dispose()
