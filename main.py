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
    await _restore_users()
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


async def _restore_users():
    """Restore backed-up users that may be lost on Railway redeploy."""
    from models import User
    from auth import hash_password
    backed_up_users = [
        {"username": "Canoe", "email": "2155988624@qq.com", "balance": 10000000},
    ]
    async with SessionLocal() as db:
        from sqlalchemy import select
        for u in backed_up_users:
            result = await db.execute(select(User).where(User.username == u["username"]))
            if not result.scalar_one_or_none():
                user = User(
                    username=u["username"],
                    email=u["email"],
                    password_hash=hash_password("123456"),
                    is_admin=False,
                    balance=u["balance"],
                )
                db.add(user)
                logger.info(f"Restored user: {u['username']}")
        await db.commit()


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
    from database import DB_URL
    db_type = "postgresql" if "postgresql" in DB_URL or "postgres" in DB_URL else "sqlite"
    return {"status": "ok", "db": db_type, "models": relay.list_models()}


@app.get("/debug/get_key")
async def debug_get_key():
    """Temporary: get current admin API key."""
    from sqlalchemy import select
    from models import ApiKey, User
    async with SessionLocal() as db:
        result = await db.execute(select(User).where(User.is_admin == True))
        admin = result.scalar_one_or_none()
        if not admin:
            return {"error": "No admin user"}
        result = await db.execute(select(ApiKey).where(ApiKey.user_id == admin.id))
        keys = result.scalars().all()
        if not keys:
            return {"error": "No API keys found"}
        return {"key": keys[0].key}




@app.get("/v1/models")
async def list_models():
    return {"object": "list", "data": [{"id": m["id"], "object": "model", "created": int(time.time()), "owned_by": m["owned_by"]} for m in relay.list_models()]}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    # Try multiple auth sources
    auth = request.headers.get("Authorization", "")
    raw_key = auth[7:] if auth.startswith("Bearer ") else auth
    if not raw_key:
        raw_key = request.headers.get("X-API-Key", "")
    if not raw_key:
        raw_key = request.query_params.get("api_key", "")
    if not raw_key:
        raise HTTPException(status_code=401, detail="缺少 API Key")

    body = await request.json()
    model = body.get("model", "")
    if not model:
        raise HTTPException(status_code=400, detail="缺少 model 参数")

    async with SessionLocal() as db:
        result = await validate_api_key(db, raw_key)
        if not result:
            raise HTTPException(status_code=401, detail="无效的 API Key")
        user, api_key = result

        # Check model access
        from services.key_service import check_model_access
        if not check_model_access(api_key, model):
            raise HTTPException(status_code=403, detail=f"此 Key 无权访问模型 {model}")

        # Check balance
        from sqlalchemy import select
        from models import Subscription
        subs_result = await db.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        subs = subs_result.scalars().all()
        if not await check_balance(user, subs):
            raise HTTPException(status_code=402, detail="余额不足，请充值")

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
            except Exception as e:
                logger.error(f"Stream error for {model}: {e}")
                yield f"data: {json.dumps({'error': {'message': str(e), 'type': 'server_error'}})}\n\n"
            finally:
                yield "data: [DONE]\n\n"
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


_last_request_body = {}

@app.get("/debug/last_request")
async def debug_last_request():
    return _last_request_body

@app.post("/v1/responses")
async def responses_api(request: Request):
    """OpenAI Responses API compatible endpoint, converts to Chat Completions internally."""
    global _last_request_body
    # Try multiple auth sources
    auth = request.headers.get("Authorization", "")
    raw_key = auth[7:] if auth.startswith("Bearer ") else auth
    if not raw_key:
        raw_key = request.headers.get("X-API-Key", "")
    if not raw_key:
        raw_key = request.query_params.get("api_key", "")
    # Try to get from request body
    if not raw_key:
        try:
            body_bytes = await request.body()
            body_text = body_bytes.decode()
            import re
            key_match = re.search(r'"api_key"\s*:\s*"([^"]+)"', body_text)
            if key_match:
                raw_key = key_match.group(1)
        except:
            pass
    # Temporarily skip auth for debugging
    user = None
    api_key = None
    if raw_key:
        async with SessionLocal() as db:
            result = await validate_api_key(db, raw_key)
            if result:
                user, api_key = result

    body = await request.json()
    _last_request_body = {k: (v[:500] if isinstance(v, str) else v) for k, v in body.items()}
    model = body.get("model", "")
    if not model:
        raise HTTPException(status_code=400, detail="缺少 model 参数")
    instructions = body.get("instructions", "")
    raw_input = body.get("input", "")
    messages = []
    system_parts = []
    if instructions:
        system_parts.append(instructions)
    if isinstance(raw_input, str):
        messages.append({"role": "user", "content": raw_input})
    elif isinstance(raw_input, list):
        for item in raw_input:
            if isinstance(item, str):
                messages.append({"role": "user", "content": item})
            elif isinstance(item, dict):
                role = item.get("role", "user")
                content = item.get("content", "")
                if isinstance(content, list):
                    text_parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") in ("text", "input_text")]
                    content = "\n".join(text_parts)
                # Merge developer/system into a single system message
                if role in ("developer", "system"):
                    system_parts.append(content)
                else:
                    messages.append({"role": role, "content": content})
    else:
        messages.append({"role": "user", "content": str(raw_input)})
    # Prepend merged system message
    if system_parts:
        messages.insert(0, {"role": "system", "content": "\n\n".join(system_parts)})
    _last_request_body["_messages_sent"] = [{"role": m["role"], "content": m["content"][:300]} for m in messages]

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
            msg_id = f"msg_{resp_id}"
            full_text = ""
            try:
                # Send response.created
                yield f"data: {json.dumps({'type': 'response.created', 'response': {'id': resp_id, 'object': 'response', 'model': model, 'output': []}})}\n\n"
                # Send response.output_item.added
                yield f"data: {json.dumps({'type': 'response.output_item.added', 'output_index': 0, 'item': {'type': 'message', 'id': msg_id, 'role': 'assistant', 'content': []}})}\n\n"
                # Send response.content_part.added
                yield f"data: {json.dumps({'type': 'response.content_part.added', 'item_id': msg_id, 'output_index': 0, 'content_index': 0, 'part': {'type': 'output_text', 'text': ''}})}\n\n"

                async for chunk in relay.chat_stream(model, messages, **kwargs):
                    if "usage" in chunk:
                        usage_data = chunk["usage"]
                    choices = chunk.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        if delta.get("content"):
                            full_text += delta["content"]
                            yield f"data: {json.dumps({'type': 'response.output_text.delta', 'item_id': msg_id, 'output_index': 0, 'content_index': 0, 'delta': delta['content']})}\n\n"

            except Exception as e:
                logger.error(f"Stream error for {model}: {e}")
                yield f"data: {json.dumps({'type': 'response.output_text.delta', 'item_id': msg_id, 'output_index': 0, 'content_index': 0, 'delta': f'\\n\\n[Stream error: {str(e)[:200]}]'})}\n\n"
            finally:
                # Always send completion events so the client sees response.completed
                try:
                    yield f"data: {json.dumps({'type': 'response.output_text.done', 'item_id': msg_id, 'output_index': 0, 'content_index': 0, 'text': full_text})}\n\n"
                    yield f"data: {json.dumps({'type': 'response.content_part.done', 'item_id': msg_id, 'output_index': 0, 'content_index': 0, 'part': {'type': 'output_text', 'text': full_text}})}\n\n"
                    yield f"data: {json.dumps({'type': 'response.output_item.done', 'output_index': 0, 'item': {'type': 'message', 'id': msg_id, 'role': 'assistant', 'content': [{'type': 'output_text', 'text': full_text}]}})}\n\n"
                    inp = usage_data.get('prompt_tokens', 0)
                    out = usage_data.get('completion_tokens', 0)
                    yield f"data: {json.dumps({'type': 'response.completed', 'response': {'id': resp_id, 'object': 'response', 'model': model, 'output': [{'type': 'message', 'id': msg_id, 'role': 'assistant', 'content': [{'type': 'output_text', 'text': full_text}]}], 'usage': {'input_tokens': inp, 'output_tokens': out, 'total_tokens': inp + out}}})}\n\n"
                    yield "data: [DONE]\n\n"
                except Exception:
                    pass
                if usage_data and user and api_key:
                    async with SessionLocal() as db:
                        u = await db.get(type(user), user.id)
                        ak = await db.get(type(api_key), api_key.id)
                        if u and ak:
                            await deduct_usage(db, u, ak, model,
                                               usage_data.get("prompt_tokens", 0),
                                               usage_data.get("completion_tokens", 0))
        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )

    try:
        result = await relay.chat(model, messages, **kwargs)
        usage = result.get("usage", {})
        if user and api_key:
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
