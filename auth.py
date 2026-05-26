import os
import hashlib
import secrets
from datetime import datetime, timedelta
from functools import wraps

import jwt
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import SessionLocal
from models import User

JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production-use-a-long-random-string")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 72


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}${h}"


def verify_password(password: str, password_hash: str) -> bool:
    salt, h = password_hash.split("$", 1)
    return hashlib.sha256((salt + password).encode()).hexdigest() == h


def create_token(user_id: int, is_admin: bool = False) -> str:
    payload = {
        "sub": str(user_id),
        "admin": is_admin,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def get_current_user(request: Request):
    token = request.cookies.get("token")
    if not token:
        return None
    payload = decode_token(token)
    # We return user_id; caller fetches from DB
    return int(payload["sub"])


def require_login(func):
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        user_id = get_current_user(request)
        if not user_id:
            return RedirectResponse("/login", status_code=302)
        async with SessionLocal() as db:
            user = await db.get(User, user_id)
            if not user or not user.is_active:
                resp = RedirectResponse("/login", status_code=302)
                resp.delete_cookie("token")
                return resp
            request.state.user = user
            request.state.db = db
            return await func(request, *args, **kwargs)
    return wrapper


def require_admin(func):
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        user_id = get_current_user(request)
        if not user_id:
            return RedirectResponse("/login", status_code=302)
        async with SessionLocal() as db:
            user = await db.get(User, user_id)
            if not user or not user.is_admin:
                raise HTTPException(status_code=403, detail="Admin access required")
            request.state.user = user
            request.state.db = db
            return await func(request, *args, **kwargs)
    return wrapper
