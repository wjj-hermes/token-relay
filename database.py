import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

DB_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data.db")

engine = create_async_engine(DB_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    from models import User, ApiKey, Product, Order, UsageLog, Subscription  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Migrate: add description column to products if missing
        try:
            await conn.execute(__import__('sqlalchemy').text(
                "ALTER TABLE products ADD COLUMN description VARCHAR(500) DEFAULT ''"
            ))
        except Exception:
            pass  # column already exists


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
