# TikTok Video Orchestrator

Hệ thống điều phối video TikTok tự động: nhận webhook video mới từ kênh YouTube → phân tích & cắt video dài bằng Gemini AI → upload lên Cloudflare R2 → phân phối đến profile TikTok phù hợp qua VPS endpoint.

## Kiến trúc

```
YouTube Webhook → Django API → Celery Queue ─┬─ split (video dài)
                                              └─ distribute (video ngắn)
                                                     │
                                              ┌──────┘
                                              ▼
                                        VPS /api/upload-profile
```

## Stack

| Thành phần | Công nghệ |
|---|---|
| Web framework | Django 5.x + Django REST Framework |
| Task queue | Celery 5.x + Redis |
| Database | PostgreSQL 16 |
| Object storage | Cloudflare R2 (S3-compatible) |
| AI analysis | Google Gemini (highlight detection) |
| Video download | yt-dlp |
| Video cutting | FFmpeg (hardsub + speed adjustment) |

## Yêu cầu hệ thống

- **Python** 3.12+
- **Docker** & Docker Compose
- **FFmpeg** (được cài tự động trong Docker image)

Hoặc chạy local không Docker:

- Python 3.12+
- PostgreSQL 16
- Redis 7
- FFmpeg

## Cài đặt nhanh (Docker)

```bash
# 1. Clone repo
git clone git@github.com:tungvt93/tiktok-orchestrator.git
cd tiktok-orchestrator

# 2. Tạo file .env từ mẫu
cp .env.example .env

# 3. Sửa các biến môi trường trong .env
#    - SECRET_KEY: sinh key ngẫu nhiên
#    - DB_PASSWORD: mật khẩu PostgreSQL
#    - R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY: Cloudflare R2 credentials
#    - R2_PUBLIC_DOMAIN: public domain của R2 bucket (dạng https://pub-xxx.r2.dev)

# 4. Build và chạy container
docker compose up -d --build

# 5. Chạy migration
docker compose exec web python manage.py migrate

# 6. Kiểm tra health
curl http://localhost:8000/api/health/
```

## Cài đặt local (không Docker)

```bash
# 1. Tạo virtual environment
python -m venv venv
source venv/bin/activate

# 2. Cài dependencies
pip install -r requirements.txt

# 3. Cấu hình .env — DB_HOST=localhost, REDIS_URL=redis://localhost:6379/0, ...

# 4. Chạy migration
python manage.py migrate

# 5. Tạo superuser (cho Django Admin)
python manage.py createsuperuser

# 6. Chạy development server
python manage.py runserver

# 7. Chạy Celery worker (terminal khác)
celery -A config.celery worker --loglevel=info --concurrency=4

# 8. Chạy Celery Beat (terminal khác)
celery -A config.celery beat --loglevel=info
```

## Biến môi trường

### Django

| Key | Mặc định | Mô tả |
|---|---|---|
| `SECRET_KEY` | — | Django secret key **(bắt buộc)** |
| `DEBUG` | `False` | Bật debug mode |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Danh sách host được phép |

### Database

| Key | Mặc định | Mô tả |
|---|---|---|
| `DB_NAME` | `tiktok_orchestrator` | Tên database |
| `DB_USER` | `tiktok_user` | User PostgreSQL |
| `DB_PASSWORD` | — | Mật khẩu PostgreSQL |
| `DB_HOST` | `localhost` | Host PostgreSQL |
| `DB_PORT` | `5432` | Port PostgreSQL |

### Redis & Celery

| Key | Mặc định | Mô tả |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection (general) |
| `CELERY_BROKER_URL` | `redis://localhost:6379/1` | Celery message broker |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/2` | Celery result backend |

### Cloudflare R2

| Key | Mặc định | Mô tả |
|---|---|---|
| `R2_ENDPOINT` | — | S3 API endpoint (`https://<account-id>.r2.cloudflarestorage.com`) |
| `R2_ACCESS_KEY_ID` | — | R2 Access Key ID |
| `R2_SECRET_ACCESS_KEY` | — | R2 Secret Access Key |
| `R2_BUCKET_NAME` | `tiktok-clips` | Tên R2 bucket |
| `R2_PUBLIC_DOMAIN` | — | Public domain của bucket (`https://pub-xxx.r2.dev`) |

## Services chạy trong Docker Compose

| Service | Port | Mô tả |
|---|---|---|
| `web` | 8000 | Django development server |
| `worker` | — | Celery worker (xử lý split + distribute) |
| `beat` | — | Celery Beat (lịch cron) |
| `db` | 5433 | PostgreSQL 16 |
| `redis` | 6379 | Redis 7 |

## API Endpoints

### Webhook nhận video mới

```
POST /api/upload_new_video
Content-Type: application/json

{
    "channel_id": "UCxxxxxxxxxxxxxx",
    "video_id": "dQw4w9WgXcQ",
    "is_short": false,
    "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"  // optional
}
```

**Response:** `202 Accepted` — video được enqueue vào Celery để xử lý.

- `is_short: true` → gửi thẳng vào `distribute_video`
- `is_short: false` → gửi vào `split_and_distribute_video` (Gemini phân tích → FFmpeg cắt → upload R2 → distribute từng clip con)
- Gọi lại với `video_id` đã tồn tại → `200 OK` (idempotent)

### Health check

```
GET /api/health/
```

**Response:**
```json
{
    "status": "healthy",
    "checks": {
        "database": "ok",
        "redis": "ok"
    }
}
```

## Celery Tasks

| Task | Mô tả |
|---|---|
| `split_and_distribute_video` | Tải video → Gemini phân tích → FFmpeg cắt → Upload R2 → Enqueue distribute từng clip |
| `distribute_video` | Tìm profile TikTok phù hợp → Gọi VPS upload (có semaphore + retry) |
| `reset_daily_video_counters` | Reset `videos_today` cho tất cả profile (00:00 hàng ngày) |
| `reset_gemini_usage_counters` | Reset `daily_usage_count` cho Gemini API key (00:03 hàng ngày) |
| `cleanup_r2_daily` | Xóa toàn bộ clip cũ trên R2 (00:06 hàng ngày) |

## Django Admin

Truy cập `/admin/` để quản lý các model:

- **Topic** — Danh mục chủ đề (gắn với YouTube Channel và TikTok Profile)
- **YouTube Channel** — Kênh YouTube nguồn (gắn với Topic)
- **VPS** — Thông tin kết nối VPS (host, API endpoint, API key)
- **TikTok Profile** — Profile TikTok đích (gắn với VPS + Topic, cấu hình `daily_video_limit`)
- **Gemini API Key** — Quản lý API key Gemini (có usage counter, round-robin)
- **Video** — Theo dõi trạng thái video (pending → splitting → split/processing → uploaded/failed)

## Luồng xử lý video

### Video ngắn (is_short = true)

```
Webhook → Video(pending) → distribute_video
                                │
                    find_best_profile(topic)
                                │
                    acquire VPS semaphore
                                │
                    POST /api/upload-profile → VPS upload TikTok
                                │
                    release VPS semaphore
                                │
                    Video(uploaded)
```

### Video dài (is_short = false)

```
Webhook → Video(pending) → split_and_distribute_video
                                │
                    yt-dlp download video
                                │
                    Gemini analyze (tìm highlight)
                                │
                    FFmpeg cut clips (hardsub + speed 1.2x)
                                │
                    Upload từng clip lên R2
                                │
                    Tạo Video child records (video_id_part1, ...)
                                │
                    Enqueue distribute_video cho từng child
                                │
                    Video parent → status=split
```

## Semaphore VPS

Mỗi VPS bị giới hạn 1 upload đồng thời (Redis Lua script). Nếu VPS đang bận, task sẽ retry sau 60 giây. Điều này tránh việc nhiều profile trên cùng 1 VPS bị upload chồng lấn gây lỗi.

## Cloudflare R2

### Tại sao cần R2?

Sau khi cắt video trên orchestrator host, các file MP4 cần được VPS tải về để upload lên TikTok. R2 hoạt động như bộ đệm trung gian:

1. Orchestrator upload clip lên R2 → nhận public URL
2. Gửi URL đó cho VPS qua API `/api/upload-profile`
3. VPS tải clip từ R2 về rồi upload lên TikTok

### Cleanup

Hàng ngày lúc 00:06, Celery Beat chạy task xóa toàn bộ object trong R2 bucket để giữ storage trong free tier 10GB.

### Free tier (hàng tháng)

| Hạng mục | Giới hạn |
|---|---|
| Storage | 10 GB |
| Class A (upload) | 1 triệu requests |
| Class B (download) | 10 triệu requests |
| Delete | Miễn phí |
| Egress | Miễn phí |
