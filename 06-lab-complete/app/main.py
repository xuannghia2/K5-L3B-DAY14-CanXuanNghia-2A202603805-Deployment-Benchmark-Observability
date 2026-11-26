"""Production agent: auth, Redis guards, health probes and JSON logs."""
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from redis.exceptions import RedisError
from utils.mock_llm import ask as llm_ask
from .auth import verify_api_key
from .config import settings
from .cost_guard import check_budget, record_cost
from .rate_limiter import check_rate_limit
from .redis_client import r, redis_healthy

class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                           "level": record.levelname, "event": record.getMessage(),
                           **getattr(record, "fields", {})}, ensure_ascii=False)

logger = logging.getLogger("production_agent")
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger.handlers = [handler]
logger.setLevel(settings.log_level.upper())
logger.propagate = False

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", extra={"fields": {"environment": settings.environment}})
    yield
    # Uvicorn drains requests on SIGTERM before lifespan cleanup.
    r.close()
    logger.info("shutdown")

app = FastAPI(title="Production AI Agent", lifespan=lifespan)

@app.middleware("http")
async def request_logging(request: Request, call_next):
    start = time.perf_counter()
    request_id = uuid.uuid4().hex
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    route = request.scope.get("route")
    logger.info("request", extra={"fields": {
        "request_id": request_id, "method": request.method,
        "path": route.path if route else "unmatched", "status": response.status_code,
        "ms": round((time.perf_counter() - start) * 1000, 2)}})
    return response

@app.exception_handler(RedisError)
async def redis_unavailable(request: Request, exc: RedisError):
    logger.warning("redis_unavailable")
    return JSONResponse(status_code=503, content={"detail": "State store unavailable; retry later"})

@app.exception_handler(Exception)
async def internal_error(request: Request, exc: Exception):
    logger.error("internal_error", extra={"fields": {"error_type": type(exc).__name__}})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=200)

    @field_validator("question")
    @classmethod
    def non_blank(cls, value):
        if not value.strip():
            raise ValueError("Question must contain non-whitespace characters")
        return value

@app.get("/health")
def health():
    return {"status": "ok", "environment": settings.environment}

@app.get("/ready")
def ready():
    if not redis_healthy():
        raise HTTPException(503, "Redis unavailable")
    if not settings.agent_api_key:
        raise HTTPException(503, "API key not configured")
    return {"ready": True}

@app.post("/ask")
def ask(body: AskRequest, key: str = Depends(verify_api_key)):
    check_rate_limit(key)
    check_budget()
    answer = llm_ask(body.question)
    # The mock has no token usage API: apply a character-based estimate.
    input_tokens, output_tokens = max(1, len(body.question) // 4), max(1, len(answer) // 4)
    cost = record_cost(input_tokens, output_tokens)
    return {"question": body.question, "answer": answer,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": cost}}

