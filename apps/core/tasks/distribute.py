"""Celery task for video distribution to TikTok profiles."""
import logging

from celery import shared_task
from django.utils import timezone

from apps.core.models.video import Video
from apps.core.services.distributor import find_best_profile
from apps.core.services.vps_client import upload_to_vps
from apps.core.services.vps_semaphore import acquire, release

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=30, default_retry_delay=30)
def distribute_video(self, video_id, tried_profile_ids=None):
    """
    Distribute a video to the best available TikTok profile.

    Retry strategy:
    - max_retries=30, default_retry_delay=30 (30 seconds)
    - Total retry window: 30 × 30s = 15 minutes
    - Each retry excludes previously failed profile IDs

    Args:
        video_id: UUID string of the Video to distribute.
        tried_profile_ids: List of TikTokProfile UUID strings that have
                           already been tried and failed for this video.
    """
    if tried_profile_ids is None:
        tried_profile_ids = []

    from django.db import transaction

    try:
        with transaction.atomic():
            video = Video.objects.select_for_update().get(id=video_id)
            if video.status in [Video.Status.UPLOADED, Video.Status.PROCESSING]:
                logger.info("Video %s is already %s, skipping duplicate distribution.", video.video_id, video.status)
                return

            channel = video.youtube_channel
            # Channel has no topic assigned yet — retry later
            if channel.topic is None:
                if self.request.retries >= self.max_retries:
                    video.status = Video.Status.FAILED
                    video.error_log = "Channel has no topic assigned after max retries"
                    video.save(update_fields=["status", "error_log"])
                    return
                # We will raise retry outside the transaction or roll back
                # Let's handle retry outside the atomic block
                raise_retry_topic = True
            else:
                raise_retry_topic = False

            if not raise_retry_topic:
                # Claim the video immediately
                video.status = Video.Status.PROCESSING
                video.save(update_fields=["status"])
    except Video.DoesNotExist:
        # Video was deleted — nothing to do
        return

    if raise_retry_topic:
        raise self.retry(kwargs={"tried_profile_ids": tried_profile_ids})

    # Find the best matching profile
    profile = find_best_profile(channel.topic, exclude_profile_ids=tried_profile_ids)

    if profile is None:
        # Reset status to PENDING before retrying
        if self.request.retries >= self.max_retries:
            video.status = Video.Status.FAILED
            video.error_log = (
                f"No available profile after {self.max_retries} retries. "
                f"Tried profile IDs: {tried_profile_ids}"
            )
            video.save(update_fields=["status", "error_log"])
            return
        
        video.status = Video.Status.PENDING
        video.save(update_fields=["status"])
        raise self.retry(kwargs={"tried_profile_ids": tried_profile_ids})

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
        # Track the failed profile
        tried_profile_ids.append(str(profile.id))
        video.retry_count = self.request.retries + 1
        video.error_log = f"[Profile {profile.profile_name}] {error}"
        
        # Mark as FAILED immediately without retrying
        video.status = Video.Status.FAILED
        video.save(update_fields=["retry_count", "error_log", "status"])

        # Clean up local video file
        import os
        try:
            if os.path.exists(video.video_url):
                os.remove(video.video_url)
        except OSError:
            pass
        
        # Enqueue next pending video
        next_video = Video.objects.filter(status=Video.Status.PENDING).exclude(id=video.id).order_by("created_at").first()
        if next_video:
            distribute_video.delay(str(next_video.id))
        
        return
