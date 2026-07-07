"""Celery task for daily counter reset + Beat schedule."""
from celery import shared_task
from celery.schedules import crontab

from apps.core.models.gemini_api_key import GeminiAPIKey
from apps.core.models.tiktok_profile import TikTokProfile
from apps.core.services.r2_storage import cleanup_old_clips


@shared_task
def reset_daily_video_counters():
    """
    Reset videos_today to 0 for all TikTok profiles.

    Runs daily at midnight via Celery Beat cron.
    Fallback: distributor.find_best_profile() also detects stale counters
    inline when last_upload_at.date() != today.
    """
    updated = TikTokProfile.objects.exclude(videos_today=0).update(videos_today=0)
    return f"Reset {updated} profile counters"


@shared_task
def reset_gemini_usage_counters():
    """
    Reset daily_usage_count to 0 for all Gemini API keys.

    Runs daily at midnight via Celery Beat cron, just after profile counters.
    This ensures all keys get a fresh quota window each day.
    """
    updated = GeminiAPIKey.objects.exclude(daily_usage_count=0).update(daily_usage_count=0)
    return f"Reset {updated} Gemini API key usage counters"


@shared_task
def cleanup_r2_daily():
    """
    Delete all clip files from R2 to free storage.

    Runs daily before midnight reset. Clips are safe to delete after 24h
    because the distribute task retry window is at most 1 hour.
    """
    deleted = cleanup_old_clips()
    return f"Deleted {deleted} clips from R2"


# Celery Beat schedule — registered via app.conf.beat_schedule
# in the Celery app config, or importable here for the beat scheduler.
BEAT_SCHEDULE = {
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
