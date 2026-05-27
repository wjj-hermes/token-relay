from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from auth import require_login
from database import SessionLocal
from models import Order, Product
from services.order_service import create_order, complete_order
from services.alipay import create_qrcode_pay, verify_notify
from i18n import get_lang, t as _t

router = APIRouter(prefix="/pay")
templates = Jinja2Templates(directory="templates")


def _ctx(request: Request, **extra):
    lang = get_lang(request)
    ctx = {"lang": lang, "t": lambda k: _t(lang, k)}
    ctx.update(extra)
    return ctx


@router.post("/create")
@require_login
async def pay_create(request: Request, product_id: int = Form(...)):
    user = request.state.user
    db = request.state.db
    try:
        order = await create_order(db, user.id, product_id)
    except ValueError as e:
        return RedirectResponse(f"/?error={e}", status_code=302)

    product = await db.get(Product, product_id)
    amount_yuan = f"{order.amount / 100:.2f}"
    pay_url = create_qrcode_pay(order.order_no, amount_yuan, product.name)

    if pay_url:
        return RedirectResponse(pay_url, status_code=302)
    return RedirectResponse(f"/?error=payment_failed", status_code=302)


@router.get("/qrcode/{order_no}")
@require_login
async def pay_qrcode(request: Request, order_no: str):
    user = request.state.user
    db = request.state.db
    result = await db.execute(select(Order).where(Order.order_no == order_no, Order.user_id == user.id))
    order = result.scalar_one_or_none()
    if not order:
        return RedirectResponse("/user/dashboard", status_code=302)
    product = await db.get(Product, order.product_id)
    amount_yuan = f"{order.amount / 100:.2f}"
    pay_url = create_qrcode_pay(order.order_no, amount_yuan, product.name)
    if pay_url:
        return RedirectResponse(pay_url, status_code=302)
    return RedirectResponse(f"/?error=payment_failed", status_code=302)


@router.post("/notify")
async def pay_notify(request: Request):
    form = await request.form()
    params = dict(form)

    if not verify_notify(params):
        return HTMLResponse("fail")

    trade_status = params.get("trade_status", "")
    order_no = params.get("out_trade_no", "")
    trade_no = params.get("trade_no", "")

    if trade_status in ("TRADE_SUCCESS", "TRADE_FINISHED"):
        async with SessionLocal() as db:
            await complete_order(db, order_no, trade_no)

    return HTMLResponse("success")


@router.get("/return")
async def pay_return(request: Request):
    """Alipay redirect-back after payment. Show success page."""
    return templates.TemplateResponse(request, "pay/success.html", _ctx(request))


@router.get("/status/{order_no}")
@require_login
async def pay_status(request: Request, order_no: str):
    user = request.state.user
    db = request.state.db
    result = await db.execute(select(Order).where(Order.order_no == order_no, Order.user_id == user.id))
    order = result.scalar_one_or_none()
    if not order:
        return {"status": "not_found"}
    return {"status": order.status}
