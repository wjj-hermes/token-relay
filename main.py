import json
import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import config
from relay import relay
from database import init_db, SessionLocal
from services.key_service import validate_api_key, check_balance, deduct_usage

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Auto-create admin user if not exists
    await _ensure_admin()
    await _seed_products()
    await _fix_products()
    await _seed_models()
    # Load models from database
    await relay.reload_from_db()
    logger.info(f"Token Relay starting on {config['server']['host']}:{config['server']['port']}")
    logger.info(f"Models: {[m['id'] for m in relay.list_models()]}")
    yield


app = FastAPI(title="Token Relay Station", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


async def _ensure_admin():
    from models import User
    from auth import hash_password
    import os
    admin_user = os.getenv("ADMIN_USERNAME", "admin")
    admin_pass = os.getenv("ADMIN_PASSWORD", "admin123")
    async with SessionLocal() as db:
        from sqlalchemy import select
        result = await db.execute(select(User).where(User.username == admin_user))
        if not result.scalar_one_or_none():
            user = User(
                username=admin_user,
                email=f"{admin_user}@localhost",
                password_hash=hash_password(admin_pass),
                is_admin=True,
            )
            db.add(user)
            await db.commit()
            logger.info(f"Created admin user: {admin_user}")


async def _seed_products():
    from models import Product
    async with SessionLocal() as db:
        from sqlalchemy import select
        result = await db.execute(select(Product))
        if result.scalars().first():
            return
        defaults = [
            Product(name="入门套餐", description="适合轻度使用和个人学习，约可进行 2000 次对话", type="quota", price=990, token_amount=100000, duration_days=365),
            Product(name="专业套餐", description="适合日常开发和小型团队，约可进行 10000 次对话", type="quota", price=4990, token_amount=500000, duration_days=365),
            Product(name="企业套餐", description="适合高频调用和企业级应用，约可进行 40000 次对话", type="quota", price=19900, token_amount=2000000, duration_days=365),
            Product(name="月度基础版", description="按月订阅，每日 5 万 token 额度，适合稳定用量", type="subscription", price=2990, duration_days=30, daily_limit=50000),
            Product(name="月度专业版", description="按月订阅，每日 20 万 token 额度，适合高频调用", type="subscription", price=9990, duration_days=30, daily_limit=200000),
        ]
        db.add_all(defaults)
        await db.commit()
        logger.info("Seeded default products")


async def _fix_products():
    """Fix corrupted subscription products."""
    from models import Product
    async with SessionLocal() as db:
        from sqlalchemy import select
        result = await db.execute(select(Product).where(Product.name.in_(["月度基础版", "月度专业版"])))
        products = result.scalars().all()
        fix_map = {
            "入门套餐": {"type": "quota", "price": 990, "token_amount": 100000, "duration_days": 365, "daily_limit": 0},
            "专业套餐": {"type": "quota", "price": 4990, "token_amount": 500000, "duration_days": 365, "daily_limit": 0},
            "企业套餐": {"type": "quota", "price": 19900, "token_amount": 2000000, "duration_days": 365, "daily_limit": 0},
            "月度基础版": {"type": "subscription", "price": 2990, "token_amount": 0, "duration_days": 30, "daily_limit": 50000},
            "月度专业版": {"type": "subscription", "price": 9990, "token_amount": 0, "duration_days": 30, "daily_limit": 200000},
        }
        for p in products:
            if p.name in fix_map:
                f = fix_map[p.name]
                changed = False
                for k, v in f.items():
                    if getattr(p, k) != v:
                        setattr(p, k, v)
                        changed = True
                if changed:
                    logger.info(f"Fixed product: {p.name}")
        await db.commit()


async def _seed_models():
    from models import LLMModel
    async with SessionLocal() as db:
        from sqlalchemy import select
        result = await db.execute(select(LLMModel))
        if result.scalars().first():
            return
        default = LLMModel(
            name="deepseek-v4-flash",
            model_id="deepseek-ai/deepseek-v4-flash",
            base_url="https://integrate.api.nvidia.com/v1",
            api_key="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",
        )
        db.add(default)
        await db.commit()
        logger.info("Seeded default model")


# Register routers
from routers.web import router as web_router
from routers.user import router as user_router
from routers.admin import router as admin_router
from routers.payment import router as payment_router

app.include_router(web_router)
app.include_router(user_router)
app.include_router(admin_router)
app.include_router(payment_router)


# === API Proxy Endpoints (OpenAI compatible) ===

@app.get("/health")
async def health():
    return {"status": "ok", "models": relay.list_models()}


@app.get("/debug/alipay")
async def debug_alipay():
    import os
    from services.alipay import ALIPAY_PRIVATE_KEY as mod_priv, ALIPAY_PUBLIC_KEY as mod_pub
    env_priv = os.getenv("ALIPAY_PRIVATE_KEY", "")
    env_pub = os.getenv("ALIPAY_PUBLIC_KEY", "")

    # Use the module-level values (which may have been loaded from file)
    priv = mod_priv
    pub = mod_pub

    # Analyze key format
    priv_stripped = priv.strip().replace("\\n", "").replace("\n", "").replace("\r", "")
    pub_stripped = pub.strip().replace("\\n", "").replace("\n", "").replace("\r", "")

    key_info = {
        "app_id": os.getenv("ALIPAY_APP_ID", ""),
        "env_priv_key_len": len(env_priv),
        "module_priv_key_len": len(priv_stripped),
        "priv_key_first_20": priv_stripped[:20],
        "priv_key_has_BEGIN": "BEGIN" in priv,
        "pub_key_len": len(pub_stripped),
        "pub_key_first_20": pub_stripped[:20],
        "pub_key_has_BEGIN": "BEGIN" in pub,
        "sandbox": os.getenv("ALIPAY_SANDBOX", "false"),
        "notify_url": os.getenv("ALIPAY_NOTIFY_URL", ""),
    }

    # Try to decode and analyze key structure
    try:
        import base64
        priv_bytes = base64.b64decode(priv_stripped)
        key_info["priv_der_len"] = len(priv_bytes)
        key_info["priv_der_first_10_hex"] = priv_bytes[:10].hex()
        # PKCS#8 starts with 30 82 xx xx 02 01 00 30 0d ...
        # PKCS#1 starts with 30 82 xx xx 02 01 00 02 82 ...
        if len(priv_bytes) > 6:
            key_info["priv_format_guess"] = "PKCS#8 (PRIVATE KEY)" if priv_bytes[6:8] == b'\x30\x0d' else "PKCS#1 (RSA PRIVATE KEY)" if priv_bytes[6:8] == b'\x02\x82' else "unknown"
    except Exception as e:
        key_info["base64_decode_error"] = str(e)

    # Try initializing the client
    try:
        from services.alipay import _get_client
        alipay = _get_client()
        key_info["client_init"] = "SUCCESS"

        # Try raw API call to see actual response
        try:
            import httpx, json as _json, time as _time
            biz = _json.dumps({"out_trade_no": "TEST_ORDER_001", "total_amount": "0.01", "subject": "test"})
            params = {
                "app_id": "2021006156623714",
                "method": "alipay.trade.precreate",
                "format": "JSON",
                "charset": "utf-8",
                "sign_type": "RSA2",
                "timestamp": "2026-05-26 12:00:00",
                "version": "1.0",
                "biz_content": biz,
            }
            # Sign params
            unsigned = "&".join(f"{k}={params[k]}" for k in sorted(params))
            from Crypto.Signature import pkcs1_15
            from Crypto.Hash import SHA256
            from Crypto.PublicKey import RSA
            key = RSA.import_key(alipay._app_private_key)
            h = SHA256.new(unsigned.encode())
            signature = pkcs1_15.new(key).sign(h)
            import base64 as _b64
            params["sign"] = _b64.b64encode(signature).decode()
            resp = httpx.post("https://openapi.alipay.com/gateway.do", data=params, timeout=15)
            key_info["raw_response"] = resp.text[:1000]
        except Exception as e:
            import traceback
            key_info["raw_error"] = f"{type(e).__name__}: {e}"
            key_info["raw_traceback"] = traceback.format_exc()[-500:]
    except Exception as e:
        import traceback
        key_info["client_init"] = f"FAILED: {type(e).__name__}: {e}"
        key_info["traceback"] = traceback.format_exc()

    return key_info


@app.get("/v1/models")
async def list_models():
    return {"object": "list", "data": [{"id": m["id"], "object": "model", "created": int(time.time()), "owned_by": m["owned_by"]} for m in relay.list_models()]}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    # Validate API key from Authorization header
    auth = request.headers.get("Authorization", "")
    raw_key = auth[7:] if auth.startswith("Bearer ") else auth
    if not raw_key:
        raise HTTPException(status_code=401, detail="缺少 API Key")

    async with SessionLocal() as db:
        result = await validate_api_key(db, raw_key)
        if not result:
            raise HTTPException(status_code=401, detail="无效的 API Key")
        user, api_key = result

        # Check balance
        from sqlalchemy import select
        from models import Subscription
        subs_result = await db.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        subs = subs_result.scalars().all()
        if not await check_balance(user, subs):
            raise HTTPException(status_code=402, detail="余额不足，请充值")

    body = await request.json()
    model = body.get("model", "")
    if not model:
        raise HTTPException(status_code=400, detail="缺少 model 参数")
    messages = body.get("messages", [])
    kwargs = {k: body[k] for k in ("temperature", "max_tokens", "top_p", "tools", "tool_choice", "stop") if k in body}

    if body.get("stream"):
        async def event_stream():
            usage_data = {}
            try:
                async for chunk in relay.chat_stream(model, messages, **kwargs):
                    # Try to capture usage from final chunk
                    if "usage" in chunk:
                        usage_data = chunk["usage"]
                    yield f"data: {json.dumps(chunk)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': {'message': str(e), 'type': 'server_error'}})}\n\n"
            finally:
                # Deduct usage
                if usage_data:
                    async with SessionLocal() as db:
                        u = await db.get(type(user), user.id)
                        ak = await db.get(type(api_key), api_key.id)
                        if u and ak:
                            await deduct_usage(db, u, ak, model,
                                               usage_data.get("prompt_tokens", 0),
                                               usage_data.get("completion_tokens", 0))
        return StreamingResponse(event_stream(), media_type="text/event-stream")

    try:
        result = await relay.chat(model, messages, **kwargs)
        # Deduct usage
        usage = result.get("usage", {})
        async with SessionLocal() as db:
            u = await db.get(type(user), user.id)
            ak = await db.get(type(api_key), api_key.id)
            if u and ak:
                await deduct_usage(db, u, ak, model,
                                   usage.get("prompt_tokens", 0),
                                   usage.get("completion_tokens", 0))
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": {"message": str(e), "type": "server_error"}}, status_code=502)


# Legacy dashboard endpoint (redirect to new admin)
@app.get("/dashboard", response_class=HTMLResponse)
async def legacy_dashboard(request: Request):
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/admin/dashboard", status_code=301)


@app.get("/api/stats")
async def api_stats():
    return relay.get_stats()


@app.get("/api/providers")
async def api_providers():
    return [{"name": n, "base_url": p.base_url, "models": list(p.models.keys()), "keys": relay.key_manager.get_status(n)} for n, p in relay.providers.items()]


if __name__ == "__main__":
    import uvicorn
    sc = config.get("server", {})
    uvicorn.run(app, host=sc.get("host", "0.0.0.0"), port=sc.get("port", 8888))
# redeploy trigger
# force deploy Tue May 26 18:24:40     2026
