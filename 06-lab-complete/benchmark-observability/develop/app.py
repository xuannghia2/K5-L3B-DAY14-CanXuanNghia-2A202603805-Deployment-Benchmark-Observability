"""
✅ DEVELOP — Agent có Observability cơ bản (chạy local, không cần Docker)

Agent này "tự khai báo" sức khoẻ của nó qua 2 kênh:
  1. Metrics  → GET /metrics (định dạng Prometheus)
  2. Logs     → JSON có request_id, latency, token, cost

Dùng kèm:
  • load_test.py        — benchmark hiệu năng (p50/p95/p99, RPS, error rate)
  • eval/run_eval.py    — benchmark chất lượng (accuracy trên golden dataset)

Chạy:
  pip install -r requirements.txt
  AGENT_VERSION=v1 python app.py      # agent cũ, không có retrieval
  AGENT_VERSION=v2 python app.py      # agent mới, có retrieval (RAG)
"""
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    disable_created_metrics,
    generate_latest,
)
from pydantic import BaseModel, Field

from utils import mock_llm

AGENT_VERSION = os.getenv("AGENT_VERSION", "v2")
LLM_MODEL = os.getenv("LLM_MODEL", mock_llm.DEFAULT_MODEL)
PORT = int(os.getenv("PORT", "8000"))

# ─────────────────────────────────────────────────────────
# Logging — mỗi dòng là một JSON object
# ─────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("agent")


def log_event(event: str, **fields):
    logger.info(json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }, ensure_ascii=False))


# ─────────────────────────────────────────────────────────
# Prometheus metrics
#
# Quy tắc đặt tên: <namespace>_<tên>_<đơn vị>, counter kết thúc bằng _total
# Label chỉ dùng giá trị ÍT (route, status, model) — KHÔNG dùng user_id,
# request_id hay nội dung câu hỏi (cardinality bùng nổ → Prometheus hết RAM)
# ─────────────────────────────────────────────────────────
disable_created_metrics()  # bỏ các series *_created cho /metrics dễ đọc hơn

LATENCY_BUCKETS = (0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0)

HTTP_REQUESTS = Counter(
    "http_requests_total", "Tổng số HTTP request",
    ["method", "route", "status"],
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds", "Thời gian xử lý HTTP request",
    ["method", "route"], buckets=LATENCY_BUCKETS,
)
IN_FLIGHT = Gauge(
    "agent_in_flight_requests", "Số request đang xử lý",
)
LLM_REQUESTS = Counter(
    "llm_requests_total", "Số lần gọi LLM",
    ["model", "status"],
)
LLM_LATENCY = Histogram(
    "llm_request_duration_seconds", "Latency của LLM call",
    ["model"], buckets=LATENCY_BUCKETS,
)
LLM_TOKENS = Counter(
    "llm_tokens_total", "Số token đã dùng",
    ["model", "type"],  # type = input | output
)
LLM_COST = Counter(
    "llm_cost_usd_total", "Tổng chi phí LLM (USD)",
    ["model"],
)
AGENT_INFO = Gauge(
    "agent_info", "Thông tin phiên bản agent (luôn = 1)",
    ["version", "model"],
)
AGENT_INFO.labels(version=AGENT_VERSION, model=LLM_MODEL).set(1)
QUESTION_LENGTH = Histogram(
    "agent_question_length_chars", "Question length in characters",
    buckets=(20, 50, 100, 200, 500, 1000, 2000),
)

# ─────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────
app = FastAPI(title="Observable Agent (develop)", version="1.0.0")
START_TIME = time.time()


@app.middleware("http")
async def observe_requests(request: Request, call_next):
    """Đo mọi request: đếm, đo latency, gắn request_id, ghi log."""
    if request.url.path == "/metrics":  # không tự đo việc Prometheus scrape
        return await call_next(request)

    request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
    request.state.request_id = request_id
    start = time.perf_counter()
    IN_FLIGHT.inc()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        IN_FLIGHT.dec()
        duration = time.perf_counter() - start
        # Dùng route TEMPLATE (vd "/ask"), không dùng URL thật → tránh cardinality cao
        route = request.scope.get("route")
        route_path = route.path if route else "unmatched"
        HTTP_REQUESTS.labels(request.method, route_path, str(status)).inc()
        HTTP_LATENCY.labels(request.method, route_path).observe(duration)
        log_event("http_request", request_id=request_id, method=request.method,
                  route=route_path, status=status, ms=round(duration * 1000, 1))


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int
    cost_usd: float


class AskResponse(BaseModel):
    answer: str
    model: str
    agent_version: str
    usage: Usage
    llm_latency_ms: float
    request_id: str


@app.post("/ask", response_model=AskResponse)
async def ask(body: AskRequest, request: Request):
    QUESTION_LENGTH.observe(len(body.question))
    # v2 có bước retrieval (RAG) → chính xác hơn nhưng prompt dài hơn → tốn token hơn
    context = await mock_llm.search_knowledge_base(body.question) if AGENT_VERSION == "v2" else None

    try:
        result = await mock_llm.generate(body.question, context=context, model=LLM_MODEL)
    except mock_llm.LLMError as exc:
        LLM_REQUESTS.labels(LLM_MODEL, "error").inc()
        log_event("llm_error", request_id=request.state.request_id, error=str(exc))
        raise HTTPException(status_code=503, detail="LLM upstream unavailable, please retry")

    LLM_REQUESTS.labels(result.model, "ok").inc()
    LLM_LATENCY.labels(result.model).observe(result.latency_s)
    LLM_TOKENS.labels(result.model, "input").inc(result.input_tokens)
    LLM_TOKENS.labels(result.model, "output").inc(result.output_tokens)
    LLM_COST.labels(result.model).inc(result.cost_usd)

    log_event("llm_call", request_id=request.state.request_id, model=result.model,
              agent_version=AGENT_VERSION, input_tokens=result.input_tokens,
              output_tokens=result.output_tokens, cost_usd=round(result.cost_usd, 6),
              llm_ms=round(result.latency_s * 1000, 1), retrieved=bool(context))

    return AskResponse(
        answer=result.text,
        model=result.model,
        agent_version=AGENT_VERSION,
        usage=Usage(input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                    cost_usd=round(result.cost_usd, 8)),
        llm_latency_ms=round(result.latency_s * 1000, 1),
        request_id=request.state.request_id,
    )


@app.get("/health")
def health():
    return {"status": "ok", "agent_version": AGENT_VERSION,
            "uptime_seconds": round(time.time() - START_TIME, 1)}


@app.get("/ready")
def ready():
    return {"ready": True}


@app.get("/metrics")
def metrics():
    """Endpoint cho Prometheus scrape. Mở trình duyệt xem thử: http://localhost:8000/metrics"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    log_event("startup", agent_version=AGENT_VERSION, model=LLM_MODEL, port=PORT)
    uvicorn.run(app, host="0.0.0.0", port=PORT, access_log=False)
