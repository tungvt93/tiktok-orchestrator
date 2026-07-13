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
        # Step 1: Download video and get its title
        video.video_url = video.video_url
        downloaded_path, video_title = download_video(video.video_url)

        # Step 2 & 3: Bypassed Gemini analysis per requirement. Get duration and determine split count.
        from apps.core.services.splitter import get_video_duration
        total_duration = get_video_duration(downloaded_path)
        
        # Calculate split count N (3, 2, or 1) based on speed multiplier (1.2)
        # to ensure each rendered video is > 60 seconds (i.e. original segment > 72 seconds)
        speed = 1.2
        target_min_original_duration = 60 * speed  # 72.0 seconds
        
        if total_duration >= 3 * target_min_original_duration:
            num_parts = 3
        elif total_duration >= 2 * target_min_original_duration:
            num_parts = 2
        else:
            num_parts = 1
            
        segment_len = total_duration / num_parts

        logger.info(
            "Video %s duration is %.1fs. Splitting into %d parts (target segment > %.1fs).",
            video.video_id, total_duration, num_parts, target_min_original_duration
        )

        highlights = []
        for i in range(1, num_parts + 1):
            start = (i - 1) * segment_len
            end = total_duration if i == num_parts else i * segment_len
            title_suffix = f" - Phần {i}" if num_parts > 1 else ""
            highlights.append({
                "clip_index": i,
                "title": f"{video_title}{title_suffix}",
                "start_seconds": round(start, 2),
                "end_seconds": round(end, 2),
            })

        # Step 4, 5 & 6: Cut, upload to R2, and queue distribution sequentially per clip
        from apps.core.tasks.distribute import distribute_video
        import random

        child_count = 0
        child_videos = []

        for idx, highlight in enumerate(highlights):
            # Cut single clip
            processed = cut_video_clips(
                video_path=downloaded_path,
                clips=[highlight],
                speed=1.2,
            )

            if not processed:
                logger.warning("FFmpeg failed to cut clip #%d.", highlight["clip_index"])
                continue

            clip = processed[0]
            clip_path = clip.get("output_path")
            if not clip_path:
                logger.warning("Clip #%d has no output_path, skipping.", clip["clip_index"])
                continue

            # Upload to Cloudflare R2 immediately after cutting
            try:
                r2_url = upload_clip(clip_path)
            except Exception as r2_exc:
                logger.error("R2 upload failed for clip #%d: %s", clip["clip_index"], r2_exc)
                try:
                    os.remove(clip_path)
                except OSError:
                    pass
                continue

            clip_id = f"{video.video_id}_part{clip['clip_index']}"
            child, created = Video.objects.get_or_create(
                video_id=clip_id,
                defaults={
                    "video_url": r2_url,
                    "youtube_channel": video.youtube_channel,
                    "status": Video.Status.PENDING,
                    "parent_video": video,
                    "part_number": clip["clip_index"],
                }
            )
            if not created:
                child.video_url = r2_url
                child.save(update_fields=["video_url"])
            child_videos.append(child)
            child_count += 1

            # Clean up local clip file
            try:
                os.remove(clip_path)
            except OSError:
                pass

            # Enqueue distribution with staggered countdowns (5-7 minutes apart)
            if idx == 0:
                distribute_video.delay(str(child.id))
                logger.info("Enqueued Part 1 distribution (video %s) immediately.", child.id)
            elif idx == 1:
                # Part 2: 5-7 minutes delay (300 to 420 seconds)
                delay = random.randint(300, 420)
                logger.info("Scheduling Part 2 distribution (video %s) in %d seconds.", child.id, delay)
                distribute_video.apply_async(args=[str(child.id)], countdown=delay)
            elif idx == 2:
                # Part 3: 10-14 minutes delay (600 to 840 seconds)
                delay = random.randint(600, 840)
                logger.info("Scheduling Part 3 distribution (video %s) in %d seconds.", child.id, delay)
                distribute_video.apply_async(args=[str(child.id)], countdown=delay)

        if child_count == 0:
            video.status = Video.Status.FAILED
            video.error_log = "FFmpeg failed to cut or upload any clips"
            video.save(update_fields=["status", "error_log"])
            return

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
