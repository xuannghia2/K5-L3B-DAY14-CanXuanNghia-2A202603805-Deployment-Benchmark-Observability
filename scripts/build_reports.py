"""Build submission text from measured JSON/CSV and preserved checker output."""
import csv, json, re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
R=ROOT/"reports"
def read(name): return json.loads((R/name).read_text(encoding="utf-8"))
def write(name,text): (ROOT/name).write_text(text.strip()+"\n",encoding="utf-8")
def line(path,needle):
    return next(i for i,s in enumerate((ROOT/path).read_text(encoding="utf-8").splitlines(),1) if needle in s)
def ref(path,needle): return f"[{path}:{line(path,needle)}]({path}#L{line(path,needle)})"
def table(headers,rows):
    return "| "+" | ".join(headers)+" |\n|"+ "|".join("---" for _ in headers)+"|\n"+ "\n".join("| "+" | ".join(map(str,row))+" |" for row in rows)
env=read("environment.json")
loads=[read(f"load_v2_c{c}.json") for c in (1,10,50,100)]
slow=[read(f"load_v2_slow_{s}.json") for s in ("0","0.03","0.1")]
ev=[read(n) for n in ("eval_v1.json","eval_v2.json","eval_v2_fixed.json")]
concurrency=table(["Concurrency","RPS","p50 ms","p95 ms","p99 ms","Error rate","SLO"],[
    [d["concurrency"],d["rps"],d["latency_ms"]["p50"],d["latency_ms"]["p95"],d["latency_ms"]["p99"],
     f'{d["error_rate"]:.2%}',"PASS" if d["slo"]["passed"] else "FAIL"] for d in loads])
tails=table(["MOCK_SLOW_RATE","avg ms","p95 ms","p99 ms"],[
    [s,d["latency_ms"]["avg"],d["latency_ms"]["p95"],d["latency_ms"]["p99"]] for s,d in zip(("0","0.03","0.1"),slow)])
quality=table(["Chỉ số","v1","v2 ban đầu","v2 sửa KB"],[
    ["Accuracy",*[f'{d["passed"]}/{d["total"]} ({d["accuracy"]:.2%})' for d in ev]],
    ["Avg tokens / câu",*[d["avg_tokens"] for d in ev]],
    ["Tổng cost USD",*[d["total_cost_usd"] for d in ev]],
    ["Cost / câu đúng USD",*[d["cost_per_correct_usd"] for d in ev]],
    ["Quality gate",*["PASS" if d["quality_gate"]["passed"] else "FAIL" for d in ev]],
    ["p95 ms",*[d["latency_ms"]["p95"] for d in ev]],
])
missing=table(["ID","Keywords thiếu","Cách sửa"],[
    [d["id"],", ".join(d["missing_keywords"]),"Bổ sung tài liệu JWT" if "security" in d["id"] else "Bổ sung tài liệu Kubernetes HPA"]
    for d in ev[1]["results"] if not d["passed"]])
obs="Chưa có kết quả Docker observability. Không suy ra số đo hoặc tạo ảnh thay thế."
scaling="Chưa có CSV Locust."
if (R/"trace-evidence.json").exists():
    e=read("trace-evidence.json")
    trace=e["slow"]
    spans=trace["spans"]
    total=max(s["startTime"]+s["duration"] for s in spans)-min(s["startTime"] for s in spans)
    chat=max((s for s in spans if s["operationName"].startswith("chat ")),key=lambda s:s["duration"])
    alerts=read("chaos-alerts.json")
    p=read("prometheus-snapshot.json")
    obs=f"""### 4.1 Dashboard và trace
- [Grafana có tải](screenshots/grafana-dashboard.png)
- [Trace chậm](screenshots/jaeger-slow-trace.png)
- [Trace lỗi](screenshots/jaeger-error-trace.png)
- [Hai alert firing đồng thời](screenshots/prometheus-alert-firing.png)

Ảnh và dữ liệu lấy từ GitHub Actions Linux, cùng stack Compose, không phải từ máy Windows.
Snapshot Prometheus: [reports/prometheus-snapshot.json](reports/prometheus-snapshot.json).
p95 = {float(p["p95"][0]["value"][1])*1000:.1f} ms; avg = {float(p["avg"][0]["value"][1])*1000:.1f} ms.
Chênh lệch thể hiện tail latency; tải fault injection dùng để tạo ảnh không phải lượt scale benchmark.
Requests/s theo instance tại snapshot:
{table(["Instance", "Requests/s"], [[v["metric"]["instance"], round(float(v["value"][1]),2)] for v in p["requests_by_instance"]])}
Ảnh chaos dùng {len(p["requests_by_instance"])} instance được Prometheus scrape ở thời điểm này; đây là thí nghiệm riêng với hai lượt scaling ở mục 5.
Nginx chia traffic tương đối đều nếu các giá trị trên gần nhau; chưa dùng một snapshot để kết luận cho mọi thời điểm.
Input tokens gồm system prompt + retrieved context + câu hỏi, nên thường lớn hơn output ngắn.
Gọi /metrics qua Nginx trả HTTP {p["public_metrics_status"]}: config chặn đường này; Prometheus scrape trực tiếp từng agent.

### 4.2 Chaos
Chạy đồng thời MOCK_ERROR_RATE=0.2 và MOCK_SLOW_RATE=0.3 trên cùng stack, giữ tải 100 users.
Thời gian đo từ lúc bắt đầu recreate service đến lần poll thấy firing (poll 3 giây, có độ phân giải 3 giây):
{table(["Alert","Thời gian firing s"],alerts["first_firing_seconds"].items())}
Bằng chứng đầy đủ gồm mọi mẫu inactive/pending/firing: [chaos-alerts.json](reports/chaos-alerts.json).
Error rate và p95 phản ánh hai lỗi tương ứng. Thời gian firing gồm scrape, evaluation, cửa sổ rate và điều kiện for.
Không chạy thử thay model, pause instance hay v1 trong stack này; không ghi số cho những thí nghiệm chưa chạy.
Đổi v1 làm giảm chất lượng nhưng metrics lỗi/latency vẫn tốt: cần golden eval trong CI, canary eval và đánh giá mẫu traffic thực.

### 4.3 Debug theo trace
- trace_id chậm: {trace["traceID"]}.
- Tổng thời gian trace: {total/1000:.3f} ms.
- Span LLM: {chat["operationName"]}, {chat["duration"]/1000:.3f} ms, {chat["duration"]/total:.1%} tổng trace.
- trace_id lỗi: {e["error"]["traceID"]}; span có tag error và exception event.
- Dữ liệu span gốc và log khớp ID: [trace-evidence.json](reports/trace-evidence.json).

Log tương ứng trace chậm:
```json
{json.dumps(e["slow_log"],ensure_ascii=False)}
```

Log tương ứng trace lỗi:
```json
{json.dumps(e["error_log"],ensure_ascii=False)}
```
Trace JSON gốc có event exception với exception.type, exception.message và exception.stacktrace; ảnh Jaeger hiển thị span lỗi và response 503.
"""
if (ROOT/"benchmark-results/scale_1_stats.csv").exists():
    rows=[]
    for n in (1,3):
        data=list(csv.DictReader((ROOT/f"benchmark-results/scale_{n}_stats.csv").open(encoding="utf-8")))
        # Compare the endpoint being assessed, excluding /health.
        d=next(x for x in data if x["Name"]=="/ask")
        rows.append([n,f'{float(d["Requests/s"]):.2f}',d["50%"],d["95%"],d["99%"],d["Failure Count"]])
    scaling=table(["Instances","/ask RPS","p50 ms","p95 ms","p99 ms","Failures"],rows)
    scaling+="\n\nMỗi lượt 100 users, ramp 10 users/s, chạy 2 phút; bảng lấy dòng /ask, không gộp /health. Xem file CSV gốc ở benchmark-results/.\n"
    scaling+=("Số đo 1→3 instance: /ask RPS 60.26→59.91, p95 250→220 ms. Throughput chưa tăng, p95 giảm nhẹ; một lượt đo với mock ngẫu nhiên chưa đủ kết luận cải thiện có ý nghĩa thống kê. Cần tăng tải tới khi một instance bão hòa và đo lặp. Độ chậm cố ý của LLM vẫn còn. Số container đã được kiểm tra và lưu trong reports/scale_1_instances.json và reports/scale_3_instances.json. Locust dùng --no-deps để không thay số replica. "
             "Locust có think time 0.5–2 giây nên tải là closed-loop, không bảo đảm RPS tăng gấp ba. "
             "Mỗi lượt có sai số do mock ngẫu nhiên và tài nguyên runner dùng chung.")
write("BENCHMARK_REPORT.md",f"""# Benchmark & Observability Report — Day 14

**Họ tên:** CanXuanNghia
**Ngày chạy:** 26/11/2026 (Asia/Saigon)
**Môi trường CP7:** {env["platform"]}, Python {env["python"]}, {env["cpu_count"]} logical CPU; HTTP loopback, một process uvicorn. Không dùng Docker cho CP7.

## 1. SLO
| SLI | SLO | Lý do |
|---|---|---|
| p95 /ask | ≤ 500 ms | Ngưỡng của load_test.py cho agent mock nhỏ |
| Error rate /ask | ≤ 2% | Ngưỡng load test; mock mặc định có 1% lỗi |
| Golden accuracy | ≥ 85%, không regression | Gate CI; sau sửa KB kiểm thêm ngưỡng 100% |

Đây là ngưỡng mục tiêu, không phải khẳng định mọi lượt đều đạt.
Eval tắt MOCK_ERROR_RATE và MOCK_SLOW_RATE để tách chất lượng khỏi lỗi hạ tầng. Load test giữ lỗi mặc định 0.01.
Mỗi lượt load có 300 request sau warm-up. v1 và v2 ban đầu dùng KB nguyên bản tại commit 83e677f; v2 cuối dùng KB đã sửa.
Hai bản golden_dataset.jsonl và check_production_ready.py không đổi.

## 2. Benchmark hiệu năng
### 2.1 Concurrency
{concurrency}

Nguồn: reports/load_v2_c*.json. p50/p95/p99 chỉ tính trên response 200 theo script gốc; error rate tính trên mọi request.
Throughput không tuyến tính: từ concurrency 50 lên 100, RPS còn giảm, p95 tăng mạnh.
Đây là một lượt đo trên Windows đang dùng chung máy với ứng dụng khác; chưa đủ bằng chứng kết luận nút thắt là CPU hay event loop.
Cần lặp thử, đo CPU, queue và client overhead trước khi quy nguyên nhân cụ thể.
Lượt c1 có 7 lỗi trên 300 request, vượt SLO 2% dù xác suất lỗi cấu hình là 1%; mẫu nhỏ có dao động.

### 2.2 Tail latency
{tails}

Nguồn: reports/load_v2_slow_*.json, cùng concurrency 20.
p99 nhạy với số ít request chậm; slow rate 0.1 còn đẩy p95 lên vùng chậm. Average trộn nhiều request nhanh với ít request chậm nên che trải nghiệm nhóm cuối.
Dùng percentile và error rate cùng nhau; không thay p99 bằng trung bình.

## 3. Chất lượng và chi phí
{quality}

{missing}

Bổ sung hai entry HPA và JWT vào KNOWLEDGE_BASE của cả develop và production; giữ nguyên evaluator và golden dataset.
v2 tăng token do retrieval, nhưng cost/câu đúng thấp hơn v1 vì nhiều câu đúng hơn.
Latency mock có ngẫu nhiên nên không diễn giải chênh lệch p95 giữa hai lượt như một cải tiến hiệu năng chắc chắn.
Cost là giá mô phỏng của mock, không phải hoá đơn LLM thật.

CI ở .github/workflows/lab.yml gọi run_eval.py --min-accuracy 0.85 --baseline reports/eval_v2.json.
Exit 1 làm job fail. Muốn chặn merge trên GitHub, cần đặt job production là required status check trong branch ruleset; workflow tự nó không bật chính sách đó.

## 4. Observability
{obs}

## 5. Scaling
{scaling}

## 6. Kết luận
1. Average không mô tả được tail latency: cần percentile và error budget.
2. So chi phí với số câu đúng giúp thấy lợi ích retrieval; golden eval bắt lỗi chất lượng mà dashboard hạ tầng không thấy.
3. Metric xác định hiện tượng, trace chỉ ra bước chậm, log trace_id giúp nối bằng chứng.

Nếu vận hành thật: thêm queue depth, time-to-first-token, retry count, budget remaining và eval chất lượng theo phiên bản.
Không dùng câu hỏi, user_id hay request_id làm Prometheus label.
""")
check=(R/"production-readiness-linux.txt").read_text(encoding="utf-8")
checklist=check[check.index("  📋 Checklist Deliverable"):]
http_summary=""
if (R/"exercise-http-evidence.json").exists():
    http=read("exercise-http-evidence.json")
    chosen=[x for x in http if x["exercise"] in ("1.2 query request","1.2 JSON mismatch","4.1 missing key","4.1 correct key","4.2 no JWT","4.3 authenticated request 1","4.3 authenticated request 11")]
    http_summary="\n\n".join(f"**{d['exercise']}**\n\n```http\nHTTP {d['status']}\n{d['response_body']}\n```" for d in chosen)
images="Chưa lấy được số đo image Part 2."
if (R/"docker-image-sizes.json").exists():
    sizes=read("docker-image-sizes.json")
    images=f'Develop: {sizes["develop"]/1024**2:.2f} MiB; production: {sizes["advanced"]/1024**2:.2f} MiB; giảm {sizes["reduction_percent"]:.2f}% so với develop. Nguồn: reports/docker-image-sizes.json (byte inspect thực).'
write("MISSION_ANSWERS.md",f"""# Day 14 — Mission Answers

## Part 1: Localhost vs Production
### Exercise 1.1 — Anti-patterns
1. Hardcode API key: {ref("01-localhost-vs-production/develop/app.py","OPENAI_API_KEY =")}. Secret có thể nằm vĩnh viễn trong lịch sử Git.
2. Hardcode connection string chứa password: {ref("01-localhost-vs-production/develop/app.py","DATABASE_URL =")}.
3. Debug luôn bật: {ref("01-localhost-vs-production/develop/app.py","DEBUG = True")}.
4. Log API key bằng print: {ref("01-localhost-vs-production/develop/app.py",'Using key:')}; log aggregator cũng làm lộ key.
5. Chỉ bind localhost: {ref("01-localhost-vs-production/develop/app.py",'host="localhost"')}; container/cloud không nhận traffic bên ngoài.
6. Port 8000 cố định thay vì env PORT; reload=True không thích hợp production.
7. Thiếu /health và /ready để nền tảng quyết định restart hoặc route traffic.
8. Không có lifespan cleanup và cơ chế quản lý cấu hình.

### Exercise 1.2 — Chạy bản develop
Gọi POST /ask?question=Hello trả 200. Gửi JSON như ví dụ cũ trả 422 vì hàm nhận query param.
Output thật: [exercise-http-evidence.txt](reports/exercise-http-evidence.txt).
Bản này chạy được chưa có nghĩa là production-ready.

### Exercise 1.3 — So sánh
| Tính năng | Develop | Production mẫu | Ý nghĩa |
|---|---|---|---|
| Config | Literal trong app.py | Dataclass đọc os.getenv trong config.py | Cùng code chạy ở nhiều môi trường, không commit key |
| Health/readiness | Thiếu | /health và /ready | Phân biệt restart process và tạm ngừng traffic |
| Logging | print, lộ secret | Có cấu trúc và field ngữ cảnh | Dễ tìm kiếm; cần json.dumps/formatter chuẩn để escape |
| Shutdown | Không cleanup | Lifespan startup/shutdown | Đóng tài nguyên sau khi drain request |
| Network | localhost, port cố định | 0.0.0.0 và settings.port | Nhận traffic container, theo port platform |

Ví dụ sửa port: {ref("01-localhost-vs-production/production/config.py","port: int")}.
Lưu ý code mẫu logging dùng format JSON và message có thể đã json.dumps gây lồng quote; Part 6 dùng JsonFormatter chuẩn để tránh lỗi này.

## Part 2: Docker
### Exercise 2.1
1. Base image develop: python:3.11, từ 02-docker/develop/Dockerfile.
2. Working directory: /app.
3. COPY requirements.txt trước source để pip layer dùng cache khi chỉ sửa code; thay requirements mới phải cài lại.
4. CMD cung cấp command/argument mặc định, docker run có thể thay. ENTRYPOINT định nghĩa executable; argument docker run thường được nối vào nó. Dạng exec giúp truyền signal trực tiếp.

### Exercise 2.2–2.3
Build từ gốc repo vì đường dẫn COPY tính theo build context.
Builder cài compiler/dependencies; runtime chỉ mang package và source cần thiết, bỏ build tools.
Multi-stage không tự bảo đảm nhỏ: nếu copy thừa hoặc dependencies lớn thì image vẫn lớn.
{images}
Kết quả HTTP container: reports/docker-basic-http.txt. Image Part 6 được checker đo 56 MB theo định dạng script, không dùng số đó để thay số image Part 2.

### Exercise 2.4
```mermaid
flowchart LR
    Client --> Nginx
    Nginx --> Agent
    Agent --> Redis
    Agent --> Qdrant
```
Stack có agent, Redis, Qdrant và Nginx cùng network internal. depends_on với health condition giúp khởi động đúng thứ tự.
Đây là sơ đồ dịch vụ cấu hình; mock agent mẫu chưa thực hiện đầy đủ truy vấn Redis/Qdrant.
HTTP qua Nginx: reports/part2-nginx.txt.

## Part 3: Cloud Deployment
### Exercise 3.1/3.2
Đã deploy public tại https://day14-production-agent-haua.onrender.com với Redis trên Render. Bốn lệnh CP6 đạt 200/200/401/200; xem reports/public-deployment.json và screenshots/.
Cấu hình chuẩn bị trong 06-lab-complete/render.yaml; xem [DEPLOYMENT.md](DEPLOYMENT.md).
Criterion 12 của checker xác nhận config; public-deployment.json bổ sung bằng chứng endpoint cloud thực.

Railway dùng TOML chọn Dockerfile builder, healthcheckPath và restart policy; Redis là service được tạo và nối REDIS_URL riêng.
Render Blueprint dùng YAML mô tả cả web Docker và Key Value, kết nối REDIS_URL bằng fromService, AGENT_API_KEY dùng generateValue.
Render đường dẫn Docker tính từ repo root; Blueprint Path chọn 06-lab-complete/render.yaml. Không nhập secret vào code.

### Exercise 3.3 — Cloud Run
cloudbuild.yaml chạy pip + pytest trước; test thành công mới build Docker image gắn COMMIT_SHA và latest.
Bước tiếp theo push image lên registry rồi gcloud run deploy ở asia-southeast1.
Deploy đặt tài nguyên, timeout, min/max instances và inject secret từ Secret Manager.
service.yaml mô tả Knative Service, concurrency 80, autoscaling 1–10 và liveness /health, startup /ready.
Đây là mô tả file mẫu; chưa chạy GCP. File pipeline mẫu và service.yaml là hai cách deploy, không tự bảo đảm mọi setting được đồng bộ.

## Part 4: API Security
### Exercise 4.1–4.3 — HTTP thực tế
{http_summary}

Output đầy đủ response và header: [exercise-http-evidence.txt](reports/exercise-http-evidence.txt).
Lấy JWT bằng POST /auth/token với tài khoản demo student/demo123, giữ token trong process rồi gửi Bearer; không ghi JWT vào bài.
Sau 10 request hợp lệ, bản production mẫu trả 429; request bị chặn không gọi LLM.
Bản API-key mẫu trả 403 nếu sai key; Part 6 dùng 401 cho cả thiếu/sai theo hợp đồng chấm.

### Exercise 4.4 — Cost guard
Kiểm tra budget trước LLM; tính input/output tokens theo bảng giá mô phỏng rồi cộng usage sau request.
Part 6 dùng Redis daily/monthly keys theo UTC và INCRBYFLOAT trong transaction, chia sẻ giữa workers, ngày/tháng mới có key mới.
Rate limit bảo vệ tốc độ/sức tải, cost guard bảo vệ tổng ngân sách. Request ít nhưng prompt dài vẫn tốn nhiều tiền.
Giới hạn: check trước và ghi cost sau chưa reserve chi phí của các request đồng thời; có thể vượt budget bằng lượng đang in-flight.
Nếu dùng LLM thật cần reserve upper bound atomically và settle theo usage trả từ provider; token ở bài này chỉ là ước lượng của mock.

## Part 5: Scaling & Reliability
### Exercise 5.1–5.3
/health là liveness: process còn sống; /ready là readiness: dependency sẵn sàng.
Redis hỏng thì /health vẫn 200, /ready 503 và /ask 503; tránh vòng restart vô ích do lỗi dependency.
Uvicorn ngừng nhận request mới, drain request rồi chạy lifespan cleanup khi SIGTERM. Không ghi đè signal handler của nó.
Bằng chứng SIGTERM thực tế Linux trong reports/production-readiness-linux.txt: request vẫn 200, exit 0; docker stop 0.6 giây.

### Exercise 5.4–5.5
RAM thuộc riêng từng worker/container: request tiếp theo có thể tới instance khác và mất history hoặc quota.
Redis chia sẻ session, sorted-set quota và budget cho các instance.
Chạy docker compose -p k5-day14-scaling up -d --build --scale agent=3 rồi test_stateless.py.
Bằng chứng: reports/part5-stateless.txt. Script gửi 5 câu chung session, đọc lại history, không tự tắt instance.
Graceful shutdown dùng để rolling update: stop instance cũ sau khi bỏ khỏi traffic, chờ drain rồi thay instance mới.

## Part 6: Final Project
Các module trong 06-lab-complete/app/ đã được triển khai. Rate limiter dùng Lua nguyên tử và thời gian Redis để tránh race giữa workers.
API key so sánh constant-time, key trong Redis được băm SHA-256; request log không chứa key/câu hỏi.
Compose Redis có AOF + volume; Docker dùng hai stage, non-root, HEALTHCHECK và exec uvicorn nghe PORT.
Môi trường kiểm tra: GitHub Actions Ubuntu 26.04, Python 3.11.18, Docker 29.4.2.
Nguồn: [workflow run](https://github.com/xuannghia2/K5-L3B-DAY14-CanXuanNghia-2A202603805-Deployment-Benchmark-Observability/actions/runs/45785321467).
Script chấm và golden dataset giữ nguyên. Đã chạy thêm integration test cạnh tranh 30 request, chỉ 5 được nhận, reload vẫn bị 429.

```text
{checklist}
```

## AI log
- Công cụ: OpenAI Codex.
- Yêu cầu: đọc README/RULES/CHECKPOINTS/SUBMISSION/RUBRIC; triển khai TODO Part 6, metric độ dài câu hỏi, sửa KB HPA/JWT, viết CI và tài liệu bài nộp.
- Kết quả: code/config và scripts tái chạy, load/eval JSON, kết quả checker Linux; không sửa script chấm hay golden dataset.
- Kiểm tra do agent thực hiện: 28 static checks, API HTTP thực, 7 lượt load 300 requests, eval v1/v2/fixed, full checker Linux 43/43 và integration tests Redis.
- Người học cần tự đọc code, chạy lại và giải thích từng tiêu chí, con số trước khi nộp; không khẳng định đã tự thực hiện các bước khi chưa làm.
- Các giá trị đo lấy từ JSON/CSV/log thật; cloud đã được triển khai và kiểm chứng, mô tả ở DEPLOYMENT.md.
""")
print("Wrote MISSION_ANSWERS.md and BENCHMARK_REPORT.md")
