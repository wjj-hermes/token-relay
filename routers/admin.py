from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func

from auth import require_admin
from models import User, Product, Order, UsageLog, ApiKey
from database import SessionLocal

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="templates")


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
    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request, "user": request.state.user,
        "user_count": user_count, "order_count": order_count,
        "revenue": revenue, "total_tokens": total_tokens,
        "recent_orders": recent_orders,
    })


@router.get("/users")
@require_admin
async def admin_users(request: Request):
    db = request.state.db
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return templates.TemplateResponse("admin/users.html", {
        "request": request, "user": request.state.user, "users": users,
    })


@router.post("/users/{user_id}/toggle")
@require_admin
async def toggle_user(request: Request, user_id: int):
    db = request.state.db
    target = await db.get(User, user_id)
    if target:
        target.is_active = not target.is_active
        await db.commit()
    return RedirectResponse("/admin/users", status_code=302)


@router.get("/products")
@require_admin
async def admin_products(request: Request):
    db = request.state.db
    result = await db.execute(select(Product).order_by(Product.id))
    products = result.scalars().all()
    return templates.TemplateResponse("admin/products.html", {
        "request": request, "user": request.state.user, "products": products,
    })


@router.post("/products/create")
@require_admin
async def create_product(request: Request, name: str = Form(...), type: str = Form(...),
                         price: int = Form(...), token_amount: int = Form(0),
                         duration_days: int = Form(0), daily_limit: int = Form(0)):
    db = request.state.db
    product = Product(
        name=name, type=type, price=price,
        token_amount=token_amount, duration_days=duration_days, daily_limit=daily_limit,
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


@router.get("/orders")
@require_admin
async def admin_orders(request: Request):
    db = request.state.db
    result = await db.execute(select(Order).order_by(Order.created_at.desc()).limit(100))
    orders = result.scalars().all()
    return templates.TemplateResponse("admin/orders.html", {
        "request": request, "user": request.state.user, "orders": orders,
    })
