"""Distribution logic — selects the best TikTok profile for a video by topic."""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.core.models.tiktok_profile import TikTokProfile
from apps.core.services.config import get_config


def find_best_profile(topic, exclude_profile_ids=None):
    """
    Find the best available TikTok profile using atomic DB-level locking
    to prevent race conditions when multiple workers run concurrently.

    Selection criteria (in priority order):
    1. Same topic, is_active=True, VPS.is_active=True
    2. videos_today < daily_video_limit (has remaining capacity)
    3. last_upload_at IS NULL OR (now - last_upload_at) >= upload_cooldown_minutes
    4. Ordered by: last_upload_at ASC NULLS FIRST (true round-robin),
       then videos_today ASC (prefer least-used)
    5. Exclude previously failed profile IDs

    Uses SELECT FOR UPDATE SKIP LOCKED to atomically claim a profile,
    preventing multiple workers from picking the same profile simultaneously.

    Args:
        topic: Topic model instance to match profiles against.
        exclude_profile_ids: Optional list of TikTokProfile UUIDs to skip.

    Returns:
        TikTokProfile instance if a suitable profile is found, None otherwise.
    """
    cooldown_minutes = int(get_config("upload_cooldown_minutes", settings.UPLOAD_COOLDOWN_MINUTES))
    cutoff = timezone.now() - timedelta(minutes=cooldown_minutes)
    today = timezone.now().date()

    with transaction.atomic():
        # Build base queryset: active profiles with remaining capacity
        candidates = (
            TikTokProfile.objects.select_for_update(skip_locked=True)
            .filter(
                topic=topic,
                is_active=True,
                vps__is_active=True,
                videos_today__lt=F("daily_video_limit"),
            )
        )

        if exclude_profile_ids:
            candidates = candidates.exclude(id__in=exclude_profile_ids)

        # True round-robin: always pick the profile that uploaded longest ago
        # (or never uploaded), then by fewest uploads today as tiebreaker
        candidates = candidates.order_by(
            F("last_upload_at").asc(nulls_first=True),
            "videos_today",
        )

        for profile in candidates:
            # Inline fallback: reset daily counter if Celery Beat missed the cron
            if profile.last_upload_at and profile.last_upload_at.date() != today:
                profile.videos_today = 0
                profile.save(update_fields=["videos_today"])

            # If the topic bypasses cooldown, return the profile immediately
            if getattr(topic, "bypass_cooldown", False):
                return profile

            # Check cooldown — skip profiles that uploaded too recently
            if profile.last_upload_at is None or profile.last_upload_at <= cutoff:
                return profile

    return None
