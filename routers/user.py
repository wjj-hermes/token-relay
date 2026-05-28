from datetime import datetime, timedelta
import os
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func

from auth import require_login, hash_password, verify_password
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

    products_result = await db.execute(select(Product).where(Product.is_active == True))
    products = products_result.scalars().all()

    models_result = await db.execute(select(LLMModel).where(LLMModel.is_active == True))
    models = models_result.scalars().all()
    api_base_url = os.getenv("API_BASE_URL", "https://token-relay-v2-production.up.railway.app") + "/v1"

    return templates.TemplateResponse(request, "user/dashboard.html", _ctx(
        request, user=user, keys=keys,
        orders=orders, subs=subs, total_used=total_used, products=products,
        models=models, api_base_url=api_base_url,
    ))


@router.get("/analytics")
@require_login
async def analytics(request: Request):
    user = request.state.user
    db = request.state.db

    # Daily usage for last 30 days
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    daily_result = await db.execute(
        select(
            func.date(UsageLog.created_at).label("day"),
            func.sum(UsageLog.prompt_tokens).label("prompt"),
            func.sum(UsageLog.completion_tokens).label("completion"),
            func.sum(UsageLog.cost_tokens).label("cost"),
        )
        .where(UsageLog.user_id == user.id, UsageLog.created_at >= thirty_days_ago)
        .group_by(func.date(UsageLog.created_at))
        .order_by(func.date(UsageLog.created_at))
    )
    daily_stats = daily_result.all()

    usage_result = await db.execute(
        select(func.sum(UsageLog.cost_tokens)).where(UsageLog.user_id == user.id)
    )
    total_used = usage_result.scalar() or 0

    return templates.TemplateResponse(request, "user/analytics.html", _ctx(
        request, user=user, daily_stats=daily_stats, total_used=total_used,
    ))


@router.get("/usage")
@require_login
async def usage(request: Request):
    user = request.state.user
    db = request.state.db

    usage_result = await db.execute(
        select(func.sum(UsageLog.cost_tokens)).where(UsageLog.user_id == user.id)
    )
    total_used = usage_result.scalar() or 0

    usage_logs_result = await db.execute(
        select(UsageLog).where(UsageLog.user_id == user.id)
        .order_by(UsageLog.created_at.desc()).limit(200)
    )
    usage_logs = usage_logs_result.scalars().all()

    return templates.TemplateResponse(request, "user/usage.html", _ctx(
        request, user=user, usage_logs=usage_logs, total_used=total_used,
    ))


@router.get("/subscriptions")
@require_login
async def subscriptions(request: Request):
    user = request.state.user
    db = request.state.db

    subs_result = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id).order_by(Subscription.created_at.desc())
    )
    subs = subs_result.scalars().all()

    return templates.TemplateResponse(request, "user/subscriptions.html", _ctx(
        request, user=user, subs=subs,
    ))


@router.get("/profile")
@require_login
async def profile_page(request: Request):
    user = request.state.user
    return templates.TemplateResponse(request, "user/profile.html", _ctx(
        request, user=user, success="", error="",
    ))


@router.post("/profile")
@require_login
async def profile_update(request: Request):
    user = request.state.user
    db = request.state.db
    form = await request.form()
    old_pw = form.get("old_password", "")
    new_pw = form.get("new_password", "")
    confirm_pw = form.get("confirm_new_password", "")
    lang = get_lang(request)

    if not old_pw or not new_pw:
        return templates.TemplateResponse(request, "user/profile.html", _ctx(
            request, user=user, error=_t(lang, "pw_wrong"), success="",
        ))
    if not verify_password(old_pw, user.password_hash):
        return templates.TemplateResponse(request, "user/profile.html", _ctx(
            request, user=user, error=_t(lang, "pw_wrong"), success="",
        ))
    if new_pw != confirm_pw:
        return templates.TemplateResponse(request, "user/profile.html", _ctx(
            request, user=user, error=_t(lang, "err_pw_mismatch"), success="",
        ))
    if len(new_pw) < 6:
        return templates.TemplateResponse(request, "user/profile.html", _ctx(
            request, user=user, error=_t(lang, "err_pw_short"), success="",
        ))

    user.password_hash = hash_password(new_pw)
    await db.commit()
    return templates.TemplateResponse(request, "user/profile.html", _ctx(
        request, user=user, success=_t(lang, "pw_changed"), error="",
    ))


@router.get("/guide")
@require_login
async def guide(request: Request):
    user = request.state.user
    models_result = await request.state.db.execute(
        select(LLMModel).where(LLMModel.is_active == True)
    )
    models = models_result.scalars().all()
    api_base_url = os.getenv("API_BASE_URL", "https://token-relay-v2-production.up.railway.app") + "/v1"

    return templates.TemplateResponse(request, "user/guide.html", _ctx(
        request, user=user, models=models, api_base_url=api_base_url,
    ))


@router.post("/keys/create")
@require_login
async def create_key(request: Request, name: str = Form("default")):
    user = request.state.user
    db = request.state.db
    lang = get_lang(request)

    # Check if user has active subscription
    now = datetime.utcnow()
    sub_result = await db.execute(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.expire_at > now,
        ).order_by(Subscription.expire_at.desc())
    )
    active_sub = sub_result.scalars().first()

    # If no active subscription and no balance, reject
    if not active_sub and user.balance <= 0:
        return RedirectResponse("/user/dashboard?error=no_plan", status_code=302)

    # Key expires with the subscription, or no expiration for quota-only users
    expire_at = active_sub.expire_at if active_sub else None
    await create_api_key(db, user.id, name, expire_at=expire_at)
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
