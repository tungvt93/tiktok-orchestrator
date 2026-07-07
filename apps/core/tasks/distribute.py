"""Celery task for video distribution to TikTok profiles."""
import logging

from celery import shared_task
from django.utils import timezone

from apps.core.models.video import Video
from apps.core.services.distributor import find_best_profile
from apps.core.services.vps_client import upload_to_vps
from apps.core.services.vps_semaphore import acquire, release

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=12, default_retry_delay=300)
def distribute_video(self, video_id, tried_profile_ids=None):
    """
    Distribute a video to the best available TikTok profile.

    Retry strategy:
    - max_retries=12, default_retry_delay=300 (5 minutes)
    - Total retry window: 12 × 5 min = 1 hour
    - Each retry excludes previously failed profile IDs

    Args:
        video_id: UUID string of the Video to distribute.
        tried_profile_ids: List of TikTokProfile UUID strings that have
                           already been tried and failed for this video.
    """
    if tried_profile_ids is None:
        tried_profile_ids = []

    try:
        video = Video.objects.get(id=video_id)
    except Video.DoesNotExist:
        # Video was deleted — nothing to do
        return

    channel = video.youtube_channel

    # Channel has no topic assigned yet — retry later
    if channel.topic is None:
        if self.request.retries >= self.max_retries:
            video.status = Video.Status.FAILED
            video.error_log = "Channel has no topic assigned after max retries"
            video.save(update_fields=["status", "error_log"])
            return
        raise self.retry(kwargs={"tried_profile_ids": tried_profile_ids})

    # Find the best matching profile
    profile = find_best_profile(channel.topic, exclude_profile_ids=tried_profile_ids)

    if profile is None:
        # No suitable profile found
        if self.request.retries >= self.max_retries:
            video.status = Video.Status.FAILED
            video.error_log = (
                f"No available profile after {self.max_retries} retries. "
                f"Tried profile IDs: {tried_profile_ids}"
            )
            video.save(update_fields=["status", "error_log"])
            return
        raise self.retry(kwargs={"tried_profile_ids": tried_profile_ids})

    # Attempt upload via VPS (with semaphore)
    video.status = Video.Status.PROCESSING
    video.save(update_fields=["status"])

    # Acquire VPS concurrency slot
    vps_id = str(profile.vps.id)
    if not acquire(vps_id):
        logger.info("VPS %s at capacity, retrying in 60s for video %s.", vps_id, video.video_id)
        video.status = Video.Status.PENDING
        video.save(update_fields=["status"])
        raise self.retry(kwargs={"tried_profile_ids": tried_profile_ids}, countdown=60)

    try:
        success, error = upload_to_vps(
            profile.vps,
            profile.profile_name,
            video.video_url,
        )
    finally:
        release(vps_id)

    if success:
        # Update profile counters
        profile.videos_today += 1
        profile.last_upload_at = timezone.now()
        profile.save(update_fields=["videos_today", "last_upload_at"])

        # Mark video as uploaded
        video.status = Video.Status.UPLOADED
        video.uploaded_to_profile = profile
        video.uploaded_at = timezone.now()
        video.save(update_fields=["status", "uploaded_to_profile", "uploaded_at"])
    else:
        # Track the failed profile and retry
        tried_profile_ids.append(str(profile.id))
        video.retry_count = self.request.retries + 1
        video.error_log = f"[Profile {profile.profile_name}] {error}"
        video.status = Video.Status.PENDING
        video.save(update_fields=["retry_count", "error_log", "status"])

        raise self.retry(kwargs={"tried_profile_ids": tried_profile_ids})
