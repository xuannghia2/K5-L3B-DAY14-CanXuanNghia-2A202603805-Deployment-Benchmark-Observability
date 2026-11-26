> Bài làm: [Mission Answers](MISSION_ANSWERS.md) · [Deployment](DEPLOYMENT.md) · [Benchmark Report](BENCHMARK_REPORT.md) · [Agent public](https://day14-production-agent-haua.onrender.com/health)

# Day 14 — Deployment, Benchmark & Observability

> Đưa agent lên cloud, đo xem nó nhanh và đúng tới đâu, rồi giám sát nó khi chạy thật.

> **AICB-P1 · VinUniversity 2026**
> Repository thực hành đi kèm bài giảng Day 14.
> Mỗi phần có ví dụ **cơ bản** (hiểu concept) và **chuyên sâu** (production-ready).

> **Hình thức: CÁ NHÂN** · **Thời lượng:** 4 giờ tại lớp · **Deadline:** 23h59 (GMT+7) ngày lab, trừ khi Lab Coach thông báo khác
> **Đọc theo thứ tự:** README → [RULES](RULES.md) → [CHECKPOINTS](CHECKPOINTS.md) → [SUBMISSION](SUBMISSION.md) → [RUBRIC](RUBRIC.md)
> **Bài nộp:** repo `K5-<L3A|L3B>-DAY14-HoVaTen-MSSV-Deployment-Benchmark-Observability`, nộp **link repo** trên LMS (chi tiết: [SUBMISSION.md](SUBMISSION.md)).

### ⚠️ Lưu ý khi làm bài (K5)

Lớp K5 làm khác `CODE_LAB.md` và `DAY14_DELIVERY_CHECKLIST.md` ở vài chỗ dưới đây. Đọc trước khi bắt đầu:

1. **Code Part 6 nằm trong `06-lab-complete/`.** Làm ngay trong thư mục đó của bản fork. Bỏ qua cây thư mục `app/` ở gốc repo vẽ trong [DAY14_DELIVERY_CHECKLIST.md](DAY14_DELIVERY_CHECKLIST.md) mục 2.
2. **Windows: chạy Python trong WSL2** (Docker Desktop bật tích hợp WSL2). Chạy Python Windows, kể cả từ Git Bash, thì `check_production_ready.py` không gửi được SIGTERM, tiêu chí Graceful shutdown luôn ⚠️ và không bao giờ đạt `PASS 12/12`. Kiểm tra trong terminal làm bài: `python -c "import os; print(os.name)"` phải in `posix`.
3. **Part 1 và Part 2: app bản develop nhận `question` qua query**, không nhận JSON (gửi JSON sẽ bị 422). Gọi bằng `curl -X POST "http://localhost:8000/ask?question=Hello"`. Các bản dùng chung cổng 8000: tắt server cũ (Ctrl+C hoặc dừng container) trước khi bật bản mới.
4. **Part 2: build image từ gốc repo**, không `cd` vào thư mục con, vì Dockerfile `COPY` theo đường dẫn tính từ gốc:
   `docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .` và `docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .`
5. **Docker Compose ở Part 2 và Part 5 cần file `.env.local`.** Repo không có sẵn nên `docker compose up` báo thiếu file. Chạy `touch .env.local` trong `02-docker/production/` và `05-scaling-reliability/production/` (để trống cũng được, bài dùng mock LLM).
6. **Part 4:**
   - Bản develop: bật bằng `AGENT_API_KEY=secret-key-123 python app.py` để lệnh curl "có key" trong `CODE_LAB.md` khớp.
   - Bản production (Exercise 4.2, 4.3): tắt bản develop trước (cùng cổng 8000), cài `requirements.txt` của thư mục đó. Lấy token ở `POST /auth/token` với tài khoản `student` / `demo123` (không phải `/token` và `admin`/`secret` như trong `CODE_LAB.md`); tài khoản này giới hạn 10 request/phút. Dùng token đó cho vòng lặp 4.3.
   - Thêm `-i` vào curl để thấy mã HTTP (401 / 200 / 429) khi dán vào bài. Che token trước khi dán.
7. **Part 5 (Exercise 5.4, 5.5):** stack trong `05-scaling-reliability/production/` mở cổng **8080**, endpoint là **`POST /chat`** (không phải cổng 80 và `/ask`). Chạy `docker compose -p k5-day14-scaling up -d --build --scale agent=3` rồi `python test_stateless.py`. Script gửi 5 câu trong cùng một session rồi đọc history, không tự tắt instance nào. Xong thì `docker compose -p k5-day14-scaling down` để trả cổng. Lý do có `-p` và `--build`: `02-docker/production/`, `05-scaling-reliability/production/` và `06-lab-complete/benchmark-observability/production/` cùng tên thư mục `production`, nên nếu không đặt `-p` thì Compose gán chung tên project và chung image `production-agent`, dễ chạy nhầm app của bài trước. Mỗi lệnh `docker compose` của một bài (kể cả `logs`, `down`) dùng cùng một `-p`.
8. **Part 3 deploy luôn agent Part 6** (xem [CHECKPOINTS.md](CHECKPOINTS.md), CP6). Khi làm theo Exercise 3.1/3.2 trong `CODE_LAB.md`, bỏ các lệnh `cd ../../03-cloud-deployment/...` và chạy trong `06-lab-complete/` (Railway: `cd 06-lab-complete && railway up`; Railway CLI cài bằng `npm`, cần Node.js). Agent cần Redis trên cloud: tạo một Redis trên nền tảng, đặt `REDIS_URL` của service agent trỏ tới nó, kiểm `/ready` trả 200 trước khi chụp ảnh. Dùng Render thì `render.yaml` nằm trong thư mục con và phải tự khai báo Redis; kẹt thì hỏi Lab Coach. Lệnh tự kiểm dùng bản ở CP6, không dùng mục Self-Test của checklist (mục đó gọi `GET /ask` nên ra 405 thay vì 401).
9. **"Bảng Hợp đồng"** mà `CODE_LAB.md` và checklist nhắc tới là mục *Script chấm dựa vào những tiêu chí dưới đây* trong [06-lab-complete/README.md](06-lab-complete/README.md).
10. **Exercise 7.3** sửa `KNOWLEDGE_BASE` trong `06-lab-complete/benchmark-observability/develop/utils/mock_llm.py`, rồi tắt và bật lại agent v2 (app không tự nạp lại code). Stack Docker ở Part 7 Bước 2 dùng bản `production/utils/mock_llm.py`; muốn stack đó cũng đạt 100% thì chép phần đã sửa sang.
11. **Part 7: `load_test.py` và `run_eval.py` chỉ ghi file JSON khi có `--out`.** Lệnh eval mặc định gọi cổng 8000, agent v2 chạy ở 8002 thì thêm `--url http://localhost:8002`. Dùng các lệnh có sẵn tên file ở CP7 và CP8 trong [CHECKPOINTS.md](CHECKPOINTS.md).

---

## Cấu Trúc Project

```
K5-L3-Day14-Deployment-Agent-Benchmark-Observability/
├── 01-localhost-vs-production/     # Section 1: Dev ≠ Production
│   ├── develop/                      #   Agent "đúng kiểu localhost"
│   └── production/                   #   12-Factor compliant agent
│
├── 02-docker/                      # Section 2: Containerization
│   ├── develop/                      #   Dockerfile đơn giản
│   └── production/                   #   Multi-stage + Docker Compose stack
│
├── 03-cloud-deployment/            # Section 3: Cloud Options
│   ├── railway/                    #   Deploy Railway (< 5 phút)
│   ├── render/                     #   Deploy Render + render.yaml
│   └── production-cloud-run/         #   GCP Cloud Run + CI/CD
│
├── 04-api-gateway/                 # Section 4: Security
│   ├── develop/                      #   API Key authentication
│   └── production/                   #   JWT + Rate Limiting + Cost Guard
│
├── 05-scaling-reliability/         # Section 5: Scale & Reliability
│   ├── develop/                      #   Health check + graceful shutdown
│   └── production/                   #   Stateless + Redis + Nginx LB
│
├── 06-lab-complete/                # Lab 14: Production-ready agent
│   ├── (bản khung TODO — sinh viên tự làm, chấm bằng check_production_ready.py)
│   └── benchmark-observability/      #   Part 7: Benchmark & Observability
│       ├── develop/                  #     Metrics + load test + eval (chạy local)
│       └── production/               #     Prometheus + Grafana + Jaeger + Locust
│
├── Dockerfile_examples/            # Ví dụ Dockerfile (Go) + thứ tự layers
│   ├── Dockerfile                    #   Single-stage, COPY . . (chưa tối ưu)
│   ├── Dockerfile.deps-first         #   Dependencies trước, source sau (tối ưu)
│   └── Dockerfile.source-first       #   Source trước, dependencies sau (không tối ưu)
│
└── utils/                          # Mock LLM dùng chung (không cần API key)
```

---

## 🚀 Bắt Đầu Nhanh

**Muốn thử ngay?** → [QUICK_START.md](QUICK_START.md) (5 phút)

**Muốn học kỹ?** → [CODE_LAB.md](CODE_LAB.md) (4-5 giờ)

## Cách Học

| Bước | Làm gì |
|------|--------|
| 0 | **[Khuyến nghị]** Đọc [QUICK_START.md](QUICK_START.md) để thử nhanh |
| 1 | Đọc [CODE_LAB.md](CODE_LAB.md) để hiểu chi tiết |
| 2 | Chạy ví dụ **basic** trước — hiểu concept |
| 3 | So sánh với ví dụ **advanced** — thấy sự khác biệt |
| 4 | Tự làm Lab 06 từ bản khung, chạy `python check_production_ready.py` tới khi `PASS 12/12` |
| 4b | Benchmark và giám sát agent với `06-lab-complete/benchmark-observability`, điền Benchmark Report |
| 5 | Tham khảo [QUICK_REFERENCE.md](QUICK_REFERENCE.md) khi cần |
| 6 | Xem [TROUBLESHOOTING.md](TROUBLESHOOTING.md) khi gặp lỗi |

---

## Yêu Cầu

```bash
python 3.11+
docker & docker compose
```

Mỗi folder có `requirements.txt` riêng. Không cần API key thật — các ví dụ dùng **mock LLM** để chạy offline.

---

## Sections

| # | Folder | Concept chính |
|---|--------|--------------|
| 1 | `01-localhost-vs-production` | Dev/prod gap, 12-factor, secrets |
| 2 | `02-docker` | Dockerfile, multi-stage, docker-compose |
| 3 | `03-cloud-deployment` | Railway, Render, Cloud Run |
| 4 | `04-api-gateway` | Auth, rate limiting, cost protection |
| 5 | `05-scaling-reliability` | Health check, stateless, rolling deploy |
| 6 | `06-lab-complete` | **Final project: tự xây production agent từ bản khung TODO** |
| 7 | `06-lab-complete/benchmark-observability` | Load test, eval, Prometheus, Grafana, OpenTelemetry, alerts |

---

## 📚 Lab Materials

Chúng tôi đã chuẩn bị đầy đủ tài liệu hướng dẫn:

### Cho Sinh Viên

| Tài liệu | Mô tả | Thời gian |
|----------|-------|-----------|
| **[CODE_LAB.md](CODE_LAB.md)** | Hướng dẫn lab chi tiết từng bước | 4-5 giờ |
| **[QUICK_REFERENCE.md](QUICK_REFERENCE.md)** | Cheat sheet các lệnh và patterns | Tra cứu |
| **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** | Giải quyết lỗi thường gặp | Khi cần |

### Cho Giảng Viên

| Tài liệu | Mô tả |
|----------|-------|
| **[INSTRUCTOR_GUIDE.md](INSTRUCTOR_GUIDE.md)** | Hướng dẫn chấm điểm và đánh giá |

### Cách Sử Dụng

1. **Trước lab:** Đọc [CODE_LAB.md](CODE_LAB.md) để hiểu tổng quan
2. **Trong lab:** Làm theo từng Part, tham khảo [QUICK_REFERENCE.md](QUICK_REFERENCE.md)
3. **Gặp lỗi:** Xem [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
4. **Sau lab:** Nộp Part 6 Final Project và Part 7 Benchmark Report để chấm điểm (xem [DAY14_DELIVERY_CHECKLIST.md](DAY14_DELIVERY_CHECKLIST.md))
