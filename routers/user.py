from datetime import datetime
import os
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func

from auth import require_login
from models import ApiKey, Order, UsageLog, Subscription, Product, LLMModel
from services.key_service import create_api_key
from i18n import get_lang, t as _t

router = APIRouter(prefix="/user")
templates = Jinja2Templates(directory="templates")


def _ctx(request: Request, **extra):
    lang = get_lang(request)
    ctx = {"lang": lang, "t": lambda k: _t(lang, k)}
    ctx.update(extra)
    return ctx


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

    usage_logs_result = await db.execute(
        select(UsageLog).where(UsageLog.user_id == user.id)
        .order_by(UsageLog.created_at.desc()).limit(50)
    )
    usage_logs = usage_logs_result.scalars().all()

    products_result = await db.execute(select(Product).where(Product.is_active == True))
    products = products_result.scalars().all()

    models_result = await db.execute(select(LLMModel).where(LLMModel.is_active == True))
    models = models_result.scalars().all()
    api_base_url = os.getenv("API_BASE_URL", "https://token-relay-v2-production.up.railway.app") + "/v1"

    return templates.TemplateResponse(request, "user/dashboard.html", _ctx(
        request, user=user, keys=keys,
        orders=orders, subs=subs, total_used=total_used, products=products,
        models=models, api_base_url=api_base_url, usage_logs=usage_logs,
    ))


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
