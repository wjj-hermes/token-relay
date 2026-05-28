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
    await _ensure_gpt55()
    await _ensure_codex_key()
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
    admin_pass = os.getenv("ADMIN_PASSWORD", "Wj123321@")
    async with SessionLocal() as db:
        from sqlalchemy import select
        result = await db.execute(select(User).where(User.username == admin_user))
        existing = result.scalar_one_or_none()
        if not existing:
            user = User(
                username=admin_user,
                email=f"{admin_user}@localhost",
                password_hash=hash_password(admin_pass),
                is_admin=True,
                balance=10000000,
            )
            db.add(user)
            await db.commit()
            logger.info(f"Created admin user: {admin_user}")
        else:
            existing.password_hash = hash_password(admin_pass)
            if existing.balance < 10000000:
                existing.balance = 10000000
            await db.commit()
            logger.info(f"Updated admin password")


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
            name="deepseek-ai/deepseek-v4-flash",
            model_id="deepseek-ai/deepseek-v4-flash",
            base_url="https://integrate.api.nvidia.com/v1",
            api_key="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",
        )
        db.add(default)
        await db.commit()
        logger.info("Seeded default model")


async def _ensure_gpt55():
    from models import LLMModel
    async with SessionLocal() as db:
        from sqlalchemy import select
        result = await db.execute(select(LLMModel).where(LLMModel.name == "GPT5.5"))
        if result.scalar_one_or_none():
            return
        m = LLMModel(
            name="GPT5.5",
            model_id="mimo-v2.5-pro",
            base_url="https://token-plan-cn.xiaomimimo.com/v1",
            api_key="tp-c6ja7uur7jmeau1hsbunnn3y1exktw5996kp5oeqfexhxh56",
        )
        db.add(m)
        await db.commit()
        logger.info("Added GPT5.5 model (mimo-v2.5-pro)")


async def _ensure_codex_key():
    from models import User, ApiKey
    from services.key_service import generate_key
    async with SessionLocal() as db:
        from sqlalchemy import select
        # Find admin user
        result = await db.execute(select(User).where(User.is_admin == True))
        admin = result.scalar_one_or_none()
        if not admin:
            return
        # Check if codex key already exists
        result = await db.execute(select(ApiKey).where(ApiKey.user_id == admin.id, ApiKey.name == "codex"))
        if result.scalar_one_or_none():
            return
        key_str = generate_key()
        key = ApiKey(user_id=admin.id, key=key_str, name="codex")
        db.add(key)
        await db.commit()
        logger.info(f"Created codex API key: {key_str}")


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


@app.post("/v1/responses")
async def responses_api(request: Request):
    """OpenAI Responses API compatible endpoint, converts to Chat Completions internally."""
    auth = request.headers.get("Authorization", "")
    raw_key = auth[7:] if auth.startswith("Bearer ") else auth
    if not raw_key:
        raise HTTPException(status_code=401, detail="缺少 API Key")

    async with SessionLocal() as db:
        result = await validate_api_key(db, raw_key)
        if not result:
            raise HTTPException(status_code=401, detail="无效的 API Key")
        user, api_key = result
        from sqlalchemy import select
        from models import Subscription
        subs_result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
        subs = subs_result.scalars().all()
        if not await check_balance(user, subs):
            raise HTTPException(status_code=402, detail="余额不足，请充值")

    body = await request.json()
    model = body.get("model", "")
    if not model:
        raise HTTPException(status_code=400, detail="缺少 model 参数")

    # Convert Responses API input to messages
    raw_input = body.get("input", "")
    if isinstance(raw_input, str):
        messages = [{"role": "user", "content": raw_input}]
    elif isinstance(raw_input, list):
        messages = []
        for item in raw_input:
            if isinstance(item, str):
                messages.append({"role": "user", "content": item})
            elif isinstance(item, dict):
                role = item.get("role", "user")
                content = item.get("content", "")
                if isinstance(content, list):
                    text_parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                    content = "\n".join(text_parts)
                messages.append({"role": role, "content": content})
    else:
        messages = [{"role": "user", "content": str(raw_input)}]

    kwargs = {}
    if "max_output_tokens" in body:
        kwargs["max_tokens"] = body["max_output_tokens"]
    if "temperature" in body:
        kwargs["temperature"] = body["temperature"]

    is_stream = body.get("stream", False)

    if is_stream:
        async def event_stream():
            usage_data = {}
            resp_id = f"resp_{int(time.time())}"
            try:
                async for chunk in relay.chat_stream(model, messages, **kwargs):
                    if "usage" in chunk:
                        usage_data = chunk["usage"]
                    # Convert chunk to Responses API format
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    if delta.get("content"):
                        event = {
                            "type": "response.output_text.delta",
                            "item_id": f"msg_{resp_id}",
                            "delta": delta["content"]
                        }
                        yield f"data: {json.dumps(event)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': {'message': str(e)}})}\n\n"
            finally:
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
        usage = result.get("usage", {})
        async with SessionLocal() as db:
            u = await db.get(type(user), user.id)
            ak = await db.get(type(api_key), api_key.id)
            if u and ak:
                await deduct_usage(db, u, ak, model,
                                   usage.get("prompt_tokens", 0),
                                   usage.get("completion_tokens", 0))

        # Convert to Responses API format
        choice = result.get("choices", [{}])[0]
        message = choice.get("message", {})
        content_text = message.get("content", "") or ""
        resp_id = f"resp_{int(time.time())}"
        response = {
            "id": resp_id,
            "object": "response",
            "created": result.get("created", int(time.time())),
            "model": model,
            "output": [
                {
                    "type": "message",
                    "id": f"msg_{resp_id}",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": content_text
                        }
                    ]
                }
            ],
            "usage": {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0)
            }
        }
        return JSONResponse(response)
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
