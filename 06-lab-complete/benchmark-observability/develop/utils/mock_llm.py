"""
Mock LLM cho Part 7 — Benchmark & Observability.

Khác với mock ở các section trước, mock này được thiết kế để có thứ ĐO ĐƯỢC:
  • Latency có jitter + "tail latency" (một phần nhỏ request chậm bất thường)
  • Lỗi upstream ngẫu nhiên (giống OpenAI/Anthropic trả 429/503)
  • Đếm token + tính cost theo bảng giá model
  • Knowledge base nhỏ để agent v2 (có retrieval) trả lời đúng hơn agent v1

Không cần API key. Tất cả hành vi chỉnh qua biến môi trường:

  MOCK_LATENCY_MS   latency cơ bản mỗi call (mặc định 120)
  MOCK_JITTER_MS    dao động ngẫu nhiên thêm vào (mặc định 60)
  MOCK_SLOW_RATE    tỉ lệ request bị chậm bất thường, 0..1 (mặc định 0.03)
  MOCK_SLOW_MS      độ chậm thêm của request "slow" (mặc định 1500)
  MOCK_ERROR_RATE   tỉ lệ call bị lỗi upstream, 0..1 (mặc định 0.01)
  MOCK_RETRIEVAL_MS latency của bước tìm tài liệu (mặc định 20)
"""
from __future__ import annotations

import asyncio
import os
import random
from dataclasses import dataclass


# ─────────────────────────────────────────────────────────
# Bảng giá (USD / 1K tokens) — mô phỏng model nhỏ vs model lớn
# ─────────────────────────────────────────────────────────
PRICING = {
    "mock-llm-small": {"input": 0.00015, "output": 0.0006, "latency_factor": 1.0},
    "mock-llm-large": {"input": 0.0025, "output": 0.01, "latency_factor": 2.5},
}
DEFAULT_MODEL = "mock-llm-small"

SYSTEM_PROMPT = (
    "Bạn là trợ lý kỹ thuật cho khoá học Deployment AI Agent. "
    "Trả lời ngắn gọn, chính xác, bằng tiếng Việt."
)


class LLMError(Exception):
    """Lỗi từ LLM provider (timeout, 429, 503...)."""


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    cost_usd: float


# ─────────────────────────────────────────────────────────
# Knowledge base — agent v2 "retrieve" từ đây (mô phỏng RAG)
# Mỗi entry: (các từ khoá kích hoạt, nội dung tài liệu)
# ─────────────────────────────────────────────────────────
KNOWLEDGE_BASE: list[tuple[list[str], str]] = [
    (["hpa", "kubernetes", "autoscal"],
     "Kubernetes HPA (Horizontal Pod Autoscaler) scale số pod dựa trên CPU, memory "
     "hoặc custom metrics như RPS hay độ dài hàng đợi."),
    (["jwt"],
     "API key là chuỗi bí mật cố định, không tự hết hạn. JWT là token có chữ ký số, chứa "
     "thông tin user và thời điểm hết hạn; server xác minh chữ ký mà không cần tra database."),
    (["multi-stage", "multi stage"],
     "Multi-stage build tách Dockerfile thành stage builder (cài compiler, build dependencies) "
     "và stage runtime chỉ copy kết quả cần thiết. Image cuối nhỏ hơn và ít lỗ hổng bảo mật hơn."),
    (["docker", "container"],
     "Container đóng gói code cùng dependencies và runtime thành image chạy giống nhau ở mọi môi trường. "
     "Docker build image từ Dockerfile, chạy được ở laptop lẫn cloud."),
    (["liveness", "health check", "/health"],
     "Liveness probe (GET /health) cho biết process còn sống. Nếu fail, platform sẽ restart container."),
    (["readiness", "/ready"],
     "Readiness probe (GET /ready) cho biết instance sẵn sàng nhận traffic. Nếu fail, load balancer "
     "ngừng route traffic tới instance đó nhưng không restart."),
    (["graceful", "sigterm"],
     "Graceful shutdown: khi nhận SIGTERM, app ngừng nhận request mới, chờ các request in-flight "
     "hoàn thành rồi mới thoát, nên không làm mất request của người dùng."),
    (["12-factor", "12 factor", "biến môi trường", "config"],
     "12-Factor App yêu cầu lưu config trong biến môi trường (environment variables), không hardcode "
     "secret trong code, giúp cùng một image chạy được ở dev, staging và production."),
    (["rate limit", "429"],
     "Rate limiting giới hạn số request mỗi client trong một cửa sổ thời gian, ví dụ 10 req/phút. "
     "Vượt giới hạn thì trả HTTP 429 Too Many Requests kèm header Retry-After."),
    (["stateless", "redis", "session"],
     "Stateless nghĩa là instance không giữ state trong memory; session được lưu ở Redis. "
     "Nhờ vậy có thể scale ngang nhiều instance sau load balancer."),
    (["load balancer", "nginx", "round-robin"],
     "Load balancer như Nginx phân phối request tới nhiều instance theo round-robin, "
     "và bỏ qua instance không healthy."),
    (["p95", "p99", "percentile", "tail latency", "trung bình"],
     "Percentile p95 là ngưỡng mà 95% request nhanh hơn. Latency trung bình (average) che giấu "
     "tail latency, nên SLO thường đặt theo p95 hoặc p99."),
    (["prometheus", "metric", "histogram", "counter"],
     "Prometheus pull metrics bằng cách scrape endpoint /metrics theo chu kỳ. Counter chỉ tăng "
     "(đếm request), Gauge lên xuống (request đang xử lý), Histogram chia latency vào các bucket "
     "để tính percentile bằng histogram_quantile."),
    (["cardinality", "label"],
     "Label có cardinality cao (user_id, request_id, câu hỏi) làm số time series bùng nổ và "
     "Prometheus tốn RAM. Chỉ dùng label có ít giá trị như route, status, model."),
    (["trace", "tracing", "span", "opentelemetry", "jaeger"],
     "Distributed tracing ghi lại một request đi qua những bước nào. Mỗi bước là một span có "
     "thời gian bắt đầu, kết thúc và attributes. OpenTelemetry thu thập trace và gửi tới Jaeger để xem."),
    (["slo", "sli", "error budget"],
     "SLI là chỉ số đo được (vd tỉ lệ request thành công), SLO là mục tiêu cho SLI (vd 99.5% trong 30 ngày). "
     "Error budget là phần được phép lỗi còn lại: 100% - SLO."),
    (["token", "cost", "chi phí", "budget"],
     "Chi phí LLM tính theo token: cost = input_tokens x giá input + output_tokens x giá output. "
     "Cần theo dõi cost theo thời gian thực và đặt budget alert."),
    (["golden dataset", "eval", "đánh giá chất lượng", "regression"],
     "Eval chất lượng dùng golden dataset: bộ câu hỏi có đáp án mong đợi. Chạy eval trước mỗi lần deploy "
     "để bắt regression, ví dụ accuracy giảm so với phiên bản trước."),
    (["log", "logging", "json"],
     "Structured logging ghi log dạng JSON với các field cố định (timestamp, level, request_id, trace_id) "
     "để dễ tìm kiếm, lọc và liên kết với trace."),
    (["cloud run", "serverless", "railway", "render"],
     "Cloud Run, Railway, Render là nền tảng chạy container managed: tự scale, tự cấp HTTPS, "
     "bạn chỉ cần cung cấp image và biến môi trường."),
]

# Agent v1 không có retrieval → chỉ "biết" vài câu chung chung như mock cũ
V1_RESPONSES = {
    "docker": "Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!",
    "deploy": "Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.",
    "health": "Agent đang hoạt động bình thường. All systems operational.",
}
GENERIC_RESPONSES = [
    "Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.",
    "Câu hỏi hay! Điều này phụ thuộc vào kiến trúc hệ thống và yêu cầu cụ thể của bạn.",
    "Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.",
]


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def estimate_tokens(text: str) -> int:
    """Ước lượng token ~ 4 ký tự/token. Tiếng Việt thực tế tốn token hơn tiếng Anh."""
    return max(1, len(text) // 4)


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    price = PRICING.get(model, PRICING[DEFAULT_MODEL])
    return (input_tokens / 1000) * price["input"] + (output_tokens / 1000) * price["output"]


def retrieve_context(question: str, top_k: int = 1) -> list[str]:
    """Tìm tài liệu liên quan trong knowledge base (keyword match, mô phỏng vector search)."""
    q = question.lower()
    scored = []
    for keywords, doc in KNOWLEDGE_BASE:
        hits = sum(1 for kw in keywords if kw in q)
        if hits:
            scored.append((hits, doc))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [doc for _, doc in scored[:top_k]]


async def search_knowledge_base(question: str, top_k: int = 1) -> list[str]:
    """Bản async của retrieve_context, có latency giống gọi vector database thật."""
    await asyncio.sleep(_env_float("MOCK_RETRIEVAL_MS", 20) / 1000 * random.uniform(0.7, 1.3))
    return retrieve_context(question, top_k)


def _compose_answer(question: str, context: list[str] | None) -> str:
    if context:
        return context[0]
    q = question.lower()
    for keyword, response in V1_RESPONSES.items():
        if keyword in q:
            return response
    return random.choice(GENERIC_RESPONSES)


async def generate(question: str, context: list[str] | None = None,
                   model: str = DEFAULT_MODEL) -> LLMResult:
    """
    Mock LLM call (async — không block event loop khi chịu tải).

    Raises:
        LLMError: mô phỏng lỗi upstream theo MOCK_ERROR_RATE.
    """
    price = PRICING.get(model, PRICING[DEFAULT_MODEL])

    prompt = SYSTEM_PROMPT + "\n" + "\n".join(context or []) + "\n" + question
    input_tokens = estimate_tokens(prompt)

    # Latency = base + jitter + phụ thuộc độ dài prompt, nhân hệ số model
    latency_ms = (
        _env_float("MOCK_LATENCY_MS", 120)
        + random.uniform(0, _env_float("MOCK_JITTER_MS", 60))
        + input_tokens * 0.2
    ) * price["latency_factor"]
    if random.random() < _env_float("MOCK_SLOW_RATE", 0.03):
        latency_ms += _env_float("MOCK_SLOW_MS", 1500)  # tail latency

    if random.random() < _env_float("MOCK_ERROR_RATE", 0.01):
        await asyncio.sleep(latency_ms / 2000)  # lỗi thường đến sớm hơn response thành công
        raise LLMError("Upstream LLM error: 503 Service Unavailable (mock)")

    await asyncio.sleep(latency_ms / 1000)

    text = _compose_answer(question, context)
    output_tokens = estimate_tokens(text)
    return LLMResult(
        text=text,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_s=latency_ms / 1000,
        cost_usd=calculate_cost(model, input_tokens, output_tokens),
    )
