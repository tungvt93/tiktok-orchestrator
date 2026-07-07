"""Celery task — split a long video, create child records, enqueue distribution."""
import logging
import os

from celery import shared_task

from apps.core.models.gemini_api_key import GeminiAPIKey
from apps.core.models.video import Video
from apps.core.services.downloader import download_video
from apps.core.services.gemini_key_manager import (
    NoAvailableKeyError,
    get_available_key,
    increment_usage,
)
from apps.core.services.splitter import analyze_video_for_highlights
from apps.core.services.cutter import cut_video_clips
from apps.core.services.r2_storage import upload_clip

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=6, default_retry_delay=120)
def split_and_distribute_video(self, video_id: str):
    """
    Download a long YouTube video, split it into short clips, and distribute.

    Pipeline:
    1. Download video from YouTube (yt-dlp)
    2. Select Gemini API key from pool
    3. Analyze video → highlight timestamps
    4. Cut clips with FFmpeg
    5. Create child Video records
    6. Enqueue distribute_video for each child
    7. Mark original video as SPLIT
    """
    try:
        video = Video.objects.get(id=video_id)
    except Video.DoesNotExist:
        logger.warning("Video %s deleted before splitting could start.", video_id)
        return

    # Mark as splitting
    video.status = Video.Status.SPLITTING
    video.save(update_fields=["status"])

    downloaded_path = None

    try:
        # Step 1: Download video
        video.video_url = video.video_url
        downloaded_path = download_video(video.video_url)

        # Step 2: Get Gemini API key
        try:
            gemini_key = get_available_key()
        except NoAvailableKeyError:
            video.status = Video.Status.FAILED
            video.error_log = "No Gemini API key available"
            video.save(update_fields=["status", "error_log"])
            return

        # Step 3: Analyze with Gemini
        highlights = analyze_video_for_highlights(
            video_path=downloaded_path,
            api_key=gemini_key.api_key,
            num_clips=5,
            min_clip_duration=8.0,
            max_clip_duration=10.0,
        )

        if not highlights:
            video.status = Video.Status.FAILED
            video.error_log = "Gemini returned no highlight clips"
            video.save(update_fields=["status", "error_log"])
            return

        # Mark key as used
        increment_usage(gemini_key)

        # Step 4: Cut clips
        processed_clips = cut_video_clips(
            video_path=downloaded_path,
            clips=highlights,
            speed=1.2,
        )

        if not processed_clips:
            video.status = Video.Status.FAILED
            video.error_log = "FFmpeg failed to cut any clips"
            video.save(update_fields=["status", "error_log"])
            return

        # Step 5: Upload clips to R2 and create child Video records
        from apps.core.tasks.distribute import distribute_video

        child_count = 0
        for clip in processed_clips:
            clip_path = clip.get("output_path")
            if not clip_path:
                logger.warning("Clip #%d has no output_path, skipping.", clip["clip_index"])
                continue

            # Upload to Cloudflare R2
            try:
                r2_url = upload_clip(clip_path)
            except Exception as r2_exc:
                logger.error("R2 upload failed for clip #%d: %s", clip["clip_index"], r2_exc)
                continue

            clip_id = f"{video.video_id}_part{clip['clip_index']}"
            child = Video.objects.create(
                video_id=clip_id,
                video_url=r2_url,
                youtube_channel=video.youtube_channel,
                status=Video.Status.PENDING,
                parent_video=video,
                part_number=clip["clip_index"],
            )
            child_count += 1

            # Clean up local clip file
            try:
                os.remove(clip_path)
            except OSError:
                pass

            # Step 6: Enqueue distribution for each child
            distribute_video.delay(str(child.id))

        # Step 7: Mark original as split
        video.status = Video.Status.SPLIT
        video.save(update_fields=["status"])

        logger.info(
            "Video %s split into %d child clips, distribution enqueued.",
            video.video_id, child_count,
        )

    except Exception as exc:
        logger.exception("Split task failed for video %s: %s", video.video_id, exc)

        if self.request.retries < self.max_retries:
            video.status = Video.Status.PENDING  # will retry
            video.error_log = f"Split attempt {self.request.retries + 1} failed: {exc}"
            video.save(update_fields=["status", "error_log"])
            raise self.retry(exc=exc)
        else:
            video.status = Video.Status.FAILED
            video.error_log = f"Split failed after {self.max_retries} attempts: {exc}"
            video.save(update_fields=["status", "error_log"])

    finally:
        # Cleanup downloaded source file
        if downloaded_path:
            try:
                os.remove(downloaded_path)
            except OSError:
                pass
