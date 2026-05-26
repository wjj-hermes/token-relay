from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from database import SessionLocal
from models import User, Product
from auth import hash_password, verify_password, create_token, get_current_user
from i18n import get_lang, t as _t

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _ctx(request: Request, **extra):
    lang = get_lang(request)
    ctx = {"lang": lang, "t": lambda k: _t(lang, k)}
    ctx.update(extra)
    return ctx


@router.get("/")
async def index(request: Request):
    user_id = get_current_user(request)
    user = None
    if user_id:
        async with SessionLocal() as db:
            user = await db.get(User, user_id)
    async with SessionLocal() as db:
        result = await db.execute(select(Product).where(Product.is_active == True))
        products = result.scalars().all()
    return templates.TemplateResponse(request, "index.html", _ctx(request, user=user, products=products))


@router.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", _ctx(request, error=""))


@router.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    lang = get_lang(request)
    async with SessionLocal() as db:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if not user or not verify_password(password, user.password_hash):
            return templates.TemplateResponse(request, "login.html", _ctx(request, error=_t(lang, "err_invalid_creds")))
        if not user.is_active:
            return templates.TemplateResponse(request, "login.html", _ctx(request, error=_t(lang, "err_disabled")))
        token = create_token(user.id, user.is_admin)
        resp = RedirectResponse("/user/dashboard", status_code=302)
        resp.set_cookie("token", token, httponly=True, max_age=72 * 3600)
        return resp


@router.get("/register")
async def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html", _ctx(request, error=""))


@router.post("/register")
async def register_submit(request: Request, username: str = Form(...), email: str = Form(...),
                          password: str = Form(...), password2: str = Form(...)):
    lang = get_lang(request)
    if password != password2:
        return templates.TemplateResponse(request, "register.html", _ctx(request, error=_t(lang, "err_pw_mismatch")))
    if len(password) < 6:
        return templates.TemplateResponse(request, "register.html", _ctx(request, error=_t(lang, "err_pw_short")))
    async with SessionLocal() as db:
        existing = await db.execute(select(User).where((User.username == username) | (User.email == email)))
        if existing.scalar_one_or_none():
            return templates.TemplateResponse(request, "register.html", _ctx(request, error=_t(lang, "err_taken")))
        user = User(username=username, email=email, password_hash=hash_password(password))
        db.add(user)
        await db.commit()
        await db.refresh(user)
        token = create_token(user.id, False)
        resp = RedirectResponse("/user/dashboard", status_code=302)
        resp.set_cookie("token", token, httponly=True, max_age=72 * 3600)
        return resp


@router.get("/logout")
async def logout():
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie("token")
    return resp


@router.get("/lang/{lang}")
async def switch_lang(request: Request, lang: str):
    referer = request.headers.get("referer", "/")
    resp = RedirectResponse(referer, status_code=302)
    resp.set_cookie("lang", lang if lang in ("zh", "en") else "zh", max_age=365 * 86400)
    return resp
