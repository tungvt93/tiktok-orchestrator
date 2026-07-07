"""Distribution logic — selects the best TikTok profile for a video by topic."""
from datetime import timedelta

from django.db.models import F
from django.utils import timezone

from apps.core.models.tiktok_profile import TikTokProfile


def find_best_profile(topic, exclude_profile_ids=None):
    """
    Find the best TikTok profile to upload a video to.

    Selection criteria (in priority order):
    1. Same topic, is_active=True, VPS.is_active=True
    2. videos_today < daily_video_limit (has remaining capacity)
    3. Ordered by: videos_today ASC, last_upload_at ASC NULLS FIRST
    4. First profile with: last_upload_at IS NULL
       OR (now - last_upload_at) >= 10 minutes
    5. Exclude previously failed profile IDs (retry with different profile)

    Args:
        topic: Topic model instance to match profiles against.
        exclude_profile_ids: Optional list of TikTokProfile UUIDs to skip
                             (profiles that already failed for this video).

    Returns:
        TikTokProfile instance if a suitable profile is found, None otherwise.
    """
    candidates = TikTokProfile.objects.filter(
        topic=topic,
        is_active=True,
        vps__is_active=True,
        videos_today__lt=F("daily_video_limit"),
    )

    if exclude_profile_ids:
        candidates = candidates.exclude(id__in=exclude_profile_ids)

    # Prioritize: fewest uploads today, then oldest (or never) upload
    candidates = candidates.order_by(
        "videos_today",
        F("last_upload_at").asc(nulls_first=True),
    )

    cutoff = timezone.now() - timedelta(minutes=10)
    today = timezone.now().date()

    for profile in candidates:
        # Inline fallback: reset daily counter if Celery Beat missed the cron
        if profile.last_upload_at and profile.last_upload_at.date() != today:
            profile.videos_today = 0
            profile.save(update_fields=["videos_today"])

        # Check 10-minute gap between uploads
        if profile.last_upload_at is None or profile.last_upload_at <= cutoff:
            return profile

    return None
