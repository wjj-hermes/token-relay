from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func

from auth import require_admin
from models import User, Product, Order, UsageLog, LLMModel
from i18n import get_lang, t as _t

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="templates")


def _ctx(request: Request, **extra):
    lang = get_lang(request)
    ctx = {"lang": lang, "t": lambda k: _t(lang, k)}
    ctx.update(extra)
    return ctx


@router.get("/dashboard")
@require_admin
async def admin_dashboard(request: Request):
    db = request.state.db
    user_count = (await db.execute(select(func.count(User.id)))).scalar()
    order_count = (await db.execute(select(func.count(Order.id)))).scalar()
    revenue = (await db.execute(select(func.sum(Order.amount)).where(Order.status == "paid"))).scalar() or 0
    total_tokens = (await db.execute(select(func.sum(UsageLog.cost_tokens)))).scalar() or 0
    recent_orders_result = await db.execute(
        select(Order).order_by(Order.created_at.desc()).limit(20)
    )
    recent_orders = recent_orders_result.scalars().all()
    return templates.TemplateResponse(request, "admin/dashboard.html", _ctx(
        request, user=request.state.user,
        user_count=user_count, order_count=order_count,
        revenue=revenue, total_tokens=total_tokens,
        recent_orders=recent_orders,
    ))


@router.get("/users")
@require_admin
async def admin_users(request: Request):
    db = request.state.db
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return templates.TemplateResponse(request, "admin/users.html", _ctx(
        request, user=request.state.user, users=users,
    ))


@router.get("/users/{user_id}/usage")
@require_admin
async def admin_user_usage(request: Request, user_id: int):
    db = request.state.db
    target = await db.get(User, user_id)
    if not target:
        return RedirectResponse("/admin/users", status_code=302)

    usage_result = await db.execute(
        select(func.sum(UsageLog.cost_tokens)).where(UsageLog.user_id == user_id)
    )
    total_used = usage_result.scalar() or 0

    logs_result = await db.execute(
        select(UsageLog).where(UsageLog.user_id == user_id)
        .order_by(UsageLog.created_at.desc()).limit(100)
    )
    usage_logs = logs_result.scalars().all()

    return templates.TemplateResponse(request, "admin/user_usage.html", _ctx(
        request, user=request.state.user, target=target,
        total_used=total_used, usage_logs=usage_logs,
    ))


@router.post("/users/{user_id}/toggle")
@require_admin
async def toggle_user(request: Request, user_id: int):
    db = request.state.db
    target = await db.get(User, user_id)
    if target:
        target.is_active = not target.is_active
        await db.commit()
    return RedirectResponse("/admin/users", status_code=302)


@router.post("/users/{user_id}/set_balance")
@require_admin
async def set_balance(request: Request, user_id: int, balance: int = Form(...)):
    db = request.state.db
    target = await db.get(User, user_id)
    if target:
        target.balance = balance
        await db.commit()
    return RedirectResponse("/admin/users", status_code=302)


@router.get("/products")
@require_admin
async def admin_products(request: Request):
    db = request.state.db
    result = await db.execute(select(Product).order_by(Product.id))
    products = result.scalars().all()
    models_result = await db.execute(select(LLMModel).where(LLMModel.is_active == True))
    models = models_result.scalars().all()
    return templates.TemplateResponse(request, "admin/products.html", _ctx(
        request, user=request.state.user, products=products, models=models,
    ))


@router.post("/products/create")
@require_admin
async def create_product(request: Request, name: str = Form(...), type: str = Form(...),
                         price: int = Form(...), description: str = Form(""),
                         token_amount: int = Form(0),
                         duration_days: int = Form(0), daily_limit: int = Form(0),
                         model_name: str = Form("")):
    db = request.state.db
    product = Product(
        name=name, description=description, type=type, price=price,
        token_amount=token_amount, duration_days=duration_days, daily_limit=daily_limit,
        model_name=model_name,
    )
    db.add(product)
    await db.commit()
    return RedirectResponse("/admin/products", status_code=302)


@router.post("/products/{product_id}/toggle")
@require_admin
async def toggle_product(request: Request, product_id: int):
    db = request.state.db
    product = await db.get(Product, product_id)
    if product:
        product.is_active = not product.is_active
        await db.commit()
    return RedirectResponse("/admin/products", status_code=302)


@router.post("/products/{product_id}/update")
@require_admin
async def update_product(request: Request, product_id: int,
                         name: str = Form(...), description: str = Form(""),
                         type: str = Form(...), price: int = Form(...),
                         token_amount: int = Form(0), duration_days: int = Form(0),
                         daily_limit: int = Form(0), model_name: str = Form("")):
    db = request.state.db
    product = await db.get(Product, product_id)
    if product:
        product.name = name
        product.description = description
        product.type = type
        product.price = price
        product.token_amount = token_amount
        product.duration_days = duration_days
        product.daily_limit = daily_limit
        product.model_name = model_name
        await db.commit()
    return RedirectResponse("/admin/products", status_code=302)


@router.get("/orders")
@require_admin
async def admin_orders(request: Request):
    db = request.state.db
    result = await db.execute(select(Order).order_by(Order.created_at.desc()).limit(100))
    orders = result.scalars().all()
    return templates.TemplateResponse(request, "admin/orders.html", _ctx(
        request, user=request.state.user, orders=orders,
    ))


# === Model Management ===

@router.get("/models")
@require_admin
async def admin_models(request: Request):
    db = request.state.db
    result = await db.execute(select(LLMModel).order_by(LLMModel.id))
    models = result.scalars().all()
    return templates.TemplateResponse(request, "admin/models.html", _ctx(
        request, user=request.state.user, models=models,
    ))


@router.post("/models/create")
@require_admin
async def create_model(request: Request, name: str = Form(...),
                       model_id: str = Form(...), base_url: str = Form(...),
                       api_key: str = Form(...)):
    db = request.state.db
    m = LLMModel(name=name, model_id=model_id, base_url=base_url, api_key=api_key)
    db.add(m)
    await db.commit()
    # Reload relay models
    from relay import relay
    await relay.reload_from_db()
    return RedirectResponse("/admin/models", status_code=302)


@router.post("/models/{model_id}/toggle")
@require_admin
async def toggle_model(request: Request, model_id: int):
    db = request.state.db
    m = await db.get(LLMModel, model_id)
    if m:
        m.is_active = not m.is_active
        await db.commit()
        from relay import relay
        await relay.reload_from_db()
    return RedirectResponse("/admin/models", status_code=302)


@router.post("/models/{model_id}/update")
@require_admin
async def update_model(request: Request, model_id: int,
                       name: str = Form(...), model_id_val: str = Form(...),
                       base_url: str = Form(...), api_key: str = Form(...)):
    db = request.state.db
    m = await db.get(LLMModel, model_id)
    if m:
        m.name = name
        m.model_id = model_id_val
        m.base_url = base_url
        m.api_key = api_key
        await db.commit()
        from relay import relay
        await relay.reload_from_db()
    return RedirectResponse("/admin/models", status_code=302)


@router.post("/models/{model_id}/delete")
@require_admin
async def delete_model(request: Request, model_id: int):
    db = request.state.db
    m = await db.get(LLMModel, model_id)
    if m:
        await db.delete(m)
        await db.commit()
        from relay import relay
        await relay.reload_from_db()
    return RedirectResponse("/admin/models", status_code=302)
