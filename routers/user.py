import secrets
from datetime import datetime
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func

from auth import require_login
from models import ApiKey, Order, UsageLog, Subscription
from services.key_service import create_api_key

router = APIRouter(prefix="/user")
templates = Jinja2Templates(directory="templates")


@router.get("/dashboard")
@require_login
async def dashboard(request: Request):
    user = request.state.user
    db = request.state.db

    keys_result = await db.execute(select(ApiKey).where(ApiKey.user_id == user.id))
    keys = keys_result.scalars().all()

    orders_result = await db.execute(
        select(Order).where(Order.user_id == user.id).order_by(Order.created_at.desc()).limit(10)
    )
    orders = orders_result.scalars().all()

    subs_result = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id, Subscription.expire_at > datetime.utcnow())
    )
    subs = subs_result.scalars().all()

    usage_result = await db.execute(
        select(func.sum(UsageLog.cost_tokens)).where(UsageLog.user_id == user.id)
    )
    total_used = usage_result.scalar() or 0

    return templates.TemplateResponse("user/dashboard.html", {
        "request": request, "user": user, "keys": keys,
        "orders": orders, "subs": subs, "total_used": total_used,
    })


@router.post("/keys/create")
@require_login
async def create_key(request: Request, name: str = Form("default")):
    user = request.state.user
    db = request.state.db
    await create_api_key(db, user.id, name)
    return RedirectResponse("/user/dashboard", status_code=302)


@router.post("/keys/{key_id}/delete")
@require_login
async def delete_key(request: Request, key_id: int):
    user = request.state.user
    db = request.state.db
    key = await db.get(ApiKey, key_id)
    if key and key.user_id == user.id:
        await db.delete(key)
        await db.commit()
    return RedirectResponse("/user/dashboard", status_code=302)
