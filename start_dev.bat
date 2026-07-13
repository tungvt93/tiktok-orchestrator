@echo off
title TikTok Orchestrator - Dev Environment

echo ==================================================
echo 1. Starting Docker services (db, redis, beat)...
echo ==================================================
docker compose up -d db redis beat

echo.
echo ==================================================
echo 2. Setting environment variables for local services...
echo ==================================================
set DB_HOST=127.0.0.1
set DB_PORT=5433
set REDIS_URL=redis://127.0.0.1:6379/0
set CELERY_BROKER_URL=redis://127.0.0.1:6379/1
set CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/2

echo.
echo ==================================================
echo 3. Starting Celery Worker (Local) in a new window...
echo ==================================================
start "Celery Worker (Local - Watchdog)" cmd /k "cd /d %~dp0 && watchdog_worker.bat"

echo.
echo ==================================================
echo 4. Starting Django Web Server (Local) in a new window...
echo ==================================================
start "Django Web Server (Local)" cmd /k ".\venv\Scripts\activate && python manage.py runserver"

echo.
echo ==================================================
echo All services have been initiated!
echo You can access the web server at: http://127.0.0.1:8000
echo ==================================================
pause
