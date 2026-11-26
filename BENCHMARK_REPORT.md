# Benchmark & Observability Report — Day 14

**Họ tên:** CanXuanNghia
**Ngày chạy:** 26/11/2026 (Asia/Saigon)
**Môi trường CP7:** Windows-10-10.0.26300-SP0, Python 3.11.18, 12 logical CPU; HTTP loopback, một process uvicorn. Không dùng Docker cho CP7.

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
| Concurrency | RPS | p50 ms | p95 ms | p99 ms | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.26 | 199.8 | 233.6 | 1699.4 | 2.33% | FAIL |
| 10 | 34.03 | 195.6 | 245.5 | 1703.3 | 0.33% | PASS |
| 50 | 47.75 | 307.5 | 2745.1 | 3859.2 | 0.00% | FAIL |
| 100 | 41.58 | 857.5 | 5308.1 | 5475.1 | 1.00% | FAIL |

Nguồn: reports/load_v2_c*.json. p50/p95/p99 chỉ tính trên response 200 theo script gốc; error rate tính trên mọi request.
Throughput không tuyến tính: từ concurrency 50 lên 100, RPS còn giảm, p95 tăng mạnh.
Đây là một lượt đo trên Windows đang dùng chung máy với ứng dụng khác; chưa đủ bằng chứng kết luận nút thắt là CPU hay event loop.
Cần lặp thử, đo CPU, queue và client overhead trước khi quy nguyên nhân cụ thể.
Lượt c1 có 7 lỗi trên 300 request, vượt SLO 2% dù xác suất lỗi cấu hình là 1%; mẫu nhỏ có dao động.

### 2.2 Tail latency
| MOCK_SLOW_RATE | avg ms | p95 ms | p99 ms |
|---|---|---|---|
| 0 | 199.3 | 235.2 | 262.6 |
| 0.03 | 254.3 | 273.3 | 1715.3 |
| 0.1 | 364.2 | 1710.3 | 1733.6 |

Nguồn: reports/load_v2_slow_*.json, cùng concurrency 20.
p99 nhạy với số ít request chậm; slow rate 0.1 còn đẩy p95 lên vùng chậm. Average trộn nhiều request nhanh với ít request chậm nên che trải nghiệm nhóm cuối.
Dùng percentile và error rate cùng nhau; không thay p99 bằng trung bình.

## 3. Chất lượng và chi phí
| Chỉ số | v1 | v2 ban đầu | v2 sửa KB |
|---|---|---|---|
| Accuracy | 1/23 (4.35%) | 21/23 (91.30%) | 23/23 (100.00%) |
| Avg tokens / câu | 57.3 | 109.0 | 113.7 |
| Tổng cost USD | 0.000406 | 0.000759 | 0.00079 |
| Cost / câu đúng USD | 0.00040635 | 3.616e-05 | 3.436e-05 |
| Quality gate | FAIL | PASS | PASS |
| p95 ms | 181.3 | 227.3 | 237.0 |

| ID | Keywords thiếu | Cách sửa |
|---|---|---|
| security-02 | token, hết hạn, chữ ký | Bổ sung tài liệu JWT |
| scaling-03 | cpu, memory, custom metrics | Bổ sung tài liệu Kubernetes HPA |

Bổ sung hai entry HPA và JWT vào KNOWLEDGE_BASE của cả develop và production; giữ nguyên evaluator và golden dataset.
v2 tăng token do retrieval, nhưng cost/câu đúng thấp hơn v1 vì nhiều câu đúng hơn.
Latency mock có ngẫu nhiên nên không diễn giải chênh lệch p95 giữa hai lượt như một cải tiến hiệu năng chắc chắn.
Cost là giá mô phỏng của mock, không phải hoá đơn LLM thật.

CI ở .github/workflows/lab.yml gọi run_eval.py --min-accuracy 0.85 --baseline reports/eval_v2.json.
Exit 1 làm job fail. Muốn chặn merge trên GitHub, cần đặt job production là required status check trong branch ruleset; workflow tự nó không bật chính sách đó.

## 4. Observability
### 4.1 Dashboard và trace
- [Grafana có tải](screenshots/grafana-dashboard.png)
- [Trace chậm](screenshots/jaeger-slow-trace.png)
- [Trace lỗi](screenshots/jaeger-error-trace.png)
- [Hai alert firing đồng thời](screenshots/prometheus-alert-firing.png)

Ảnh và dữ liệu lấy từ GitHub Actions Linux, cùng stack Compose, không phải từ máy Windows.
Snapshot Prometheus: [reports/prometheus-snapshot.json](reports/prometheus-snapshot.json).
p95 = 1899.1 ms; avg = 587.2 ms.
Chênh lệch thể hiện tail latency; tải fault injection dùng để tạo ảnh không phải lượt scale benchmark.
Requests/s theo instance tại snapshot:
| Instance | Requests/s |
|---|---|
| 172.18.0.8:8000 | 25.4 |
| 172.18.0.5:8000 | 25.38 |
Ảnh chaos dùng 2 instance được Prometheus scrape ở thời điểm này; đây là thí nghiệm riêng với hai lượt scaling ở mục 5.
Nginx chia traffic tương đối đều nếu các giá trị trên gần nhau; chưa dùng một snapshot để kết luận cho mọi thời điểm.
Input tokens gồm system prompt + retrieved context + câu hỏi, nên thường lớn hơn output ngắn.
Gọi /metrics qua Nginx trả HTTP 404: config chặn đường này; Prometheus scrape trực tiếp từng agent.

### 4.2 Chaos
Chạy đồng thời MOCK_ERROR_RATE=0.2 và MOCK_SLOW_RATE=0.3 trên cùng stack, giữ tải 100 users.
Thời gian đo từ lúc bắt đầu recreate service đến lần poll thấy firing (poll 3 giây, có độ phân giải 3 giây):
| Alert | Thời gian firing s |
|---|---|
| AgentHighErrorRate | 81.9 |
| AgentHighLatencyP95 | 142.0 |
Bằng chứng đầy đủ gồm mọi mẫu inactive/pending/firing: [chaos-alerts.json](reports/chaos-alerts.json).
Error rate và p95 phản ánh hai lỗi tương ứng. Thời gian firing gồm scrape, evaluation, cửa sổ rate và điều kiện for.
Không chạy thử thay model, pause instance hay v1 trong stack này; không ghi số cho những thí nghiệm chưa chạy.
Đổi v1 làm giảm chất lượng nhưng metrics lỗi/latency vẫn tốt: cần golden eval trong CI, canary eval và đánh giá mẫu traffic thực.

### 4.3 Debug theo trace
- trace_id chậm: 8018abb9d6006bec1359f9c667fbbd79.
- Tổng thời gian trace: 1717.762 ms.
- Span LLM: chat mock-llm-small, 1699.895 ms, 99.0% tổng trace.
- trace_id lỗi: d8f79e38e1fffc3ce1df6527734c15a2; span có tag error và exception event.
- Dữ liệu span gốc và log khớp ID: [trace-evidence.json](reports/trace-evidence.json).

Log tương ứng trace chậm:
```json
{"ts": "2026-11-26T09:12:49.721379+00:00", "level": "INFO", "service": "observable-agent", "instance": "00f3b35eea9a", "event": "http_request", "trace_id": "8018abb9d6006bec1359f9c667fbbd79", "span_id": "d34cacd96c14e46a", "request_id": "55d93dcc42c6", "method": "POST", "route": "/ask", "status": 200, "ms": 1717.5}
```

Log tương ứng trace lỗi:
```json
{"ts": "2026-11-26T09:14:37.326886+00:00", "level": "INFO", "service": "observable-agent", "instance": "8f8cb8afe8de", "event": "http_request", "trace_id": "d8f79e38e1fffc3ce1df6527734c15a2", "span_id": "eb0b67952ebf5fbd", "request_id": "f52f18392ba5", "method": "POST", "route": "/ask", "status": 503, "ms": 856.6}
```
Trace JSON gốc có event exception với exception.type, exception.message và exception.stacktrace; ảnh Jaeger hiển thị span lỗi và response 503.


## 5. Scaling
| Instances | /ask RPS | p50 ms | p95 ms | p99 ms | Failures |
|---|---|---|---|---|---|
| 1 | 60.26 | 190 | 250 | 1700 | 77 |
| 3 | 59.91 | 190 | 220 | 1700 | 74 |

Mỗi lượt 100 users, ramp 10 users/s, chạy 2 phút; bảng lấy dòng /ask, không gộp /health. Xem file CSV gốc ở benchmark-results/.
Số đo 1→3 instance: /ask RPS 60.26→59.91, p95 250→220 ms. Throughput chưa tăng, p95 giảm nhẹ; một lượt đo với mock ngẫu nhiên chưa đủ kết luận cải thiện có ý nghĩa thống kê. Cần tăng tải tới khi một instance bão hòa và đo lặp. Độ chậm cố ý của LLM vẫn còn. Số container đã được kiểm tra và lưu trong reports/scale_1_instances.json và reports/scale_3_instances.json. Locust dùng --no-deps để không thay số replica. Locust có think time 0.5–2 giây nên tải là closed-loop, không bảo đảm RPS tăng gấp ba. Mỗi lượt có sai số do mock ngẫu nhiên và tài nguyên runner dùng chung.

## 6. Kết luận
1. Average không mô tả được tail latency: cần percentile và error budget.
2. So chi phí với số câu đúng giúp thấy lợi ích retrieval; golden eval bắt lỗi chất lượng mà dashboard hạ tầng không thấy.
3. Metric xác định hiện tượng, trace chỉ ra bước chậm, log trace_id giúp nối bằng chứng.

Nếu vận hành thật: thêm queue depth, time-to-first-token, retry count, budget remaining và eval chất lượng theo phiên bản.
Không dùng câu hỏi, user_id hay request_id làm Prometheus label.
