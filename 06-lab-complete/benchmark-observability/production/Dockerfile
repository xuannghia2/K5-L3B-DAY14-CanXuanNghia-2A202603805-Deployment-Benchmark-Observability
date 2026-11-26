# ============================================================
# Dockerfile — Observable Agent (multi-stage, non-root)
# ============================================================

# Stage 1: Builder
FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# Stage 2: Runtime
FROM python:3.11-slim AS runtime

RUN groupadd -r agent && useradd -r -g agent -d /app agent

WORKDIR /app

COPY --from=builder /root/.local /home/agent/.local
COPY app/ ./app/
COPY utils/ ./utils/

RUN chown -R agent:agent /app

USER agent

ENV PATH=/home/agent/.local/bin:$PATH
ENV PYTHONUSERBASE=/home/agent/.local
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c \
    "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" \
    || exit 1

# ⚠️ Chỉ 1 worker/container: prometheus_client lưu metric trong memory của TỪNG process.
#    Nhiều worker → mỗi lần scrape trúng 1 worker khác nhau → số liệu nhảy lung tung.
#    Muốn scale → tăng số container (docker compose --scale agent=3), không tăng --workers.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
