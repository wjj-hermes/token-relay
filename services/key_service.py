import secrets
from datetime import datetime, date
from typing import Optional, Tuple, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from models import ApiKey, User, Subscription, UsageLog

KEY_PREFIX = "sk-tr-"


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_hex(24)


async def create_api_key(db: AsyncSession, user_id: int, name: str = "default", expire_at=None) -> ApiKey:
    key = ApiKey(user_id=user_id, key=generate_key(), name=name, expire_at=expire_at)
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return key


async def validate_api_key(db: AsyncSession, raw_key: str) -> Optional[Tuple[User, ApiKey]]:
    result = await db.execute(select(ApiKey).where(ApiKey.key == raw_key, ApiKey.is_active == True))
    api_key = result.scalar_one_or_none()
    if not api_key:
        return None
    # Check key expiration
    if api_key.expire_at and datetime.utcnow() > api_key.expire_at:
        return None
    user = await db.get(User, api_key.user_id)
    if not user or not user.is_active:
        return None
    return user, api_key


async def check_balance(user: User, subs: list[Subscription]) -> bool:
    """Return True if user has available quota (balance > 0 or active subscription)."""
    if user.balance > 0:
        return True
    now = datetime.utcnow()
    today = date.today()
    for sub in subs:
        if sub.start_at <= now <= sub.expire_at:
            if sub.last_reset_date != today:
                sub.daily_used = 0
                sub.last_reset_date = today
            if sub.daily_limit == 0 or sub.daily_used < sub.daily_limit:
                return True
    return False


async def deduct_usage(db: AsyncSession, user: User, api_key: ApiKey, model: str,
                       prompt_tokens: int, completion_tokens: int):
    cost = prompt_tokens + completion_tokens
    # Log usage
    log = UsageLog(
        user_id=user.id,
        api_key_id=api_key.id,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_tokens=cost,
    )
    db.add(log)

    # Deduct from subscription first, then balance
    now = datetime.utcnow()
    today = date.today()
    result = await db.execute(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.start_at <= now,
            Subscription.expire_at >= now,
        )
    )
    active_sub = result.scalars().first()
    if active_sub:
        if active_sub.last_reset_date != today:
            active_sub.daily_used = 0
            active_sub.last_reset_date = today
        if active_sub.daily_limit == 0 or active_sub.daily_used < active_sub.daily_limit:
            active_sub.daily_used += cost
            await db.commit()
            return

    # Fallback to balance
    user.balance = max(0, user.balance - cost)
    await db.commit()
