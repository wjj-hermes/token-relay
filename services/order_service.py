import time
import secrets
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from models import Order, Product, User, Subscription


def generate_order_no() -> str:
    return f"TR{int(time.time() * 1000)}{secrets.token_hex(4)}"


async def create_order(db: AsyncSession, user_id: int, product_id: int) -> Order:
    product = await db.get(Product, product_id)
    if not product or not product.is_active:
        raise ValueError("Product not found or inactive")

    order = Order(
        user_id=user_id,
        product_id=product.id,
        order_no=generate_order_no(),
        amount=product.price,
        status="pending",
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return order


async def complete_order(db: AsyncSession, order_no: str, alipay_trade_no: str) -> bool:
    result = await db.execute(select(Order).where(Order.order_no == order_no))
    order = result.scalar_one_or_none()
    if not order or order.status != "pending":
        return False

    order.status = "paid"
    order.alipay_trade_no = alipay_trade_no
    order.paid_at = datetime.utcnow()

    product = await db.get(Product, order.product_id)
    user = await db.get(User, order.user_id)

    if product.type == "quota":
        user.balance += product.token_amount
    elif product.type == "subscription":
        now = datetime.utcnow()
        # Check if user has existing active sub for this product
        existing = await db.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.product_id == product.id,
                Subscription.expire_at > now,
            )
        )
        sub = existing.scalar_one_or_none()
        if sub:
            sub.expire_at += timedelta(days=product.duration_days)
        else:
            sub = Subscription(
                user_id=user.id,
                product_id=product.id,
                start_at=now,
                expire_at=now + timedelta(days=product.duration_days),
                daily_limit=product.daily_limit,
            )
            db.add(sub)

    await db.commit()
    return True
