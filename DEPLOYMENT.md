# Deployment — Day 14

## Trạng thái
Code agent đã PASS 12/12 trên GitHub Actions Linux. Đã triển khai agent và Redis trên Render Free; cả bốn kiểm tra public đều PASS.
Public URL: https://day14-production-agent-haua.onrender.com. Bằng chứng: reports/public-deployment.json; screenshots/dashboard.png (Render Live), running.png (/health), test.png (/ready).

## Render Blueprint đã chuẩn bị
1. Đăng nhập https://dashboard.render.com và chọn New → Blueprint, kết nối repo bài làm.
2. Branch main; Blueprint Path: `06-lab-complete/render.yaml`.
3. Kiểm tra web service và Key Value đều plan `free`, rồi deploy.
4. Blueprint tạo AGENT_API_KEY bằng generateValue; REDIS_URL lấy connectionString của day14-state.
5. Đợi service healthy, copy URL HTTPS. Không ghi API key vào báo cáo, Git hay ảnh.
6. Chạy kiểm tra bên dưới và chụp dashboard/service/test vào screenshots/.

Nguồn: [Render Blueprint specification](https://render.com/docs/blueprint-spec) và [Blueprint setup](https://render.com/docs/infrastructure-as-code).
Free Key Value không lưu bền dữ liệu khi chính Redis bị restart; state vẫn được chia sẻ khi agent scale/restart. Gói free phù hợp thực hành, không bảo đảm độ bền production.
Tài khoản có thể cần xác minh theo yêu cầu nền tảng; không bật gói trả phí.

## Biến môi trường
PORT do Render cấp; ENVIRONMENT=production; AGENT_API_KEY được sinh tự động; REDIS_URL nối Key Value;
RATE_LIMIT_PER_MINUTE=10; DAILY_BUDGET_USD=1; MONTHLY_BUDGET_USD=10.
LOG_LEVEL mặc định INFO, giá mock đọc PRICE_INPUT_PER_1K và PRICE_OUTPUT_PER_1K.

## Tự kiểm tra public
Thiết lập BASE và AGENT_API_KEY trong terminal bằng giá trị từ dashboard, không paste key vào chat:

```bash
python scripts/check_public_deployment.py
```

Script đọc BASE/AGENT_API_KEY từ env và chỉ ghi status, không ghi key.
Mong đợi /health=200, /ready=200, POST /ask thiếu key=401, POST /ask có key=200.
Lưu output thật vào reports/public-deployment.json; sau đó cập nhật mục Public URL và chụp ảnh.

## Public URL
https://day14-production-agent-haua.onrender.com

## Railway thay thế
Chọn root directory 06-lab-complete, config railway.toml tại thư mục đó.
Tạo thêm Redis, đặt REDIS_URL bằng biến tham chiếu service Redis, tạo AGENT_API_KEY ngẫu nhiên trong dashboard.
Không dùng app ví dụ Part 3 thay cho agent Part 6.

## Chạy lại kiểm tra Part 6 trên Linux
```bash
cd 06-lab-complete
pip install -r requirements.txt
python check_production_ready.py
```

GitHub Actions đã cấu hình chạy lệnh này với Docker và Redis thật; xem reports/production-readiness-linux.txt.
