"""Celery application config for TikTok Video Orchestrator."""
import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("tiktok_orchestrator")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.imports = (
    "apps.core.tasks.distribute",
    "apps.core.tasks.reset",
    "apps.core.tasks.split",
    "apps.core.tasks.fetch_videos",
)

# Periodic tasks (Celery Beat)
app.conf.beat_schedule = {
    "reset-daily-video-counters": {
        "task": "apps.core.tasks.reset.reset_daily_video_counters",
        "schedule": crontab(hour=0, minute=0),
    },
    "reset-gemini-usage-counters": {
        "task": "apps.core.tasks.reset.reset_gemini_usage_counters",
        "schedule": crontab(hour=0, minute=3),
    },
    "cleanup-r2-daily": {
        "task": "apps.core.tasks.reset.cleanup_r2_daily",
        "schedule": crontab(hour=0, minute=6),
    },
}
