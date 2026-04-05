"""Bootstrap script to create all database tables.

This script connects asynchronously to the database and creates all tables
defined in the SQLAlchemy models. Run it instead of `alembic upgrade head`
when you need to quickly set up the schema from scratch.

Usage:
    cd backend
    python bootstrap_db.py
"""

import asyncio

from app.database import engine
from app.models.base import BaseModel
from app.models import *  # noqa: F403 – register all models with BaseModel.metadata


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all)
    print("Tables created successfully")

    # Print table names for verification
    print("Tables:")
    for table in Base.metadata.sorted_tables:
        print(f"  - {table.name}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
